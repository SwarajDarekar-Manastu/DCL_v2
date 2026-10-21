from pathlib import Path

import pytest
import yaml

from backend.celery_redis import app as celery_app
from backend.celery_redis.queues import POOLS, VISIBILITY_TIMEOUT_S, Queue

DEVOPS = Path(__file__).resolve().parents[4] / "backend/devops"
EXPECTED_FILE_10 = {
    Queue.IO_LIGHT: ("threads", 4, 1024),
    Queue.CPU_PARSE: ("prefork", 4, 4 * 6144),
    Queue.TELEMETRY_STREAM: ("prefork", 2, 2 * 3072),
    Queue.MEDIA: ("prefork", 2, 4096),
    Queue.VISION_BATCH: ("threads", 2, 1024),
    Queue.EMBED: ("threads", 2, 2048),
}


def compose(name: str) -> dict:
    return yaml.safe_load((DEVOPS / name).read_text())


def worker_service(queue: Queue) -> str:
    return "worker-" + str(queue).replace("_", "-")


def test_pools_match_file_10_section_4():
    assert {q: (p.pool, p.concurrency, p.memory_limit_mb) for q, p in POOLS.items()} == EXPECTED_FILE_10
    assert POOLS[Queue.TELEMETRY_STREAM].max_memory_per_child_mb == 3072
    assert POOLS[Queue.CPU_PARSE].max_memory_per_child_mb == 6144


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


def test_backend_containers_never_inherit_the_host_database_url():
    services = compose("compose.yaml")["services"]
    for name, svc in services.items():
        if svc.get("image", "").startswith(("dcl-v2-backend", "dcl-v2-models")):
            assert svc["environment"]["DCL_DATABASE_URL"] == "", name


def test_celery_app_declares_every_queue_and_safe_defaults():
    conf = celery_app.app.conf
    assert {q.name for q in conf.task_queues} == {str(q) for q in Queue}
    assert conf.task_acks_late is True
    assert conf.task_reject_on_worker_lost is True
    assert conf.worker_prefetch_multiplier == 1
    assert conf.broker_transport_options["visibility_timeout"] == VISIBILITY_TIMEOUT_S
    assert conf.broker_url == "redis://redis:6379/0"


def test_ping_task_runs_eagerly():
    assert celery_app.ping.apply().get() == "pong"


def test_only_existing_task_modules_are_included(monkeypatch):
    found = {"backend.celery_redis.tasks_sync"}
    monkeypatch.setattr(
        celery_app.importlib.util, "find_spec", lambda name: object() if name in found else None
    )
    assert celery_app.present_task_modules() == ["backend.celery_redis.tasks_sync"]
