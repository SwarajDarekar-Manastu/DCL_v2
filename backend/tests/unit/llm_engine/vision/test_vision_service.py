import json

import pytest

from backend.llm_engine.gemini_types import Capabilities, CapabilityUnavailable, Image, StructuredOutputError
from backend.llm_engine.vision.schemas import HandwritingReading, PageTriage
from backend.llm_engine.vision.service import TASKS, VisionCapability

PNG = Image(b"\x89PNG fake crop bytes", "image/png")
OTHER_PNG = Image(b"\x89PNG another crop", "image/png")

TRIAGE = {
    "page_type": "scanned_form_with_handwriting",
    "has_handwriting": True,
    "has_tables": False,
    "has_figures": False,
    "is_rotated": False,
    "language": "en",
    "script": "latin",
    "handwriting_regions": [{"box_2d": [100, 200, 140, 380], "kind": "value"}],
}
HANDWRITING = {
    "field_label": "Injector orifice dia (mm)",
    "value_raw": "0.85",
    "value_number": 0.85,
    "unit": "mm",
    "confidence": 0.92,
    "alternatives": ["0.86"],
    "illegible": False,
    "notes": None,
}
READINGS = {
    VisionCapability.TRIAGE_PAGE: TRIAGE,
    VisionCapability.TRANSCRIBE_PAGE: {"markdown": "# Run sheet", "language": "de", "confidence": 0.8},
    VisionCapability.TRANSCRIBE_HANDWRITING: HANDWRITING,
    VisionCapability.READ_TABLE_IMAGE: {
        "html_table": "<table><tr><td>1</td></tr></table>",
        "n_rows": 1,
        "n_cols": 1,
        "header_rows": 0,
        "units_by_column": ["bar"],
        "confidence": 0.9,
    },
    VisionCapability.DIGITIZE_PLOT: {
        "plot_type": "line",
        "x_axis": {"label": "t", "unit": "s", "range": [0, 10]},
        "y_axes": [{"label": "Pc", "unit": "bar", "range": [0, 15]}],
        "series": [{"name": "PT-101", "key_points": [{"x": 1.0, "y": 12.4}], "trend": "plateau"}],
        "annotations": [],
        "confidence": 0.7,
    },
    VisionCapability.READ_SCHEMATIC: {
        "components": [{"tag": "SV-1", "type": "solenoid valve", "label": None}],
        "connections": [{"from": "F-101", "to": "SV-1", "medium": "propellant", "label": None}],
        "notes": None,
    },
    VisionCapability.INSPECT_HARDWARE_PHOTO: {
        "components_visible": ["injector"],
        "failure_modes": [{"mode": "erosion", "location": "face", "severity": "moderate", "confidence": 0.7}],
        "visible_text": ["INJ-14"],
        "test_stage_hint": "post_test",
        "description": "Eroded injector face, scale unknown.",
    },
    VisionCapability.DESCRIBE_SLIDE: {
        "summary": "Heater plan.",
        "diagram_description": None,
        "key_numbers": [],
    },
    VisionCapability.VIDEO_TIMELINE: {"events": [{"t_s": 0.4, "type": "ignition", "description": "flash"}]},
}
CALLS = {
    VisionCapability.TRIAGE_PAGE: lambda s: s.triage_page(PNG, context="TP37 run sheet p.1"),
    VisionCapability.TRANSCRIBE_PAGE: lambda s: s.transcribe_page(PNG, context="p.3", language_hint="de"),
    VisionCapability.TRANSCRIBE_HANDWRITING: lambda s: s.transcribe_handwriting(
        PNG, field_label="Injector orifice dia (mm)", allowed_units=["mm"], context="TP37"
    ),
    VisionCapability.READ_TABLE_IMAGE: lambda s: s.read_table_image(PNG, caption="Table 3", context="TP37"),
    VisionCapability.DIGITIZE_PLOT: lambda s: s.digitize_plot(PNG, caption="Figure 4", context="TP37"),
    VisionCapability.READ_SCHEMATIC: lambda s: s.read_schematic(PNG, caption=None, context="Rev C"),
    VisionCapability.INSPECT_HARDWARE_PHOTO: lambda s: s.inspect_hardware_photo(
        PNG, folder_context="APU / Test Plan 19 / Post-Explosion / burned_injector_mesh.jpg"
    ),
    VisionCapability.DESCRIBE_SLIDE: lambda s: s.describe_slide(
        PNG, slide_text="Heater plan", context="workshop"
    ),
    VisionCapability.VIDEO_TIMELINE: lambda s: s.video_timeline(
        [(0.0, PNG), (0.5, OTHER_PNG)], folder_context="TP19/cam1.mp4"
    ),
}


@pytest.mark.parametrize("capability", list(VisionCapability))
def test_every_capability_renders_its_prompt_and_returns_its_schema(make_service, capability):
    service, gateway, ledger, _ = make_service(READINGS[capability])
    output = CALLS[capability](service)
    assert isinstance(output.reading, TASKS[capability].schema)
    assert output.prompt_version == f"{capability}.v1"
    assert gateway.bodies[0]["model"] == TASKS[capability].model
    assert ledger[0].purpose == f"vision.{capability}"


