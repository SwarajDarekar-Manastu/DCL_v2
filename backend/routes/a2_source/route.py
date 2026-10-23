"""Route A2 (file 03 §5): a LaTeX project or a report JSON file → ``ProcessedDocument`` + CIR + assets.

Input is what the folder-level assembler (``backend/dispatcher/assembler.py``) planned for one logical
document: the primary file, its ``part`` files and an optional ``visual_twin`` PDF, each with its bytes.
Siblings the route needs beyond the plan (images for ``\\includegraphics``, ``.bib``, ``.sty``) are read
through ``read_file`` by their path in the same subtree, chosen from ``folder_files``.

LaTeX: include resolution with a source map → macro expansion → walk (``latex.py``) → references →
figures (images linked as assets; a plot goes through ``classify_image`` + ``digitize_plot`` when cloud
processing is allowed) → page map to the twin → nodes. Every node's ``line_start``/``line_end`` are lines
of ``assembled.md``; ``metadata.source`` is the ``file:line`` it came from and ``metadata.pdf_page`` the
twin page of its section.

CIR (``dcl-cir/{sha256}/A2/v{parser_version}/``): ``assembled.md``, ``structure.json`` (sections, labels,
figures, unresolved references, missing includes, unknown macros), ``source_map.json`` (Markdown line →
``file:line``), ``page_map.json`` (section → twin page, when a twin exists).

Flags (file 06 §4): ``CONFLICT`` SOFT from the assembler (two masters, no master); ``PARSE_FAILURE`` HARD
only when the full walk and every per-section walk fail; ``UNIT_AMBIGUITY`` SOFT for a numeric table in a
results section with values that no column header or row label gives a unit; ``SENSITIVE_CONTENT`` HARD
for a secret in the source; ``SCHEMA_UNKNOWN`` SOFT for a JSON file of unknown shape.
"""

import hashlib
import json
import logging
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

from backend.dispatcher.contract import (
    ConflictEvidence,
    ConflictSide,
    DocumentFields,
    Flag,
    FlagAnchor,
    JsonSchemaEvidence,
    Mention,
    ParseFailureEvidence,
    ProcessedAsset,
    ProcessedDocument,
    ProcessedNode,
    SensitiveEvidence,
    UnitFactEvidence,
)
from backend.dispatcher.folder_context import FolderContext
from backend.postgres.enums import (
    AssetKind,
    DocKind,
    DocumentSourceRole,
    FlagSeverity,
    FlagType,
    MentionSource,
    NodeSource,
    NodeType,
    Route,
)
from backend.routes.a1_office.metadata import extract_metadata, humanize, plan_conflicts
from backend.routes.a2_source import json_sections
from backend.sync.gate import scan_secrets

PARSER_VERSION = 1
REPORT_SCHEMAS_YAML = Path(__file__).resolve().parents[3] / "config" / "report_json_schemas.yaml"
IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".pdf", ".eps", ".svg", ".gif", ".bmp", ".tif", ".tiff")
RASTER_MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}
RESULTS_SECTION = re.compile(
    r"result|observation|performance|output|measurement|summary|finding|data|ergebnis", re.IGNORECASE
)
UNIT_HINT = re.compile(
    r"\[[^\]]+\]|\([^)]*[A-Za-z%°µ][^)]*\)|(?<![\w])(bar[ga]?|psi[ga]?|k?pa|mpa|°c|degc|k|w|kw|v|mv|a|ma|n|kn|"
    r"ns|g/s|kg/s|grams?|kg|mg|s|sec|seconds?|ms|min|minutes?|h|hz|mm|cm|m|%|l|ml|percent)(?![\w])",
    re.IGNORECASE,
)
NUMERIC = re.compile(r"^[-+]?\d+(?:[.,]\d+)?(?:[eE][-+]?\d+)?$")
ID_HEADER = re.compile(
    r"\b(no\.?|nr\.?|number|#|sr|s\.?\s?no|id|test|run|edition|rev(ision)?|step|item|index)\b", re.I
)
BABEL = re.compile(r"\\usepackage\s*\[([^\]]*)\]\s*\{(?:babel|polyglossia)\}|\\setmainlanguage\s*\{(\w+)\}")
LANGUAGES = {
    "english": "en",
    "british": "en",
    "american": "en",
    "ukenglish": "en",
    "usenglish": "en",
    "ngerman": "de",
    "german": "de",
    "french": "fr",
    "francais": "fr",
    "spanish": "es",
    "italian": "it",
    "japanese": "ja",
    "russian": "ru",
    "chinese": "zh",
    "korean": "ko",
    "hindi": "hi",
    "dutch": "nl",
    "portuguese": "pt",
}
FURNITURE = re.compile(
    r"\\(?:fancyhead|fancyfoot|lhead|chead|rhead|lfoot|cfoot|rfoot)\s*(?:\[[^\]]*\])?\s*\{"
)

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class SourceFile:
    """One file of the plan: path relative to the processing subtree (the assembler's ``FileRef.path``)."""

    path: str
    blob_sha256: str
    data: bytes
    role: DocumentSourceRole = DocumentSourceRole.PART


