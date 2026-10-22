"""S2: /embed/text, /embed/image, /rerank, /tokenize/count, /models/health (ROLE models or all).

Importing this module loads no weights. The first request to any endpoint here (the compose healthcheck on
/models/health at container start) loads both models once per process; until then nothing touches the GPU,
so processes that never serve a model request never load one. `/tokenize/count` needs only the
EmbeddingGemma tokenizer (CPU) and never loads the weights: workers size chunks with it instead of
importing transformers (DECISIONS 2026-10-22).
"""

import base64
import binascii
from collections.abc import Callable
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.llm_engine import local_models
from backend.llm_engine.local_models import (
    EMBEDDING_DIM,
    EMBEDDING_MODEL_TAG,
    MAX_TOKENIZE_ITEMS,
    RERANKER_MODEL_ID,
    EmbedKind,
    InputTooLong,
    LocalModels,
)

MAX_TEXT_ITEMS = 256
MAX_IMAGE_ITEMS = 32
MAX_RERANK_PASSAGES = 100
TOKENIZE_BATCH = 128


router = APIRouter(tags=["models"])


class TextItem(BaseModel):
    text: Annotated[str, Field(min_length=1)]
    title: str | None = None


class EmbedTextRequest(BaseModel):
    kind: EmbedKind
    items: Annotated[list[TextItem], Field(min_length=1, max_length=MAX_TEXT_ITEMS)]


class EmbedImageRequest(BaseModel):
    images_b64: Annotated[list[str], Field(min_length=1, max_length=MAX_IMAGE_ITEMS)]


class EmbedResponse(BaseModel):
    model: str = EMBEDDING_MODEL_TAG
    dim: int = EMBEDDING_DIM
    vectors: list[list[float]]


class RerankRequest(BaseModel):
    query: Annotated[str, Field(min_length=1)]
    passages: Annotated[list[str], Field(min_length=1, max_length=MAX_RERANK_PASSAGES)]


class RerankResponse(BaseModel):
    model: str = RERANKER_MODEL_ID
    scores: list[float]
    order: list[int]
    margin_1_5: float | None


class TokenCountRequest(BaseModel):
    texts: Annotated[list[str], Field(min_length=1, max_length=MAX_TOKENIZE_ITEMS)]


class TokenCountResponse(BaseModel):
    model: str = EMBEDDING_MODEL_TAG
    counts: list[int] = Field(description="tokens per text, without special tokens, in request order")


def tokenizer_dependency() -> Callable[[list[str]], list[int]]:
    try:
        local_models.embedding_tokenizer()
    except (OSError, ValueError, ImportError) as exc:
        raise HTTPException(status_code=503, detail=f"tokenizer failed to load: {exc}") from exc
    return local_models.count_tokens


TokenCounter = Annotated[Callable[[list[str]], list[int]], Depends(tokenizer_dependency)]


def models_dependency() -> LocalModels:
    try:
        return local_models.load_models()
    except (OSError, RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=503, detail=f"models failed to load: {exc}") from exc


Models = Annotated[LocalModels, Depends(models_dependency)]


@router.post("/embed/text")
def embed_text(request: EmbedTextRequest, models: Models) -> EmbedResponse:
    texts = [item.text for item in request.items]
    titles = [item.title for item in request.items]
    try:
        vectors = models.embed_texts(texts, request.kind, titles)
    except InputTooLong as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return EmbedResponse(vectors=vectors)


@router.post("/embed/image")
def embed_image(request: EmbedImageRequest, models: Models) -> EmbedResponse:
    try:
        images = [base64.b64decode(item, validate=True) for item in request.images_b64]
    except binascii.Error as exc:
        raise HTTPException(status_code=422, detail="images_b64 contains invalid base64") from exc
    try:
        vectors = models.embed_images(images)
    except OSError as exc:
        raise HTTPException(status_code=422, detail=f"undecodable image: {exc}") from exc
    return EmbedResponse(vectors=vectors)


@router.post("/rerank")
def rerank(request: RerankRequest, models: Models) -> RerankResponse:
    result = models.rerank(request.query, request.passages)
    return RerankResponse(scores=result.scores, order=result.order, margin_1_5=result.margin_1_5)


@router.post("/tokenize/count")
def tokenize_count(request: TokenCountRequest, count: TokenCounter) -> TokenCountResponse:
    counts: list[int] = []
    for start in range(0, len(request.texts), TOKENIZE_BATCH):
        counts += count(request.texts[start : start + TOKENIZE_BATCH])
    return TokenCountResponse(counts=counts)


@router.get("/models/health")
def models_health(models: Models) -> dict:
    return models.health()
