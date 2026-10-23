"""Revision supersession for diagrams and drawings (file 02 §5.1, Lead 2026-10-23).

Two documents of the same route in the same folder whose titles match once the revision token is removed
("Feed system Rev B" / "Feed system Rev C") are revisions of one drawing: the newer gets
``SUPERSEDES`` to the older and the older becomes ``SUPERSEDED`` (citable, out of default retrieval).
Two documents claiming the same revision raise ``CONFLICT`` SOFT on each. Revisions compare letter with
letter (A < B < … < Z < AA) and number with number; a letter and a number are not ordered (no action).
"""

import hashlib
import re
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.dispatcher.contract import ConflictEvidence, ConflictSide, Flag, FlagAnchor
from backend.postgres.enums import DocumentSourceRole, DocumentStatus, FlagSeverity, FlagType
from backend.postgres.models import Document, DocumentRelation, DocumentSource
from backend.review.flags import upsert_document_flag

REV = re.compile(r"\brev(?:ision)?\.?\s*([A-Z]{1,3}|\d{1,3})\b", re.IGNORECASE)
LIVE = (DocumentStatus.ACTIVE, DocumentStatus.ACTIVE_WITH_SOFT_FLAGS, DocumentStatus.HALTED)


@dataclass(frozen=True)
class Revision:
    kind: str  # "letter" | "number"
    value: int

    @classmethod
    def parse(cls, marker: str | None) -> "Revision | None":
        match = REV.search(marker or "")
        if match is None:
            return None
        token = match.group(1).upper()
        if token.isdigit():
            return cls("number", int(token))
        value = 0
        for ch in token:
            value = value * 26 + (ord(ch) - ord("A") + 1)
        return cls("letter", value)


def title_base(title: str | None) -> str:
    """The title without its revision token, separators and case: what two revisions share."""
    stripped = REV.sub(" ", title or "")
    return re.sub(r"[\s_\-–.]+", " ", stripped).strip().casefold()


def _folder(session: Session, doc_id) -> str | None:
    from backend.dispatcher.location import primary_location

    sha = session.scalar(
        select(DocumentSource.blob_sha256).where(
            DocumentSource.doc_id == doc_id, DocumentSource.role == DocumentSourceRole.PRIMARY
        )
    )
    where = primary_location(session, sha) if sha else None
    return where.parent_item_id if where else None


def _same_revision_conflict(document: Document, other: Document) -> Flag:
    a, b = sorted([(str(document.doc_id), document.title or ""), (str(other.doc_id), other.title or "")])
    return Flag(
        flag_type=FlagType.CONFLICT,
        severity=FlagSeverity.SOFT,
        anchor=FlagAnchor(content_sha256=hashlib.sha256(f"revision|{a[0]}|{b[0]}".encode()).hexdigest()[:16]),
        evidence=ConflictEvidence(
            subject="revision",
            a=ConflictSide(
                label=a[1], value=document.revision_marker or "", provenance="file name", doc_id=a[0]
            ),
            b=ConflictSide(
                label=b[1], value=other.revision_marker or "", provenance="file name", doc_id=b[0]
            ),
        ),
    )


def _supersede(session: Session, newer: Document, older: Document) -> None:
    from backend.dispatcher.routing import _set_status

    if session.get(DocumentRelation, (newer.doc_id, older.doc_id, "SUPERSEDES")) is None:
        session.add(DocumentRelation(doc_id_a=newer.doc_id, doc_id_b=older.doc_id, relation="SUPERSEDES"))
    if older.status in LIVE:
        sha = session.scalar(
            select(DocumentSource.blob_sha256).where(
                DocumentSource.doc_id == older.doc_id, DocumentSource.role == DocumentSourceRole.PRIMARY
            )
        )
        _set_status(older, DocumentStatus.SUPERSEDED, sha)


def apply_revisions(session: Session, document: Document) -> list[str]:
    """Supersession and same-revision conflicts for ``document`` against its folder's revisions."""
    mine = Revision.parse(document.revision_marker)
    if mine is None:
        return []
    folder, base = _folder(session, document.doc_id), title_base(document.title)
    events = []
    candidates = session.scalars(
        select(Document).where(
            Document.route == document.route,
            Document.doc_id != document.doc_id,
            Document.revision_marker.is_not(None),
            Document.status.in_(LIVE),
        )
    ).all()
    for other in candidates:
        theirs = Revision.parse(other.revision_marker)
        if theirs is None or theirs.kind != mine.kind or title_base(other.title) != base:
            continue
        if _folder(session, other.doc_id) != folder:
            continue
        if theirs.value == mine.value:
            flag = _same_revision_conflict(document, other)
            upsert_document_flag(session, document.doc_id, flag, str(document.route))
            upsert_document_flag(session, other.doc_id, flag, str(other.route))
            events.append(f"conflict:{other.doc_id}")
        elif mine.value > theirs.value:
            _supersede(session, document, other)
            events.append(f"supersedes:{other.doc_id}")
        else:
            _supersede(session, other, document)
            events.append(f"superseded_by:{other.doc_id}")
    session.flush()
    return events
