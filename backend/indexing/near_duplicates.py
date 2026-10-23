"""Near-duplicate reports (file 02 §5.3, DECISIONS 2026-10-23): MinHash over 5-word shingles.

Two live documents of one route in one OneDrive root whose estimated Jaccard similarity is at least
``THRESHOLD`` get one ``NEAR_DUPLICATE`` row (``doc_id_a < doc_id_b``, the score). Both stay indexed and
neither changes status; retrieval collapses the pair to the newer document. The signature is computed from
the body text of the document's nodes, never from ``search_text`` (title, summary and entity names), and
numbers stay in the shingles so two reports that differ only in their numbers still link.

Rows written here carry ``created_by = 'minhash'``: a re-index replaces exactly those and leaves any link an
operator made. Documents without a OneDrive item of their own (archive members, embedded objects) are not
compared, so the result does not depend on the order documents are committed in.
"""

import argparse
import hashlib
import re
import uuid
from itertools import combinations

import numpy as np
from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session

from backend.postgres.enums import DocumentSourceRole, DocumentStatus, DriveItemStatus, NodeType
from backend.postgres.models import Document, DocumentNode, DocumentRelation, DocumentSource, DriveItem

PERMUTATIONS = 128
SHINGLE_WORDS = 5
THRESHOLD = 0.85
MIN_SHINGLES = 50
CREATED_BY = "minhash"
RELATION = "NEAR_DUPLICATE"
LIVE = (DocumentStatus.ACTIVE, DocumentStatus.ACTIVE_WITH_SOFT_FLAGS)
BODY_TYPES = (NodeType.PARENT, NodeType.TABLE)

PRIME = (1 << 31) - 1  # a Mersenne prime: a * x + b stays below 2**63 for 31-bit a, x, b
_CHUNK = 8192
_TAGS = re.compile(r"<[^>]+>")
_WORDS = re.compile(r"\w+")


def _seed(label: str) -> int:
    return int.from_bytes(hashlib.blake2b(label.encode(), digest_size=8).digest(), "big")


_A = np.array([1 + _seed(f"a{i}") % (PRIME - 1) for i in range(PERMUTATIONS)], dtype=np.uint64)[:, None]
_B = np.array([_seed(f"b{i}") % PRIME for i in range(PERMUTATIONS)], dtype=np.uint64)[:, None]


def shingles(text: str) -> set[int]:
    words = _WORDS.findall(_TAGS.sub(" ", text).casefold())
    return {
        int.from_bytes(
            hashlib.blake2b(" ".join(words[i : i + SHINGLE_WORDS]).encode(), digest_size=4).digest(), "big"
        )
        % PRIME
        for i in range(len(words) - SHINGLE_WORDS + 1)
    }


def signature(text: str) -> bytes | None:
    """128 minimum hashes as big-endian uint32; ``None`` when the text has fewer than ``MIN_SHINGLES``."""
    found = shingles(text)
    if len(found) < MIN_SHINGLES:
        return None
    values = np.fromiter(found, dtype=np.uint64, count=len(found))
    minima = np.full(PERMUTATIONS, PRIME, dtype=np.uint64)
    for start in range(0, len(values), _CHUNK):
        block = values[start : start + _CHUNK]
        minima = np.minimum(minima, ((_A * block + _B) % PRIME).min(axis=1))
    return minima.astype(">u4").tobytes()


def similarity(a: bytes, b: bytes) -> float:
    """The share of equal minimum hashes: an estimate of the Jaccard similarity of the shingle sets."""
    return float(np.mean(np.frombuffer(a, dtype=">u4") == np.frombuffer(b, dtype=">u4")))


def body_text(session: Session, doc_id: uuid.UUID) -> str:
    return "\n".join(
        session.scalars(
            select(DocumentNode.content)
            .where(DocumentNode.doc_id == doc_id, DocumentNode.node_type.in_([str(t) for t in BODY_TYPES]))
            .order_by(DocumentNode.ordinal)
        )
    )


def _roots(session: Session, doc_ids: list[uuid.UUID]) -> dict[uuid.UUID, str]:
    rows = session.execute(
        select(DocumentSource.doc_id, DriveItem.root_name)
        .join(DriveItem, DriveItem.blob_sha256 == DocumentSource.blob_sha256)
        .where(
            DocumentSource.doc_id.in_(doc_ids),
            DocumentSource.role == DocumentSourceRole.PRIMARY,
            DriveItem.status != DriveItemStatus.DELETED,
        )
        .order_by(DriveItem.path_cached.desc())
    )
    return {doc_id: root for doc_id, root in rows}


