"""The Gemini judge (file 08 §5.4): only for checks that need reading the answer — the conflict-behaviour
expectation and provenance labeling of library-vs-internal cases. Everything else is scored deterministically
in metrics.py. One call per check, through the gateway client, prompt `benchmark/judge.v1`."""

from pydantic import BaseModel

from backend.config import ThinkingLevel
from backend.llm_engine.gemini_types import CallContext, GeminiError, Message
from backend.llm_engine.model_ids import model_id
from backend.llm_engine.prompts import load_prompt

PROMPT = "judge.v1"


class JudgeVerdict(BaseModel):
    passed: bool
    rationale: str


async def judge(
    client, expectation: str, question: str, answer: str, sources: list[dict], *, trace_id=None
) -> dict:
    """`{passed, rationale}`; a gateway failure is a failed check with the error as rationale."""
    prompt = load_prompt("benchmark", PROMPT)
    listed = "\n".join(
        f"[{i}] {s.get('provenance') or 'unknown'} — {s.get('title') or s.get('label') or 'untitled'}"
        for i, s in enumerate(sources, 1)
    )
    try:
        reply = await client.generate(
            model=model_id(),
            messages=[
                Message.system(prompt.system),
                Message.user(
                    prompt.render_user(
                        expectation=expectation, question=question, sources=listed or "(none)", answer=answer
                    )
                ),
            ],
            context=CallContext(purpose="benchmark.judge", prompt_version=PROMPT, trace_id=trace_id),
            schema=JudgeVerdict,
            thinking=ThinkingLevel.LOW,
            temperature=0.0,
        )
    except GeminiError as exc:
        return {"passed": False, "rationale": f"judge unavailable: {str(exc)[:200]}"}
    verdict: JudgeVerdict = reply.parsed
    return verdict.model_dump()
