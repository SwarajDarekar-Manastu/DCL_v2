"""First-page language and DOI check over landed library PDFs (DECISIONS 2026-10-22, allowlist ruling).

Finds the non-English material the MULTILINGUAL benchmark cases need, before Route A1 runs on it:
for each LANDED PDF under a root (default ``APS - Library``) the text layer of page 1 (page 2 added when
page 1 is nearly empty) is read with pypdfium2, its language guessed and a DOI looked for. No Gemini,
nothing written to the database: the output is a TSV for S5 and the Lead.

Language without a model dependency (file 04 names fastText/langdetect for documents; neither is in the
lock file): a script census decides ja/zh/ko/ru/ar/el; Latin text is scored by the share of each
language's function words. A page without a text layer is ``no_text`` (scans: triage reads them later).

CLI (parse dependency group, stack DB and MinIO from the environment):
``uv run --group parse python -m backend.sync.language_check --out data/library_languages.tsv``
"""

import argparse
import csv
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass

DOI = re.compile(r"\b10\.\d{4,9}/[^\s\"<>]+")
WORD = re.compile(r"[^\W\d_]+", re.UNICODE)
MIN_LETTERS = 40
MIN_HITS = 4
MIN_SHARE = 0.06

# Function words of two letters or more: single letters ("a", "e", "o", "y") also occur in English
# patent numbering and slide text and made English pages score as Portuguese.
STOPWORDS: dict[str, frozenset[str]] = {
    "en": frozenset("the of and to in is for with on that by this are be as from at an or which it".split()),
    "de": frozenset(
        "der die das und ist mit von den für nicht im zu auf ein eine dem des bei sich werden".split()
    ),
    "fr": frozenset("le la les et des est pour dans une du en sur au par que qui avec sont ce aux".split()),
    "es": frozenset("el la los las de que en un una por con para es del se al como su".split()),
    "it": frozenset("il lo la gli le di che un una per con del della sono nel alla dei".split()),
    "pt": frozenset("os as de que em um uma para com do da não por dos no na".split()),
    "nl": frozenset("de het een en van is dat op te in met voor zijn niet aan door".split()),
}


def _script(ch: str) -> str | None:
    code = ord(ch)
    if 0x3040 <= code <= 0x30FF:
        return "kana"
    if 0x4E00 <= code <= 0x9FFF or 0x3400 <= code <= 0x4DBF:
        return "han"
    if 0xAC00 <= code <= 0xD7AF:
        return "hangul"
    if 0x0400 <= code <= 0x04FF:
        return "cyrillic"
    if 0x0600 <= code <= 0x06FF:
        return "arabic"
    if 0x0370 <= code <= 0x03FF:
        return "greek"
    if ch.isalpha():
        return "latin"
    return None


@dataclass(frozen=True)
class Guess:
    language: str  # BCP-47 primary tag, "und" (undetermined) or "no_text"
    confidence: float
    letters: int


def detect_language(text: str) -> Guess:
    scripts = Counter(s for s in map(_script, text) if s)
    letters = sum(scripts.values())
    if letters < MIN_LETTERS:
        return Guess("no_text" if letters == 0 else "und", 0.0, letters)
    if scripts["kana"] >= 0.1 * letters:
        return Guess("ja", round(scripts["kana"] / letters, 2), letters)
    for script, language in (
        ("hangul", "ko"),
        ("han", "zh"),
        ("cyrillic", "ru"),
        ("arabic", "ar"),
        ("greek", "el"),
    ):
        if scripts[script] >= 0.3 * letters:
            return Guess(language, round(scripts[script] / letters, 2), letters)
    words = [w.casefold() for w in WORD.findall(text)]
    hits = {lang: sum(w in stops for w in words) for lang, stops in STOPWORDS.items()}
    best = max(hits, key=hits.__getitem__)
    share = hits[best] / len(words) if words else 0.0
    if hits[best] < MIN_HITS or share < MIN_SHARE:
        return Guess("und", round(share, 2), letters)
    runner_up = max(v for k, v in hits.items() if k != best)
    return Guess(best, round(1 - runner_up / hits[best], 2), letters)