def _candidates(session: Session, document: Document, root: str) -> list[tuple[uuid.UUID, bytes]]:
    rows = session.execute(
        select(Document.doc_id, Document.minhash)
        .join(DocumentSource, DocumentSource.doc_id == Document.doc_id)
        .join(DriveItem, DriveItem.blob_sha256 == DocumentSource.blob_sha256)
        .where(
            Document.route == document.route,
            Document.doc_id != document.doc_id,
            Document.status.in_([str(s) for s in LIVE]),
            Document.minhash.is_not(None),
            DocumentSource.role == DocumentSourceRole.PRIMARY,
            DriveItem.root_name == root,
            DriveItem.status != DriveItemStatus.DELETED,
        )
        .distinct()
    )
    return [(doc_id, bytes(minhash)) for doc_id, minhash in rows]


def apply_near_duplicates(session: Session, document: Document) -> list[tuple[uuid.UUID, float]]:
    """Store ``document``'s signature and replace its ``minhash`` links; returns ``(other doc_id, score)``."""
    session.flush()
    document.minhash = signature(body_text(session, document.doc_id))
    session.execute(
        delete(DocumentRelation).where(
            DocumentRelation.relation == RELATION,
            DocumentRelation.created_by == CREATED_BY,
            or_(DocumentRelation.doc_id_a == document.doc_id, DocumentRelation.doc_id_b == document.doc_id),
        )
    )
    root = _roots(session, [document.doc_id]).get(document.doc_id)
    found: list[tuple[uuid.UUID, float]] = []
    if document.minhash is not None and root is not None and document.status in {str(s) for s in LIVE}:
        for other, other_hash in _candidates(session, document, root):
            score = similarity(document.minhash, other_hash)
            if score >= THRESHOLD:
                a, b = sorted([document.doc_id, other])
                session.add(
                    DocumentRelation(
                        doc_id_a=a, doc_id_b=b, relation=RELATION, score=score, created_by=CREATED_BY
                    )
                )
                found.append((other, score))
    session.flush()
    return found


def backfill(session: Session) -> int:
    """Signatures and links for every live document; returns how many ``minhash`` links exist afterwards."""
    documents = session.scalars(
        select(Document).where(Document.status.in_([str(s) for s in LIVE])).order_by(Document.created_at)
    ).all()
    for document in documents:
        apply_near_duplicates(session, document)
    return session.scalar(
        select(func.count()).where(
            DocumentRelation.relation == RELATION, DocumentRelation.created_by == CREATED_BY
        )
    )


def report(session: Session, floor: float = 0.7) -> list[tuple[str, str, float]]:
    """Read-only: every pair of live documents (same route and root) at or above ``floor``, best first."""
    documents = session.scalars(select(Document).where(Document.status.in_([str(s) for s in LIVE]))).all()
    roots = _roots(session, [d.doc_id for d in documents])
    groups: dict[tuple[str | None, str], list[tuple[Document, bytes]]] = {}
    for document in documents:
        root = roots.get(document.doc_id)
        signed = signature(body_text(session, document.doc_id)) if root else None
        if signed is not None:
            groups.setdefault((document.route, root), []).append((document, signed))
    pairs = [
        (a.title or str(a.doc_id), b.title or str(b.doc_id), similarity(sa, sb))
        for members in groups.values()
        for (a, sa), (b, sb) in combinations(members, 2)
    ]
    return sorted((p for p in pairs if p[2] >= floor), key=lambda p: -p[2])


def main(argv: list[str]) -> int:
    import os
    from pathlib import Path

    from sqlalchemy import create_engine

    from backend.config import get_settings, load_settings
    from backend.postgres.session import normalize_url

    parser = argparse.ArgumentParser(prog="python -m backend.indexing.near_duplicates")
    parser.add_argument("command", choices=["backfill", "report"])
    parser.add_argument("--floor", type=float, default=0.7, help="report: lowest score listed")
    parser.add_argument("--env-file", default=None)
    args = parser.parse_args(argv)
    settings = load_settings(Path(args.env_file)) if args.env_file else get_settings()
    engine = create_engine(
        normalize_url(os.environ.get("DCL_DATABASE_URL") or settings.stack_database_url().get_secret_value())
    )
    with Session(engine, expire_on_commit=False) as session:
        if args.command == "report":
            for a, b, score in report(session, args.floor):
                print(f"{score:.2f}  {a}  |  {b}")
            return 0
        print(f"{backfill(session)} NEAR_DUPLICATE links")
        session.commit()
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main(sys.argv[1:]))
