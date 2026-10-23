"""Answer Engine tools (file 07 §4): typed arguments, one result shape, provenance on everything.

Every tool takes a Pydantic argument model (its JSON schema is the function declaration Gemini sees, through
`tool_spec`) and returns a `ToolResult`: the structured `result`, the `provenance` of every source it used
(stable anchors, never node ids), `warnings`, and `display` — the text the synthesis step quotes. The verifier
checks every numeric claim against the `display` strings of the trace (file 07 §7), so a tool writes each
number exactly once, with its unit, the way the answer may state it.
"""

import uuid
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from backend.llm_engine.gemini_types import ToolSpec
from backend.postgres.enums import DocKind, SourceOrigin


class Provenance(StrEnum):
    MEASURED = "measured"
    INTERNAL_REPORT = "internal_report"
    STANDARD = "standard"
    VENDOR_CLAIM = "vendor_claim"
    LITERATURE = "literature"
    CALCULATION = "calculation"
    WEB = "web"
    USER_PROVIDED = "user_provided"  # a file the user attached in chat; answer-time only, never indexed


LITERATURE_KINDS = frozenset(
    {DocKind.ACADEMIC_PAPER, DocKind.ARTICLE, DocKind.BOOK_EXCERPT, DocKind.CONFERENCE_PAPER}
)
VENDOR_KINDS = frozenset({DocKind.DATASHEET, DocKind.VENDOR_BROCHURE})


def provenance_of(source_origin: str | None, doc_kind: str | None) -> Provenance:
    """The label every cited claim carries (file 07 §7, file 04 §2.3)."""
    if doc_kind == DocKind.TELEMETRY_RUN:
        return Provenance.MEASURED
    if doc_kind == DocKind.STANDARD:
        return Provenance.STANDARD
    if source_origin == SourceOrigin.EXTERNAL_KEPT:
        if doc_kind in LITERATURE_KINDS:
            return Provenance.LITERATURE
        return Provenance.VENDOR_CLAIM if doc_kind in VENDOR_KINDS else Provenance.LITERATURE
    return Provenance.INTERNAL_REPORT


class Source(BaseModel):
    """One cited source of a tool result."""

    doc_id: uuid.UUID | None = None
    anchor: str | None = Field(default=None, description="<kind>:<value>:<content_sha256>")
    title: str | None = None
    label: str = Field(description='how the answer names it: "Test Report 37, p. 8"')
    provenance: Provenance
    language: str | None = None
    needs_review: bool = False
    web_url: str | None = None
    url: str | None = Field(default=None, description="external URL for web sources")


class ToolResult(BaseModel):
    tool: str
    call_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    result: Any
    provenance: list[Source] = []
    warnings: list[str] = []
    display: str = Field(description="what synthesis may quote; every number appears here with its unit")


def tool_spec(name: str, description: str, arguments: type[BaseModel]) -> ToolSpec:
    """A Gemini function declaration from the argument model."""
    schema = arguments.model_json_schema()
    schema.pop("title", None)
    return ToolSpec(name=name, description=description, parameters=schema)


def page_label(title: str | None, page_no: int | None, extra: str | None = None) -> str:
    parts = [title or "untitled"]
    if page_no:
        parts.append(f"p. {page_no}")
    if extra:
        parts.append(extra)
    return ", ".join(parts)
