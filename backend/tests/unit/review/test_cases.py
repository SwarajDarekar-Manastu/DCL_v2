"""Review cases on a real database: queue, filters, impact sort, detail, resolve (rule + flags + audit),
reject, assign. Needs DCL_TEST_DATABASE_URL."""

import uuid

import pytest
from sqlalchemy import select

from backend.dispatcher.contract import (
    ConflictEvidence,
    ConflictSide,
    Flag,
    FlagAnchor,
    Suggestion,
    UnitTelemetryEvidence,
)
from backend.dispatcher.contract import SetUnit as SetUnitModel
from backend.postgres.models import (
    AuditEvent,
    Blob,
    Document,
    DocumentSource,
    DriveFolder,
    DriveItem,
    ReviewFlag,
    Rule,
)
from backend.review import cases
from backend.review.api_models import CaseFilters, FlagResolution, RejectRequest, ResolveRequest
from backend.review.flags import upsert_document_flag

ROOT = "APU Injector"


def _doc(session, name, status, folder, route="C", test_plan=None):
    sha = uuid.uuid4().hex + uuid.uuid4().hex
    session.add(Blob(sha256=sha, size_bytes=1, minio_uri=f"s3://dcl-raw/{sha}"))
    session.flush()
    session.add(
        DriveItem(
            drive_id="D",
            item_id=name,
            root_name=ROOT,
            name=name,
            extension="." + name.rsplit(".", 1)[1],
            parent_item_id=folder,
            path_cached=f"{ROOT}/E3/{name}",
            status="LANDED",
            blob_sha256=sha,
            web_url=f"https://x/{name}",
        )
    )
    doc = Document(
        route=route,
        status=status,
        title=name,
        test_plan_id=test_plan,
        staged_payload_uri=f"s3://dcl-cir/{sha}/staged.json" if status == "HALTED" else None,
    )
    session.add(doc)
    session.flush()
    session.add(DocumentSource(doc_id=doc.doc_id, blob_sha256=sha, role="primary"))
    session.flush()
    return doc


def _unit(channel, suggestion=True):
    return Flag(
        flag_type="UNIT_AMBIGUITY",
        severity="HARD",
        anchor=FlagAnchor(channel=channel),
        evidence=UnitTelemetryEvidence(channel=channel),
        suggested_resolution=Suggestion(confidence=0, rationale="no suggestion") if suggestion else None,
    )


@pytest.fixture()
def seeded(session):
    for fid, name in (("F-E3", "E3"), ("F-E9", "E9")):
        session.add(DriveFolder(drive_id="D", item_id=fid, parent_item_id="ROOT", root_name=ROOT, name=name))
    session.flush()
    dat = _doc(session, "T01.dat", "HALTED", "F-E3", test_plan="TP07")
    other = _doc(session, "T02.dat", "HALTED", "F-E3", test_plan="TP07")
    sheet = _doc(session, "plan.xlsx", "ACTIVE_WITH_SOFT_FLAGS", "F-E9")
    for channel in ("y0", "y1"):
        upsert_document_flag(session, dat.doc_id, _unit(channel), "C")
    upsert_document_flag(session, other.doc_id, _unit("y0", suggestion=False), "C")
    conflict = Flag(
        flag_type="CONFLICT",
        severity="SOFT",
        evidence=ConflictEvidence(
            subject="test_plan_id",
            a=ConflictSide(label="folder", value="TP07", provenance="folder"),
            b=ConflictSide(label="page 1", value="TP06", provenance="footer"),
        ),
    )
    upsert_document_flag(session, sheet.doc_id, conflict, "C")
    session.commit()
    return {"dat": dat, "other": other, "sheet": sheet}


def test_queue_defaults_to_open_cases_sorted_by_impact(session, seeded):
    result = cases.list_cases(session, CaseFilters())
    titles = [(c.title, c.max_severity, c.files_unblocked) for c in result.items]
    assert titles == [("T01.dat", "HARD", 2), ("T02.dat", "HARD", 2), ("plan.xlsx", "SOFT", None)]
    assert (result.open_hard, result.open_soft, result.next_cursor) == (3, 1, None)
    first = result.items[0]
    assert (first.flag_counts, first.has_suggestion, first.root_name, first.route, first.status) == (
        {"UNIT_AMBIGUITY": 2},
        True,
        ROOT,
        "C",
        "OPEN",
    )


