"""Live checks of a running compose project. Skipped unless DCL_STACK_PROJECT names one, e.g.:

DCL_STACK_PROJECT=dcl-v2 uv run pytest backend/tests/integration/stack -q
"""

import json
import os
import shutil
import subprocess

import pytest

PROJECT = os.environ.get("DCL_STACK_PROJECT")
pytestmark = pytest.mark.skipif(not PROJECT or not shutil.which("docker"), reason="no live compose project")
CPU_SERVICES = ("api", "worker-io-light", "worker-cpu-parse", "beat")


def docker(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["docker", *args], capture_output=True, text=True, timeout=120, check=check)


def containers() -> list[dict]:
    out = docker("compose", "-p", PROJECT, "ps", "--all", "--format", "json").stdout
    return [json.loads(line) for line in out.splitlines() if line.strip()]


def exec_in(service: str, *cmd: str) -> subprocess.CompletedProcess:
    return docker("compose", "-p", PROJECT, "exec", "-T", service, *cmd, check=False)


ONE_SHOT = ("minio-init", "migrate")


def test_every_service_is_running_and_healthy_where_checked():
    states = {c["Service"]: (c["State"], c.get("Health", ""), c.get("ExitCode")) for c in containers()}
    assert states, "project has no containers"
    bad = {
        s: st
        for s, st in states.items()
        if (s in ONE_SHOT and (st[0], st[2]) != ("exited", 0))
        or (s not in ONE_SHOT and (st[0] != "running" or st[1] not in ("", "healthy")))
    }
    assert bad == {}


def test_migrations_are_at_head():
    result = exec_in("api", "alembic", "-c", "backend/postgres/alembic.ini", "current")
    assert "(head)" in result.stdout


def test_token_dir_is_writable_only_in_the_sync_worker():
    probe = 'test -w "${DCL_TOKEN_DIR:-/nonexistent}" && echo writable || echo absent'
    assert exec_in("worker-io-light", "sh", "-c", probe).stdout.strip() == "writable"
    assert exec_in("api", "sh", "-c", probe).stdout.strip() == "absent"


def test_gpu_is_visible_to_models():
    result = exec_in("models", "nvidia-smi", "-L")
    assert result.returncode == 0 and "GPU 0" in result.stdout


@pytest.mark.parametrize("service", CPU_SERVICES)
def test_gpu_is_not_visible_to_cpu_services(service):
    result = exec_in(
        service, "sh", "-c", "command -v nvidia-smi && nvidia-smi -L; ls /dev/nvidia* 2>/dev/null"
    )
    assert "GPU 0" not in result.stdout
    assert "/dev/nvidia" not in result.stdout


def test_api_reports_its_role():
    result = exec_in(
        "api",
        "python",
        "-c",
        "import urllib.request;print(urllib.request.urlopen('http://127.0.0.1:8200/healthz').read().decode())",
    )
    assert json.loads(result.stdout) == {"status": "ok", "role": "api"}


def test_no_env_file_or_secret_in_backend_image():
    secret_names = "\\( -name '.env' -o -name '.env.*' -o -name '*.pfx' -o -name '*.key' \\)"
    result = exec_in("api", "sh", "-c", f"find /app /home /opt /root /tmp -xdev {secret_names} 2>/dev/null")
    assert result.stdout.strip() == ""


def test_every_worker_answers_ping():
    for service in [c["Service"] for c in containers() if c["Service"].startswith("worker-")]:
        queue = service.removeprefix("worker-").replace("-", "_")
        result = exec_in(
            service,
            "sh",
            "-c",
            f"celery -A backend.celery_redis.app inspect ping --timeout 10 -d {queue}@$HOSTNAME",
        )
        assert "pong" in result.stdout, service


def test_duckdb_httpfs_loads_without_network():
    image = containers_image("api")
    probe = (
        "import duckdb; c = duckdb.connect(); c.execute('INSTALL httpfs; LOAD httpfs');"
        "q = \"select loaded from duckdb_extensions() where extension_name = 'httpfs'\";"
        "print(c.execute(q).fetchone()[0])"
    )
    result = docker(
        "run", "--rm", "--network", "none", "--entrypoint", "python", image, "-c", probe, check=False
    )
    assert result.returncode == 0, result.stderr[-500:]
    assert result.stdout.strip() == "True"


def containers_image(service: str) -> str:
    return next(c["Image"] for c in containers() if c["Service"] == service)
