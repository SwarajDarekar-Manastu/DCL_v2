"""get_session yields one session per request and closes it; routers and tests override it."""

from typing import Annotated

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from backend.postgres import session as session_module


class FakeSession:
    closed = False

    def close(self):
        self.closed = True

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def test_get_session_yields_and_closes_one_session_per_request(monkeypatch):
    made: list[FakeSession] = []

    def factory():
        made.append(FakeSession())
        return made[-1]

    monkeypatch.setattr(session_module, "default_session_factory", lambda: factory)
    app = FastAPI()

    @app.get("/probe")
    def probe(session: Annotated[Session, Depends(session_module.get_session)]) -> bool:
        return isinstance(session, FakeSession)

    client = TestClient(app)
    assert client.get("/probe").json() is True
    assert client.get("/probe").json() is True
    assert len(made) == 2 and all(s.closed for s in made)


def test_normalize_url_selects_psycopg():
    assert session_module.normalize_url("postgresql://u:p@h:5432/d") == "postgresql+psycopg://u:p@h:5432/d"
    assert session_module.normalize_url("postgresql+psycopg://x") == "postgresql+psycopg://x"
