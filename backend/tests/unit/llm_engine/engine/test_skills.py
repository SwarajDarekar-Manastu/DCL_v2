"""The Open WebUI Skills say what the planner really does, and they publish idempotently."""

import importlib.util
import json
from pathlib import Path

import httpx
import pytest

from backend.llm_engine.engine.analysis import Intent, QueryAnalysis, resolve
from backend.llm_engine.engine.playbooks import build_plan
from backend.llm_engine.enrichment.entities import AliasIndex

SKILLS_DIR = Path(__file__).resolve().parents[5] / "frontend" / "openwebui" / "skills"
spec = importlib.util.spec_from_file_location("publish_skills", SKILLS_DIR / "publish_skills.py")
publish_skills = importlib.util.module_from_spec(spec)
spec.loader.exec_module(publish_skills)
SKILLS = publish_skills.load_skills(SKILLS_DIR)


def planned_tools(intents: tuple[str, ...]) -> set[str]:
    """Every tool the engine runs for these intents, on a question that names a plan, a part and a script."""
    raw = QueryAnalysis(
        intents=list(intents),
        test_plan_ids=["TP7"],
        hardware_items=["Injector 14"],
        entities=[
            {"type": "tool_software", "surface": "expansion_ratio"},
            {"type": "sensor_tag", "surface": "SV-1"},
        ],
    )
    analysis = resolve(raw, AliasIndex(), user_groups=["ext"], external_allowed_groups=["ext"])
    plan = build_plan("question", analysis)
    tools = {c.tool for c in plan.calls}
    tools |= {"query_telemetry"} if plan.needs_telemetry_args else set()
    tools |= {"physics_calculator"} if plan.needs_physics_args else set()
    tools |= {"get_document"} if plan.read_top_document else set()
    tools |= {"external_search"} if plan.external != "no" else set()
    return tools


def test_one_skill_per_playbook_row_and_every_intent_covered():
    assert len(SKILLS) == 13
    assert len({s.id for s in SKILLS}) == len({s.name for s in SKILLS}) == 13
    covered = {i for s in SKILLS for i in s.intents}
    assert covered == {str(i) for i in Intent} - {Intent.CHITCHAT}


@pytest.mark.parametrize("skill", SKILLS, ids=lambda s: s.id)
def test_the_tools_a_skill_names_are_the_tools_the_planner_runs(skill):
    assert set(skill.tools) == planned_tools(skill.intents)
    for tool in skill.tools:
        assert f"`{tool}`" in skill.content


class FakeOpenWebUI:
    """The v0.12.3 skill routes the script uses: get by id, create, update, toggle."""

    def __init__(self, existing=()):
        self.skills = {sid: {"id": sid, "is_active": False} for sid in existing}
        self.writes = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if request.method == "GET":
            sid = path.rsplit("/", 1)[1]
            return httpx.Response(200 if sid in self.skills else 404, json=self.skills.get(sid))
        self.writes.append((path, json.loads(request.content) if request.content else None))
        if path.endswith("/create"):
            body = self.writes[-1][1]
            self.skills[body["id"]] = {"id": body["id"], "is_active": True}
            return httpx.Response(200, json=self.skills[body["id"]])
        if path.endswith("/update"):
            return httpx.Response(200, json=self.skills[path.split("/")[-2]])
        if path.endswith("/toggle"):
            sid = path.split("/")[-2]
            self.skills[sid]["is_active"] = True
            return httpx.Response(200, json=self.skills[sid])
        return httpx.Response(404)


def run(server, dry_run=False):
    lines = []
    with httpx.Client(base_url="http://owui.test", transport=httpx.MockTransport(server)) as http:
        publish_skills.publish(http, SKILLS, dry_run=dry_run, log=lines.append)
    return lines


def test_publish_creates_then_updates_and_activates():
    server = FakeOpenWebUI(existing=["dcl-physics-calc"])
    run(server)
    paths = [p for p, _ in server.writes]
    assert paths.count("/api/v1/skills/create") == 12
    assert "/api/v1/skills/id/dcl-physics-calc/update" in paths
    assert "/api/v1/skills/id/dcl-physics-calc/toggle" in paths  # it existed inactive
    body = dict(server.writes)["/api/v1/skills/create"]
    assert body["access_grants"] == [{"principal_type": "user", "principal_id": "*", "permission": "read"}]
    assert not body["content"].startswith("---") and body["name"].startswith("DCL playbook: ")
    server.writes.clear()
    run(server)
    assert [p for p, _ in server.writes if p.endswith("/create")] == []  # second run only updates


def test_dry_run_writes_nothing():
    server = FakeOpenWebUI()
    lines = run(server, dry_run=True)
    assert (
        server.writes == []
        and len(lines) == 13
        and all(line.startswith("create skill dcl-") for line in lines)
    )
