"""EmbeddingGemma 2 and bge-reranker-v2-m3, loaded once per process on the GPU (file 04 §5, file 01 §5.4).

The models role (ROLE=models) loads both through `load_models()` on the first request to
backend/api/models.py; every other process reaches them over HTTP with `ModelsClient`.
Importing this module loads no weights.

Rules from the manual enforced here:
- bfloat16 or float32 only; float16 silently corrupts EmbeddingGemma 2 vectors, so it is refused.
- Document side `title: {title} | text: {text}` (`title: none` without a title); query side
  `task: search result | query: {query}`; images raw, no prefix.
- 768 dimensions, L2-normalized; a non-finite or collapsed vector is an error, never a result.
- An embed_text above 8,000 tokens (or an input above the 8,192-token context) is refused, never truncated.
"""

import io
import math
import threading
from dataclasses import dataclass
from enum import StrEnum
from functools import lru_cache
from typing import Any

import httpx

EMBEDDING_MODEL_ID = "google/embeddinggemma-2"
EMBEDDING_MODEL_TAG = "embeddinggemma-2@768"
EMBEDDING_DIM = 768
EMBEDDING_CONTEXT_TOKENS = 8192
MAX_EMBED_TEXT_TOKENS = 8000
MAX_TOKENIZE_ITEMS = 1024  # per `/tokenize/count` request; ModelsClient.count_tokens splits larger lists
RERANKER_MODEL_ID = "BAAI/bge-reranker-v2-m3"
RERANKER_MAX_LENGTH = 512
QUERY_PREFIX = "task: search result | query: "

TEXT_BATCH_SIZE = 16
IMAGE_BATCH_SIZE = 8
RERANK_BATCH_SIZE = 50
MIN_RAW_NORM = 0.5


class EmbedKind(StrEnum):
    DOCUMENT = "document"
    QUERY = "query"


class ModelDtype(StrEnum):
    BFLOAT16 = "bfloat16"
    FLOAT32 = "float32"


class InputTooLong(ValueError):
    """An input would be truncated by the model; the caller must split it."""


class ModelServerUnavailable(RuntimeError):
    """The models role did not answer; callers degrade (retrieval keeps RRF order, file 07 §12)."""


class ModelRequestRejected(ValueError):
    """The models role refused the request (4xx): a caller bug, not an outage."""


def check_dtype(name: str) -> ModelDtype:
    """Refuse float16 and anything else outside bfloat16/float32; needs no torch."""
    try:
        return ModelDtype(name)
    except ValueError:
        raise ValueError(
            f"dtype {name!r} is not allowed for EmbeddingGemma 2; use bfloat16 or float32 "
            "(float16 overflows its activations and returns NaN or degraded vectors)"
        ) from None


def resolve_dtype(name: str, device: str):
    """The torch dtype for an allowed name; bfloat16 only where the GPU supports it."""
    dtype = check_dtype(name)
    import torch

    if dtype is ModelDtype.BFLOAT16 and device.startswith("cuda") and not torch.cuda.is_bf16_supported():
        raise ValueError("bfloat16 requested but this GPU does not support it; use float32")
    return {ModelDtype.BFLOAT16: torch.bfloat16, ModelDtype.FLOAT32: torch.float32}[dtype]


def _is_cuda_oom(exc: BaseException) -> bool:
    """torch.cuda.OutOfMemoryError, recognized without importing torch (it subclasses RuntimeError)."""
    return type(exc).__name__ == "OutOfMemoryError"


def _release_cuda_cache() -> None:
    try:
        import torch
    except ImportError:
        return
    if torch.cuda.is_available():
        torch.cuda.empty_cache()


def default_device_and_dtype() -> tuple[str, str]:
    import torch

    if torch.cuda.is_available():
        return "cuda", ModelDtype.BFLOAT16 if torch.cuda.is_bf16_supported() else ModelDtype.FLOAT32
    return "cpu", ModelDtype.FLOAT32


def format_document(text: str, title: str | None) -> str:
    title = (title or "").strip() or "none"
    return f"title: {title} | text: {text}"


def format_query(query: str) -> str:
    return f"{QUERY_PREFIX}{query}"


