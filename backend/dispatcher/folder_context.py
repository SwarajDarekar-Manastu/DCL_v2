"""Folder context of a file (file 03 §1.2), persisted in ``documents.folder_context``.

Test plan, test run and hardware ids and a date are inferred by regex over the breadcrumb and the file name,
and the source of each inference is kept (``folder[2]`` or ``filename``). Different plan ids in
one path are kept and reported as a CONFLICT; a plan id with a run id is the normal case. A date in the path
(``13012026 - Flow Test``, ``WIN_20250530_14_01_51``, ``2026.04.20 - Clamp Heater``) is only a fallback: a
date the route reads from the file itself wins. Library roots get no path date.
"""

import re
from collections.abc import Sequence
from datetime import date
from typing import TYPE_CHECKING

from pydantic import BaseModel

from backend.postgres.enums import SourceOrigin

if TYPE_CHECKING:
    from backend.dispatcher.contract import ProcessedDocument

PLAN_PATTERNS = (re.compile(r"(?i)(?<![a-z])TP\s?(\d+)"), re.compile(r"(?i)Test[_ ]Plan[_ ](\d+)"))
RUN_PATTERNS = (
    re.compile(r"(?<![A-Za-z])T(\d{2})(?!\d)"),
    re.compile(r"(?i)Test_(\d+)_"),
    re.compile(r"(?i)(?<![a-z])Run[_ ]?(\d+)"),
    re.compile(r"(?i)(?<![a-z])Test[ _]?(\d{1,2})(?!\d)"),  # "Test 01_…", "Injector 14 - Test01", "Test1_…"
)
# year first (2026-04-20, 2026.04.20, 2026_04_20), day first (04-12-2025), or eight digits standing alone
DATE_YMD = re.compile(r"(?<!\d)(20\d{2})[-._](\d{2})[-._](\d{2})(?!\d)")
DATE_DMY = re.compile(r"(?<!\d)(\d{2})-(\d{2})-(20\d{2})(?!\d)")
DATE_EIGHT = re.compile(r"(?<!\d)(\d{8})(?!\d)")
HARDWARE_PATTERNS = (re.compile(r"(?i)(?<![a-z])INJ(?:ector)?[_ ]?(\d+)"),)
FOLDER_KINDS = (
    ("pressure_data_files", re.compile(r"(?i)pressure")),
    ("post_firing_photos", re.compile(r"(?i)photo|picture|image")),
    ("reports", re.compile(r"(?i)report")),
)
TRUST_BY_ORIGIN = {SourceOrigin.INTERNAL: 2, SourceOrigin.EXTERNAL_KEPT: 4}


class Inference(BaseModel):
    value: str
    source: str


class Sibling(BaseModel):
    name: str
    extension: str | None
    size_bytes: int | None


class FolderContext(BaseModel):
    root_name: str
    breadcrumb: list[str]
    path_cached: str
    test_plan_id: str | None = None
    test_run_id: str | None = None
    hardware_item: str | None = None
    doc_date: date | None = None
    inferences: dict[str, list[Inference]] = {}
    siblings: list[Sibling] = []
    folder_kind: str | None = None
    source_origin: SourceOrigin = SourceOrigin.INTERNAL
    trust_tier: int = 2
    conflicts: list[str] = []


def _infer(patterns, names: Sequence[tuple[str, str]], fmt) -> list[Inference]:
    found: list[Inference] = []
    for source, text in names:
        for pattern in patterns:
            for match in pattern.finditer(text):
                found.append(Inference(value=fmt(match.group(1)), source=source))
    return found


def _valid(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def path_date(text: str) -> date | None:
    """The first date written in ``text``, as a name starts with its date (``2026.06.18 - … - 10102025``).
    Eight digits read as YYYYMMDD when that is a valid date in this century, else DDMMYYYY (``29122025``);
    a longer digit run (a patent number) is no date."""
    found: list[tuple[int, date]] = []
    for m in DATE_YMD.finditer(text):
        if d := _valid(int(m[1]), int(m[2]), int(m[3])):
            found.append((m.start(), d))
    for m in DATE_DMY.finditer(text):
        if d := _valid(int(m[3]), int(m[2]), int(m[1])):
            found.append((m.start(), d))
    for m in DATE_EIGHT.finditer(text):
        s = m[1]
        d = (_valid(int(s[:4]), int(s[4:6]), int(s[6:])) if s.startswith("20") else None) or (
            _valid(int(s[4:]), int(s[2:4]), int(s[:2])) if s[4:6] == "20" else None
        )
        if d:
            found.append((m.start(), d))
    return min(found)[1] if found else None


def build_folder_context(
    root_name: str,
    folder_names: Sequence[str],
    file_name: str,
    siblings: Sequence[Sibling] = (),
    root_origin: SourceOrigin = SourceOrigin.INTERNAL,
    folder_origin_override: SourceOrigin | None = None,
    library_roots: Sequence[str] = ("APS - Library",),
) -> FolderContext:
    """``folder_names`` runs from the root folder (its own name first) down to the file's folder."""
    named = [(f"folder[{i}]", name) for i, name in enumerate(folder_names)] + [("filename", file_name)]
    plans = _infer(PLAN_PATTERNS, named, lambda n: f"TP{int(n):02d}")
    runs = _infer(RUN_PATTERNS, named, lambda n: f"T{int(n):02d}")
    hardware = _infer(HARDWARE_PATTERNS, named, lambda n: f"INJ{int(n):02d}")
    dates = [Inference(value=d.isoformat(), source=s) for s, name in named if (d := path_date(name))]
    conflicts = []
    if len({p.value for p in plans}) > 1:
        conflicts.append("two test plan ids in one path: " + ", ".join(sorted({p.value for p in plans})))
    origin = folder_origin_override or root_origin
    folder_kind = "library" if root_name in library_roots else None
    if folder_kind is None:
        for kind, pattern in FOLDER_KINDS:
            if any(pattern.search(name) for name in folder_names[1:]):
                folder_kind = kind
                break
    return FolderContext(
        root_name=root_name,
        breadcrumb=list(folder_names),
        path_cached="/".join([*folder_names, file_name]),
        test_plan_id=plans[-1].value if plans else None,
        test_run_id=runs[-1].value if runs else None,
        hardware_item=hardware[-1].value if hardware else None,
        doc_date=date.fromisoformat(dates[-1].value) if dates and folder_kind != "library" else None,
        inferences={
            k: v
            for k, v in (
                ("test_plan_id", plans),
                ("test_run_id", runs),
                ("hardware_item", hardware),
                ("doc_date", dates if folder_kind != "library" else []),
            )
            if v
        },
        siblings=list(siblings),
        folder_kind=folder_kind,
        source_origin=origin,
        trust_tier=TRUST_BY_ORIGIN[origin],
        conflicts=conflicts,
    )


def with_folder_labels(processed: "ProcessedDocument", folder: FolderContext) -> "ProcessedDocument":
    """The route's result with its empty plan, run, hardware and date taken from the folder context; a value
    the route read from the file itself is kept. A path date is marked ``date_source = "path"``."""
    fields = processed.document
    update = {
        name: getattr(folder, name)
        for name in ("test_plan_id", "test_run_id", "hardware_item")
        if getattr(fields, name) is None and getattr(folder, name) is not None
    }
    if fields.doc_date is None and folder.doc_date is not None:
        update |= {"doc_date": folder.doc_date, "date_source": "path"}
    if not update:
        return processed
    return processed.model_copy(update={"document": fields.model_copy(update=update)})
