import json
import shutil
import subprocess
from pathlib import Path

import pytest

from backend.dispatcher.folder_context import build_folder_context
from backend.postgres.enums import AssetKind, DocKind, FlagSeverity, FlagType, NodeType
from backend.routes.f_video import (
    Ignition,
    Word,
    audio_slice,
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
    cir = {}
    doc = process_video(
        data,
        blob_sha256=SHA,
        file_name="hotfire_T01.mp4",
        folder=TEST_CELL,
        vision=vision,
        put_asset=store,
        put_cir=lambda key, body: cir.setdefault(key, json.loads(body)) and key,
    )
    assert sorted(cir) == ["events.json", "probe.json", "scenes.json", "transcript.json"]
    assert cir["probe.json"]["has_audio"] is False and cir["transcript.json"] == []
    assert {e["event_type"] for e in cir["events.json"]} >= {"ignition", "shutdown"}
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
    assert call[1]["folder_context"] == "APU / Test Plan 19 / Videos / hotfire_T01.mp4"
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


def big_clip(tmp_path: Path, segments: list[tuple[str, float]]) -> bytes:
    """1920x1080 at 60 fps with heavy noise and an audio tone: a phone-sized source well above 2 Mbit/s."""
    out = tmp_path / "big.mov"
    args = ["ffmpeg", "-v", "error", "-y"]
    for colour, seconds in segments:
        args += ["-f", "lavfi", "-i", f"color=c={colour}:s=1920x1080:d={seconds}:r=60"]
    args += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={sum(s for _, s in segments)}"]
    graph = "".join(f"[{i}]" for i in range(len(segments)))
    graph += f"concat=n={len(segments)}:v=1:a=0,noise=alls=30:allf=t[v]"
    args += ["-filter_complex", graph, "-map", "[v]", "-map", f"{len(segments)}:a", "-shortest"]
    args += ["-c:v", "libx264", "-crf", "12", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(out)]
    subprocess.run(args, check=True)  # noqa: S603
    return out.read_bytes()


@needs_ffmpeg
def test_a_large_clip_is_processed_from_a_smaller_copy_that_the_viewer_plays(
    tmp_path, fake_vision, memory_store
):
    data = big_clip(tmp_path, [("black", 2), ("white", 3), ("black", 2)])
    store = memory_store("s3://dcl-assets/")
    doc = process_video(
        data,
        blob_sha256=SHA,
        file_name="hotfire_T01.mov",
        folder=TEST_CELL,
        vision=fake_vision(video_timeline=TIMELINE),
        put_asset=store,
    )
    copy = doc.document.catalog["working_copy"]
    assert copy["compressed"] is True and copy["bytes"] < 0.9 * copy["source_bytes"] == 0.9 * len(data)
    (proxy,) = [a for a in doc.assets if a.kind is AssetKind.VIDEO_PROXY]
    assert (proxy.ref, proxy.width, proxy.height, proxy.bytes) == ("video:proxy", 1280, 720, copy["bytes"])
    assert doc.document.catalog["fps"] == 30
    assert abs(doc.document.catalog["t0_ignition_video_ms"] - 2000) <= 500  # found on the copy
    assert any(a.kind is AssetKind.VIDEO_FRAME for a in doc.assets)


@needs_ffmpeg
def test_a_small_h264_clip_is_processed_as_it_is(tmp_path, fake_vision, memory_store):
    data = clip(tmp_path, [("black", 3), ("white", 3)])
    doc = process_video(
        data,
        blob_sha256=SHA,
        file_name="hotfire_T01.mp4",
        folder=TEST_CELL,
        vision=fake_vision(video_timeline=TIMELINE),
        put_asset=memory_store("s3://dcl-assets/"),
    )
    assert doc.document.catalog["working_copy"] == {
        "compressed": False,
        "reason": "already small",
        "source_bytes": len(data),
    }
    assert all(a.kind is not AssetKind.VIDEO_PROXY for a in doc.assets)


def test_a_part_reads_only_its_own_samples_of_the_audio(tmp_path):
    import wave

    import numpy as np

    rate, seconds = 16000, 4
    samples = (np.arange(rate * seconds) % 1000).astype("<i2")
    audio = tmp_path / "audio.wav"
    with wave.open(str(audio), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(samples.tobytes())
    part = audio_slice(audio, 1.5, 3.0)
    assert part.dtype == np.float32 and len(part) == int(1.5 * rate)
    assert np.allclose(part * 32768.0, samples[int(1.5 * rate) : 3 * rate])
    assert len(audio_slice(audio, 3.5, 9.0)) == rate // 2  # a part past the end stops at the end


def test_a_recording_continues_from_its_saved_parts_after_a_checkpoint():
    full = speech(1500)
    saved: dict[str, bytes] = {}
    store = type(
        "Store", (), {"get": lambda self, k: saved.get(k), "put": lambda self, k, d: saved.setdefault(k, d)}
    )()
    calls = []

    def transcribe(audio, start_s, end_s):
        calls.append(start_s)
        return [w for w in full if start_s <= w.start_s < end_s]

    first = transcribe_parts(Path("audio.wav"), 1500.0, transcribe, store)
    assert calls == [0.0, 600.0, 1200.0] and len(saved) == 3

    def stopped(audio, start_s, end_s):
        raise AssertionError("a saved part is transcribed again")

    assert transcribe_parts(Path("audio.wav"), 1500.0, stopped, store) == first


@needs_ffmpeg
def test_when_brightness_misses_the_ignition_the_model_finds_it_in_frames_of_the_whole_clip(
    tmp_path, fake_vision, memory_store
):
    data = clip(tmp_path, [("gray", 8)])  # no luminance jump: a small glow the whole-frame mean cannot see
    seen = {"ignition": 3.5, "shutdown": 6.5}
    vision = fake_vision(
        video_timeline=lambda kw: {
            "events": [
                {"t_s": t, "type": kind, "description": "glow at the nozzle"} for kind, t in seen.items()
            ],
            "anomalies": [],
        }
    )
    doc = process_video(
        data,
        blob_sha256=SHA,
        file_name="hotfire_T02.mp4",
        folder=TEST_CELL,
        vision=vision,
        put_asset=memory_store("s3://dcl-assets/"),
    )
    (call,) = vision.calls
    assert len(call[1]["keyframes"]) == 16  # frames across the whole clip, not two
    catalog = doc.document.catalog
    assert (catalog["t0_ignition_video_ms"], catalog["t_shutdown_video_ms"], catalog["t0_source"]) == (
        3500,
        6500,
        "model reading of the frames",
    )
    assert doc.flags == []
    ignition = next(n for n in doc.nodes if n.metadata.get("event_type") == "ignition")
    assert ignition.source == "vlm"  # the model wrote it
