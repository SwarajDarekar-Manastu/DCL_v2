"""M5 acceptance (file 10 §5 M5): A1 crop geometry, table crops, figure readings and the per-document
contact sheet, read-only. The database is read in a read-only transaction; MinIO is only asked whether
an object exists (HEAD).

    DCL_DATABASE_URL=... DCL_MINIO_ENDPOINT=... DCL_MINIO_ACCESS_KEY=... DCL_MINIO_SECRET_KEY=... \\
        uv run python backend/tests/acceptance/m5_state.py report
"""

import json
import os
import sys
from collections import Counter
from collections.abc import Callable
from urllib.parse import urlsplit

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from backend.postgres.enums import AssetKind, NodeType, Route
from backend.postgres.models import Asset, Document, DocumentNode, DocumentSource

Exists = Callable[[str], bool]

CROP_KINDS = (AssetKind.FIGURE_CROP, AssetKind.HANDWRITING_CROP)
MIN_SIDE_PX = 48
MIN_PAGE_SHARE = 0.003
MAX_PAGE_SHARE = 0.90
FULL_PAGE_CLASS = "full_page_image"


def read_only(url: str) -> Session:
    engine = create_engine(url, connect_args={"options": "-c default_transaction_read_only=on"})
    return Session(engine)


def contact_sheet_uri(blob_sha256: str) -> str:
    return f"s3://dcl-assets/qa/{blob_sha256}/crops.png"


def minio_exists() -> Exists:
    """HEAD-only access to the stack's MinIO from DCL_MINIO_ENDPOINT / _ACCESS_KEY / _SECRET_KEY."""
    from minio import Minio
    from minio.error import S3Error

    from backend.storage.minio import parse_uri

    endpoint = urlsplit(os.environ["DCL_MINIO_ENDPOINT"])
    client = Minio(
        endpoint.netloc,
        access_key=os.environ["DCL_MINIO_ACCESS_KEY"],
        secret_key=os.environ["DCL_MINIO_SECRET_KEY"],
        secure=endpoint.scheme == "https" or os.environ.get("DCL_MINIO_SECURE", "").lower() == "true",
    )

    def exists(minio_uri: str) -> bool:
        try:
            client.stat_object(*parse_uri(minio_uri))
        except S3Error as exc:
            if exc.code in ("NoSuchKey", "NoSuchObject"):
                return False
            raise
        return True

    return exists


def a1_documents(session: Session) -> dict:
    """A1 document id -> primary blob sha256."""
    return dict(
        session.execute(
            select(Document.doc_id, DocumentSource.blob_sha256)
            .join(DocumentSource, DocumentSource.doc_id == Document.doc_id)
            .where(Document.route == Route.A1, DocumentSource.role == "primary")
        ).all()
    )


def _page_share(bbox: dict | None) -> float | None:
    if not bbox:
        return None
    return max(0.0, bbox["x1"] - bbox["x0"]) * max(0.0, bbox["y1"] - bbox["y0"])


def crop_violations(session: Session) -> list[str]:
    """Every figure and handwriting crop is at least 48 px a side and 0.3 % of its page; none covers
    more than 90 % of the page unless a node using it is classed full_page_image."""
    classes: dict = {}
    for asset_id, meta in session.execute(
        select(DocumentNode.asset_id, DocumentNode.metadata_).where(DocumentNode.asset_id.is_not(None))
    ):
        classes.setdefault(asset_id, set()).add((meta or {}).get("class"))
    out = []
    for asset in session.scalars(select(Asset).where(Asset.kind.in_(CROP_KINDS)).order_by(Asset.minio_uri)):
        where = f"{asset.kind} {asset.minio_uri}"
        if asset.width is None or asset.height is None:
            out.append(f"{where}: no pixel size")
        elif min(asset.width, asset.height) < MIN_SIDE_PX:
            out.append(f"{where}: {asset.width}x{asset.height} px, below {MIN_SIDE_PX} px")
        share = _page_share(asset.bbox)
        if share is None:
            out.append(f"{where}: no bbox")
        elif share < MIN_PAGE_SHARE:
            out.append(f"{where}: {share:.2%} of the page, below {MIN_PAGE_SHARE:.1%}")
        elif share > MAX_PAGE_SHARE and FULL_PAGE_CLASS not in classes.get(asset.asset_id, set()):
            out.append(f"{where}: {share:.0%} of the page and not classed {FULL_PAGE_CLASS}")
    return out


def _a1_nodes(session: Session, node_type: str):
    return session.execute(
        select(DocumentNode.doc_id, DocumentNode.node_id, DocumentNode.content, Asset.kind)
        .join(Document, Document.doc_id == DocumentNode.doc_id)
        .outerjoin(Asset, Asset.asset_id == DocumentNode.asset_id)
        .where(Document.route == Route.A1, DocumentNode.node_type == node_type)
    ).all()


def table_crop_violations(session: Session) -> list[str]:
    return [
        f"doc {doc_id} table node {node_id}: asset kind {kind!r}, expected table_crop"
        for doc_id, node_id, _, kind in _a1_nodes(session, NodeType.TABLE)
        if kind != AssetKind.TABLE_CROP
    ]


def figure_content_violations(session: Session) -> list[str]:
    return [
        f"doc {doc_id} figure node {node_id}: empty content"
        for doc_id, node_id, content, _ in _a1_nodes(session, NodeType.FIGURE)
        if not (content or "").strip()
    ]


def contact_sheet_violations(session: Session, exists: Exists) -> list[str]:
    return [
        f"doc {doc_id}: no contact sheet {contact_sheet_uri(sha)}"
        for doc_id, sha in sorted(a1_documents(session).items(), key=lambda kv: str(kv[0]))
        if not exists(contact_sheet_uri(sha))
    ]


def counts(session: Session) -> dict:
    kinds = Counter(
        str(k)
        for k in session.scalars(
            select(Asset.kind).where(Asset.kind.in_([*CROP_KINDS, AssetKind.TABLE_CROP]))
        )
    )
    return {
        "a1_documents": len(a1_documents(session)),
        "assets": dict(kinds),
        "a1_table_nodes": len(_a1_nodes(session, NodeType.TABLE)),
        "a1_figure_nodes": len(_a1_nodes(session, NodeType.FIGURE)),
    }


def report(session: Session, exists: Exists | None) -> dict:
    checks = {
        "crops": crop_violations(session),
        "table_crops": table_crop_violations(session),
        "figure_content": figure_content_violations(session),
    }
    if exists is not None:
        checks["contact_sheets"] = contact_sheet_violations(session, exists)
    return {
        "counts": counts(session),
        "violations": {k: len(v) for k, v in checks.items()},
        "examples": {k: v[:10] for k, v in checks.items() if v},
    }


def main(argv: list[str]) -> int:
    if argv != ["report"]:
        print(__doc__, file=sys.stderr)
        return 2
    from backend.postgres.session import normalize_url

    exists = minio_exists() if os.environ.get("DCL_MINIO_ENDPOINT") else None
    with read_only(normalize_url(os.environ["DCL_DATABASE_URL"])) as session:
        print(json.dumps(report(session, exists), indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
