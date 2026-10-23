"""On-the-fly translation for the viewer (file 04 §10, `translation.mode = enrichment_only`; file 08 §6).

In `enrichment_only` mode node content stays in its language; when a reader turns on "Translate" for a
non-English page or passage, `translate_passages` asks Gemini (gateway, `GEMINI_MODEL`, prompt
`enrichment/translate.v1`) for the missing translations and caches each one as derived data keyed by the
content hash, so a passage is paid for once
(`dcl-cir/_translation_cache/{model}/{prompt}/{target}/{sha}.json`).
Translations are never cited: a citation points to the original node, the quote says "translated from …".
Content under a root without cloud permission is never sent (`TranslationRefused`).
"""

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from pydantic import BaseModel

from backend.config import ThinkingLevel
from backend.llm_engine.gemini_types import CallContext, Message
from backend.llm_engine.model_ids import model_id
from backend.llm_engine.prompts import load_prompt

PROMPT = "translate.v1"
CACHE_PREFIX = "_translation_cache"
MAX_PASSAGES = 60
LANGUAGE_NAMES = {
    "en": "English",
    "de": "German",
    "fr": "French",
    "es": "Spanish",
    "it": "Italian",
    "ja": "Japanese",
    "zh": "Chinese",
    "ko": "Korean",
    "ru": "Russian",
    "hi": "Hindi",
}


class TranslationRefused(PermissionError):
    pass


class Cache(Protocol):
    def get(self, key: str) -> bytes | None: ...

    def put(self, key: str, data: bytes) -> object: ...


class Translations(BaseModel):
    translations: list[str]


@dataclass(frozen=True)
class Translated:
    source: str
    text: str
    cached: bool


def _key(model: str, target: str, text: str) -> str:
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return f"{CACHE_PREFIX}/{model}/{PROMPT}/{target}/{digest}.json"


def translate_passages(
    client,
    cache: Cache,
    passages: Sequence[str],
    *,
    source_language: str | None,
    target_language: str = "en",
    cloud_allowed: bool,
    doc_id: str | None = None,
) -> list[Translated]:
    """One translation per passage, from the cache where possible and one Gemini call for the rest."""
    model = model_id()
    out: list[Translated | None] = []
    missing: list[int] = []
    for i, text in enumerate(passages):
        if not text.strip() or source_language == target_language:
            out.append(Translated(text, text, True))
            continue
        hit = cache.get(_key(model, target_language, text))
        if hit is not None:
            out.append(Translated(text, json.loads(hit)["text"], True))
        else:
            out.append(None)
            missing.append(i)
    if missing and not cloud_allowed:
        raise TranslationRefused("this document's root may not be sent to Gemini; no translation is made")
    for start in range(0, len(missing), MAX_PASSAGES):
        batch = missing[start : start + MAX_PASSAGES]
        prompt = load_prompt("enrichment", PROMPT)
        target = LANGUAGE_NAMES.get(target_language, target_language)
        listed = "\n\n".join(f"[{n}]\n<<<\n{passages[i]}\n>>>" for n, i in enumerate(batch, start=1))
        reply = client.generate_sync(
            model=model,
            messages=[
                Message.system(prompt.system.replace("$target", target)),
                Message.user(
                    prompt.render_user(
                        source=LANGUAGE_NAMES.get(source_language or "", source_language or "unknown"),
                        passages=listed,
                    )
                ),
            ],
            context=CallContext(purpose="enrichment.translate", prompt_version=PROMPT, doc_id=doc_id),
            schema=Translations,
            thinking=ThinkingLevel.LOW,
            temperature=0.0,
        )
        texts = reply.parsed.translations
        if len(texts) != len(batch):
            raise ValueError(f"translation returned {len(texts)} passages for {len(batch)}")
        for i, text in zip(batch, texts, strict=True):
            entry = {
                "text": text,
                "model": reply.model or model,
                "source_language": source_language,
                "cached_at": datetime.now(UTC).isoformat(),
            }
            cache.put(
                _key(model, target_language, passages[i]), json.dumps(entry, ensure_ascii=False).encode()
            )
            out[i] = Translated(passages[i], text, False)
    return [t for t in out if t is not None]
