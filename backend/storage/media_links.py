"""Media links that outlive the chat they are shown in (user, 2026-10-26).

A presigned MinIO link lives at most 15 minutes, and Open WebUI keeps an answer's embedded images and videos
with the message: after a reload, or later, the embedded link was dead. An answer now embeds a link to the
API instead, `{DCL_API_BASE_URL}/media/<key>?s=<signature>`; the API checks the signature and redirects to a
fresh 15-minute presigned link for that object (`api/media.py`). The browser follows the redirect, so a video
still streams with range requests straight from MinIO.

Only `dcl-assets` objects (renders, crops, thumbnails, video frames, video proxies, plots) get such links,
never raw files. The signature is an HMAC of the object key with a key derived from the MinIO secret, so a
link cannot be made for another object. Clicking a photo opens the file's OneDrive page, where OneDrive
decides who may see the original.
"""

import hashlib
import hmac
from urllib.parse import quote

from backend.config import ConfigError, Settings
from backend.storage.minio import ASSETS, parse_uri

LABEL = b"dcl-media-links/v1"
SIGNATURE_CHARS = 32


def _key(settings: Settings) -> bytes:
    secret = settings.minio_secret_key
    if secret is None:
        raise ConfigError("DCL_MINIO_SECRET_KEY is required to sign media links")
    return hmac.new(secret.get_secret_value().encode(), LABEL, hashlib.sha256).digest()


def signature(settings: Settings, key: str) -> str:
    return hmac.new(_key(settings), key.encode(), hashlib.sha256).hexdigest()[:SIGNATURE_CHARS]


def media_url(settings: Settings, minio_uri: str) -> str:
    """The lasting link of a `dcl-assets` object; any other bucket is refused."""
    bucket, key = parse_uri(minio_uri)
    if bucket != ASSETS:
        raise ValueError(f"only {ASSETS} objects get media links")
    if settings.api_base_url is None:
        raise ConfigError("DCL_API_BASE_URL is required for media links a browser opens")
    base = str(settings.api_base_url).rstrip("/")
    return f"{base}/media/{quote(key)}?s={signature(settings, key)}"


def valid(settings: Settings, key: str, sig: str) -> bool:
    return hmac.compare_digest(signature(settings, key), sig)
