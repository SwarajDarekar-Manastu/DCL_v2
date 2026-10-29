import re
from pathlib import Path

import pytest
import yaml

from backend.celery_redis import app as celery_app
from backend.celery_redis.queues import POOLS, VISIBILITY_TIMEOUT_S, Queue

DEVOPS = Path(__file__).resolve().parents[4] / "backend/devops"
EXPECTED_FILE_10 = {
    Queue.IO_LIGHT: ("threads", 4, 1024),
    Queue.CPU_PARSE: ("prefork", 1, 6144),
    Queue.TELEMETRY_STREAM: ("prefork", 2, 2 * 3072),
    Queue.MEDIA: ("prefork", 1, 6144),
    Queue.VISION_BATCH: ("threads", 2, 1024),
    Queue.EMBED: ("threads", 2, 2048),
    Queue.BENCHMARK: ("prefork", 1, 2048),
}


def compose(name: str) -> dict:
    return yaml.safe_load((DEVOPS / name).read_text())


def worker_service(queue: Queue) -> str:
    return "worker-" + str(queue).replace("_", "-")


def test_pools_match_file_10_section_4():
    assert {q: (p.pool, p.concurrency, p.memory_limit_mb) for q, p in POOLS.items()} == EXPECTED_FILE_10
    assert POOLS[Queue.TELEMETRY_STREAM].max_memory_per_child_mb == 3072
    assert POOLS[Queue.CPU_PARSE].max_memory_per_child_mb == 6144
    assert (POOLS[Queue.CPU_PARSE].soft_time_limit_s, POOLS[Queue.CPU_PARSE].time_limit_s) == (3600, 3900)
    benchmark = POOLS[Queue.BENCHMARK]
    assert (benchmark.soft_time_limit_s, benchmark.time_limit_s) == (950, 1000)


def test_every_pool_has_sane_time_limits():
    for pool in POOLS.values():
        assert 0 < pool.soft_time_limit_s < pool.time_limit_s
    assert VISIBILITY_TIMEOUT_S > max(p.time_limit_s for p in POOLS.values())


@pytest.mark.parametrize("queue", list(POOLS))
def test_compose_worker_matches_its_pool(queue):
    service = compose("compose.yaml")["services"][worker_service(queue)]
    pool = POOLS[queue]
    command = service["command"]
    assert command[:7] == [
        "celery",
        "-A",
        "backend.celery_redis.app",
        "worker",
        "--hostname",
        f"{queue}@%h",
        "--loglevel",
    ]
    assert command[8:] == pool.worker_args
    assert service["deploy"]["resources"]["limits"]["memory"] == f"{pool.memory_limit_mb}M"
    assert f"-d {queue}@$$HOSTNAME" in service["healthcheck"]["test"][1]


def test_compose_has_one_worker_per_queue_and_nothing_else_named_worker():
    services = compose("compose.yaml")["services"]
    workers = {name for name in services if name.startswith("worker-")}
    assert workers == {worker_service(q) for q in POOLS}


def test_gpu_is_reserved_only_for_models():
    services = compose("compose.yaml")["services"]
    with_gpu = {
        name
        for name, svc in services.items()
        if svc.get("deploy", {}).get("resources", {}).get("reservations", {}).get("devices")
    }
    assert with_gpu == {"models"}
    (device,) = services["models"]["deploy"]["resources"]["reservations"]["devices"]
    assert {"gpu", "compute"} <= set(device["capabilities"]), (
        "without compute the container gets no CUDA driver"
    )
    for name, svc in services.items():
        env = svc.get("environment") or {}
        assert "NVIDIA_VISIBLE_DEVICES" not in env, name


def test_dev_override_only_lowers_limits():
    base = compose("compose.yaml")["services"]
    for name, svc in compose("compose.dev.yaml")["services"].items():
        limit = svc.get("deploy", {}).get("resources", {}).get("limits", {}).get("memory")
        if limit:
            assert int(limit.rstrip("M")) <= int(
                base[name]["deploy"]["resources"]["limits"]["memory"].rstrip("M")
            )


