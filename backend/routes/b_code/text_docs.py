"""Tooling documents of Route B (file 03 §6 step 7, edge cases): Markdown, plain text, ``.bat``, notebooks.

- Markdown: ATX (``#``) and setext headings make the section breadcrumb; each paragraph, list or fenced code
  block is one passage with its line range (fences protect ``#`` lines inside code).
- Plain text and batch files: windows of ``TEXT_WINDOW`` lines; ``requirements*.txt`` lines become
  ``dependency`` mentions.
- Notebooks (``.ipynb``, nbformat 4): one node per cell; Markdown cells follow the Markdown rules, code
  cells are code passages; outputs are ignored. A cell's line is where its ``"cell_type"`` key sits in the
  raw JSON, so a citation opens the file there.
"""

import json
import re
from dataclasses import dataclass, field

TEXT_WINDOW = 40
ATX = re.compile(r"^\s{0,3}(#{1,6})\s+(.*?)\s*#*\s*$")
SETEXT = re.compile(r"^\s{0,3}(=+|-+)\s*$")
FENCE = re.compile(r"^\s{0,3}(```|~~~)")
REQUIREMENT = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*(?:\[[^\]]*\])?)\s*((?:[=<>!~]=?|===)\s*[^\s;#]+)?")


@dataclass
class Passage:
    text: str
    start: int
    end: int
    crumbs: list[str] = field(default_factory=list)
    kind: str = "text"  # text, code, cell_code, cell_markdown
    meta: dict = field(default_factory=dict)


def markdown_passages(
    text: str, first_line: int = 1, crumbs: list[str] | None = None
) -> tuple[list[Passage], list[str]]:
    """Passages of a Markdown text and the heading path at its end (a notebook carries it on)."""
    lines = text.split("\n")
    stack: list[tuple[int, str]] = [(0, c) for c in (crumbs or [])]
    passages: list[Passage] = []
    block: list[str] = []
    block_start = 0
    in_fence = False

    def path() -> list[str]:
        return [title for _, title in stack]

    def flush(end: int) -> None:
        nonlocal block
        body = "\n".join(block).strip("\n")
        if body.strip():
            kind = "code" if body.lstrip().startswith(("```", "~~~")) else "text"
            passages.append(Passage(body, first_line + block_start, first_line + end, path(), kind))
        block = []

    for i, line in enumerate(lines):
        if FENCE.match(line):
            if not in_fence:
                flush(i - 1)
                block_start = i
            in_fence = not in_fence
            block.append(line)
            if not in_fence:
                flush(i)
            continue
        if in_fence:
            block.append(line)
            continue
        heading = ATX.match(line)
        setext = SETEXT.match(line) if block and len(block) == 1 and block[0].strip() else None
        if heading or setext:
            if setext:
                title, level = block[0].strip(), 1 if setext.group(1).startswith("=") else 2
                block = []
            else:
                flush(i - 1)
                title, level = heading.group(2), len(heading.group(1))
            stack[:] = [(lv, t) for lv, t in stack if lv < level] + [(level, title)]
            block_start = i + 1
            continue
        if not line.strip():
            flush(i - 1)
            block_start = i + 1
            continue
        if not block:
            block_start = i
        block.append(line)
    flush(len(lines) - 1)
    return passages, path()


def text_windows(text: str) -> list[Passage]:
    lines = text.split("\n")
    out = []
    for start in range(0, len(lines), TEXT_WINDOW):
        chunk = lines[start : start + TEXT_WINDOW]
        while chunk and not chunk[-1].strip():
            chunk.pop()
        if any(line.strip() for line in chunk):
            out.append(Passage("\n".join(chunk), start + 1, start + len(chunk)))
    return out


def requirements(text: str) -> list[str]:
    found = []
    for line in text.split("\n"):
        stripped = line.split("#", 1)[0].strip()
        if not stripped or stripped.startswith(("-", "--")):
            continue
        match = REQUIREMENT.match(stripped)
        if match:
            found.append((match.group(1) + (match.group(2) or "").replace(" ", "")).strip())
    return found


def is_requirements(name: str) -> bool:
    return bool(re.fullmatch(r"requirements[\w.-]*\.txt|constraints\.txt", name.casefold()))


def notebook_passages(text: str) -> tuple[list[Passage], str | None]:
    """(passages, kernel language)."""
    data = json.loads(text)
    cell_lines = [text.count("\n", 0, m.start()) + 1 for m in re.finditer(r'"cell_type"\s*:', text)]
    kernel = (data.get("metadata", {}).get("kernelspec", {}) or {}).get("language") or (
        data.get("metadata", {}).get("language_info", {}) or {}
    ).get("name")
    passages: list[Passage] = []
    crumbs: list[str] = []
    for index, cell in enumerate(data.get("cells", [])):
        source = cell.get("source", "")
        source = "".join(source) if isinstance(source, list) else str(source)
        line = cell_lines[index] if index < len(cell_lines) else 1
        if not source.strip():
            continue
        if cell.get("cell_type") == "markdown":
            found, crumbs = markdown_passages(source, line, crumbs)
            for passage in found:
                passage.start = passage.end = line
                passage.meta = {"cell": index + 1, "cell_type": "markdown"}
                passage.kind = "cell_markdown"
            passages += found
        else:
            passages.append(
                Passage(
                    source.rstrip(),
                    line,
                    line,
                    list(crumbs),
                    "cell_code",
                    {
                        "cell": index + 1,
                        "cell_type": cell.get("cell_type", "code"),
                        "execution_count": cell.get("execution_count"),
                    },
                )
            )
    return passages, kernel
