import shutil
import subprocess
from pathlib import Path

import pytest

from backend.dispatcher.folder_context import build_folder_context
from backend.postgres.enums import AssetKind, DocKind, FlagSeverity, FlagType, NodeType
from backend.routes.f_video import (
    Ignition,
    Word,
    detect_ignition,
    keyframe_times,
    process_video,
    transcribe_parts,
    windows,
)

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is not installed")
SHA = "f" * 64
TEST_CELL = build_folder_context("APU", ["APU", "Test Plan 19", "Videos"], "hotfire_T01.mp4")
WORKSHOP = build_folder_context("APU", ["APU", "Workshops"], "design_review.mp4")


def clip(tmp_path: Path, segments: list[tuple[str, float]], *, audio=False, fps=25) -> bytes:
    """Concatenated solid-colour segments (colour, seconds) at 25 fps, optionally with a sine tone."""
    out = tmp_path / "clip.mp4"
    args = ["ffmpeg", "-v", "error", "-y"]
    for colour, seconds in segments:
        args += ["-f", "lavfi", "-i", f"color=c={colour}:s=320x240:d={seconds}:r={fps}"]
    if audio:
        args += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={sum(s for _, s in segments)}"]
    graph = "".join(f"[{i}]" for i in range(len(segments))) + f"concat=n={len(segments)}:v=1:a=0[v]"
    args += ["-filter_complex", graph, "-map", "[v]"]
    if audio:
        args += ["-map", f"{len(segments)}:a", "-shortest"]
    args += ["-pix_fmt", "yuv420p", str(out)]
    subprocess.run(args, check=True)  # noqa: S603
    return out.read_bytes()


def test_ignition_detection_on_a_luminance_series():
    series = [2, 2, 2, 2, 2, 2, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 2, 2, 2, 2]
    result = detect_ignition(series)
    assert (result.t_ignition_ms, result.t_shutdown_ms, result.confidence) == (3000, 8000, 1.0)
    assert detect_ignition([10] * 20) == Ignition(None, None, 0.0)


def test_keyframes_at_the_specified_offsets():
    assert keyframe_times(Ignition(3000, 8000, 1.0), 10.0) == [2500, 3000, 3500, 5500, 8000]


TIMELINE = {
    "events": [
        {"t_s": 3.0, "type": "ignition", "description": "bright flash"},
        {"t_s": 5.5, "type": "steady_plume", "description": "steady white glow"},
    ],
    "anomalies": [],
}


@needs_ffmpeg
def test_test_cell_clip_end_to_end(tmp_path, fake_vision, memory_store):
    data = clip(tmp_path, [("black", 3), ("white", 5), ("black", 2)])
    vision = fake_vision(video_timeline=TIMELINE)
    store = memory_store("s3://dcl-assets/")
    doc = process_video(
        data, blob_sha256=SHA, file_name="hotfire_T01.mp4", folder=TEST_CELL, vision=vision, put_asset=store
    )
    catalog = doc.document.catalog
    assert abs(catalog["t0_ignition_video_ms"] - 3000) <= 500
    assert abs(catalog["t_shutdown_video_ms"] - 8000) <= 500
    assert doc.document.doc_kind is DocKind.VIDEO_TIMELINE and doc.document.test_plan_id == "TP19"
    timeline, *events = doc.nodes
    assert timeline.node_type is NodeType.PARENT and timeline.t_start_ms == 0
    assert all(
        e.node_type is NodeType.VIDEO_EVENT and e.parent_ref == "timeline" and e.asset_ref for e in events
    )
    assert {e.metadata["event_type"] for e in events} >= {"ignition", "shutdown", "steady_plume"}
    assert {a.kind for a in doc.assets} == {AssetKind.VIDEO_FRAME}
    assert sorted(a.t_ms for a in doc.assets) == [2500, 3000, 3500, 5500, 8000]
    (call,) = vision.calls
    assert [round(t, 1) for t, _ in call[1]["keyframes"]] == [2.5, 3.0, 3.5, 5.5, 8.0]
    assert doc.flags == []


