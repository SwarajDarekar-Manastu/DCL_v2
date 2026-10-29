"""One card per file (docs/sessions/PLAN_metadata_search.md step 3): the file's metadata in one text.

The card is what the answer engine's catalog step searches before any model reads the question
(``engine/catalog.py``): title, kind, origin, date, test labels, folder path, summary, entities and the
titles of what the file contains. It lives on the file's own ``documents`` row (``search_text``, its
identifiers in ``card_codes``, its vector in ``card_embedding``), so every file has exactly one, halted files
included. Built in code from what the route and the enrichment already produced; no model call.
"""

import logging
from collections.abc import Callable, Iterable
from typing import Any

from backend.dispatcher.contract import DocumentFields
from backend.indexing.identifiers import content_codes
from backend.postgres.enums import NodeType, SourceOrigin

log = logging.getLogger(__name__)

CARD_MAX_CHARS = 4000
CONTENTS_MAX = 40
ENTITIES_MAX = 40
CONTENT_TYPES = frozenset(
    {
        NodeType.PARENT,
        NodeType.TABLE,
        NodeType.FIGURE,
        NodeType.PHOTO,
        NodeType.VIDEO_EVENT,
        NodeType.RUN_SUMMARY,
        NodeType.DIAGRAM_SUMMARY,
        NodeType.CODE_SYMBOL,
        NodeType.SLIDE,
        NodeType.CONFIG,
    }
)
SEPARATOR = " › "


def contents_of(nodes: Iterable[Any], title: str) -> list[str]:
    """What the file contains, in reading order: section paths, table and figure captions, code symbols."""
    found: list[str] = []
    for node in nodes:
        if node.node_type not in CONTENT_TYPES:
            continue
        meta = node.metadata or {}
        label = meta.get("caption") or meta.get("qualname")
        if not label:
            parts = [p.strip() for p in (node.breadcrumb or "").split(SEPARATOR.strip()) if p.strip()]
            parts = parts[1:] if parts and parts[0] == title.strip() else parts
            label = SEPARATOR.join(parts[-2:])
        if label and label not in found:
            found.append(str(label)[:160])
        if len(found) == CONTENTS_MAX:
            break
    return found


def card_text(
    fields: DocumentFields,
    *,
    folder_path: str | None,
    summary: str | None,
    entities: list[str],
    contents: list[str],
    category: str | None = None,
) -> str:
    kind = [str(fields.doc_kind)]
    if category and category != str(fields.doc_kind):
        kind.append(category.replace("_", " "))
    if fields.source_origin:
        kind.append("external" if fields.source_origin == SourceOrigin.EXTERNAL_KEPT else "internal")
    if fields.publisher:
        kind.append(fields.publisher)
    if fields.standard_id:
        kind.append(f"{fields.standard_id} {fields.standard_revision or ''}".strip())
    if fields.revision_marker:
        kind.append(f"rev {fields.revision_marker}")
    if fields.doc_date:
        kind.append(fields.doc_date.isoformat())
    labels = [
        f"{word} {value}"
        for word, value in (
            ("plan", fields.test_plan_id),
            ("run", fields.test_run_id),
            ("hardware", fields.hardware_item),
        )
        if value
    ]
    lines = [fields.title, "Kind: " + " · ".join(kind)]
    if labels:
        lines.append("Test: " + " · ".join(labels))
    if folder_path:
        lines.append(f"Path: {folder_path}")
    if summary:
        lines.append(f"Summary: {' '.join(summary.split())}")
    if entities:
        lines.append("Entities: " + ", ".join(entities[:ENTITIES_MAX]))
    if contents:
        lines.append("Contains: " + "; ".join(contents))
    return "\n".join(lines)[:CARD_MAX_CHARS]


def card_codes(text: str) -> str:
    """The card's identifiers, normalized like `document_nodes.content_codes` (TP12 INJ14 T04 SV-3 …)."""
    return content_codes(text)


def folder_path(folder_context: dict | None) -> str | None:
    crumbs = (folder_context or {}).get("breadcrumb") or []
    return SEPARATOR.join(crumbs) or None


def write_halted_card(
    document: Any,
    fields: DocumentFields,
    *,
    embed: Callable[[list[str], list[str | None]], list[list[float]]] | None,
) -> None:
    """A halted file has no pieces in the index, but it has a card, so the catalog can say it exists and why
    it is held. Without the models role the card is kept without a vector (the re-index fills it)."""
    text = card_text(
        fields,
        folder_path=folder_path(document.folder_context),
        summary=fields.summary,
        entities=[],
        contents=[],
    )
    document.search_text = text
    document.card_codes = card_codes(text)
    if embed is None:
        return
    try:
        document.card_embedding = embed([text], [fields.title])[0]
    except Exception as exc:  # the models role being down must not undo the halt
        log.warning("card vector of halted %s not computed: %s", document.doc_id, exc)


def models_embedder() -> Callable[[list[str], list[str | None]], list[list[float]]] | None:
    """The models role's document embedder, or None without ``DCL_MODELS_URL``."""
    from backend.config import get_settings
    from backend.llm_engine.local_models import ModelsClient

    url = get_settings().models_url
    return ModelsClient(base_url=str(url)).embed_documents if url else None
