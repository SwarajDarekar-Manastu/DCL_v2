"""Typed access to ``pipeline_config`` (file 05 §4.6): versioned, append-only, non-secret settings.

Reads take the highest version of a key (``v_config_current``). Writes append a version.
The ``gate.*`` keys are seeded from ``config/gate.yaml``: on first start only the missing keys
are written; ``reseed`` appends a version wherever the YAML differs. The gate reads the table,
never the YAML (file 02 §4).

``sanity_ranges`` is one key holding S5's ``config/sanity_ranges.yaml`` mapping, seeded the same way.

CLI: ``python -m backend.postgres.pipeline_config seed-config [--reseed]`` (gate + sanity ranges + answer
external-search defaults;
``seed-gate`` seeds the gate only). Uses DCL_DATABASE_URL.
"""

import re
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, JsonValue, NonNegativeInt, PositiveInt, TypeAdapter, ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.postgres.enums import AuditEntityType, Route
from backend.postgres.models import AuditEvent, PipelineConfig
from backend.sync.gate import GateConfig

CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"
GATE_YAML = CONFIG_DIR / "gate.yaml"
SANITY_RANGES_YAML = CONFIG_DIR / "sanity_ranges.yaml"
SANITY_RANGES = "sanity_ranges"
GATE_PREFIX = "gate."
DOWNLOAD_SCOPE = "sync.download_scope"
PROCESSING_SCOPE = "processing.scope"
FORMULA_ENRICHMENT_MAX = "routes.A1.formula_enrichment_max"
FORMULA_ENRICHMENT_DEFAULT = 30  # about 30 s per formula on CPU (DECISIONS 2026-10-23)
MISSING = object()
_ABSENT = object()


class ConfigMissing(LookupError):
    pass


def get(session: Session, key: str, default: Any = MISSING) -> Any:
    value = session.scalar(
        select(PipelineConfig.value)
        .where(PipelineConfig.key == key)
        .order_by(PipelineConfig.version.desc())
        .limit(1)
    )
    if value is None:
        if default is MISSING:
            raise ConfigMissing(f"pipeline_config has no value for {key!r}")
        return default
    return value


def get_prefix(session: Session, prefix: str) -> dict[str, Any]:
    """Current value of every key starting with ``prefix``."""
    latest = (
        select(PipelineConfig.key, func.max(PipelineConfig.version).label("version"))
        .where(PipelineConfig.key.startswith(prefix))
        .group_by(PipelineConfig.key)
        .subquery()
    )
    rows = session.execute(
        select(PipelineConfig.key, PipelineConfig.value).join(
            latest, (PipelineConfig.key == latest.c.key) & (PipelineConfig.version == latest.c.version)
        )
    )
    return dict(rows.all())


def set_value(session: Session, key: str, value: Any, updated_by: str, description: str | None = None) -> int:
    """Append a version of ``key``; returns the new version number."""
    current = session.scalar(select(func.max(PipelineConfig.version)).where(PipelineConfig.key == key)) or 0
    session.add(
        PipelineConfig(
            key=key, version=current + 1, value=value, updated_by=updated_by, description=description
        )
    )
    session.flush()
    return current + 1


def seed_gate(
    session: Session, gate: Mapping[str, Any], updated_by: str = "seed", reseed: bool = False
) -> list[str]:
    """Write ``gate.<name>`` keys from the gate YAML mapping; returns the keys written."""
    GateConfig.from_mapping(gate)  # refuse a file the gate could not use
    current = get_prefix(session, GATE_PREFIX)
    written = []
    for name, value in gate.items():
        key = GATE_PREFIX + name
        if key in current and (not reseed or current[key] == value):
            continue
        set_value(session, key, value, updated_by, description="seeded from config/gate.yaml")
        written.append(key)
    return written


def load_gate_yaml(path: Path = GATE_YAML) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def seed_key(
    session: Session, key: str, value: Any, source: str, updated_by: str = "seed", reseed: bool = False
) -> bool:
    """First start: write ``key`` if missing; re-seed: append a version if the value differs."""
    current = get(session, key, default=_ABSENT)
    if current is not _ABSENT and (not reseed or current == value):
        return False
    set_value(session, key, value, updated_by, description=f"seeded from {source}")
    return True


