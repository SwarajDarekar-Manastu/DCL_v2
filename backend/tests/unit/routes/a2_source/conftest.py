import hashlib
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from backend.dispatcher.folder_context import FolderContext
from backend.llm_engine.vision import schemas
from backend.llm_engine.vision.service import VisionOutput
from backend.postgres.enums import DocumentSourceRole

pytest.importorskip("pylatexenc")  # parse dependency group (arrives with docling)

from backend.routes.a2_source.route import SourceFile, Stores  # noqa: E402

REPO = Path(__file__).resolve().parents[5]
SAMPLES = REPO / "data" / "samples"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@dataclass
class MemoryStores:
    cir: dict[str, bytes] = field(default_factory=dict)
    assets: dict[str, bytes] = field(default_factory=dict)

    def stores(self) -> Stores:
        def put_cir(key: str, data: bytes) -> str:
            self.cir[key] = data
            return f"s3://dcl-cir/test/{key}"

        def put_asset(key: str, data: bytes) -> str:
            self.assets[key] = data
            return f"s3://dcl-assets/{key}"

        return Stores(put_cir=put_cir, put_asset=put_asset)


def source(path: str, text: str | bytes, role=DocumentSourceRole.PART) -> SourceFile:
    data = text.encode("utf-8") if isinstance(text, str) else text
    return SourceFile(path=path, blob_sha256=sha(data), data=data, role=role)


def primary(path: str, text: str | bytes) -> SourceFile:
    return source(path, text, DocumentSourceRole.PRIMARY)


@pytest.fixture
def folder() -> FolderContext:
    return FolderContext(
        root_name="APU",
        breadcrumb=["APU", "Test Campaign 1", "Test Plan 12", "APU - Firing"],
        path_cached="APU/Test Campaign 1/Test Plan 12/APU - Firing",
        test_plan_id="TP12",
    )


@pytest.fixture
def memory() -> MemoryStores:
    return MemoryStores()


class FakeVision:
    """classify_image + digitize_plot stand-in; every call recorded."""

    def __init__(self, image_class: str = "plot_or_screenshot"):
        self.image_class = image_class
        self.calls: list[str] = []

    def classify_image(self, image, **kw):
        self.calls.append("classify_image")
        reading = schemas.ImageClassification.model_validate(
            {"image_class": self.image_class, "confidence": 0.9, "shows_people": False}
        )
        return VisionOutput(reading, "gemini-3.1-flash-lite", "classify_image.v1", "h", False)

    def digitize_plot(self, image, **kw):
        self.calls.append("digitize_plot")
        reading = schemas.PlotReading.model_validate(
            {
                "plot_type": "line",
                "x_axis": {"label": "Time", "unit": "s", "range": [0, 10]},
                "y_axes": [{"label": "Chamber pressure", "unit": "bar", "range": [0, 12]}],
                "series": [
                    {"name": "Pc", "key_points": [{"x": 0, "y": 0}, {"x": 2, "y": 10.5}], "trend": "rise"}
                ],
                "annotations": [],
                "confidence": 0.8,
            }
        )
        return VisionOutput(reading, "gemini-3.8-flash", "digitize_plot.v1", "h", False)
