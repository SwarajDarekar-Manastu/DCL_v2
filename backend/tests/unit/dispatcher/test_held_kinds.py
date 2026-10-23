"""``routes.held_kinds``: files of a held kind wait as WAITING_FOR_ROUTE while their route stays on.

Needs DCL_TEST_DATABASE_URL and DCL_TEST_MINIO_ENDPOINT (disposable PostgreSQL and MinIO).
"""

import gzip
import io
import zipfile

import pytest
from sqlalchemy import select

from backend.dispatcher.routing import dispatch
from backend.postgres import pipeline_config
from backend.postgres.models import Document
from backend.tests.unit.dispatcher.test_dispatch import _file, _folders

HELD = ["zip", "gzip", "wbpz", "iges"]


def _zip(*names: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name in names:
            archive.writestr(name, "x")
    return buffer.getvalue()


def _seed(session, minio) -> None:
    _folders(session)
    files = {
        "bracket.stl": b"solid bracket\nendsolid bracket\n",
        "plate.dwg": b"AC1032" + bytes(64),
        "bundle.zip": _zip("readme.md"),
        "bundle.tar.gz": gzip.compress(b"x" * 600),
        "study.wbpz": _zip("Study.wbpj"),
        "surface.igs": b"IGES surface list\n",
    }
    for name, data in files.items():
        _file(session, minio, name, "F-TP12", name, data, "application/octet-stream")
    pipeline_config.set_value(session, pipeline_config.PROCESSING_SCOPE, ["F-TP12"], "test")
    pipeline_config.set_value(session, "routes.G.enabled", True, "test")
    pipeline_config.set_value(session, pipeline_config.HELD_KINDS, HELD, "test")
    session.commit()


def _status(session) -> dict[str, str]:
    return {d.title: d.status for d in session.scalars(select(Document))}


def test_held_kinds_wait_while_cad_runs(session, minio):
    _seed(session, minio)
    result = dispatch(session, minio)
    statuses = _status(session)
    assert [statuses[t] for t in ("bracket", "plate")] == ["PROCESSING", "PROCESSING"]
    assert sorted(t for t, s in statuses.items() if s == "WAITING_FOR_ROUTE") == [
        "bundle",
        "bundle.tar",
        "study",
        "surface",
    ]
    assert (result.created, result.waiting, len(result.to_process)) == (6, 4, 2)


def test_a_later_dispatch_does_not_release_a_held_kind(session, minio):
    _seed(session, minio)
    dispatch(session, minio)
    again = dispatch(session, minio)
    assert (again.released, again.created) == (0, 0)
    assert sum(s == "WAITING_FOR_ROUTE" for s in _status(session).values()) == 4


def test_removing_a_kind_from_the_list_releases_only_that_kind(session, minio):
    _seed(session, minio)
    dispatch(session, minio)
    pipeline_config.set_value(session, pipeline_config.HELD_KINDS, ["gzip", "wbpz", "iges"], "test")
    session.commit()
    released = dispatch(session, minio)
    statuses = _status(session)
    assert released.released == 1
    assert statuses["bundle"] == "PROCESSING"
    assert statuses["study"] == statuses["surface"] == statuses["bundle.tar"] == "WAITING_FOR_ROUTE"


def test_an_unknown_kind_is_refused_by_the_settings_validator(session):
    with pytest.raises(pipeline_config.InvalidConfig) as refused:
        pipeline_config.validate_changes(session, {pipeline_config.HELD_KINDS: ["zip", "zipp"]})
    assert "zipp" in refused.value.errors[pipeline_config.HELD_KINDS]
