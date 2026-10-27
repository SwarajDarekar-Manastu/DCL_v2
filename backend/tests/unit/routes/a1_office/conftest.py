import pytest

from backend.llm_engine.vision import schemas
from backend.llm_engine.vision.service import VisionOutput
from backend.tests.unit.routes.vision_readings import with_image_metadata


class FakeVision:
    """VisionService stand-in: one canned reading per capability, every call recorded."""

    def __init__(self, **readings):
        self.readings = readings
        self.calls: list[tuple[str, dict]] = []

    def _out(self, capability, schema, **kwargs):
        self.calls.append((capability, kwargs))
        value = self.readings[capability]
        reading = value(kwargs) if callable(value) else value
        return VisionOutput(
            schema.model_validate(with_image_metadata(schema, reading)),
            "gemini-3.8-flash",
            f"{capability}.v1",
            "h",
            False,
        )

    def triage_page(self, image, **kw):
        return self._out("triage_page", schemas.PageTriage, **kw)

    def transcribe_page(self, image, **kw):
        return self._out("transcribe_page", schemas.PageTranscription, **kw)

    def read_table_image(self, image, **kw):
        return self._out("read_table_image", schemas.TableReading, **kw)

    def digitize_plot(self, image, **kw):
        return self._out("digitize_plot", schemas.PlotReading, **kw)

    def read_schematic(self, image, **kw):
        return self._out("read_schematic", schemas.SchematicReading, **kw)

    def inspect_hardware_photo(self, image, **kw):
        return self._out("inspect_hardware_photo", schemas.HardwarePhotoReading, **kw)

    def describe_slide(self, image, **kw):
        return self._out("describe_slide", schemas.SlideReading, **kw)


class MemoryStore:
    def __init__(self, prefix):
        self.prefix = prefix
        self.objects: dict[str, bytes] = {}

    def __call__(self, key, data):
        self.objects[key] = data
        return f"{self.prefix}{key}"


@pytest.fixture
def fake_vision():
    return FakeVision


@pytest.fixture
def memory_store():
    return MemoryStore
