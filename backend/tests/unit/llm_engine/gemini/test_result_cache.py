"""Plan task 7: every pipeline result is saved the moment it arrives, so a re-run after the gateway connection
dies in the middle of a document repeats no model call; hits are ledger rows with status cache_hit."""

import httpx
import pytest

from backend import config
from backend.llm_engine.gemini_types import BudgetExhausted, CallContext, DailyTokenBudget, Message
from backend.tests.unit.llm_engine.gemini.test_gemini_client import MODEL, Answer, Gateway, client_for, ok


@pytest.fixture(autouse=True)
def no_google_key(monkeypatch):
    for name in config.FORBIDDEN_NAMES:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def records():
    return []


class Store:
    def __init__(self, fail_put: bool = False):
        self.data: dict[str, bytes] = {}
        self.fail_put = fail_put

    def get(self, key):
        return self.data.get(key)

    def put(self, key, data):
        if self.fail_put:
            raise OSError("minio unreachable")
        self.data[key] = data


def _document(client, n=3, purpose="enrichment.parent"):
    """One document's calls: n sections, each its own request."""
    return [
        client.generate_sync(
            model=MODEL,
            messages=[Message.user(f"section {i} of the test report")],
            context=CallContext(purpose=purpose, prompt_version="parent.v1", doc_id="doc-1"),
            schema=Answer,
        )
        for i in range(n)
    ]


def test_a_rerun_after_the_connection_died_mid_document_repeats_no_call(records):
    store = Store()
    dead = Gateway(ok("structured.json"), ok("structured.json"), httpx.ConnectError("connection killed"))
    first = client_for(dead, records, max_attempts=1, result_cache=store)
    with pytest.raises(Exception, match="unreachable|connection"):
        _document(first)
    assert len(dead.requests) == 3 and len(store.data) == 2  # two answers saved before the cut

    alive = Gateway(ok("structured.json"))
    again = client_for(alive, records, result_cache=store)
    results = _document(again)

    assert len(alive.requests) == 1  # only the section the outage interrupted
    assert all(r.parsed == Answer(city="Tokyo", population_millions=37.1) for r in results)
    assert [r.status for r in records][-3:] == ["cache_hit", "cache_hit", "ok"]
    assert [r.input_tokens for r in records if r.status == "cache_hit"] == [0, 0]


def test_interactive_purposes_are_never_cached(records):
    store = Store()
    gateway = Gateway(ok("structured.json"))
    client = client_for(gateway, records, result_cache=store)
    _document(client, n=1, purpose="engine.query_analysis")
    _document(client, n=1, purpose="engine.query_analysis")
    assert len(gateway.requests) == 2 and store.data == {}


def test_a_saved_answer_is_served_even_when_the_budget_is_used_up(records):
    store = Store()
    gateway = Gateway(ok("structured.json"))
    _document(client_for(gateway, records, result_cache=store), n=1)
    exhausted = DailyTokenBudget(limit_tokens=1)
    exhausted.record(10)
    client = client_for(gateway, records, result_cache=store, budget=exhausted)
    (hit,) = _document(client, n=1)
    assert records[-1].status == "cache_hit" and len(gateway.requests) == 1
    with pytest.raises(BudgetExhausted):
        client.generate_sync(
            model=MODEL,
            messages=[Message.user("a section never seen")],
            context=CallContext(purpose="enrichment.parent", prompt_version="parent.v1"),
            schema=Answer,
        )


def test_a_failed_save_never_loses_the_answer_in_hand(records):
    gateway = Gateway(ok("structured.json"))
    (result,) = _document(client_for(gateway, records, result_cache=Store(fail_put=True)), n=1)
    assert result.parsed is not None and records[-1].status == "ok"


def test_a_hit_in_a_callers_own_cache_is_a_free_ledger_row(records):
    gateway = Gateway()
    client = client_for(gateway, records)
    client.record_cache_hit(MODEL, CallContext(purpose="vision.triage_page", prompt_version="triage_page.v1"))
    (row,) = records
    assert (row.status, row.purpose, row.input_tokens, row.output_tokens) == (
        "cache_hit",
        "vision.triage_page",
        0,
        0,
    )
    assert gateway.requests == []
