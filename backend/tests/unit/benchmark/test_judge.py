"""The Gemini judge: one structured call per check with its prompt version; an outage fails the check."""

import asyncio

from backend.benchmark.judge import PROMPT, judge
from backend.llm_engine.gemini_types import GatewayError, GenerateResult, Usage


class Client:
    def __init__(self, reply):
        self.reply, self.calls = reply, []

    async def generate(self, *, model, messages, context, schema=None, **options):
        self.calls.append((messages, context, options))
        if isinstance(self.reply, Exception):
            raise self.reply
        parsed = schema.model_validate(self.reply)
        return GenerateResult("", parsed, (), Usage(1, 1), model, "stop", "r", 1)


def test_the_judge_reads_the_answer_and_its_sources():
    client = Client({"passed": True, "rationale": "states TP6 (sheet) and TP7 (folder)"})
    sources = [{"provenance": "internal_report", "title": "Run sheet"}]
    verdict = asyncio.run(
        judge(client, "must_present_both_conflicting_values", "Which plan?", "TP6 or TP7", sources)
    )
    assert verdict == {"passed": True, "rationale": "states TP6 (sheet) and TP7 (folder)"}
    [(messages, context, options)] = client.calls
    assert context.purpose == "benchmark.judge" and context.prompt_version == PROMPT
    user = messages[1].parts[0].text
    assert "[1] internal_report — Run sheet" in user and "TP6 or TP7" in user
    assert options["temperature"] == 0.0


def test_a_gateway_outage_is_a_failed_check_not_a_crash():
    verdict = asyncio.run(judge(Client(GatewayError("502")), "provenance_labeling", "q", "a", []))
    assert verdict["passed"] is False and "judge unavailable" in verdict["rationale"]
