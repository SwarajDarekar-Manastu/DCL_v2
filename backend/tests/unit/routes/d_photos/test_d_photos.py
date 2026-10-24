import io
import random

import pytest

pytest.importorskip("imagehash")
from PIL import Image as PILImage  # noqa: E402
from PIL import ImageDraw  # noqa: E402

from backend.dispatcher.folder_context import build_folder_context  # noqa: E402
from backend.postgres.enums import AssetKind, DocKind, FlagSeverity, FlagType, NodeType  # noqa: E402
from backend.routes.d_photos import cluster_photos, normalize, process_photo  # noqa: E402

SHA = "e" * 64
FOLDER = build_folder_context("APU", ["APU", "Test Plan 19", "Post-Explosion"], "burned_injector_mesh.jpg")
HARDWARE = {
    "components_visible": ["injector", "mesh"],
    "failure_modes": [
        {"mode": "burn-through", "location": "mesh centre", "severity": "severe", "confidence": 0.8}
    ],
    "visible_text": ["INJ-14"],
    "test_stage_hint": "post_test",
    "description": "Burned injector mesh with a hole at the centre, scale unknown.",
}


def photo(
    width=800, height=600, *, gps=True, orientation=None, taken="2024:05:02 10:15:00", dark=False, seed=1
):
    rng = random.Random(seed)
    image = PILImage.new("RGB", (width, height))
    pixels = [(rng.randrange(0, 40 if dark else 255),) * 3 for _ in range(width * height)]
    image.putdata(pixels)
    exif = PILImage.Exif()
    exif[0x010F] = "Apple"
    exif[0x0110] = "iPhone 13"
    exif[0x0132] = taken
    if orientation:
        exif[0x0112] = orientation
    if gps:
        exif[0x8825] = {1: "N", 2: (18.0, 31.0, 12.0), 3: "E", 4: (73.0, 51.0, 30.0)}
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", exif=exif)
    return buffer.getvalue()


def plot_png():
    image = PILImage.new("RGB", (800, 600), "white")
    ImageDraw.Draw(image).line([(50, 550), (300, 100), (750, 120)], fill="blue", width=4)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def run(data, vision, store, **kw):
    return process_photo(
        data,
        blob_sha256=SHA,
        file_name="burned_injector_mesh.jpg",
        folder=FOLDER,
        vision=vision,
        put_asset=store,
        **kw,
    )


def test_hardware_photo_becomes_one_photo_node_with_web_and_thumb_assets(fake_vision, memory_store):
    store = memory_store("s3://dcl-assets/")
    vision = fake_vision(
        classify_image={"image_class": "hardware_photo", "confidence": 0.95, "shows_people": False},
        inspect_hardware_photo=HARDWARE,
    )
    doc, reading = run(photo(), vision, store)
    (node,) = doc.nodes
    assert node.node_type is NodeType.PHOTO and node.asset_ref == "photo:web" and node.page_no == 1
    assert "Burned injector mesh" in node.content and "Failure mode: burn-through" in node.content
    assert [c[0] for c in vision.calls] == ["classify_image", "inspect_hardware_photo"]
    assert (
        vision.calls[1][1]["folder_context"]
        == "APU / Test Plan 19 / Post-Explosion / burned_injector_mesh.jpg"
    )
    assert {a.kind for a in doc.assets} == {AssetKind.PHOTO_WEB, AssetKind.PHOTO_THUMB}
    web = PILImage.open(io.BytesIO(store.objects[f"photos/{SHA}/web.jpg"]))
    thumb = PILImage.open(io.BytesIO(store.objects[f"photos/{SHA}/thumb.jpg"]))
    assert max(web.size) == 800 and max(thumb.size) == 256
    assert (doc.document.doc_kind, doc.document.doc_date.isoformat(), doc.document.date_source) == (
        DocKind.HARDWARE_PHOTO,
        "2024-05-02",
        "exif",
    )
    assert doc.flags == []


def test_gps_is_never_stored(fake_vision, memory_store):
    store = memory_store("s3://dcl-assets/")
    vision = fake_vision(
        classify_image={"image_class": "hardware_photo", "confidence": 0.9, "shows_people": False},
        inspect_hardware_photo=HARDWARE,
    )
    doc, _ = run(photo(gps=True), vision, store)
    for key in (f"photos/{SHA}/web.jpg", f"photos/{SHA}/thumb.jpg"):
        exif = PILImage.open(io.BytesIO(store.objects[key])).getexif()
        assert 0x8825 not in exif and len(exif) == 0
    for asset in doc.assets:
        assert not any("gps" in k.lower() for k in asset.exif) and "18.0" not in str(asset.exif)
    assert "18.0" not in doc.model_dump_json()
    assert normalize(photo(gps=True)).exif["make"] == "Apple"


def test_exif_orientation_is_applied_before_anything_else():
    assert normalize(photo(800, 600, orientation=6)).image.size == (600, 800)


