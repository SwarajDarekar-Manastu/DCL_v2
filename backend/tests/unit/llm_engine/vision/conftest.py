import pytest

from backend.llm_engine.gemini_types import (
    CallContext,
    Capability,
    CapabilityUnavailable,
    GenerateResult,
    Image,
    Message,
    StructuredOutputError,
    Usage,
)
from backend.llm_engine.vision.service import VisionService


class MemoryCache:
    def __init__(self):
        self.objects: dict[str, bytes] = {}

    def get(self, key):
        return self.objects.get(key)

    def put(self, key, data):
        self.objects[key] = data


class FakeClient:
    """Stands in for GeminiClient through its adapter-neutral interface only (no wire format).

    It records what VisionService asks for and, like the real client, refuses image parts while the
    image_input capability is off and raises StructuredOutputError for a reply that fails the schema.
    """

    def __init__(self, *readings: dict, image_input: bool = True):
        self.readings = list(readings)
        self.image_input = image_input
        self.calls: list[dict] = []
        self.contexts: list[CallContext] = []

    def generate_sync(self, *, model: str, messages: list[Message], context: CallContext, schema, **options):
        if not self.image_input and any(isinstance(p, Image) for m in messages for p in m.parts):
            raise CapabilityUnavailable(Capability.IMAGE_INPUT)
        self.calls.append({"model": model, "messages": messages, "schema": schema, **options})
        self.contexts.append(context)
        reading = self.readings.pop(0) if len(self.readings) > 1 else self.readings[0]
        try:
            parsed = schema.model_validate(reading)
        except ValueError:
            raise StructuredOutputError("response does not match the schema", raw_text=str(reading)) from None
        return GenerateResult(
            text=str(reading),
            parsed=parsed,
            tool_calls=(),
            usage=Usage(input_tokens=300, output_tokens=40),
            model=model,
            finish_reason="stop",
            request_id=f"req-{len(self.calls)}",
            latency_ms=5,
        )


@pytest.fixture
def make_service():
    def build(*readings, image_input=True, **service_options):
        client = FakeClient(*readings, image_input=image_input)
        cache = MemoryCache()
        return VisionService(client, cache, **service_options), client, cache

    return build
