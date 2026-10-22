"""T3 relook and the photo strip, with a fake Gemini client (the search itself is tested on a database)."""

import asyncio
import uuid

import pytest
from pydantic import TypeAdapter

from backend.api.engine import EmbedEvent
from backend.llm_engine.engine.tools import Provenance, Source, ToolResult
from backend.llm_engine.engine.tools.visuals import RELOOK_PROMPT, node_types, relook
from backend.llm_engine.gemini_types import GenerateResult, Image, Usage

DOC = uuid.UUID("00000000-0000-4000-8000-000000000041")


def visual(n):
    return {
        "doc_id": str(DOC),
        "title": "TP07 post-test photos",
        "anchor": f"page:1:{n:064d}",
        "node_type": "photo",
        "reading": f"Catalyst screen photo {n}",
        "breadcrumb": f"TP07 › photo {n}",
        "asset_uri": f"s3://dcl-assets/photos/{n}.jpg",
        "url_web": f"https://minio.test/{n}.jpg",
        "url_thumb": f"https://minio.test/{n}_t.jpg",
    }


def t3_result(count=6):
    source = Source(
        doc_id=DOC,
        anchor="page:1:" + "0" * 64,
        title="TP07 post-test photos",
        label="TP07 post-test photos, p. 1",
        provenance=Provenance.INTERNAL_REPORT,
    )
    return ToolResult(
        tool="inspect_visuals",
        call_id="c1",
        result={"visuals": [visual(n) for n in range(count)], "hits": []},
        provenance=[source],
        display="6 photos",
    )


class Client:
    def __init__(self):
        self.calls = []

    async def generate(self, *, model, messages, context, schema=None, **options):
        self.calls.append((messages, context))
        parsed = schema.model_validate(
            {
                "answer": "The screen in image 1 is deformed.",
                "images": [{"image": 1, "observation": "ring buckled", "visible": "yes"}],
            }
        )
        return GenerateResult(
            text="",
            parsed=parsed,
            tool_calls=(),
            usage=Usage(1, 1),
            model=model,
            finish_reason="stop",
            request_id="r",
            latency_ms=1,
        )


def test_relook_sends_at_most_four_images_and_persists_nothing():
    client, fetched = Client(), []

    def fetch(uri):
        fetched.append(uri)
        return b"\xff\xd8jpeg"

    result = asyncio.run(relook(client, t3_result(), "is the catalyst screen deformed?", fetch=fetch))
    [(messages, context)] = client.calls
    images = [p for m in messages for p in m.parts if isinstance(p, Image)]
    assert len(images) == 4 and len(fetched) == 4
    assert {i.mime_type for i in images} == {"image/jpeg"}
    assert context.prompt_version == RELOOK_PROMPT and context.purpose == "engine.relook"
    look = result.result["relook"]
    assert look["source"] == "relook" and look["persisted"] is False and look["images_sent"] == 4
    assert "not part of the indexed record" in result.result["hits"][-1]["parent_text"]
    assert result.provenance[-1].label.endswith("(looked at again)") and result.provenance[-1].needs_review


def test_relook_without_images_warns_and_calls_nothing():
    client = Client()
    empty = t3_result(0)
    result = asyncio.run(relook(client, empty, "deformed?", fetch=lambda uri: b""))
    assert client.calls == [] and result.warnings == ["no image to look at again"]


def test_kinds_map_to_node_types():
    assert node_types(["plot_figure"]) == ["figure"]
    assert node_types(["video_frame"]) == ["video_event"]
    assert set(node_types([])) == {"photo", "figure", "video_event", "diagram_summary"}


def test_photo_strip_is_an_escaped_embed_that_fits_the_wire_contract():
    pytest.importorskip("workflows", reason="llama-index-workflows is not installed")
    from backend.llm_engine.engine.workflow import photo_strips

    result = t3_result()
    result.result["visuals"][0]["breadcrumb"] = '<script>alert("x")</script>'
    [embed] = photo_strips([result])
    event = TypeAdapter(EmbedEvent).validate_python(embed)
    assert event.kind == "photo_strip" and event.html.count("<img") == 6
    assert "<script>" not in event.html and "https://minio.test/0_t.jpg" in event.html
    assert photo_strips([t3_result(0)]) == []