@lru_cache(maxsize=1)
def embedding_tokenizer():
    """EmbeddingGemma 2's own tokenizer, CPU only; the chunker sizes chunks with it (file 04 §4.3)."""
    from transformers import AutoTokenizer

    return AutoTokenizer.from_pretrained(EMBEDDING_MODEL_ID)


def count_tokens(texts: list[str]) -> list[int]:
    encoded = embedding_tokenizer()(texts, add_special_tokens=False)["input_ids"]
    return [len(ids) for ids in encoded]


def unit_vectors(vectors: list[list[float]]) -> list[list[float]]:
    """Refuse wrong-sized or non-finite vectors; re-normalize in float64 (bfloat16 output drifts ~0.5%)."""
    result = []
    for vector in vectors:
        if len(vector) != EMBEDDING_DIM:
            raise RuntimeError(f"embedding has {len(vector)} dimensions, expected {EMBEDDING_DIM}")
        norm = math.sqrt(math.fsum(x * x for x in vector))
        if not math.isfinite(norm) or norm < MIN_RAW_NORM:
            raise RuntimeError(f"embedding is not a finite non-zero vector (norm {norm}); check the dtype")
        result.append([x / norm for x in vector])
    return result


@dataclass(frozen=True)
class RerankResult:
    scores: list[float]
    order: list[int]
    margin_1_5: float | None


def rank_scores(scores: list[float]) -> RerankResult:
    order = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
    margin = scores[order[0]] - scores[order[4]] if len(order) >= 5 else None
    return RerankResult(scores=scores, order=order, margin_1_5=margin)


class LocalModels:
    """Both models on one device. GPU calls are serialized by a lock; FastAPI runs them in its threadpool."""

    def __init__(self, embedder: Any, reranker: Any, device: str, dtype: str, token_counter=count_tokens):
        self.embedder = embedder
        self.reranker = reranker
        self.device = device
        self.dtype = dtype
        self._count_tokens = token_counter
        self._lock = threading.Lock()

    def embed_texts(self, texts: list[str], kind: EmbedKind, titles: list[str | None] | None = None):
        if kind is EmbedKind.DOCUMENT:
            titles = titles or [None] * len(texts)
            inputs = [format_document(t, title) for t, title in zip(texts, titles, strict=True)]
        else:
            inputs = [format_query(t) for t in texts]
        self._refuse_long(texts, inputs)
        return unit_vectors(self._encode(inputs, TEXT_BATCH_SIZE))

    def embed_images(self, images: list[bytes]) -> list[list[float]]:
        from PIL import Image

        decoded = [Image.open(io.BytesIO(raw)).convert("RGB") for raw in images]
        return unit_vectors(self._encode(decoded, IMAGE_BATCH_SIZE))

    def rerank(self, query: str, passages: list[str]) -> RerankResult:
        with self._lock:
            scores = self.reranker.predict(
                [(query, passage) for passage in passages],
                batch_size=RERANK_BATCH_SIZE,
                convert_to_numpy=True,
            )
        return rank_scores([float(s) for s in scores])

    def health(self) -> dict[str, Any]:
        return {
            "embedding_model": EMBEDDING_MODEL_TAG,
            "reranker_model": RERANKER_MODEL_ID,
            "dim": EMBEDDING_DIM,
            "device": self.device,
            "dtype": str(self.dtype),
        }

    def _encode(self, inputs: list, batch_size: int) -> list[list[float]]:
        """Encode under the GPU lock; on CUDA out-of-memory halve the batch (the card is shared, 09 §H12)."""
        with self._lock:
            while True:
                try:
                    vectors = self.embedder.encode(
                        inputs, batch_size=batch_size, normalize_embeddings=True, convert_to_numpy=True
                    )
                    return vectors.tolist()
                except RuntimeError as exc:
                    if not _is_cuda_oom(exc) or batch_size == 1:
                        raise
                    _release_cuda_cache()
                    batch_size //= 2

    def _refuse_long(self, texts: list[str], inputs: list[str]) -> None:
        for i, n in enumerate(self._count_tokens(texts)):
            if n > MAX_EMBED_TEXT_TOKENS:
                raise InputTooLong(
                    f"item {i}: {n} tokens > {MAX_EMBED_TEXT_TOKENS}; split it before embedding"
                )
        for i, n in enumerate(self._count_tokens(inputs)):
            if n + 2 > EMBEDDING_CONTEXT_TOKENS:
                raise InputTooLong(
                    f"item {i}: {n} tokens with prefix exceeds the {EMBEDDING_CONTEXT_TOKENS} context"
                )


