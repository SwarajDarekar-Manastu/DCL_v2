"""Throughput of the local models on this machine's GPU; the numbers go into the embedding-service map.

From the repository root: .venv/bin/python -m backend.tests.unit.llm_engine.local_models.measure_throughput
"""

import io
import statistics
import time

import torch
from PIL import Image

from backend.llm_engine.local_models import EmbedKind, count_tokens, load_models

CHILD = (
    "During hot fire 3 of Test Plan 37 the chamber pressure PT-101 rose to 12.4 bar(a) within 40 ms of valve "
    "opening, then settled at a steady-state mean of 11.8 bar(a) while the catalyst bed thermocouple TC-3 "
    "climbed past 600 °C. The injector INJ-14 showed no visible streaking after the run. "
)


def child_text(i: int, target_tokens: int = 325) -> str:
    """A child passage of about target_tokens EmbeddingGemma tokens (children are 250-400, file 04 §4.1)."""
    words = (CHILD * 6).split()
    text = f"[{i}] " + " ".join(words)
    while count_tokens([text])[0] > target_tokens:
        words = words[:-5]
        text = f"[{i}] " + " ".join(words)
    return text


def timed(fn, repeats: int) -> list[float]:
    out = []
    for _ in range(repeats):
        torch.cuda.synchronize()
        started = time.perf_counter()
        fn()
        torch.cuda.synchronize()
        out.append(time.perf_counter() - started)
    return out


def main() -> None:
    models = load_models(device="cuda", dtype="bfloat16")
    texts = [child_text(i) for i in range(512)]
    tokens = statistics.mean(count_tokens(texts[:32]))
    titles = ["Test Report 37 › 3 Hot Fire Results › 3.2 Chamber Pressure"] * len(texts)
    models.embed_texts(texts[:64], EmbedKind.DOCUMENT, titles[:64])
    text_runs = timed(lambda: models.embed_texts(texts, EmbedKind.DOCUMENT, titles), 3)

    buffer = io.BytesIO()
    Image.new("RGB", (1600, 1200), (120, 90, 60)).save(buffer, format="JPEG")
    images = [buffer.getvalue()] * 64
    models.embed_images(images[:8])
    image_runs = timed(lambda: models.embed_images(images), 3)

    query_runs = timed(
        lambda: models.embed_texts(["TP37 chamber pressure steady state"], EmbedKind.QUERY), 20
    )

    rerank_runs = {}
    for size in (325, 400):
        passages = [child_text(i, size) for i in range(50)]
        models.rerank("steady-state chamber pressure TP37", passages)
        rerank_runs[size] = timed(
            lambda p=passages: models.rerank("steady-state chamber pressure TP37", p), 20
        )

    print(f"GPU: {torch.cuda.get_device_name(0)}, torch {torch.__version__}, dtype bfloat16")
    print(f"peak GPU memory allocated: {torch.cuda.max_memory_allocated() / 2**20:.0f} MiB")
    print(
        f"text: {len(texts)} children of ~{tokens:.0f} tokens -> {len(texts) / min(text_runs):.0f} chunks/s"
    )
    print(f"images: {len(images)} 1600x1200 JPEG -> {len(images) / min(image_runs):.1f} images/s")
    print(f"single query embed: p50 {statistics.median(query_runs) * 1000:.1f} ms")
    for size, runs in rerank_runs.items():
        p95 = sorted(runs)[int(0.95 * len(runs)) - 1]
        p50 = statistics.median(runs)
        print(f"rerank 50 pairs of ~{size} tokens: p50 {p50 * 1000:.0f} ms, p95 {p95 * 1000:.0f} ms")
    backfill_min = 250_000 / (len(texts) / min(text_runs)) / 60
    print(f"estimated 250k-chunk backfill: {backfill_min:.0f} min")


if __name__ == "__main__":
    main()
