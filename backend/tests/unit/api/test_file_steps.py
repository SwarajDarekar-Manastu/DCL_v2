"""Files per pipeline step on the Ops page (api/file_steps.py). Needs DCL_TEST_DATABASE_URL."""

import json

import pytest

from backend.api.file_steps import NOT_QUEUED, Jobs, Step, count_steps, list_step, read_jobs
from backend.postgres import pipeline_config
from backend.postgres.models import Blob, Document, DocumentSource, DriveFolder, DriveItem

ROOT = "APU Injector"


@pytest.fixture()
def tree(session):
    """One folder in the processing scope and one outside it; files in every step."""
    for item_id, name in (("f-in", "Plans"), ("f-out", "Archive")):
        session.add(DriveFolder(drive_id="D", item_id=item_id, root_name=ROOT, name=name, path_cached=name))
    pipeline_config.set_value(session, pipeline_config.PROCESSING_SCOPE, ["f-in"], "test")

    def location(name, status, folder="f-in", sha=None, **extra):
        if sha:
            session.merge(Blob(sha256=sha, size_bytes=1, minio_uri=f"s3://dcl-raw/{sha}"))
        session.add(
            DriveItem(
                drive_id="D",
                item_id=f"i-{name}",
                root_name=ROOT,
                parent_item_id=folder,
                name=name,
                path_cached=f"{'Plans' if folder == 'f-in' else 'Archive'}/{name}",
                status=status,
                blob_sha256=sha,
                detected_mime="application/pdf" if sha else None,
                **extra,
            )
        )

    def document(title, status, sha=None, **extra):
        doc = Document(route="A1", status=status, title=title, **extra)
        session.add(doc)
        session.flush()
        if sha:
            session.add(DocumentSource(doc_id=doc.doc_id, blob_sha256=sha, role="primary"))
        return str(doc.doc_id)

    location("Thumbs.db", "SKIPPED_JUNK")
    location("rig.mov", "HELD_LARGE_FILE", gate_reason="T3:size")
    location("new.pdf", "PENDING_DOWNLOAD")
    location("old_notes.pdf", "LANDED", folder="f-out", sha="1" * 64)
    location("plan.pdf", "LANDED", sha="2" * 64)
    location("report.pdf", "LANDED", sha="3" * 64)
    docs = {
        "report": document("Report", "ACTIVE", sha="3" * 64),
        "running": document("Atlas", "PROCESSING"),
        "queued": document("HTRCHAR", "PROCESSING"),
        "lost": document("Setup", "PROCESSING"),
        "failed": document(
            "Manual", "FAILED", metadata_sources={"error": "StructuredOutputError: bad reply"}
        ),
        "halted": document("Run 12", "HALTED", staged_payload_uri="s3://dcl-cir/run12/staged.json"),
        "old": document("Report v1", "SUPERSEDED"),
    }
    session.flush()
    jobs = Jobs(held={docs["running"]: "cpu_parse"}, waiting={docs["queued"]: ("cpu_parse", 2)})
    return docs, jobs


def test_every_file_is_counted_in_its_step(session, tree):
    _, jobs = tree
    counts = {c.step: c.count for c in count_steps(session, jobs)}
    assert counts == {
        Step.TO_DOWNLOAD: 1,
        Step.HELD: 1,
        Step.SKIPPED: 1,
        Step.OUTSIDE_SCOPE: 1,
        Step.WAITING: 1,
        Step.IN_LINE: 2,
        Step.PROCESSING: 1,
        Step.REVIEW: 1,
        Step.FAILED: 1,
        Step.IN_SEARCH: 1,
        Step.TAKEN_OUT: 1,
    }


def test_a_step_lists_its_files_with_where_they_are(session, tree):
    def listed(step):
        return sorted((f.name, f.path, f.detail) for f in list_step(session, step, tree[1], 500).files)

    assert listed(Step.IN_LINE) == [
        ("HTRCHAR", None, "place 2 in cpu_parse"),
        ("Setup", None, NOT_QUEUED),
    ]
    assert listed(Step.PROCESSING) == [("Atlas", None, "cpu_parse")]
    assert listed(Step.IN_SEARCH) == [("Report", "Plans/report.pdf", None)]
    assert listed(Step.WAITING) == [("plan.pdf", "Plans/plan.pdf", "not yet made into a document")]
    assert listed(Step.OUTSIDE_SCOPE) == [("old_notes.pdf", "Archive/old_notes.pdf", None)]
    assert listed(Step.HELD) == [("rig.mov", "Plans/rig.mov", "too large to download")]
    assert listed(Step.FAILED) == [("Manual", None, "StructuredOutputError: bad reply")]
    assert listed(Step.TAKEN_OUT) == [("Report v1", None, "replaced by a newer version")]


def test_the_limit_caps_the_list_but_not_the_total(session, tree):
    page = list_step(session, Step.IN_LINE, tree[1], 1)
    assert (page.total, len(page.files)) == (2, 1)


class Redis:
    def __init__(self, unacked, queues):
        self.unacked, self.queues = unacked, queues

    def hvals(self, key):
        return [json.dumps(v) for v in self.unacked]

    def lrange(self, key, start, end):
        return [json.dumps(m) for m in self.queues.get(key, [])]


def _job(doc_id):
    return {"headers": {"task": "dcl.process.route_a1", "argsrepr": f"['{doc_id}']", "kwargsrepr": "{}"}}


def test_jobs_are_read_from_what_workers_hold_and_what_waits():
    a, b, c = (
        "11e7fa72-d20a-452f-baa4-1269b5d9ff3e",
        "8c4cdfdf-8d21-4290-b09e-3d2fddbe6213",
        "0" * 8 + "-0000-0000-0000-" + "0" * 12,
    )
    redis = Redis(
        unacked=[[_job(a), "", "cpu_parse"]],
        queues={"cpu_parse": [_job(c), _job(b)], "benchmark": [_job(c)]},  # b was pushed first: next
    )
    assert read_jobs(redis, False) == Jobs(held={a: "cpu_parse"}, waiting={})
    assert read_jobs(redis, True) == Jobs(
        held={a: "cpu_parse"}, waiting={b: ("cpu_parse", 1), c: ("cpu_parse", 2)}
    )
