"""Route F — test-cell and workshop videos (file 03 §10): one video → `ProcessedDocument`.

Triage with ffprobe (duration, audio, frame rate) and a quick speech check on the first 60 s decides the
sub-route; a folder hint (`Test Plan`, `Run`, `hot fire`) favours the test-cell route for short clips.

F.2 test-cell (short, usually no speech): luminance sampled at 2 fps; ignition = first sustained jump of the
mean luminance, shutdown = the last sustained drop; keyframes at ignition −0.5 s, ignition, +0.5 s, the
steady midpoint and shutdown, plus anomaly spikes; `video_timeline` reads them (the gateway takes images,
not video); audio RMS spikes become acoustic events without interpretation. One timeline node (kept whole
as the parent) and one `video_event` per event with its keyframe asset; `documents.catalog` holds
`t0_ignition_video_ms` and its confidence for the clock alignment of file 03 §C.6.

F.1 workshop (speech): 16 kHz mono audio, transcribed with word timestamps (faster-whisper large-v3 by
default, injectable); recordings above 30 minutes go in 30-minute parts with 30 s overlap, words of the
overlap kept once; windows of 60–120 s split at pauses above 2 s and at slide changes (FFmpeg scene
detection); 10-minute parent sections kept whole with `transcript_window` children; slide frames are assets
and, when cloud processing is allowed, described by `describe_slide`.
"""

import json
import math
import subprocess
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from backend.dispatcher.contract import (
    DocumentFields,
    Flag,
    FlagAnchor,
    LowConfidenceEvidence,
    ParseFailureEvidence,
    ProcessedAsset,
    ProcessedDocument,
    ProcessedNode,
)
from backend.dispatcher.folder_context import FolderContext
from backend.llm_engine.gemini_types import Image
from backend.postgres.enums import AssetKind, DocKind, FlagSeverity, FlagType, NodeSource, NodeType, Route
from backend.routes.a1_office.assets import image_fields

PARSER_VERSION = 1
SAMPLE_FPS = 2
SPEECH_PROBE_S = 60
SPEECH_SHARE_WORKSHOP = 0.3
IGNITION_JUMP = 40.0  # mean-luminance step (0–255) that counts as ignition
SUSTAIN_SAMPLES = 2
WINDOW_MIN_S, WINDOW_MAX_S = 60.0, 120.0
PAUSE_S = 2.0
SECTION_S = 600.0
PART_S, PART_OVERLAP_S = 1800.0, 30.0
SCENE_THRESHOLD = 0.3
RMS_SPIKE_FACTOR = 6.0
TEST_CELL_HINTS = ("test plan", "testplan", "run", "hot fire", "hotfire", "firing", "test cell")


class MediaError(RuntimeError):
    pass


def _run(args: list[str], *, binary: bool = False) -> bytes | str:
    completed = subprocess.run(args, capture_output=True, check=False)  # noqa: S603 (fixed argv, no shell)
    if completed.returncode != 0:
        raise MediaError(completed.stderr.decode("utf-8", "replace")[-500:])
    return completed.stdout if binary else completed.stdout.decode("utf-8", "replace")


@dataclass(frozen=True)
class Probe:
    duration_s: float
    has_audio: bool
    width: int | None
    height: int | None
    fps: float | None


def probe(path: Path) -> Probe:
    data = json.loads(
        _run(["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)])
    )
    streams = data.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    if video is None:
        raise MediaError("no video stream")
    rate = video.get("avg_frame_rate") or "0/1"
    num, _, den = rate.partition("/")
    fps = float(num) / float(den) if den and float(den) else None
    return Probe(
        float(data["format"].get("duration", 0.0)),
        any(s.get("codec_type") == "audio" for s in streams),
        video.get("width"),
        video.get("height"),
        fps,
    )


def luminance(path: Path, fps: int = SAMPLE_FPS) -> list[float]:
    """Mean luminance (0–255) of frames sampled at `fps`, on 32×24 grayscale thumbnails."""
    raw = _run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            str(path),
            "-vf",
            f"fps={fps},scale=32:24,format=gray",
            "-f",
            "rawvideo",
            "-",
        ],
        binary=True,
    )
    size = 32 * 24
    return [sum(raw[i : i + size]) / size for i in range(0, len(raw) - size + 1, size)]


