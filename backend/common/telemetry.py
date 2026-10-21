"""OpenTelemetry for every backend process (docs/architecture/01 §5.7; 02 §10) and the one list of metrics.

Each process calls setup_telemetry(service) once. When OTEL_EXPORTER_OTLP_ENDPOINT is set (compose sets it to
the collector), traces and metrics go there over OTLP/HTTP; otherwise nothing is exported, so tests and host
CLIs need no collector. Prometheus scrapes the collector, so prefork Celery children need no local exporter.

Metric names are final here (the collector adds no suffixes); features record through METRICS:

    from backend.common.telemetry import METRICS
    METRICS.graph_requests_total.add(1, {"status": "200"})
"""

import logging
import os
import threading
from collections.abc import Iterable

from opentelemetry import metrics, trace
from opentelemetry.metrics import CallbackOptions, Observation

log = logging.getLogger(__name__)

SERVICE_NAMESPACE = "dcl-v2"
EXPORT_INTERVAL_MS = 15_000
_meter = metrics.get_meter("dcl")
_setup_lock = threading.Lock()
_configured: str | None = None


class _Metrics:
    """Instruments of file 02 §10 plus the Gemini ledger; names are what Prometheus shows."""

    graph_requests_total = _meter.create_counter(
        "graph_requests_total", description="Graph calls by HTTP status"
    )
    graph_pause_seconds_total = _meter.create_counter(
        "graph_pause_seconds_total", description="Seconds paused for Graph Retry-After"
    )
    delta_pages_total = _meter.create_counter(
        "delta_pages_total", description="Graph delta pages read, per root"
    )
    items_gated_total = _meter.create_counter("items_gated_total", description="Gate decisions by decision")
    downloads_total = _meter.create_counter("downloads_total", description="Downloads by result")
    download_bytes_total = _meter.create_counter("download_bytes_total", description="Bytes downloaded")
    blob_dedup_hits_total = _meter.create_counter(
        "blob_dedup_hits_total", description="Downloads skipped by hash"
    )
    sync_resync_started_total = _meter.create_counter(
        "sync_resync_started_total", description="410 or forced resyncs started, per root"
    )
    sync_auth_ok = _meter.create_gauge(
        "sync_auth_ok", description="1 when the token health check passed, per root"
    )
    sync_root_reachable = _meter.create_gauge(
        "sync_root_reachable", description="1 when the root answered, per root"
    )
    webhook_last_notification_timestamp_seconds = _meter.create_gauge(
        "webhook_last_notification_timestamp_seconds",
        description="Unix time of the last Graph notification, per root",
    )
    llm_calls_total = _meter.create_counter(
        "llm_calls_total", description="Gemini calls by model, purpose, status"
    )
    llm_tokens_total = _meter.create_counter(
        "llm_tokens_total", description="Gemini tokens by model and kind"
    )
    llm_cost_total = _meter.create_counter("llm_cost_total", description="Estimated Gemini cost by model")
    llm_budget_exhausted_total = _meter.create_counter(
        "llm_budget_exhausted_total", description="Calls refused by the daily budget or gateway quota"
    )


METRICS = _Metrics()


def otlp_enabled() -> bool:
    return bool(os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT"))


def setup_telemetry(service_name: str, environment: str | None = None) -> bool:
    """Install the tracer and meter providers once per process. Returns True when exporting."""
    global _configured
    with _setup_lock:
        if _configured is not None:
            return otlp_enabled()
        _configured = service_name
        if not otlp_enabled():
            return False
        from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
        from opentelemetry.sdk.metrics import MeterProvider
        from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        resource = Resource.create(
            {
                "service.name": service_name,
                "service.namespace": SERVICE_NAMESPACE,
                "deployment.environment": environment or os.environ.get("DCL_ENV", "dev"),
            }
        )
        tracer_provider = TracerProvider(resource=resource)
        tracer_provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
        trace.set_tracer_provider(tracer_provider)
        reader = PeriodicExportingMetricReader(
            OTLPMetricExporter(), export_interval_millis=EXPORT_INTERVAL_MS
        )
        metrics.set_meter_provider(MeterProvider(resource=resource, metric_readers=[reader]))
        HTTPXClientInstrumentor().instrument()
        log.info("telemetry exporting as %s", service_name)
        return True


def instrument_fastapi(app) -> None:
    if otlp_enabled():
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        FastAPIInstrumentor.instrument_app(app, excluded_urls="healthz,models/health,metrics")


def instrument_celery() -> None:
    if otlp_enabled():
        from opentelemetry.instrumentation.celery import CeleryInstrumentor

        CeleryInstrumentor().instrument()


def register_queue_depth(redis_url: str, queues: Iterable[str]) -> None:
    """Observable gauge `celery_queue_depth{queue}` read from the Redis broker lists (api role only)."""
    import redis

    client = redis.Redis.from_url(redis_url, socket_timeout=2)
    names = list(queues)

    def observe(_: CallbackOptions):
        for name in names:
            try:
                yield Observation(client.llen(name), {"queue": name})
            except redis.RedisError:
                log.warning("queue depth unavailable for %s", name)

    _meter.create_observable_gauge("celery_queue_depth", callbacks=[observe], description="Messages waiting")