@dataclass(frozen=True)
class Stores:
    """``put_cir(relative_key, bytes) -> uri`` under the document's CIR prefix and
    ``put_asset(key, bytes) -> uri`` in dcl-assets (S1's BucketStore in the workers), as for Route A1."""

    put_cir: Callable[[str, bytes], str]
    put_asset: Callable[[str, bytes], str]


def decode(data: bytes) -> str:
    """UTF-8 (with or without BOM), else the detected encoding, else Latin-1; NUL bytes dropped."""
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        from charset_normalizer import from_bytes

        best = from_bytes(data).best()
        text = str(best) if best is not None else data.decode("latin-1")
    return text.replace("\x00", "")


def _flag_hash(*parts: str) -> str:
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def conflict_flags(conflicts: Sequence[str], primary: str) -> list[Flag]:
    """The assembler's doubts (two masters, no master) as CONFLICT SOFT, one per message."""
    flags = []
    for message in conflicts:
        flags.append(
            Flag(
                flag_type=FlagType.CONFLICT,
                severity=FlagSeverity.SOFT,
                anchor=FlagAnchor(content_sha256=_flag_hash("assembler", message)),
                evidence=ConflictEvidence(
                    subject=message,
                    a=ConflictSide(label="assembled as", value=primary, provenance="folder-level assembler"),
                    b=ConflictSide(label="reason", value=message, provenance="folder-level assembler"),
                ),
            )
        )
    return flags


def secret_flags(files: Sequence[SourceFile], texts: Mapping[str, str]) -> list[Flag]:
    flags = []
    for f in files:
        for hit in scan_secrets(texts.get(f.path, "")):
            flags.append(
                Flag(
                    flag_type=FlagType.SENSITIVE_CONTENT,
                    severity=FlagSeverity.HARD,
                    anchor=FlagAnchor(line=hit.line, content_sha256=f.blob_sha256),
                    evidence=SensitiveEvidence(
                        pattern=hit.pattern,
                        redacted_preview=f"{f.path}: {hit.redacted_preview}",
                        line=hit.line,
                    ),
                )
            )
    return flags


def _parse_failure(error: str, data: bytes, extension: str) -> Flag:
    return Flag(
        flag_type=FlagType.PARSE_FAILURE,
        severity=FlagSeverity.HARD,
        evidence=ParseFailureEvidence(
            error=error[:2000],
            magic_bytes_hex=data[:16].hex(),
            size_bytes=len(data),
            extension=extension,
            first_kb_preview=data[:1024].decode("utf-8", errors="replace"),
        ),
    )


def _unique_flags(flags: list[Flag]) -> list[Flag]:
    seen, out = set(), []
    for flag in flags:
        if flag.fingerprint not in seen:
            seen.add(flag.fingerprint)
            out.append(flag)
    return out


def language_of(preamble: str) -> str:
    match = BABEL.search(preamble)
    if match:
        options = (match.group(1) or match.group(2) or "").split(",")
        for option in reversed(options):  # babel: the last language is the main one
            code = LANGUAGES.get(option.strip().casefold().replace("main=", ""))
            if code:
                return code
    return "en"


# ---------------------------------------------------------------- tables: unit check