def audio_rms(path: Path, window_s: float = 0.1) -> list[float]:
    """RMS per window of the 16 kHz mono track (empty when there is no audio)."""
    try:
        raw = _run(
            ["ffmpeg", "-v", "error", "-i", str(path), "-vn", "-ac", "1", "-ar", "16000", "-f", "s16le", "-"],
            binary=True,
        )
    except MediaError:
        return []
    samples = memoryview(raw).cast("h") if raw else []
    step = int(16000 * window_s)
    out = []
    for start in range(0, len(samples) - step + 1, step):
        chunk = samples[start : start + step]
        out.append(math.sqrt(sum(x * x for x in chunk) / step))
    return out


@dataclass(frozen=True)
class Ignition:
    t_ignition_ms: int | None
    t_shutdown_ms: int | None
    confidence: float
    anomalies_ms: list[int] = field(default_factory=list)


def detect_ignition(series: Sequence[float], fps: int = SAMPLE_FPS) -> Ignition:
    """Ignition = first index where luminance rises by ≥ IGNITION_JUMP and stays up for SUSTAIN_SAMPLES."""
    if len(series) < SUSTAIN_SAMPLES + 1:
        return Ignition(None, None, 0.0)
    baseline = series[0]
    start = None
    for i in range(1, len(series) - SUSTAIN_SAMPLES + 1):
        window = series[i : i + SUSTAIN_SAMPLES]
        if all(v - baseline >= IGNITION_JUMP for v in window):
            start = i
            break
    if start is None:
        return Ignition(None, None, 0.0)
    plateau = series[start]
    stop = None
    for j in range(len(series) - 1, start, -1):
        if plateau - series[j] >= IGNITION_JUMP and plateau - series[j - 1] < IGNITION_JUMP:
            stop = j
            break
    jump = series[start] - baseline
    confidence = max(0.0, min(1.0, jump / (2 * IGNITION_JUMP)))
    steady = series[start:stop] if stop else series[start:]
    mean = sum(steady) / len(steady)
    spread = math.sqrt(sum((v - mean) ** 2 for v in steady) / len(steady)) or 1.0
    anomalies = [int((start + k) * 1000 / fps) for k, v in enumerate(steady) if abs(v - mean) > 3 * spread]
    to_ms = lambda i: int(i * 1000 / fps)  # noqa: E731
    return Ignition(to_ms(start), to_ms(stop) if stop else None, round(confidence, 2), anomalies[:5])


def keyframe_times(ignition: Ignition, duration_s: float) -> list[int]:
    if ignition.t_ignition_ms is None:
        return sorted({0, int(duration_s * 500)})
    t0 = ignition.t_ignition_ms
    end = ignition.t_shutdown_ms or int(duration_s * 1000)
    times = [max(0, t0 - 500), t0, t0 + 500, (t0 + end) // 2]
    if ignition.t_shutdown_ms:
        times.append(ignition.t_shutdown_ms)
    times += ignition.anomalies_ms
    limit = int(duration_s * 1000) - 1
    return sorted({min(t, limit) for t in times})


def frame_at(path: Path, t_ms: int, width: int = 768) -> bytes:
    return _run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-ss",
            f"{t_ms / 1000:.3f}",
            "-i",
            str(path),
            "-frames:v",
            "1",
            "-vf",
            f"scale={width}:-2",
            "-f",
            "image2",
            "-c:v",
            "mjpeg",
            "-",
        ],
        binary=True,
    )


