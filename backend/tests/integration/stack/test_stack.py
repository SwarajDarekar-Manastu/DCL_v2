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


def test_every_service_is_running_and_healthy_where_checked():
    states = {c["Service"]: (c["State"], c.get("Health", "")) for c in containers()}
    assert states, "project has no containers"
    bad = {s: st for s, st in states.items() if st[0] != "running" or st[1] not in ("", "healthy")}
    assert bad == {}


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
