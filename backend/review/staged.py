"""The validation gate and the staged payload (file 06 §2, §7; file 03 §1.5).

After a route returns its ``ProcessedDocument``, the gate applies the severity policy
(``flags.severity_overrides`` per route and flag type, ``flags.strict_mode``), upserts every flag by
fingerprint, and decides: any HARD flag → the document is HALTED, the payload is staged at
``dcl-cir/{sha256}/staged.json`` and nothing reaches the index; otherwise the commit path runs.
``load_staged`` reads the payload back for ``resume_from_staged`` (resolution never re-parses).
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.dispatcher.contract import Flag, ProcessedDocument
from backend.postgres import pipeline_config
from backend.postgres.enums import DocumentStatus, FlagSeverity, FlagStatus
from backend.postgres.models import Document, ReviewFlag
from backend.review.flags import upsert_document_flag
from backend.review.rule_answers import answer_flags
from backend.storage.minio import BucketStore, parse_uri


def staged_key(blob_sha256: str) -> str:
    return f"{blob_sha256}/staged.json"


@dataclass(frozen=True)
class GateResult:
    halted: bool
    hard: int
    soft: int
    document: ProcessedDocument
    staged_uri: str | None = None


def apply_severity_policy(session: Session, doc: ProcessedDocument) -> ProcessedDocument:
    """``flags.strict_mode = true`` turns every SOFT into HARD; ``flags.severity_overrides`` is
    ``{route: {flag_type: "HARD" | "SOFT"}}`` and wins over the route's default."""
    strict = pipeline_config.get(session, "flags.strict_mode", default=False) is True
    overrides = pipeline_config.get(session, "flags.severity_overrides", default={}) or {}
    by_type = overrides.get(str(doc.route), {}) if isinstance(overrides, dict) else {}
    flags: list[Flag] = []
    for flag in doc.flags:
        override = by_type.get(str(flag.flag_type))
        severity = FlagSeverity(override) if override else flag.severity
        if strict:
            severity = FlagSeverity.HARD
        flags.append(flag if severity == flag.severity else flag.model_copy(update={"severity": severity}))
    return doc.model_copy(update={"flags": flags})


OPEN_STATUSES = (FlagStatus.OPEN, FlagStatus.IN_PROGRESS, FlagStatus.REOPENED)


def gate(
    session: Session,
    cir: BucketStore,
    document: Document,
    doc: ProcessedDocument,
    stale: Callable[[ReviewFlag], bool] | None = None,
    now: datetime | None = None,
) -> GateResult:
    """Record the flags and halt on an open HARD one. The caller commits; a clean document goes to the commit
    path. A HARD flag a person decided (resolved, approved) no longer halts its document (file 06 §7: the
    resumed gate passes); one the pipeline closed and the route raises again is open again. An open flag an
    active rule answers is resolved by that rule (``rule_answers``) before the decision is taken.

    ``stale`` names the route's own flags: an open one the route did not raise again this time (a rule now
    answers it) becomes ``AUTO_RESOLVED``. Flags of other origins (dispatcher, humans) are left alone."""
    doc = apply_severity_policy(session, doc)
    rows = []
    for flag in doc.flags:
        row = upsert_document_flag(session, document.doc_id, flag, str(doc.route))
        if row.status == FlagStatus.AUTO_RESOLVED and row.resolved_by == "pipeline":
            row.status, row.resolved_by, row.resolved_at = FlagStatus.OPEN, None, None
        rows.append(row)
    answer_flags(session, document, rows)  # a rule answers a flag the way a person would (rule_answers.py)
    if stale is not None:
        current = {flag.fingerprint for flag in doc.flags}
        for row in session.scalars(
            select(ReviewFlag).where(
                ReviewFlag.doc_id == document.doc_id, ReviewFlag.status.in_(OPEN_STATUSES)
            )
        ):
            if row.fingerprint not in current and stale(row):
                row.status = FlagStatus.AUTO_RESOLVED
                row.resolved_by = "pipeline"
                row.resolved_at = now or datetime.now(UTC)
    decided = {
        f.fingerprint
        for f, r in zip(doc.flags, rows, strict=True)
        if f.severity == FlagSeverity.HARD and r.status not in OPEN_STATUSES
    }
    doc = doc.model_copy(update={"flags": [f for f in doc.flags if f.fingerprint not in decided]})
    hard = sum(flag.severity == FlagSeverity.HARD for flag in doc.flags)
    soft = len(doc.flags) - hard
    if not hard:
        return GateResult(halted=False, hard=0, soft=soft, document=doc)
    staged_uri = cir.put(staged_key(doc.blob_sha256), doc.model_dump_json().encode(), "application/json")
    document.status = DocumentStatus.HALTED
    document.staged_payload_uri = staged_uri
    session.flush()
    return GateResult(halted=True, hard=hard, soft=soft, document=doc, staged_uri=staged_uri)


def load_staged(cir: BucketStore, document: Document) -> ProcessedDocument:
    if document.staged_payload_uri is None:
        raise ValueError(f"document {document.doc_id} has no staged payload")
    _, key = parse_uri(document.staged_payload_uri)
    payload = cir.get(key)
    if payload is None:
        raise FileNotFoundError(f"staged payload {document.staged_payload_uri} is missing")
    return ProcessedDocument.model_validate_json(payload)
