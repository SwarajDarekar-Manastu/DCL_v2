"""Review API: resolution actions by discriminator, allowed actions per flag type, published routes."""

import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import TypeAdapter, ValidationError

from backend.api import auth, review
from backend.dispatcher.contract import ALLOWED_ACTIONS, MapColumns, Resolution, SetUnit
from backend.postgres.enums import FlagType
from backend.review.api_models import FlagResolution, ResolveRequest, allowed_actions_for, check_actions

FLAG = uuid.UUID("00000000-0000-4000-8000-0000000000f1")
RESOLUTION = TypeAdapter(Resolution)

EXAMPLES = {
    "set_unit": {
        "channel": "AIN0",
        "unit": "psig",
        "quantity": "pressure",
        "gauge_or_abs": "gauge",
        "ambient_condition": "SEA_LEVEL",
    },
    "set_fact_unit": {"unit": None},
    "map_columns": {"columns": [{"index": 0, "canonical_name": "t_rel_ms", "is_time": True}]},
    "map_json_keys": {"key_to_section": {"obs": "Observations"}},
    "set_value": {"value": "0.85", "unit": "mm"},
    "choose_table": {"choice": "B"},
    "choose_source": {"choice": "A"},
    "mark_superseded": {"superseded_doc_id": str(FLAG)},
    "accept_both": {},
    "ignore": {},
    "use_replacement": {"replacement_blob_sha256": "ab" * 32},
    "redact": {"regions": [{"page": 2, "bbox": {"x0": 0.1, "y0": 0.1, "x1": 0.5, "y1": 0.2}}]},
    "approve_internal": {},
    "approve_download": {},
    "watch": {},
    "skip": {},
    "mark_junk": {},
    "exclude": {},
}


@pytest.mark.parametrize("action", sorted(EXAMPLES))
def test_every_action_parses_from_json_by_its_discriminator(action):
    parsed = RESOLUTION.validate_python({"action": action, **EXAMPLES[action]})
    assert parsed.action == action


def test_every_allowed_action_has_a_model_and_every_model_is_allowed_somewhere():
    allowed = set().union(*ALLOWED_ACTIONS.values())
    assert allowed == set(EXAMPLES)
    assert set(ALLOWED_ACTIONS) == set(FlagType)


def test_unknown_action_and_extra_fields_are_refused():
    with pytest.raises(ValidationError):
        RESOLUTION.validate_python({"action": "delete_everything"})
    with pytest.raises(ValidationError):
        RESOLUTION.validate_python({"action": "skip", "force": True})


def test_resolve_request_carries_typed_resolutions():
    body = ResolveRequest.model_validate(
        {
            "resolutions": [
                {"flag_id": str(FLAG), "resolution": {"action": "set_unit", **EXAMPLES["set_unit"]}}
            ]
        }
    )
    assert isinstance(body.resolutions[0].resolution, SetUnit)
    with pytest.raises(ValidationError):
        ResolveRequest.model_validate({"resolutions": []})


def test_check_actions_enforces_the_flag_type():
    ok = [FlagResolution(flag_id=FLAG, resolution=MapColumns(columns=[{"index": 0, "canonical_name": "t"}]))]
    check_actions(ok, {FLAG: FlagType.SCHEMA_UNKNOWN})
    with pytest.raises(ValueError, match="not allowed for UNIT_AMBIGUITY"):
        check_actions(ok, {FLAG: FlagType.UNIT_AMBIGUITY})
    with pytest.raises(ValueError, match="not part of this case"):
        check_actions(ok, {})


# ---------- published routes ----------

ROUTES = {
    ("get", "/review/cases"): "CaseList",
    ("get", "/review/cases/{case_key}"): "CaseDetail",
    ("post", "/review/cases/{case_key}/assign"): "CaseSummary",
    ("post", "/review/cases/{case_key}/resolve"): "ResolveResponse",
    ("post", "/review/cases/{case_key}/reject"): "CaseSummary",
    ("post", "/review/cases/{case_key}/undo"): "UndoResponse",
    ("post", "/review/dry-run"): "DryRunResponse",
    ("get", "/review/rules"): "RuleList",
    ("post", "/review/rules"): "RuleView",
    ("post", "/review/rules/{rule_id}/simulate"): "RuleSimulation",
    ("post", "/review/rules/{rule_id}/deactivate"): "RuleView",
}


def _app(*roles: auth.ConsoleRole) -> TestClient:
    app = FastAPI()
    app.include_router(review.router)
    user = auth.ConsoleUser(oid="o", name="n", email="r@manastuspace.com", roles=list(roles))
    app.dependency_overrides[auth.current_user] = lambda: user
    return TestClient(app)


def test_every_review_route_is_published_with_its_response_model():
    schema = _app().app.openapi()
    for (method, path), model in ROUTES.items():
        responses = schema["paths"][path][method]["responses"]
        ok = responses.get("200") or responses["201"]
        assert ok["content"]["application/json"]["schema"]["$ref"].endswith(f"/{model}"), (method, path)


def test_reviewer_gets_501_until_the_tables_exist():
    client = _app(auth.ConsoleRole.REVIEWER)
    response = client.get("/review/cases", params={"severity": "HARD", "sort": "age"})
    assert response.status_code == 501
    assert client.post("/review/cases/doc:4/undo").status_code == 501


def test_viewer_cannot_use_review_routes_and_reviewer_cannot_deactivate_rules():
    assert _app(auth.ConsoleRole.VIEWER).get("/review/cases").status_code == 403
    reviewer = _app(auth.ConsoleRole.REVIEWER)
    assert reviewer.post(f"/review/rules/{FLAG}/deactivate").status_code == 403
    assert _app(auth.ConsoleRole.ADMIN).post(f"/review/rules/{FLAG}/deactivate").status_code == 501


def test_allowed_actions_hide_admin_only_actions_from_reviewers():
    assert allowed_actions_for(FlagType.SENSITIVE_CONTENT, is_admin=True) == [
        "approve_internal",
        "exclude",
        "redact",
    ]
    assert allowed_actions_for(FlagType.SENSITIVE_CONTENT, is_admin=False) == ["exclude", "redact"]
    assert allowed_actions_for(FlagType.UNIT_AMBIGUITY, is_admin=False) == ["set_fact_unit", "set_unit"]