def test_identical_crops_cost_once(make_service):
    service, gateway, ledger, cache = make_service(TRIAGE)
    first = service.triage_page(PNG, context="TP37 run sheet p.1", doc_id="doc-1")
    second = service.triage_page(PNG, context="TP37 run sheet p.1", doc_id="doc-2")
    assert (first.cached, second.cached) == (False, True)
    assert second.reading == first.reading
    assert len(gateway.requests) == 1
    assert len(ledger) == 1
    assert list(cache.objects) == [
        f"_vision_cache/gemini-3.5-flash-lite/triage_page.v1/{first.input_sha256}.json"
    ]


def test_different_bytes_or_context_are_new_calls(make_service):
    service, gateway, _, _ = make_service(TRIAGE)
    service.triage_page(PNG, context="p.1")
    service.triage_page(OTHER_PNG, context="p.1")
    service.triage_page(PNG, context="p.2")
    assert len(gateway.requests) == 3


def test_every_call_reaches_the_ledger_with_doc_reference_prompt_version_and_tokens(make_service):
    service, _, ledger, _ = make_service(HANDWRITING)
    service.transcribe_handwriting(
        PNG,
        field_label="dia (mm)",
        allowed_units=["mm"],
        context="TP37",
        doc_id="doc-9",
        anchor="page:3:ab12",
    )
    (record,) = ledger
    assert (record.purpose, record.prompt_version) == (
        "vision.transcribe_handwriting",
        "transcribe_handwriting.v1",
    )
    assert (record.doc_id, record.node_anchor) == ("doc-9", "page:3:ab12")
    assert (record.input_tokens, record.output_tokens, record.status) == (300, 40, "ok")


def test_request_carries_prompt_file_image_resolution_and_temperature_zero(make_service):
    service, gateway, _, _ = make_service(HANDWRITING)
    service.transcribe_handwriting(PNG, field_label="dia (mm)", allowed_units=["mm", "bar"], context="TP37")
    body = gateway.bodies[0]
    system, user = body["messages"][0], body["messages"][-1]
    assert "never invent or complete a digit" in system["content"]
    assert "Allowed units for this page: mm, bar" in user["content"][0]["text"]
    assert user["content"][1]["image_url"]["detail"] == "high"
    assert user["content"][1]["image_url"]["url"].startswith("data:image/png;base64,")
    assert body["temperature"] == 0.0
    assert body["response_format"]["json_schema"]["name"] == "HandwritingReading"


def test_image_capability_off_raises_before_any_request_or_cache_write(make_service):
    service, gateway, ledger, cache = make_service(TRIAGE, capabilities=Capabilities())
    with pytest.raises(CapabilityUnavailable):
        service.triage_page(PNG, context="p.1")
    assert (gateway.requests, ledger, cache.objects) == ([], [], {})


def test_invalid_reply_raises_and_is_not_cached(make_service):
    service, _, _, cache = make_service(json.dumps({"page_type": "poster"}))
    with pytest.raises(StructuredOutputError):
        service.triage_page(PNG, context="p.1")
    assert cache.objects == {}


def test_video_keyframes_are_sent_after_their_timestamps(make_service):
    service, gateway, _, _ = make_service(READINGS[VisionCapability.VIDEO_TIMELINE])
    service.video_timeline([(0.0, PNG), (0.5, OTHER_PNG)], folder_context="TP19/cam1.mp4")
    content = gateway.bodies[0]["messages"][-1]["content"]
    assert [c["type"] for c in content] == ["text", "text", "image_url", "text", "image_url"]
    assert [content[1]["text"], content[3]["text"]] == ["t = 0.00 s", "t = 0.50 s"]


@pytest.mark.parametrize(
    ("reply", "expected_number"),
    [
        ({**HANDWRITING, "illegible": True}, None),
        ({**HANDWRITING, "value_raw": "0.8?", "value_number": 0.85}, None),
        ({**HANDWRITING, "value_raw": "0,85 mm", "value_number": 0.85}, 0.85),
    ],
)
def test_handwriting_never_returns_a_guessed_digit(make_service, reply, expected_number):
    service, _, _, _ = make_service(reply)
    reading = service.transcribe_handwriting(
        PNG, field_label="dia", allowed_units=["mm"], context="TP37"
    ).reading
    assert reading.value_number == expected_number
    assert 0.0 <= reading.confidence <= 1.0
    assert reading.alternatives == ["0.86"]


def test_illegible_handwriting_drops_the_raw_value_and_caps_confidence():
    reading = HandwritingReading.model_validate({**HANDWRITING, "illegible": True, "confidence": 0.9})
    assert (reading.value_raw, reading.value_number, reading.confidence) == (None, None, 0.5)


@pytest.mark.parametrize("box", [[0, 0, 1001, 10], [500, 0, 400, 10], [0, 0, 10]])
def test_box_2d_must_be_ordered_and_within_0_1000(box):
    with pytest.raises(ValueError):
        PageTriage.model_validate({**TRIAGE, "handwriting_regions": [{"box_2d": box, "kind": "value"}]})


def test_media_resolution_per_capability_follows_file_03_section_3():
    expected = {
        "triage_page": "low",
        "transcribe_handwriting": "high",
        "transcribe_page": "high",
        "read_table_image": "high",
        "digitize_plot": "high",
        "read_schematic": "high",
        "inspect_hardware_photo": "medium",
        "describe_slide": "medium",
        "video_timeline": "low",
    }
    assert {str(c): t.media_resolution for c, t in TASKS.items()} == expected
