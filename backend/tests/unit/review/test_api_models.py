"""Review API: resolution actions by discriminator, allowed actions per flag type, published routes."""

import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import TypeAdapter, ValidationError

from backend.api import auth, review
from backend.dispatcher.contract import (
    ALLOWED_ACTIONS,
    MapColumns,
    Resolution,
    SetUnit,
    allowed_actions,
    flag_subject,
)
from backend.postgres.enums import FlagType
from backend.postgres.session import get_session
from backend.review import cases
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


def test_check_actions_enforces_what_the_flag_allows():
    ok = [FlagResolution(flag_id=FLAG, resolution=MapColumns(columns=[{"index": 0, "canonical_name": "t"}]))]
    check_actions(ok, {FLAG: ALLOWED_ACTIONS[FlagType.SCHEMA_UNKNOWN]})
    with pytest.raises(ValueError, match="not allowed for this flag"):
        check_actions(ok, {FLAG: ALLOWED_ACTIONS[FlagType.UNIT_AMBIGUITY]})
    with pytest.raises(ValueError, match="not part of this case"):
        check_actions(ok, {})


PAGE_ONLY = {"page": 8}
FIGURE = {"page": 41, "bbox": {"x0": 0.1, "y0": 0.2, "x1": 0.4, "y1": 0.5}}
ENTRY = {"page": 2, "content_sha256": "ab" * 16}


@pytest.mark.parametrize(
    ("flag_type", "anchor", "evidence", "subject", "actions"),
    [
        (FlagType.PARSE_FAILURE, {}, None, "file", {"use_replacement", "skip", "mark_junk"}),
        (FlagType.SCHEMA_UNKNOWN, {"content_sha256": "ab" * 16}, None, "file", None),
        (FlagType.LOW_CONFIDENCE_EXTRACTION, PAGE_ONLY, {}, "page", {"ignore", "mark_junk"}),
        (FlagType.LOW_CONFIDENCE_EXTRACTION, FIGURE, {"crops": []}, "object", {"ignore", "mark_junk"}),
        (
            FlagType.LOW_CONFIDENCE_EXTRACTION,
            FIGURE,
            {"table_a_html": "<table/>"},
            "object",
            {"choose_table", "mark_junk"},
        ),
        (FlagType.LOW_CONFIDENCE_EXTRACTION, ENTRY, {}, "value", {"set_value"}),
        (FlagType.LOW_CONFIDENCE_EXTRACTION, {"content_sha256": "cd" * 8}, {}, "value", {"ignore"}),
        (FlagType.UNIT_AMBIGUITY, {"channel": "AIN0"}, {}, "value", {"set_unit", "set_fact_unit"}),
        (FlagType.UNIT_AMBIGUITY, {"sheet": "Steady State", "column": "P1"}, {}, "value", None),
    ],
)
def test_skip_and_junk_act_only_on_what_the_flag_is_about(flag_type, anchor, evidence, subject, actions):
    assert flag_subject(flag_type, anchor) == subject
    allowed = allowed_actions(flag_type, anchor, evidence)
    assert allowed == (actions or ALLOWED_ACTIONS[flag_type])
    if subject == "value":
        assert not {"skip", "mark_junk"} & allowed  # a value question can never take anything out of search


# ---------- published routes ----------

ROUTES = {
    ("get", "/review/cases"): "CaseList",
    ("get", "/review/cases/{case_key}"): "CaseDetail",
    ("post", "/review/cases/{case_key}/assign"): "CaseSummary",
    ("post", "/review/cases/{case_key}/resolve"): "ResolveResponse",
    ("post", "/review/cases/{case_key}/undo"): "UndoResponse",
    ("post", "/review/cases/{case_key}/reopen"): "ReopenResponse",
    ("post", "/review/cases/{case_key}/edit"): "EditResponse",
    ("post", "/review/dry-run"): "DryRunResponse",
    ("get", "/review/rules"): "RuleList",
    ("post", "/review/rules"): "RuleCreated",
    ("post", "/review/rules/preview"): "RulePreview",
    ("get", "/review/folders"): "FolderList",
    ("post", "/review/rules/{rule_id}/simulate"): "RuleSimulation",
    ("post", "/review/rules/{rule_id}/deactivate"): "RuleView",
}


def _app(*roles: auth.ConsoleRole) -> TestClient:
    app = FastAPI()
    app.include_router(review.router)
    user = auth.ConsoleUser(oid="o", name="n", email="r@manastuspace.com", roles=list(roles))
    app.dependency_overrides[auth.current_user] = lambda: user
    app.dependency_overrides[get_session] = lambda: object()
    return TestClient(app)


def test_every_review_route_is_published_with_its_response_model():
    schema = _app().app.openapi()
    for (method, path), model in ROUTES.items():
        responses = schema["paths"][path][method]["responses"]
        ok = responses.get("200") or responses["201"]
        assert ok["content"]["application/json"]["schema"]["$ref"].endswith(f"/{model}"), (method, path)


def test_undo_and_simulate_answer_404_for_unknown_ids(monkeypatch):
    def missing(*args, **kwargs):
        raise cases.CaseNotFound("x")

    monkeypatch.setattr(cases, "undo_case", missing)
    monkeypatch.setattr(cases, "simulate_rule", missing)
    client = _app(auth.ConsoleRole.REVIEWER)
    assert client.post("/review/cases/doc:4/undo").status_code == 404
    assert client.post(f"/review/rules/{FLAG}/simulate").status_code == 404


def test_viewer_cannot_use_review_routes_and_reviewers_may_deactivate_rules(monkeypatch):
    def missing(session, rule_id, actor):
        raise cases.CaseNotFound(f"rule {rule_id}")

    monkeypatch.setattr(cases, "deactivate_rule", missing)
    assert _app(auth.ConsoleRole.VIEWER).get("/review/cases").status_code == 403
    assert _app(auth.ConsoleRole.VIEWER).post(f"/review/rules/{FLAG}/deactivate").status_code == 403
    assert _app(auth.ConsoleRole.REVIEWER).post(f"/review/rules/{FLAG}/deactivate").status_code == 404


def test_allowed_actions_hide_admin_only_actions_from_reviewers():
    assert allowed_actions_for(FlagType.SENSITIVE_CONTENT, is_admin=True) == [
        "approve_internal",
        "exclude",
        "redact",
    ]
    assert allowed_actions_for(FlagType.SENSITIVE_CONTENT, is_admin=False) == ["exclude", "redact"]
    assert allowed_actions_for(FlagType.UNIT_AMBIGUITY, is_admin=False) == ["set_fact_unit", "set_unit"]