def unitless_values(grid: list[list[str]], header_rows: int) -> list[tuple[str, str]]:
    """(value, its row label or column header) for numeric cells no header or row label gives a unit."""
    if not grid:
        return []
    header = grid[:header_rows]
    body = grid[header_rows:]
    width = max(len(r) for r in grid)
    column_header = [
        " ".join(row[j] for row in header if j < len(row)) if header else "" for j in range(width)
    ]
    numeric_columns = [
        j
        for j in range(width)
        if sum(1 for r in body if j < len(r) and NUMERIC.match(r[j].strip())) >= 2
        and not ID_HEADER.search(column_header[j])
    ]
    found = []
    for row in body:
        label = row[0] if row and not NUMERIC.match(row[0].strip()) else ""
        for j in numeric_columns:
            if j == 0 or j >= len(row) or not NUMERIC.match(row[j].strip()):
                continue
            if UNIT_HINT.search(column_header[j]) or UNIT_HINT.search(label):
                continue
            found.append((row[j].strip(), label or column_header[j]))
    return found


def _unit_flag(block_meta: dict, md_line: int, crumb: str) -> Flag | None:
    values = unitless_values(block_meta.get("grid") or [], block_meta.get("header_rows") or 0)
    if not values:
        return None
    value, context = values[0]
    caption = block_meta.get("caption") or ""
    labels = sorted({c for _, c in values if c})
    return Flag(
        flag_type=FlagType.UNIT_AMBIGUITY,
        severity=FlagSeverity.SOFT,
        anchor=FlagAnchor(line=md_line, content_sha256=_flag_hash("table", crumb, caption, *labels)),
        evidence=UnitFactEvidence(
            value_raw=value,
            context=f"{crumb} — {caption}: {', '.join(labels)[:400]}".strip(" —:"),
        ),
    )


# ---------------------------------------------------------------- LaTeX


@dataclass
class _Built:
    nodes: list[ProcessedNode] = field(default_factory=list)
    assets: list[ProcessedAsset] = field(default_factory=list)
    mentions: list[Mention] = field(default_factory=list)
    flags: list[Flag] = field(default_factory=list)
    markdown: list[str] = field(default_factory=list)
    source_map: list[str] = field(default_factory=list)
    figures: list[dict] = field(default_factory=list)


def _graphics_paths(preamble: str) -> list[str]:
    match = re.search(r"\\graphicspath\s*\{((?:\s*\{[^}]*\})*)\s*\}", preamble)
    return re.findall(r"\{([^}]*)\}", match.group(1)) if match else []


def _resolver(
    master_folder: str, folder_files: Sequence[str], graphics: Sequence[str]
) -> Callable[[str], str | None]:
    from backend.routes.a2_source.latex import resolve_path

    known = {_norm(p): p for p in folder_files}

    def resolve(name: str) -> str | None:
        name = name.strip()
        if not name:
            return None
        for prefix in ["", *graphics]:
            found = resolve_path(prefix + name, master_folder, known, IMAGE_SUFFIXES)
            if found is not None:
                return found
        return None

    return resolve


def _norm(path: str) -> str:
    from backend.routes.a2_source.latex import _normalize

    return _normalize(path)


def _image_size(data: bytes) -> tuple[int | None, int | None]:
    try:
        import io

        from PIL import Image as PILImage

        with PILImage.open(io.BytesIO(data)) as image:
            return image.width, image.height
    except Exception:  # noqa: BLE001 — size is optional; an unreadable image keeps no size
        return None, None


def _read_figure(vision, data: bytes, mime: str, caption: str | None, context: str, doc_id, anchor: str):
    """classify_image → digitize_plot for plots; (text, confidence, reading) or None."""
    from backend.llm_engine.gemini_types import GeminiError, Image
    from backend.llm_engine.vision.schemas import ImageClass

    try:
        kind = vision.classify_image(Image(data, mime), folder_context=context, doc_id=doc_id, anchor=anchor)
        if kind.reading.image_class != ImageClass.PLOT_OR_SCREENSHOT:
            return None
        output = vision.digitize_plot(
            Image(data, mime), caption=caption, context=context, doc_id=doc_id, anchor=anchor
        )
    except GeminiError as exc:
        log.warning("figure reading failed (%s): %s", anchor, exc)
        return None
    from backend.routes.a1_office.figures import render_plot

    reading = output.reading
    return render_plot(reading), reading.confidence, reading.model_dump(mode="json")


