import json
from pathlib import Path

import httpx
import pytest
from opentelemetry import metrics
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader

from backend import config
from backend.common import telemetry
from backend.config import Settings
from backend.llm_engine.gemini_client import GeminiClient
from backend.llm_engine.gemini_types import (
    BudgetExhausted,
    CallContext,
    Capabilities,
    DailyTokenBudget,
    Message,
)

READER = InMemoryMetricReader()
metrics.set_meter_provider(MeterProvider(metric_readers=[READER]))
RECORDED = Path(__file__).resolve().parents[2] / "unit/llm_engine/gemini/responses/manastu/plain.json"


@pytest.fixture(autouse=True)
def no_google_key(monkeypatch):
    for name in config.FORBIDDEN_NAMES:
        monkeypatch.delenv(name, raising=False)


def points() -> dict[str, list]:
    data = READER.get_metrics_data()
    found: dict[str, list] = {}
    for resource in data.resource_metrics if data else []:
        for scope in resource.scope_metrics:
            for metric in scope.metrics:
                found.setdefault(metric.name, []).extend(metric.data.data_points)
    return found


def test_without_an_otlp_endpoint_nothing_is_exported(monkeypatch):
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    assert telemetry.otlp_enabled() is False
    assert telemetry.setup_telemetry("dcl-test") is False


def test_metric_names_match_file_02_section_10():
    names = {name for name in vars(type(telemetry.METRICS)) if not name.startswith("_")}
    assert {
        "graph_requests_total",
        "graph_pause_seconds_total",
        "delta_pages_total",
        "items_gated_total",
        "downloads_total",
        "download_bytes_total",
        "blob_dedup_hits_total",
    } <= names
    for name in names:
        instrument = getattr(telemetry.METRICS, name)
        assert getattr(instrument, "name", getattr(instrument, "_name", None)) == name


def test_feature_code_records_through_metrics():
    telemetry.METRICS.downloads_total.add(3, {"result": "ok"})
    telemetry.METRICS.sync_auth_ok.set(0, {"root": "APU"})
    found = points()
    assert sum(p.value for p in found["downloads_total"] if p.attributes == {"result": "ok"}) >= 3
    assert [p.value for p in found["sync_auth_ok"] if p.attributes == {"root": "APU"}] == [0]


def test_gateway_calls_record_calls_tokens_and_budget_stops():
    body = json.loads(RECORDED.read_text())["body"]
    settings = Settings(
        _env_file=None,
        GEMINI_BACKEND="gateway",
        GEMINI_GATEWAY_URL="https://gw.test",
        GEMINI_GATEWAY_KEY="k" * 20,
    )
    client = GeminiClient(
        settings,
        capabilities=Capabilities.all(),
        budget=DailyTokenBudget(limit_tokens=1),
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json=body)),
    )
    ctx = CallContext(purpose="metrics_test")
    client.generate_sync(model="gemini-3.8-flash", messages=[Message.user("x")], context=ctx)
    with pytest.raises(BudgetExhausted):
        client.generate_sync(model="gemini-3.8-flash", messages=[Message.user("x")], context=ctx)
    found = points()
    calls = [p for p in found["llm_calls_total"] if p.attributes.get("purpose") == "metrics_test"]
    assert [(p.attributes["status"], p.value) for p in calls] == [("ok", 1)]
    kinds = {
        p.attributes["kind"]
        for p in found["llm_tokens_total"]
        if p.attributes.get("purpose") == "metrics_test"
    }
    assert {"input", "output"} <= kinds
    assert any(p.value >= 1 for p in found["llm_budget_exhausted_total"])