def seed_sanity_ranges(session: Session, reseed: bool = False, path: Path = SANITY_RANGES_YAML) -> bool:
    return seed_key(
        session,
        SANITY_RANGES,
        yaml.safe_load(path.read_text(encoding="utf-8")),
        "config/sanity_ranges.yaml",
        reseed=reseed,
    )


ROUTE_DEFAULTS: dict[str, Any] = {FORMULA_ENRICHMENT_MAX: FORMULA_ENRICHMENT_DEFAULT}


def seed_route_defaults(session: Session) -> list[str]:
    """Route settings with a decided default (first start only; an admin's later value stays)."""
    return [
        key for key, value in ROUTE_DEFAULTS.items() if seed_key(session, key, value, "DECISIONS 2026-10-23")
    ]


ANSWER_DEFAULTS: dict[str, Any] = {
    "answer.external_allowed_groups": ["dcl-external-search"],
    "answer.external_search_enabled": True,  # kill switch for external search (S2, Lead 2026-10-22)
}


def seed_answer_defaults(session: Session) -> list[str]:
    """The answer engine's external-search keys (file 05 key list). First start only, never re-seeded:
    ``--reseed`` must not turn the kill switch back on after an admin turned it off.
    ``answer.proprietary_terms`` is written only after the user confirms S5's draft, not here."""
    return [key for key, value in ANSWER_DEFAULTS.items() if seed_key(session, key, value, "Lead 2026-10-22")]


def sanity_ranges(session: Session) -> dict[str, Any]:
    """S5's sanity ranges mapping (``version``, ``ranges[]``) as seeded; raises if not seeded."""
    return get(session, SANITY_RANGES)


def gate_config(session: Session) -> GateConfig:
    values = get_prefix(session, GATE_PREFIX)
    if not values:
        raise ConfigMissing(
            "the gate.* keys are not seeded; run `python -m backend.postgres.pipeline_config seed-gate`"
        )
    return GateConfig.from_mapping({key.removeprefix(GATE_PREFIX): value for key, value in values.items()})


def download_scope(session: Session) -> list[str]:
    """``sync.download_scope``; empty or missing means everything."""
    return list(get(session, DOWNLOAD_SCOPE, default=[]) or [])


def processing_scope(session: Session) -> list[str]:
    """``processing.scope``; empty or missing means everything."""
    return list(get(session, PROCESSING_SCOPE, default=[]) or [])


# ---------------------------------------------------------------- Settings API (file 08 §3.2)

_LIST = TypeAdapter(list[str])
_BOOL = TypeAdapter(bool)
_TEXT = TypeAdapter(str)
_JSON = TypeAdapter(JsonValue)
_TEXT_MAP = TypeAdapter(dict[str, str])
_CRON = re.compile(r"^\S+( \S+){4}$")
MODEL_PRICES = "models.prices"


class PriceSpec(BaseModel):
    """USD per million tokens for one model (``models.prices``; the gateway client's ``ModelPrice``)."""

    input_per_mtok: float = Field(ge=0)
    output_per_mtok: float = Field(ge=0)
    cached_per_mtok: float = Field(default=0.0, ge=0)


# Exact keys of file 05 §4.6 with the shape their readers expect. Secrets and endpoints are never keys.
KEYS: dict[str, TypeAdapter] = {
    DOWNLOAD_SCOPE: _LIST,
    PROCESSING_SCOPE: _LIST,
    "sync.download_concurrency": TypeAdapter(PositiveInt),
    "sync.daily_delta_cron": _TEXT,
    "cloud_allowed_roots": _LIST,
    "sources.origin_defaults": TypeAdapter(dict[str, Literal["internal", "external_kept"]]),
    "translation.mode": TypeAdapter(Literal["none", "enrichment_only", "full"]),
    "translation.full_for": _JSON,
    "flags.severity_overrides": TypeAdapter(dict[str, dict[str, Literal["HARD", "SOFT"]]]),
    "flags.strict_mode": _BOOL,
    "cloud.vertex_project": _TEXT,
    "cloud.region": _TEXT,
    "cloud.daily_token_budget": TypeAdapter(NonNegativeInt),
    SANITY_RANGES: TypeAdapter(dict[str, JsonValue]),
    "critical_field_patterns": _JSON,
    "report_json_schemas": _JSON,
    "answer.external_allowed_groups": _LIST,
    "answer.proprietary_terms": _LIST,
    "answer.external_search_enabled": _BOOL,
    "routes.A1.ocr_engine_by_script": _TEXT_MAP,
    MODEL_PRICES: TypeAdapter(dict[str, PriceSpec]),
    FORMULA_ENRICHMENT_MAX: TypeAdapter(NonNegativeInt),
}
FAMILIES = ("thresholds.", "chunking.", "models.")  # free-form JSON values per family
TELEMETRY_PREFIX = "telemetry."  # Route C NormalizeConfig fields, numbers
_ROUTE_KEY = re.compile(r"^routes\.([^.]+)\.(enabled|parser_version)$")
GATE_FIELDS = frozenset(f.name for f in fields(GateConfig))