def _furniture(text: str, inline: Callable[[str], str]) -> list[str]:
    from backend.routes.a2_source.latex import _group

    found = []
    for match in FURNITURE.finditer(text):
        group = _group(text, match.end() - 1)
        if group is not None:
            rendered = inline(group[0])
            if rendered and rendered not in found and not rendered.isdigit():
                found.append(rendered)
    return found


def process_latex(
    files: Sequence[SourceFile],
    *,
    title: str | None,
    folder: FolderContext,
    stores: Stores,
    folder_files: Sequence[str] = (),
    read_file: Callable[[str], bytes | None] = lambda _path: None,
    conflicts: Sequence[str] = (),
    vision=None,
    cloud_allowed: bool = False,
    doc_id: str | None = None,
) -> ProcessedDocument:
    from pylatexenc.latexwalker import LatexWalker

    from backend.routes.a2_source import latex
    from backend.routes.a2_source.bib import parse_bib, reference_text
    from backend.routes.a2_source.page_map import Heading, map_headings, page_texts

    primary = next(f for f in files if f.role == DocumentSourceRole.PRIMARY)
    sources = [f for f in files if f.role in (DocumentSourceRole.PRIMARY, DocumentSourceRole.PART)]
    twin = next((f for f in files if f.role == DocumentSourceRole.VISUAL_TWIN), None)
    blob = primary.blob_sha256
    cir_uri = f"s3://dcl-cir/{blob}/{Route.A2}/v{PARSER_VERSION}/"
    texts = {f.path: decode(f.data) for f in sources}
    flags = conflict_flags(conflicts, primary.path) + secret_flags(sources, texts)

    master_folder = str(PurePosixPath(primary.path).parent)
    if latex.BEGIN_DOCUMENT.search(texts[primary.path]) or "\\documentclass" in texts[primary.path]:
        master = primary.path
    else:  # orphan sections: one synthetic master that inputs them in the plan's (file name) order
        master = str(PurePosixPath(master_folder) / "__assembled_by_filename__.tex")
        relative = [
            str(PurePosixPath(f.path).relative_to(master_folder)) if master_folder != "." else f.path
            for f in sources
        ]
        texts[master] = "\n".join(f"\\input{{{path}}}" for path in relative)
    assembled = latex.assemble(master, texts)
    text = assembled.text
    begin, end = latex.BEGIN_DOCUMENT.search(text), latex.END_DOCUMENT.search(text)
    body_start = begin.end() if begin else 0
    body_end = end.start() if end and end.start() > body_start else len(text)
    preamble = text[:body_start] if begin else ""

    sty_texts = []
    for path in folder_files:
        if path.casefold().endswith(".sty") and (data := read_file(path)) is not None:
            sty_texts.append(decode(data))
    macros = latex.collect_macros([*sty_texts, text])
    resolve_image = _resolver(master_folder, folder_files, _graphics_paths(preamble))
    fallback_title = (title or humanize(PurePosixPath(primary.path).name)).strip()

    def new_walker() -> latex.Walker:
        walker = latex.Walker(text, macros, lambda p: resolve_image(p) is not None, fallback_title)
        raw_title = latex.preamble_title(preamble)
        if raw_title:
            nodes = LatexWalker(raw_title, latex_context=walker.db, tolerant_parsing=True).get_latex_nodes()[
                0
            ]
            walker.title = walker.inline(nodes, 0) or None
        return walker

    walker = new_walker()
    failed: list[str] = []
    try:
        walker.run(body_start, body_end)
    except Exception as exc:  # noqa: BLE001 — per-section fallback (A2 flags: HARD only if both fail)
        log.warning("full LaTeX walk failed for %s: %s", primary.path, exc)
        walker = new_walker()
        cuts = [body_start]
        cuts += [
            m.start() for m in re.finditer(r"\\(?:chapter|section)\*?\s*[\[{]", text[body_start:body_end])
        ]
        cuts = sorted({body_start, *(body_start + c for c in cuts[1:]), body_end})
        for a, b in zip(cuts, cuts[1:], strict=False):
            try:
                walker.run_isolated(a, b)
            except Exception as section_exc:  # noqa: BLE001
                failed.append(f"{assembled.locate(a)}: {section_exc}")
        if len(failed) == len(cuts) - 1:
            flags.append(_parse_failure(f"{exc}; every section failed too", primary.data, "tex"))
            return ProcessedDocument(
                blob_sha256=blob,
                route=Route.A2,
                parser_version=PARSER_VERSION,
                cir_uri=cir_uri,
                document=DocumentFields(title=fallback_title, doc_kind=DocKind.UNKNOWN),
                flags=_unique_flags(flags),
            )

    doc_title = walker.title or fallback_title
    blocks = walker.blocks
    for block in blocks:
        block.breadcrumb = (doc_title, *block.breadcrumb[1:])

    bib_entries = list(walker.inline_bib)
    bib_paths = []
    for name in walker.bib_files:
        path = latex.resolve_path(name, master_folder, {_norm(p): p for p in folder_files}, (".bib",))
        if path is not None and (data := read_file(path)) is not None:
            bib_paths.append(path)
            bib_entries += parse_bib(decode(data))
    bib = {entry.key: entry for entry in bib_entries}
    unresolved = latex.resolve_refs(blocks, walker.labels, bib)

    twin_pages: list[str] = []
    if twin is not None:
        try:
            twin_pages = page_texts(twin.data)
        except Exception as exc:  # noqa: BLE001 — a broken twin only loses the page map
            log.warning("twin %s unreadable: %s", twin.path, exc)
    headings = [b for b in blocks if b.kind == "heading"]
    page_of = (
        map_headings(
            [
                Heading(str(i), b.meta.get("number", ""), b.meta.get("title", b.text))
                for i, b in enumerate(headings)
            ],
            twin_pages,
        )
        if twin_pages
        else {}
    )
    heading_page = {id(b): page_of.get(str(i)) for i, b in enumerate(headings)}

    context = " / ".join([*folder.breadcrumb, PurePosixPath(primary.path).name])
    built = _Built()
    current_page: int | None = None
    asset_count = 0
    all_text: list[str] = []
    first_page_text: list[str] = []
    seen_heading = False
    for block in blocks:
        loc = assembled.locate(block.pos)
        if block.kind == "heading":
            seen_heading = True
            current_page = heading_page.get(id(block)) or current_page
            built.markdown.append("#" * max(block.level, 1) + " " + block.text)
            built.source_map.append(str(loc))
            built.markdown.append("")
            built.source_map.append(str(loc))
            continue
        meta: dict[str, Any] = {"source": str(loc)}
        if current_page is not None:
            meta["pdf_page"] = current_page
        ref = f"b{len(built.nodes)}"
        node_type, content, source, confidence, asset_ref = (
            NodeType.CHILD,
            block.text,
            NodeSource.PRINTED,
            None,
            None,
        )
        if block.kind == "table":
            node_type = NodeType.TABLE
            caption = block.meta.get("caption")
            number = block.meta.get("number")
            meta.update(
                caption=f"Table {number}: {caption}" if caption and number else caption,
                header_rows=block.meta.get("header_rows"),
                labels=block.meta.get("labels") or [],
            )
            lines = ([meta["caption"]] if meta["caption"] else []) + [content]
        elif block.kind == "figure":
            figure = _figure(
                block,
                walker,
                resolve_image,
                read_file,
                stores,
                blob,
                asset_count,
                vision,
                cloud_allowed,
                context,
                doc_id,
            )
            if figure is None:
                built.figures.append(
                    {"source": str(loc), "images": block.meta.get("images"), "indexed": False}
                )
                continue
            node_type = NodeType.FIGURE
            content, asset, extra, reading_conf = figure
            if asset is not None:
                built.assets.append(asset)
                asset_ref = asset.ref
                asset_count += 1
            if reading_conf is not None:
                source, confidence = NodeSource.VLM, reading_conf
            meta.update(extra)
            built.figures.append({"source": str(loc), **extra, "indexed": True})
            lines = [f"![{extra.get('caption') or ''}]({extra.get('image') or ''})"]
        else:
            if block.kind == "equation" and block.meta.get("number"):
                meta["equation_number"] = block.meta["number"]
            if block.kind == "code":
                meta["code"] = True
            lines = [content]
        if block.meta.get("refs"):
            meta["refs"] = block.meta["refs"]
        md_lines = "\n".join(lines).split("\n")
        start = len(built.markdown) + 1
        built.markdown += md_lines + [""]
        built.source_map += [str(loc)] * (len(md_lines) + 1)
        built.nodes.append(
            ProcessedNode(
                ref=ref,
                node_type=node_type,
                level=block.level,
                ordinal=len(built.nodes),
                breadcrumb=" › ".join(block.breadcrumb),
                language=None,
                content=content,
                line_start=start,
                line_end=start + len(md_lines) - 1,
                source=source,
                confidence=confidence,
                asset_ref=asset_ref,
                metadata=meta,
            )
        )
        if block.kind != "figure":
            all_text.append(content)
            if not seen_heading:
                first_page_text.append(content)
        for surface in block.meta.get("quantities", []):
            at = content.find(surface)
            built.mentions.append(
                Mention(
                    node_ref=ref,
                    kind="quantity",
                    surface=surface,
                    span_start=at if at >= 0 else None,
                    span_end=at + len(surface) if at >= 0 else None,
                    source=MentionSource.REGEX,
                )
            )
        if block.kind == "table" and RESULTS_SECTION.search(
            " ".join(block.breadcrumb[1:]) + " " + (block.meta.get("caption") or "")
        ):
            flag = _unit_flag(block.meta, start, " › ".join(block.breadcrumb[1:]))
            if flag is not None:
                built.flags.append(flag)

    language = language_of(preamble)
    nodes = [n.model_copy(update={"language": language}) for n in built.nodes]
    _referencing(nodes, walker.labels)
    first_text = next((n for n in nodes if n.node_type == NodeType.CHILD), nodes[0] if nodes else None)
    if first_text is not None:
        for entry in bib_entries:
            built.mentions.append(
                Mention(
                    node_ref=first_text.ref,
                    kind="reference",
                    surface=reference_text(entry),
                    source=MentionSource.REGEX,
                )
            )

    def inline(raw: str) -> str:
        parsed = LatexWalker(raw, latex_context=walker.db, tolerant_parsing=True).get_latex_nodes()[0]
        return re.sub(r"\ue000[^\ue001]*\ue001", "", walker.inline(parsed, 0))

    furniture = _furniture(text, inline)
    metadata = extract_metadata(
        file_name=PurePosixPath(primary.path).name,
        title=doc_title,
        first_page_text="\n".join(first_page_text),
        full_text="\n".join(all_text),
        furniture=furniture,
        folder=folder,
        page_languages=[language],
        page_count=len(twin_pages),
    )
    fields = metadata.fields.model_copy(
        update={
            "page_count": len(twin_pages) or None,
            "unit_count": None,
            "catalog": None,
        }
    )
    flags += metadata.flags + plan_conflicts(folder, {1: furniture}, "\n".join(first_page_text)) + built.flags

    structure = {
        "title": doc_title,
        "master": master,
        "included": assembled.included,
        "missing_includes": assembled.missing,
        "magic_comments": assembled.magic_comments,
        "sections": [
            {
                "number": b.meta.get("number"),
                "title": b.meta.get("title"),
                "level": b.level,
                "source": str(assembled.locate(b.pos)),
                "pdf_page": heading_page.get(id(b)),
            }
            for b in headings
        ],
        "labels": {k: {"kind": v.kind, "number": v.number} for k, v in walker.labels.items()},
        "unresolved_refs": unresolved,
        "unknown_macros": walker.unknown,
        "figures": built.figures,
        "bibliography": bib_paths,
        "failed_sections": failed,
        "metadata_sources": metadata.sources,
    }
    stores.put_cir("assembled.md", "\n".join(built.markdown).encode("utf-8"))
    stores.put_cir("structure.json", json.dumps(structure, ensure_ascii=False, indent=1).encode("utf-8"))
    stores.put_cir("source_map.json", json.dumps(built.source_map, ensure_ascii=False).encode("utf-8"))
    if twin is not None:
        page_map = {
            "twin": twin.path,
            "twin_blob_sha256": twin.blob_sha256,
            "pages": len(twin_pages),
            "sections": {
                f"{b.meta.get('number') or ''} {b.meta.get('title') or b.text}".strip(): heading_page.get(
                    id(b)
                )
                for b in headings
            },
        }
        stores.put_cir("page_map.json", json.dumps(page_map, ensure_ascii=False, indent=1).encode("utf-8"))

    return ProcessedDocument(
        blob_sha256=blob,
        route=Route.A2,
        parser_version=PARSER_VERSION,
        cir_uri=cir_uri,
        document=fields,
        nodes=nodes,
        assets=built.assets,
        mentions=built.mentions,
        flags=_unique_flags(flags),
    )


