"""Real EmbeddingGemma 2 and bge-reranker-v2-m3 on the GPU. Skipped where no CUDA device is visible."""

import io
import math
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

torch = pytest.importorskip("torch")
NEEDED_GPU_BYTES = 3 * 2**30


def _gpu_free_bytes() -> int:
    return torch.cuda.mem_get_info()[0] if torch.cuda.is_available() else 0


pytestmark = pytest.mark.skipif(
    _gpu_free_bytes() < NEEDED_GPU_BYTES, reason="needs a CUDA GPU with 3 GiB free (the card is shared)"
)

from backend.api import models as models_router  # noqa: E402
from backend.llm_engine import local_models  # noqa: E402
from backend.llm_engine.local_models import EmbedKind, ModelsClient  # noqa: E402

RERANK_BUDGET_S = 0.4


@pytest.fixture(scope="module")
def models():
    return local_models.load_models(device="cuda", dtype="bfloat16")


def norm(vector):
    return math.sqrt(math.fsum(x * x for x in vector))


def dot(a, b):
    return math.fsum(x * y for x, y in zip(a, b, strict=True))


def test_text_vectors_are_768_d_unit_and_rank_the_relevant_passage_first(models):
    docs = models.embed_texts(
        [
            "The chamber pressure rose to 12.4 bar during the hot fire.",
            "Der Kühlkanal wurde aus C-103 gefertigt.",
        ],
        EmbedKind.DOCUMENT,
        ["Test Report 37 › 3.2 Chamber Pressure", None],
    )
    (query,) = models.embed_texts(["TP37 chamber pressure"], EmbedKind.QUERY)
    assert [len(v) for v in docs + [query]] == [768, 768, 768]
    assert all(math.isclose(norm(v), 1.0, rel_tol=1e-6) for v in docs + [query])
    assert dot(query, docs[0]) > dot(query, docs[1])


def test_image_vectors_are_768_d_unit_in_the_same_space(models):
    buffer = io.BytesIO()
    Image.new("RGB", (640, 480), (220, 40, 30)).save(buffer, format="JPEG")
    (vector,) = models.embed_images([buffer.getvalue()])
    assert len(vector) == 768
    assert math.isclose(norm(vector), 1.0, rel_tol=1e-6)


def test_loaded_weights_are_bfloat16_never_float16(models):
    dtypes = {p.dtype for p in models.embedder.parameters()} | {
        p.dtype for p in models.reranker.model.parameters()
    }
    assert dtypes == {torch.bfloat16}


def test_reranker_scores_50_pairs_within_budget_and_ranks_the_answer_first(models):
    query = "What was the steady-state chamber pressure in TP07 run T04?"
    filler = "The heater coil was inspected and the wiring harness was re-routed along the frame. " * 12
    passages = [filler] * 49 + [
        "TP07 run T04 reached a steady-state chamber pressure of 12.4 bar(a). " + filler
    ]
    models.rerank(query, passages)
    started = time.perf_counter()
    result = models.rerank(query, passages)
    elapsed = time.perf_counter() - started
    assert result.order[0] == 49
    assert elapsed < RERANK_BUDGET_S, f"50 pairs took {elapsed:.3f} s"


def test_router_serves_the_real_models():
    app = FastAPI()
    app.include_router(models_router.router)
    client = ModelsClient(http=TestClient(app))
    health = client.health()
    assert health["device"] == "cuda"
    assert health["dtype"] == "bfloat16"
    assert len(client.embed_queries(["INJ-14 post-test photos"])[0]) == 768
