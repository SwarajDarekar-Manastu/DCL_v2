"""Chat attachments (file 07 §9.7, file 08 §2.1): files the user attached, read at answer time, never indexed.

The Pipe uploads each attached file and sends a presigned GET URL. `fetch` reads it once with a size cap.
`read_attachment` turns it into user-provided evidence for the planner and synthesis:

- text-like files (`text/*`, JSON, CSV, Markdown, source code) are decoded and used as they are;
- PDFs and images go to Gemini through the gateway with prompt `engine/attachment.v1`, which transcribes
  what bears on the question (numbers kept verbatim) or describes a photo;
- Word, PowerPoint and spreadsheet files are converted to PDF by S4's LibreOffice client first.

The result is a `ToolResult` (tool `user_attachment`) whose source has provenance `user_provided` and the
label "<name> (your attachment)", so the answer can cite it and never mixes it with indexed evidence
unlabelled. An image attachment also yields its embedding so T3 can look for similar photos in the index.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass

import httpx

from backend.config import ThinkingLevel
from backend.llm_engine.engine.tools import Provenance, Source, ToolResult
from backend.llm_engine.gemini_types import CallContext, GeminiError, Image, Message, Pdf
from backend.llm_engine.model_ids import model_id
from backend.llm_engine.prompts import load_prompt

log = logging.getLogger(__name__)

NAME = "user_attachment"
PROMPT = "attachment.v1"
MAX_BYTES = 25 * 1024 * 1024  # the Pipe's MAX_ATTACHMENT_MB ceiling
MAX_TEXT_CHARS = 40_000
MAX_ATTACHMENTS = 5
TEXT_TYPES = ("text/", "application/json", "application/xml", "application/x-yaml", "application/csv")
TEXT_EXTENSIONS = (
    ".txt",
    ".md",
    ".csv",
    ".json",
    ".yaml",
    ".yml",
    ".py",
    ".m",
    ".tex",
    ".cfg",
    ".ini",
    ".log",
)
OFFICE_EXTENSIONS = {"docx", "doc", "rtf", "odt", "pptx", "ppt", "odp", "xlsx", "xls", "ods"}
IMAGE_TYPES = ("image/png", "image/jpeg", "image/webp")


class AttachmentTooLarge(ValueError):
    pass


@dataclass
class Attached:
    name: str
    mime_type: str
    data: bytes

    @property
    def extension(self) -> str:
        return self.name.rsplit(".", 1)[-1].lower() if "." in self.name else ""

    @property
    def is_image(self) -> bool:
        return self.mime_type in IMAGE_TYPES

    @property
    def is_text(self) -> bool:
        return self.mime_type.startswith(TEXT_TYPES) or self.name.lower().endswith(TEXT_EXTENSIONS)


def fetch(url: str, *, cap: int = MAX_BYTES, http: httpx.Client | None = None) -> bytes:
    """GET the presigned upload once, refusing more than `cap` bytes."""
    client = http or httpx.Client(timeout=60)
    try:
        with client.stream("GET", url) as response:
            response.raise_for_status()
            chunks, size = [], 0
            for chunk in response.iter_bytes():
                size += len(chunk)
                if size > cap:
                    raise AttachmentTooLarge(f"over {cap // (1024 * 1024)} MB")
                chunks.append(chunk)
            return b"".join(chunks)
    finally:
        if http is None:
            client.close()


def _source(item: Attached) -> Source:
    return Source(
        label=f"{item.name} (your attachment)", title=item.name, provenance=Provenance.USER_PROVIDED
    )


async def read_attachment(
    client,
    item: Attached,
    question: str,
    *,
    convert_office: Callable[..., bytes] | None = None,
    trace_id: str | None = None,
) -> ToolResult:
    """User-provided evidence from one attachment; a failure becomes a warning, not a failed answer."""
    try:
        if item.is_text:
            text = item.data.decode("utf-8", errors="replace")
            cut = len(text) > MAX_TEXT_CHARS
            text = text[:MAX_TEXT_CHARS] + ("\n[… file cut]" if cut else "")
        else:
            part = await _model_part(item, convert_office)
            prompt = load_prompt("engine", PROMPT)
            reply = await client.generate(
                model=model_id(),
                messages=[
                    Message.system(prompt.system),
                    Message.user(
                        prompt.render_user(question=question, name=item.name, mime=item.mime_type), part
                    ),
                ],
                context=CallContext(purpose="engine.attachment", prompt_version=PROMPT, trace_id=trace_id),
                thinking=ThinkingLevel.LOW,
                media_resolution="high",
            )
            text = reply.text.strip()
    except (GeminiError, ValueError, RuntimeError) as exc:
        log.warning("attachment %s could not be read: %s", item.name, exc)
        return ToolResult(
            tool=NAME,
            result={"name": item.name, "read": False},
            warnings=[f"the attachment {item.name} could not be read: {str(exc)[:200]}"],
            display=f"The attachment {item.name} could not be read.",
        )
    return ToolResult(
        tool=NAME,
        result={
            "name": item.name,
            "mime_type": item.mime_type,
            "read": True,
            "hits": [{"parent_text": text}],
        },
        provenance=[_source(item)],
        display=f"User-provided attachment {item.name} (answer-time only, not indexed):\n{text}",
    )


async def _model_part(item: Attached, convert_office: Callable[..., bytes] | None):
    if item.is_image:
        return Image(item.data, item.mime_type)
    if item.mime_type == "application/pdf" or item.extension == "pdf":
        return Pdf(item.data, item.name)
    if item.extension in OFFICE_EXTENSIONS:
        if convert_office is None:
            from backend.common.office import convert as convert_office
        import asyncio

        pdf = await asyncio.to_thread(convert_office, item.data, item.extension, "pdf")
        return Pdf(pdf, item.name.rsplit(".", 1)[0] + ".pdf")
    raise ValueError(f"unsupported attachment type {item.mime_type}")
