"""Presigned URLs for renderable assets (file 05 §1, file 08 §4.4).

The Console never talks to MinIO with credentials: it asks here, after sign-in, for a 15-minute
GET URL of a `dcl-assets` object (page renders, crops, photos, frames, sparklines). Typed review
evidence and viewer payloads carry `s3://dcl-assets/...` URIs; originals (`dcl-raw`) are never
presigned through this route.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from minio import Minio
from pydantic import BaseModel

from backend.api.auth import ConsoleRole, ConsoleUser, require_role
from backend.config import get_settings
from backend.storage.minio import (
    ASSETS,
    PRESIGN_TTL,
    StorageError,
    client_from_settings,
    parse_uri,
    presign_get,
)


class AssetUrl(BaseModel):
    url: str
    expires_in_s: int


def get_minio() -> Minio:
    return client_from_settings(get_settings())


router = APIRouter(tags=["assets"])
Viewer = Annotated[ConsoleUser, Depends(require_role(ConsoleRole.VIEWER))]


@router.get("/assets/url")
def asset_url(
    uri: Annotated[str, Query(max_length=1024, description="s3://dcl-assets/<key>")],
    user: Viewer,
    client: Annotated[Minio, Depends(get_minio)],
) -> AssetUrl:
    try:
        bucket, _ = parse_uri(uri)
    except StorageError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    if bucket != ASSETS:
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"only {ASSETS} objects are presigned here")
    return AssetUrl(url=presign_get(client, uri), expires_in_s=int(PRESIGN_TTL.total_seconds()))
