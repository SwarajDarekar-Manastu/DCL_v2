"""Lasting media links (storage/media_links.py, api/media.py): signed per object, dcl-assets only."""

from types import SimpleNamespace

import pytest
from pydantic import SecretStr

from backend.storage import media_links

SETTINGS = SimpleNamespace(minio_secret_key=SecretStr("minio-secret"), api_base_url="http://localhost:8200/")


def test_a_link_names_the_object_and_carries_a_signature_only_for_it():
    url = media_links.media_url(SETTINGS, "s3://dcl-assets/photos/abc/thumb.jpg")
    base, _, sig = url.partition("?s=")
    assert base == "http://localhost:8200/media/photos/abc/thumb.jpg"
    assert media_links.valid(SETTINGS, "photos/abc/thumb.jpg", sig)
    assert not media_links.valid(SETTINGS, "photos/abc/web.jpg", sig)  # another object, same signature
    other = SimpleNamespace(minio_secret_key=SecretStr("rotated"), api_base_url="http://localhost:8200")
    assert not media_links.valid(other, "photos/abc/thumb.jpg", sig)


def test_only_asset_objects_get_lasting_links():
    with pytest.raises(ValueError, match="dcl-assets"):
        media_links.media_url(SETTINGS, "s3://dcl-raw/aa/original.heic")
