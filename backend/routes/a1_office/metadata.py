"""A1 deterministic metadata (file 04 §2, file 03 §A1.3 footers, §A1.12 step 1): the L1 fields a PDF yields.

Inputs are the page-1 text, the page headers and footers Docling separated (furniture), the title, the file
name and S1's FolderContext. First hit wins; every field records where it came from in `sources`.

- External identity: DOI, arXiv id, ISBN, a journal or proceedings running head, a copyright line, a vendor
  from `config/vendors.yaml` (an `internal_equipment` vendor counts only with a datasheet/brochure cue),
  a URL footer. Any of them turns `internal` into `external_kept`, never the reverse.
- Markings: classification (`CONFIDENTIAL`, `INTERNAL`, `EXPORT CONTROLLED`, `ITAR`, `RESTRICTED`; the last
  three raise SENSITIVE_CONTENT HARD), revision (`DRAFT`, `ISSUE n`, `REV x`, `SUPERSEDED`, `OBSOLETE`,
  `FINAL`), standard id and revision.
- doc_kind by rule (`ECSS-` → standard, Test Plan → test_plan, Report/Results → test_report, FMEA/Risk →
  risk_assessment, Calibration → calibration, DOI/journal → academic_paper, vendor + datasheet cue →
  datasheet, vendor + brochure cue → vendor_brochure), else `unknown` and L2 decides.
- trust tier from origin and kind; number locale from decimal patterns; language from the page triage.
"""

import re
from collections import Counter
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path

import yaml

from backend.dispatcher.contract import DocumentFields, ExternalIds, Flag, FlagAnchor
from backend.dispatcher.folder_context import FolderContext
from backend.postgres.enums import DocKind, FlagSeverity, FlagType, SourceOrigin

VENDORS_FILE = Path(__file__).resolve().parents[3] / "config" / "vendors.yaml"
DOI = re.compile(r"\b10\.\d{4,9}/[^\s\"<>]+")
ARXIV = re.compile(r"\barXiv:\s*(\d{4}\.\d{4,5}(?:v\d+)?)", re.IGNORECASE)
ISBN = re.compile(r"\bISBN(?:-1[03])?:?\s*((?:97[89][- ]?)?(?:\d[- ]?){9}[\dX])\b", re.IGNORECASE)
RUNNING_HEAD = re.compile(
    r"^\s*((?:Journal|Proceedings|Transactions|Acta|Annals|Letters|Conference|Zeitschrift|Revue)\b[^,\n]{3,120}?)"
    r"\s*(?:,\s*Vol\.|,\s*\d{4}|\(|$)",
    re.IGNORECASE | re.MULTILINE,
)
COPYRIGHT = re.compile(r"(?:©|\(c\)|copyright)\s*(?:\d{4}\s*)?([A-Z][\w&.,' -]{2,80})", re.IGNORECASE)
URL = re.compile(r"\b(?:https?://)?(?:www\.)?([a-z0-9-]+(?:\.[a-z0-9-]+)+)(?:/\S*)?", re.IGNORECASE)
STANDARD = re.compile(
    r"\b(ECSS-[EMQU]-(?:ST|HB|AS|TM)-\d+(?:-\d+)*[A-Z]?)(?:\s*Rev\.?\s*(\d+))?"
    r"|\b(ISO\s?\d{3,5}(?:-\d+)?|MIL-STD-\d+[A-Z]?|AIAA\s?S-\d+[A-Z]?|DIN\s(?:EN\s)?\d{3,5}|GOST\s?R?\s?\d+|JIS\s[A-Z]\s?\d+|GB/T\s?\d+)"
)
CLASSIFICATION = ("EXPORT CONTROLLED", "ITAR", "RESTRICTED", "CONFIDENTIAL", "INTERNAL")
HARD_MARKINGS = frozenset({"EXPORT CONTROLLED", "ITAR", "RESTRICTED"})
REVISION = re.compile(
    r"\b(DRAFT|SUPERSEDED|OBSOLETE|FINAL|ISSUE\s+\d+(?:\s+REV\s+\d+)?|REV(?:ISION)?\.?\s+[A-Z0-9]{1,3})\b"
)
DATASHEET_CUES = re.compile(
    r"\b(datasheet|data sheet|datenblatt|technical specification|technische daten|produktinformation|"
    r"fiche technique|specification sheet)\b|仕様書|规格书",
    re.IGNORECASE,
)
BROCHURE_CUES = re.compile(
    r"\b(brochure|broschüre|catalogue|catalog|katalog|product overview)\b", re.IGNORECASE
)
KIND_RULES = (
    (re.compile(r"\bECSS-", re.IGNORECASE), DocKind.STANDARD),
    (re.compile(r"\btest[ _-]?plan\b", re.IGNORECASE), DocKind.TEST_PLAN),
    (re.compile(r"\bFMEA\b|\brisk\b", re.IGNORECASE), DocKind.RISK_ASSESSMENT),
    (re.compile(r"\bcalibration\b|\bkalibrier", re.IGNORECASE), DocKind.CALIBRATION),
    (re.compile(r"\breport\b|\bresults\b|\bbericht\b", re.IGNORECASE), DocKind.TEST_REPORT),
)
COMMA_DECIMAL = re.compile(r"(?<![\d.,])\d{1,4},\d{1,3}(?![\d,])")
DOT_DECIMAL = re.compile(r"(?<![\d.,])\d{1,4}\.\d{1,3}(?![\d.])")
TIER_BY_KIND = {
    DocKind.STANDARD: 3,
    DocKind.DATASHEET: 4,
    DocKind.VENDOR_BROCHURE: 4,
    DocKind.ACADEMIC_PAPER: 5,
    DocKind.ARTICLE: 5,
    DocKind.BOOK_EXCERPT: 5,
    DocKind.CONFERENCE_PAPER: 5,
}