@dataclass(frozen=True)
class PdfCheck:
    language: str
    confidence: float
    letters: int
    doi: str | None
    error: str | None = None


def check_pdf(data: bytes) -> PdfCheck:
    import pypdfium2 as pdfium

    try:
        pdf = pdfium.PdfDocument(data)
    except Exception as exc:  # encrypted or broken: reported, not fatal for the survey
        return PdfCheck("error", 0.0, 0, None, f"{type(exc).__name__}: {exc}")
    try:
        text = ""
        for index in range(min(2, len(pdf))):
            text += pdf[index].get_textpage().get_text_range() + "\n"
            if index == 0 and sum(c.isalpha() for c in text) >= 200:
                break
    finally:
        pdf.close()
    guess = detect_language(text)
    doi = DOI.search(text)
    return PdfCheck(
        guess.language, guess.confidence, guess.letters, doi.group(0).rstrip(".,;)") if doi else None
    )


FIELDS = ("folder", "path", "language", "confidence", "letters", "doi", "error", "location_id")


def survey(session, minio, root: str) -> list[dict[str, object]]:
    from sqlalchemy import func, select

    from backend.postgres.enums import DriveItemStatus
    from backend.postgres.models import Blob, DriveItem
    from backend.storage.minio import parse_uri

    rows = session.execute(
        select(DriveItem, Blob.minio_uri)
        .join(Blob, Blob.sha256 == DriveItem.blob_sha256)
        .where(
            DriveItem.root_name == root,
            DriveItem.status == DriveItemStatus.LANDED,
            func.lower(DriveItem.extension) == ".pdf",
        )
        .order_by(DriveItem.path_cached)
    ).all()
    out = []
    for item, minio_uri in rows:
        bucket, key = parse_uri(minio_uri)
        response = minio.get_object(bucket, key)
        try:
            data = response.read()
        finally:
            response.close()
            response.release_conn()
        result = check_pdf(data)
        parts = (item.path_cached or item.name).split("/")
        out.append(
            {
                "folder": "/".join(parts[:3]) if len(parts) > 3 else "/".join(parts[:-1]),
                "path": item.path_cached,
                "language": result.language,
                "confidence": result.confidence,
                "letters": result.letters,
                "doi": result.doi or "",
                "error": result.error or "",
                "location_id": str(item.location_id),
            }
        )
    return out


def summarize(rows: list[dict[str, object]]) -> str:
    by_folder: dict[str, Counter] = defaultdict(Counter)
    for row in rows:
        by_folder[str(row["folder"])][str(row["language"])] += 1
    lines = [f"{len(rows)} PDFs; languages: {dict(Counter(str(r['language']) for r in rows).most_common())}"]
    lines.append(f"with a DOI on page 1-2: {sum(bool(r['doi']) for r in rows)}")
    for folder, counts in sorted(by_folder.items()):
        foreign = {k: v for k, v in counts.items() if k not in ("en", "no_text", "und")}
        if foreign:
            lines.append(f"  {folder}: {dict(counts.most_common())}")
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    from sqlalchemy.orm import Session

    from backend.config import get_settings
    from backend.postgres.session import engine_from_settings
    from backend.storage.minio import client_from_settings

    parser = argparse.ArgumentParser(prog="python -m backend.sync.language_check")
    parser.add_argument("--root", default="APS - Library")
    parser.add_argument("--out", required=True, help="TSV path (keep it under the git-ignored data/)")
    args = parser.parse_args(argv)
    settings = get_settings()
    with Session(engine_from_settings(settings)) as session:
        rows = survey(session, client_from_settings(settings), args.root)
    with open(args.out, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)
    print(summarize(rows))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
