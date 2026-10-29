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

Safety settings (DECISIONS 2026-10-22): the extraction capabilities may send
`gemini_types.EXTRACTION_SAFETY` (DANGEROUS_CONTENT at BLOCK_ONLY_HIGH), because propellant-chemistry pages
were blocked with the gateway defaults. It is off unless `pipeline_config` `vision.extraction_safety` turns it
on: `true` for all six extraction capabilities, or a list of capability names. Other capabilities never send
it. Refusals are not cached, so switching the flag on lets a refused page through on the next run.

Every call starts with the shared preamble `image_context.v2` (what the library is, how to use a file's
origin, the rules for every image) and the file's own ingestion metadata (`FileMetadata`): one service per
document run, made by the runner with `vision_for(session, file=...)`, so each file's calls carry that file's
metadata and never another's (user, 2026-10-24). The metadata is part of the cache key.

Methods are synchronous (Celery prefork workers on cpu_parse and media). CapabilityUnavailable (image input
not enabled on the gateway), BudgetExhausted (retry later) and StructuredOutputError propagate to the route.
"""

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol

from backend.config import Settings, ThinkingLevel, get_settings
from backend.llm_engine.gemini_client import GeminiClient
from backend.llm_engine.gemini_types import EXTRACTION_SAFETY, CallContext, Image, Message, Text
from backend.llm_engine.model_ids import Tier, model_id
from backend.llm_engine.prompts import load_prompt
from backend.llm_engine.vision.schemas import (
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

PREAMBLE_VERSION = "image_context.v2"
FLASH = Tier.FLASH
FLASH_LITE = Tier.LITE
CACHE_PREFIX = "_vision_cache"
PROMPT_AREA = "vision"


class VisionCapability(StrEnum):
    TRIAGE_PAGE = "triage_page"
    TRANSCRIBE_PAGE = "transcribe_page"
    READ_TABLE_IMAGE = "read_table_image"
    DIGITIZE_PLOT = "digitize_plot"
    READ_SCHEMATIC = "read_schematic"
    INSPECT_HARDWARE_PHOTO = "inspect_hardware_photo"
    DESCRIBE_SLIDE = "describe_slide"
    VIDEO_TIMELINE = "video_timeline"
    CLASSIFY_IMAGE = "classify_image"


EXTRACTION_CAPABILITIES = frozenset(
    {
        VisionCapability.TRANSCRIBE_PAGE,
        VisionCapability.READ_TABLE_IMAGE,
        VisionCapability.DIGITIZE_PLOT,
        VisionCapability.READ_SCHEMATIC,
        VisionCapability.DESCRIBE_SLIDE,
        VisionCapability.VIDEO_TIMELINE,
    }
)
SAFETY_CONFIG_KEY = "vision.extraction_safety"


def extraction_safety(value: object) -> frozenset[VisionCapability]:
    """The capabilities that send EXTRACTION_SAFETY, from the `vision.extraction_safety` config value.

    `true` → all extraction capabilities; a list → those named; absent, `false` or empty → none. A name
    that is not an extraction capability is refused, so a typo cannot silently leave the flag off."""
    if value is None or value is False:
        return frozenset()
    if value is True:
        return EXTRACTION_CAPABILITIES
    if not isinstance(value, list | tuple):
        raise ValueError(f"{SAFETY_CONFIG_KEY} must be true, false or a list of capabilities, got {value!r}")
    unknown = sorted(str(v) for v in value if v not in EXTRACTION_CAPABILITIES)
    if unknown:
        raise ValueError(f"{SAFETY_CONFIG_KEY}: not extraction capabilities: {', '.join(unknown)}")
    return frozenset(VisionCapability(v) for v in value)


def extraction_safety_from(session) -> frozenset[VisionCapability]:
    """`extraction_safety` read from `pipeline_config` (default off)."""
    from backend.postgres import pipeline_config

    return extraction_safety(pipeline_config.get(session, SAFETY_CONFIG_KEY, None))


@dataclass(frozen=True)
class Task:
    prompt_version: str
    schema: type[Reading]
    tier: Tier
    media_resolution: str
    thinking: ThinkingLevel
    max_output_tokens: int  # about 2-3x the largest complete reply in llm_calls (26 Oct): stops only runaways

    @property
    def model(self) -> str:
        """The model id of the task's tier, from the settings (GEMINI_MODEL / GEMINI_LITE_MODEL)."""
        return model_id(self.tier)


