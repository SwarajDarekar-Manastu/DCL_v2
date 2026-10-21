"""The outbound IP sanitizer (file 07 §6): internal identifiers never leave the network in a search query.

Every `external_search` call passes the planner's generic need through `sanitize_query` first; the
provider sees only the returned text. Removed: organization names, project codenames and proprietary
terms (`pipeline_config` `answer.proprietary_terms`), internal identifiers (test plans, runs, part and
drawing numbers), file and folder names, paths, internal URLs, e-mail addresses, people's names from the
supplied list, and precise measurements (any value with a decimal fraction). Kept: public standard ids
(ECSS, ISO, MIL-STD…), public vocabulary seeded from `config/aerospace_synonyms.yaml` (HTP, LMP-103S), and
round class sizes ("300 bar", "5 N"). The trace logs the sanitized text and the SHA-256 of the original.
"""

import hashlib
import re
import unicodedata
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field

from backend.indexing.identifiers import JOINED, SPACED, SPACED_STOPWORDS

DEFAULT_ORGANIZATION_NAMES = ("Manastu Space", "Manastu")
PUBLIC_STANDARD_PREFIXES = (
    "ECSS",
    "ISO",
    "MIL",
    "AIAA",
    "ASTM",
    "DIN",
    "EN",
    "NASA",
    "SAE",
    "ASME",
    "IEC",
    "GOST",
    "JIS",
    "GB",
    "BS",
)
MIN_CONTENT_WORDS = 2
FUNCTION_WORDS = frozenset(
    "a an the and or of in on at to for from by with per as is are was were be did does do why what how "
    "which when where who whom this that these those it its our we us during after before about into "
    "than then".split()
)

EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b")
URL = re.compile(r"\bhttps?://\S+|\bwww\.\S+", re.IGNORECASE)
# two or more separators between space-free segments: APU/TP19/run3, C:\\data\\tp19 (never "1/4 inch")
PATH = re.compile(r"(?:[A-Za-z]:)?(?:[\\/]?[\w.-]+)(?:[\\/][\w.-]+){2,}")
FILENAME = re.compile(
    r"\b[\w-]+\.(?:pdf|docx?|pptx?|xlsx?|csv|dat|dat_fail|cfg|tdms|py|ipynb|json|tex|drawio|xsd|zip|7z|"
    r"wbpz|stp|step|stl|mp4|mov|jpe?g|png|heic|npy|txt|md)\b",
    re.IGNORECASE,
)
RUN_WORDS = re.compile(
    r"\b(?:test\s*plan|test\s*run|hot[\s-]*fire|firing|campaign|run|trial|test|tp|sub[\s-]*run)\s*(?:no\.?|#)?\s*\d+\b",
    re.IGNORECASE,
)
DECIMAL_MEASUREMENT = re.compile(
    r"[-+]?\d+[.,]\d+\s*(?:[%°]|[A-Za-zµμΩ°/²³()]+(?:\s*\([ag]\))?)?", re.IGNORECASE
)
SPACES = re.compile(r"\s{2,}")
DANGLING = re.compile(r"\(\s*\)|\[\s*\]|\s+([,;:.)])|([(])\s+")


class SanitizerRefused(ValueError):
    """Too little of the query is left to search for; the engine must not call the provider."""


@dataclass(frozen=True)
class SanitizedQuery:
    text: str
    original_sha256: str
    removed: dict[str, int] = field(default_factory=dict)


def _term_pattern(terms: Iterable[str]) -> re.Pattern[str] | None:
    cleaned = sorted({t.strip() for t in terms if t and t.strip()}, key=len, reverse=True)
    if not cleaned:
        return None
    return re.compile(r"(?<!\w)(?:" + "|".join(re.escape(t) for t in cleaned) + r")(?!\w)", re.IGNORECASE)


def _is_public(token: str, public_terms: set[str]) -> bool:
    upper = token.upper()
    return upper in public_terms or upper.split("-")[0] in PUBLIC_STANDARD_PREFIXES


def sanitize_query(
    query: str,
    *,
    proprietary_terms: Iterable[str] = (),
    organization_names: Iterable[str] = DEFAULT_ORGANIZATION_NAMES,
    people: Iterable[str] = (),
    folder_names: Iterable[str] = (),
    public_terms: Iterable[str] = (),
) -> SanitizedQuery:
    """The query with internal material removed; SanitizerRefused if nothing useful is left."""
    original_sha256 = hashlib.sha256(query.encode("utf-8")).hexdigest()
    text = unicodedata.normalize("NFKC", query)
    removed: Counter[str] = Counter()
    public = {t.strip().upper() for t in public_terms if t.strip()}

    def strip(kind: str, pattern: re.Pattern[str] | None, keep=lambda _m: False) -> None:
        nonlocal text
        if pattern is None:
            return

        def replace(match: re.Match[str]) -> str:
            if keep(match):
                return match.group(0)
            removed[kind] += 1
            return " "

        text = pattern.sub(replace, text)

    strip("email", EMAIL)
    strip("url", URL)
    strip("file_name", FILENAME)
    strip("path", PATH)
    strip("organization", _term_pattern(organization_names))
    strip("proprietary_term", _term_pattern(proprietary_terms))
    strip("person", _term_pattern(people))
    strip("folder_name", _term_pattern(folder_names))
    strip("test_or_run_id", RUN_WORDS)
    strip("measurement", DECIMAL_MEASUREMENT)
    strip("identifier", JOINED, keep=lambda m: _is_public(m.group(0), public))
    strip(
        "identifier", SPACED, keep=lambda m: m.group(1) in SPACED_STOPWORDS or _is_public(m.group(1), public)
    )

    text = DANGLING.sub(lambda m: m.group(1) or m.group(2) or "", text)
    text = SPACES.sub(" ", text).strip(" ,;:-")
    content_words = [w for w in re.findall(r"[^\W\d_]{2,}", text) if w.lower() not in FUNCTION_WORDS]
    if len(content_words) < MIN_CONTENT_WORDS:
        raise SanitizerRefused("the sanitized query has fewer than two content words; no external search")
    return SanitizedQuery(text=text, original_sha256=original_sha256, removed=dict(removed))
