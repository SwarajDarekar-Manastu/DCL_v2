"""Capability probe for the Manastu Gemini gateway (docs/architecture/09 §H.1).

Runs one minimal request per capability through GeminiClient with every capability forced on, records
supported / unsupported / inconclusive with short evidence, and writes gemini_capabilities.json so the client
enables only what the gateway passes through. The gateway URL and key never appear in the output.

    uv run python -m backend.llm_engine.gemini_probe            # print the table
    uv run python -m backend.llm_engine.gemini_probe --write    # also update gemini_capabilities.json
"""

import argparse
import asyncio
import json
import struct
import sys
import zlib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel

from backend.config import ThinkingLevel
from backend.llm_engine.gemini_client import (
    CAPABILITIES_FILE,
    CallContext,
    Capabilities,
    Capability,
    CapabilityStatus,
    GatewayError,
    GeminiClient,
    GeminiError,
    Image,
    Message,
    Pdf,
    StreamDone,
    TextDelta,
    ToolSpec,
)

DEFAULT_MODEL = "gemini-3.8-flash"
DEFAULT_LITE_MODEL = "gemini-3.5-flash-lite"
PDF_CODE = "4217"
CONTEXT = CallContext(purpose="gateway_probe", prompt_version="probe-v1")


@dataclass(frozen=True)
class ProbeResult:
    name: str
    status: CapabilityStatus
    evidence: str


class ProbeAnswer(BaseModel):
    city: str
    population_millions: float


def tiny_png(rgb: tuple[int, int, int] = (220, 20, 20), size: int = 8) -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + kind
            + data
            + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
        )

    row = b"\x00" + bytes(rgb) * size
    header = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(row * size))
        + chunk(b"IEND", b"")
    )


def tiny_pdf(text: str) -> bytes:
    stream = f"BT /F1 24 Tf 72 720 Td ({text}) Tj ET".encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{offset:010d} 00000 n \n".encode() for offset in offsets)
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)


def _from_error(name: str, exc: Exception) -> ProbeResult:
    if isinstance(exc, GatewayError) and exc.status_code in (400, 404, 405, 415, 422, 501):
        return ProbeResult(name, CapabilityStatus.UNSUPPORTED, str(exc))
    return ProbeResult(name, CapabilityStatus.INCONCLUSIVE, f"{type(exc).__name__}: {exc}")


async def _check(name: str, run: Callable[[], Awaitable[ProbeResult]]) -> ProbeResult:
    try:
        return await run()
    except (GeminiError, ValueError, KeyError) as exc:
        return _from_error(name, exc)


