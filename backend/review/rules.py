"""Operator rules and derived maps: one table, one precedence resolver (file 06 §8, file 03 §C.0).

A rule applies to a file when every scope column it sets matches. Among the matching rules
of one ``rule_type`` the winner is decided in this order:

1. the most specific scope: a nearer folder beats a farther ancestor beats no folder; then a
   filename glob; then an extension; then a root; a rule with no scope is global and last;
2. ``origin = operator`` beats the derived origins (cfg, header, config_json, tdms_props);
3. the higher ``precedence``;
4. the newest ``created_at``.

Bodies are typed per ``rule_type``. Operator rules export to YAML for ``config/rules/``.
"""

import uuid
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Any, Literal, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.dispatcher.contract import ColumnMapping
from backend.postgres.enums import AmbientCondition, GaugeOrAbs, Quantity, RuleOrigin, RuleType, SourceOrigin

EXPORT_VERSION = 1


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


# ---------------------------------------------------------------- scope


class RuleScope(_Model):
    """The four scope columns; all null means global."""

    scope_root: str | None = None
    scope_folder_id: str | None = None
    scope_filename_glob: str | None = None
    scope_extension: str | None = None


@dataclass(frozen=True)
class RuleTarget:
    """The file a rule is resolved for. ``folder_ids`` lists the parent folder first, then its ancestors."""

    root_name: str
    folder_ids: Sequence[str]
    file_name: str
    extension: str | None


@dataclass(frozen=True)
class RuleRecord:
    """The ``rules`` columns the resolver needs."""

    rule_id: uuid.UUID
    rule_type: RuleType
    origin: RuleOrigin
    scope: RuleScope
    precedence: int
    created_at: datetime
    active: bool = True


def _extension(value: str | None) -> str | None:
    if not value:
        return None
    return "." + value.casefold().lstrip(".")


def matches(rule: RuleRecord, target: RuleTarget) -> bool:
    scope = rule.scope
    if not rule.active:
        return False
    if scope.scope_root is not None and scope.scope_root != target.root_name:
        return False
    if scope.scope_folder_id is not None and scope.scope_folder_id not in target.folder_ids:
        return False
    if scope.scope_filename_glob is not None and not fnmatchcase(
        target.file_name.casefold(), scope.scope_filename_glob.casefold()
    ):
        return False
    return scope.scope_extension is None or _extension(scope.scope_extension) == _extension(target.extension)


def specificity(rule: RuleRecord, target: RuleTarget) -> tuple[int, bool, bool, bool]:
    """Sort key of a matching rule's scope: higher is more specific."""
    scope = rule.scope
    folder_rank = 0
    if scope.scope_folder_id is not None:
        folder_rank = len(target.folder_ids) - list(target.folder_ids).index(scope.scope_folder_id)
    return (
        folder_rank,
        scope.scope_filename_glob is not None,
        scope.scope_extension is not None,
        scope.scope_root is not None,
    )


def resolve(rules: Iterable[RuleRecord], target: RuleTarget, rule_type: RuleType) -> RuleRecord | None:
    """The one rule of ``rule_type`` that applies to ``target``, or None."""
    candidates = [rule for rule in rules if rule.rule_type == rule_type and matches(rule, target)]
    if not candidates:
        return None
    return max(
        candidates,
        key=lambda rule: (
            specificity(rule, target),
            rule.origin == RuleOrigin.OPERATOR,
            rule.precedence,
            rule.created_at,
        ),
    )


def resolve_where(
    rules: Iterable[RuleRecord], target: RuleTarget, rule_type: RuleType, accept: Callable[[RuleRecord], bool]
) -> RuleRecord | None:
    """Like ``resolve`` but only among rules ``accept`` keeps (for example: the channel_map rules that
    name one raw channel), so a specific rule that is silent about a channel does not hide a broader one."""
    return resolve((rule for rule in rules if accept(rule)), target, rule_type)


# ---------------------------------------------------------------- bodies


class ChannelScaling(_Model):
    """``value = slope * raw + offset`` (LabJack header equations such as ``y = 50*v - 25``)."""

    slope: float
    offset: float = 0.0