_models: LocalModels | None = None
_load_lock = threading.Lock()


def load_models(device: str | None = None, dtype: str | None = None) -> LocalModels:
    """Load both models once per process; later calls return the same instance."""
    global _models
    with _load_lock:
        if _models is not None:
            return _models
        if dtype is not None:
            check_dtype(dtype)
        from sentence_transformers import CrossEncoder, SentenceTransformer

        default_device, default_dtype = default_device_and_dtype()
        device = device or default_device
        dtype = dtype or default_dtype
        torch_dtype = resolve_dtype(dtype, device)
        embedder = SentenceTransformer(
            EMBEDDING_MODEL_ID,
            device=device,
            model_kwargs={"dtype": torch_dtype},
            config_kwargs={"audio_config": None},
        )
        embedder.max_seq_length = EMBEDDING_CONTEXT_TOKENS
        reranker = CrossEncoder(
            RERANKER_MODEL_ID,
            device=device,
            max_length=RERANKER_MAX_LENGTH,
            model_kwargs={"dtype": torch_dtype},
        )
        _models = LocalModels(embedder, reranker, device=device, dtype=dtype)
        return _models


class ModelsClient:
    """HTTP client for the models role: workers send document vectors, the API role queries and reranks."""

    def __init__(self, base_url: str = "", timeout_s: float = 30.0, http: httpx.Client | None = None):
        self._http = http or httpx.Client(base_url=base_url, timeout=timeout_s)

    def embed_documents(self, texts: list[str], titles: list[str | None] | None = None) -> list[list[float]]:
        titles = titles or [None] * len(texts)
        items = [{"text": t, "title": title} for t, title in zip(texts, titles, strict=True)]
        return self._post("/embed/text", {"kind": EmbedKind.DOCUMENT, "items": items})["vectors"]

    def embed_queries(self, queries: list[str]) -> list[list[float]]:
        items = [{"text": q} for q in queries]
        return self._post("/embed/text", {"kind": EmbedKind.QUERY, "items": items})["vectors"]

    def embed_images(self, images: list[bytes]) -> list[list[float]]:
        import base64

        payload = {"images_b64": [base64.b64encode(raw).decode("ascii") for raw in images]}
        return self._post("/embed/image", payload)["vectors"]

    def count_tokens(self, texts: list[str]) -> list[int]:
        """EmbeddingGemma token counts from the models role (workers never import transformers)."""
        counts: list[int] = []
        for start in range(0, len(texts), MAX_TOKENIZE_ITEMS):
            batch = texts[start : start + MAX_TOKENIZE_ITEMS]
            counts += self._post("/tokenize/count", {"texts": batch})["counts"]
        return counts

    def rerank(self, query: str, passages: list[str]) -> RerankResult:
        body = self._post("/rerank", {"query": query, "passages": passages})
        return RerankResult(scores=body["scores"], order=body["order"], margin_1_5=body["margin_1_5"])

    def health(self) -> dict[str, Any]:
        try:
            response = self._http.get("/models/health")
        except httpx.HTTPError as exc:
            raise ModelServerUnavailable(f"models role unreachable: {type(exc).__name__}") from exc
        return self._json(response)

    def close(self) -> None:
        self._http.close()

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            response = self._http.post(path, json=payload)
        except httpx.HTTPError as exc:
            raise ModelServerUnavailable(f"models role unreachable on {path}: {type(exc).__name__}") from exc
        return self._json(response)

    @staticmethod
    def _json(response: httpx.Response) -> dict[str, Any]:
        if response.status_code >= 500:
            raise ModelServerUnavailable(f"models role failed: HTTP {response.status_code}")
        if response.status_code >= 400:
            raise ModelRequestRejected(f"models role rejected the request: {response.text[:300]}")
        return response.json()
