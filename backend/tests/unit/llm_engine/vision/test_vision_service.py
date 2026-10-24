import pytest

from backend.config import Settings, ThinkingLevel
from backend.llm_engine.gemini_types import (
    EXTRACTION_SAFETY,
    CapabilityUnavailable,
    Image,
    StructuredOutputError,
    Text,
)
from backend.llm_engine.vision.schemas import HandwritingReading, PageTriage
from backend.llm_engine.vision.service import (
    EXTRACTION_CAPABILITIES,
    TASKS,
    FileMetadata,
    VisionCapability,
    VisionService,
    extraction_safety,
    vision_cache,
)

VERSIONS = {
    VisionCapability.TRANSCRIBE_PAGE: 2,  # v2 (2026-10-22): page furniture as its own field
    VisionCapability.READ_SCHEMATIC: 2,  # v2 (2026-10-24): verbatim, mechanical drawings have no connections
    VisionCapability.VIDEO_TIMELINE: 2,  # v2 (2026-10-24): frames across the clip, what ignition looks like
}

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
IMAGE_METADATA = {"subject": "Injector face", "setting": "test cell", "hardware": ["INJ-14"]}
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
        "image_metadata": IMAGE_METADATA,
        "plot_type": "line",
        "x_axis": {"label": "t", "unit": "s", "range": [0, 10]},
        "y_axes": [{"label": "Pc", "unit": "bar", "range": [0, 15]}],
        "series": [{"name": "PT-101", "key_points": [{"x": 1.0, "y": 12.4}], "trend": "plateau"}],
        "annotations": [],
        "confidence": 0.7,
    },
    VisionCapability.READ_SCHEMATIC: {
        "image_metadata": IMAGE_METADATA,
        "components": [{"tag": "SV-1", "type": "solenoid valve", "label": None}],
        "connections": [{"from": "F-101", "to": "SV-1", "medium": "propellant", "label": None}],
        "notes": None,
    },
    VisionCapability.INSPECT_HARDWARE_PHOTO: {
        "image_metadata": IMAGE_METADATA,
        "components_visible": ["injector"],
        "failure_modes": [{"mode": "erosion", "location": "face", "severity": "moderate", "confidence": 0.7}],
        "visible_text": ["INJ-14"],
        "test_stage_hint": "post_test",
        "description": "Eroded injector face, scale unknown.",
    },
    VisionCapability.DESCRIBE_SLIDE: {
        "image_metadata": IMAGE_METADATA,
        "summary": "Heater plan.",
        "diagram_description": None,
        "key_numbers": [],
    },
    VisionCapability.VIDEO_TIMELINE: {
        "events": [{"t_s": 0.4, "type": "ignition", "description": "flash"}],
        "image_metadata": IMAGE_METADATA,
    },
    VisionCapability.CLASSIFY_IMAGE: {
        "image_class": "hardware_photo",
        "confidence": 0.9,
        "shows_people": False,
    },
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
    VisionCapability.CLASSIFY_IMAGE: lambda s: s.classify_image(PNG, folder_context="APU / TP19 / photos"),
    VisionCapability.VIDEO_TIMELINE: lambda s: s.video_timeline(
        [(0.0, PNG), (0.5, OTHER_PNG)], folder_context="TP19/cam1.mp4"
    ),
}


@pytest.mark.parametrize("capability", list(VisionCapability))
def test_every_capability_renders_its_prompt_and_returns_its_schema(make_service, capability):
    service, client, _ = make_service(READINGS[capability])
    output = CALLS[capability](service)
    assert isinstance(output.reading, TASKS[capability].schema)
    assert (
        output.prompt_version
        == TASKS[capability].prompt_version
        == f"{capability}.v{VERSIONS.get(capability, 1)}"
    )
    assert client.calls[0]["model"] == TASKS[capability].model
    assert client.calls[0]["schema"] is TASKS[capability].schema
    assert client.contexts[0].purpose == f"vision.{capability}"


def test_identical_crops_cost_once(make_service):
    service, client, cache = make_service(TRIAGE)
    first = service.triage_page(PNG, context="TP37 run sheet p.1", doc_id="doc-1")
    second = service.triage_page(PNG, context="TP37 run sheet p.1", doc_id="doc-2")
    assert (first.cached, second.cached) == (False, True)
    assert second.reading == first.reading
    assert len(client.calls) == 1
    assert list(cache.objects) == [
        f"_vision_cache/gemini-3.1-flash-lite/triage_page.v1/{first.input_sha256}.json"
    ]


def test_different_bytes_or_context_are_new_calls(make_service):
    service, client, _ = make_service(TRIAGE)
    service.triage_page(PNG, context="p.1")
    service.triage_page(OTHER_PNG, context="p.1")
    service.triage_page(PNG, context="p.2")
    assert len(client.calls) == 3


