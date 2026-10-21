"""M1 acceptance state of the registry (file 10 §5 M1), read-only.

Used by test_m1_acceptance.py (pass/fail per criterion) and as a CLI for the event-driven
procedures in M1.md, which compare the state before and after an operator action:

    DCL_DATABASE_URL=... uv run python backend/tests/acceptance/m1_state.py snapshot OUT.json
    uv run python backend/tests/acceptance/m1_state.py compare BEFORE.json AFTER.json
"""

import json
import re
import sys
from collections import Counter
from pathlib import Path

from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import Session

from backend.postgres.enums import DriveItemStatus as S
from backend.postgres.models import Blob, Document, DocumentSource, DriveFolder, DriveItem, Job
from backend.postgres.pipeline_config import download_scope, processing_scope
from backend.sync.scope import in_scope

REPO = Path(__file__).resolve().parents[3]
ACCEPTED = {S.PENDING_DOWNLOAD, S.LANDED, S.DOWNLOAD_FAILED, S.HELD_BY_SCOPE, S.HELD_LARGE_FILE}
REJECTED = {S.SKIPPED_JUNK, S.SKIPPED_EMPTY, S.SKIPPED_SHORTCUT, S.SKIPPED_UNSUPPORTED_PACKAGE, S.QUARANTINED}
GATE_REASON = re.compile(r"^(T[1-4]|SCOPE):\S")
# file 10 §5 M1: "~110k items with ~105k gate rejections and ~5,200 accepted"; ±10% bands.
BANDS = {"items": (99_000, 121_000), "rejected": (94_500, 115_500), "accepted": (4_680, 5_720)}
GRAPH_ID = re.compile(r"\b01[A-Z0-9]{32}\b")


def read_only(url: str) -> Session:
    engine = create_engine(url, connect_args={"options": "-c default_transaction_read_only=on"})
    return Session(engine)


def item_counts(session: Session) -> dict[str, int]:
    live = DriveItem.deleted_at.is_(None)
    by_status = dict(
        session.execute(select(DriveItem.status, func.count()).where(live).group_by(DriveItem.status)).all()
    )
    decided_without_reason = session.scalar(
        select(func.count()).where(
            live,
            DriveItem.status.in_(REJECTED | {S.HELD_BY_SCOPE, S.HELD_LARGE_FILE}),
            DriveItem.gate_reason.is_(None),
        )
    )
    bad_reason_format = sum(
        1
        for (reason,) in session.execute(
            select(DriveItem.gate_reason).where(live, DriveItem.gate_reason.is_not(None))
        )
        if not GATE_REASON.match(reason)
    )
    landed_without_blob = session.scalar(
        select(func.count()).where(live, DriveItem.status == S.LANDED, DriveItem.blob_sha256.is_(None))
    )
    return {
        "items": sum(by_status.values()),
        "accepted": sum(n for s, n in by_status.items() if s in ACCEPTED),
        "rejected": sum(n for s, n in by_status.items() if s in REJECTED),
        "undecided": by_status.get(S.SEEN, 0),
        "landed": by_status.get(S.LANDED, 0),
        "pending_or_failed": by_status.get(S.PENDING_DOWNLOAD, 0) + by_status.get(S.DOWNLOAD_FAILED, 0),
        "held_by_scope": by_status.get(S.HELD_BY_SCOPE, 0),
        "held_large": by_status.get(S.HELD_LARGE_FILE, 0),
        "decided_without_reason": decided_without_reason,
        "bad_reason_format": bad_reason_format,
        "landed_without_blob": landed_without_blob,
        "blobs": session.scalar(select(func.count()).select_from(Blob)),
        "documents": session.scalar(select(func.count()).select_from(Document)),
        "deleted_items": session.scalar(select(func.count()).where(DriveItem.deleted_at.is_not(None))),
    }


def band_violations(c: dict[str, int]) -> list[str]:
    return [
        f"{key} = {c[key]}, expected {low}-{high}"
        for key, (low, high) in BANDS.items()
        if not low <= c[key] <= high
    ]


