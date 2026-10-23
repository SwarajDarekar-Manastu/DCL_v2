"""Steps 5 and 6 of the workflow (file 07 §7, §8): synthesis under the citation contract, then verification.

Evidence is numbered (`E1`, `E2`, …): each search hit is its own item, every other tool result is one item.
The model cites evidence ids, never anchors, so a citation can only point at a source a tool returned; code
maps the ids back to `Source`s. Verification has two parts: every numeric claim must match a value and unit
string of the evidence it cites (deterministic, `verifier.check_numeric_claims`), and every claim is judged
entailed / contradicted / not_supported by a separate call that sees only that claim's evidence. A
contradicted or unsupported claim triggers one re-synthesis with the verdicts; what still fails is removed
from the answer and named in the caveats.
"""

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, Field

from backend.config import ThinkingLevel
from backend.llm_engine.engine.tools import Source, ToolResult
from backend.llm_engine.engine.verifier import check_numeric_claim
from backend.llm_engine.gemini_types import CallContext, GeminiError, Message
from backend.llm_engine.model_ids import model_id
from backend.llm_engine.prompts import load_prompt

log = logging.getLogger(__name__)
SYNTHESIS_PROMPT = "synthesis.v1"
VERIFY_PROMPT = "verify.v1"
REPAIR_PROMPT = "repair.v1"
REPAIR_MAX_OUTPUT_TOKENS = 2048  # a repair is a few sentences; one stack repair ran 208 s / 4,198 tokens
EVIDENCE_CHARS = 9000


@dataclass(frozen=True)
class Evidence:
    id: str
    call_id: str
    tool: str
    text: str
    source: Source | None


def evidence_items(results: list[ToolResult]) -> list[Evidence]:
    items: list[Evidence] = []
    for result in results:
        hits = (result.result or {}).get("hits") if isinstance(result.result, dict) else None
        if hits:  # search results and external results: one evidence item per hit and source
            for hit, source in zip(hits, result.provenance, strict=False):
                items.append(
                    Evidence(
                        f"E{len(items) + 1}",
                        result.call_id,
                        result.tool,
                        hit["parent_text"][:EVIDENCE_CHARS],
                        source,
                    )
                )
        else:
            items.append(
                Evidence(
                    f"E{len(items) + 1}",
                    result.call_id,
                    result.tool,
                    result.display[:EVIDENCE_CHARS],
                    result.provenance[0] if result.provenance else None,
                )
            )
    return items


def render_evidence(items: list[Evidence]) -> str:
    blocks = []
    for item in items:
        source = item.source
        head = f"[{item.id}] {item.tool}"
        if source:
            marks = [str(source.provenance)]
            if source.language and source.language != "en":
                marks.append(f"language {source.language}")
            if source.needs_review:
                marks.append("⚠ unverified extraction")
            head += f" — {source.label} ({', '.join(marks)})"
        blocks.append(f"{head}\n<<<\n{item.text}\n>>>")
    return "\n\n".join(blocks)


class Claim(BaseModel):
    text: str
    kind: Literal["numeric", "factual", "inference"]
    evidence_ids: list[str] = []
    quote: str | None = None


class SynthesisOutput(BaseModel):
    answer_markdown: str
    claims: list[Claim] = []
    caveats: list[str] = []
    followups: list[str] = Field(default_factory=list, max_length=3)


class Verdict(BaseModel):
    claim_index: int
    verdict: Literal["entailed", "contradicted", "not_supported"]
    reason: str


class Verification(BaseModel):
    verdicts: list[Verdict] = []


@dataclass
class Answer:
    markdown: str
    claims: list[Claim]
    citations: list[Source]
    caveats: list[str]
    followups: list[str]
    verdicts: list[Verdict] = field(default_factory=list)
    numeric_mismatches: list[dict] = field(default_factory=list)
    passes: int = 1

    def summary(self) -> dict:
        counts = {
            v: sum(1 for d in self.verdicts if d.verdict == v)
            for v in ("entailed", "contradicted", "not_supported")
        }
        return {"claims": len(self.claims), **counts}


