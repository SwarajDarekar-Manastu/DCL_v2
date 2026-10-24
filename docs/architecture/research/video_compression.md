# Video compression for the DCL pipeline: research notes (2026-10-23)

> Chosen settings for the stored working copy (Lead, 2026-10-24): H.264 High / MP4, long side <= 1280 px, fps <= 30, CRF 26, preset medium, `-threads 2`, `rc-lookahead=20`, AAC mono 64 kbit/s, `+faststart`; HDR (HLG, PQ) tone-mapped to BT.709 SDR; no re-encode when the source is H.264, <= 1280 px and < 2 Mbit/s, or when the copy is not at least 10 % smaller. One profile for every video because the meeting/test-cell decision comes after the speech check. Implemented in `backend/routes/f_video.py` (`compress`).

Legend: [DOC] primary documentation read this session. [MEAS] measured here on a 20-core Ubuntu box with
FFmpeg 6.1.1 (libx264, libx265, libsvtav1, libvpx-vp9, libzimg present). [FORUM] forum or blog, anecdotal.
[UNVERIFIED] recalled or inferred, not confirmed. The FFmpeg wiki (trac.ffmpeg.org) blocked my fetcher, so
claims about the wiki are marked [UNVERIFIED] and its URLs are listed for you to open.

## Bottom line

- Store one derived copy: MP4, H.264 High profile, yuv420p, AAC mono, `+faststart`. Keep the original untouched.
- Do not use HEVC or AV1 for the stored copy. H.264 plays everywhere, encodes fastest and uses the least RAM.
- Cap the long side at 1280 px. Cap fps at 30 for test-cell clips and 10 for meetings and screen recordings.
- Use CRF 26 (test-cell) and CRF 30 (meetings), preset `medium`, `-threads 2`, `rc-lookahead=20`.
- Do not transcode what is already small. A 1.3 Mbps phone clip barely shrank (see section 3).
- Use plain `subprocess` calling the ffmpeg and ffprobe binaries you already have. Do not add a wrapper library.
- Run the pipeline's analyses (brightness, slide frames, Whisper audio) off the compressed copy. Whisper and
  Gemini both downscale anyway, so the compressed copy loses nothing they could use.

## 1. Container and codec

| | H.264 / MP4 | H.265 / HEVC / MP4 | AV1 (MP4 or WebM) | VP9 / WebM |
|---|---|---|---|---|
| Chrome | all versions | 107+, hardware-dependent | 70+ | all |
| Firefox | all (uses OS decoders) | Win 134+, macOS 136+, Linux 137+ (system ffmpeg), Android hw only | 67+ | all |
| Safari | all | yes | only M3+ Macs, iPhone 15 Pro and later | all (no alpha) |
| Encode CPU, 10 s 1280x720 clip, 2 threads [MEAS] | 3.3 s wall, 321 MB RSS | 6.4 s, 352 MB | SVT-AV1 preset 8: 6.0 s, 539 MB; preset 6: 19.6 s, 593 MB | 13.5 s, 278 MB |
| Decode, same clip, 2 threads [MEAS] | 0.28 s | 0.40 s | 0.36 s (dav1d) | 0.52 s |

Browser table: [DOC] MDN video codec guide, https://developer.mozilla.org/en-US/docs/Web/Media/Guides/Formats/Video_codecs.
MDN's own advice: "AVC in MP4 as the broadest fallback"; avoid HEVC for general web delivery because of
platform-dependent support and licensing. MDN's two HEVC tables disagree on version numbers, so verify before relying on them.

- Decode is fast for every codec (about 20-35x realtime with 2 threads on this clip), so frame sampling
  speed does not decide the codec. Encode cost and compatibility do.
