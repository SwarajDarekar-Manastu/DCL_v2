"""Rules propose, people approve (DECISIONS 2026-10-24).

A ``channel_proposal`` rule says what the columns of a folder's files probably are. It never answers a flag:
Route C reads only ``channel_map`` rules as answers, and only a person's "Apply" on a file writes one. What a
proposal does is fill in the *suggestion* of the open unit flags of the files it matches, so the reviewer
opens a file with the units already chosen, checks the converted numbers and approves it.

``refresh`` is the one place that derives a flag's suggestion from the active proposals. It runs when a
proposal is created or switched off, after a person approves a file with "also propose", and after Route C
raises its flags, so a halted file always shows what the rules say now (else the pipeline's own hint).
"""

import uuid
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.dispatcher.contract import SetUnit, Suggestion, UnitTelemetryEvidence
from backend.postgres.enums import (
    DocumentSourceRole,
    FlagStatus,
    FlagType,
    RuleOrigin,
    RuleType,
)
from backend.postgres.models import Document, DocumentSource, DriveFolder, ReviewFlag, Rule
from backend.review.rules import ChannelMapBody, RuleRecord, RuleScope, RuleTarget, resolve_where

# Below the 0.9 auto-apply line on purpose: a rule proposes, a person approves (suggest.py).
PROPOSAL_CONFIDENCE = 0.85
OPEN = (FlagStatus.OPEN, FlagStatus.IN_PROGRESS, FlagStatus.REOPENED)


@dataclass(frozen=True)
class Proposals:
    """The active ``channel_proposal`` rules, ready to resolve a channel of a file."""

    records: list[RuleRecord]
    bodies: dict[uuid.UUID, ChannelMapBody]
    made: dict[uuid.UUID, tuple[str, datetime]]  # rule_id -> (created_by, created_at)


def load_proposals(session: Session) -> Proposals:
    rows = session.scalars(
        select(Rule).where(Rule.rule_type == RuleType.CHANNEL_PROPOSAL, Rule.active.is_(True))
    ).all()
    return Proposals(
        records=[
            RuleRecord(
                rule_id=row.rule_id,
                rule_type=RuleType.CHANNEL_PROPOSAL,
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
        ],
        bodies={row.rule_id: ChannelMapBody.model_validate(row.body) for row in rows},
        made={row.rule_id: (row.created_by, row.created_at) for row in rows},
    )


def propose(proposals: Proposals, target: RuleTarget, channel: str) -> tuple[uuid.UUID, Suggestion] | None:
    """The closest proposal that names ``channel`` for this file, as the suggestion a flag would carry."""
    rule = resolve_where(
        proposals.records,
        target,
        RuleType.CHANNEL_PROPOSAL,
        lambda r: channel in proposals.bodies[r.rule_id].channels,
    )
    if rule is None:
        return None
    body = proposals.bodies[rule.rule_id]
    entry = body.channels[channel]
    by, at = proposals.made[rule.rule_id]
    return rule.rule_id, Suggestion(
        resolution=SetUnit(
            channel=channel,
            unit=entry.unit,
            quantity=entry.physical_quantity.value,
            gauge_or_abs=entry.gauge_or_abs,
            ambient_condition=body.ambient_condition,
            ambient_pressure_bar_abs=body.ambient_pressure_bar_abs,
            expression=entry.expression,
            canonical_name=entry.canonical_name,
        ),
        confidence=PROPOSAL_CONFIDENCE,
        rationale=f"proposed by a rule that {by} saved on {at:%Y-%m-%d}; check it against this file",
        proposed_by="rule",
    )


def target_of(session: Session, document: Document) -> tuple[RuleTarget | None, object | None]:
    """The rule target of a document's primary file (derived blobs use their parent's location)."""
    from backend.dispatcher.location import primary_location

    sha = session.scalar(
        select(DocumentSource.blob_sha256).where(
            DocumentSource.doc_id == document.doc_id, DocumentSource.role == DocumentSourceRole.PRIMARY
        )
    )
    where = primary_location(session, sha) if sha else None
    if where is None:
        return None, None
    folders: list[str] = []
    parent = where.parent_item_id
    while parent and len(folders) < 64:
        folders.append(parent)
        parent = session.scalar(select(DriveFolder.parent_item_id).where(DriveFolder.item_id == parent))
    return RuleTarget(where.root_name, folders, where.name, where.extension), where


def refresh(session: Session, doc_ids: Iterable[uuid.UUID] | None = None) -> dict[uuid.UUID, set[uuid.UUID]]:
    """Re-derive the suggestion of the open telemetry unit flags of ``doc_ids`` (all documents when None).

    Returns ``rule_id -> documents that now carry its proposal``. A flag no proposal reaches gets the
    pipeline's own hint back, so switching a rule off leaves nothing of it behind; a model proposal the route
    made (``proposed_by = llm``, file 06 §5) is the pipeline's own hint and is kept."""
    from backend.routes.c_telemetry.suggest import suggest_unit

    statement = select(ReviewFlag).where(
        ReviewFlag.flag_type == FlagType.UNIT_AMBIGUITY,
        ReviewFlag.status.in_(OPEN),
        ReviewFlag.doc_id.is_not(None),
    )
    if doc_ids is not None:
        statement = statement.where(ReviewFlag.doc_id.in_(list(doc_ids)))
    proposals = load_proposals(session)
    targets: dict[uuid.UUID, RuleTarget | None] = {}
    reached: dict[uuid.UUID, set[uuid.UUID]] = defaultdict(set)
    for flag in session.scalars(statement):
        channel = (flag.anchor or {}).get("channel")
        if (flag.evidence or {}).get("kind") != "unit_telemetry" or not channel:
            continue
        if flag.doc_id not in targets:
            document = session.get(Document, flag.doc_id)
            targets[flag.doc_id] = target_of(session, document)[0] if document else None
        target = targets[flag.doc_id]
        found = propose(proposals, target, channel) if target else None
        if found is not None:
            rule_id, suggestion = found
            reached[rule_id].add(flag.doc_id)
        elif (flag.suggested_resolution or {}).get("proposed_by") == "llm":
            flag.proposed_by_rule_id = None
            continue
        else:
            rule_id, suggestion = None, suggest_unit(UnitTelemetryEvidence.model_validate(flag.evidence))
        flag.suggested_resolution = suggestion.model_dump(mode="json")
        flag.proposed_by_rule_id = rule_id
    session.flush()
    return dict(reached)