async def _synthesize(
    client,
    question: str,
    analysis: dict,
    items: list[Evidence],
    language: str,
    notes: str | None,
    trace_id: str | None,
) -> SynthesisOutput:
    prompt = load_prompt("engine", SYNTHESIS_PROMPT)
    user = prompt.render_user(
        question=question,
        analysis=json.dumps(analysis, default=str),
        evidence=render_evidence(items),
        language=language,
    )
    if notes:
        user += (
            f"\n\nThe verifier rejected these claims of your previous answer; fix or remove them:\n{notes}"
        )
    result = await client.generate(
        model=model_id(),
        messages=[Message.system(prompt.system), Message.user(user)],
        context=CallContext(purpose="engine.synthesis", prompt_version=SYNTHESIS_PROMPT, trace_id=trace_id),
        schema=SynthesisOutput,
        thinking=ThinkingLevel.HIGH,
    )
    return result.parsed


class RepairedClaim(BaseModel):
    index: int
    text: str | None = None
    evidence_ids: list[str] = []


class Repair(BaseModel):
    claims: list[RepairedClaim] = []


async def _repair(
    client,
    question: str,
    output: SynthesisOutput,
    rejected: dict[int, str],
    items: list[Evidence],
    language: str,
    trace_id: str | None,
) -> tuple[SynthesisOutput, set[int]]:
    """Only the rejected claims go back, each with its evidence items, at thinking MEDIUM (DECISIONS
    2026-10-23); the corrected sentence replaces the old one in place, a null removes it. Returns the
    patched output and the indexes of the claims that changed."""
    by_id = {e.id: e for e in items}
    blocks = []
    for i, reason in rejected.items():
        claim = output.claims[i]
        cited = [by_id[eid] for eid in claim.evidence_ids if eid in by_id] or items
        evidence = "\n".join(f"[{e.id}] {e.text}" for e in cited)
        blocks.append(f"Claim {i}: {claim.text}\nRejected because: {reason}\nEvidence:\n<<<\n{evidence}\n>>>")
    prompt = load_prompt("engine", REPAIR_PROMPT)
    try:
        result = await client.generate(
            model=model_id(),
            messages=[
                Message.system(prompt.system.replace("$language", language)),
                Message.user(prompt.render_user(question=question, claims="\n\n".join(blocks))),
            ],
            context=CallContext(purpose="engine.repair", prompt_version=REPAIR_PROMPT, trace_id=trace_id),
            schema=Repair,
            thinking=ThinkingLevel.MEDIUM,
            max_output_tokens=REPAIR_MAX_OUTPUT_TOKENS,
        )
    except GeminiError as exc:  # a cut or failed repair: the rejected claims are removed as before
        log.warning("repair of %s claims failed: %s", len(rejected), exc)
        return output, set()
    markdown, claims, changed = output.answer_markdown, list(output.claims), set()
    for fix in result.parsed.claims:
        if fix.index not in rejected or not 0 <= fix.index < len(claims) or not fix.text:
            continue
        old = claims[fix.index]
        markdown = markdown.replace(old.text, fix.text)
        claims[fix.index] = old.model_copy(
            update={"text": fix.text, "evidence_ids": fix.evidence_ids or old.evidence_ids}
        )
        changed.add(fix.index)
    return output.model_copy(update={"answer_markdown": markdown, "claims": claims}), changed


async def verify(client, claims: list[Claim], items: list[Evidence], trace_id: str | None) -> list[Verdict]:
    if not claims:
        return []
    by_id = {e.id: e for e in items}
    blocks = []
    for i, claim in enumerate(claims):
        cited = (
            "\n".join(f"[{eid}] {by_id[eid].text}" for eid in claim.evidence_ids if eid in by_id) or "(none)"
        )
        blocks.append(f"Claim {i}: {claim.text}\nEvidence:\n<<<\n{cited}\n>>>")
    prompt = load_prompt("engine", VERIFY_PROMPT)
    result = await client.generate(
        model=model_id(),
        messages=[
            Message.system(prompt.system),
            Message.user(prompt.render_user(claims="\n\n".join(blocks))),
        ],
        context=CallContext(purpose="engine.verify", prompt_version=VERIFY_PROMPT, trace_id=trace_id),
        schema=Verification,
        thinking=ThinkingLevel.LOW,
    )
    return result.parsed.verdicts


