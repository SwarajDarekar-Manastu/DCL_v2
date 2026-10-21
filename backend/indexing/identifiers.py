"""Identifier extraction shared by the indexer (`document_nodes.content_codes`) and the query side (04 §6).

Aerospace identifiers must match exactly: PT-104, ECSS-E-ST-35C, C-103, TP37, INJ-14, SV-1, LMP-103S.
`extract_identifiers` finds identifier-like tokens case-insensitively, keeps the full multi-segment form
(ECSS-E-ST-35C, never ST-35C alone), uppercases it, and adds the separator-less variant (PT104, ECSSEST35C),
so "C103" in a query meets "C-103" in a document. The BM25 field indexes the joined tokens with a whitespace
tokenizer and no stemming; the query side runs this same function on the user's text.
"""

import re
import unicodedata

DASHES = dict.fromkeys(map(ord, "‐‑‒–—―−"), "-")

# letters (optionally several dash-joined letter segments), an optional separator, then a segment that holds a
# digit, then further dash-joined segments: TP37, PT-101, ECSS-E-ST-35C, AF-M315E, LMP-103S, MIL-STD-1522A
JOINED = re.compile(
    r"(?<![A-Za-z0-9])"
    r"[A-Za-z]{1,8}(?:[-_][A-Za-z]{1,8})*"
    r"[-_]?[A-Za-z]{0,3}[0-9][A-Za-z0-9]*"
    r"(?:[-_][A-Za-z0-9]*[0-9][A-Za-z0-9]*|[-_][A-Za-z]{1,3}(?![A-Za-z]))*"
    r"(?![A-Za-z0-9])"
)
# space-separated tag written in capitals: "PT 101", "INJ 14", "SV 1" (lowercase "page 5" is prose)
SPACED = re.compile(r"(?<![A-Za-z0-9])([A-Z]{2,5}) ([0-9]{1,5}[A-Z]?)(?![A-Za-z0-9])")
SPACED_STOPWORDS = frozenset(
    {"FIG", "TAB", "PAGE", "NO", "NR", "REV", "ISSUE", "SEC", "EQ", "REF", "ANNEX", "PART"}
)
SEPARATORS = re.compile(r"[-_]")
# squared and cubed units look like tags (cm2, m3) but are not identifiers
UNIT_TOKENS = frozenset(f"{u}{p}" for u in ("M", "CM", "MM", "KM", "DM", "S", "IN", "FT") for p in ("2", "3"))


def _normalize(text: str) -> str:
    return unicodedata.normalize("NFKC", text).translate(DASHES)


def extract_identifiers(text: str) -> list[str]:
    """Identifier tokens in first-seen order, each uppercased, followed by its separator-less variant."""
    text = _normalize(text)
    found: list[tuple[int, str]] = [(m.start(), m.group(0)) for m in JOINED.finditer(text)]
    found += [
        (m.start(), f"{m.group(1)}-{m.group(2)}")
        for m in SPACED.finditer(text)
        if m.group(1) not in SPACED_STOPWORDS
    ]
    tokens: list[str] = []
    seen: set[str] = set()
    for _, raw in sorted(found):
        canonical = raw.upper().replace("_", "-")
        if canonical in UNIT_TOKENS:
            continue
        for token in (canonical, SEPARATORS.sub("", canonical)):
            if token not in seen and any(ch.isalpha() for ch in token):
                seen.add(token)
                tokens.append(token)
    return tokens


def content_codes(text: str) -> str:
    """The value of `document_nodes.content_codes`: identifier tokens joined by single spaces."""
    return " ".join(extract_identifiers(text))