def test_every_call_carries_the_ledger_context_doc_reference_and_prompt_version(make_service):
    service, client, _ = make_service(HANDWRITING)
    service.transcribe_handwriting(
        PNG,
        field_label="dia (mm)",
        allowed_units=["mm"],
        context="TP37",
        doc_id="doc-9",
        anchor="page:3:ab12",
    )
    (context,) = client.contexts
    assert (context.purpose, context.prompt_version) == (
        "vision.transcribe_handwriting",
        "transcribe_handwriting.v1",
    )
    assert (context.doc_id, context.node_anchor) == ("doc-9", "page:3:ab12")


def test_call_sends_the_prompt_file_the_crop_resolution_thinking_and_temperature_zero(make_service):
    service, client, _ = make_service(HANDWRITING)
    service.transcribe_handwriting(PNG, field_label="dia (mm)", allowed_units=["mm", "bar"], context="TP37")
    call = client.calls[0]
    system, user = call["messages"]
    assert (system.role, user.role) == ("system", "user")
    assert "never invent or complete a digit" in system.parts[0].text
    assert user.parts[0] == Text("About this file:\nnot known")
    assert isinstance(user.parts[1], Text) and "Allowed units for this page: mm, bar" in user.parts[1].text
    assert user.parts[2] == PNG
    assert (call["media_resolution"], call["thinking"], call["temperature"]) == (
        "high",
        ThinkingLevel.LOW,
        0.0,
    )


def test_image_capability_off_raises_before_any_request_or_cache_write(make_service):
    service, client, cache = make_service(TRIAGE, image_input=False)
    with pytest.raises(CapabilityUnavailable):
        service.triage_page(PNG, context="p.1")
    assert (client.calls, cache.objects) == ([], {})


def test_invalid_reply_raises_and_is_not_cached(make_service):
    service, _, cache = make_service({"page_type": "poster"})
    with pytest.raises(StructuredOutputError):
        service.triage_page(PNG, context="p.1")
    assert cache.objects == {}


def test_video_keyframes_are_sent_after_their_timestamps(make_service):
    service, client, _ = make_service(READINGS[VisionCapability.VIDEO_TIMELINE])
    service.video_timeline([(0.0, PNG), (0.5, OTHER_PNG)], folder_context="TP19/cam1.mp4")
    parts = client.calls[0]["messages"][-1].parts
    assert [type(p).__name__ for p in parts] == ["Text", "Text", "Text", "Image", "Text", "Image"]
    assert [parts[2].text, parts[4].text] == ["t = 0.00 s", "t = 0.50 s"]


@pytest.mark.parametrize(
    ("reply", "expected_number"),
    [
        ({**HANDWRITING, "illegible": True}, None),
        ({**HANDWRITING, "value_raw": "0.8?", "value_number": 0.85}, None),
        ({**HANDWRITING, "value_raw": "0,85 mm", "value_number": 0.85}, 0.85),
    ],
)
def test_handwriting_never_returns_a_guessed_digit(make_service, reply, expected_number):
    service, _, _ = make_service(reply)
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
        "video_timeline": "medium",
        "classify_image": "low",
    }
    assert {str(c): t.media_resolution for c, t in TASKS.items()} == expected


def test_production_cache_is_the_cir_bucket():
    settings = Settings(
        _env_file=None,
        DCL_MINIO_ENDPOINT="http://minio:9000",
        DCL_MINIO_ACCESS_KEY="dcl-access",
        DCL_MINIO_SECRET_KEY="dcl-secret-value-0123456789",
    )
    assert vision_cache(settings).bucket == "dcl-cir"


def test_only_flash_lite_tasks_ask_for_minimal_thinking():
    """gemini-3.8-flash rejects "minimal" thinking with a non-retryable 400; 3.1 Flash-Lite accepts it."""
    minimal = {str(c) for c, t in TASKS.items() if t.thinking is ThinkingLevel.MINIMAL}
    assert minimal == {"triage_page", "classify_image"}
    assert all(TASKS[c].model == "gemini-3.1-flash-lite" for c in minimal)


def test_transcribe_page_v2_asks_for_furniture_and_the_schema_keeps_it():
    from backend.llm_engine.prompts import load_prompt
    from backend.llm_engine.vision.schemas import PageTranscription

    prompt = load_prompt("vision", "transcribe_page.v2")
    assert "furniture" in prompt.system and "Skip page headers" not in prompt.system
    reading = PageTranscription.model_validate(
        {"markdown": "x", "language": "en", "confidence": 0.9, "furniture": ["Test Plan 6"]}
    )
    assert reading.furniture == ["Test Plan 6"]
    assert (
        PageTranscription.model_validate({"markdown": "x", "language": "en", "confidence": 0.9}).furniture
        == []
    )