def scene_changes(path: Path, threshold: float = SCENE_THRESHOLD) -> list[int]:
    """Timestamps (ms) of scene changes (slide transitions); FFmpeg's showinfo reports them on stderr."""
    completed = subprocess.run(  # noqa: S603 (fixed argv, no shell)
        [  # noqa: S607 (ffmpeg from the image PATH)
            "ffmpeg",
            "-v",
            "info",
            "-i",
            str(path),
            "-vf",
            f"select='gt(scene,{threshold})',showinfo",
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
        check=False,
    )
    times = []
    for line in completed.stderr.decode("utf-8", "replace").splitlines():
        if "pts_time:" in line:
            value = line.split("pts_time:", 1)[1].split()[0]
            try:
                times.append(int(float(value) * 1000))
            except ValueError:
                continue
    return times


# ---------------------------------------------------------------- workshop transcripts


@dataclass(frozen=True)
class Word:
    start_s: float
    end_s: float
    text: str


Transcriber = Callable[[Path, float, float], list[Word]]
"""`(audio_path, start_s, end_s) -> words` with absolute timestamps."""


def whisper_transcriber(model_size: str = "large-v3") -> Transcriber:
    from faster_whisper import WhisperModel

    model = WhisperModel(model_size, device="cpu", compute_type="int8")

    def transcribe(audio: Path, start_s: float, end_s: float) -> list[Word]:
        segments, _ = model.transcribe(
            str(audio), word_timestamps=True, vad_filter=True, clip_timestamps=[start_s, end_s]
        )
        return [Word(w.start, w.end, w.word.strip()) for s in segments for w in (s.words or [])]

    return transcribe


def transcribe_parts(audio: Path, duration_s: float, transcribe: Transcriber) -> list[Word]:
    """30-minute parts with 30 s overlap; a word is kept from the part whose core contains its start."""
    words: list[Word] = []
    start = 0.0
    while start < duration_s:
        end = min(duration_s, start + PART_S + PART_OVERLAP_S)
        core_end = start + PART_S if end < duration_s else duration_s + 1
        for word in transcribe(audio, start, end):
            if start <= word.start_s < core_end and (not words or word.start_s >= words[-1].start_s):
                if not words or (word.start_s, word.text) != (words[-1].start_s, words[-1].text):
                    words.append(word)
        start += PART_S
    return words


def windows(words: Sequence[Word], slide_changes_ms: Sequence[int] = ()) -> list[list[Word]]:
    """60–120 s windows: a window closes at a pause > 2 s or a slide change once it is 60 s long, and
    always by 120 s."""
    out: list[list[Word]] = []
    current: list[Word] = []
    changes = sorted(t / 1000 for t in slide_changes_ms)
    for word in words:
        if current:
            length = word.start_s - current[0].start_s
            pause = word.start_s - current[-1].end_s
            slide = any(current[-1].end_s <= c <= word.start_s for c in changes)
            if length >= WINDOW_MAX_S or (length >= WINDOW_MIN_S and (pause > PAUSE_S or slide)):
                out.append(current)
                current = []
        current.append(word)
    if current:
        if out and current[-1].end_s - current[0].start_s < WINDOW_MIN_S / 2:
            out[-1].extend(current)
        else:
            out.append(current)
    return out


def _text(words: Sequence[Word]) -> str:
    return " ".join(w.text for w in words).replace(" ,", ",").replace(" .", ".")


def _clock(ms: int) -> str:
    seconds = ms // 1000
    return f"{seconds // 60}m{seconds % 60:02d}s"


# ---------------------------------------------------------------- the route


def _hint_test_cell(folder: FolderContext, file_name: str) -> bool:
    text = " ".join([*folder.breadcrumb, file_name]).lower()
    return any(h in text for h in TEST_CELL_HINTS) or folder.test_plan_id is not None


def _speech_share(words: Sequence[Word], probe_s: float) -> float:
    spoken = sum(max(0.0, min(w.end_s, probe_s) - w.start_s) for w in words if w.start_s < probe_s)
    return spoken / probe_s if probe_s else 0.0


def process_video(
    data: bytes,
    *,
    blob_sha256: str,
    file_name: str,
    folder: FolderContext,
    vision,
    put_asset: Callable[[str, bytes], str],
    transcribe: Transcriber | None = None,
    cloud_allowed: bool = True,
    doc_id: str | None = None,
) -> ProcessedDocument:
    cir_uri = f"s3://dcl-cir/{blob_sha256}/F/v{PARSER_VERSION}/"
    title = Path(file_name).stem.replace("_", " ")
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / f"input{Path(file_name).suffix or '.mp4'}"
        path.write_bytes(data)
        try:
            info = probe(path)
        except (MediaError, KeyError, ValueError) as exc:
            flag = Flag(
                flag_type=FlagType.PARSE_FAILURE,
                severity=FlagSeverity.HARD,
                evidence=ParseFailureEvidence(
                    error=f"undecodable video: {exc}"[:300],
                    magic_bytes_hex=data[:16].hex(),
                    size_bytes=len(data),
                ),
            )
            return ProcessedDocument(
                blob_sha256=blob_sha256,
                route=Route.F,
                parser_version=PARSER_VERSION,
                cir_uri=cir_uri,
                document=DocumentFields(title=title),
                flags=[flag],
            )
        audio = Path(tmp) / "audio.wav"
        words: list[Word] = []
        if info.has_audio and transcribe is not None:
            _run(
                [
                    "ffmpeg",
                    "-v",
                    "error",
                    "-y",
                    "-i",
                    str(path),
                    "-vn",
                    "-ac",
                    "1",
                    "-ar",
                    "16000",
                    str(audio),
                ]
            )
            probe_words = transcribe(audio, 0.0, min(SPEECH_PROBE_S, info.duration_s))
            workshop = (
                _speech_share(probe_words, min(SPEECH_PROBE_S, info.duration_s)) >= SPEECH_SHARE_WORKSHOP
            )
            if workshop and not (_hint_test_cell(folder, file_name) and info.duration_s < 300):
                words = transcribe_parts(audio, info.duration_s, transcribe)
        if words:
            nodes, assets, flags, catalog = _workshop(
                path, info, words, folder, title, blob_sha256, vision, put_asset, cloud_allowed, doc_id
            )
            kind = DocKind.VIDEO_TRANSCRIPT
        else:
            nodes, assets, flags, catalog = _test_cell(
                path, info, folder, title, blob_sha256, vision, put_asset, cloud_allowed, doc_id
            )
            kind = DocKind.VIDEO_TIMELINE
    document = DocumentFields(
        title=title,
        doc_kind=kind,
        source_origin=folder.source_origin,
        trust_tier=folder.trust_tier,
        test_plan_id=folder.test_plan_id,
        test_run_id=folder.test_run_id,
        hardware_item=folder.hardware_item,
        catalog={**catalog, "duration_s": info.duration_s, "has_audio": info.has_audio, "fps": info.fps},
    )
    return ProcessedDocument(
        blob_sha256=blob_sha256,
        route=Route.F,
        parser_version=PARSER_VERSION,
        cir_uri=cir_uri,
        document=document,
        nodes=nodes,
        assets=assets,
        flags=flags,
    )


def _frame_asset(path: Path, t_ms: int, blob_sha256: str, put_asset) -> tuple[ProcessedAsset, bytes]:
    jpeg = frame_at(path, t_ms)
    uri = put_asset(f"frames/{blob_sha256}/{t_ms}.jpg", jpeg)
    size = image_fields(jpeg)
    return ProcessedAsset(
        ref=f"frame:{t_ms}", kind=AssetKind.VIDEO_FRAME, minio_uri=uri, t_ms=t_ms, **size
    ), jpeg


def _test_cell(path, info, folder, title, blob_sha256, vision, put_asset, cloud_allowed, doc_id):
    ignition = detect_ignition(luminance(path))
    times = keyframe_times(ignition, info.duration_s)
    assets, frames = [], []
    for t_ms in times:
        asset, jpeg = _frame_asset(path, t_ms, blob_sha256, put_asset)
        assets.append(asset)
        frames.append((t_ms, jpeg))
    crumb = " › ".join([*folder.breadcrumb, title])
    events: list[tuple[int, str, str]] = []
    if ignition.t_ignition_ms is not None:
        events.append((ignition.t_ignition_ms, "ignition", "sudden brightness rise (luminance)"))
    if ignition.t_shutdown_ms is not None:
        events.append((ignition.t_shutdown_ms, "shutdown", "brightness drop (luminance)"))
    rms = audio_rms(path) if info.has_audio else []
    if rms:
        median = sorted(rms)[len(rms) // 2] or 1.0
        events += [
            (int(i * 100), "acoustic_event", "loud sound (audio RMS spike)")
            for i, v in enumerate(rms)
            if v > RMS_SPIKE_FACTOR * median
        ][:10]
    anomalies: list[str] = []
    if cloud_allowed and frames:
        timeline = vision.video_timeline(
            [(t / 1000, Image(j, "image/jpeg")) for t, j in frames],
            folder_context=" / ".join([*folder.breadcrumb, path.name]),
            doc_id=doc_id,
            anchor=f"t:{times[0]}:",
        ).reading
        events += [(int(e.t_s * 1000), e.type, e.description) for e in timeline.events]
        anomalies = list(timeline.anomalies)
    events = sorted(dict(((t, kind), (t, kind, text)) for t, kind, text in events).values())
    summary = [f"Video timeline of {title} ({info.duration_s:.1f} s)."]
    if ignition.t_ignition_ms is not None:
        summary.append(
            f"Ignition at {ignition.t_ignition_ms / 1000:.2f} s "
            f"(video clock, confidence {ignition.confidence})."
        )
    summary += [f"{t / 1000:.2f} s: {kind} — {text}" for t, kind, text in events]
    summary += [f"Anomaly: {a}" for a in anomalies]
    end_ms = int(info.duration_s * 1000)
    nodes = [
        ProcessedNode(
            ref="timeline",
            node_type=NodeType.PARENT,
            ordinal=0,
            breadcrumb=crumb,
            content="\n".join(summary),
            t_start_ms=0,
            t_end_ms=end_ms,
            source=NodeSource.VLM if cloud_allowed else NodeSource.STRUCTURED,
        )
    ]
    frame_refs = {a.t_ms: a.ref for a in assets}
    for i, (t_ms, kind, text) in enumerate(events):
        nearest = min(frame_refs, key=lambda f: abs(f - t_ms)) if frame_refs else None
        nodes.append(
            ProcessedNode(
                ref=f"event{i}",
                parent_ref="timeline",
                node_type=NodeType.VIDEO_EVENT,
                ordinal=i + 1,
                breadcrumb=crumb,
                content=f"{t_ms / 1000:.2f} s: {kind} — {text}",
                t_start_ms=t_ms,
                t_end_ms=t_ms,
                source=NodeSource.VLM
                if kind not in ("ignition", "shutdown", "acoustic_event")
                else NodeSource.STRUCTURED,
                asset_ref=frame_refs.get(nearest),
                metadata={"event_type": kind},
            )
        )
    flags = []
    if ignition.t_ignition_ms is None or ignition.confidence < 0.5:
        flags.append(
            Flag(
                flag_type=FlagType.LOW_CONFIDENCE_EXTRACTION,
                severity=FlagSeverity.SOFT,
                anchor=FlagAnchor(channel="video_luminance"),
                evidence=LowConfidenceEvidence(),
            )
        )
    catalog = {
        "t0_ignition_video_ms": ignition.t_ignition_ms,
        "t0_ignition_confidence": ignition.confidence,
        "t_shutdown_video_ms": ignition.t_shutdown_ms,
    }
    return nodes, assets, flags, catalog


def _workshop(path, info, words, folder, title, blob_sha256, vision, put_asset, cloud_allowed, doc_id):
    changes = scene_changes(path)
    crumb = " › ".join([*folder.breadcrumb, title])
    assets, slide_text = [], {}
    for t_ms in changes:
        asset, jpeg = _frame_asset(path, t_ms, blob_sha256, put_asset)
        assets.append(asset)
        if cloud_allowed:
            reading = vision.describe_slide(
                Image(jpeg, "image/jpeg"), slide_text="", context=crumb, doc_id=doc_id, anchor=f"t:{t_ms}:"
            ).reading
            slide_text[t_ms] = reading.summary + (
                f" {reading.diagram_description}" if reading.diagram_description else ""
            )
    nodes: list[ProcessedNode] = []
    sections: dict[int, str] = {}
    for window in windows(words, changes):
        start_ms, end_ms = int(window[0].start_s * 1000), int(window[-1].end_s * 1000)
        section = int(window[0].start_s // SECTION_S)
        if section not in sections:
            ref = f"section{section}"
            sections[section] = ref
            s_start, s_end = (
                int(section * SECTION_S * 1000),
                int(min(info.duration_s, (section + 1) * SECTION_S) * 1000),
            )
            section_words = [w for w in words if s_start <= w.start_s * 1000 < s_end]
            nodes.append(
                ProcessedNode(
                    ref=ref,
                    node_type=NodeType.PARENT,
                    ordinal=len(nodes),
                    breadcrumb=crumb,
                    content=_text(section_words),
                    t_start_ms=s_start,
                    t_end_ms=s_end,
                    source=NodeSource.STRUCTURED,
                )
            )
        slides = [slide_text[t] for t in changes if start_ms <= t <= end_ms and t in slide_text]
        content = _text(window) + ("\nSlides: " + " | ".join(slides) if slides else "")
        nodes.append(
            ProcessedNode(
                ref=f"w{start_ms}",
                parent_ref=sections[section],
                node_type=NodeType.TRANSCRIPT_WINDOW,
                ordinal=len(nodes),
                breadcrumb=crumb,
                content=content,
                t_start_ms=start_ms,
                t_end_ms=end_ms,
                source=NodeSource.STRUCTURED,
                metadata={"deep_link": f"#t={_clock(start_ms)}"},
            )
        )
    return nodes, assets, [], {"slide_changes_ms": changes}