class InvalidConfig(ValueError):
    """``errors`` maps each refused key to the reason; nothing was written."""

    def __init__(self, errors: Mapping[str, str]):
        super().__init__("; ".join(f"{k}: {v}" for k, v in errors.items()))
        self.errors = dict(errors)


class VersionConflict(RuntimeError):
    def __init__(self, key: str, expected: int, actual: int):
        super().__init__(f"{key}: expected version {expected}, current is {actual}")
        self.key, self.expected, self.actual = key, expected, actual


class Change(BaseModel):
    key: str
    value: JsonValue
    expected_version: NonNegativeInt | None = Field(
        default=None, description="the version the editor saw (0 = key absent); a newer one answers 409"
    )


@dataclass(frozen=True)
class Applied:
    key: str
    version: int
    before: Any
    after: Any


def _adapter(key: str) -> TypeAdapter | None:
    if key in KEYS:
        return KEYS[key]
    match = _ROUTE_KEY.match(key)
    if match and match.group(1) in {r.value for r in Route}:
        return _BOOL if match.group(2) == "enabled" else _TEXT
    if key.startswith(FAMILIES) and len(key.split(".", 1)[1]) > 0:
        return _JSON
    return None


def validate_changes(session: Session, changes: Mapping[str, Any]) -> dict[str, Any]:
    """Validated values per key, or ``InvalidConfig`` naming every refused key."""
    from backend.routes.c_telemetry.normalize import NormalizeConfig, sanity_ranges_from

    errors: dict[str, str] = {}
    values: dict[str, Any] = {}
    gate_changes: dict[str, Any] = {}
    for key, value in changes.items():
        if key.startswith(GATE_PREFIX):
            if key.removeprefix(GATE_PREFIX) not in GATE_FIELDS:
                errors[key] = f"unknown gate key; known: {', '.join(sorted(GATE_FIELDS))}"
            else:
                gate_changes[key] = value
            continue
        if key.startswith(TELEMETRY_PREFIX):
            field = key.removeprefix(TELEMETRY_PREFIX)
            if field not in NormalizeConfig.__dataclass_fields__:
                errors[key] = "unknown telemetry key"
            elif isinstance(value, bool) or not isinstance(value, int | float):
                errors[key] = "must be a number"
            else:
                values[key] = value
            continue
        adapter = _adapter(key)
        if adapter is None:
            errors[key] = "unknown key (file 05 §4.6 lists the keys; secrets and endpoints never go here)"
            continue
        try:
            values[key] = adapter.validate_python(value, strict=key != MODEL_PRICES)
            if key == MODEL_PRICES:
                values[key] = {m: spec.model_dump() for m, spec in values[key].items()}
        except ValidationError as exc:
            errors[key] = "; ".join(e["msg"] for e in exc.errors())
            continue
        if key == "sync.daily_delta_cron" and not _CRON.match(values[key]):
            errors[key] = "must be a five-field cron expression"
        elif key == SANITY_RANGES:
            try:
                sanity_ranges_from(values[key])
            except (KeyError, TypeError, ValueError) as exc:
                errors[key] = f"not a sanity_ranges mapping: {exc!r}"
    if gate_changes:
        merged = {k.removeprefix(GATE_PREFIX): v for k, v in get_prefix(session, GATE_PREFIX).items()}
        merged.update({k.removeprefix(GATE_PREFIX): v for k, v in gate_changes.items()})
        try:
            GateConfig.from_mapping(merged)
            values.update(gate_changes)
        except (KeyError, TypeError, ValueError) as exc:
            for key in gate_changes:
                errors[key] = f"the gate refuses this configuration: {exc}"
    if errors:
        raise InvalidConfig(errors)
    return values