- File size: I did not get a matched-quality comparison. My runs used different CRF scales, so their sizes
  (x264 2.3 MB, x265 2.0 MB, SVT-AV1 2.8 MB) are not comparable. Published claims of 30-50% savings for
  HEVC/AV1 over x264 are [UNVERIFIED]; a Doom9 poster notes x264 keeps slightly more fine detail at high
  quality (https://forum.doom9.org/showthread.php?p=1694075 [FORUM]). For 10-minute meeting clips the
  absolute saving is a few MB; it does not justify losing Firefox and older Safari users.
- Cost of a slower preset is steep: Jan Ozer's VMAF tests found x265 `slow` took over twice the encode time of
  `medium` for 0.87% better quality (via https://ottverse.com/choosing-an-x265-preset-an-roi-analysis/ [FORUM]).
- iPhone clips are often 10-bit HLG HEVC (Dolby Vision profile 8). Convert them to 8-bit SDR H.264. See the
  HDR note in section 3. Source: https://dev.to/masonwritescode/ffmpeg-hdr-to-sdr-tone-mapping-that-doesnt-look-washed-out-2026-24ie [FORUM].
- Later option: keep an AV1 or HEVC derivative only if storage cost becomes real. Not recommended now.

## 2. How far quality can drop

### 2a. Whisper / faster-whisper
- [DOC/source] openai/whisper `load_audio` runs `ffmpeg -nostdin -threads 0 -i FILE -f s16le -ac 1 -acodec pcm_s16le -ar 16000 -`,
  with SAMPLE_RATE 16000 and 30 s chunks: https://raw.githubusercontent.com/openai/whisper/main/whisper/audio.py
- [DOC/source] faster-whisper `decode_audio` uses PyAV, an `AudioResampler` to s16, mono, 16 kHz, and holds the whole
  decoded audio in memory (a `BytesIO`); it calls `gc.collect()` to work around resampler leaks (issue 390):
  https://raw.githubusercontent.com/SYSTRAN/faster-whisper/master/faster_whisper/audio.py
  Consequence: 16 kHz mono is all Whisper ever sees, so keeping 44.1/48 kHz or stereo only costs size.
  A 1-hour 16 kHz s16 mono buffer is about 115 MB (3600 x 16000 x 2), plus a float32 copy of about 230 MB.
- Minimum bitrate: I found no controlled WER-vs-bitrate study for Whisper. Evidence is weak:
  - A gist recommends mono, 16 kHz, MP3 or AAC at 32-64 kbps and says accuracy holds to 32 kbps at 12 kHz. It
    cites no data and says it was generated by an AI: https://gist.github.com/danielrosehill/06fb17e7462980f99efa9fdab2335a14 [FORUM].
  - One OpenAI forum post saw no loss re-encoding a clip from 64 kbps stereo MP3 to 12 kbps mono Opus (single clip):
    https://community.openai.com/t/send-an-hours-worth-of-audio-through-whisper-using-node-js/957808/5 [FORUM].
  - A Google ASR paper (not Whisper, codecs simulated in training) shows MP3 at 23 kbps degrading baseline WER
    (13.6% vs 10.5% clean) while AAC 64 kbps stayed near clean (10.6%): https://arxiv.org/pdf/1808.05312.
- Recommendation: AAC-LC mono at 48 kbps (16 kHz) or 64 kbps (48 kHz). Both sit well above the evidence floor.
  [UNVERIFIED] Run the 20-minute check in section 6 before going lower, because room echo and noisy test cells
  are worse than the clean speech in those studies.
- Practical point: for the audio the pipeline transcribes, extract from the compressed copy at 16 kHz mono
  (`-ac 1 -ar 16000`). Only AAC loss at that bitrate affects it.

### 2b. Slide / scene-change detection
- My synthetic 1080p slide clip with hard cuts every 10 s [MEAS]: ffmpeg `select='gt(scene,0.02)'` after `fps=2`
  found all 5 cuts at identical timestamps for the source and for every variant: 1920 wide CRF 28; 1280 wide 10 fps
  CRF 28; 1280 wide 5 fps CRF 30; 960 wide 2 fps CRF 32. This only proves hard cuts survive; it does not test
  soft transitions, animations or small-text legibility. [UNVERIFIED] for real recordings.
- Lowest safe fps for slides: your detector samples at 2 fps already. Anything at or above about 5 fps is enough
  to see a slide appear. Use 10 fps to leave margin for cursor and animation changes.
- Text legibility is the real limit, not scene detection. Slide frames are reread by Gemini after extraction at
  768 px width, so 1280 wide source is already above what is sent. Below about 960 wide, 28 px body text blurs.

### 2c. Brightness-based ignition detection
- My synthetic test [MEAS]: 1280x720 dark scene, a 67 ms flash (2 source frames) and a 133 ms flash (4 frames), then
  a luminance ramp (plume). Measured mean luma on 32x24 gray thumbnails (`scale=32:24:flags=area,format=gray`, signalstats YAVG):
  - Luma fidelity: CRF 23 and CRF 28 at 30 fps moved steady-state thumbnail luma by at most 0.27 and 0.71 of 255.
    CRF 32 at 960 wide, 15 fps moved it by 1.18. Ramp onset time shifted by at most one frame.
  - Flash survival (frames whose thumbnail luma was above 100):

    | variant | 67 ms flash | 133 ms flash |
    |---|---|---|
    | 30 fps | 2 frames | 4 |
    | 15 fps | 1 | 2 |
    | 10 fps | 1 | 1 |
    | 5 fps | 0 (lost) | 1 |

  - The `fps` filter picks the nearest source frame per output slot, so a flash shorter than 1/fps can vanish
    (5 fps lost the 67 ms flash). 10 fps kept both.
- Your own 2 fps sampling is the bigger limit: a sub-500 ms flash is only caught if a sample lands on it. That
  depends on the sampler, not on compression. If you must catch very short transients, sample the compressed copy
  at 10 fps or denser instead of 2.
- Recommendation: keep test-cell clips at source fps capped at 30 (do not go below 15), and CRF at or below 28.
  Lowering fps saves little on short clips anyway.
- Caveat: H.264 CRF does not preserve absolute luma exactly. Use relative thresholds (frame vs baseline), as you do.
- HDR phone clips: naive 8-bit conversion keeps pixel values but leaves an HLG tag (my test: mean luma 128.05
  unchanged). Tonemapping to SDR changed it to 113.8. Pick one pipeline and use it for all clips so thresholds compare.

### 2d. Gemini video understanding
- [DOC] https://ai.google.dev/gemini-api/docs/video-understanding : default sampling is 1 fps ("Fast action may lose
  detail at this rate"); audio is processed at 1 Kbps mono; custom `fps` and `start_offset` / `end_offset` go in the
  `processing` object (static mode; allowed range not stated, so test it); tokens: low media resolution about 66
  tokens per frame (about 100 per second with audio), otherwise about 258 per frame (about 300 per second); audio
  32 tokens per second; File API for files over 100 MB or over 10 minutes; formats MP4, MOV, WebM and others.
- [DOC] https://ai.google.dev/gemini-api/docs/media-resolution : for Gemini 3 and 4 video, default / low / medium =
  70 tokens per frame, high = 280, ultra_high not available for video. Pixel dimensions are not published.
  Google gives no pixel figure for "effective resolution". Treat a frame as roughly a 384-768 px tile [UNVERIFIED].
- A staff-style forum reply says the 70-token cap forces downsampling of 1080p input and that pre-resizing to
  360p-480p saves bandwidth, not tokens: https://discuss.ai.google.dev/t/best-practices-for-video-pre-processing-resolution-with-media-resolution-parameter-in-gemini-3-0/109808 [FORUM].
- Image path (your keyframes): images up to 384 px per side cost 258 tokens; larger ones are tiled in 768x768 tiles
  at 258 tokens each: https://ai.google.dev/gemini-api/docs/image-understanding . So a 768 px wide JPEG keyframe is
  one tile. Sending wider than 768 px mostly adds tiles, not detail you need.
- Implications: (1) 1280 wide is more than Gemini uses for a video frame. (2) Default 1 fps can miss ignition
  flashes, so set `fps` to 2-5 for the 2-minute clips (cost 70 x 5 x 120 = 42k tokens at the 70-token setting).
  (3) For slide text use the keyframe/image path, or `high` (280 tokens per frame), not `low`.

## 3. Concrete FFmpeg commands

Common filter: long side at most 1280, even dimensions, 8-bit 4:2:0. ffmpeg autorotates phone clips before filters.

```
SCALE="scale='if(gt(iw,ih),min(1280,iw),-2)':'if(gt(iw,ih),-2,min(1280,ih))'"
```

Tested in this session: valid on FFmpeg 6.1.1, output is 1280x720 for 1080p landscape, h264 plus aac 48 kHz mono.

### Test-cell clips (keep fps up to 30, CRF 26)
```
ffmpeg -nostdin -hide_banner -v error -y -threads 2 -i IN.mov \
  -map 0:v:0 -map "0:a:0?" -vf "$SCALE,format=yuv420p" \
  -c:v libx264 -preset medium -crf 26 -profile:v high -threads 2 \
  -x264-params rc-lookahead=20 -g 60 \
  -c:a aac -ac 1 -b:a 64k \
  -map_metadata 0 -movflags +faststart OUT.mp4
```
- Add `-fps_mode cfr -r 30` only if the source is variable frame rate above 30 [UNVERIFIED for your clips]. Phone
  clips are VFR; `-vf fps=30` would make it constant. Do not use `-r` below 15.
- Measured [MEAS]: synthetic 20 s 1080p clip with stereo 128k AAC (14.5 MB) became 6.1 MB (-58%), 7.6 s wall,
  346 MB RSS. Ratio depends on source bitrate; real phone video at 15-25 Mbps shrinks 5-10x [UNVERIFIED].
- `-g 60` keeps a keyframe at least every 2 s at 30 fps for scrubbing and sampling.

### Meetings / screen recordings (fps 10, CRF 30)
```
ffmpeg -nostdin -hide_banner -v error -y -threads 2 -i IN.mp4 \
  -map 0:v:0 -map "0:a:0?" -vf "fps=10,$SCALE,format=yuv420p" \
  -c:v libx264 -preset medium -crf 30 -tune stillimage -profile:v high -threads 2 \
  -x264-params rc-lookahead=20 -g 100 \
  -c:a aac -ac 1 -ar 16000 -b:a 48k \
  -map_metadata 0 -movflags +faststart OUT.mp4
```
- `-ar 16000 -b:a 48k` matches Whisper's input. Playback audio will sound narrower (8 kHz band). If humans must
  listen comfortably, use `-ar 48000 -b:a 64k` instead (+16 kbps, about 7 MB per hour).
- `-tune stillimage` suits slides; if screen content has video playback or fast scrolling, drop it [UNVERIFIED].
- Measured [MEAS] on a synthetic static slide clip (60 s, 1080p, CRF 18 source = 279 KB): CRF 28 at 1920 wide 233 KB;
  10 fps 1280 wide 67 KB; 5 fps 43 KB; 2 fps 960 wide 23 KB. The synthetic clip is near-static so these ratios
  overstate real savings; expect 10-30x on real screen recordings with 10 fps, 1280 wide [UNVERIFIED].
- A 1-hour meeting: video about 150-400 MB at source bitrate becomes roughly 30-100 MB; audio 48 kbps = 21.6 MB/hour.

### Do not re-encode small sources
- [MEAS] `refrence.mp4` (720x1280, 1.24 Mbps, 9.4 MB): CRF 26 gave 7.5 MB, CRF 30 gave 5.1 MB, CRF 30 plus fps 15
  gave 4.5 MB. Sources already near 1-2 Mbps shrink little and lose quality.
- Rule: run ffprobe first. If long side <= 1280, video bitrate < 2 Mbps and codec is H.264 in MP4, skip the
  transcode (use `-c copy -movflags +faststart`) and use the original as the working copy. If the output is larger
  than 90% of the source, keep the source.

### HDR phone clips (check ffprobe `color_transfer` for `arib-std-b67` or `smpte2084`)
```
-vf "zscale=t=linear:npl=100,format=gbrpf32le,zscale=p=bt709,tonemap=tonemap=hable:desat=0,zscale=t=bt709:m=bt709:r=tv,format=yuv420p,$SCALE" \
-color_primaries bt709 -color_trc bt709 -colorspace bt709
```
Tested for syntax on a synthetic HLG clip [MEAS]; output tagged bt709 yuv420p. Needs an ffmpeg built with libzimg
(your container's build must include it; check `ffmpeg -filters | grep zscale`). Dolby Vision profile 7 is not fully handled [FORUM].

### Reference docs
- movflags faststart: "Run a second pass moving the index (moov atom) to the beginning of the file"; off by default,
  not valid for fragmented output [DOC]: https://ffmpeg.org/ffmpeg-formats.html . Verified: output box order was ftyp, moov, mdat.
- FFmpeg wiki H.264 guide (CRF 0-51, default 23, `-preset`, `-tune`, `-pix_fmt yuv420p` for compatibility; not fetched
  here, so [UNVERIFIED]): https://trac.ffmpeg.org/wiki/Encode/H.264 . A mailing-list reply confirms that omitting
  `-pix_fmt yuv420p` can yield 4:2:2 that older players reject: https://ffmpeg.org//pipermail/ffmpeg-user/2019-February/043458.html
- AV1 wiki (not fetched): https://trac.ffmpeg.org/wiki/Encode/AV1

## 4. Python tooling (Celery worker, ffmpeg binary already in image)

| Option | State | Notes |
|---|---|---|
| `subprocess` + ffprobe JSON | stdlib | Exact CLI flags above, no new dependency, ffmpeg runs in its own process so a crash or OOM kills the child, not the worker. |
| ffmpeg-python | latest 0.2.0, July 2019 [DOC: https://pypi.org/project/ffmpeg-python/] | Dead for practical purposes; builds a CLI string, adds nothing you need. Not recommended. |
| typed-ffmpeg | 4.6.2, requires Python >=3.10, versioned per FFmpeg release; ships a `typed-ffmpeg-v9` package [DOC: https://pypi.org/pypi/typed-ffmpeg/json] | Active (many 2025-26 releases) but ties your code to a package per FFmpeg major version and adds a graph DSL for flags you can write by hand. Version pairing with your container's ffmpeg is [UNVERIFIED]. |
| PyAV 19.0.2 | Oct 2026, Python >=3.12, wheels bundle their own FFmpeg libraries [DOC: https://pypi.org/project/av/] | Needed only if you decode frames in-process. Bundles a second FFmpeg, so codec and filter behaviour can differ from your binary. Its own docs say PyAV is "more of a hindrance than a help" when the `ffmpeg` command does the job: https://pyav.basswood.io/docs/stable/ . faster-whisper already depends on it for audio decoding. |
| imageio-ffmpeg 0.6.0 | Jan 2025 [DOC: https://pypi.org/project/imageio-ffmpeg/] | Subprocess plus pipes; wheel bundles a roughly 60 MiB ffmpeg unless you set `IMAGEIO_FFMPEG_EXE` or `--no-binary`. Its README recommends PyAV instead: https://github.com/imageio/imageio-ffmpeg |
| MoviePy 2.2.1 | May 2025 [DOC: https://pypi.org/project/moviepy/] | Decodes into numpy arrays; its own page says it is slower than ffmpeg directly. Highest memory use. Not recommended. |

Recommendation: plain `subprocess.run([...], check=True, timeout=...)` with an argument list (no shell), plus
`ffprobe -v error -print_format json -show_format -show_streams`. Reasons: zero added dependencies, the same
binary you test by hand, memory isolated in a child process, easy `timeout=` and `-progress pipe:1` for Celery
task progress. Add `-nostdin` so ffmpeg never waits on the worker's stdin. Keep PyAV only where faster-whisper
already pulls it in; do not use it for transcoding.
Watch-out: PyAV decode loops that do not release frames grow memory. I found no PyAV-specific report; general libav
reports are at https://ffmpeg.org/pipermail/libav-user/ [FORUM].

## 5. Memory of FFmpeg/libx264 on a 4 GiB worker

Measured peak RSS (1080p 20 s source, CRF 28, audio dropped, 20-core host) [MEAS]:

| Setting | Peak RSS | Wall |
|---|---|---|
| medium, `-threads` auto (20 cores) | 1198 MB | 4.5 s |
| veryfast, auto | 926 MB | 2.1 s |
| slow, auto | 1278 MB | 6.1 s |
| slower, auto | 1381 MB | 11.1 s |
| medium, `-threads 1` | 549 MB | 26.9 s |
| medium, `-threads 2` | 601 MB | 13.7 s |
| medium, `-threads 2`, rc-lookahead 10 | 405 MB | 12.6 s |
| slow, threads 2 | 678 MB | 20.4 s |
| slower, threads 2 | 776 MB | 37.2 s |
| veryslow, threads 2 | 993 MB | 66.3 s |

With the real command (decode 1080p, scale to 1280, encode) [MEAS]: veryfast 193 MB, medium 288 MB, medium with
lookahead 20 about 225 MB, slow 324 MB, all at `-threads 2`.
4K HEVC 60 fps phone-style input to 1280 [MEAS]: 978 MB with default threads, 380 MB with `-threads 2` on both
decoder and encoder.

- The biggest lever is threads. Default x264 threads scale with core count, and I measured about 2x RAM at default
  versus 2 threads. A container CPU quota does not necessarily lower the thread count the encoder picks, because
  `nproc` can still report host cores [UNVERIFIED for your Docker setup]. Always pass `-threads N` explicitly, before
  `-i` for the decoder and after it for the encoder.
- Second lever: `rc-lookahead`. An x264 developer says it "tends to use quite a lot of memory"
  (https://mailman.videolan.org/pipermail/x264-devel/2016-March/011581.html [FORUM]); a Doom9 user saw about 4 GB at
  1080p with lookahead 175 on veryslow (https://forum.doom9.org/archive/index.php/t-163751.html [FORUM]). Presets
  ship with lookahead 10-60 frames (veryslow has 60); `-x264-params rc-lookahead=20` is a safe cap.
  `-tune zerolatency` sets lookahead to 0 but disables B-frames and mb-tree, which costs compression. Do not use it.
- Preset choice is a smaller lever on memory but a big one on time: veryslow is 5x slower than medium for
  almost no size change on this clip. Use `medium` (or `veryfast` if throughput matters more than size).
- Input resolution: scaling to 1280 before the encoder shrinks encoder buffers; decoder frame threads on 4K HEVC
  still cost a few hundred MB, so cap decoder threads.
- Concurrency: set Celery `--concurrency` so that (concurrent ffmpeg jobs) x (about 0.4 GB) plus the Whisper
  `medium` int8 process (roughly 1.5-2 GB resident [UNVERIFIED]) stays under 4 GiB. Prefer one ffmpeg job per
  worker process. Run Whisper and transcoding in separate queues.
- Enforce a ceiling: `timeout=` on subprocess, plus the container cgroup limit; ffmpeg runs as a child, so the OOM
  killer takes the child first in most cases [UNVERIFIED].

## 6. Checks to run before locking settings (cannot be done from the web)
1. Take 3 real meeting recordings with speech. Encode audio at 32 / 48 / 64 kbps AAC mono 16 kHz and the original.
   Transcribe with faster-whisper medium int8 and compare WER with jiwer on a hand-corrected reference. The 20 minutes
   of audio total are enough to see a 1-2 point difference.
2. Take 3 real test-cell clips. Encode with the command above at CRF 26 and 30, fps 30 and 15, and compare the
   brightness series against the source at your 2 fps sampler. Confirm ignition and shutdown timestamps match within
   one sample.
3. Send the same 1-minute clip to Gemini at fps 1, 2 and 5 with media_resolution low and high; compare event timelines
   and token counts reported in `usage_metadata`.
4. Run `ffmpeg -filters | grep zscale` and `ffmpeg -encoders | grep libx264` in the production image.

## Sources
- https://ai.google.dev/gemini-api/docs/video-understanding
- https://ai.google.dev/gemini-api/docs/media-resolution
- https://ai.google.dev/gemini-api/docs/image-understanding
- https://discuss.ai.google.dev/t/best-practices-for-video-pre-processing-resolution-with-media-resolution-parameter-in-gemini-3-0/109808
- https://developer.mozilla.org/en-US/docs/Web/Media/Guides/Formats/Video_codecs
- https://ffmpeg.org/ffmpeg-formats.html
- https://raw.githubusercontent.com/openai/whisper/main/whisper/audio.py
- https://raw.githubusercontent.com/SYSTRAN/faster-whisper/master/faster_whisper/audio.py
- https://arxiv.org/pdf/1808.05312 ; https://gist.github.com/danielrosehill/06fb17e7462980f99efa9fdab2335a14
- https://mailman.videolan.org/pipermail/x264-devel/2016-March/011581.html ; https://forum.doom9.org/archive/index.php/t-163751.html
- https://pypi.org/project/ffmpeg-python/ ; https://pypi.org/pypi/typed-ffmpeg/json ; https://pypi.org/project/av/
- https://pypi.org/project/imageio-ffmpeg/ ; https://github.com/imageio/imageio-ffmpeg ; https://pypi.org/project/moviepy/
- https://pyav.basswood.io/docs/stable/
- https://dev.to/masonwritescode/ffmpeg-hdr-to-sdr-tone-mapping-that-doesnt-look-washed-out-2026-24ie
- https://ottverse.com/choosing-an-x265-preset-an-roi-analysis/
- Not fetched (bot block): https://trac.ffmpeg.org/wiki/Encode/H.264 , https://trac.ffmpeg.org/wiki/Encode/AV1
- Benchmarks were run in a scratch folder during the research session (not kept in the repository).
