"""`GET /media/<key>?s=<signature>`: a lasting link to one `dcl-assets` object (storage/media_links.py).

A valid signature redirects to a fresh 15-minute presigned link signed for the browser's MinIO address; the
browser caches the redirect for at most 10 minutes. A wrong signature or another bucket is a 404, so the route
never confirms which objects exist.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import RedirectResponse
from minio import Minio

from backend.api.assets import get_browser_minio
from backend.config import get_settings
from backend.storage import media_links
from backend.storage.minio import ASSETS, presign_get

router = APIRouter(tags=["media"])


@router.get("/media/{key:path}")
def media(
    key: str,
    s: Annotated[str, Query(min_length=8, max_length=64)],
    client: Annotated[Minio, Depends(get_browser_minio)],
) -> RedirectResponse:
    if ".." in key or not media_links.valid(get_settings(), key, s):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such media")
    return RedirectResponse(
        presign_get(client, f"s3://{ASSETS}/{key}"),
        status_code=status.HTTP_302_FOUND,
        headers={"Cache-Control": "private, max-age=600"},
    )
