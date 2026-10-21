"""Folder context of a file (file 03 §1.2), persisted in ``documents.folder_context``.

Test plan, test run and hardware ids are inferred by regex over the breadcrumb and the file name,
and the source of each inference is kept (``folder[2]`` or ``filename``). Different plan ids in
one path are kept and reported as a CONFLICT; a plan id with a run id is the normal case.
"""

import re
from collections.abc import Sequence

from pydantic import BaseModel

from backend.postgres.enums import SourceOrigin

PLAN_PATTERNS = (re.compile(r"(?i)(?<![a-z])TP\s?(\d+)"), re.compile(r"(?i)Test[_ ]Plan[_ ](\d+)"))
RUN_PATTERNS = (
    re.compile(r"(?<![A-Za-z])T(\d{2})(?!\d)"),
    re.compile(r"(?i)Test_(\d+)_"),
    re.compile(r"(?i)(?<![a-z])Run[_ ]?(\d+)"),
)
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
        inferences={
            k: v
            for k, v in (("test_plan_id", plans), ("test_run_id", runs), ("hardware_item", hardware))
            if v
        },
        siblings=list(siblings),
        folder_kind=folder_kind,
        source_origin=origin,
        trust_tier=TRUST_BY_ORIGIN[origin],
        conflicts=conflicts,
    )
