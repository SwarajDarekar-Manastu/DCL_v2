"""VisionService: every vision call of routes A1, C-XLSX, D, E and F (file 03 §3).

One place for prompts (versioned files under llm_engine/prompts/vision), schemas (vision/schemas.py), the
cache and the call context. Gemini is reached only through S4's GeminiClient; its ledger hook writes the
llm_calls row from the CallContext built here (purpose, prompt_version, doc_id, node_anchor).

Cache: `dcl-cir/_vision_cache/{model}/{prompt_version}/{input_sha256}.json`. A hit makes no gateway call and
no ledger row, so identical crops (the same logo on 300 pages) cost once. The store is anything with
`get(key) -> bytes | None` and `put(key, data)`; in the workers it is `vision_cache()`, S1's BucketStore on
dcl-cir.

Only the client's adapter-neutral interface is used (`generate_sync(model=, messages=, context=, schema=,
**options)` with `Message`/`Text`/`Image` parts and the options thinking, media_resolution, temperature), so
the gateway's wire format (S4's adapters) never leaks in here.

Methods are synchronous (Celery prefork workers on cpu_parse and media). CapabilityUnavailable (image input
not enabled on the gateway), BudgetExhausted (retry later) and StructuredOutputError propagate to the route.
"""

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol

from backend.config import Settings, ThinkingLevel, get_settings
from backend.llm_engine.gemini_client import GeminiClient
from backend.llm_engine.gemini_types import CallContext, Image, Message, Text
from backend.llm_engine.model_ids import Tier, model_id
from backend.llm_engine.prompts import load_prompt
from backend.llm_engine.vision.schemas import (
    HandwritingReading,
    HardwarePhotoReading,
    ImageClassification,
    PageTranscription,
    PageTriage,
    PlotReading,
    Reading,
    SchematicReading,
    SlideReading,
    TableReading,
    VideoTimeline,
)

FLASH = Tier.FLASH
FLASH_LITE = Tier.LITE
CACHE_PREFIX = "_vision_cache"
PROMPT_AREA = "vision"


class VisionCapability(StrEnum):
    TRIAGE_PAGE = "triage_page"
    TRANSCRIBE_PAGE = "transcribe_page"
    TRANSCRIBE_HANDWRITING = "transcribe_handwriting"
    READ_TABLE_IMAGE = "read_table_image"
    DIGITIZE_PLOT = "digitize_plot"
    READ_SCHEMATIC = "read_schematic"
    INSPECT_HARDWARE_PHOTO = "inspect_hardware_photo"
    DESCRIBE_SLIDE = "describe_slide"
    VIDEO_TIMELINE = "video_timeline"
    CLASSIFY_IMAGE = "classify_image"


@dataclass(frozen=True)
class Task:
    prompt_version: str
    schema: type[Reading]
    tier: Tier
    media_resolution: str
    thinking: ThinkingLevel

    @property
    def model(self) -> str:
        """The model id of the task's tier, from the settings (GEMINI_MODEL / GEMINI_LITE_MODEL)."""
        return model_id(self.tier)


TASKS: dict[VisionCapability, Task] = {
    VisionCapability.TRIAGE_PAGE: Task(
        "triage_page.v1", PageTriage, FLASH_LITE, "low", ThinkingLevel.MINIMAL
    ),
    VisionCapability.TRANSCRIBE_PAGE: Task(
        "transcribe_page.v2", PageTranscription, FLASH, "high", ThinkingLevel.LOW
    ),
    VisionCapability.TRANSCRIBE_HANDWRITING: Task(
        "transcribe_handwriting.v1", HandwritingReading, FLASH, "high", ThinkingLevel.LOW
    ),
    VisionCapability.READ_TABLE_IMAGE: Task(
        "read_table_image.v1", TableReading, FLASH, "high", ThinkingLevel.LOW
    ),
    VisionCapability.DIGITIZE_PLOT: Task("digitize_plot.v1", PlotReading, FLASH, "high", ThinkingLevel.LOW),
    VisionCapability.READ_SCHEMATIC: Task(
        "read_schematic.v1", SchematicReading, FLASH, "high", ThinkingLevel.LOW
    ),
    VisionCapability.INSPECT_HARDWARE_PHOTO: Task(
        "inspect_hardware_photo.v1", HardwarePhotoReading, FLASH, "medium", ThinkingLevel.LOW
    ),
    VisionCapability.DESCRIBE_SLIDE: Task(
        "describe_slide.v1", SlideReading, FLASH, "medium", ThinkingLevel.LOW
    ),
    VisionCapability.VIDEO_TIMELINE: Task(
        "video_timeline.v1", VideoTimeline, FLASH, "low", ThinkingLevel.LOW
    ),
    VisionCapability.CLASSIFY_IMAGE: Task(
        "classify_image.v1", ImageClassification, FLASH_LITE, "low", ThinkingLevel.MINIMAL
    ),
}


