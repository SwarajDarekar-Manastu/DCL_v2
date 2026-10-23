"""Routes D (photos) and F (videos) on the shared runner, S2's ``process_photo`` and ``process_video``.

Bursts (file 03 §D): the photos of one folder are clustered by pHash and capture time (``burst_readings``,
``cluster_photos``, no model call; each photo's pair is cached at ``{sha}/D/v1/burst.json``). The first
photo of a burst is read by the model and its reading saved at ``{sha}/D/v1/reading.json``; the other
members reuse it. A member whose representative is still PROCESSING raises ``RepresentativePending`` and
the task retries later; without cloud processing, or when the representative ended without a reading,
the member is read on its own.
"""

import json
import uuid
from datetime import datetime
from functools import lru_cache

from minio import Minio
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.dispatcher.location import primary_location
from backend.dispatcher.runner import (
    Outcome,
    RunContext,
    common_options,
    read_object,
    run_document,
    vision_for,
)
from backend.indexing.commit import Indexer
from backend.postgres import pipeline_config
from backend.postgres.enums import DocumentSourceRole, DocumentStatus, Route
from backend.postgres.models import Blob, Document, DocumentSource

WHISPER_MODEL = "routes.F.whisper_model"
WHISPER_DEFAULT = "medium"  # int8 on CPU; large-v3 does not fit the 4 GiB media worker (DECISIONS 2026-10-23)


class RepresentativePending(RuntimeError):
    """The burst's representative photo has not been read yet; retry the member later."""


def _burst_pair(ctx: RunContext, sha: str, minio_uri: str) -> tuple[str, datetime | None]:
    from backend.routes import d_photos as d

    key = f"{sha}/D/v{d.PARSER_VERSION}/burst.json"
    cached = ctx.cir.get(key)
    if cached:
        value = json.loads(cached)
        return value["phash"], datetime.fromisoformat(value["taken_at"]) if value["taken_at"] else None
    ((phash, taken_at),) = d.burst_readings([(sha, read_object(ctx.minio, minio_uri))]).values()
    ctx.cir.put(
        key, json.dumps({"phash": phash, "taken_at": taken_at.isoformat() if taken_at else None}).encode()
    )
    return phash, taken_at


def _representative(ctx: RunContext) -> str:
    """The sha256 of the photo that represents this one's burst (itself when it leads one)."""
    from backend.routes import d_photos as d

    rows = ctx.session.execute(
        select(DocumentSource.blob_sha256, Blob.minio_uri)
        .join(Document, Document.doc_id == DocumentSource.doc_id)
        .join(Blob, Blob.sha256 == DocumentSource.blob_sha256)
        .where(
            Document.route == Route.D,
            DocumentSource.role == DocumentSourceRole.PRIMARY,
            Document.status.not_in(
                [DocumentStatus.SUPERSEDED, DocumentStatus.DELETED, DocumentStatus.QUARANTINED]
            ),
        )
    ).all()
    siblings = []
    for sha, minio_uri in rows:
        where = primary_location(ctx.session, sha)
        if where is not None and where.parent_item_id == ctx.where.parent_item_id:
            siblings.append((sha, *_burst_pair(ctx, sha, minio_uri)))
    return d.cluster_photos(siblings).get(ctx.blob.sha256, ctx.blob.sha256)


def _in_flight(session: Session, blob_sha256: str) -> bool:
    """The representative's document will still produce a reading (it is queued or running)."""
    status = session.scalar(
        select(Document.status)
        .join(DocumentSource, DocumentSource.doc_id == Document.doc_id)
        .where(DocumentSource.blob_sha256 == blob_sha256, DocumentSource.role == DocumentSourceRole.PRIMARY)
    )
    return status == DocumentStatus.PROCESSING


def process_d_document(
    session: Session, minio: Minio, doc_id: uuid.UUID, indexer: Indexer | None = None
) -> Outcome:
    from backend.routes import d_photos as d

    def build(ctx: RunContext):
        representative = _representative(ctx)
        reading = None
        if representative != ctx.blob.sha256 and ctx.cloud_allowed:
            saved = ctx.cir.get(f"{representative}/D/v{d.PARSER_VERSION}/reading.json")
            if saved is not None:
                value = json.loads(saved)
                reading = d.PhotoReading(
                    image_class=d.ImageClass(value["image_class"]),
                    content=value["content"],
                    metadata=value["metadata"],
                    confidence=value["confidence"],
                )
            elif _in_flight(ctx.session, representative):
                raise RepresentativePending(f"photo {representative} has not been read yet")
        processed, own = d.process_photo(
            ctx.data,
            folder=ctx.folder,
            vision=vision_for(ctx.session),
            put_asset=ctx.put_asset,
            representative=reading,
            cluster_id=representative,
            **common_options(ctx),
        )
        if own is not None and representative == ctx.blob.sha256:
            ctx.put_cir(
                "reading.json",
                json.dumps(
                    {
                        "image_class": str(own.image_class),
                        "content": own.content,
                        "metadata": own.metadata,
                        "confidence": own.confidence,
                    },
                    default=str,
                ).encode(),
            )
        return processed

    return run_document(session, minio, doc_id, Route.D, d.PARSER_VERSION, build, indexer)


@lru_cache(maxsize=2)
def _transcriber(model_size: str):
    from backend.routes.f_video import whisper_transcriber

    return whisper_transcriber(model_size)


def process_f_document(
    session: Session, minio: Minio, doc_id: uuid.UUID, indexer: Indexer | None = None
) -> Outcome:
    from backend.routes import f_video as f

    def build(ctx: RunContext):
        return f.process_video(
            ctx.data,
            folder=ctx.folder,
            vision=vision_for(ctx.session),
            put_asset=ctx.put_asset,
            transcribe=_transcriber(pipeline_config.get(ctx.session, WHISPER_MODEL, default=WHISPER_DEFAULT)),
            **common_options(ctx),
        )

    return run_document(session, minio, doc_id, Route.F, f.PARSER_VERSION, build, indexer)
