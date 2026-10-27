"""Landing a location's bytes (sync/downloader.py _land): an edit is inspected again."""

from types import SimpleNamespace

from backend.sync.downloader import _land

OLD, NEW = "a" * 64, "b" * 64


def _item(**kw):
    values = {
        "blob_sha256": OLD,
        "previous_blob_sha256": None,
        "detected_mime": "text/csv",
        "ext_mime_mismatch": True,
    }
    return SimpleNamespace(**(values | kw), status="SEEN", error_last="x")


def test_new_bytes_in_place_are_inspected_again_and_remember_the_old_version():
    item = _item()
    _land(None, item, NEW)
    assert (item.blob_sha256, item.previous_blob_sha256, item.detected_mime, item.ext_mime_mismatch) == (
        NEW,
        OLD,
        None,
        False,
    )


def test_the_same_bytes_keep_their_inspection():
    item = _item()
    _land(None, item, OLD)
    assert (item.detected_mime, item.ext_mime_mismatch, item.previous_blob_sha256) == ("text/csv", True, None)