class ChannelMapEntry(_Model):
    """One raw channel's mapping: canonical name, quantity, unit, scaling or expression, tag, range."""

    canonical_name: str = Field(min_length=1)
    physical_quantity: Quantity
    unit: str = Field(min_length=1, description="unit of the value after scaling, pint-parsable")
    gauge_or_abs: GaugeOrAbs = GaugeOrAbs.NOT_APPLICABLE
    scaling: ChannelScaling | None = None
    expression: str | None = Field(default=None, description="custom conversion over `val`")
    sensor_tag: str | None = None
    range_min: float | None = None
    range_max: float | None = None
    open_threshold: float | None = Field(
        default=None,
        description="valve_state only: value (after scaling) at which the valve counts as open; default 0.5",
    )

    @model_validator(mode="after")
    def _one_conversion(self) -> Self:
        if self.scaling is not None and self.expression is not None:
            raise ValueError("a channel uses scaling or expression, not both")
        if self.open_threshold is not None and self.physical_quantity != Quantity.VALVE_STATE:
            raise ValueError("open_threshold applies to valve_state channels only")
        return self


class ChannelMapBody(_Model):
    channels: dict[str, ChannelMapEntry] = Field(min_length=1, description="raw channel name → mapping")
    ambient_condition: AmbientCondition | None = None
    ambient_pressure_bar_abs: float | None = None


class UnitMappingBody(_Model):
    """A unit decision for one channel (the SetUnit resolution without ``action``)."""

    channel: str
    unit: str = Field(min_length=1)
    quantity: str
    gauge_or_abs: GaugeOrAbs
    ambient_condition: AmbientCondition | None = None
    ambient_pressure_bar_abs: float | None = None
    expression: str | None = None


class SchemaMappingBody(_Model):
    """Column meanings for an array or headerless table (the MapColumns resolution without ``action``)."""

    columns: list[ColumnMapping] = Field(min_length=1)


class SupersessionBody(_Model):
    superseded_doc_id: uuid.UUID
    reason: str = ""


class IgnorePatternBody(_Model):
    reason: str = Field(min_length=1)


class OriginOverrideBody(_Model):
    source_origin: SourceOrigin
    trust_tier: int | None = Field(default=None, ge=1, le=6)


RULE_BODIES: dict[RuleType, type[_Model]] = {
    RuleType.CHANNEL_MAP: ChannelMapBody,
    RuleType.UNIT_MAPPING: UnitMappingBody,
    RuleType.SCHEMA_MAPPING: SchemaMappingBody,
    RuleType.SUPERSESSION: SupersessionBody,
    RuleType.IGNORE_PATTERN: IgnorePatternBody,
    RuleType.ORIGIN_OVERRIDE: OriginOverrideBody,
}


def parse_body(rule_type: RuleType, body: Mapping[str, Any]) -> _Model:
    return RULE_BODIES[rule_type].model_validate(body)


# ---------------------------------------------------------------- YAML export (config/rules/)


class ExportedRule(_Model):
    """One operator rule in ``config/rules/*.yaml``; a new environment loads it as an operator rule
    (``load_rules_dir``: top-level confirmed files only, never ``config/rules/proposed/``)."""

    rule_type: RuleType
    scope: RuleScope = RuleScope()
    precedence: int = 0
    body: dict[str, Any]
    created_by: str | None = None

    @model_validator(mode="after")
    def _body_matches_type(self) -> Self:
        parse_body(self.rule_type, self.body)
        return self


class RulesFile(_Model):
    """``status = proposed``: drafted (for example by S5 for an SME), never applied until confirmed; a
    confirmation in the Review UI or in writing turns it into an operator rule (Lead ruling 2026-10-22)."""

    version: int = EXPORT_VERSION
    status: Literal["confirmed", "proposed"] = "confirmed"
    rules: list[ExportedRule]


def export_yaml(rules: Iterable[tuple[RuleOrigin, ExportedRule]]) -> str:
    """YAML of the operator rules only; derived rules are rebuilt from their source files."""
    kept = [rule for origin, rule in rules if origin == RuleOrigin.OPERATOR]
    data = RulesFile(rules=kept).model_dump(mode="json", exclude_none=True)
    return yaml.safe_dump(data, sort_keys=False, allow_unicode=True)


def load_yaml(text: str) -> RulesFile:
    return RulesFile.model_validate(yaml.safe_load(text))


def load_rules_dir(directory: Path) -> list[tuple[Path, ExportedRule]]:
    """The operator rules to load: ``*.yaml`` directly in ``directory`` (never subfolders such as
    ``proposed/``), skipping any file whose ``status`` is ``proposed``."""
    loaded: list[tuple[Path, ExportedRule]] = []
    for path in sorted(p for p in directory.glob("*.yaml") if p.is_file()):
        rules_file = load_yaml(path.read_text(encoding="utf-8"))
        if rules_file.status == "confirmed":
            loaded.extend((path, rule) for rule in rules_file.rules)
    return loaded
