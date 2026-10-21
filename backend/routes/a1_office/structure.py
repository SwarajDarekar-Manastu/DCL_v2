"""DoclingDocument → route nodes (file 03 §A1.3–A1.6, §A1.11, §A1.12), by the chunker's input conventions.

- One `child` text node per paragraph, list item, footnote, code block or form text, with its page and a
  `PageBox` in 0..1 of the page, top-left origin (Docling boxes are PDF points, usually bottom-left).
- Breadcrumbs from section headers; levels from their numbering (`3`, `3.2`, `3.2.1`, `Annex B`), the first
  header before any body text is the document title. Consecutive nodes under one heading form one section.
- Display formulas become `$$…$$` text units (the chunker keeps them with the sentence before).
- Tables become `table` nodes holding HTML with spans; pictures become `figure` placeholders that A1.6 fills
  from VisionService; captions go to the metadata of their table or figure.
- Page headers and footers are not body text: their strings are returned per page for the metadata scan
  (document id, revision, classification marking, DOI, journal).
- A references section (`References`, `Bibliography`, `Literatur`, …) is not indexed as body nodes: each
  entry becomes a `reference` mention (A1.12 step 2), attached to the document's first text node.
"""

import re
from dataclasses import dataclass, field
from typing import Any

from backend.dispatcher.contract import Mention, PageBox, ProcessedNode
from backend.postgres.enums import MentionSource, NodeSource, NodeType

NUMBERED = re.compile(r"^\s*(\d+(?:\.\d+){0,5})\.?\s+\S")
ANNEX = re.compile(r"^\s*(annex|appendix|anhang|annexe)\s+[A-Z0-9]+\b", re.IGNORECASE)
REFERENCES = re.compile(
    r"^\s*(\d+(\.\d+)*\.?\s+)?(references|bibliography|literature|literatur(verzeichnis)?|quellen|"
    r"références|bibliographie|参考文献|引用文献|список литературы)\s*$",
    re.IGNORECASE,
)
TEXT_LABELS = frozenset(
    {
        "text",
        "paragraph",
        "list_item",
        "footnote",
        "code",
        "handwritten_text",
        "form",
        "key_value_region",
        "field_item",
        "field_value",
        "reference",
        "marker",
    }
)
CHECKBOX = {"checkbox_selected": "[x] ", "checkbox_unselected": "[ ] "}
BREADCRUMB_SEPARATOR = " › "


@dataclass
class PageContext:
    language: str | None
    source: NodeSource
    confidence: float | None = None


@dataclass
class Structure:
    nodes: list[ProcessedNode]
    mentions: list[Mention]
    furniture: dict[int, list[str]] = field(default_factory=dict)
    title: str | None = None
    references: list[str] = field(default_factory=list)


def heading_level(text: str) -> int:
    numbered = NUMBERED.match(text)
    if numbered:
        return numbered.group(1).count(".") + 1
    return 1


def page_box(prov, page_sizes: dict[int, tuple[float, float]]) -> PageBox | None:
    size = page_sizes.get(prov.page_no)
    if not size:
        return None
    width, height = size
    box = prov.bbox.to_top_left_origin(page_height=height)
    left, top, right, bottom = box.l, box.t, box.r, box.b
    clamp = lambda v: min(1.0, max(0.0, v))  # noqa: E731
    x0, x1 = sorted((clamp(left / width), clamp(right / width)))
    y0, y1 = sorted((clamp(top / height), clamp(bottom / height)))
    return PageBox(page_no=prov.page_no, x0=x0, y0=y0, x1=x1, y1=y1)


def _boxes(item, page_sizes) -> list[PageBox]:
    return [b for b in (page_box(p, page_sizes) for p in getattr(item, "prov", []) or []) if b]


def _page(item) -> int | None:
    provs = getattr(item, "prov", None) or []
    return provs[0].page_no if provs else None


def _caption(item, doc) -> str | None:
    try:
        text = item.caption_text(doc)
    except Exception:  # noqa: BLE001 (older docling items have no caption API)
        return None
    return text or None


def _picture_class(item) -> str | None:
    meta = getattr(item, "meta", None)
    classification = getattr(meta, "classification", None) if meta else None
    predictions = getattr(classification, "predictions", None) if classification else None
    if predictions:
        best = max(predictions, key=lambda p: getattr(p, "confidence", 0) or 0)
        return getattr(best, "class_name", None)
    for annotation in getattr(item, "annotations", []) or []:
        classes = getattr(annotation, "predicted_classes", None)
        if classes:
            return max(classes, key=lambda c: c.confidence).class_name
    return None


