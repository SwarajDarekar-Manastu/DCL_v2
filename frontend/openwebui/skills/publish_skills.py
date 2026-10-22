"""Publish the Answer Engine playbooks (file 07 §5) as Open WebUI Skills (admin API of Open WebUI v0.12.3).

Each folder here holds one `SKILL.md`: YAML front matter (`name`, `description`, `intents`, `tools`) and the
playbook text. The front matter's `tools` are checked against the engine's planner by
backend/tests/unit/llm_engine/engine/test_skills.py, so the published text says what the engine really does.

Run by a person once Open WebUI is up, with an admin API key (Settings › Account › API keys), from the
repository root:

    OWUI_API_KEY=sk-... uv run python frontend/openwebui/skills/publish_skills.py [--dry-run]

Every run is idempotent: a skill `dcl-<folder>` is created when absent and updated when present, active and
readable by every user. The skills are not attached to the engine model (see README.md). The API key is
never printed.
"""

import argparse
import os
import sys
from dataclasses import dataclass
from pathlib import Path

import httpx
import yaml

HERE = Path(__file__).resolve().parent
ID_PREFIX = "dcl-"
NAME_PREFIX = "DCL playbook: "
PUBLIC_READ = [{"principal_type": "user", "principal_id": "*", "permission": "read"}]


@dataclass(frozen=True)
class Skill:
    id: str
    name: str
    description: str
    content: str
    intents: tuple[str, ...]
    tools: tuple[str, ...]

    def form(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "content": self.content,
            "meta": {"tags": ["dcl", "playbook"]},
            "is_active": True,
            "access_grants": PUBLIC_READ,
        }


def parse(path: Path) -> Skill:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        raise ValueError(f"{path}: no front matter")
    head, body = text[4:].split("\n---\n", 1)
    meta = yaml.safe_load(head)
    return Skill(
        id=ID_PREFIX + path.parent.name,
        name=NAME_PREFIX + meta["name"],
        description=meta["description"],
        content=body.lstrip("\n"),
        intents=tuple(meta["intents"]),
        tools=tuple(meta["tools"]),
    )


def load_skills(root: Path = HERE) -> list[Skill]:
    return [parse(path) for path in sorted(root.glob("*/SKILL.md"))]


def _check(response: httpx.Response, what: str) -> dict:
    if response.status_code >= 400:
        try:
            detail = response.json().get("detail")
        except ValueError:
            detail = response.text[:200]
        raise SystemExit(f"{what} failed: HTTP {response.status_code} {detail}")
    return response.json() if response.content else {}


def publish(http: httpx.Client, skills: list[Skill], dry_run: bool = False, log=print) -> None:
    for skill in skills:
        current = http.get(f"/api/v1/skills/id/{skill.id}")
        exists = current.status_code == 200 and current.json() is not None
        log(f"{'update' if exists else 'create'} skill {skill.id} ({skill.name})")
        if dry_run:
            continue
        path = f"/api/v1/skills/id/{skill.id}/update" if exists else "/api/v1/skills/create"
        saved = _check(http.post(path, json=skill.form()), f"{'update' if exists else 'create'} {skill.id}")
        if not saved.get("is_active", True):
            log(f"activate skill {skill.id}")
            _check(http.post(f"/api/v1/skills/id/{skill.id}/toggle"), f"activate {skill.id}")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--dry-run", action="store_true", help="read the current state and print the plan only"
    )
    args = parser.parse_args(argv)
    api_key = os.environ.get("OWUI_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("set OWUI_API_KEY to an Open WebUI admin API key (Settings › Account › API keys)")
    url = os.environ.get("OWUI_URL")
    if not url:
        sys.path.insert(0, str(HERE.parents[2]))
        from backend.config import get_settings

        url = f"http://localhost:{get_settings().openwebui_port}"
    with httpx.Client(base_url=url, headers={"Authorization": f"Bearer {api_key}"}, timeout=30) as http:
        publish(http, load_skills(), dry_run=args.dry_run)
    print("done" if not args.dry_run else "dry run: nothing changed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