def model_prices(session: Session) -> dict[str, Any]:
    """``models.prices`` as the gateway client's ``prices`` argument (``{model: ModelPrice}``); empty when
    unset, so ``cost_estimate`` stays null rather than guessed."""
    from backend.llm_engine.gemini_types import ModelPrice

    raw = get(session, MODEL_PRICES, default={}) or {}
    return {model: ModelPrice(**PriceSpec.model_validate(spec).model_dump()) for model, spec in raw.items()}


def current_entries(session: Session, prefix: str = "") -> list[PipelineConfig]:
    latest = (
        select(PipelineConfig.key, func.max(PipelineConfig.version).label("version"))
        .where(PipelineConfig.key.startswith(prefix))
        .group_by(PipelineConfig.key)
        .subquery()
    )
    return list(
        session.scalars(
            select(PipelineConfig)
            .join(latest, (PipelineConfig.key == latest.c.key) & (PipelineConfig.version == latest.c.version))
            .order_by(PipelineConfig.key)
        )
    )


def history(session: Session, key: str) -> list[PipelineConfig]:
    """Every version of ``key``, newest first."""
    return list(
        session.scalars(
            select(PipelineConfig).where(PipelineConfig.key == key).order_by(PipelineConfig.version.desc())
        )
    )


def _latest(session: Session, key: str) -> PipelineConfig | None:
    rows = history(session, key)
    return rows[0] if rows else None


def apply_changes(
    session: Session,
    changes: Sequence[Change],
    actor: str,
    description: str | None = None,
    action: str = "update",
) -> list[Applied]:
    """Validate the whole batch, then append one version and one ``audit_events`` row per changed key.
    A value equal to the current one is skipped. The caller commits (all or nothing)."""
    keys = [c.key for c in changes]
    if len(set(keys)) != len(keys):
        raise InvalidConfig({k: "appears twice in one batch" for k in keys if keys.count(k) > 1})
    values = validate_changes(session, {c.key: c.value for c in changes})
    applied = []
    for change in changes:
        row = _latest(session, change.key)
        version = row.version if row else 0
        if change.expected_version is not None and change.expected_version != version:
            raise VersionConflict(change.key, change.expected_version, version)
        before = row.value if row else None
        after = values[change.key]
        if row is not None and before == after:
            continue
        new_version = set_value(session, change.key, after, actor, description)
        session.add(
            AuditEvent(
                actor=actor,
                entity_type=AuditEntityType.CONFIG,
                entity_id=change.key,
                action=action,
                before={"version": version, "value": before} if row else None,
                after={"version": new_version, "value": after},
            )
        )
        applied.append(Applied(change.key, new_version, before, after))
    session.flush()
    return applied


def rollback_changes(session: Session, versions: Mapping[str, int]) -> list[Change]:
    """The changes that restore each key's value at ``version`` (as a new version, append-only).
    ``LookupError`` names a key/version that does not exist."""
    changes = []
    for key, version in versions.items():
        value = session.scalar(
            select(PipelineConfig.value).where(PipelineConfig.key == key, PipelineConfig.version == version)
        )
        if value is None:
            raise LookupError(f"{key} has no version {version}")
        changes.append(Change(key=key, value=value))
    return changes


def main(argv: list[str]) -> int:
    import os

    from sqlalchemy import create_engine

    from backend.postgres.session import normalize_url

    if not argv or argv[0] not in ("seed-gate", "seed-config"):
        print(
            "usage: python -m backend.postgres.pipeline_config seed-gate | seed-config [--reseed]",
            file=sys.stderr,
        )
        return 2
    reseed = "--reseed" in argv
    engine = create_engine(normalize_url(os.environ["DCL_DATABASE_URL"]))
    with Session(engine) as session:
        written = seed_gate(session, load_gate_yaml(), reseed=reseed)
        if argv[0] == "seed-config":
            if seed_sanity_ranges(session, reseed=reseed):
                written.append(SANITY_RANGES)
            written += seed_answer_defaults(session)
            written += seed_route_defaults(session)
        session.commit()
    print(f"wrote {len(written)} keys" + (f": {', '.join(written)}" if written else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
