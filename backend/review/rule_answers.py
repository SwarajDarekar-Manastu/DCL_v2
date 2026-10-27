"""Rules that act (user, 2026-10-24, option A): a rule answers a flag the way a person would.

A flag the route raises is checked against the active rules of the answering types for its file (scope and
precedence as in ``rules.resolve``). The first type that speaks to the flag gives its resolution, the same
payload a person's decision stores; the flag becomes ``AUTO_RESOLVED`` with ``resolution_rule_id``, and the
commit applies it as an overlay like any other decision (``indexing/overlays.py``).

A flag a person reopened is never answered again by a rule; it waits for that person. Switching a rule off
opens the flags it answered (``cases.switch_off_rule``) and another active rule may answer them.

Telemetry channel units are never answered here: a ``channel_proposal`` proposes and a person approves
(DECISIONS 2026-10-24). A HARD unit flag is therefore never answered by a rule.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from fnmatch import fnmatchcase
from typing import Any

from pydantic import TypeAdapter
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.dispatcher.contract import Resolution, allowed_actions, subject_key
from backend.postgres.enums import FlagSeverity, FlagStatus, FlagType, RuleOrigin, RuleType
from backend.postgres.models import Document, ReviewFlag, Rule
from backend.review.rules import (
    ColumnUnitBody,
    IgnorePatternBody,
    OriginOverrideBody,
    RuleRecord,
    RuleScope,
    RuleTarget,
    SchemaMappingBody,
    SourceChoiceBody,
    matches,
    parse_body,
    resolve,
)

# The most specific answer first: a named side, a mapping or a unit before "accept this kind of finding".
ANSWERING = (RuleType.SOURCE_CHOICE, RuleType.SCHEMA_MAPPING, RuleType.COLUMN_UNIT, RuleType.IGNORE_PATTERN)
RESOLVED_BY = "rule"
# A flag a person reopened waits for a person: no rule answers it again (undo on one file keeps the rule).
ANSWERABLE = (FlagStatus.OPEN, FlagStatus.IN_PROGRESS)
_RESOLUTION = TypeAdapter(Resolution)


@dataclass(frozen=True)
class ActingRule:
    record: RuleRecord
    body: Any


@dataclass(frozen=True)
class Answer:
    rule_id: uuid.UUID
    resolution: dict[str, Any]


def load_acting(session: Session) -> list[ActingRule]:
    rows = session.scalars(select(Rule).where(Rule.rule_type.in_(ANSWERING), Rule.active.is_(True))).all()
    return [
        ActingRule(
            RuleRecord(
                rule_id=row.rule_id,
                rule_type=RuleType(row.rule_type),
                origin=RuleOrigin(row.origin),
                scope=RuleScope(
                    scope_root=row.scope_root,
                    scope_folder_id=row.scope_folder_id,
                    scope_filename_glob=row.scope_filename_glob,
                    scope_extension=row.scope_extension,
                ),
                precedence=row.precedence,
                created_at=row.created_at,
            ),
            parse_body(RuleType(row.rule_type), row.body),
        )
        for row in rows
    ]


def _names(flag: ReviewFlag) -> list[str]:
    """The column or label names a unit flag is about: the anchor's column, a channel, or the label at the
    end of a prose number's context ("… Test 01: C_F")."""
    evidence, anchor = flag.evidence or {}, flag.anchor or {}
    names = [anchor.get("column"), anchor.get("channel"), evidence.get("channel")]
    context = evidence.get("context") or ""
    if ":" in context:
        names.append(context.rsplit(":", 1)[1])
    return [n.strip() for n in names if n and n.strip()]


def answer(rule_type: RuleType, body: Any, flag: ReviewFlag) -> dict[str, Any] | None:
    """What a rule of ``rule_type`` resolves ``flag`` with, or None when it does not speak to it."""
    flag_type, evidence = FlagType(flag.flag_type), flag.evidence or {}
    if rule_type == RuleType.COLUMN_UNIT:
        assert isinstance(body, ColumnUnitBody)
        if flag_type != FlagType.UNIT_AMBIGUITY or flag.severity != FlagSeverity.SOFT:
            return None
        if any(fnmatchcase(name.casefold(), body.column.casefold()) for name in _names(flag)):
            return {"action": "set_fact_unit", "unit": body.unit}
        return None
    if rule_type == RuleType.SOURCE_CHOICE:
        assert isinstance(body, SourceChoiceBody)
        if (
            flag_type != FlagType.CONFLICT
            or evidence.get("relation", "sources_disagree") != "sources_disagree"
        ):
            return None
        if subject_key(evidence.get("subject")) != subject_key(body.subject):
            return None
        for side, choice in (("a", "A"), ("b", "B")):
            if ((evidence.get(side) or {}).get("label") or "").casefold() == body.prefer.casefold():
                return {"action": "choose_source", "choice": choice}
        return None
    if rule_type == RuleType.SCHEMA_MAPPING:
        assert isinstance(body, SchemaMappingBody)
        if flag_type != FlagType.SCHEMA_UNKNOWN:
            return None
        if evidence.get("kind") == "json_schema" and body.key_to_section:
            return {"action": "map_json_keys", "key_to_section": body.key_to_section}
        if evidence.get("kind") == "array_schema" and body.columns:
            return {"action": "map_columns", "columns": [c.model_dump(mode="json") for c in body.columns]}
        return None
    if rule_type == RuleType.IGNORE_PATTERN:
        assert isinstance(body, IgnorePatternBody)
        if body.flag_type is None or body.flag_type != flag_type:
            return None
        if body.relation and evidence.get("relation", "sources_disagree") != body.relation:
            return None
        if (
            body.subject_contains
            and body.subject_contains.casefold() not in (evidence.get("subject") or "").casefold()
        ):
            return None
        if flag_type in (FlagType.CONFLICT, FlagType.CLOUD_RESTRICTED):
            return {"action": "ignore"}
        if flag_type == FlagType.LOW_CONFIDENCE_EXTRACTION:  # the model's reading stands
            suggested = (flag.suggested_resolution or {}).get("resolution")
            return suggested or None
    return None