@dataclass(frozen=True)
class Vendor:
    id: str
    name: str
    aliases: tuple[str, ...]
    case_sensitive: frozenset[str]
    domains: tuple[str, ...]
    internal_equipment: bool


@cache
def load_vendors(path: Path = VENDORS_FILE) -> tuple[Vendor, ...]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return tuple(
        Vendor(
            id=v["id"],
            name=v["name"],
            aliases=tuple(v.get("aliases", [])) or (v["name"],),
            case_sensitive=frozenset(v.get("case_sensitive_aliases", [])),
            domains=tuple(v.get("domains", [])),
            internal_equipment=bool(v.get("internal_equipment", False)),
        )
        for v in data.get("vendors", [])
    )


def _vendor_pattern(alias: str, case_sensitive: bool) -> re.Pattern[str]:
    return re.compile(rf"(?<!\w){re.escape(alias)}(?!\w)", 0 if case_sensitive else re.IGNORECASE)


def find_vendor(text: str, vendors: tuple[Vendor, ...]) -> Vendor | None:
    for vendor in vendors:
        for alias in vendor.aliases:
            if _vendor_pattern(alias, alias in vendor.case_sensitive or len(alias) < 4).search(text):
                return vendor
    return None


@dataclass
class Metadata:
    fields: DocumentFields
    flags: list[Flag] = field(default_factory=list)
    sources: dict[str, str] = field(default_factory=dict)


def number_locale(text: str) -> str | None:
    commas, dots = len(COMMA_DECIMAL.findall(text)), len(DOT_DECIMAL.findall(text))
    if not commas and not dots:
        return None
    return "comma" if commas > dots else "dot"


def humanize(file_name: str) -> str:
    stem = Path(file_name).stem
    return re.sub(r"\s+", " ", re.sub(r"[_]+", " ", stem)).strip()