def numeric_mismatches(claims: list[Claim], items: list[Evidence]) -> list[dict]:
    """A numeric claim must match the value and unit strings of its cited evidence (all evidence if none)."""
    by_id = {e.id: e for e in items}
    out = []
    for i, claim in enumerate(claims):
        if claim.kind != "numeric":
            continue
        texts = [by_id[eid].text for eid in claim.evidence_ids if eid in by_id] or [e.text for e in items]
        for mismatch in check_numeric_claim(claim.text, texts):
            out.append(
                {"claim_index": i, "value": mismatch.value, "unit": mismatch.unit, "reason": mismatch.reason}
            )
    return out


def _rejected(output: SynthesisOutput, verdicts: list[Verdict], mismatches: list[dict]) -> dict[int, str]:
    bad = {v.claim_index: f"{v.verdict}: {v.reason}" for v in verdicts if v.verdict != "entailed"}
    for m in mismatches:
        bad.setdefault(
            m["claim_index"], f"number {m['value']} {m['unit'] or ''} is not in the cited evidence"
        )
    return {i: r for i, r in bad.items() if 0 <= i < len(output.claims)}


MARKER = re.compile(r"\s?\[(E\d+(?:\s*,\s*E\d+)*)\]")


def number_citations(markdown: str, claims: list[Claim], items: list[Evidence]) -> tuple[str, list[Source]]:
    """The answer's `[E3]` / `[E1, E4]` markers become `[1]` / `[1, 2]`, numbered by first appearance and
    matching the citation events one to one: the same source (document, anchor, label) is one number, a
    marker whose evidence has no source is dropped, and a source only claims cite (no marker) is appended."""
    by_id = {e.id: e for e in items}
    numbers: dict[tuple, int] = {}
    sources: list[Source] = []

    def number(eid: str) -> int | None:
        source = by_id[eid].source if eid in by_id else None
        if source is None:
            return None
        key = (source.doc_id, source.anchor, source.label)
        if key not in numbers:
            numbers[key] = len(sources) + 1
            sources.append(source)
        return numbers[key]

    def replace(match: re.Match) -> str:
        found = [number(e.strip()) for e in match.group(1).split(",")]
        kept = list(dict.fromkeys(n for n in found if n is not None))
        return f" [{', '.join(map(str, kept))}]" if kept else ""

    text = MARKER.sub(replace, markdown)
    for claim in claims:
        for eid in claim.evidence_ids:
            number(eid)
    return text, sources


async def answer(
    client,
    question: str,
    analysis: dict,
    results: list[ToolResult],
    *,
    language: str = "en",
    trace_id: str | None = None,
) -> Answer:
    items = evidence_items(results)
    output = await _synthesize(client, question, analysis, items, language, None, trace_id)
    verdicts = await verify(client, output.claims, items, trace_id)
    mismatches = numeric_mismatches(output.claims, items)
    rejected = _rejected(output, verdicts, mismatches)
    passes = 1
    if rejected:
        output, changed = await _repair(client, question, output, rejected, items, language, trace_id)
        if changed:
            order = sorted(changed)
            fresh = await verify(client, [output.claims[i] for i in order], items, trace_id)
            renumbered = {
                order[v.claim_index]: v.model_copy(update={"claim_index": order[v.claim_index]})
                for v in fresh
                if 0 <= v.claim_index < len(order)
            }
            verdicts = [renumbered.get(v.claim_index, v) for v in verdicts if v.claim_index not in changed]
            verdicts += list(renumbered.values())
            verdicts.sort(key=lambda v: v.claim_index)
        mismatches = numeric_mismatches(output.claims, items)
        rejected = _rejected(output, verdicts, mismatches)
        passes = 2
    markdown, caveats = output.answer_markdown, list(output.caveats)
    kept = []
    for i, claim in enumerate(output.claims):
        if i in rejected:
            markdown = markdown.replace(claim.text, "").strip()
            caveats.append(f"Removed because it could not be verified against the sources: {claim.text}")
        else:
            kept.append(claim)
    markdown, citations = number_citations(markdown, kept, items)
    return Answer(
        markdown=markdown,
        claims=kept,
        citations=citations,
        caveats=caveats,
        followups=output.followups,
        verdicts=verdicts,
        numeric_mismatches=mismatches,
        passes=passes,
    )
