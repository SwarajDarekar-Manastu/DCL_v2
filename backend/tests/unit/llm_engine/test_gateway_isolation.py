"""Only the gateway client may import a Google SDK or read the gateway URL (docs/architecture/01 §7)."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
SCANNED = [ROOT / "backend", ROOT / "frontend"]
SUFFIXES = {".py", ".ts", ".js", ".svelte", ".yaml", ".yml", ".toml"}
ALLOWED_URL_READERS = {
    "backend/config.py",
    "backend/llm_engine/gemini_client.py",
    "backend/llm_engine/gemini_probe.py",
}
GOOGLE_SDK = re.compile(
    r"^\s*(from|import)\s+(google\.genai|google\.generativeai|google\.ai|vertexai|google\.cloud\.aiplatform"
    r"|langchain_google|llama_index\.llms\.(gemini|vertex|google))\b|['\"]@google/(genai|generative-ai)['\"]",
    re.MULTILINE,
)
GATEWAY_URL = re.compile(
    r"GEMINI_GATEWAY_URL|gemini_gateway_url|GEMINI_GATEWAY_KEY|gemini_gateway_key|DCL_GEMINI_API_KEY"
)


def source_files():
    for base in SCANNED:
        for path in base.rglob("*"):
            if path.suffix in SUFFIXES and "node_modules" not in path.parts and "tests" not in path.parts:
                yield path


def test_no_module_imports_a_google_sdk():
    offenders = [
        str(p.relative_to(ROOT)) for p in source_files() if GOOGLE_SDK.search(p.read_text(errors="ignore"))
    ]
    assert offenders == []


def test_only_the_gateway_client_knows_the_gateway_url_and_key():
    offenders = [
        rel
        for p in source_files()
        if (rel := str(p.relative_to(ROOT))) not in ALLOWED_URL_READERS
        and GATEWAY_URL.search(p.read_text(errors="ignore"))
    ]
    assert offenders == []


def test_the_scan_sees_the_gateway_client():
    assert any(str(p.relative_to(ROOT)) == "backend/llm_engine/gemini_client.py" for p in source_files())
