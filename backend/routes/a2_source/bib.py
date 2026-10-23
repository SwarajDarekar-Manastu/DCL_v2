"""BibTeX entries (file 03 §A2.2 step 6): ``reference`` mentions and the text a ``\\cite`` resolves to.

A small tolerant parser: ``@type{key, field = {…} | "…" | 123, …}``; ``@string``, ``@comment`` and
``@preamble`` are skipped; braces and accents are reduced to plain Unicode text.
"""

import re
from dataclasses import dataclass, field

ENTRY = re.compile(r"@(\w+)\s*[{(]\s*([^,\s]+)\s*,", re.IGNORECASE)
SKIPPED_TYPES = frozenset({"string", "comment", "preamble"})


@dataclass(frozen=True)
class BibEntry:
    key: str
    entry_type: str
    fields: dict[str, str] = field(default_factory=dict)


def _plain(value: str) -> str:
    try:
        from pylatexenc.latex2text import LatexNodes2Text

        value = LatexNodes2Text(math_mode="verbatim").latex_to_text(value)
    except ImportError:  # parse group absent: keep the raw text without braces
        value = value.replace("{", "").replace("}", "")
    return re.sub(r"\s+", " ", value).strip()


def _value(text: str, pos: int) -> tuple[str, int]:
    while pos < len(text) and text[pos].isspace():
        pos += 1
    if pos < len(text) and text[pos] == "{":
        depth, start = 0, pos
        while pos < len(text):
            if text[pos] == "{":
                depth += 1
            elif text[pos] == "}":
                depth -= 1
                if depth == 0:
                    return text[start + 1 : pos], pos + 1
            pos += 1
        return text[start + 1 :], len(text)
    if pos < len(text) and text[pos] == '"':
        end = pos + 1
        depth = 0
        while end < len(text):
            if text[end] == "{":
                depth += 1
            elif text[end] == "}":
                depth -= 1
            elif text[end] == '"' and depth == 0:
                break
            end += 1
        return text[pos + 1 : end], end + 1
    match = re.compile(r"[^,}\s]+").match(text, pos)
    return (match.group(0), match.end()) if match else ("", pos)


def parse_bib(text: str) -> list[BibEntry]:
    entries = []
    for match in ENTRY.finditer(text):
        entry_type = match.group(1).lower()
        if entry_type in SKIPPED_TYPES:
            continue
        fields: dict[str, str] = {}
        pos = match.end()
        while pos < len(text):
            name = re.compile(r"\s*([A-Za-z][\w-]*)\s*=\s*").match(text, pos)
            if name is None:
                break
            value, pos = _value(text, name.end())
            fields[name.group(1).lower()] = _plain(value)
            separator = re.compile(r"\s*,?").match(text, pos)
            pos = separator.end() if separator else pos
            if pos < len(text) and text[pos] in "})":
                break
        entries.append(BibEntry(match.group(2), entry_type, fields))
    return entries


def _surname(author: str) -> str:
    author = author.strip()
    if "," in author:
        return author.split(",", 1)[0].strip()
    return author.split()[-1] if author.split() else author


def authors_short(authors: str) -> str:
    names = [a for a in re.split(r"\s+and\s+", authors) if a.strip()]
    if not names:
        return ""
    if len(names) == 1:
        return _surname(names[0])
    if len(names) == 2:
        return f"{_surname(names[0])} and {_surname(names[1])}"
    return f"{_surname(names[0])} et al."


def cite_text(entry: BibEntry) -> str:
    """``Smith et al. 2020, Title`` (inside the brackets the walker adds)."""
    if entry.entry_type == "bibitem":
        return entry.fields.get("text", entry.key)
    head = " ".join(filter(None, [authors_short(entry.fields.get("author", "")), entry.fields.get("year")]))
    title = entry.fields.get("title")
    return ", ".join(filter(None, [head, title])) or entry.key


def reference_text(entry: BibEntry) -> str:
    """The full reference for a ``reference`` mention."""
    if entry.entry_type == "bibitem":
        return entry.fields.get("text", entry.key)
    f = entry.fields
    venue = f.get("journal") or f.get("booktitle") or f.get("publisher") or f.get("institution")
    parts = [
        f.get("author"),
        f"({f['year']})" if f.get("year") else None,
        f.get("title"),
        venue,
        f"doi:{f['doi']}" if f.get("doi") else None,
    ]
    return ". ".join(p.rstrip(".") for p in parts if p) or entry.key