IN_NETWORK = {
    "DCL_REDIS_URL": "redis://${DCL_REDIS_PASSWORD:+:}${DCL_REDIS_PASSWORD:-}${DCL_REDIS_PASSWORD:+@}redis:6379/0",
    "DCL_MINIO_ENDPOINT": "http://minio:9000",
    "DCL_MODELS_URL": "http://models:8500",
    "DCL_OFFICE_URL": "http://libreoffice:2003",
}


@pytest.mark.parametrize("name", ["compose.yaml", "compose.dev.yaml"])
def test_backend_containers_get_in_network_urls_never_host_ones(name):
    base = compose("compose.yaml")["services"]
    services = compose(name)["services"]
    for service, svc in services.items():
        image = base.get(service, {}).get("image", "")
        if not image.startswith(("dcl-v2-backend", "dcl-v2-models")) or service == "minio-init":
            continue
        env = svc["environment"]
        for key, value in IN_NETWORK.items():
            assert env[key] == value, (name, service, key)
        assert "@postgres:5432/dcl_v2" in env["DCL_DATABASE_URL"], (name, service)
        assert "127.0.0.1" not in str(env), (name, service)


def test_token_dir_is_mounted_only_into_the_sync_worker():
    services = compose("compose.yaml")["services"]
    with_tokens = {
        n for n, svc in services.items() if any("DCL_TOKEN_DIR" in str(v) for v in svc.get("volumes", []))
    }
    assert with_tokens == {"worker-io-light"}


def test_published_host_ports_follow_the_lead_allocation():
    services = compose("compose.yaml")["services"]
    ports = [port for svc in services.values() for port in svc.get("ports", [])]
    published = {
        re.fullmatch(r"\$\{DCL_(?:DATA_)?BIND_HOST:-127\.0\.0\.1\}:(.+):\d+", port).group(1) for port in ports
    }
    assert published == {
        "${DCL_DB_PORT:-5435}",
        "6381",
        "9100",
        "${DCL_MINIO_CONSOLE_PORT:-9101}",
        "8500",
        "8200",
        "${DCL_GRAFANA_PORT:-3300}",
        "8601",
        "${DCL_OPENWEBUI_PORT:-8300}",
    }
    data_ports = {name: svc["ports"] for name, svc in services.items() if name in ("postgres", "redis")}
    assert all(
        p.startswith("${DCL_DATA_BIND_HOST:-127.0.0.1}:") for ports_ in data_ports.values() for p in ports_
    )
    assert services["minio"]["ports"][0].startswith("${DCL_DATA_BIND_HOST:-127.0.0.1}:9100:")
    assert services["minio"]["ports"][1].startswith("${DCL_BIND_HOST:-127.0.0.1}:")


def test_celery_app_declares_every_queue_and_safe_defaults():
    conf = celery_app.app.conf
    assert {q.name for q in conf.task_queues} == {str(q) for q in Queue}
    assert conf.task_acks_late is True
    assert conf.task_reject_on_worker_lost is True
    assert conf.worker_prefetch_multiplier == 1
    assert conf.broker_transport_options["visibility_timeout"] == VISIBILITY_TIMEOUT_S
    # The broker follows the configured DCL_REDIS_URL (host-side in a developer .env, in-network in compose);
    # the literal dev default only applies when no .env provides one.
    from backend.config import get_settings

    assert conf.broker_url == str(get_settings().redis_url)


def test_ping_task_runs_eagerly():
    assert celery_app.ping.apply().get() == "pong"


def test_only_existing_task_modules_are_included(monkeypatch):
    found = {"backend.celery_redis.tasks_sync"}
    monkeypatch.setattr(
        celery_app.importlib.util, "find_spec", lambda name: object() if name in found else None
    )
    assert celery_app.present_task_modules() == ["backend.celery_redis.tasks_sync"]