class VisionCache(Protocol):
    def get(self, key: str) -> bytes | None: ...

    def put(self, key: str, data: bytes) -> None: ...


@dataclass(frozen=True)
class VisionOutput[R: Reading]:
    """A reading plus what produced it; routes store model and prompt_version in the CIR (source = vlm)."""

    reading: R
    model: str
    prompt_version: str
    input_sha256: str
    cached: bool


def vision_cache(settings: Settings | None = None):
    """The production cache: S1's BucketStore on dcl-cir (MinIO settings from the env contract)."""
    from backend.storage.minio import CIR, BucketStore, client_from_settings

    return BucketStore(client_from_settings(settings or get_settings()), CIR)


def cache_key(model: str, prompt_version: str, input_sha256: str) -> str:
    return f"{CACHE_PREFIX}/{model}/{prompt_version}/{input_sha256}.json"


def input_hash(capability: VisionCapability, task: Task, parts: list[Text | Image]) -> str:
    """SHA-256 over everything that shapes the answer: task, rendered text, image bytes and their order."""
    described = [
        ["text", p.text]
        if isinstance(p, Text)
        else ["image", p.mime_type, hashlib.sha256(p.data).hexdigest()]
        for p in parts
    ]
    material = [str(capability), task.prompt_version, task.model, task.media_resolution, described]
    return hashlib.sha256(json.dumps(material, ensure_ascii=False).encode("utf-8")).hexdigest()


def _or_none(value: str | None) -> str:
    return value if value else "none"


