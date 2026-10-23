"""A1 entry for every office format (file 03 §A1.9–A1.10, amended 2026-10-23): one call for S1's dispatcher.

- PDF → `process_pdf`.
- Word family (`.docx`, `.doc`, `.rtf`, `.odt`): LibreOffice (S4's `backend.common.office.convert`) turns the
  file into a PDF that runs the PDF pipeline (pages, renders, figures, tables, scanned inserts). What only the
  Word file has is read from the DOCX itself (legacy formats are converted to DOCX first): tracked changes
  (`has_tracked_changes`; the PDF shows the accepted view), comments as `annotation` mentions on the node that
  holds the commented paragraph, footnotes appended to the node that holds their reference, and the list of
  embedded objects in `documents.catalog` (their own documents follow once S1's `derived_blobs` exists).
- Slides (`.pptx`, `.ppt`, `.odp`): read natively (slides.py); legacy formats are converted to PPTX first and
  the deck to PDF once for the slide renders.
"""

import io
import re
import zipfile
from collections.abc import Callable
from dataclasses import dataclass, field

from lxml import etree

from backend.dispatcher.contract import Mention, ProcessedDocument, ProcessedNode
from backend.postgres.enums import MentionSource
from backend.routes.a1_office.route import Stores, process_pdf
from backend.routes.a1_office.slides import process_slides

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
WORD = frozenset({"docx", "doc", "rtf", "odt"})
SLIDES = frozenset({"pptx", "ppt", "odp"})
TRACKED = ("ins", "del", "moveFrom", "moveTo", "rPrChange", "pPrChange")
MATCH_CHARS = 60


class UnsupportedOfficeFormat(ValueError):
    pass


@dataclass
class Comment:
    author: str
    text: str
    anchor_text: str


@dataclass
class WordExtras:
    has_tracked_changes: bool = False
    comments: list[Comment] = field(default_factory=list)
    footnotes: list[tuple[str, str]] = field(default_factory=list)  # (paragraph text, footnote text)
    embedded: list[dict] = field(default_factory=list)

    def catalog(self) -> dict:
        return {
            "word": {
                "has_tracked_changes": self.has_tracked_changes,
                "comments": len(self.comments),
                "footnotes": len(self.footnotes),
                "embedded_objects": self.embedded,
            }
        }


def _text(element) -> str:
    return "".join(element.itertext()).strip()


def _paragraph_text(paragraph) -> str:
    """The accepted view: inserted text kept, deleted text (w:delText) left out."""
    return "".join(t.text or "" for t in paragraph.iter(f"{W}t")).strip()


def word_extras(docx_bytes: bytes) -> WordExtras:
    extras = WordExtras()
    with zipfile.ZipFile(io.BytesIO(docx_bytes)) as archive:
        names = set(archive.namelist())
        body = etree.fromstring(archive.read("word/document.xml"))
        extras.has_tracked_changes = any(next(body.iter(f"{W}{tag}"), None) is not None for tag in TRACKED)
        anchors: dict[str, str] = {}
        notes_at: dict[str, str] = {}
        for paragraph in body.iter(f"{W}p"):
            text = _paragraph_text(paragraph)
            for start in paragraph.iter(f"{W}commentRangeStart", f"{W}commentReference"):
                anchors.setdefault(start.get(f"{W}id"), text)
            for ref in paragraph.iter(f"{W}footnoteReference"):
                notes_at[ref.get(f"{W}id")] = text
        if "word/comments.xml" in names:
            for comment in etree.fromstring(archive.read("word/comments.xml")).iter(f"{W}comment"):
                text = _text(comment)
                if text:
                    extras.comments.append(
                        Comment(
                            comment.get(f"{W}author") or "unknown",
                            text,
                            anchors.get(comment.get(f"{W}id"), ""),
                        )
                    )
        if "word/footnotes.xml" in names:
            for note in etree.fromstring(archive.read("word/footnotes.xml")).iter(f"{W}footnote"):
                note_id = note.get(f"{W}id")
                text = _text(note)
                if note_id in notes_at and text:
                    extras.footnotes.append((notes_at[note_id], text))
        extras.embedded = [
            {"name": n.rsplit("/", 1)[-1], "bytes": archive.getinfo(n).file_size}
            for n in sorted(names)
            if n.startswith("word/embeddings/")
        ]
    return extras


def _normalized(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().casefold()


def _holder(nodes: list[ProcessedNode], paragraph: str) -> ProcessedNode | None:
    """The first text node whose content contains the paragraph's opening words."""
    probe = _normalized(paragraph)[:MATCH_CHARS]
    if not probe:
        return None
    return next((n for n in nodes if probe in _normalized(n.content)), None)


def apply_word_extras(processed: ProcessedDocument, extras: WordExtras) -> ProcessedDocument:
    nodes = list(processed.nodes)
    mentions = list(processed.mentions)
    for anchor_text, note in extras.footnotes:
        holder = _holder(nodes, anchor_text)
        if holder is not None:
            i = nodes.index(holder)
            nodes[i] = holder.model_copy(update={"content": f"{holder.content}\n[Footnote: {note}]"})
    for comment in extras.comments:
        holder = _holder(nodes, comment.anchor_text) or (nodes[0] if nodes else None)
        if holder is not None:
            mentions.append(
                Mention(
                    node_ref=holder.ref,
                    kind="annotation",
                    surface=f"{comment.author}: {comment.text}"[:500],
                    source=MentionSource.REGEX,
                )
            )
    catalog = {**(processed.document.catalog or {}), **extras.catalog()}
    return processed.model_copy(
        update={
            "nodes": nodes,
            "mentions": mentions,
            "document": processed.document.model_copy(update={"catalog": catalog}),
        }
    )


def process_office(
    data: bytes,
    *,
    blob_sha256: str,
    file_name: str,
    stores: Stores,
    vision,
    convert_office: Callable[..., bytes] | None = None,
    **options,
) -> ProcessedDocument:
    """Route A1 for any office file; `options` are process_pdf's (folder, cloud_allowed, doc_id, …)."""
    ext = file_name.rsplit(".", 1)[-1].lower() if "." in file_name else ""
    if ext == "pdf":
        return process_pdf(
            data, blob_sha256=blob_sha256, file_name=file_name, stores=stores, vision=vision, **options
        )
    if convert_office is None:
        from backend.common.office import convert as convert_office
    if ext in WORD:
        pdf = convert_office(data, ext, "pdf")
        processed = process_pdf(
            pdf, blob_sha256=blob_sha256, file_name=file_name, stores=stores, vision=vision, **options
        )
        docx = data if ext == "docx" else convert_office(data, ext, "docx")
        return apply_word_extras(processed, word_extras(docx))
    if ext in SLIDES:
        pptx = data if ext == "pptx" else convert_office(data, ext, "pptx")
        pdf = convert_office(pptx, "pptx", "pdf")
        return process_slides(
            pptx,
            pdf,
            blob_sha256=blob_sha256,
            file_name=file_name,
            folder=options["folder"],
            vision=vision,
            put_asset=stores.put_asset,
            put_cir=stores.put_cir,
            cloud_allowed=options.get("cloud_allowed", True),
            doc_id=options.get("doc_id"),
        )
    raise UnsupportedOfficeFormat(f"Route A1 does not read .{ext} files")
