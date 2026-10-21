import json

import httpx
import pytest

from backend import config
from backend.config import Settings
from backend.llm_engine import gemini_probe
from backend.llm_engine.gemini_client import Capabilities, Capability, CapabilityStatus

KEY = "probe-key-never-printed-987"
URL = "https://gateway.manastu.test/v1"
USAGE = {"prompt_tokens": 40, "completion_tokens": 5}


@pytest.fixture(autouse=True)
def no_google_key(monkeypatch):
    for name in config.FORBIDDEN_NAMES:
        monkeypatch.delenv(name, raising=False)


def reply(content=None, tool_calls=None, reasoning_tokens=0):
    message = {"role": "assistant", "content": content}
    if tool_calls:
        message["tool_calls"] = tool_calls
    usage = {**USAGE, "completion_tokens_details": {"reasoning_tokens": reasoning_tokens}}
    return httpx.Response(
        200, json={"id": "p", "choices": [{"message": message, "finish_reason": "stop"}], "usage": usage}
    )


def full_gateway(request: httpx.Request) -> httpx.Response:
    body = json.loads(request.content)
    if body.get("stream"):
        chunks = [{"choices": [{"delta": {"content": f"{i}, "}}]} for i in range(1, 4)]
        chunks.append({"choices": [], "usage": USAGE})
        text = "".join(f"data: {json.dumps(c)}\n\n" for c in chunks) + "data: [DONE]\n\n"
        return httpx.Response(200, text=text, headers={"content-type": "text/event-stream"})
    if "response_format" in body:
        return reply('{"city": "Tokyo", "population_millions": 37.1}')
    if "tools" in body:
        call = {
            "id": "c1",
            "type": "function",
            "function": {"name": "get_run_peak", "arguments": '{"run_id": "HT-042"}'},
        }
        return reply(tool_calls=[call])
    content = body["messages"][-1]["content"]
    if isinstance(content, list):
        kinds = {part["type"] for part in content}
        return reply("4217" if "file" in kinds else "Red")
    if body.get("extra_body", {}).get("google", {}).get("thinking_config"):
        return reply("<thought>check divisors</thought>yes", reasoning_tokens=50)
    if body.get("reasoning_effort") == "high":
        return reply("yes", reasoning_tokens=50)
    return reply("OK")


def settings() -> Settings:
    return Settings(_env_file=None, GEMINI_BACKEND="gateway", GEMINI_GATEWAY_URL=URL, GEMINI_GATEWAY_KEY=KEY)


async def test_probe_against_full_gateway_writes_capabilities(tmp_path):
    path = tmp_path / "caps.json"
    document = await gemini_probe.run(
        True,
        "gemini-3.8-flash",
        "gemini-3.5-flash-lite",
        path=path,
        settings=settings(),
        transport=httpx.MockTransport(full_gateway),
    )
    caps = document["capabilities"]
    supported = {name for name, entry in caps.items() if entry["status"] == CapabilityStatus.SUPPORTED}
    assert supported == {
        "structured_output",
        "function_calling",
        "thinking_level",
        "include_thoughts",
        "image_input",
        "pdf_input",
        "streaming",
        "stream_usage",
    }
    assert caps["media_resolution"]["status"] == "inconclusive"
    assert caps["context_cache"]["status"] == "unknown"
    assert caps["batch"]["status"] == "unknown"
    assert document["baseline"]["plain_chat"]["status"] == "supported"
    written = path.read_text()
    assert KEY not in written and URL not in written
    loaded = Capabilities.load(path)
    assert Capability.STRUCTURED_OUTPUT in loaded.enabled
    assert Capability.CONTEXT_CACHE not in loaded.enabled
    table = gemini_probe.to_markdown(document)
    assert "| structured_output | supported |" in table
    assert KEY not in table


async def test_probe_records_rejected_capabilities_as_unsupported(tmp_path):
    def strict_gateway(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if "response_format" in body or "tools" in body:
            return httpx.Response(400, json={"error": {"message": "Unknown field"}})
        if isinstance(body["messages"][-1]["content"], list):
            return httpx.Response(422, json={"error": {"message": "multimodal input not allowed"}})
        return full_gateway(request)

    path = tmp_path / "caps.json"
    document = await gemini_probe.run(
        True, "m", "lite", path=path, settings=settings(), transport=httpx.MockTransport(strict_gateway)
    )
    caps = document["capabilities"]
    for name in ("structured_output", "function_calling", "image_input", "pdf_input"):
        assert caps[name]["status"] == "unsupported", name
    assert "HTTP 400" in caps["structured_output"]["evidence"]
    assert Capabilities.load(path).enabled.isdisjoint({Capability.STRUCTURED_OUTPUT, Capability.IMAGE_INPUT})


async def test_probe_does_not_write_when_plain_chat_fails(tmp_path):
    path = tmp_path / "caps.json"
    path.write_text("{}")
    down = httpx.MockTransport(lambda request: httpx.Response(401, json={"error": {"message": "bad key"}}))
    with pytest.raises(SystemExit, match="plain chat failed"):
        await gemini_probe.run(True, "m", "lite", path=path, settings=settings(), transport=down)
    assert path.read_text() == "{}"


def test_tiny_pdf_and_png_are_well_formed():
    pdf = gemini_probe.tiny_pdf("CODE 4217")
    assert pdf.startswith(b"%PDF-1.4") and pdf.rstrip().endswith(b"%%EOF")
    xref_at = int(pdf.rsplit(b"startxref\n", 1)[1].split(b"\n")[0])
    assert pdf[xref_at:].startswith(b"xref")
    png = gemini_probe.tiny_png()
    assert png.startswith(b"\x89PNG\r\n\x1a\n") and png.endswith(b"IEND\xaeB`\x82")
