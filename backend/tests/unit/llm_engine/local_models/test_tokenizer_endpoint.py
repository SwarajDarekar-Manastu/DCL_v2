"""`/tokenize/count` with the real EmbeddingGemma tokenizer; skips without transformers or its files."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

pytest.importorskip("transformers", reason="the models dependency group is not installed")

from backend.api import models as models_router  # noqa: E402
from backend.llm_engine import local_models  # noqa: E402


@pytest.fixture
def http():
    try:
        local_models.embedding_tokenizer()
    except OSError as exc:
        pytest.skip(f"EmbeddingGemma tokenizer files are not available: {exc}")
    app = FastAPI()
    app.include_router(models_router.router)
    app.dependency_overrides[models_router.models_dependency] = lambda: pytest.fail("weights loaded")
    return TestClient(app)


def test_counts_match_the_tokenizer_the_chunker_uses(http):
    texts = ["Chamber pressure reached 12.4 bar(a) in TP07 T04.", "", "Brennkammerdruck " * 50]
    body = http.post("/tokenize/count", json={"texts": texts}).json()
    assert body["counts"] == local_models.count_tokens(texts)
    assert body["counts"][1] == 0 and body["counts"][2] > body["counts"][0] > 5
