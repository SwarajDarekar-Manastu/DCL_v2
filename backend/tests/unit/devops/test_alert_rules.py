"""promtool checks and unit-tests the operational alert rules (backend/devops/prometheus)."""

import shutil
import subprocess
from pathlib import Path

import pytest

PROMETHEUS = Path(__file__).resolve().parents[3] / "devops" / "prometheus"
IMAGE = "prom/prometheus:v3.15.1"
pytestmark = pytest.mark.skipif(shutil.which("docker") is None, reason="docker is not available")


def promtool(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["docker", "run", "--rm", "-v", f"{PROMETHEUS}:/p:ro", "--entrypoint", "promtool", IMAGE, *args],
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )


def test_rules_are_valid():
    result = promtool("check", "rules", "/p/alerts.yml")
    assert result.returncode == 0, result.stdout + result.stderr


def test_alert_rules_fire_for_auth_failure_resync_queue_stall_and_budget_cap():
    result = promtool("test", "rules", "/p/alerts_test.yml")
    assert result.returncode == 0, result.stdout + result.stderr