def best_answer(rules: list[ActingRule], target: RuleTarget, flag: ReviewFlag) -> Answer | None:
    """The answer of the most specific matching rule of the first answering type that speaks to ``flag``;
    a rule answers only with what the flag allows, the same gate a person's decision passes."""
    allowed = allowed_actions(FlagType(flag.flag_type), flag.anchor, flag.evidence)
    for rule_type in ANSWERING:
        found: dict[uuid.UUID, dict[str, Any]] = {}
        for rule in rules:
            if rule.record.rule_type == rule_type:
                resolution = answer(rule_type, rule.body, flag)
                if resolution is not None and resolution["action"] in allowed:
                    found[rule.record.rule_id] = resolution
        winner = resolve([r.record for r in rules if r.record.rule_id in found], target, rule_type)
        if winner is not None:
            resolution = _RESOLUTION.validate_python(found[winner.rule_id]).model_dump(
                mode="json", exclude_none=True
            )
            return Answer(winner.rule_id, resolution)
    return None


def answer_flags(
    session: Session,
    document: Document,
    flags: list[ReviewFlag],
    rules: list[ActingRule] | None = None,
    now: datetime | None = None,
) -> list[ReviewFlag]:
    """Resolve the open flags of ``document`` that an active rule answers; returns the flags it resolved."""
    from backend.review.proposals import target_of

    rules = load_acting(session) if rules is None else rules
    if not rules:
        return []
    target, _ = target_of(session, document)
    if target is None:
        return []
    resolved = []
    for flag in flags:
        if flag.status not in ANSWERABLE:
            continue
        found = best_answer(rules, target, flag)
        if found is None:
            continue
        flag.status, flag.resolution = FlagStatus.AUTO_RESOLVED, found.resolution
        flag.resolution_rule_id, flag.resolved_by = found.rule_id, RESOLVED_BY
        flag.resolved_at = now or datetime.now(UTC)
        resolved.append(flag)
    return resolved


# ---------------------------------------------------------------- rules that act on the document itself

DOCUMENT_RULES = (RuleType.ORIGIN_OVERRIDE, RuleType.SUPERSESSION)


@dataclass(frozen=True)
class DocumentRules:
    origin: OriginOverrideBody | None = None
    origin_rule_id: uuid.UUID | None = None
    superseded: tuple[uuid.UUID, ...] = ()


def document_rules(session: Session, document: Document) -> DocumentRules:
    """``origin_override``: the most specific matching rule sets the document's origin (and trust tier);
    ``supersession``: every matching rule marks its document superseded by this one."""
    from backend.review.proposals import target_of

    rows = session.scalars(
        select(Rule).where(Rule.rule_type.in_(DOCUMENT_RULES), Rule.active.is_(True))
    ).all()
    if not rows:
        return DocumentRules()
    target, _ = target_of(session, document)
    if target is None:
        return DocumentRules()
    records = [
        RuleRecord(
            rule_id=row.rule_id,
            rule_type=RuleType(row.rule_type),
            origin=RuleOrigin(row.origin),
            scope=RuleScope(
                scope_root=row.scope_root,
                scope_folder_id=row.scope_folder_id,
                scope_filename_glob=row.scope_filename_glob,
                scope_extension=row.scope_extension,
            ),
            precedence=row.precedence,
            created_at=row.created_at,
        )
        for row in rows
    ]
    bodies = {row.rule_id: parse_body(RuleType(row.rule_type), row.body) for row in rows}
    origin = resolve(records, target, RuleType.ORIGIN_OVERRIDE)
    superseded = tuple(
        bodies[r.rule_id].superseded_doc_id
        for r in records
        if r.rule_type == RuleType.SUPERSESSION and matches(r, target)
    )
    return DocumentRules(
        origin=bodies[origin.rule_id] if origin else None,
        origin_rule_id=origin.rule_id if origin else None,
        superseded=superseded,
    )


def json_key_mapping(session: Session, document: Document) -> dict[str, str] | None:
    """The sections of an unknown JSON shape for Route A2 (a mapping changes the parse, so the route reads
    it): the file's own decision first, else the most specific active ``schema_mapping`` rule naming keys."""
    from backend.review.proposals import target_of

    decided = session.scalars(
        select(ReviewFlag)
        .where(
            ReviewFlag.doc_id == document.doc_id,
            ReviewFlag.flag_type == FlagType.SCHEMA_UNKNOWN,
            ReviewFlag.status.in_((FlagStatus.RESOLVED, FlagStatus.AUTO_RESOLVED)),
        )
        .order_by(ReviewFlag.resolved_at.desc())
    )
    for flag in decided:
        if (flag.resolution or {}).get("action") == "map_json_keys":
            return dict(flag.resolution["key_to_section"])
    rules = [
        r
        for r in load_acting(session)
        if r.record.rule_type == RuleType.SCHEMA_MAPPING and r.body.key_to_section
    ]
    target, _ = target_of(session, document) if rules else (None, None)
    if target is None:
        return None
    winner = resolve([r.record for r in rules], target, RuleType.SCHEMA_MAPPING)
    return next(
        (dict(r.body.key_to_section) for r in rules if winner and r.record.rule_id == winner.rule_id), None
    )