@pytest.mark.parametrize("capability", list(VisionCapability))
def test_safety_settings_are_off_by_default(make_service, capability):
    service, client, _ = make_service(READINGS[capability])
    CALLS[capability](service)
    assert "safety_settings" not in client.calls[0]


@pytest.mark.parametrize("capability", list(VisionCapability))
def test_the_flag_sends_extraction_safety_only_for_extraction_capabilities(make_service, capability):
    service, client, _ = make_service(READINGS[capability], extraction_safety=extraction_safety(True))
    CALLS[capability](service)
    expected = EXTRACTION_SAFETY if capability in EXTRACTION_CAPABILITIES else None
    assert client.calls[0].get("safety_settings") == expected


def test_the_config_value_names_capabilities_and_refuses_typos():
    assert len(extraction_safety(True)) == 7
    assert extraction_safety(None) == extraction_safety(False) == extraction_safety([]) == frozenset()
    assert extraction_safety(["transcribe_page"]) == {VisionCapability.TRANSCRIBE_PAGE}
    with pytest.raises(ValueError, match="triage_page"):
        extraction_safety(["triage_page"])
    with pytest.raises(ValueError, match="must be true"):
        extraction_safety("yes")


FILE = FileMetadata(
    file_name="IMG_0042.HEIC",
    folder_path="APU/Test Campaign 2/Test Plan 19/Photos",
    site="APU",
    modified_at="2025-11-20",
    test_plan_id="TP19",
    hardware_item="INJ14",
    other_locations=("APU/Archive/IMG_0042.HEIC",),
)


def test_every_call_starts_with_the_shared_preamble_and_the_files_own_metadata(make_service):
    service, client, _ = make_service(READINGS[VisionCapability.INSPECT_HARDWARE_PHOTO], file=FILE)
    service.inspect_hardware_photo(PNG, folder_context="TP19/Photos")
    system, user = client.calls[0]["messages"]
    preamble, task = system.parts[0].text.split("\n\n", 1)[0], system.parts[0].text
    assert "document library of a rocket propulsion team" in preamble
    assert "You inspect one photo of rocket propulsion hardware" in task
    assert user.parts[0].text.splitlines() == [
        "About this file:",
        "File name: IMG_0042.HEIC",
        "Folder: APU/Test Campaign 2/Test Plan 19/Photos",
        "Site: APU",
        "Test plan: TP19",
        "Hardware: INJ14",
        "Last modified: 2025-11-20",
        "Also stored in: APU/Archive/IMG_0042.HEIC",
    ]


def test_the_same_image_in_two_files_is_two_cache_entries(make_service):
    reading = READINGS[VisionCapability.INSPECT_HARDWARE_PHOTO]
    one, client, cache = make_service(reading, reading, file=FILE)
    other = VisionService(client, cache, file=FileMetadata(file_name="other.jpg"))
    first = one.inspect_hardware_photo(PNG, folder_context="x")
    second = other.inspect_hardware_photo(PNG, folder_context="x")
    assert first.input_sha256 != second.input_sha256 and len(client.calls) == 2
    assert one.inspect_hardware_photo(PNG, folder_context="x").cached is True


def test_image_metadata_comes_back_with_the_reading(make_service):
    reply = {
        **READINGS[VisionCapability.INSPECT_HARDWARE_PHOTO],
        "image_metadata": {
            "subject": "Injector face after a hot fire",
            "setting": "test cell",
            "hardware": ["INJ14"],
            "test_context": "TP19 post-test",
            "from_metadata": "test plan and hardware from the folder",
        },
    }
    service, _, _ = make_service(reply, file=FILE)
    reading = service.inspect_hardware_photo(PNG, folder_context="x").reading
    assert reading.image_metadata.hardware == ["INJ14"] and reading.image_metadata.setting == "test cell"


def test_a_cache_hit_is_a_ledger_row_for_the_same_purpose_and_document(make_service):
    service, client, _ = make_service(TRIAGE)
    service.triage_page(PNG, context="p.1", doc_id="doc-1")
    service.triage_page(PNG, context="p.1", doc_id="doc-2", anchor="page:1")
    ((model, context),) = client.hits
    assert (model, context.purpose, context.doc_id, context.node_anchor) == (
        "gemini-3.1-flash-lite",
        "vision.triage_page",
        "doc-2",
        "page:1",
    )


def test_the_file_metadata_has_no_document_title_so_a_commit_cannot_change_the_cache_key():
    assert "document_title" not in FileMetadata.__dataclass_fields__


def test_a_reply_without_image_metadata_fails_the_schema_and_is_not_cached(make_service):
    reply = {
        k: v for k, v in READINGS[VisionCapability.INSPECT_HARDWARE_PHOTO].items() if k != "image_metadata"
    }
    service, _, cache = make_service(reply, file=FILE)
    with pytest.raises(StructuredOutputError):
        service.inspect_hardware_photo(PNG, folder_context="x")
    assert cache.objects == {}