def test_heic_decodes(fake_vision, memory_store):
    pillow_heif = pytest.importorskip("pillow_heif")
    heif = pillow_heif.from_pillow(PILImage.open(io.BytesIO(photo(gps=False))))
    buffer = io.BytesIO()
    heif.save(buffer, quality=80)
    assert normalize(buffer.getvalue()).image.size == (800, 600)


def test_plot_goes_to_digitize_plot_and_people_get_no_description(fake_vision, memory_store):
    plot = {
        "plot_type": "line",
        "x_axis": {"label": "t", "unit": "s", "range": [0, 10]},
        "y_axes": [],
        "series": [],
        "annotations": [],
        "confidence": 0.7,
    }
    vision = fake_vision(
        classify_image={"image_class": "plot_or_screenshot", "confidence": 0.9, "shows_people": False},
        digitize_plot=plot,
    )
    doc, _ = run(plot_png(), vision, memory_store("s3://dcl-assets/"))
    assert [c[0] for c in vision.calls] == ["classify_image", "digitize_plot"]
    assert doc.document.doc_kind is DocKind.PLOT_FIGURE and doc.nodes[0].content.startswith("Plot (line)")
    people = fake_vision(
        classify_image={"image_class": "people_or_other", "confidence": 0.9, "shows_people": True}
    )
    doc, _ = run(photo(seed=2), people, memory_store("s3://dcl-assets/"))
    assert [c[0] for c in people.calls] == ["classify_image"] and doc.nodes == []


def test_low_confidence_and_export_markings_raise_flags(fake_vision, memory_store):
    reading = {
        **HARDWARE,
        "failure_modes": [{"mode": "crack", "location": "?", "severity": "minor", "confidence": 0.3}],
        "visible_text": ["EXPORT CONTROLLED"],
    }
    vision = fake_vision(
        classify_image={"image_class": "hardware_photo", "confidence": 0.9, "shows_people": False},
        inspect_hardware_photo=reading,
    )
    doc, _ = run(photo(), vision, memory_store("s3://dcl-assets/"))
    assert sorted((f.flag_type, f.severity) for f in doc.flags) == [
        (FlagType.LOW_CONFIDENCE_EXTRACTION, FlagSeverity.SOFT),
        (FlagType.SENSITIVE_CONTENT, FlagSeverity.HARD),
    ]


def test_a_marking_inside_another_word_is_not_a_marking(fake_vision, memory_store):
    reading = {**HARDWARE, "visible_text": ["SANITARY FITTING", "MILITARY GRADE"]}
    vision = fake_vision(
        classify_image={"image_class": "hardware_photo", "confidence": 0.9, "shows_people": False},
        inspect_hardware_photo=reading,
    )
    doc, _ = run(photo(), vision, memory_store("s3://dcl-assets/"))
    assert all(f.flag_type != FlagType.SENSITIVE_CONTENT for f in doc.flags)


def test_dark_photo_is_auto_contrasted_for_the_model(fake_vision, memory_store):
    seen = {}

    def classify(kw):
        return {"image_class": "people_or_other", "confidence": 0.9, "shows_people": False}

    vision = fake_vision(classify_image=classify)
    original = vision.classify_image

    def spy(image, **kw):
        seen["mean"] = sum(PILImage.open(io.BytesIO(image.data)).convert("L").getdata()) / (800 * 600)
        return original(image, **kw)

    vision.classify_image = spy
    run(photo(dark=True), vision, memory_store("s3://dcl-assets/"))
    assert seen["mean"] > 60  # the dark original averages about 20


def test_a_burst_costs_one_classification_and_one_inspection(fake_vision, memory_store):
    shots = {f"p{i}": photo(seed=7, taken=f"2024:05:02 10:15:{i * 5:02d}") for i in range(5)}
    shots["far"] = photo(seed=99, taken="2024:05:02 11:00:00")
    clusters = cluster_photos([(k, normalize(v).phash, normalize(v).taken_at) for k, v in shots.items()])
    assert {clusters[f"p{i}"] for i in range(5)} == {"p0"} and clusters["far"] == "far"
    vision = fake_vision(
        classify_image={"image_class": "hardware_photo", "confidence": 0.9, "shows_people": False},
        inspect_hardware_photo=HARDWARE,
    )
    _, reading = run(shots["p0"], vision, memory_store("s3://dcl-assets/"), cluster_id="p0")
    members = [
        run(
            shots[f"p{i}"], vision, memory_store("s3://dcl-assets/"), representative=reading, cluster_id="p0"
        )[0]
        for i in range(1, 5)
    ]
    assert len(vision.calls) == 2
    assert all(m.nodes[0].metadata["inherited"] for m in members)


def test_undecodable_bytes_are_a_hard_parse_failure(fake_vision, memory_store):
    doc, reading = run(b"not an image", fake_vision(), memory_store("s3://dcl-assets/"))
    assert reading is None and [(f.flag_type, f.severity) for f in doc.flags] == [
        (FlagType.PARSE_FAILURE, FlagSeverity.HARD)
    ]
