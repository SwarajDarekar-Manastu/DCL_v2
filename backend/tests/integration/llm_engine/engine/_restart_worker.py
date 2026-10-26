"""Worker process for test_workflow_restart.py (not collected by pytest).

`python _restart_worker.py start <dir> <database_url>` runs one answer under DBOS; the search tool kills the
process the first time it runs. `... recover <dir> <database_url>` launches the runtime again, which lets
DBOS recover the pending run, and waits for it to finish. Gemini and tool calls are counted in files in
<dir> so the test can see which steps ran in which process.
"""

import asyncio
import contextlib
import json
import os
import sys
import uuid
from pathlib import Path

from backend.llm_engine.engine import workflow as wf
from backend.llm_engine.engine.tools import Provenance, Source, ToolResult
from backend.llm_engine.enrichment.entities import AliasIndex
from backend.llm_engine.gemini_types import GenerateResult, Usage

APP_NAME = "dcl-engine-restart-test"
PASSAGE = "Run T04 of TP07 reached 12.4 bar chamber pressure."
REPLIES = {
    "query_analysis": {"intents": ["fact_lookup"], "test_plan_ids": ["TP07"]},
    "synthesis": {
        "answer_markdown": "TP07 T04 reached 12.4 bar [1].",
        "claims": [{"text": "TP07 T04 reached 12.4 bar", "kind": "numeric", "evidence_ids": ["E1"]}],
    },
    "verify": {"verdicts": [{"claim_index": 0, "verdict": "entailed", "reason": "stated"}]},
}


def count(directory: Path, name: str) -> None:
    with (directory / "calls.log").open("a") as log:
        log.write(f"{os.getpid()} {name}\n")


class Client:
    def __init__(self, directory: Path):
        self.directory = directory

    async def generate(self, *, model, messages, context, schema=None, **options):
        purpose = context.purpose.split(".")[1]
        count(self.directory, purpose)
        return GenerateResult(
            "", schema.model_validate(REPLIES[purpose]), (), Usage(1, 1), model, "stop", "r", 1
        )


def make_search(directory: Path):
    def search(session, args, *, embed_query, rerank):
        count(directory, "search_documents")
        marker = directory / "crashed"
        if not marker.exists():
            marker.write_text(str(os.getpid()))
            os._exit(9)  # the engine dies inside the tool step
        source = Source(
            doc_id=uuid.UUID("00000000-0000-4000-8000-000000000037"),
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

    return search


async def main(mode: str, directory: Path, url: str) -> None:
    wf.search_documents = make_search(directory)
    # no file database here: the catalog step finds nothing and there is no earlier turn
    wf.catalog.search_catalog = lambda session, question, vector, previous=None: wf.catalog.CatalogResult(
        question, wf.catalog.Labels(), [], [], [], previous
    )
    wf.catalog.previous_record = lambda session, chat, user: None
    deps = wf.EngineDeps(
        gemini=Client(directory),
        session_factory=contextlib.nullcontext,
        embed_query=lambda q: [0.0],
        rerank=None,
        alias_index=lambda session: AliasIndex(),
        save_trace=lambda trace: (directory / "trace.json").write_text(json.dumps(trace, default=str)),
    )
    runtime = wf.build_runtime(url, app_name=APP_NAME)
    workflow = wf.AnswerWorkflow(deps, runtime=runtime, workflow_name="answer", timeout=120)
    await runtime.launch()
    try:
        if mode == "start":
            trace_id = str(uuid.uuid4())
            handler = workflow.run(question="TP07 T04 pressure?", trace_id=trace_id)
            (directory / "run.json").write_text(json.dumps({"run_id": handler.run_id, "trace_id": trace_id}))
            await handler  # never returns: the search tool exits the process
            return
        from dbos import DBOS

        run_id = json.loads((directory / "run.json").read_text())["run_id"]
        status = None
        for _ in range(120):
            status = await DBOS.get_workflow_status_async(run_id)
            if status is not None and status.status in ("SUCCESS", "ERROR"):
                break
            await asyncio.sleep(0.5)
        output = status.output if status else None
        output = getattr(output, "result", output)  # the run's StopEvent; its result is the done payload
        (directory / "status.json").write_text(
            json.dumps(
                {
                    "status": status.status if status else None,
                    "output": output,
                    "type": type(output).__name__,
                },
                default=str,
            )
        )
    finally:
        await runtime.destroy()


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1], Path(sys.argv[2]), sys.argv[3]))