@pytest.mark.parametrize(
    ("filters", "titles"),
    [
        ({"severity": "SOFT"}, ["plan.xlsx"]),
        ({"flag_type": "UNIT_AMBIGUITY", "has_suggestion": False}, ["T02.dat"]),
        ({"test_plan_id": "tp07", "sort": "age"}, ["T01.dat", "T02.dat"]),
        ({"root_name": "elsewhere"}, []),
        ({"limit": 1}, ["T01.dat"]),
    ],
)
def test_queue_filters(session, seeded, filters, titles):
    assert [c.title for c in cases.list_cases(session, CaseFilters(**filters)).items] == titles


def test_case_detail_has_flags_actions_locations_and_siblings(session, seeded):
    key = f"{seeded['dat'].doc_id}:"
    detail = cases.case_detail(session, key, is_admin=False)
    assert [(f.flag_type, f.anchor.channel, f.allowed_actions) for f in detail.flags] == [
        ("UNIT_AMBIGUITY", "y0", ["set_fact_unit", "set_unit"]),
        ("UNIT_AMBIGUITY", "y1", ["set_fact_unit", "set_unit"]),
    ]
    assert detail.flags[0].suggested_resolution.rationale == "no suggestion"
    assert [(loc.folder_id, loc.file_name, loc.web_url) for loc in detail.locations] == [
        ("F-E3", "T01.dat", "https://x/T01.dat")
    ]
    assert (detail.siblings, detail.document_status) == (["T02.dat"], "HALTED")
    with pytest.raises(cases.CaseNotFound):
        cases.case_detail(session, "nope:", is_admin=False)


def test_set_unit_without_a_rule_writes_a_file_scoped_channel_map(session, seeded):
    key = f"{seeded['dat'].doc_id}:"
    flags = {
        f.anchor["channel"]: f for f in session.scalars(select(ReviewFlag).where(ReviewFlag.case_key == key))
    }
    request = ResolveRequest(
        resolutions=[
            FlagResolution(
                flag_id=flags[c].flag_id,
                resolution=SetUnitModel(channel=c, unit="bar", quantity="pressure", gauge_or_abs="gauge"),
            )
            for c in ("y0", "y1")
        ],
        comment="per the TP7 setup",
    )
    outcome = cases.resolve_case(session, key, request, "asha@manastu.space", is_admin=False)
    session.commit()
    rule = session.get(Rule, outcome.resume_rule_id)
    assert (rule.rule_type, rule.origin, rule.scope_root, rule.scope_folder_id, rule.scope_filename_glob) == (
        "channel_map",
        "operator",
        ROOT,
        "F-E3",
        "T01.dat",
    )
    assert rule.body["channels"]["y0"] == {
        "canonical_name": "y0",
        "physical_quantity": "pressure",
        "unit": "bar",
        "gauge_or_abs": "gauge",
    }
    assert {(f.status, f.resolution_rule_id, f.resolved_by) for f in outcome.flags} == {
        ("RESOLVED", rule.rule_id, "asha@manastu.space")
    }
    actions = sorted(session.scalars(select(AuditEvent.entity_type + ":" + AuditEvent.action)).all())
    assert actions == ["case:resolve", "flag:resolve", "flag:resolve", "rule:create"]
    with pytest.raises(cases.InvalidAction, match="not open"):
        cases.resolve_case(session, key, request, "asha@manastu.space", is_admin=False)


def test_wrong_action_is_refused_and_soft_resolution_settles_the_document(session, seeded):
    key = f"{seeded['sheet'].doc_id}:"
    (flag,) = session.scalars(select(ReviewFlag).where(ReviewFlag.case_key == key)).all()
    bad = ResolveRequest(
        resolutions=[FlagResolution(flag_id=flag.flag_id, resolution={"action": "set_value", "value": "x"})]
    )
    with pytest.raises(cases.InvalidAction, match="not allowed"):
        cases.resolve_case(session, key, bad, "r@x", is_admin=False)
    ok = ResolveRequest(
        resolutions=[FlagResolution(flag_id=flag.flag_id, resolution={"action": "accept_both"})]
    )
    outcome = cases.resolve_case(session, key, ok, "r@x", is_admin=False)
    session.commit()
    assert (outcome.rule, outcome.resume_rule_id) == (None, None)
    assert session.get(Document, seeded["sheet"].doc_id).status == "ACTIVE"


