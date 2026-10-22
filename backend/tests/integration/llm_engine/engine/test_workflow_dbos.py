"""The Answer Engine workflow under DBOS (decision H8). Needs DCL_TEST_DATABASE_URL (any PostgreSQL)."""

import asyncio
import contextlib
import os
import uuid

import pytest

pytest.importorskip("llama_agents.dbos", reason="llama-agents-dbos is not installed")

from sqlalchemy import create_engine, text  # noqa: E402

from backend.llm_engine.engine import workflow as wf
from backend.llm_engine.engine.tools import Provenance, Source, ToolResult
from backend.llm_engine.enrichment.entities import AliasIndex
from backend.llm_engine.gemini_types import GenerateResult, Usage

URL = os.environ.get("DCL_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not URL, reason="DCL_TEST_DATABASE_URL is not set")
PASSAGE = "Run T04 of TP07 reached 12.4 bar chamber pressure."
ANSWER = "TP07 T04 reached 12.4 bar [1]. " + " ".join(f"Sentence {n} of a long answer." for n in range(30))


class Client:
    def __init__(self, replies):
        self.replies = replies

    async def generate(self, *, model, messages, context, schema=None, **options):
        reply = self.replies[context.purpose.split(".")[1]]
        return GenerateResult("", schema.model_validate(reply), (), Usage(1, 1), model, "stop", "r", 1)


def search(session, args, *, embed_query, rerank):
    source = Source(
        doc_id=uuid.uuid4(),
        anchor="page:2:" + "b" * 64,
        title="TR 37",
        label="TR 37, p. 2",
        provenance=Provenance.INTERNAL_REPORT,
    )
    return ToolResult(
        tool="search_documents",
        result={"hits": [{"parent_text": PASSAGE}]},
        provenance=[source],
        display=PASSAGE,
    )


def test_the_workflow_runs_durably_under_dbos(monkeypatch):
    from dbos import DBOS

    monkeypatch.setattr(wf, "search_documents", search)
    client = Client(
        {
            "query_analysis": {"intents": ["fact_lookup"], "test_plan_ids": ["TP07"]},
            "synthesis": {
                "answer_markdown": ANSWER,
                "claims": [{"text": "TP07 T04 reached 12.4 bar", "kind": "numeric", "evidence_ids": ["E1"]}],
            },
            "verify": {"verdicts": [{"claim_index": 0, "verdict": "entailed", "reason": "stated"}]},
        }
    )
    deps = wf.EngineDeps(
        gemini=client,
        session_factory=contextlib.nullcontext,
        embed_query=lambda q: [0.0],
        rerank=None,
        alias_index=lambda s: AliasIndex(),
    )
    trace_id = str(uuid.uuid4())

    async def go():
        runtime = wf.build_runtime(URL, app_name="dcl-engine-test")
        workflow = wf.AnswerWorkflow(deps, runtime=runtime, workflow_name="answer", timeout=60)
        await runtime.launch()
        try:
            handler = workflow.run(question="TP07 T04 pressure?", trace_id=trace_id)
            frames = [payload async for payload in wf.ordered(handler.stream_events())]
            return frames, await handler, handler.run_id
        finally:
            await runtime.destroy()

    try:
        frames, done, run_id = asyncio.run(go())
    finally:
        DBOS.destroy()
    kinds = [f["type"] for f in frames]
    assert kinds[-1] == "done" and "citation" in kinds and kinds.count("token") >= 3
    assert "".join(f["text"] for f in frames if f["type"] == "token") == ANSWER  # order restored
    assert done["mode"] == "answered" and done["trace_id"] == trace_id
    with create_engine(URL.replace("postgresql://", "postgresql+psycopg://")).connect() as conn:
        status = conn.execute(
            text("SELECT status FROM dbos.workflow_status WHERE workflow_uuid = :id"), {"id": run_id}
        ).scalar()
    assert status == "SUCCESS"
