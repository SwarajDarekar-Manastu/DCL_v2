"""Capability probe for the Gemini gateway (docs/architecture/09 §H.1).

1. Discovery: `GET /health` without credentials, then the model-list endpoint of every API style with that
   style's auth header. Each is reported as ok, "key rejected" (401/403) or "endpoint missing" (404/405), and
   the style whose list answers is recorded as the detected style.
2. Capabilities: one minimal request per capability through GeminiClient (configured style, every capability
   forced on), recorded as supported / unsupported / inconclusive / unknown with short evidence.
3. With --write, gemini_capabilities.json is replaced so the client enables only what was confirmed.

The gateway URL and key never appear in the output.

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

import httpx
from pydantic import BaseModel

from backend.config import ApiStyle, Group, Settings, ThinkingLevel, get_settings
from backend.llm_engine.gemini_adapters import ADAPTERS
from backend.llm_engine.gemini_client import GeminiClient
from backend.llm_engine.gemini_types import (
    CAPABILITIES_FILE,
    CallContext,
    Capabilities,
    Capability,
    CapabilityStatus,
    GatewayError,
    GeminiError,
    Image,
    Message,
    Pdf,
    StreamDone,
    TextDelta,
    ToolSpec,
)

DEFAULT_MODEL = "gemini-3.8-flash"
DEFAULT_LITE_MODEL = "gemini-3.1-flash-lite"
PDF_CODE = "4217"
CONTEXT = CallContext(purpose="gateway_probe", prompt_version="probe-v2")
MISSING = (404, 405)
REJECTED = (401, 403)
S = CapabilityStatus


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


def _http_status(code: int) -> str:
    if code in REJECTED:
        return "key rejected"
    if code in MISSING:
        return "endpoint missing"
    return "ok" if 200 <= code < 300 else f"HTTP {code}"


def _list_style(body: object) -> ApiStyle | None:
    if isinstance(body, dict):
        if "generation" in body:
            return ApiStyle.MANASTU
        if isinstance(body.get("models"), list):
            return ApiStyle.GEMINI
        if isinstance(body.get("data"), list):
            return ApiStyle.OPENAI
    return None


async def discover(settings: Settings, transport: httpx.AsyncBaseTransport | None = None):
    """Returns (results, detected style or None)."""
    base = str(settings.gemini_gateway_url).rstrip("/")
    key = settings.gemini_gateway_key.get_secret_value()
    results, detected = [], None
    async with httpx.AsyncClient(base_url=base, timeout=20, transport=transport) as http:
        try:
            health = await http.get("/health")
            status = S.SUPPORTED if health.is_success else S.INCONCLUSIVE
            results.append(
                ProbeResult("health", status, f"{_http_status(health.status_code)} without credentials")
            )
        except httpx.HTTPError as exc:
            results.append(ProbeResult("health", S.INCONCLUSIVE, f"unreachable: {type(exc).__name__}"))
        for style, adapter in ADAPTERS.items():
            name = f"models_list_{style}"
            try:
                response = await http.get(adapter.models_path, headers=adapter.headers(key))
            except httpx.HTTPError as exc:
                results.append(ProbeResult(name, S.INCONCLUSIVE, f"unreachable: {type(exc).__name__}"))
                continue
            listed = None
            if response.is_success:
                try:
                    listed = _list_style(response.json())
                except ValueError:
                    listed = None
            if listed is style:
                detected = detected or style
                results.append(ProbeResult(name, S.SUPPORTED, f"GET {adapter.models_path}: ok"))
                continue
            evidence = f"GET {adapter.models_path}: {_http_status(response.status_code)}"
            if response.is_success:
                evidence += " (body not in this style)"
            status = (
                S.UNSUPPORTED if response.status_code in MISSING or response.is_success else S.INCONCLUSIVE
            )
            results.append(ProbeResult(name, status, evidence))
    return results, detected


def _from_error(name: str, exc: Exception) -> ProbeResult:
    if isinstance(exc, GatewayError) and exc.status_code in (400, 404, 405, 415, 422, 501):
        return ProbeResult(name, S.UNSUPPORTED, str(exc))
    if isinstance(exc, GatewayError) and exc.status_code == 502 and not exc.retryable:
        return ProbeResult(name, S.UNSUPPORTED, str(exc))
    return ProbeResult(name, S.INCONCLUSIVE, f"{type(exc).__name__}: {exc}")


async def _check(
    name: str, run: Callable[[], Awaitable[list[ProbeResult] | ProbeResult]]
) -> list[ProbeResult]:
    try:
        outcome = await run()
    except (GeminiError, ValueError, KeyError) as exc:
        return [_from_error(name, exc)]
    return outcome if isinstance(outcome, list) else [outcome]


async def _get_status(client: GeminiClient, path: str) -> int:
    return (await client._async.get(path)).status_code


async def probe(client: GeminiClient, model: str = DEFAULT_MODEL, lite_model: str = DEFAULT_LITE_MODEL):
    """Returns (baseline results, capability results). The client must be built with Capabilities.all()."""
    say_ok = [Message.user("Reply with the single word OK.")]
    low = ThinkingLevel.LOW

    async def plain(probe_model: str, name: str) -> list[ProbeResult]:
        result = await client.generate(model=probe_model, messages=say_ok, context=CONTEXT, thinking=low)
        usage = result.usage
        evidence = (
            f"reply {result.text.strip()[:20]!r}; tokens in/out {usage.input_tokens}/{usage.output_tokens}"
        )
        if usage.estimated:
            return [ProbeResult(name, S.INCONCLUSIVE, evidence + "; usage estimated")]
        return [ProbeResult(name, S.SUPPORTED, evidence)]

    async def request_id() -> ProbeResult:
        result = await client.generate(model=model, messages=say_ok, context=CONTEXT, thinking=low)
        own = bool(result.request_id) and len(result.request_id) != 36
        evidence = (
            "gateway returns its own id" if own else "none returned; the idempotency key is recorded instead"
        )
        return ProbeResult("request_id", S.SUPPORTED if own else S.INCONCLUSIVE, evidence)

    async def structured() -> ProbeResult:
        result = await client.generate(
            model=model,
            messages=[Message.user("Give the largest city of Japan and its population in millions.")],
            context=CONTEXT,
            schema=ProbeAnswer,
            thinking=low,
        )
        return ProbeResult(Capability.STRUCTURED_OUTPUT, S.SUPPORTED, f"parsed {result.parsed!r}")

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
        question = Message.user("What was the peak chamber pressure of run HT-042? Use the tool.")
        first = await client.generate(
            model=model,
            messages=[question],
            context=CONTEXT,
            tools=[spec],
            tool_choice="required",
            thinking=low,
        )
        if not first.tool_calls or first.tool_calls[0].name != spec.name:
            return ProbeResult(Capability.FUNCTION_CALLING, S.UNSUPPORTED, "no tool call returned")
        call = first.tool_calls[0]
        answer = await client.generate(
            model=model,
            messages=[
                question,
                Message.assistant(tool_calls=first.tool_calls),
                Message.tool_result(call.id, '{"peak_bar": 31.2}', name=call.name),
            ],
            context=CONTEXT,
            tools=[spec],
            thinking=low,
        )
        used = "31.2" in answer.text
        evidence = f"call {call.arguments}; round trip used the result: {used}"
        return ProbeResult(Capability.FUNCTION_CALLING, S.SUPPORTED if used else S.INCONCLUSIVE, evidence)

    async def thinking() -> list[ProbeResult]:
        question = [Message.user("Is 221 a prime number? Answer yes or no.")]
        low_result = await client.generate(model=model, messages=question, context=CONTEXT, thinking=low)
        high_result = await client.generate(
            model=model,
            messages=question,
            context=CONTEXT,
            thinking=ThinkingLevel.HIGH,
            include_thoughts=True,
        )
        lo, hi = low_result.usage.thinking_tokens, high_result.usage.thinking_tokens
        return [
            ProbeResult(
                Capability.THINKING_LEVEL,
                S.SUPPORTED if hi > lo else S.INCONCLUSIVE,
                f"thinking tokens low={lo} high={hi}",
            ),
            ProbeResult(
                Capability.INCLUDE_THOUGHTS,
                S.SUPPORTED if high_result.thoughts else S.INCONCLUSIVE,
                "thought text returned" if high_result.thoughts else "no thoughts returned",
            ),
        ]

    async def image() -> list[ProbeResult]:
        ask = "Name the single color of this image in one word."
        replies = {}
        for level in ("low", "high"):
            replies[level] = await client.generate(
                model=model,
                messages=[Message.user(Image(tiny_png(), media_resolution=level), ask)],
                context=CONTEXT,
                thinking=low,
            )
        seen = "red" in replies["high"].text.lower()
        lo, hi = replies["low"].usage.input_tokens, replies["high"].usage.input_tokens
        return [
            ProbeResult(
                Capability.IMAGE_INPUT,
                S.SUPPORTED if seen else S.INCONCLUSIVE,
                f"reply {replies['high'].text.strip()[:20]!r}",
            ),
            ProbeResult(
                Capability.MEDIA_RESOLUTION,
                S.SUPPORTED if lo < hi else S.INCONCLUSIVE,
                f"prompt tokens low={lo} high={hi}",
            ),
        ]

    async def pdf() -> ProbeResult:
        document = Pdf(tiny_pdf(f"CODE {PDF_CODE}"), media_resolution="medium")
        result = await client.generate(
            model=model,
            messages=[Message.user(document, "Return only the number printed in this PDF.")],
            context=CONTEXT,
            thinking=low,
        )
        ok = PDF_CODE in result.text
        return ProbeResult(
            Capability.PDF_INPUT,
            S.SUPPORTED if ok else S.INCONCLUSIVE,
            f"reply {result.text.strip()[:30]!r} (inline_data)",
        )

    async def streaming() -> list[ProbeResult]:
        deltas, done = 0, None
        async for event in client.stream(
            model=model,
            messages=[Message.user("Count from 1 to 40, comma-separated.")],
            context=CONTEXT,
            thinking=low,
        ):
            if isinstance(event, TextDelta):
                deltas += 1
            elif isinstance(event, StreamDone):
                done = event.result
        usage = done.usage if done else None
        if usage is None:
            usage_result = ProbeResult(Capability.STREAM_USAGE, S.UNSUPPORTED, "no usage in stream")
        elif usage.estimated:
            usage_result = ProbeResult(
                Capability.STREAM_USAGE, S.INCONCLUSIVE, f"total only ({usage.total_tokens}); split estimated"
            )
        else:
            usage_result = ProbeResult(Capability.STREAM_USAGE, S.SUPPORTED, "full usage in the final chunk")
        return [
            ProbeResult(
                Capability.STREAMING, S.SUPPORTED if deltas > 1 else S.INCONCLUSIVE, f"{deltas} deltas"
            ),
            usage_result,
        ]

    async def google_search() -> ProbeResult:
        result = await client.generate(
            model=model,
            messages=[
                Message.user(
                    "What is the latest stable release of the Python programming language? One sentence."
                )
            ],
            context=CONTEXT,
            thinking=low,
            google_search=True,
        )
        grounding = result.grounding
        if grounding and grounding.sources:
            evidence = f"{len(grounding.queries)} queries, {len(grounding.sources)} web sources"
            return ProbeResult(Capability.GOOGLE_SEARCH, S.SUPPORTED, evidence)
        return ProbeResult(Capability.GOOGLE_SEARCH, S.INCONCLUSIVE, "accepted; no grounding metadata")

    def endpoint(capability: Capability, path: str, note: str):
        async def check() -> ProbeResult:
            code = await _get_status(client, path)
            if code in MISSING:
                return ProbeResult(capability, S.UNSUPPORTED, f"GET {path}: endpoint missing")
            suffix = f"; {note}" if 200 <= code < 300 else ""
            return ProbeResult(capability, S.INCONCLUSIVE, f"GET {path}: {_http_status(code)}{suffix}")

        return check

    baseline = [
        *await _check("plain_chat", lambda: plain(model, "plain_chat")),
        *await _check("lite_model", lambda: plain(lite_model, "lite_model")),
        *await _check("request_id", request_id),
    ]
    if client.adapter.style is ApiStyle.MANASTU:
        code = await _get_status(client, "/usage")
        baseline.append(
            ProbeResult(
                "usage_endpoint",
                S.SUPPORTED if code == 200 else S.INCONCLUSIVE,
                f"GET /usage: {_http_status(code)}",
            )
        )
    results = [
        *await _check(Capability.STRUCTURED_OUTPUT, structured),
        *await _check(Capability.FUNCTION_CALLING, tools),
        *await _check(Capability.THINKING_LEVEL, thinking),
        *await _check(Capability.IMAGE_INPUT, image),
        *await _check(Capability.PDF_INPUT, pdf),
        *await _check(Capability.STREAMING, streaming),
        *await _check(Capability.GOOGLE_SEARCH, google_search),
        *await _check(
            Capability.CONTEXT_CACHE,
            endpoint(
                Capability.CONTEXT_CACHE,
                "/caches",
                "explicit cache creation not exercised; implicit caching needs no flag",
            ),
        ),
        *await _check(
            Capability.BATCH, endpoint(Capability.BATCH, "/batches", "batch submission not exercised")
        ),
    ]
    names = {r.name for r in results}
    results += [
        ProbeResult(c, S.UNKNOWN, "not checked (an earlier check failed)")
        for c in Capability
        if c not in names
    ]
    return baseline, results


def to_document(discovery, detected, configured, baseline, results, model: str) -> dict:
    def section(items):
        return {r.name: {"status": r.status, "evidence": r.evidence} for r in items}

    return {
        "probed_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "model": model,
        "api_style": {"configured": str(configured), "detected": str(detected) if detected else None},
        "discovery": section(discovery),
        "baseline": section(baseline),
        "capabilities": section(results),
    }


def to_markdown(document: dict) -> str:
    style = document["api_style"]
    lines = [
        f"Gateway capability probe, {document['probed_at']}, model `{document['model']}`, "
        f"style configured `{style['configured']}`, detected `{style['detected']}`",
        "",
        "| Check | Status | Evidence |",
        "|-------|--------|----------|",
    ]
    for part in ("discovery", "baseline", "capabilities"):
        for name, entry in document[part].items():
            evidence = str(entry["evidence"]).replace("|", "\\|")
            lines.append(f"| {name} | {entry['status']} | {evidence} |")
    return "\n".join(lines)


async def run(
    write: bool,
    model: str,
    lite_model: str,
    path: Path = CAPABILITIES_FILE,
    settings: Settings | None = None,
    **client_kwargs,
) -> dict:
    settings = (settings or get_settings()).require(Group.GEMINI)
    discovery, detected = await discover(settings, client_kwargs.get("transport"))
    configured = settings.gemini_api_style
    if detected is not None and detected is not configured:
        evidence = f"GEMINI_API_STYLE is {configured}, gateway answers as {detected}: set it to {detected}"
        discovery.append(ProbeResult("api_style", S.UNSUPPORTED, evidence))
    elif detected is not None:
        discovery.append(
            ProbeResult("api_style", S.SUPPORTED, f"configured {configured} matches the gateway")
        )
    client = GeminiClient(settings, capabilities=Capabilities.all(), max_attempts=2, **client_kwargs)
    try:
        baseline, results = await probe(client, model, lite_model)
    finally:
        await client.aclose()
    document = to_document(discovery, detected, settings.gemini_api_style, baseline, results, model)
    if write:
        if baseline[0].status != S.SUPPORTED:
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
