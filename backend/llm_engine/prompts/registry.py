"""Prompt registry for the Console's Settings › Prompts screen (file 08 §3.3) over the prompt files.

Prompts stay files (`<area>/<name>.v<N>.md`, this package's loader): the registry lists them with their
versions, shows one, diffs two versions of a name, and runs one version on a sample input with the configured
model (`GEMINI_MODEL`, or `GEMINI_LITE_MODEL` for the lite tier), the call logged under purpose
`console.prompt_preview`. A new version is a new file and a code change that pins it ("a new version applies
to new calls"); the screen does not write prompts. The highest version of a name is marked `latest`; callers
pin a version explicitly, and `in_use` lists the versions the code pins today.
"""

import difflib
import re
import time
from dataclasses import dataclass
from string import Template

from pydantic import BaseModel, Field

from backend.config import ThinkingLevel
from backend.llm_engine.gemini_types import CallContext, Image, Message
from backend.llm_engine.model_ids import Tier, model_id
from backend.llm_engine.prompts import PROMPTS_DIR, USER_MARKER, load_prompt

VERSIONED = re.compile(r"^(?P<name>[a-z0-9_]+)\.v(?P<n>\d+)$")
PIN_LITERAL = re.compile(r"[\"']([a-z0-9_]+\.v\d+)[\"']")
EXTRACT_CALL = re.compile(r"_extract\(\s*request,\s*\"([a-z0-9_]+)\"")
VARIABLE = re.compile(r"\$(?:\{(?P<b>[A-Za-z_]\w*)\}|(?P<n>[A-Za-z_]\w*))")


class PromptVersion(BaseModel):
    area: str
    name: str
    version: str
    number: int
    latest: bool
    in_use: bool
    variables: list[str]
    chars: int


class PromptText(PromptVersion):
    system: str
    user_template: str


class PromptDiff(BaseModel):
    area: str
    a: str
    b: str
    unified: str


class PromptRun(BaseModel):
    variables: dict[str, str] = Field(default_factory=dict)
    image_base64: str | None = Field(default=None, description="for vision prompts: one PNG or JPEG")
    tier: Tier = Tier.FLASH


class PromptRunResult(BaseModel):
    version: str
    model: str
    text: str
    latency_ms: int
    input_tokens: int | None = None
    output_tokens: int | None = None


class PromptNotFound(LookupError):
    pass


@dataclass(frozen=True)
class _File:
    area: str
    name: str
    number: int

    @property
    def version(self) -> str:
        return f"{self.name}.v{self.number}"


def _files() -> list[_File]:
    out = []
    for path in sorted(PROMPTS_DIR.glob("*/*.md")):
        match = VERSIONED.match(path.stem)
        if match:
            out.append(_File(path.parent.name, match["name"], int(match["n"])))
    return out


def pinned_versions() -> set[str]:
    """Versions the code pins today: every `"<name>.v<N>"` literal in the backend sources, plus the
    argument-extraction prompts the workflow names by stem (`_extract(request, "physics_args", …)`)."""
    backend = PROMPTS_DIR.parents[1]
    pins: set[str] = set()
    for path in backend.rglob("*.py"):
        if "tests" in path.parts:
            continue
        source = path.read_text(encoding="utf-8")
        pins |= set(PIN_LITERAL.findall(source))
        pins |= {f"{name}.v1" for name in EXTRACT_CALL.findall(source)}
    return pins


def _variables(text: str) -> list[str]:
    return sorted({m["b"] or m["n"] for m in VARIABLE.finditer(text)})


def list_prompts() -> list[PromptVersion]:
    files = _files()
    latest = {}
    for f in files:
        latest[(f.area, f.name)] = max(latest.get((f.area, f.name), 0), f.number)
    pins = pinned_versions()
    out = []
    for f in files:
        text = (PROMPTS_DIR / f.area / f"{f.version}.md").read_text(encoding="utf-8")
        out.append(
            PromptVersion(
                area=f.area,
                name=f.name,
                version=f.version,
                number=f.number,
                latest=latest[(f.area, f.name)] == f.number,
                in_use=f.version in pins,
                variables=_variables(text.split(USER_MARKER, 1)[-1]),
                chars=len(text),
            )
        )
    return out


def get_prompt(area: str, version: str) -> PromptText:
    entry = next((p for p in list_prompts() if p.area == area and p.version == version), None)
    if entry is None:
        raise PromptNotFound(f"no prompt {area}/{version}")
    prompt = load_prompt(area, version)
    return PromptText(**entry.model_dump(), system=prompt.system, user_template=prompt.user_template.template)


def diff_prompts(area: str, a: str, b: str) -> PromptDiff:
    known = {(f.area, f.version) for f in _files()}
    texts = []
    for version in (a, b):
        path = PROMPTS_DIR / area / f"{version}.md"
        if (area, version) not in known:
            raise PromptNotFound(f"no prompt {area}/{version}")
        texts.append(path.read_text(encoding="utf-8").splitlines(keepends=True))
    unified = "".join(difflib.unified_diff(texts[0], texts[1], fromfile=f"{area}/{a}", tofile=f"{area}/{b}"))
    return PromptDiff(area=area, a=a, b=b, unified=unified)


async def run_prompt(client, area: str, version: str, request: PromptRun, *, user: str) -> PromptRunResult:
    """One call with the prompt's system text and its user template filled from `variables` (missing ones
    stay as `$name`), plain text out, so any prompt can be previewed without its caller's schema."""
    get_prompt(area, version)  # 404 for an unknown version
    prompt = load_prompt(area, version)
    user_text = Template(prompt.user_template.template).safe_substitute(request.variables)
    parts: list = [user_text]
    if request.image_base64:
        import base64

        data = base64.b64decode(request.image_base64)
        parts.append(Image(data, "image/png" if data[:4] == b"\x89PNG" else "image/jpeg"))
    model = model_id(request.tier)
    started = time.monotonic()
    result = await client.generate(
        model=model,
        messages=[Message.system(prompt.system), Message.user(*parts)],
        context=CallContext(purpose="console.prompt_preview", prompt_version=version, trace_id=None),
        thinking=ThinkingLevel.LOW,
    )
    return PromptRunResult(
        version=version,
        model=result.model or model,
        text=result.text,
        latency_ms=int((time.monotonic() - started) * 1000),
        input_tokens=result.usage.input_tokens,
        output_tokens=result.usage.output_tokens,
    )
