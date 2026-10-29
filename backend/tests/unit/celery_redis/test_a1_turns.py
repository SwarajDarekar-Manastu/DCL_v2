"""Route A1 in turns (celery_redis/tasks_process.py route_a1, common/parallel.py): a turn that ends keeps the
file PROCESSING and sends it to the back of cpu_parse; the last allowed turn runs to the end."""

import uuid

from sqlalchemy import create_engine

from backend.celery_redis import tasks_process
from backend.common.parallel import TurnOver


def test_a_turn_that_ends_sends_the_file_to_the_back_of_its_queue(monkeypatch):
    sent, touched, checkpoints = [], [], []

    def run(doc_id, process, retryable=None, checkpoint=None):
        checkpoints.append(checkpoint)
        if checkpoint is not None:
            checkpoint()
        return {"doc_id": doc_id, "status": "continued"}

    monkeypatch.setattr(tasks_process, "_run", run)
    monkeypatch.setattr(tasks_process, "_touch", touched.append)
    monkeypatch.setattr(tasks_process.app, "send_task", lambda name, **kw: sent.append((name, kw)))
    tasks_process.route_a1.run("d1", turn=2)
    assert sent == [("dcl.process.route_a1", {"args": ["d1"], "kwargs": {"turn": 3}, "queue": "cpu_parse"})]
    assert touched == ["d1"]
    tasks_process.route_a1.run("d1", turn=tasks_process.MAX_CHECKPOINTS)
    assert checkpoints[-1] is None and len(sent) == 1


def test_an_ended_turn_is_not_a_failure(monkeypatch):
    monkeypatch.setattr(tasks_process, "_engine", lambda: create_engine("sqlite://"))
    monkeypatch.setattr(tasks_process, "get_settings", lambda: None)
    monkeypatch.setattr(tasks_process, "client_from_settings", lambda settings: None)
    monkeypatch.setattr(tasks_process, "_indexer", lambda minio: None)
    again = []

    def large_file(*args):
        raise TurnOver("the turn ended")

    result = tasks_process._run(str(uuid.uuid4()), large_file, checkpoint=lambda: again.append(True))
    assert (result["status"], again) == ("continued", [True])