def test_assign_then_reject_as_junk(session, seeded):
    key = f"{seeded['other'].doc_id}:"
    cases.assign_case(session, key, "ravi@manastu.space", "lead@x")
    assert cases.summary_of(session, cases._case(session, key)).status == "IN_PROGRESS"
    cases.assign_case(session, key, None, "lead@x")
    assert cases.summary_of(session, cases._case(session, key)).status == "OPEN"
    case = cases.reject_case(session, key, RejectRequest(action="mark_junk"), "lead@x")
    session.commit()
    document = session.get(Document, seeded["other"].doc_id)
    item = session.scalars(select(DriveItem).where(DriveItem.name == "T02.dat")).one()
    assert (document.status, document.staged_payload_uri) == ("QUARANTINED", None)
    assert (item.status, item.gate_reason) == ("QUARANTINED", "REVIEW:mark_junk")
    assert cases.summary_of(session, case).status == "REJECTED_FILE"
    assert [c.title for c in cases.list_cases(session, CaseFilters(status="REJECTED_FILE")).items] == [
        "T02.dat"
    ]


def test_simulate_counts_the_halted_files_a_folder_rule_resumes(session, seeded):
    from backend.review.rules import RuleScope

    result = cases.simulate(session, RuleScope(scope_folder_id="F-E3"), "channel_map")
    assert (result.matched_documents, result.would_resume, result.would_reprocess) == (2, 2, 0)
    assert sorted(d.title for d in result.sample) == ["T01.dat", "T02.dat"]
    assert cases.simulate(session, RuleScope(scope_folder_id="F-E9"), "channel_map").matched_documents == 1


def test_dry_run_converts_the_recorded_stats_without_writing(session, seeded):
    from backend.review.api_models import DryRunRequest

    key = f"{seeded['dat'].doc_id}:"
    flag = next(
        f
        for f in session.scalars(select(ReviewFlag).where(ReviewFlag.case_key == key))
        if f.anchor["channel"] == "y0"
    )
    flag.evidence = {
        **flag.evidence,
        "stats": {"n": 100, "min": 0.0, "max": 145.0377, "mean": 72.51885, "p99": 140.0},
    }
    session.commit()
    request = DryRunRequest(
        case_key=key,
        resolution=FlagResolution(
            flag_id=flag.flag_id,
            resolution=SetUnitModel(channel="y0", unit="psi", quantity="pressure", gauge_or_abs="gauge"),
        ),
    )
    response = cases.dry_run(session, request)
    (channel,) = response.channels
    assert (
        channel.canonical_name,
        channel.unit_si,
        round(channel.stat_max, 3),
        round(channel.stat_mean, 3),
    ) == ("y0", "bar", 10.0, 5.0)
    assert (response.affected_documents, response.messages) == (1, [])
    assert session.get(ReviewFlag, flag.flag_id).status == "OPEN"


def test_undo_reopens_the_last_resolution_and_retires_its_file_rule(session, seeded):
    key = f"{seeded['dat'].doc_id}:"
    flags = {
        f.anchor["channel"]: f for f in session.scalars(select(ReviewFlag).where(ReviewFlag.case_key == key))
    }
    request = ResolveRequest(
        resolutions=[
            FlagResolution(
                flag_id=flags[c].flag_id,
                resolution=SetUnitModel(channel=c, unit="bar", quantity="pressure", gauge_or_abs="gauge"),
            )
            for c in ("y0", "y1")
        ]
    )
    outcome = cases.resolve_case(session, key, request, "asha@x", is_admin=False)
    session.commit()
    undone = cases.undo_case(session, key, "asha@x")
    session.commit()
    assert {f.status for f in undone.reopened} == {"REOPENED"} and len(undone.reopened) == 2
    assert (undone.deactivated_rule_id, undone.rebuild_doc_id) == (
        outcome.resume_rule_id,
        None,
    )  # still HALTED
    assert session.get(Rule, outcome.resume_rule_id).active is False
    with pytest.raises(cases.InvalidAction, match="nothing to undo"):
        cases.undo_case(session, key, "asha@x")


def test_undo_of_mark_junk_restores_the_file_and_rebuilds(session, seeded):
    key = f"{seeded['other'].doc_id}:"
    cases.reject_case(session, key, RejectRequest(action="mark_junk"), "lead@x")
    session.commit()
    undone = cases.undo_case(session, key, "lead@x")
    session.commit()
    item = session.scalars(select(DriveItem).where(DriveItem.name == "T02.dat")).one()
    assert (item.status, item.gate_reason) == ("LANDED", None)
    assert undone.rebuild_doc_id == seeded["other"].doc_id
    assert session.get(Document, seeded["other"].doc_id).status == "PROCESSING"


def test_a_flag_with_an_unknown_route_still_opens(session, seeded):
    key = f"{seeded['sheet'].doc_id}:"
    (flag,) = session.scalars(select(ReviewFlag).where(ReviewFlag.case_key == key)).all()
    flag.route = "answer"
    session.commit()
    detail = cases.case_detail(session, key, is_admin=False)
    assert (detail.flags[0].route, detail.summary.route) == (None, "C")
