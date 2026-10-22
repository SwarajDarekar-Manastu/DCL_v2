import base64
import io
import socket
import subprocess
import sys
import time

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from backend.api import models as models_router
from backend.llm_engine.local_models import ModelRequestRejected, ModelsClient, ModelServerUnavailable


@pytest.fixture
def app(make_models):
    app = FastAPI()
    app.include_router(models_router.router)
    app.dependency_overrides[models_router.models_dependency] = lambda: make_models()
    app.dependency_overrides[models_router.tokenizer_dependency] = lambda: whitespace_counts
    return app


def whitespace_counts(texts: list[str]) -> list[int]:
    whitespace_counts.batches.append(len(texts))
    return [len(t.split()) for t in texts]


whitespace_counts.batches = []


@pytest.fixture
def client(app):
    return ModelsClient(http=TestClient(app))


def png_bytes() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (32, 32), (10, 200, 30)).save(buffer, format="PNG")
    return buffer.getvalue()


def test_client_round_trip_for_documents_queries_images_and_rerank(client):
    assert [len(v) for v in client.embed_documents(["a b", "c"], ["T", None])] == [768, 768]
    assert len(client.embed_queries(["q"])[0]) == 768
    assert len(client.embed_images([png_bytes()])[0]) == 768
    result = client.rerank("q", ["aa", "a", "aaaa", "aaa", "aaaaa"])
    assert result.order == [4, 2, 3, 0, 1]
    assert result.margin_1_5 == 4.0
    assert client.health()["embedding_model"] == "embeddinggemma-2@768"


def test_embed_response_names_model_and_dim(app):
    body = TestClient(app).post("/embed/text", json={"kind": "query", "items": [{"text": "x"}]}).json()
    assert body["model"] == "embeddinggemma-2@768"
    assert body["dim"] == 768


def test_too_long_text_is_422_and_client_raises_rejected(client):
    with pytest.raises(ModelRequestRejected, match="8001 tokens"):
        client.embed_documents(["w " * 8001])


@pytest.mark.parametrize(
    ("path", "payload"),
    [
        ("/embed/text", {"kind": "document", "items": []}),
        ("/embed/text", {"kind": "passage", "items": [{"text": "x"}]}),
        ("/embed/text", {"kind": "query", "items": [{"text": "x"}] * 257}),
        ("/embed/image", {"images_b64": ["not base64!"]}),
        ("/embed/image", {"images_b64": [base64.b64encode(b"not an image").decode()]}),
        ("/rerank", {"query": "q", "passages": ["p"] * 101}),
    ],
)
def test_invalid_requests_are_422(app, path, payload):
    assert TestClient(app).post(path, json=payload).status_code == 422


def test_failed_model_load_is_503():
    app = FastAPI()
    app.include_router(models_router.router)

    def broken():
        raise models_router.HTTPException(status_code=503, detail="models failed to load: no GPU")

    app.dependency_overrides[models_router.models_dependency] = broken
    assert TestClient(app).get("/models/health").status_code == 503


def test_server_error_raises_unavailable():
    transport = httpx.MockTransport(lambda request: httpx.Response(503, json={"detail": "loading"}))
    client = ModelsClient(http=httpx.Client(base_url="http://models", transport=transport))
    with pytest.raises(ModelServerUnavailable, match="HTTP 503"):
        client.rerank("q", ["p"])


def test_down_model_role_raises_unavailable_within_the_timeout():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    client = ModelsClient(base_url=f"http://127.0.0.1:{port}", timeout_s=1.0)
    started = time.monotonic()
    with pytest.raises(ModelServerUnavailable, match="unreachable"):
        client.rerank("q", ["p"])
    assert time.monotonic() - started < 2.0


def test_importing_the_router_imports_no_model_library():
    code = (
        "import sys, backend.api.models; print(sorted({'torch', 'sentence_transformers'} & set(sys.modules)))"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True).stdout
    assert out.strip() == "[]"


def test_token_counts_come_back_in_order_and_batched(client):
    whitespace_counts.batches.clear()
    texts = [" ".join(["w"] * (i % 7)) for i in range(1500)]  # 1500 > one request: the client splits
    assert client.count_tokens(texts) == [i % 7 for i in range(1500)]
    assert sum(whitespace_counts.batches) == 1500 and max(whitespace_counts.batches) <= 128


def test_token_count_validates_and_never_loads_the_models(app):
    app.dependency_overrides[models_router.models_dependency] = lambda: pytest.fail("weights loaded")
    http = TestClient(app)
    assert http.post("/tokenize/count", json={"texts": ["a b c", ""]}).json() == {
        "model": "embeddinggemma-2@768",
        "counts": [3, 0],
    }
    assert http.post("/tokenize/count", json={"texts": []}).status_code == 422
    assert http.post("/tokenize/count", json={"texts": ["x"] * 1025}).status_code == 422