TASKS: dict[VisionCapability, Task] = {
    VisionCapability.TRIAGE_PAGE: Task(
        "triage_page.v2", PageTriage, FLASH_LITE, "low", ThinkingLevel.MINIMAL, 1_024
    ),
    VisionCapability.TRANSCRIBE_PAGE: Task(
        "transcribe_page.v3", PageTranscription, FLASH, "high", ThinkingLevel.LOW, 16_384
    ),
    VisionCapability.READ_TABLE_IMAGE: Task(
        "read_table_image.v1", TableReading, FLASH, "high", ThinkingLevel.LOW, 16_384
    ),
    VisionCapability.DIGITIZE_PLOT: Task(
        "digitize_plot.v2", PlotReading, FLASH, "high", ThinkingLevel.LOW, 24_576
    ),
    VisionCapability.READ_SCHEMATIC: Task(
        "read_schematic.v3", SchematicReading, FLASH, "high", ThinkingLevel.LOW, 12_288
    ),
    VisionCapability.INSPECT_HARDWARE_PHOTO: Task(
        "inspect_hardware_photo.v2", HardwarePhotoReading, FLASH, "medium", ThinkingLevel.LOW, 12_288
    ),
    VisionCapability.DESCRIBE_SLIDE: Task(
        "describe_slide.v1", SlideReading, FLASH, "medium", ThinkingLevel.LOW, 8_192
    ),
    VisionCapability.VIDEO_TIMELINE: Task(
        "video_timeline.v4", VideoTimeline, FLASH, "medium", ThinkingLevel.LOW, 8_192
    ),
    VisionCapability.CLASSIFY_IMAGE: Task(
        "classify_image.v1", ImageClassification, FLASH_LITE, "low", ThinkingLevel.MINIMAL, 1_024
    ),
}


@dataclass(frozen=True)
class FileMetadata:
    """Where one file comes from, from its ingestion record (drive item, folder context, document row)."""

    file_name: str
    folder_path: str | None = None
    site: str | None = None  # the synced OneDrive root
    created_at: str | None = None
    modified_at: str | None = None
    parent: str | None = None  # the file this one was taken out of (archive member, attachment)
    test_plan_id: str | None = None
    test_run_id: str | None = None
    hardware_item: str | None = None
    source_origin: str | None = None
    other_locations: tuple[str, ...] = ()

    def render(self) -> str:
        fields = [
            ("File name", self.file_name),
            ("Folder", self.folder_path),
            ("Site", self.site),
            ("Taken out of", self.parent),
            ("Test plan", self.test_plan_id),
            ("Test run", self.test_run_id),
            ("Hardware", self.hardware_item),
            ("Origin", self.source_origin),
            ("Created", self.created_at),
            ("Last modified", self.modified_at),
        ]
        lines = [f"{label}: {value}" for label, value in fields if value]
        if self.other_locations:
            lines.append("Also stored in: " + "; ".join(self.other_locations))
        return "\n".join(lines)


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
    material = [
        str(capability),
        task.prompt_version,
        PREAMBLE_VERSION,
        task.model,
        task.media_resolution,
        described,
    ]
    return hashlib.sha256(json.dumps(material, ensure_ascii=False).encode("utf-8")).hexdigest()


def _or_none(value: str | None) -> str:
    return value if value else "none"


class VisionService:
    def __init__(
        self,
        client: GeminiClient,
        cache: VisionCache,
        *,
        extraction_safety: frozenset[VisionCapability] = frozenset(),
        file: FileMetadata | None = None,
    ):
        self._client = client
        self._cache = cache
        self._safety = extraction_safety & EXTRACTION_CAPABILITIES
        self._file = file

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
        duration_s: float | None = None,
        has_audio: bool | None = None,
        nearby_files: Sequence[str] = (),
        frame_plan: str = "",
        first_minute_speech: str = "",
        doc_id: str | None = None,
        anchor: str | None = None,
    ) -> VisionOutput[VideoTimeline]:
        """Keyframes with their time in seconds from the clip start; the gateway takes images, not video. The
        clip's own facts go with them (plan step D), so the model can tell what kind of recording it is."""
        parts: list[Text | Image] = []
        for t_s, frame in keyframes:
            parts += [Text(f"t = {t_s:.2f} s"), frame]
        variables = {
            "folder_context": folder_context,
            "duration_s": f"{duration_s:.1f}" if duration_s is not None else "not known",
            "has_audio": {True: "yes", False: "no", None: "not known"}[has_audio],
            "nearby_files": ", ".join(nearby_files) or "none",
            "frame_plan": frame_plan or "not stated",
            "first_minute_speech": first_minute_speech or "none",
        }
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
        preamble = load_prompt(PROMPT_AREA, PREAMBLE_VERSION)
        about = preamble.render_user(file_metadata=self._file.render() if self._file else "not known")
        parts: list[Text | Image] = [Text(about), Text(prompt.render_user(**variables)), *media]
        digest = input_hash(capability, task, parts)
        key = cache_key(task.model, task.prompt_version, digest)

        context = CallContext(
            purpose=f"vision.{capability}",
            prompt_version=task.prompt_version,
            doc_id=doc_id,
            node_anchor=anchor,
        )
        cached = self._cache.get(key)
        if cached is not None:
            entry = json.loads(cached)
            reading = task.schema.model_validate(entry["reading"])
            self._client.record_cache_hit(task.model, context)  # the ledger shows what the re-run did not pay
            return VisionOutput(reading, entry["model"], task.prompt_version, digest, cached=True)

        result = self._client.generate_sync(
            model=task.model,
            messages=[Message.system(f"{preamble.system}\n\n{prompt.system}"), Message.user(*parts)],
            context=context,
            schema=task.schema,
            thinking=task.thinking,
            max_output_tokens=task.max_output_tokens,
            media_resolution=task.media_resolution,
            temperature=0.0,
            **({"safety_settings": EXTRACTION_SAFETY} if capability in self._safety else {}),
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