def test_beat_schedule_runs_on_io_light_in_local_time():
    from celery.schedules import crontab

    schedule = celery_app.app.conf.beat_schedule
    assert {e["task"] for e in schedule.values()} == {
        "dcl.sync.delta_all",
        "dcl.sync.poll_deltas",
        "dcl.sync.renew_subscriptions",
        "dcl.sync.token_health",
        "dcl.sync.enqueue_downloads",
        "dcl.process.dispatch",
        "dcl.process.reconcile",
        "dcl.process.sweep_documents",
        "dcl.benchmark.tick",
    }
    queues = {name: e["options"]["queue"] for name, e in schedule.items()}
    assert set(queues.values()) == {"io_light"}
    daily = schedule["sync-delta-all-daily"]["schedule"]
    assert isinstance(daily, crontab) and daily.hour == {2} and daily.minute == {0}
    assert schedule["sync-delta-poll"]["schedule"] == 300.0
    renew = schedule["sync-renew-subscriptions"]["schedule"]
    assert isinstance(renew, crontab) and renew.minute == {0} and len(renew.hour) == 24
    assert schedule["sync-token-health"]["schedule"] == 900.0
    assert schedule["sync-enqueue-downloads"]["schedule"] == 600.0
    assert schedule["process-dispatch"]["schedule"] == 1800.0
    assert schedule["process-reconcile"]["schedule"] == 1800.0
    sweep = schedule["process-sweep-documents-daily"]["schedule"]
    assert sweep.hour == {3} and sweep.minute == {0}
    assert schedule["benchmark-sweep"]["schedule"] == 60.0
    assert celery_app.app.conf.timezone == "Asia/Kolkata"
    assert celery_app.app.conf.enable_utc is True


def test_every_scheduled_task_is_registered_by_an_included_module():
    celery_app.app.loader.import_default_modules()
    scheduled = {e["task"] for e in celery_app.app.conf.beat_schedule.values()}
    assert scheduled - set(celery_app.app.tasks) == set()
    for name in ("dcl.benchmark.start", "dcl.benchmark.case", "dcl.benchmark.sweep"):
        assert celery_app.app.tasks[name].queue == "benchmark"


def test_benchmark_tasks_without_their_own_queue_route_to_the_benchmark_queue():
    router = celery_app.app.amqp.router
    assert router.route({}, "dcl.benchmark.case")["queue"].name == "benchmark"
    assert router.route({}, "dcl.sync.delta_all")["queue"].name == "io_light"


def test_open_webui_is_pinned_persistent_and_on_the_stack_network():
    stack = compose("compose.yaml")
    service = stack["services"]["open-webui"]
    assert service["image"] == "ghcr.io/open-webui/open-webui:v0.12.3"
    assert service["ports"] == ["${DCL_BIND_HOST:-127.0.0.1}:${DCL_OPENWEBUI_PORT:-8300}:8080"]
    assert service["volumes"] == ["open-webui-data:/app/backend/data"]
    assert "open-webui-data" in stack["volumes"]
    assert "networks" not in service and "networks" not in stack["services"]["api"]
    assert service["environment"]["WEBUI_URL"].startswith("${DCL_OPENWEBUI_URL:-")


def test_media_worker_runs_the_media_image_with_a_whisper_cache_volume():
    stack = compose("compose.yaml")
    service = stack["services"]["worker-media"]
    assert (service["image"], service["build"]["target"]) == ("dcl-v2-media:local", "media")
    assert service["volumes"] == ["whisper-cache:/home/app/.cache/huggingface"]
    assert "whisper-cache" in stack["volumes"]
    dockerfile = (DEVOPS / "docker/backend.Dockerfile").read_text()
    media = dockerfile.split("FROM runtime AS media", 1)[1].split("\nFROM ", 1)[0]
    assert "ENV HF_HOME=/home/app/.cache/huggingface HF_HUB_DISABLE_XET=1" in media
    assert "--group media" in dockerfile and "ffmpeg" in media and "ARG WHISPER_MODEL=medium" in media


def test_media_group_keeps_pyav_below_19_for_faster_whisper():
    import tomllib

    project = tomllib.loads((DEVOPS.parents[1] / "pyproject.toml").read_text())
    media = project["dependency-groups"]["media"]
    assert "faster-whisper==1.2.1" in media and "av==18.0.0" in media