@needs_ffmpeg
def test_a_clip_without_ignition_is_flagged_soft(tmp_path, fake_vision, memory_store):
    data = clip(tmp_path, [("gray", 4)])
    doc = process_video(
        data,
        blob_sha256=SHA,
        file_name="idle.mp4",
        folder=TEST_CELL,
        vision=fake_vision(),
        put_asset=memory_store("s3://dcl-assets/"),
        cloud_allowed=False,
    )
    assert [(f.flag_type, f.severity) for f in doc.flags] == [(FlagType.CONFLICT, FlagSeverity.SOFT)]
    evidence = doc.flags[0].evidence
    assert (evidence.relation, evidence.a.value) == ("check_failed", "no ignition found")
    assert doc.document.catalog["t0_ignition_video_ms"] is None


@needs_ffmpeg
def test_undecodable_bytes_are_a_hard_parse_failure(fake_vision, memory_store):
    doc = process_video(
        b"\x00" * 64,
        blob_sha256=SHA,
        file_name="broken.mp4",
        folder=TEST_CELL,
        vision=fake_vision(),
        put_asset=memory_store("s3://dcl-assets/"),
    )
    assert [(f.flag_type, f.severity) for f in doc.flags] == [(FlagType.PARSE_FAILURE, FlagSeverity.HARD)]


def speech(duration_s: float, *, pause_every_s: float = 75.0) -> list[Word]:
    """One word per 0.5 s, with a 3 s pause every `pause_every_s` seconds."""
    words, t, i = [], 0.0, 0
    while t < duration_s:
        if t and (t % pause_every_s) < 0.5:
            t += 3.0
        words.append(Word(t, t + 0.4, f"w{i}"))
        t += 0.5
        i += 1
    return words


def test_windows_are_60_to_120_seconds_and_split_at_pauses_and_slides():
    words = speech(900)
    result = windows(words, slide_changes_ms=[440_000])
    lengths = [w[-1].end_s - w[0].start_s for w in result]
    assert all(55 <= length <= 121 for length in lengths)
    assert sum(len(w) for w in result) == len(words)
    assert any(abs(w[0].start_s - 440.0) < 1.0 for w in result[1:])  # a window starts at the slide change


def test_parts_of_long_recordings_keep_every_word_once():
    full = speech(4000)

    def transcribe(audio, start_s, end_s):
        return [w for w in full if start_s <= w.start_s < end_s]

    words = transcribe_parts(Path("audio.wav"), 4000.0, transcribe)
    assert [w.text for w in words] == [w.text for w in full]


@needs_ffmpeg
def test_workshop_recording_becomes_sections_and_windows(tmp_path, fake_vision, memory_store):
    data = clip(tmp_path, [("blue", 700)], audio=True, fps=1)
    full = speech(700)

    def transcribe(audio, start_s, end_s):
        return [w for w in full if start_s <= w.start_s < end_s]

    doc = process_video(
        data,
        blob_sha256=SHA,
        file_name="design_review.mp4",
        folder=WORKSHOP,
        vision=fake_vision(),
        put_asset=memory_store("s3://dcl-assets/"),
        transcribe=transcribe,
        cloud_allowed=False,
    )
    assert doc.document.doc_kind is DocKind.VIDEO_TRANSCRIPT
    parents = [n for n in doc.nodes if n.node_type is NodeType.PARENT]
    windows_ = [n for n in doc.nodes if n.node_type is NodeType.TRANSCRIPT_WINDOW]
    assert [p.ref for p in parents] == ["section0", "section1"]
    assert all(
        w.parent_ref in {"section0", "section1"} and w.metadata["deep_link"].startswith("#t=")
        for w in windows_
    )
    assert " ".join(w.content for w in windows_).split() == [w.text for w in full]