def decision_violations(c: dict[str, int]) -> list[str]:
    checks = {
        "items still SEEN after the full crawl": c["undecided"],
        "rejected or held items without gate_reason": c["decided_without_reason"],
        "gate_reason not in the T1:/T2:/T3:/T4:/SCOPE: format": c["bad_reason_format"],
    }
    return [f"{msg}: {n}" for msg, n in checks.items() if n]


def download_violations(c: dict[str, int]) -> list[str]:
    """H11: download_scope empty, so nothing is held by scope and every accepted item below the
    size cap has landed with a blob."""
    out = []
    if c["held_by_scope"]:
        out.append(f"held by download scope: {c['held_by_scope']}")
    if c["pending_or_failed"]:
        out.append(f"pending or failed downloads: {c['pending_or_failed']}")
    if c["landed"] != c["accepted"] - c["held_large"]:
        out.append(f"landed {c['landed']} != accepted {c['accepted']} - held_large {c['held_large']}")
    if c["landed_without_blob"]:
        out.append(f"LANDED without blob: {c['landed_without_blob']}")
    return out


def out_of_scope_documents(session: Session) -> list[str]:
    """Documents with no live source location inside processing.scope (only the allowlist may be
    dispatched until M6)."""
    scope = processing_scope(session)
    if not scope:
        return []
    parent_of = dict(session.execute(select(DriveFolder.item_id, DriveFolder.parent_item_id)).all())

    def ancestors(folder_id):
        chain = []
        while folder_id and folder_id not in chain:
            chain.append(folder_id)
            folder_id = parent_of.get(folder_id)
        return chain

    bad = []
    for (doc_id,) in session.execute(select(Document.doc_id)):
        rows = session.execute(
            select(DriveItem.root_name, DriveItem.parent_item_id, DriveItem.path_cached)
            .join(DocumentSource, DocumentSource.blob_sha256 == DriveItem.blob_sha256)
            .where(DocumentSource.doc_id == doc_id, DriveItem.deleted_at.is_(None))
        ).all()
        if not any(in_scope(scope, root, ancestors(parent), path or "") for root, parent, path in rows):
            bad.append(str(doc_id))
    return bad


def decided_allowlist() -> list[str]:
    """The folder ids of the 'Processing allowlist' row of docs/sessions/DECISIONS.md."""
    for line in (REPO / "docs/sessions/DECISIONS.md").read_text(encoding="utf-8").splitlines():
        if "Processing allowlist" in line:
            return GRAPH_ID.findall(line)
    return []


def snapshot(session: Session) -> dict:
    jobs = Counter(f"{stage}:{status}" for stage, status in session.execute(select(Job.stage, Job.status)))
    return {
        "counts": item_counts(session),
        "jobs": dict(jobs),
        "download_scope": download_scope(session),
        "processing_scope": processing_scope(session),
        "paths": dict(
            session.execute(
                text("select item_id, coalesce(path_cached, '') from drive_items where deleted_at is null")
            ).all()
        ),
    }


def compare(before: dict, after: dict) -> dict:
    changed_paths = [k for k, v in after["paths"].items() if before["paths"].get(k) not in (None, v)]
    return {
        "counts": {
            k: after["counts"][k] - before["counts"].get(k, 0)
            for k in after["counts"]
            if after["counts"][k] != before["counts"].get(k, 0)
        },
        "jobs": {
            k: after["jobs"].get(k, 0) - before["jobs"].get(k, 0)
            for k in set(before["jobs"]) | set(after["jobs"])
            if after["jobs"].get(k, 0) != before["jobs"].get(k, 0)
        },
        "changed_paths": len(changed_paths),
    }


def main(argv: list[str]) -> int:
    import os

    from backend.postgres.session import normalize_url

    if len(argv) == 2 and argv[0] == "snapshot":
        with read_only(normalize_url(os.environ["DCL_DATABASE_URL"])) as session:
            Path(argv[1]).write_text(json.dumps(snapshot(session), indent=1, sort_keys=True))
        return 0
    if len(argv) == 3 and argv[0] == "compare":
        a, b = (json.loads(Path(p).read_text()) for p in argv[1:])
        print(json.dumps(compare(a, b), indent=1, sort_keys=True))
        return 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
