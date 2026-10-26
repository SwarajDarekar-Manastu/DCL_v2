"""Presigned URLs for renderable assets and chat-attachment uploads (file 05 §1, file 08 §4.4).

The Console never talks to MinIO with credentials: it asks here, after sign-in, for a 15-minute
GET URL of a `dcl-assets` object (page renders, crops, photos, frames, sparklines). Typed review
evidence and viewer payloads carry `s3://dcl-assets/...` URIs; originals (`dcl-raw`) are never
presigned through this route.

`POST /assets/upload` is for the Open WebUI Pipe only (signed Pipe identity): it hands out a
presigned PUT and GET for a fresh `s3://dcl-exports/uploads/{user}/{uuid}` object, which the Pipe
fills with a file attached in chat and passes to the engine as an answer-time input. Uploads are
never indexed and expire after 24 hours (bucket lifecycle rule, S4).
"""

import re
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from minio import Minio
from pydantic import BaseModel, Field

from backend.api.auth import ConsoleRole, ConsoleUser, require_role
from backend.api.engine import Identity as PipeCaller
from backend.config import get_settings
from backend.storage.minio import (
    ASSETS,
    EXPORTS,
    PRESIGN_TTL,
    StorageError,
    browser_client_from_settings,
    client_from_settings,
    parse_uri,
    presign_get,
    presign_put,
    uri,
)

MAX_UPLOAD_BYTES = 25 * 1024 * 1024


class AssetUrl(BaseModel):
    url: str
    expires_in_s: int


def get_minio() -> Minio:
    return client_from_settings(get_settings())


def get_browser_minio() -> Minio:
    """Signs the links a user's browser opens (``DCL_MINIO_PUBLIC_ENDPOINT``)."""
    return browser_client_from_settings(get_settings())


router = APIRouter(tags=["assets"])
Viewer = Annotated[ConsoleUser, Depends(require_role(ConsoleRole.VIEWER))]


@router.get("/assets/url")
def asset_url(
    uri: Annotated[str, Query(max_length=1024, description="s3://dcl-assets/<key>")],
    user: Viewer,
    client: Annotated[Minio, Depends(get_browser_minio)],
) -> AssetUrl:
    try:
        bucket, _ = parse_uri(uri)
    except StorageError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    if bucket != ASSETS:
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"only {ASSETS} objects are presigned here")
    return AssetUrl(url=presign_get(client, uri), expires_in_s=int(PRESIGN_TTL.total_seconds()))


class UploadRequest(BaseModel):
    file_name: str = Field(min_length=1, max_length=255)
    mime_type: str = Field(min_length=1, max_length=255)
    size_bytes: int = Field(ge=1)


class UploadSlot(BaseModel):
    object_uri: str
    upload_url: str  # presigned PUT, 15 minutes
    get_url: str  # presigned GET for the engine, 15 minutes
    expires_in_s: int


@router.post("/assets/upload", status_code=status.HTTP_201_CREATED)
def request_upload(
    body: UploadRequest, caller: PipeCaller, client: Annotated[Minio, Depends(get_minio)]
) -> UploadSlot:
    if body.size_bytes > MAX_UPLOAD_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "file is over 25 MB")
    user = re.sub(r"[^A-Za-z0-9_-]", "_", caller.user_id)[:64] or "unknown"
    object_uri = uri(EXPORTS, f"uploads/{user}/{uuid.uuid4()}")
    return UploadSlot(
        object_uri=object_uri,
        upload_url=presign_put(client, object_uri),
        get_url=presign_get(client, object_uri),
        expires_in_s=int(PRESIGN_TTL.total_seconds()),
    )