def build_structure(documents: list[Any], pages: dict[int, PageContext], *, fallback_title: str) -> Structure:
    """Map one or more DoclingDocuments (one per conversion run, in page order) to route nodes."""
    from docling_core.types.doc import ContentLayer

    nodes: list[ProcessedNode] = []
    references: list[str] = []
    furniture: dict[int, list[str]] = {}
    title: str | None = None
    stack: list[tuple[int, str]] = []
    in_references_at: int | None = None
    seen_body = False
    counters = {"t": 0, "tab": 0, "fig": 0}

    def breadcrumb() -> str:
        return BREADCRUMB_SEPARATOR.join([title or fallback_title, *[h for _, h in stack]])

    def add(node_type: NodeType, prefix: str, content: str, item, doc, **extra) -> None:
        page_no = _page(item)
        context = pages.get(page_no) if page_no else None
        counters[prefix] += 1
        nodes.append(
            ProcessedNode(
                ref=f"{prefix}{counters[prefix]}",
                node_type=node_type,
                level=len(stack) + 1,
                ordinal=len(nodes),
                breadcrumb=breadcrumb(),
                language=context.language if context else None,
                content=content,
                page_no=page_no,
                bboxes=_boxes(item, {k: (v.size.width, v.size.height) for k, v in doc.pages.items()}),
                source=context.source if context else NodeSource.PRINTED,
                confidence=context.confidence if context else None,
                **extra,
            )
        )

    for doc in documents:
        layers = {ContentLayer.BODY, ContentLayer.FURNITURE}
        for item, _ in doc.iterate_items(included_content_layers=layers):
            label = str(getattr(item, "label", ""))
            label = label.split(".")[-1].lower()
            text = (getattr(item, "text", "") or "").strip()
            if getattr(item, "content_layer", None) == ContentLayer.FURNITURE or label in (
                "page_header",
                "page_footer",
            ):
                if text and _page(item):
                    furniture.setdefault(_page(item), []).append(text)
                continue
            if label in ("title", "section_header"):
                if not text:
                    continue
                if title is None and not seen_body and label == "title":
                    title = text
                    continue
                if (
                    title is None
                    and not seen_body
                    and not NUMBERED.match(text)
                    and not REFERENCES.match(text)
                ):
                    title = text
                    continue
                level = heading_level(text)
                if in_references_at is not None and level <= in_references_at:
                    in_references_at = None
                if REFERENCES.match(text):
                    in_references_at = level
                    continue
                stack[:] = [(lv, h) for lv, h in stack if lv < level] + [(level, text)]
                continue
            if in_references_at is not None and label in TEXT_LABELS:
                if text:
                    references.append(text)
                continue
            if label == "table":
                html = item.export_to_html(doc=doc)
                grid = getattr(getattr(item, "data", None), "grid", None) or []
                metadata = {
                    "n_rows": len(grid),
                    "n_cols": len(grid[0]) if grid else 0,
                    "caption": _caption(item, doc),
                }
                add(NodeType.TABLE, "tab", html, item, doc, metadata=metadata)
                seen_body = True
            elif label in ("picture", "chart"):
                caption = _caption(item, doc)
                add(
                    NodeType.FIGURE,
                    "fig",
                    caption or "",
                    item,
                    doc,
                    metadata={
                        "class": _picture_class(item),
                        "caption": caption,
                        "docling_ref": item.self_ref,
                    },
                )
                seen_body = True
            elif label == "formula":
                if text:
                    add(NodeType.CHILD, "t", f"$${text}$$", item, doc)
                    seen_body = True
            elif label in CHECKBOX:
                add(NodeType.CHILD, "t", CHECKBOX[label] + text, item, doc)
                seen_body = True
            elif label in TEXT_LABELS and text:
                add(NodeType.CHILD, "t", text, item, doc)
                seen_body = True

    first_text = next((n for n in nodes if n.node_type == NodeType.CHILD), None)
    mentions = (
        [
            Mention(node_ref=first_text.ref, kind="reference", surface=r, source=MentionSource.REGEX)
            for r in references
        ]
        if first_text
        else []
    )
    return Structure(nodes, mentions, furniture, title, references)