class VisionService:
    def __init__(self, client: GeminiClient, cache: VisionCache):
        self._client = client
        self._cache = cache

    def triage_page(
        self, thumbnail: Image, *, context: str, doc_id: str | None = None, anchor: str | None = None
    ) -> VisionOutput[PageTriage]:
        return self._run(VisionCapability.TRIAGE_PAGE, [thumbnail], {"context": context}, doc_id, anchor)

    def transcribe_page(
        self,
        page: Image,
        *,
        context: str,
        language_hint: str | None = None,
        doc_id: str | None = None,
        anchor: str | None = None,
    ) -> VisionOutput[PageTranscription]:
        variables = {"context": context, "language_hint": _or_none(language_hint)}
        return self._run(VisionCapability.TRANSCRIBE_PAGE, [page], variables, doc_id, anchor)

    def transcribe_handwriting(
        self,
        crop: Image,
        *,
        field_label: str | None,
        allowed_units: list[str],
        context: str,
        doc_id: str | None = None,
        anchor: str | None = None,
    ) -> VisionOutput[HandwritingReading]:
        variables = {
            "field_label": _or_none(field_label),
            "allowed_units": ", ".join(allowed_units) or "none stated",
            "context": context,
        }
        return self._run(VisionCapability.TRANSCRIBE_HANDWRITING, [crop], variables, doc_id, anchor)

    def read_table_image(
        self,
        crop: Image,
        *,
        caption: str | None,
        context: str,
        doc_id: str | None = None,
        anchor: str | None = None,
    ) -> VisionOutput[TableReading]:
        variables = {"caption": _or_none(caption), "context": context}
        return self._run(VisionCapability.READ_TABLE_IMAGE, [crop], variables, doc_id, anchor)

    def digitize_plot(
        self,
        crop: Image,
        *,
        caption: str | None,
        context: str,
        doc_id: str | None = None,
        anchor: str | None = None,
    ) -> VisionOutput[PlotReading]:
        variables = {"caption": _or_none(caption), "context": context}
        return self._run(VisionCapability.DIGITIZE_PLOT, [crop], variables, doc_id, anchor)

    def read_schematic(
        self,
        crop: Image,
        *,
        caption: str | None,
        context: str,
        doc_id: str | None = None,
        anchor: str | None = None,
    ) -> VisionOutput[SchematicReading]:
        variables = {"caption": _or_none(caption), "context": context}
        return self._run(VisionCapability.READ_SCHEMATIC, [crop], variables, doc_id, anchor)

    def inspect_hardware_photo(
        self, photo: Image, *, folder_context: str, doc_id: str | None = None, anchor: str | None = None
    ) -> VisionOutput[HardwarePhotoReading]:
        variables = {"folder_context": folder_context}
        return self._run(VisionCapability.INSPECT_HARDWARE_PHOTO, [photo], variables, doc_id, anchor)

    def describe_slide(
        self,
        slide: Image,
        *,
        slide_text: str,
        context: str,
        doc_id: str | None = None,
        anchor: str | None = None,
    ) -> VisionOutput[SlideReading]:
        variables = {"slide_text": _or_none(slide_text), "context": context}
        return self._run(VisionCapability.DESCRIBE_SLIDE, [slide], variables, doc_id, anchor)

    def classify_image(
        self, image: Image, *, folder_context: str, doc_id: str | None = None, anchor: str | None = None
    ) -> VisionOutput[ImageClassification]:
        """Route D step 3: is this a hardware photo, a plot or screenshot, a document, a diagram, or other."""
        return self._run(
            VisionCapability.CLASSIFY_IMAGE, [image], {"folder_context": folder_context}, doc_id, anchor
        )

    def video_timeline(
        self,
        keyframes: list[tuple[float, Image]],
        *,
        folder_context: str,
        doc_id: str | None = None,
        anchor: str | None = None,
    ) -> VisionOutput[VideoTimeline]:
        """Keyframes with their time in seconds from the clip start; the gateway takes images, not video."""
        parts: list[Text | Image] = []
        for t_s, frame in keyframes:
            parts += [Text(f"t = {t_s:.2f} s"), frame]
        variables = {"folder_context": folder_context}
        return self._run(VisionCapability.VIDEO_TIMELINE, parts, variables, doc_id, anchor)

    def _run(
        self,
        capability: VisionCapability,
        media: list[Text | Image],
        variables: dict[str, str],
        doc_id: str | None,
        anchor: str | None,
    ) -> VisionOutput:
        task = TASKS[capability]
        prompt = load_prompt(PROMPT_AREA, task.prompt_version)
        parts: list[Text | Image] = [Text(prompt.render_user(**variables)), *media]
        digest = input_hash(capability, task, parts)
        key = cache_key(task.model, task.prompt_version, digest)

        cached = self._cache.get(key)
        if cached is not None:
            entry = json.loads(cached)
            reading = task.schema.model_validate(entry["reading"])
            return VisionOutput(reading, entry["model"], task.prompt_version, digest, cached=True)

        result = self._client.generate_sync(
            model=task.model,
            messages=[Message.system(prompt.system), Message.user(*parts)],
            context=CallContext(
                purpose=f"vision.{capability}",
                prompt_version=task.prompt_version,
                doc_id=doc_id,
                node_anchor=anchor,
            ),
            schema=task.schema,
            thinking=task.thinking,
            media_resolution=task.media_resolution,
            temperature=0.0,
        )
        reading = result.parsed
        entry = {
            "reading": reading.model_dump(mode="json", by_alias=True),
            "model": result.model or task.model,
            "prompt_version": task.prompt_version,
            "capability": str(capability),
            "request_id": result.request_id,
            "input_tokens": result.usage.input_tokens,
            "output_tokens": result.usage.output_tokens,
            "cached_at": datetime.now(UTC).isoformat(),
        }
        self._cache.put(key, json.dumps(entry, ensure_ascii=False).encode("utf-8"))
        return VisionOutput(reading, entry["model"], task.prompt_version, digest, cached=False)
