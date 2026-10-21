"""Folder-level listing of the metadata crawl, for choosing ``processing.scope`` (S5, file 10 §10).

Metadata only, no file content. One row per folder that holds gate-accepted files, with counts by
extension and the presence flags of the allowlist slots; a second file lists the PDFs of the
``APS - Library`` root. ``\\documentclass`` is not known before download, so ``.tex`` files are
reported together with a same-stem ``.pdf`` in the folder (the PDF twin).

CLI: ``python -m backend.sync.folder_listing OUT_DIR`` (uses DCL_DATABASE_URL).
"""

import csv
import os
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from backend.postgres.enums import DriveItemStatus
from backend.postgres.models import DriveFolder, DriveItem
from backend.postgres.session import normalize_url

ACCEPTED = (
    DriveItemStatus.PENDING_DOWNLOAD,
    DriveItemStatus.LANDED,
    DriveItemStatus.DOWNLOAD_FAILED,
    DriveItemStatus.HELD_BY_SCOPE,
    DriveItemStatus.HELD_LARGE_FILE,
)
LIBRARY_ROOT = "APS - Library"
FLAG_EXTENSIONS = (".cfg", ".dat_fail", ".tdms", ".heic", ".npy", ".drawio")
VIDEO_EXTENSIONS = (".mp4", ".mov")
COLUMNS = [
    "root",
    "folder_path",
    "folder_id",
    "n_accepted",
    "extensions",
    *(f"has{ext.replace('.', '_')}" for ext in FLAG_EXTENSIONS),
    "drawio_rev_c",
    "videos",
    "xlsx_fmea_or_risk",
    "n_tex",
    "tex_with_pdf_twin",
]


@dataclass
class FolderRow:
    root: str
    folder_path: str
    folder_id: str
    extensions: Counter = field(default_factory=Counter)
    names: list[tuple[str, int | None]] = field(default_factory=list)

    def as_csv(self) -> dict[str, object]:
        names = [n for n, _ in self.names]
        stems_pdf = {PurePosixPath(n).stem.casefold() for n in names if n.casefold().endswith(".pdf")}
        tex = [n for n in names if n.casefold().endswith(".tex")]
        row: dict[str, object] = {
            "root": self.root,
            "folder_path": self.folder_path,
            "folder_id": self.folder_id,
            "n_accepted": len(names),
            "extensions": ";".join(f"{ext or '(none)'}:{n}" for ext, n in sorted(self.extensions.items())),
            "drawio_rev_c": any(n.casefold().endswith(".drawio") and "rev c" in n.casefold() for n in names),
            "videos": ";".join(
                f"{n}:{(size or 0) / 1e6:.1f}MB"
                for n, size in self.names
                if n.casefold().endswith(VIDEO_EXTENSIONS)
            ),
            "xlsx_fmea_or_risk": ";".join(
                n
                for n in names
                if n.casefold().endswith(".xlsx") and ("fmea" in n.casefold() or "risk" in n.casefold())
            ),
            "n_tex": len(tex),
            "tex_with_pdf_twin": ";".join(n for n in tex if PurePosixPath(n).stem.casefold() in stems_pdf),
        }
        for ext in FLAG_EXTENSIONS:
            row[f"has{ext.replace('.', '_')}"] = self.extensions.get(ext, 0) > 0
        return row


def build(session: Session) -> tuple[list[FolderRow], list[dict[str, object]]]:
    folders = {
        (f.drive_id, f.item_id): f
        for f in session.scalars(select(DriveFolder).where(DriveFolder.deleted_at.is_(None)))
    }
    rows: dict[tuple[str, str], FolderRow] = {}
    library: list[dict[str, object]] = []
    for item in session.scalars(select(DriveItem).where(DriveItem.status.in_(ACCEPTED))):
        folder = folders.get((item.drive_id, item.parent_item_id or ""))
        folder_path = folder.path_cached if folder and folder.path_cached else ""
        relative = folder_path.split("/", 1)[1] if "/" in folder_path else ""
        key = (item.drive_id, item.parent_item_id or "")
        row = rows.setdefault(key, FolderRow(item.root_name, relative, item.parent_item_id or ""))
        row.extensions[item.extension or ""] += 1
        row.names.append((item.name, item.size_bytes))
        if item.root_name == LIBRARY_ROOT and (item.extension or "") == ".pdf":
            library.append(
                {
                    "root": item.root_name,
                    "folder_path": relative,
                    "file_name": item.name,
                    "size_mb": round((item.size_bytes or 0) / 1e6, 2),
                }
            )
    ordered = sorted(rows.values(), key=lambda r: (r.root, r.folder_path))
    return ordered, sorted(library, key=lambda r: (r["folder_path"], r["file_name"]))


def write(out_dir: Path, folders: list[FolderRow], library: list[dict[str, object]]) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    folder_file, library_file = out_dir / "folders.csv", out_dir / "library_pdfs.csv"
    with folder_file.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(row.as_csv() for row in folders)
    with library_file.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["root", "folder_path", "file_name", "size_mb"])
        writer.writeheader()
        writer.writerows(library)
    return folder_file, library_file


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print("usage: python -m backend.sync.folder_listing OUT_DIR", file=sys.stderr)
        return 2
    engine = create_engine(normalize_url(os.environ["DCL_DATABASE_URL"]))
    with Session(engine) as session:
        folders, library = build(session)
    paths = write(Path(argv[0]), folders, library)
    print(f"{len(folders)} folders, {len(library)} library PDFs → {paths[0]}, {paths[1]}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
