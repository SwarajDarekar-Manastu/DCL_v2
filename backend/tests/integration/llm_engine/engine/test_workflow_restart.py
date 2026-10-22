"""Durability (file 07 §2, decision H8): an engine killed mid-answer resumes the run in a new process.

Needs DCL_TEST_DATABASE_URL (any PostgreSQL). The worker runs in subprocesses so the kill is real.
"""

import json
import os
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pytest

pytest.importorskip("llama_agents.dbos", reason="llama-agents-dbos is not installed")

URL = os.environ.get("DCL_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not URL, reason="DCL_TEST_DATABASE_URL is not set")
WORKER = Path(__file__).with_name("_restart_worker.py")
ROOT = Path(__file__).resolve().parents[5]


def worker(mode: str, directory: Path) -> subprocess.CompletedProcess:
    env = {**os.environ, "PYTHONPATH": str(ROOT)}
    return subprocess.run(
        [sys.executable, str(WORKER), mode, str(directory), URL],
        env=env,
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )


def calls(directory: Path) -> list[tuple[str, str]]:
    return [tuple(line.split(" ", 1)) for line in (directory / "calls.log").read_text().splitlines()]


def test_a_killed_engine_resumes_the_answer_in_a_new_process(tmp_path):
    first = worker("start", tmp_path)
    assert first.returncode == 9, first.stderr[-2000:]  # died inside the tool step
    crashed_pid = (tmp_path / "crashed").read_text()
    assert not (tmp_path / "trace.json").exists()

    second = worker("recover", tmp_path)
    assert second.returncode == 0, second.stderr[-2000:]
    status = json.loads((tmp_path / "status.json").read_text())
    run = json.loads((tmp_path / "run.json").read_text())
    assert status["status"] == "SUCCESS", status
    assert isinstance(status["output"], dict), status["output"][:800]
    assert status["output"]["mode"] == "answered" and status["output"]["trace_id"] == run["trace_id"]

    log = calls(tmp_path)
    by_name = Counter(name for _, name in log)
    assert by_name["query_analysis"] == 1  # replayed from the journal, not asked again
    assert by_name["search_documents"] == 2  # interrupted, then run again
    assert {pid for pid, name in log if name == "query_analysis"} == {crashed_pid}
    assert all(pid != crashed_pid for pid, name in log if name in ("synthesis", "verify"))

    trace = json.loads((tmp_path / "trace.json").read_text())
    assert trace["trace_id"] == run["trace_id"] and trace["mode"] == "answered"
