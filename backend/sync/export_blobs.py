"""Read-only export of landed blobs for checks outside the pipeline (S5's benchmark verification).

``python -m backend.sync.export_blobs --folder-id ID [--folder-id ID …] OUT_DIR`` copies every
``LANDED`` item inside the given folder subtrees from ``dcl-raw`` to ``OUT_DIR/<path below the
folder>``. It only reads: GETs from MinIO and SELECTs from the database (DCL_DATABASE_URL).
"""

import argparse
import os
import sys
from collections.abc import Sequence
from pathlib import Path, PurePosixPath

from minio import Minio
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from backend.postgres.enums import DriveItemStatus
from backend.postgres.models import DriveFolder, DriveItem
from backend.postgres.session import normalize_url
from backend.storage.minio import RAW, raw_key


def folder_paths(session: Session, folder_ids: Sequence[str]) -> dict[str, str]:
    rows = session.execute(
        select(DriveFolder.item_id, DriveFolder.path_cached).where(DriveFolder.item_id.in_(folder_ids))
    ).all()
    found = {item_id: path for item_id, path in rows if path}
    missing = sorted(set(folder_ids) - set(found))
    if missing:
        raise LookupError(f"unknown folder ids (crawl first): {', '.join(missing)}")
    return found


def items_under(session: Session, folder_path: str, status: DriveItemStatus) -> list[DriveItem]:
    return list(
        session.scalars(
            select(DriveItem).where(
                DriveItem.status == status, DriveItem.path_cached.startswith(folder_path + "/")
            )
        )
    )


def export(session: Session, minio: Minio, folder_ids: Sequence[str], out_dir: Path) -> list[Path]:
    written = []
    for folder_path in folder_paths(session, folder_ids).values():
        base = PurePosixPath(folder_path).name
        for item in items_under(session, folder_path, DriveItemStatus.LANDED):
            relative = PurePosixPath(item.path_cached).relative_to(folder_path)
            target = out_dir / base / Path(*relative.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            minio.fget_object(RAW, raw_key(item.blob_sha256), str(target))
            written.append(target)
    return written


def main(argv: list[str]) -> int:
    from backend.config import get_settings
    from backend.storage.minio import client_from_settings

    parser = argparse.ArgumentParser(prog="python -m backend.sync.export_blobs")
    parser.add_argument("--folder-id", action="append", required=True)
    parser.add_argument("out_dir", type=Path)
    args = parser.parse_args(argv)
    engine = create_engine(normalize_url(os.environ["DCL_DATABASE_URL"]))
    with Session(engine) as session:
        written = export(session, client_from_settings(get_settings()), args.folder_id, args.out_dir)
    print(f"exported {len(written)} files to {args.out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
