"""Model proposals for review flags (file 06 §5): when the route's deterministic hints are silent, one Gemini
call proposes and a person decides. A proposal is never applied by itself: its confidence is capped below the
auto-apply line and it is marked ``proposed_by = llm``. The tier per task is the one plan task 5 measured
(``docs/architecture/research/suggestion_models.md``).
"""

from pydantic import BaseModel, ConfigDict, Field

from backend.common.units import UnitError, parse_unit
from backend.config import ThinkingLevel
from backend.dispatcher.contract import SetUnit, Suggestion, UnitTelemetryEvidence
from backend.llm_engine.gemini_types import CallContext, Message
from backend.llm_engine.model_ids import Tier, model_id
from backend.llm_engine.prompts import load_prompt
from backend.postgres.enums import GaugeOrAbs, Quantity

UNIT_PROMPT = "unit.v1"
UNIT_PURPOSE = "suggest.unit"
UNIT_TIER = Tier.FLASH  # plan task 5 (2026-10-24): lite answered 2 of 24, flash 16 of 24
MAX_CONFIDENCE = 0.5  # a model proposal never reaches the 0.9 auto-apply line (file 06 §5)


class UnitProposal(BaseModel):
    model_config = ConfigDict(extra="ignore")

    quantity: str | None = Field(default=None, description="one of the listed quantity names, or null")
    unit: str | None = None
    gauge_or_abs: str | None = Field(default=None, description="gauge, absolute, unknown or n/a")
    confidence: float = 0.0
    rationale: str = ""


def _enum(kind, value: str | None):
    """A model's free string as the enum member it names, or None (the reply schema takes plain strings so one
    odd value never fails the whole proposal)."""
    try:
        return kind((value or "").strip().casefold()) if value else None
    except ValueError:
        return None


def _evidence_text(evidence: UnitTelemetryEvidence) -> str:
    stats = evidence.stats
    lines = [
        f"values: min {stats.min}, max {stats.max}, mean {stats.mean}, n {stats.n}",
        f"quantity guessed by the route: {evidence.quantity_guess or 'none'}",
    ]
    if evidence.scaling_equation:
        lines.append(
            f"scaling in {evidence.scaling_source or 'the folder .cfg'}: {evidence.scaling_equation}"
        )
    if evidence.header_lines:
        lines.append("header lines: " + " | ".join(evidence.header_lines[:5]))
    for sibling in evidence.sibling_units[:12]:
        lines.append(f"{sibling.file_name} states {sibling.channel} in {sibling.unit}")
    if evidence.note:
        lines.append(evidence.note)
    return "\n".join(lines)


def propose_unit(
    client,
    evidence: UnitTelemetryEvidence,
    *,
    file_name: str,
    folder: str,
    model: str | None = None,
    doc_id: str | None = None,
) -> Suggestion:
    """One model proposal for a column's unit (``model`` overrides the measured tier, for the study)."""
    prompt = load_prompt("suggest", UNIT_PROMPT)
    user = prompt.render_user(
        file_name=file_name, folder=folder, channel=evidence.channel, evidence=_evidence_text(evidence)
    )
    model = model or model_id(UNIT_TIER)
    result = client.generate_sync(
        model=model,
        messages=[Message.system(prompt.system), Message.user(user)],
        context=CallContext(
            purpose=UNIT_PURPOSE, prompt_version=UNIT_PROMPT, doc_id=doc_id, node_anchor=None
        ),
        schema=UnitProposal,
        thinking=ThinkingLevel.MINIMAL
        if model == model_id(Tier.LITE)
        else ThinkingLevel.LOW,  # flash: no minimal
        temperature=0.0,
    )
    proposal: UnitProposal = result.parsed
    rationale = f"model proposal ({result.model or model}): {proposal.rationale}".strip()
    quantity = _enum(Quantity, proposal.quantity)
    if not proposal.unit or quantity is None:
        return Suggestion(resolution=None, confidence=0, rationale=rationale, proposed_by="llm")
    try:
        parsed = parse_unit(proposal.unit)
    except UnitError:
        return Suggestion(resolution=None, confidence=0, rationale=rationale, proposed_by="llm")
    gauge = _enum(GaugeOrAbs, proposal.gauge_or_abs) or parsed.gauge_or_abs
    return Suggestion(
        resolution=SetUnit(
            channel=evidence.channel, unit=proposal.unit, quantity=quantity.value, gauge_or_abs=gauge
        ),
        confidence=max(0.0, min(proposal.confidence, MAX_CONFIDENCE)),
        rationale=rationale,
        proposed_by="llm",
    )
