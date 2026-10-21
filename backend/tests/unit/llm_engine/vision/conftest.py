import json

import httpx
import pytest

from backend.config import Settings
from backend.llm_engine.gemini_client import GeminiClient
from backend.llm_engine.gemini_types import Capabilities
from backend.llm_engine.vision.service import VisionService

URL = "https://gateway.manastu.test/v1"


class MemoryCache:
    def __init__(self):
        self.objects: dict[str, bytes] = {}

    def get(self, key):
        return self.objects.get(key)

    def put(self, key, data):
        self.objects[key] = data


class Gateway:
    """Mock gateway: replies with the queued readings as OpenAI-compatible structured responses."""

    def __init__(self, *readings: dict | str):
        self.readings = list(readings)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        reading = self.readings.pop(0) if len(self.readings) > 1 else self.readings[0]
        content = reading if isinstance(reading, str) else json.dumps(reading)
        body = {
            "id": f"req-{len(self.requests)}",
            "model": json.loads(request.content)["model"],
            "choices": [
                {"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}
            ],
            "usage": {"prompt_tokens": 300, "completion_tokens": 40, "total_tokens": 340},
        }
        return httpx.Response(200, json=body, headers={"x-request-id": f"req-{len(self.requests)}"})

    @property
    def bodies(self) -> list[dict]:
        return [json.loads(r.content) for r in self.requests]


@pytest.fixture
def make_service():
    def build(*readings, capabilities=None):
        gateway = Gateway(*readings)
        ledger: list = []
        settings = Settings(
            _env_file=None, GEMINI_BACKEND="gateway", GEMINI_GATEWAY_URL=URL, GEMINI_GATEWAY_KEY="k" * 32
        )
        client = GeminiClient(
            settings,
            capabilities=capabilities or Capabilities.all(),
            ledger=ledger.append,
            transport=httpx.MockTransport(gateway),
            sleep=lambda _: None,
        )
        cache = MemoryCache()
        return VisionService(client, cache), gateway, ledger, cache

    return build
