"""Install or update the DCL functions in the stack's Open WebUI (admin API of Open WebUI v0.12.3).

Run by a person, after creating the first Open WebUI admin account in the browser and an API key
(Settings › Account › API keys). From the repository root:

    OWUI_API_KEY=sk-... uv run python frontend/openwebui/install_functions.py [--dry-run]

What it does, every run (idempotent): creates or updates the functions `manastu_engine` (Pipe) and
`manastu_actions` (Actions) from frontend/openwebui/bundled/, activates them, sets their valves to
the in-stack addresses and the shared secret from .env, and attaches the actions to the model
`manastu_engine.main` only. It never prints the secret or the API key.
"""

import argparse
import os
import sys
from dataclasses import dataclass
from pathlib import Path

import httpx

HERE = Path(__file__).resolve().parent
PIPE_ID, ACTIONS_ID, MODEL_ID = "manastu_engine", "manastu_actions", "manastu_engine.main"
DEFAULT_ENGINE_URL = "http://api:8200"  # the API container as Open WebUI reaches it inside the stack


@dataclass(frozen=True)
class Target:
    owui_url: str
    engine_url: str
    console_url: str
    shared_secret: str


FUNCTIONS = {
    PIPE_ID: ("Manastu Propulsion Engine", "manastu_engine.py", "The DCL Answer Engine as a chat model."),
    ACTIONS_ID: (
        "Manastu engine actions",
        "manastu_actions.py",
        "Show trace, Add to benchmark, Report issue.",
    ),
}


def valves_for(function_id: str, target: Target) -> dict:
    common = {"ENGINE_URL": target.engine_url, "ENGINE_SHARED_SECRET": target.shared_secret}
    if function_id == PIPE_ID:
        return common | {"CONSOLE_URL": target.console_url}
    return common


def _check(response: httpx.Response, what: str) -> dict:
    if response.status_code >= 400:
        try:
            detail = response.json().get("detail")
        except ValueError:
            detail = response.text[:200]
        raise SystemExit(f"{what} failed: HTTP {response.status_code} {detail}")
    return response.json() if response.content else {}


def install(http: httpx.Client, target: Target, dry_run: bool = False, log=print) -> None:
    for function_id, (name, file_name, description) in FUNCTIONS.items():
        content = (HERE / "bundled" / file_name).read_text()
        form = {"id": function_id, "name": name, "content": content, "meta": {"description": description}}
        existing = http.get(f"/api/v1/functions/id/{function_id}")
        exists = existing.status_code == 200 and existing.json() is not None
        log(f"{'update' if exists else 'create'} function {function_id}")
        if not dry_run:
            path = f"/api/v1/functions/id/{function_id}/update" if exists else "/api/v1/functions/create"
            saved = _check(http.post(path, json=form), f"{'update' if exists else 'create'} {function_id}")
            if not saved.get("is_active"):
                log(f"activate function {function_id}")
                _check(http.post(f"/api/v1/functions/id/{function_id}/toggle"), f"activate {function_id}")
        log(f"set valves of {function_id} (ENGINE_URL={target.engine_url}, secret from .env)")
        if not dry_run:
            _check(
                http.post(
                    f"/api/v1/functions/id/{function_id}/valves/update", json=valves_for(function_id, target)
                ),
                f"valves of {function_id}",
            )

    current = http.get("/api/v1/models/model", params={"id": MODEL_ID})
    model = current.json() if current.status_code == 200 else None
    meta = dict((model or {}).get("meta") or {})
    actions = list(dict.fromkeys([*(meta.get("actionIds") or []), ACTIONS_ID]))
    form = {
        "id": MODEL_ID,
        "base_model_id": None,
        "name": (model or {}).get("name") or "Manastu Propulsion Engine",
        "meta": meta | {"actionIds": actions, "description": meta.get("description") or "DCL Answer Engine"},
        "params": (model or {}).get("params") or {},
        "is_active": True,
    }
    log(f"{'update' if model else 'create'} model {MODEL_ID} with actions {actions}")
    if not dry_run:
        path = "/api/v1/models/model/update" if model else "/api/v1/models/create"
        _check(http.post(path, json=form), f"model {MODEL_ID}")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--dry-run", action="store_true", help="read the current state and print the plan only"
    )
    args = parser.parse_args(argv)

    api_key = os.environ.get("OWUI_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("set OWUI_API_KEY to an Open WebUI admin API key (Settings › Account › API keys)")
    sys.path.insert(0, str(HERE.parents[1]))
    from backend.config import get_settings

    s = get_settings()
    if s.pipe_shared_secret is None:
        raise SystemExit("DCL_PIPE_SHARED_SECRET is not set in .env")
    target = Target(
        owui_url=os.environ.get("OWUI_URL") or f"http://localhost:{s.openwebui_port}",
        engine_url=os.environ.get("DCL_ENGINE_URL_FOR_OWUI") or DEFAULT_ENGINE_URL,
        console_url=str(s.console_base_url or "").rstrip("/"),
        shared_secret=s.pipe_shared_secret.get_secret_value(),
    )
    if not target.console_url:
        print(
            "warning: DCL_CONSOLE_BASE_URL is not set; citation links fall back to OneDrive", file=sys.stderr
        )
    headers = {"Authorization": f"Bearer {api_key}"}
    with httpx.Client(base_url=target.owui_url, headers=headers, timeout=30) as http:
        install(http, target, dry_run=args.dry_run)
    print("done" if not args.dry_run else "dry run: nothing changed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
