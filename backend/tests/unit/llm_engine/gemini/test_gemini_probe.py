import json

import httpx
import pytest

from backend import config
from backend.config import Settings
from backend.llm_engine import gemini_probe
from backend.llm_engine.gemini_types import Capabilities, Capability, CapabilityStatus

KEY = "probe-key-never-printed-987"
URL = "https://gateway.manastu.test"


@pytest.fixture(autouse=True)
def no_google_key(monkeypatch):
    for name in config.FORBIDDEN_NAMES:
        monkeypatch.delenv(name, raising=False)


def usage(prompt=40, out=5, thoughts=0):
    return {"prompt_token_count": prompt, "candidates_token_count": out, "thoughts_token_count": thoughts}


def reply(parts, prompt=40, thoughts=0, parsed=None):
    body = {
        "candidates": [{"content": {"role": "model", "parts": parts}, "finish_reason": "STOP"}],
        "response_id": "resp-123",
        "model_version": "gemini-3.8-flash",
        "usage_metadata": usage(prompt=prompt, thoughts=thoughts),
        "quota": {"limit": 100, "remaining": 90, "used_today": 10},
    }
    if parsed is not None:
        body["parsed"] = parsed
    return httpx.Response(200, json=body)


def manastu_gateway(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if path == "/health":
        return httpx.Response(200, json={"status": "ok"})
    known = {"/models", "/usage", "/caches", "/generate", "/stream"}
    if path not in known:
        return httpx.Response(404, text="<html><title>404 Not Found</title></html>")
    if request.headers.get("x-api-key") != KEY:
        return httpx.Response(401, json={"error": "invalid or missing X-API-Key"})
    if request.method == "GET":
        return {
            "/models": httpx.Response(200, json={"default": "x", "generation": ["gemini-3.8-flash"]}),
            "/usage": httpx.Response(200, json={"limit": 100}),
            "/caches": httpx.Response(200, json={"caches": []}),
        }.get(path, httpx.Response(404, text="<html><title>404 Not Found</title></html>"))
    body = json.loads(request.content)
    config_sent = body.get("config", {})
    if path == "/stream":
        chunks = [{"candidates": [{"content": {"parts": [{"text": f"{i}, "}]}}]} for i in range(1, 4)]
        chunks.append({"done": True, "usage": {"total": 60}, "quota": {"remaining": 90}})
        return httpx.Response(200, text="".join(f"data: {json.dumps(c)}\n\n" for c in chunks))
    if "response_json_schema" in config_sent:
        return reply(
            [{"text": '{"city":"Tokyo","population_millions":37.1}'}],
            parsed={"city": "Tokyo", "population_millions": 37.1},
        )
    last = body["contents"][-1]["parts"]
    if "tools" in config_sent and "function_response" not in last[0]:
        call = {
            "function_call": {"name": "get_run_peak", "args": {"run_id": "HT-042"}, "id": "c1"},
            "thought_signature": "s",
        }
        return reply([call])
    if "function_response" in last[0]:
        return reply([{"text": "Peak was 31.2 bar."}])
    inline = [p for p in last if "inline_data" in p]
    if inline:
        level = inline[0].get("media_resolution", {}).get("level", "")
        if inline[0]["inline_data"]["mime_type"] == "application/pdf":
            return reply([{"text": "4217"}])
        return reply([{"text": "Red"}], prompt=260 if level.endswith("low") else 1100)
    thinking = config_sent.get("thinking_config", {})
    if thinking.get("thinking_level") == "high":
        return reply([{"text": "check divisors", "thought": True}, {"text": "no"}], thoughts=400)
    return reply([{"text": "OK"}], thoughts=10)


def settings(style="manastu") -> Settings:
    return Settings(
        _env_file=None,
        GEMINI_BACKEND="gateway",
        GEMINI_GATEWAY_URL=URL,
        GEMINI_GATEWAY_KEY=KEY,
        GEMINI_API_STYLE=style,
    )


async def test_probe_against_manastu_gateway_detects_style_and_writes_capabilities(tmp_path):
    path = tmp_path / "caps.json"
    document = await gemini_probe.run(
        True,
        "gemini-3.8-flash",
        "gemini-3.5-flash-lite",
        path=path,
        settings=settings(),
        transport=httpx.MockTransport(manastu_gateway),
    )
    assert document["api_style"] == {"configured": "manastu", "detected": "manastu"}
    discovery = document["discovery"]
    assert discovery["health"]["status"] == "supported"
    assert discovery["models_list_manastu"]["status"] == "supported"
    assert discovery["models_list_gemini"]["evidence"] == "GET /v1beta/models: endpoint missing"
    assert discovery["models_list_openai"]["evidence"] == "GET /models: key rejected"
    caps = document["capabilities"]
    supported = {name for name, entry in caps.items() if entry["status"] == CapabilityStatus.SUPPORTED}
    assert supported == {
        "structured_output",
        "function_calling",
        "thinking_level",
        "include_thoughts",
        "image_input",
        "media_resolution",
        "pdf_input",
        "streaming",
    }
    assert caps["stream_usage"]["status"] == "inconclusive"
    assert caps["batch"]["status"] == "unsupported"
    assert caps["context_cache"]["status"] == "inconclusive"
    assert document["baseline"]["request_id"]["status"] == "supported"
    written = path.read_text()
    assert KEY not in written and URL not in written
    loaded = Capabilities.load(path)
    assert Capability.STRUCTURED_OUTPUT in loaded.enabled and Capability.BATCH not in loaded.enabled
    table = gemini_probe.to_markdown(document)
    assert "| structured_output | supported |" in table and KEY not in table


async def test_probe_reports_a_style_mismatch(tmp_path):
    document = await gemini_probe.run(
        False,
        "m",
        "lite",
        path=tmp_path / "c.json",
        settings=settings("gemini"),
        transport=httpx.MockTransport(manastu_gateway),
    )
    assert document["api_style"]["detected"] == "manastu"
    assert document["discovery"]["api_style"]["status"] == "unsupported"
    assert "set it to manastu" in document["discovery"]["api_style"]["evidence"]
    assert "HTML page: 404 Not Found" in document["capabilities"]["structured_output"]["evidence"]


async def test_probe_does_not_write_when_plain_chat_fails(tmp_path):
    path = tmp_path / "caps.json"
    path.write_text("{}")
    rejected = httpx.MockTransport(
        lambda request: httpx.Response(401, json={"error": "invalid or missing X-API-Key"})
    )
    with pytest.raises(SystemExit, match="plain chat failed"):
        await gemini_probe.run(True, "m", "lite", path=path, settings=settings(), transport=rejected)
    assert path.read_text() == "{}"


def test_tiny_pdf_and_png_are_well_formed():
    pdf = gemini_probe.tiny_pdf("CODE 4217")
    assert pdf.startswith(b"%PDF-1.4") and pdf.rstrip().endswith(b"%%EOF")
    xref_at = int(pdf.rsplit(b"startxref\n", 1)[1].split(b"\n")[0])
    assert pdf[xref_at:].startswith(b"xref")
    png = gemini_probe.tiny_png()
    assert png.startswith(b"\x89PNG\r\n\x1a\n") and png.endswith(b"IEND\xaeB`\x82")