def _figure(
    block, walker, resolve_image, read_file, stores, blob, index, vision, cloud_allowed, context, doc_id
):
    """(content, asset, metadata, reading confidence) for a figure block, or None when it says nothing
    (a logo without caption)."""
    caption = block.meta.get("caption")
    number = block.meta.get("number")
    label = f"Figure {number}: {caption}" if caption and number else caption
    images = block.meta.get("images") or []
    extra: dict[str, Any] = {"caption": label, "labels": block.meta.get("labels") or []}
    parts = [label] if label else []
    if block.meta.get("subcaptions"):
        parts += block.meta["subcaptions"]
        extra["subcaptions"] = block.meta["subcaptions"]
    if block.meta.get("loose_text"):
        parts.append(block.meta["loose_text"])
    if block.meta.get("included_pdf"):
        names = [PurePosixPath(p).name for p in images]
        parts.append("Included document: " + ", ".join(names))
        extra["included_pdf"] = images
    if block.meta.get("tikz"):
        extra["tikz"] = True
        if not label:
            parts.append("TikZ picture")
    asset, confidence = None, None
    resolved = (
        next((p for p in (resolve_image(i) for i in images) if p), None)
        if not block.meta.get("included_pdf")
        else None
    )
    if images:
        extra["image"] = resolved or images[0]
    if resolved is not None and (data := read_file(resolved)) is not None:
        suffix = PurePosixPath(resolved).suffix.casefold()
        width, height = _image_size(data) if suffix in RASTER_MIME else (None, None)
        uri = stores.put_asset(f"figures/{blob}/{index:04d}{suffix}", data)
        asset = ProcessedAsset(
            ref=f"fig:{index}",
            kind=AssetKind.FIGURE_CROP,
            minio_uri=uri,
            width=width,
            height=height,
            bytes=len(data),
        )
        extra["image_path"] = resolved
        if vision is not None and cloud_allowed and suffix in RASTER_MIME:
            read = _read_figure(
                vision, data, RASTER_MIME[suffix], label, context, doc_id, f"figure:{resolved}"
            )
            if read is not None:
                text, confidence, structured = read
                parts.append(text)
                extra["structured_reading"] = structured
    if not parts:
        return None
    return "\n".join(parts), asset, extra, confidence