async def probe(client: GeminiClient, model: str = DEFAULT_MODEL, lite_model: str = DEFAULT_LITE_MODEL):
    """Returns (baseline results, capability results). The client must be built with Capabilities.all()."""
    say_ok = [Message.user("Reply with the single word OK.")]

    async def plain(probe_model: str, name: str) -> ProbeResult:
        result = await client.generate(
            model=probe_model, messages=say_ok, context=CONTEXT, max_output_tokens=16
        )
        usage = result.usage
        evidence = (
            f"reply {result.text.strip()[:20]!r}; tokens in/out {usage.input_tokens}/{usage.output_tokens}"
        )
        if usage.input_tokens == 0:
            return ProbeResult(name, CapabilityStatus.INCONCLUSIVE, evidence + "; no usage reported")
        return ProbeResult(name, CapabilityStatus.SUPPORTED, evidence)

    async def structured() -> ProbeResult:
        result = await client.generate(
            model=model,
            messages=[Message.user("Give the largest city of Japan and its population in millions.")],
            context=CONTEXT,
            schema=ProbeAnswer,
        )
        return ProbeResult(
            Capability.STRUCTURED_OUTPUT, CapabilityStatus.SUPPORTED, f"parsed {result.parsed!r}"
        )

    async def tools() -> ProbeResult:
        spec = ToolSpec(
            name="get_run_peak",
            description="Peak chamber pressure of a test run.",
            parameters={
                "type": "object",
                "properties": {"run_id": {"type": "string"}},
                "required": ["run_id"],
            },
        )
        result = await client.generate(
            model=model,
            messages=[Message.user("What was the peak chamber pressure of run HT-042? Use the tool.")],
            context=CONTEXT,
            tools=[spec],
            tool_choice="required",
        )
        if result.tool_calls and result.tool_calls[0].name == spec.name:
            return ProbeResult(
                Capability.FUNCTION_CALLING,
                CapabilityStatus.SUPPORTED,
                f"tool call {result.tool_calls[0].arguments}",
            )
        return ProbeResult(Capability.FUNCTION_CALLING, CapabilityStatus.UNSUPPORTED, "no tool call returned")

    async def thinking() -> ProbeResult:
        low = await client.generate(model=model, messages=say_ok, context=CONTEXT, thinking=ThinkingLevel.LOW)
        high = await client.generate(
            model=model,
            messages=[Message.user("Is 1,000,003 prime? Answer yes or no.")],
            context=CONTEXT,
            thinking=ThinkingLevel.HIGH,
        )
        evidence = (
            f"accepted; reasoning tokens low={low.usage.thinking_tokens} high={high.usage.thinking_tokens}"
        )
        status = CapabilityStatus.SUPPORTED if high.usage.thinking_tokens else CapabilityStatus.INCONCLUSIVE
        return ProbeResult(Capability.THINKING_LEVEL, status, evidence)

    async def thoughts() -> ProbeResult:
        result = await client.generate(
            model=model,
            messages=[Message.user("Is 1,000,003 prime? Answer yes or no.")],
            context=CONTEXT,
            thinking=ThinkingLevel.HIGH,
            include_thoughts=True,
        )
        if result.thoughts:
            return ProbeResult(
                Capability.INCLUDE_THOUGHTS, CapabilityStatus.SUPPORTED, "thought text returned"
            )
        return ProbeResult(
            Capability.INCLUDE_THOUGHTS, CapabilityStatus.INCONCLUSIVE, "accepted; no thoughts"
        )

    async def image() -> ProbeResult:
        result = await client.generate(
            model=model,
            messages=[Message.user("Name the single color of this image in one word.", Image(tiny_png()))],
            context=CONTEXT,
        )
        ok = "red" in result.text.lower()
        status = CapabilityStatus.SUPPORTED if ok else CapabilityStatus.INCONCLUSIVE
        return ProbeResult(Capability.IMAGE_INPUT, status, f"reply {result.text.strip()[:30]!r}")

    async def media_resolution() -> ProbeResult:
        await client.generate(
            model=model,
            messages=[Message.user("Name the color in one word.", Image(tiny_png()))],
            context=CONTEXT,
            media_resolution="high",
        )
        return ProbeResult(
            Capability.MEDIA_RESOLUTION, CapabilityStatus.INCONCLUSIVE, "accepted; effect not observable"
        )

    async def pdf() -> ProbeResult:
        result = await client.generate(
            model=model,
            messages=[
                Message.user("Return only the number printed in this PDF.", Pdf(tiny_pdf(f"CODE {PDF_CODE}")))
            ],
            context=CONTEXT,
        )
        ok = PDF_CODE in result.text
        status = CapabilityStatus.SUPPORTED if ok else CapabilityStatus.INCONCLUSIVE
        return ProbeResult(Capability.PDF_INPUT, status, f"reply {result.text.strip()[:30]!r}")

    async def streaming() -> list[ProbeResult]:
        deltas, done = 0, None
        async for event in client.stream(
            model=model, messages=[Message.user("Count from 1 to 20, comma-separated.")], context=CONTEXT
        ):
            if isinstance(event, TextDelta):
                deltas += 1
            elif isinstance(event, StreamDone):
                done = event.result
        stream_status = CapabilityStatus.SUPPORTED if deltas > 1 else CapabilityStatus.INCONCLUSIVE
        usage_ok = done is not None and done.usage.input_tokens > 0
        return [
            ProbeResult(Capability.STREAMING, stream_status, f"{deltas} deltas"),
            ProbeResult(
                Capability.STREAM_USAGE,
                CapabilityStatus.SUPPORTED if usage_ok else CapabilityStatus.UNSUPPORTED,
                "usage in final chunk" if usage_ok else "no usage in stream",
            ),
        ]

    baseline = [
        await _check("plain_chat", lambda: plain(model, "plain_chat")),
        await _check("lite_model", lambda: plain(lite_model, "lite_model")),
    ]
    results = [
        await _check(Capability.STRUCTURED_OUTPUT, structured),
        await _check(Capability.FUNCTION_CALLING, tools),
        await _check(Capability.THINKING_LEVEL, thinking),
        await _check(Capability.INCLUDE_THOUGHTS, thoughts),
        await _check(Capability.IMAGE_INPUT, image),
        await _check(Capability.MEDIA_RESOLUTION, media_resolution),
        await _check(Capability.PDF_INPUT, pdf),
    ]
    try:
        results.extend(await streaming())
    except (GeminiError, ValueError, KeyError) as exc:
        results.append(_from_error(Capability.STREAMING, exc))
        results.append(ProbeResult(Capability.STREAM_USAGE, CapabilityStatus.UNKNOWN, "streaming failed"))
    results.append(
        ProbeResult(
            Capability.CONTEXT_CACHE,
            CapabilityStatus.UNKNOWN,
            "not testable through chat completions; needs the gateway's cache-creation endpoint",
        )
    )
    results.append(
        ProbeResult(
            Capability.BATCH, CapabilityStatus.UNKNOWN, "not probed; needs the gateway's Batch contract"
        )
    )
    return baseline, results


def to_document(baseline: list[ProbeResult], results: list[ProbeResult], model: str) -> dict:
    return {
        "probed_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "model": model,
        "baseline": {r.name: {"status": r.status, "evidence": r.evidence} for r in baseline},
        "capabilities": {r.name: {"status": r.status, "evidence": r.evidence} for r in results},
    }


def to_markdown(document: dict) -> str:
    lines = [
        f"Gateway capability probe, {document['probed_at']}, model `{document['model']}`",
        "",
        "| Check | Status | Evidence |",
        "|-------|--------|----------|",
    ]
    for section in ("baseline", "capabilities"):
        for name, entry in document[section].items():
            evidence = entry["evidence"].replace("|", "\\|")
            lines.append(f"| {name} | {entry['status']} | {evidence} |")
    return "\n".join(lines)


async def run(
    write: bool, model: str, lite_model: str, path: Path = CAPABILITIES_FILE, **client_kwargs
) -> dict:
    client = GeminiClient(capabilities=Capabilities.all(), max_attempts=2, **client_kwargs)
    try:
        baseline, results = await probe(client, model, lite_model)
    finally:
        await client.aclose()
    document = to_document(baseline, results, model)
    if write:
        if baseline[0].status != CapabilityStatus.SUPPORTED:
            raise SystemExit("plain chat failed; gemini_capabilities.json left unchanged")
        path.write_text(json.dumps(document, indent=2) + "\n")
    return document


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--write", action="store_true", help="update gemini_capabilities.json")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--lite-model", default=DEFAULT_LITE_MODEL)
    args = parser.parse_args(argv)
    document = asyncio.run(run(args.write, args.model, args.lite_model))
    sys.stdout.write(to_markdown(document) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