def extract_metadata(
    *,
    file_name: str,
    title: str | None,
    first_page_text: str,
    full_text: str,
    furniture: list[str],
    folder: FolderContext,
    page_languages: list[str | None],
    page_count: int,
    vendors: tuple[Vendor, ...] | None = None,
) -> Metadata:
    vendors = load_vendors() if vendors is None else vendors
    sources: dict[str, str] = {}
    head = "\n".join([*furniture, first_page_text])
    margins = "\n".join(furniture)

    title_value = (title or "").strip()
    sources["title"] = "docling_heading" if title_value else "filename"
    title_value = title_value or humanize(file_name)

    external = ExternalIds()
    if doi := DOI.search(head):
        external = external.model_copy(update={"doi": doi.group(0).rstrip(".,;)")})
    if arxiv := ARXIV.search(head):
        external = external.model_copy(update={"arxiv": arxiv.group(1)})
    if isbn := ISBN.search(head):
        external = external.model_copy(update={"isbn": isbn.group(1)})
    running_head = RUNNING_HEAD.search(head)
    publisher = running_head.group(1).strip() if running_head else None
    if publisher:
        sources["publisher"] = "running_head"
    elif copyright_line := COPYRIGHT.search(margins):
        publisher = copyright_line.group(1).strip().rstrip(".,")
        sources["publisher"] = "copyright_line"

    cue_text = f"{title_value}\n{file_name}"
    datasheet_cue = bool(DATASHEET_CUES.search(cue_text))
    brochure_cue = bool(BROCHURE_CUES.search(cue_text))
    vendor = find_vendor(head, vendors)
    footer_domains = {m.group(1).lower() for m in URL.finditer(margins)}
    vendor_counts = vendor is not None and (
        not vendor.internal_equipment
        or datasheet_cue
        or brochure_cue
        or any(
            d in footer_domains or any(f.endswith("." + d) for f in footer_domains) for d in vendor.domains
        )
    )
    if vendor_counts and not publisher:
        publisher = vendor.name
        sources["publisher"] = "vendor"

    origin = folder.source_origin
    sources["source_origin"] = "folder"
    if origin == SourceOrigin.INTERNAL:
        for name, hit in (
            ("doi", external.doi),
            ("arxiv", external.arxiv),
            ("isbn", external.isbn),
            ("running_head", running_head),
            ("vendor", vendor_counts),
        ):
            if hit:
                origin, sources["source_origin"] = SourceOrigin.EXTERNAL_KEPT, name
                break

    kind = DocKind.UNKNOWN
    sources["doc_kind"] = "none"
    if external.doi or external.arxiv or running_head:
        kind, sources["doc_kind"] = DocKind.ACADEMIC_PAPER, "doi_or_journal"
    elif vendor_counts and datasheet_cue:
        kind, sources["doc_kind"] = DocKind.DATASHEET, "vendor_and_datasheet_cue"
    elif vendor_counts and brochure_cue:
        kind, sources["doc_kind"] = DocKind.VENDOR_BROCHURE, "vendor_and_brochure_cue"
    else:
        for pattern, rule_kind in KIND_RULES:
            if pattern.search(f"{file_name}\n{title_value}"):
                kind, sources["doc_kind"] = rule_kind, f"rule:{pattern.pattern}"
                break

    standard_id = standard_revision = None
    if standard := STANDARD.search(f"{margins}\n{title_value}\n{first_page_text}"):
        standard_id = standard.group(1) or standard.group(3)
        standard_revision = standard.group(2)
        if standard.group(1) and kind is DocKind.UNKNOWN:
            kind, sources["doc_kind"] = DocKind.STANDARD, "standard_id"

    marking = next((m for m in CLASSIFICATION if re.search(rf"\b{m}\b", head)), None)
    revision = REVISION.search(margins) or REVISION.search(title_value)
    flags = []
    if marking in HARD_MARKINGS:
        flags.append(
            Flag(flag_type=FlagType.SENSITIVE_CONTENT, severity=FlagSeverity.HARD, anchor=FlagAnchor(page=1))
        )

    tier = TIER_BY_KIND.get(kind) or (2 if origin == SourceOrigin.INTERNAL else folder.trust_tier)
    if origin == SourceOrigin.EXTERNAL_KEPT and kind not in TIER_BY_KIND:
        tier = 4 if vendor_counts else 5
    languages = [lang for lang in page_languages if lang]
    language = Counter(languages).most_common(1)[0][0] if languages else None

    fields = DocumentFields(
        title=title_value,
        doc_kind=kind,
        source_origin=origin,
        trust_tier=tier,
        publisher=publisher,
        external_ids=external,
        test_plan_id=folder.test_plan_id,
        test_run_id=folder.test_run_id,
        hardware_item=folder.hardware_item,
        standard_id=standard_id,
        standard_revision=standard_revision,
        revision_marker=revision.group(1) if revision else None,
        classification_marking=marking,
        language=language,
        languages_detected=sorted(set(languages)),
        number_locale=number_locale(full_text),
        page_count=page_count,
        unit_count=page_count,
    )
    return Metadata(fields, flags, sources)