def _referencing(nodes: list[ProcessedNode], labels) -> None:
    """Figure and table nodes carry the sentences that cite them (``metadata.referenced_by``) so a figure
    chunk explains itself."""
    cited: dict[str, list[str]] = {}
    for node in nodes:
        for key in node.metadata.get("refs", []):
            label = labels.get(key)
            if label is None:
                continue
            for sentence in re.split(r"(?<=[.!?])\s+", node.content):
                if label.number and label.number in sentence:
                    cited.setdefault(key, []).append(sentence.strip())
    for i, node in enumerate(nodes):
        keys = node.metadata.get("labels") or []
        sentences = [s for key in keys for s in cited.get(key, [])][:3]
        if sentences and node.node_type in (NodeType.FIGURE, NodeType.TABLE):
            metadata = {**node.metadata, "referenced_by": sentences}
            update: dict[str, Any] = {"metadata": metadata}
            if node.node_type == NodeType.FIGURE:
                update["content"] = node.content + "\n" + " ".join(sentences)
            nodes[i] = node.model_copy(update=update)


# ---------------------------------------------------------------- JSON


def process_json(
    files: Sequence[SourceFile],
    *,
    title: str | None,
    folder: FolderContext,
    stores: Stores,
    schema_config: json_sections.SchemaConfig | None = None,
) -> ProcessedDocument:
    """One report JSON file, or a JSON section-file set (primary first, parts in the configured order)."""
    config = schema_config or json_sections.read_schema_config(REPORT_SCHEMAS_YAML)
    primary = next(f for f in files if f.role == DocumentSourceRole.PRIMARY)
    sources = [f for f in files if f.role in (DocumentSourceRole.PRIMARY, DocumentSourceRole.PART)]
    blob = primary.blob_sha256
    cir_uri = f"s3://dcl-cir/{blob}/{Route.A2}/v{PARSER_VERSION}/"
    doc_title = (title or humanize(PurePosixPath(primary.path).name)).strip()
    flags: list[Flag] = []
    nodes: list[ProcessedNode] = []
    mentions: list[Mention] = []
    shapes: dict[str, Any] = {}
    test_run_id = None
    md: list[str] = []

    for f in sources:
        name = PurePosixPath(f.path).name
        text = decode(f.data)
        flags += secret_flags([f], {f.path: text})
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            flags.append(_parse_failure(f"{name}: {exc}", f.data, "json"))
            continue
        sniffed = json_sections.sniff(data, name, config)
        shapes[f.path] = {"shape": sniffed.shape, "schema": sniffed.schema_id, "keys": sniffed.top_level_keys}
        test_run_id = test_run_id or sniffed.test_run_id
        if sniffed.shape in ("report_section", "section_file"):
            sections = sniffed.sections
        else:
            label = {"data_array": "Data array", "config": "Configuration", "unknown": "Fields"}[
                sniffed.shape
            ]
            sections = [
                json_sections.Section(f"{label} ({name})", [sniffed.flattened] if sniffed.flattened else [])
            ]
        if sniffed.shape == "unknown":
            flags.append(
                Flag(
                    flag_type=FlagType.SCHEMA_UNKNOWN,
                    severity=FlagSeverity.SOFT,
                    anchor=FlagAnchor(content_sha256=f.blob_sha256),
                    evidence=JsonSchemaEvidence(
                        top_level_keys=sniffed.top_level_keys[:200],
                        flattened_sample=sniffed.flattened[:30],
                        closest_schema=sniffed.closest_schema,
                        missing_keys=sniffed.missing_keys,
                    ),
                )
            )
        for section in sections:
            crumb = f"{doc_title} › {section.title}"
            md.append(f"## {section.title}")
            md.append("")
            node_type = NodeType.CONFIG if sniffed.shape == "config" else NodeType.CHILD
            for group in section.lines:
                content = "\n".join(group)
                if not content.strip():
                    continue
                start = len(md) + 1
                md += group + [""]
                ref = f"j{len(nodes)}"
                nodes.append(
                    ProcessedNode(
                        ref=ref,
                        node_type=node_type,
                        level=2,
                        ordinal=len(nodes),
                        breadcrumb=crumb,
                        language="en",
                        content=content,
                        line_start=start,
                        line_end=start + len(group) - 1,
                        source=NodeSource.STRUCTURED,
                        metadata={"file": f.path, "json_key": section.key, "shape": sniffed.shape},
                    )
                )
                for surface, a, b in json_sections.quantities(content):
                    mentions.append(
                        Mention(node_ref=ref, kind="quantity", surface=surface, span_start=a, span_end=b)
                    )

    kind = (
        DocKind.CONFIG if shapes and all(s["shape"] == "config" for s in shapes.values()) else DocKind.UNKNOWN
    )
    if any(s["shape"] in ("report_section", "section_file") for s in shapes.values()):
        kind = DocKind.TEST_REPORT
    fields = DocumentFields(
        title=doc_title,
        doc_kind=kind,
        source_origin=folder.source_origin,
        trust_tier=folder.trust_tier,
        test_plan_id=folder.test_plan_id,
        test_run_id=test_run_id or folder.test_run_id,
        hardware_item=folder.hardware_item,
        language="en",
        catalog={"json_shapes": shapes},
    )
    stores.put_cir("assembled.md", "\n".join(md).encode("utf-8"))
    stores.put_cir(
        "structure.json", json.dumps({"files": shapes}, ensure_ascii=False, indent=1).encode("utf-8")
    )
    return ProcessedDocument(
        blob_sha256=blob,
        route=Route.A2,
        parser_version=PARSER_VERSION,
        cir_uri=cir_uri,
        document=fields,
        nodes=nodes,
        mentions=mentions,
        flags=_unique_flags(flags),
    )


# ---------------------------------------------------------------- adapter predicates (S1 registers them)


def can_handle_tex(head: bytes, name: str) -> bool:
    return name.casefold().endswith(".tex") and b"\x00" not in head[:4096]


def can_handle_json(head: bytes, name: str) -> bool:
    stripped = head.lstrip(b"\xef\xbb\xbf \t\r\n")
    return name.casefold().endswith(".json") and stripped[:1] in (b"{", b"[")
