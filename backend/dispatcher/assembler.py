"""Folder-level assembler (file 03 §1.3): files that only make sense together become one document.

Input: the eligible files of one folder subtree (paths relative to it) and a way to read a file's
text. Output: one ``DocumentPlan`` per logical document, with the primary file, its parts and their
``document_sources`` roles, and the CONFLICTs the assembler was unsure about.

- LaTeX: a ``.tex`` containing ``\\documentclass`` is a master; ``\\input``, ``\\include``,
  ``\\subfile`` and ``\\import{dir}{file}`` are resolved recursively relative to the master's folder
  (or, when not found there, its nearest ancestor that has the path) and become ``part``s.
  Two masters in one folder: both become documents with a CONFLICT. ``.tex`` files that no master
  includes are assembled per folder by file name and the document keeps a note: no person can decide
  anything about it, and the verdict holds for one folder while a document stands for every copy.
- A ``.pdf`` with the same stem as a master in its folder is that document's ``visual_twin``.
- JSON section files (``section_file_sets`` of ``config/report_json_schemas.yaml``): two or more in one
  folder become one document named after the folder, in the configured section order.
- Everything else is one document per file.
"""

import re
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

import yaml

from backend.postgres.enums import DocumentSourceRole

REPORT_SCHEMAS_YAML = Path(__file__).resolve().parents[2] / "config" / "report_json_schemas.yaml"
MASTER = re.compile(r"\\documentclass")
INCLUDE = re.compile(r"\\(?:input|include|subfile)\s*\{([^}]+)\}")
IMPORT = re.compile(r"\\(?:sub)?import\s*\{([^}]*)\}\s*\{([^}]+)\}")


@dataclass(frozen=True)
class FileRef:
    path: str  # relative to the subtree, POSIX separators
    blob_sha256: str
    kind: str  # type_resolution kind (tex, pdf, json, …)

    @property
    def folder(self) -> str:
        return str(PurePosixPath(self.path).parent)

    @property
    def name(self) -> str:
        return PurePosixPath(self.path).name

    @property
    def stem(self) -> str:
        return PurePosixPath(self.path).stem


@dataclass
class DocumentPlan:
    primary: FileRef
    title: str
    parts: list[tuple[FileRef, DocumentSourceRole]] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    missing_includes: list[str] = field(default_factory=list)


def load_section_file_sets(path: Path = REPORT_SCHEMAS_YAML) -> list[list[str]]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return [[entry["file"] for entry in spec["files"]] for spec in data.get("section_file_sets", [])]


def _uncommented(text: str) -> str:
    return "\n".join(line.split("%", 1)[0] for line in text.splitlines())


def _includes(text: str, base: PurePosixPath) -> list[str]:
    found = [str(base / name.strip()) for name in INCLUDE.findall(text)]
    found += [str(base / directory.strip() / name.strip()) for directory, name in IMPORT.findall(text)]
    return [p if PurePosixPath(p).suffix else p + ".tex" for p in found]


def _normalize(path: str) -> str:
    parts: list[str] = []
    for part in PurePosixPath(path).parts:
        if part == "..":
            if parts:
                parts.pop()
        elif part not in (".", ""):
            parts.append(part)
    return "/".join(parts).casefold()


def _find(include: str, master_folder: str, by_path: Mapping[str, FileRef]) -> tuple[FileRef | None, str]:
    """An include path is relative to the folder LaTeX compiles from: the master's folder, or (common
    with masters in ``Main_Files/``) an ancestor such as the project root. The nearest match wins."""
    relative = (
        PurePosixPath(include).relative_to(master_folder) if include.startswith(master_folder + "/") else None
    )
    key = _normalize(include)
    if key in by_path or relative is None:
        return by_path.get(key), key
    base = PurePosixPath(master_folder)
    for ancestor in base.parents:
        candidate = _normalize(str(ancestor / relative))
        if candidate in by_path:
            return by_path[candidate], candidate
    return None, key


def assemble(
    files: Sequence[FileRef],
    read_text: Callable[[FileRef], str],
    section_file_sets: Sequence[Sequence[str]] = (),
) -> list[DocumentPlan]:
    by_path = {_normalize(f.path): f for f in files}
    claimed: set[str] = set()
    plans: list[DocumentPlan] = []

    tex = [f for f in files if f.kind == "tex"]
    text_of = {f.path: _uncommented(read_text(f)) for f in tex}
    masters = [f for f in tex if MASTER.search(text_of[f.path])]
    masters_by_folder: dict[str, list[FileRef]] = defaultdict(list)
    for master in masters:
        masters_by_folder[master.folder].append(master)

    for folder, folder_masters in sorted(masters_by_folder.items()):
        for master in sorted(folder_masters, key=lambda f: f.path):
            plan = DocumentPlan(primary=master, title=master.stem)
            if len(folder_masters) > 1:
                plan.conflicts.append(f"two masters in folder {folder}")
            seen, queue = {_normalize(master.path)}, [master]
            while queue:
                current = queue.pop(0)
                for include in _includes(text_of.get(current.path, ""), PurePosixPath(master.folder)):
                    part, key = _find(include, master.folder, by_path)
                    if key in seen:
                        continue
                    seen.add(key)
                    if part is None:
                        plan.missing_includes.append(include)
                        continue
                    if part.path not in claimed and part not in folder_masters:
                        plan.parts.append((part, DocumentSourceRole.PART))
                        claimed.add(part.path)
                        queue.append(part)
            twin = by_path.get(_normalize(str(PurePosixPath(master.folder) / f"{master.stem}.pdf")))
            if twin is not None and twin.path not in claimed:
                plan.parts.append((twin, DocumentSourceRole.VISUAL_TWIN))
                claimed.add(twin.path)
            claimed.add(master.path)
            plans.append(plan)

    orphans: dict[str, list[FileRef]] = defaultdict(list)
    for f in tex:
        if f.path not in claimed:
            orphans[f.folder].append(f)
    for folder, group in sorted(orphans.items()):
        group.sort(key=lambda f: f.name)
        lone = len(group) == 1
        plan = DocumentPlan(
            primary=group[0], title=group[0].stem if lone else PurePosixPath(folder).name or group[0].stem
        )
        plan.parts = [(f, DocumentSourceRole.PART) for f in group[1:]]
        reason = "not included by any master" if masters else "no master found"
        where = "the top folder" if folder == "." else f"folder {folder}"
        plan.notes.append(f"{reason} in {where}, assembled by filename")
        claimed.update(f.path for f in group)
        plans.append(plan)

    by_folder: dict[str, dict[str, FileRef]] = defaultdict(dict)
    for f in files:
        if f.path not in claimed:
            by_folder[f.folder][f.name.casefold()] = f
    for folder, names in sorted(by_folder.items()):
        for file_set in section_file_sets:
            present = [names[n.casefold()] for n in file_set if n.casefold() in names]
            present = [f for f in present if f.path not in claimed]
            if len(present) < 2:
                continue
            plan = DocumentPlan(primary=present[0], title=PurePosixPath(folder).name or present[0].stem)
            plan.parts = [(f, DocumentSourceRole.PART) for f in present[1:]]
            claimed.update(f.path for f in present)
            plans.append(plan)

    for f in sorted(files, key=lambda f: f.path):
        if f.path not in claimed:
            plans.append(DocumentPlan(primary=f, title=f.stem))
            claimed.add(f.path)
    return plans


def sets_from_mapping(data: Mapping) -> list[list[str]]:
    return [[entry["file"] for entry in spec["files"]] for spec in data.get("section_file_sets", [])]
