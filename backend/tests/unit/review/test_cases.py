"""Review cases on a real database: queue, filters, impact sort, detail, resolve (rule + flags + audit),
skip and junk by what a flag is about, assign. Needs DCL_TEST_DATABASE_URL."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from backend.dispatcher.contract import (
    ConflictEvidence,
    ConflictSide,
    ExtractionCrop,
    Flag,
    FlagAnchor,
    LowConfidenceEvidence,
    SensitiveEvidence,
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
from backend.review.api_models import CaseFilters, FlagResolution, ResolveRequest
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
        session.add(
            DriveFolder(
                drive_id="D",
                item_id=fid,
                parent_item_id="ROOT",
                root_name=ROOT,
                name=name,
                path_cached=f"{ROOT}/{name}",
            )
        )
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
    # the decision reaches search at once: the committed file is rebuilt with it
    assert outcome.rebuild_doc_id == seeded["sheet"].doc_id
    assert session.get(Document, seeded["sheet"].doc_id).status == "PROCESSING"


def _resolve(session, key, flag, action):
    request = ResolveRequest(
        resolutions=[FlagResolution(flag_id=flag.flag_id, resolution={"action": action})]
    )
    return cases.resolve_case(session, key, request, "lead@x", is_admin=False)


def _unreadable(session):
    doc = _doc(session, "broken.pdf", "HALTED", "F-E9", route="A1")
    upsert_document_flag(session, doc.doc_id, Flag(flag_type="PARSE_FAILURE", severity="HARD"), "A1")
    session.commit()
    (flag,) = session.scalars(select(ReviewFlag).where(ReviewFlag.doc_id == doc.doc_id)).all()
    return doc, flag


def test_assign_then_junk_the_whole_file_from_its_file_flag(session, seeded):
    doc, flag = _unreadable(session)
    key = flag.case_key
    cases.assign_case(session, key, "ravi@manastu.space", "lead@x")
    assert cases.summary_of(session, cases._case(session, key)).status == "IN_PROGRESS"
    cases.assign_case(session, key, None, "lead@x")
    assert cases.summary_of(session, cases._case(session, key)).status == "OPEN"
    outcome = _resolve(session, key, flag, "mark_junk")
    session.commit()
    document = session.get(Document, doc.doc_id)
    item = session.scalars(select(DriveItem).where(DriveItem.name == "broken.pdf")).one()
    assert (document.status, document.staged_payload_uri, outcome.rebuild_doc_id) == (
        "QUARANTINED",
        None,
        None,
    )
    assert (item.status, item.gate_reason) == ("QUARANTINED", "REVIEW:mark_junk")
    assert cases.summary_of(session, cases._case(session, key)).status == "REJECTED_FILE"
    assert [c.title for c in cases.list_cases(session, CaseFilters(status="REJECTED_FILE")).items] == [
        "broken.pdf"
    ]


def test_a_value_flag_can_never_skip_or_junk_its_file(session, seeded):
    key = f"{seeded['other'].doc_id}:"
    (flag,) = session.scalars(select(ReviewFlag).where(ReviewFlag.case_key == key)).all()
    for action in ("mark_junk", "skip"):
        with pytest.raises(cases.InvalidAction, match="not allowed"):
            _resolve(session, key, flag, action)
    session.rollback()
    assert session.get(Document, seeded["other"].doc_id).status == "HALTED"


def test_sensitive_content_is_excluded_like_a_skip_and_never_released_by_redact(session, seeded):
    doc = _doc(session, "plan_itar.pdf", "HALTED", "F-E9", route="A1")
    evidence = SensitiveEvidence(pattern="ITAR", redacted_preview="marking 'ITAR' on page 1", page=1)
    flag = Flag(flag_type="SENSITIVE_CONTENT", severity="HARD", anchor=FlagAnchor(page=1), evidence=evidence)
    upsert_document_flag(session, doc.doc_id, flag, "A1")
    session.commit()
    (row,) = session.scalars(select(ReviewFlag).where(ReviewFlag.doc_id == doc.doc_id)).all()
    redact = {
        "action": "redact",
        "regions": [{"page": 1, "bbox": {"x0": 0.1, "y0": 0.1, "x1": 0.5, "y1": 0.2}}],
    }
    request = ResolveRequest(resolutions=[FlagResolution(flag_id=row.flag_id, resolution=redact)])
    with pytest.raises(cases.InvalidAction, match="not allowed"):  # nothing makes a redacted copy yet
        cases.resolve_case(session, row.case_key, request, "lead@x", is_admin=False)
    session.rollback()
    outcome = _resolve(session, row.case_key, row, "exclude")
    session.commit()
    document = session.get(Document, doc.doc_id)
    item = session.scalars(select(DriveItem).where(DriveItem.name == "plan_itar.pdf")).one()
    assert (document.status, document.staged_payload_uri) == ("QUARANTINED", None)
    assert (outcome.resume_doc_id, outcome.rebuild_doc_id) == (None, None)
    assert (session.get(ReviewFlag, row.flag_id).status, item.gate_reason) == ("REJECTED_FILE", None)


def test_junking_one_image_keeps_the_file_and_rebuilds_it_without_the_image(session, seeded):
    doc = _doc(session, "report.docx", "ACTIVE_WITH_SOFT_FLAGS", "F-E9", route="A1")
    image = Flag(
        flag_type="LOW_CONFIDENCE_EXTRACTION",
        severity="SOFT",
        anchor=FlagAnchor(page=44, bbox={"x0": 0.1, "y0": 0.2, "x1": 0.4, "y1": 0.5}),
        evidence=LowConfidenceEvidence(crops=[ExtractionCrop(crop_uri="s3://dcl-assets/figures/x/f1.png")]),
    )
    upsert_document_flag(session, doc.doc_id, image, "A1")
    session.commit()
    (flag,) = session.scalars(select(ReviewFlag).where(ReviewFlag.doc_id == doc.doc_id)).all()
    detail = cases.flag_view(flag, is_admin=False)
    assert (detail.subject, detail.allowed_actions) == ("object", ["ignore", "mark_junk"])
    outcome = _resolve(session, flag.case_key, flag, "mark_junk")
    session.commit()
    item = session.scalars(select(DriveItem).where(DriveItem.name == "report.docx")).one()
    assert (session.get(Document, doc.doc_id).status, outcome.rebuild_doc_id) == ("PROCESSING", doc.doc_id)
    assert (item.status, item.gate_reason) == ("LANDED", None)
    assert (flag.status, flag.resolution) == ("RESOLVED", {"action": "mark_junk"})


def test_simulate_counts_the_files_that_wait_for_a_folder_rule(session, seeded):
    from backend.review.rules import RuleScope

    result = cases.simulate(session, RuleScope(scope_folder_id="F-E3"), "channel_proposal")
    assert (result.matched_documents, result.waiting_documents, result.finished_documents) == (2, 2, 0)
    assert sorted(d.title for d in result.sample) == ["T01.dat", "T02.dat"]
    assert (
        cases.simulate(session, RuleScope(scope_folder_id="F-E9"), "channel_proposal").matched_documents == 1
    )


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
    named = request.model_copy(
        update={
            "resolution": FlagResolution(
                flag_id=flag.flag_id,
                resolution=SetUnitModel(
                    channel="y0",
                    unit="psi",
                    quantity="pressure",
                    gauge_or_abs="gauge",
                    canonical_name="p_chamber_1_bar_g",
                ),
            )
        }
    )
    (channel,) = cases.dry_run(session, named).channels
    assert channel.canonical_name == "p_chamber_1_bar_g"  # the name Apply writes, so the same sanity range


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
    doc, flag = _unreadable(session)
    _resolve(session, flag.case_key, flag, "mark_junk")
    session.commit()
    undone = cases.undo_case(session, flag.case_key, "lead@x")
    session.commit()
    item = session.scalars(select(DriveItem).where(DriveItem.name == "broken.pdf")).one()
    assert (item.status, item.gate_reason) == ("LANDED", None)
    assert undone.rebuild_doc_id == doc.doc_id
    assert session.get(Document, doc.doc_id).status == "PROCESSING"


def test_a_flag_with_an_unknown_route_still_opens(session, seeded):
    key = f"{seeded['sheet'].doc_id}:"
    (flag,) = session.scalars(select(ReviewFlag).where(ReviewFlag.case_key == key)).all()
    flag.route = "answer"
    session.commit()
    detail = cases.case_detail(session, key, is_admin=False)
    assert (detail.flags[0].route, detail.summary.route) == (None, "C")


def _proposal(scope, *channels, unit="bar", gauge="gauge", name=None):
    from backend.review.api_models import RuleDraft

    return RuleDraft(
        rule_type="channel_proposal",
        scope=scope,
        body={
            "channels": {
                c: {
                    "canonical_name": name or c,
                    "physical_quantity": "pressure",
                    "unit": unit,
                    "gauge_or_abs": gauge,
                }
                for c in channels
            }
        },
    )


def _open_flags(session, doc):
    return {
        f.anchor["channel"]: f
        for f in session.scalars(select(ReviewFlag).where(ReviewFlag.doc_id == doc.doc_id))
        if f.flag_type == "UNIT_AMBIGUITY"
    }


def _resolve_units(session, doc, channels, scope=None, unit="bar"):
    key = f"{doc.doc_id}:"
    flags = _open_flags(session, doc)
    request = ResolveRequest(
        resolutions=[
            FlagResolution(
                flag_id=flags[c].flag_id,
                resolution=SetUnitModel(channel=c, unit=unit, quantity="pressure", gauge_or_abs="absolute"),
            )
            for c in channels
        ],
        rule_scope=scope,
    )
    outcome = cases.resolve_case(session, key, request, "asha@manastu.space", is_admin=False)
    session.commit()
    return outcome


def test_a_rule_proposes_to_the_waiting_files_and_approves_nothing(session, seeded):
    from backend.review.rules import RuleScope

    scope = RuleScope(scope_root=ROOT, scope_folder_id="F-E3")
    rule = cases.create_rule(session, _proposal(scope, "y0", "y1", name="pt_101"), "asha")
    assert cases.propose_rule(session, rule) == 2
    session.commit()

    assert rule.rule_type == "channel_proposal"
    flags = {**_open_flags(session, seeded["dat"]), "other_y0": _open_flags(session, seeded["other"])["y0"]}
    assert {f.status for f in flags.values()} == {"OPEN"}
    assert {f.proposed_by_rule_id for f in flags.values()} == {rule.rule_id}
    suggestion = flags["y0"].suggested_resolution
    assert (suggestion["proposed_by"], suggestion["resolution"]["unit"]) == ("rule", "bar")
    assert suggestion["resolution"]["canonical_name"] == "pt_101"
    assert "asha" in suggestion["rationale"] and suggestion["confidence"] < 0.9
    assert (seeded["dat"].status, seeded["other"].status) == ("HALTED", "HALTED")
    assert session.scalars(select(Rule).where(Rule.rule_type == "channel_map")).all() == []


def test_a_unit_rule_is_a_proposal_too_and_never_a_channel_map(session, seeded):
    from backend.review.api_models import RuleDraft
    from backend.review.rules import RuleScope

    draft = RuleDraft(
        rule_type="unit_mapping",
        scope=RuleScope(scope_root=ROOT, scope_folder_id="F-E3"),
        body={"channel": "y0", "unit": "bar", "quantity": "pressure", "gauge_or_abs": "gauge"},
    )
    rule = cases.create_rule(session, draft, "asha")
    assert (rule.rule_type, sorted(rule.body["channels"])) == ("channel_proposal", ["y0"])
    with pytest.raises(cases.InvalidAction, match="approved on the file"):
        cases.resolve_case(
            session,
            f"{seeded['dat'].doc_id}:",
            ResolveRequest(
                resolutions=[
                    FlagResolution(
                        flag_id=_open_flags(session, seeded["dat"])["y0"].flag_id,
                        resolution=SetUnitModel(
                            channel="y0", unit="bar", quantity="pressure", gauge_or_abs="gauge"
                        ),
                    )
                ],
                rule=_proposal(draft.scope, "y0").model_copy(update={"rule_type": "channel_map"}),
            ),
            "asha",
            False,
        )


def test_the_closest_proposal_wins_and_switching_it_off_gives_the_hint_back(session, seeded):
    from backend.review.rules import RuleScope

    broad = cases.create_rule(session, _proposal(RuleScope(scope_root=ROOT), "y0", unit="psi"), "asha")
    close = cases.create_rule(
        session, _proposal(RuleScope(scope_root=ROOT, scope_folder_id="F-E3"), "y0", unit="bar"), "ravi"
    )
    cases.propose_rule(session, broad)
    cases.propose_rule(session, close)
    session.commit()
    flag = _open_flags(session, seeded["dat"])["y0"]
    assert (flag.proposed_by_rule_id, flag.suggested_resolution["resolution"]["unit"]) == (
        close.rule_id,
        "bar",
    )

    cases.deactivate_rule(session, close.rule_id, "asha")
    session.commit()
    session.refresh(flag)
    assert (flag.proposed_by_rule_id, flag.suggested_resolution["resolution"]["unit"]) == (
        broad.rule_id,
        "psi",
    )

    cases.deactivate_rule(session, broad.rule_id, "asha")
    session.commit()
    session.refresh(flag)
    assert flag.proposed_by_rule_id is None
    assert (
        flag.suggested_resolution["proposed_by"] == "heuristic"
        and flag.suggested_resolution["resolution"] is None
    )


def test_a_model_proposal_is_the_pipelines_own_hint_and_a_refresh_keeps_it(session, seeded):
    from backend.review.proposals import refresh

    flag = _open_flags(session, seeded["dat"])["y0"]
    model = {
        "resolution": {
            "action": "set_unit",
            "channel": "y0",
            "unit": "bar",
            "quantity": "pressure",
            "gauge_or_abs": "gauge",
        },
        "confidence": 0.5,
        "rationale": "model proposal",
        "proposed_by": "llm",
    }
    flag.suggested_resolution = model
    session.commit()
    refresh(session, [seeded["dat"].doc_id])
    session.commit()
    session.refresh(flag)
    assert (flag.suggested_resolution, flag.proposed_by_rule_id) == (model, None)


def test_a_person_approves_each_file_and_the_approval_names_who_and_which_rule(session, seeded):
    from backend.review.rules import RuleScope

    rule = cases.create_rule(
        session, _proposal(RuleScope(scope_root=ROOT, scope_folder_id="F-E3"), "y0", "y1"), "asha"
    )
    cases.propose_rule(session, rule)
    session.commit()
    flags = _open_flags(session, seeded["dat"])
    proposed_by = {f.flag_id: f.proposed_by_rule_id for f in flags.values()}

    outcome = _resolve_units(session, seeded["dat"], ["y0", "y1"])
    approval = session.get(Rule, outcome.resume_rule_id)
    assert (approval.rule_type, approval.scope_filename_glob, approval.created_by) == (
        "channel_map",
        "T01.dat",
        "asha@manastu.space",
    )
    assert {(f.status, f.resolved_by, f.resolution_rule_id) for f in flags.values()} == {
        ("RESOLVED", "asha@manastu.space", approval.rule_id)
    }
    assert all(f.proposed_by_rule_id == proposed_by[f.flag_id] == rule.rule_id for f in flags.values())
    event = session.scalars(
        select(AuditEvent).where(
            AuditEvent.entity_id == str(flags["y0"].flag_id), AuditEvent.action == "resolve"
        )
    ).one()
    assert event.after["proposed_by_rule_id"] == str(rule.rule_id)

    other = _open_flags(session, seeded["other"])["y0"]  # the neighbour is untouched and still waiting
    assert (other.status, other.proposed_by_rule_id, seeded["other"].status) == (
        "OPEN",
        rule.rule_id,
        "HALTED",
    )
    view = cases.rule_view(session, rule)
    assert (view.flags_proposed, view.flags_decided, view.files_waiting) == (3, 2, 1)


def test_approving_with_also_propose_fills_in_the_other_files_and_leaves_them_open(session, seeded):
    from backend.review.rules import RuleScope

    outcome = _resolve_units(
        session, seeded["dat"], ["y0"], scope=RuleScope(scope_root=ROOT, scope_folder_id="F-E3")
    )
    assert (outcome.rule.rule_type, outcome.proposed_files) == ("channel_proposal", 1)
    approval = session.get(Rule, outcome.resume_rule_id)
    assert (approval.rule_type, approval.scope_filename_glob) == ("channel_map", "T01.dat")
    other = _open_flags(session, seeded["other"])["y0"]
    assert (other.status, other.proposed_by_rule_id) == ("OPEN", outcome.rule.rule_id)
    assert other.suggested_resolution["resolution"]["gauge_or_abs"] == "absolute"
    assert seeded["other"].status == "HALTED"
    from backend.routes.c_telemetry.pipeline import halted_documents_for_rule

    assert halted_documents_for_rule(session, outcome.resume_rule_id) == [seeded["dat"].doc_id]


def test_preview_says_what_a_rule_would_do_before_it_is_saved(session, seeded):
    from backend.review.api_models import RulePreviewRequest
    from backend.review.rules import RuleScope

    scope = RuleScope(scope_root=ROOT, scope_folder_id="F-E3")
    preview = cases.preview_rule(session, RulePreviewRequest(rule_type="channel_proposal", scope=scope))
    assert (preview.matched_documents, preview.waiting_documents, preview.effect, preview.problem) == (
        2,
        2,
        "proposes",
        None,
    )
    assert [(c.channel, c.files) for c in preview.open_channels] == [("y0", 2), ("y1", 1)]
    assert session.scalars(select(Rule)).all() == []  # nothing was saved

    bad = cases.preview_rule(
        session, RulePreviewRequest(rule_type="channel_proposal", scope=scope, body={"channels": {}})
    )
    assert bad.problem is not None
    effects = {
        kind: cases.preview_rule(session, RulePreviewRequest(rule_type=kind, scope=scope)).effect
        for kind in ("ignore_pattern", "column_unit", "origin_override")
    }
    assert effects == {"ignore_pattern": "resolves", "column_unit": "resolves", "origin_override": "applies"}
    assert (
        cases.preview_rule(session, RulePreviewRequest(rule_type="unit_mapping", scope=scope)).effect
        == "proposes"
    )


def test_the_rule_list_separates_proposals_from_file_approvals(session, seeded):
    from backend.review.rules import RuleScope

    rule = cases.create_rule(
        session, _proposal(RuleScope(scope_root=ROOT, scope_folder_id="F-E3"), "y0"), "asha"
    )
    _resolve_units(session, seeded["dat"], ["y0"])
    assert [r.rule_type for r in cases.list_rules(session, None, "rules")] == ["channel_proposal"]
    assert [r.rule_type for r in cases.list_rules(session, None, "decisions")] == ["channel_map"]
    assert len(cases.list_rules(session, None)) == 2
    assert cases.list_rules(session, None, "rules")[0].rule_id == rule.rule_id


def test_the_queue_can_be_narrowed_to_a_rules_files_and_to_words_in_the_name(session, seeded):
    from backend.review.rules import RuleScope

    rule = cases.create_rule(
        session, _proposal(RuleScope(scope_root=ROOT, scope_folder_id="F-E3"), "y0"), "asha"
    )
    cases.propose_rule(session, rule)
    session.commit()
    proposed = cases.list_cases(session, CaseFilters(proposed_by_rule_id=rule.rule_id))
    assert sorted(c.title for c in proposed.items) == ["T01.dat", "T02.dat"]
    assert all(c.has_rule_proposal for c in proposed.items)
    assert [c.title for c in cases.list_cases(session, CaseFilters(q="t02 dat")).items] == ["T02.dat"]
    assert cases.list_cases(session, CaseFilters(q="nothing like this")).items == []
    plain = {c.title: c.has_rule_proposal for c in cases.list_cases(session, CaseFilters()).items}
    assert plain["plan.xlsx"] is False


def test_the_audit_page_finds_files_that_have_a_decision_whatever_their_status(session, seeded):
    assert cases.list_cases(session, CaseFilters(decided=True)).items == []
    _resolve_units(session, seeded["dat"], ["y0"])  # y1 stays open: the case is still OPEN
    found = cases.list_cases(session, CaseFilters(decided=True, q="t01"))
    assert [(c.title, c.status) for c in found.items] == [("T01.dat", "OPEN")]
    assert [
        c.title for c in cases.list_cases(session, CaseFilters(decided=False)).items if c.title == "T01.dat"
    ] == []


def test_reopening_one_channel_asks_it_again_and_keeps_the_others_approved(session, seeded):
    outcome = _resolve_units(session, seeded["dat"], ["y0", "y1"])
    old = session.get(Rule, outcome.resume_rule_id)
    flags = _open_flags(session, seeded["dat"])
    seeded["dat"].status, seeded["dat"].staged_payload_uri = "ACTIVE", None
    session.commit()

    result = cases.reopen_flags(
        session, f"{seeded['dat'].doc_id}:", [flags["y1"].flag_id], "wrong sensor", "asha"
    )
    session.commit()
    assert (flags["y1"].status, flags["y1"].resolution, flags["y1"].resolved_by) == ("REOPENED", None, None)
    assert flags["y0"].status == "RESOLVED"
    assert result.rebuild_doc_id == seeded["dat"].doc_id and seeded["dat"].status == "PROCESSING"
    session.refresh(old)
    assert old.active is False
    narrower = session.get(Rule, flags["y0"].resolution_rule_id)
    assert (narrower.active, narrower.supersedes_rule_id, sorted(narrower.body["channels"])) == (
        True,
        old.rule_id,
        ["y0"],
    )
    event = session.scalars(
        select(AuditEvent).where(
            AuditEvent.entity_id == str(flags["y1"].flag_id), AuditEvent.action == "reopen"
        )
    ).one()
    assert (event.actor, event.after["reason"]) == ("asha", "wrong sensor")


def test_reopening_every_channel_switches_the_approval_off(session, seeded):
    outcome = _resolve_units(session, seeded["dat"], ["y0", "y1"])
    flags = _open_flags(session, seeded["dat"])
    cases.reopen_flags(
        session, f"{seeded['dat'].doc_id}:", [f.flag_id for f in flags.values()], "start over", "asha"
    )
    session.commit()
    assert session.get(Rule, outcome.resume_rule_id).active is False
    assert {f.status for f in flags.values()} == {"REOPENED"}
    with pytest.raises(cases.InvalidAction, match="only a decided flag"):
        cases.reopen_flags(session, f"{seeded['dat'].doc_id}:", [flags["y0"].flag_id], "again", "asha")


def test_reopening_works_for_any_flag_type_and_any_age(session, seeded):
    key = f"{seeded['sheet'].doc_id}:"
    flag = session.scalars(select(ReviewFlag).where(ReviewFlag.case_key == key)).one()
    request = ResolveRequest(
        resolutions=[FlagResolution(flag_id=flag.flag_id, resolution={"action": "accept_both"})]
    )
    cases.resolve_case(session, key, request, "asha", False)
    flag.resolved_at = flag.resolved_at - timedelta(days=90)  # far older than undo's 30 days
    session.commit()
    with pytest.raises(cases.InvalidAction, match="older than 30 days"):
        cases.undo_case(session, key, "asha")
    cases.reopen_flags(session, key, [flag.flag_id], "the footer was a typo", "asha")
    assert (flag.status, flag.resolution) == ("REOPENED", None)


def test_editing_a_decided_unit_replaces_the_approval_and_records_who_and_why(session, seeded):
    from backend.review.api_models import EditRequest

    outcome = _resolve_units(session, seeded["dat"], ["y0", "y1"])
    old = session.get(Rule, outcome.resume_rule_id)
    flags = _open_flags(session, seeded["dat"])
    seeded["dat"].status, seeded["dat"].staged_payload_uri = "ACTIVE", None
    session.commit()

    result = cases.edit_case(
        session,
        f"{seeded['dat'].doc_id}:",
        EditRequest(
            resolutions=[
                FlagResolution(
                    flag_id=flags["y1"].flag_id,
                    resolution=SetUnitModel(
                        channel="y1", unit="psi", quantity="pressure", gauge_or_abs="gauge"
                    ),
                )
            ],
            reason="the rig sheet says psig",
        ),
        "ravi@manastu.space",
    )
    session.commit()
    session.refresh(old)
    new = session.get(Rule, flags["y1"].resolution_rule_id)
    assert (old.active, new.active, new.supersedes_rule_id, new.created_by) == (
        False,
        True,
        old.rule_id,
        "ravi@manastu.space",
    )
    assert {c: e["unit"] for c, e in new.body["channels"].items()} == {"y0": "bar", "y1": "psi"}
    assert flags["y0"].resolution_rule_id == new.rule_id and flags["y0"].resolved_by == "asha@manastu.space"
    assert (flags["y1"].resolved_by, flags["y1"].resolution["unit"]) == ("ravi@manastu.space", "psi")
    assert result.rebuild_doc_id == seeded["dat"].doc_id and seeded["dat"].status == "PROCESSING"
    event = session.scalars(
        select(AuditEvent).where(
            AuditEvent.entity_id == str(flags["y1"].flag_id), AuditEvent.action == "edit"
        )
    ).one()
    assert (event.actor, event.after["reason"], event.before["resolved_by"]) == (
        "ravi@manastu.space",
        "the rig sheet says psig",
        "asha@manastu.space",
    )
    case_event = session.scalars(
        select(AuditEvent).where(AuditEvent.entity_type == "case", AuditEvent.action == "edit")
    ).one()
    assert case_event.after["reason"] == "the rig sheet says psig"


def test_an_edit_needs_a_decided_telemetry_unit_and_a_reason(session, seeded):
    from pydantic import ValidationError

    from backend.review.api_models import EditRequest

    flags = _open_flags(session, seeded["dat"])
    unit = FlagResolution(
        flag_id=flags["y0"].flag_id,
        resolution=SetUnitModel(channel="y0", unit="psi", quantity="pressure", gauge_or_abs="gauge"),
    )
    with pytest.raises(cases.InvalidAction, match="only a decided flag"):
        cases.edit_case(
            session, f"{seeded['dat'].doc_id}:", EditRequest(resolutions=[unit], reason="because"), "asha"
        )
    with pytest.raises(ValidationError):
        EditRequest(resolutions=[unit], reason="")
    key = f"{seeded['sheet'].doc_id}:"
    flag = session.scalars(select(ReviewFlag).where(ReviewFlag.case_key == key)).one()
    cases.resolve_case(
        session,
        key,
        ResolveRequest(
            resolutions=[FlagResolution(flag_id=flag.flag_id, resolution={"action": "accept_both"})]
        ),
        "asha",
        False,
    )
    with pytest.raises(cases.InvalidAction, match="reopen"):
        cases.edit_case(
            session,
            key,
            EditRequest(
                resolutions=[FlagResolution(flag_id=flag.flag_id, resolution={"action": "ignore"})],
                reason="because",
            ),
            "asha",
        )


def test_folders_start_with_the_ones_that_hold_halted_files_and_can_be_searched(session, seeded):
    first = cases.list_folders(session, "")
    assert [(f.folder_id, f.files, f.waiting) for f in first.items] == [("F-E3", 2, 2)]
    both = cases.list_folders(session, "apu inj")
    assert [(f.folder_id, f.path, f.waiting) for f in both.items] == [
        ("F-E3", f"{ROOT}/E3", 2),
        ("F-E9", f"{ROOT}/E9", 0),
    ]
    assert [f.folder_id for f in cases.list_folders(session, "e9").items] == ["F-E9"]
    assert cases.list_folders(session, "100%").items == []  # a percent sign is text, not a wildcard


def _legacy(session, doc, *channels):
    """The old flow: a folder channel_map rule resumed the file, the pipeline closed its flags (no person)."""
    from backend.postgres.models import TelemetryRun

    rule = Rule(
        rule_type="channel_map",
        origin="operator",
        scope_root=ROOT,
        scope_folder_id="F-E3",
        body={
            "channels": {
                c: {
                    "canonical_name": c,
                    "physical_quantity": "pressure",
                    "unit": "bar",
                    "gauge_or_abs": "gauge",
                }
                for c in channels
            },
            "ambient_condition": "SEA_LEVEL",
        },
        created_by="ai@manastu.space",
    )
    session.add(rule)
    session.flush()
    sha = session.scalar(select(DocumentSource.blob_sha256).where(DocumentSource.doc_id == doc.doc_id))
    session.add(
        TelemetryRun(
            run_uuid=uuid.uuid4(),
            run_label=f"RUN_{doc.title}",
            doc_id=doc.doc_id,
            blob_sha256=sha,
            source_format="labjack_dat",
            channel_map_rule_id=rule.rule_id,
        )
    )
    for flag in _open_flags(session, doc).values():
        flag.status, flag.resolved_by = "AUTO_RESOLVED", "pipeline"
    doc.status, doc.staged_payload_uri = "ACTIVE", None
    session.commit()
    return rule


def test_units_a_rule_applied_without_a_person_can_be_seen_and_confirmed_by_one(session, seeded):
    from backend.review.api_models import EditRequest

    rule = _legacy(session, seeded["dat"], "y0", "y1")
    key = f"{seeded['dat'].doc_id}:"
    detail = cases.case_detail(session, key, False)
    assert sorted(
        (u.channel, u.unit, u.gauge_or_abs, u.rule_created_by, u.rule_active) for u in detail.applied_units
    ) == [
        ("y0", "bar", "gauge", "ai@manastu.space", True),
        ("y1", "bar", "gauge", "ai@manastu.space", True),
    ]
    assert [c.title for c in cases.list_cases(session, CaseFilters(decided=True, q="t01")).items] == [
        "T01.dat"
    ]

    flags = _open_flags(session, seeded["dat"])
    # nothing changed: the person only confirms y0, and corrects y1
    edit = EditRequest(
        resolutions=[
            FlagResolution(
                flag_id=flags["y0"].flag_id,
                resolution=SetUnitModel(
                    channel="y0",
                    unit="bar",
                    quantity="pressure",
                    gauge_or_abs="gauge",
                    ambient_condition="SEA_LEVEL",
                ),
            ),
            FlagResolution(
                flag_id=flags["y1"].flag_id,
                resolution=SetUnitModel(
                    channel="y1", unit="degC", quantity="temperature", gauge_or_abs="n/a"
                ),
            ),
        ],
        reason="y1 is a thermocouple",
    )
    result = cases.edit_case(session, key, edit, "ravi@manastu.space")
    session.commit()
    assert {(f.status, f.resolved_by) for f in flags.values()} == {("RESOLVED", "ravi@manastu.space")}
    approval = session.get(Rule, flags["y1"].resolution_rule_id)
    assert (approval.rule_type, approval.created_by, approval.scope_filename_glob) == (
        "channel_map",
        "ravi@manastu.space",
        "T01.dat",
    )
    assert {c: e["unit"] for c, e in approval.body["channels"].items()} == {"y0": "bar", "y1": "degC"}
    assert result.rebuild_doc_id == seeded["dat"].doc_id and seeded["dat"].status == "PROCESSING"
    event = session.scalars(
        select(AuditEvent).where(
            AuditEvent.entity_id == str(flags["y0"].flag_id), AuditEvent.action == "edit"
        )
    ).one()
    assert (event.before["status"], event.before["resolved_by"], event.after["resolved_by"]) == (
        "AUTO_RESOLVED",
        "pipeline",
        "ravi@manastu.space",
    )
    assert session.get(Rule, rule.rule_id).active is True  # a rule that applies to other files is not touched


def test_reopening_what_a_rule_applied_asks_the_questions_again_and_switches_that_rule_off(session, seeded):
    rule = _legacy(session, seeded["dat"], "y0", "y1")
    flags = _open_flags(session, seeded["dat"])
    result = cases.reopen_flags(
        session,
        f"{seeded['dat'].doc_id}:",
        [f.flag_id for f in flags.values()],
        "nobody checked these",
        "asha",
    )
    session.commit()
    assert {f.status for f in flags.values()} == {"REOPENED"}
    assert result.rebuild_doc_id == seeded["dat"].doc_id
    assert session.get(Rule, rule.rule_id).active is False


def test_a_decided_file_that_did_not_move_on_says_why(session, seeded):
    doc, flag = _unreadable(session)
    flag.status = "RESOLVED"
    doc.metadata_sources = {"error": "S3Error: XMinioStorageFull", "error_transient": True}
    session.commit()
    detail = cases.case_detail(session, flag.case_key, is_admin=False)
    assert (detail.document_status, detail.document_blocking, detail.document_retries) == ("HALTED", 0, True)
    assert detail.document_error == "S3Error: XMinioStorageFull"
    other = cases.case_detail(session, f"{seeded['dat'].doc_id}:", is_admin=False)
    assert (other.document_blocking, other.document_error) == (2, None)  # two channel units still open


def test_the_gate_hands_on_the_document_as_people_decided_it(session, seeded):
    from backend.dispatcher.contract import DocumentFields, ProcessedDocument, ProcessedNode
    from backend.review.staged import gate, own_flags

    doc = _doc(session, "plan.pdf", "PROCESSING", "F-E9", route="A1")
    key = "ab" * 16
    flag = Flag(
        flag_type="LOW_CONFIDENCE_EXTRACTION", severity="SOFT", anchor=FlagAnchor(page=8, content_sha256=key)
    )
    row = upsert_document_flag(session, doc.doc_id, flag, "A1")
    row.status, row.resolution = "RESOLVED", {"action": "set_value", "value": "0.85", "illegible": False}
    session.flush()
    node = ProcessedNode(
        ref="vlm/p8/0",
        node_type="child",
        ordinal=0,
        content="Orifice dia: 0.8? mm",
        page_no=8,
        source="vlm",
        metadata={"handwriting": [{"key": key, "value_raw": "0.8?"}]},
    )
    sha = "ef" * 32
    processed = ProcessedDocument(
        blob_sha256=sha,
        route="A1",
        parser_version=1,
        cir_uri=f"s3://dcl-cir/{sha}/A1/v1/",
        document=DocumentFields(title="plan"),
        nodes=[node],
        flags=[flag],  # the route raises the decided entry again on every run
    )
    result = gate(session, None, doc, processed, stale=own_flags("A1"))
    assert (result.halted, result.document.nodes[0].content) == (False, "Orifice dia: 0.85 mm")
    assert session.get(ReviewFlag, row.flag_id).status == "RESOLVED"


def test_a_page_case_shows_the_whole_reading_with_its_entries(session, seeded):
    import json
    from pathlib import Path

    doc = _doc(session, "trial.pdf", "ACTIVE_WITH_SOFT_FLAGS", "F-E9", route="A1")
    doc.cir_uri = f"s3://dcl-cir/{'ab' * 32}/A1/v1/"
    entries = [("990f59414aba02c459e88cc095c57f31", "Trial Name", "Trial 7.1 (warm-up run")]
    entries.append(("bd38e744b6017b861d9e6754d0d40e7e", "Sample Name", "Sample B-12 (lot 4"))
    for key, label, value in entries:
        crop = ExtractionCrop(
            crop_uri="s3://dcl-assets/pages/x/0011.png", model_value=value, printed_label=label
        )
        flag = Flag(
            flag_type="LOW_CONFIDENCE_EXTRACTION",
            severity="SOFT",
            anchor=FlagAnchor(page=11, content_sha256=key),
            evidence=LowConfidenceEvidence(crops=[crop]),
        )
        upsert_document_flag(session, doc.doc_id, flag, "A1")
    session.commit()
    page = (Path(__file__).parents[2] / "fixtures" / "review" / "sample_page.txt").read_text()
    record = {
        "markdown": page,
        "confidence": 0.9,
        "prompt_version": "transcribe_page.v3",
        "doubtful": [
            {"key": k, "label": label, "value_raw": v, "confidence": 0.9} for k, label, v in entries
        ],
    }
    stored = {f"{doc.cir_uri}pages/11.reading.json": json.dumps(record).encode()}
    detail = cases.case_detail(session, f"{doc.doc_id}:11", False, stored.get)
    reading = detail.page_reading
    assert (reading.page_no, reading.image_uri) == (11, "s3://dcl-assets/pages/x/0011.png")
    assert [p.kind for p in reading.blocks[0].parts] == ["heading", "table", "table", "table", "text"]
    flags = {f.flag_id for f in detail.flags}
    assert [(e.label, e.flag_id in flags, e.located.cell) for e in reading.entries] == [
        ("Trial Name", True, [0, 1]),
        ("Sample Name", True, [7, 1]),
    ]
    assert (
        cases.case_detail(session, f"{doc.doc_id}:11", False, {}.get).page_reading is None
    )  # no reading yet


def test_a_correction_is_kept_shown_survives_a_rerun_and_undo_removes_it(session, seeded):
    import json

    from backend.dispatcher.contract import DocumentFields, ProcessedDocument
    from backend.review.page_reading import block_key
    from backend.review.staged import gate, own_flags

    doc = _doc(session, "sheet.pdf", "ACTIVE_WITH_SOFT_FLAGS", "F-E9", route="A1")
    doc.cir_uri = f"s3://dcl-cir/{'cd' * 32}/A1/v1/"
    table = "<table><tr><td>Time</td><td>T2 [C]</td></tr><tr><td>09:10</td><td>40.25</td></tr></table>"
    entry = Flag(
        flag_type="LOW_CONFIDENCE_EXTRACTION",
        severity="SOFT",
        anchor=FlagAnchor(page=3, content_sha256="ef" * 16),
        evidence=LowConfidenceEvidence(crops=[ExtractionCrop(crop_uri="s3://dcl-assets/p/0003.png")]),
    )
    upsert_document_flag(session, doc.doc_id, entry, "A1")
    session.commit()
    key = f"{doc.doc_id}:3"
    fix = {"action": "set_cell", "block_key": block_key(table), "table": 0, "row": 1, "col": 1}
    fix |= {"old": "40.25", "value": "40.52"}
    cases.resolve_case(session, key, ResolveRequest(corrections=[fix]), "asha@x", is_admin=False)
    session.commit()
    (row,) = session.scalars(select(ReviewFlag).where(ReviewFlag.route == "review")).all()
    assert (row.status, row.case_key, row.resolution["value"]) == ("RESOLVED", key, "40.52")

    stored = {f"{doc.cir_uri}pages/3.reading.json": json.dumps({"markdown": table, "doubtful": []}).encode()}
    shown = cases.case_detail(session, key, False, stored.get).page_reading.blocks[0].parts[0].rows[1][1]
    assert (shown.text, shown.corrected) == ("40.52", True)

    sha = "cd" * 32
    rerun = ProcessedDocument(
        blob_sha256=sha, route="A1", parser_version=1, cir_uri=doc.cir_uri, document=DocumentFields(title="s")
    )
    gate(session, None, doc, rerun, stale=own_flags("A1"))
    gate(session, None, doc, rerun, stale=own_flags("A1"))
    assert session.get(ReviewFlag, row.flag_id).status == "RESOLVED"  # a re-run never closes a correction

    undone = cases.undo_case(session, key, "asha@x")
    session.commit()
    assert (undone.reopened, undone.removed_corrections) == ([], 1)
    assert session.scalars(select(ReviewFlag).where(ReviewFlag.route == "review")).all() == []


def _indexed(session, name, route="A1"):
    """A committed document with a chunk in the index."""
    from backend.postgres.models import DocumentNode

    doc = _doc(session, name, "ACTIVE", "F-E9", route=route)
    doc.indexed_at, doc.search_text = datetime.now(UTC), "card text"
    session.add(
        DocumentNode(doc_id=doc.doc_id, node_type="parent", ordinal=0, content="ITAR text", source="printed")
    )
    session.flush()
    return doc


def _chunks(session, doc):
    from backend.postgres.models import DocumentNode

    return session.scalars(select(DocumentNode.content).where(DocumentNode.doc_id == doc.doc_id)).all()


def test_taking_back_a_blocking_decision_takes_the_content_out_of_the_index_at_once(session, seeded):
    doc = _indexed(session, "itar.pdf")
    evidence = SensitiveEvidence(pattern="ITAR", redacted_preview="marking 'ITAR' on page 1", page=1)
    flag = Flag(flag_type="SENSITIVE_CONTENT", severity="HARD", anchor=FlagAnchor(page=1), evidence=evidence)
    row = upsert_document_flag(session, doc.doc_id, flag, "A1")
    row.status, row.resolution = "RESOLVED", {"action": "approve_internal"}
    row.resolved_by, row.resolved_at = "admin@x", datetime.now(UTC) - timedelta(minutes=1)
    session.commit()
    assert _chunks(session, doc) == ["ITAR text"]
    outcome = cases.undo_case(session, row.case_key, "admin@x")
    session.commit()
    assert (_chunks(session, doc), doc.search_text, outcome.rebuild_doc_id) == ([], None, doc.doc_id)
    assert doc.status == "PROCESSING"  # its rebuild raises the reopened flag and halts it


def test_taking_back_a_non_blocking_decision_keeps_the_file_searchable_until_its_rebuild(session, seeded):
    doc = _indexed(session, "sheet.pdf")
    flag = Flag(
        flag_type="LOW_CONFIDENCE_EXTRACTION",
        severity="SOFT",
        anchor=FlagAnchor(page=1, content_sha256="ab" * 16),
    )
    row = upsert_document_flag(session, doc.doc_id, flag, "A1")
    row.status, row.resolution = "RESOLVED", {"action": "set_value", "value": "1.0"}
    row.resolved_by, row.resolved_at = "asha@x", datetime.now(UTC) - timedelta(minutes=1)
    session.commit()
    cases.undo_case(session, row.case_key, "asha@x")
    session.commit()
    assert (_chunks(session, doc), doc.status) == (["ITAR text"], "PROCESSING")


def test_a_file_that_halts_after_being_indexed_leaves_the_index(session, seeded):
    from backend.dispatcher.contract import DocumentFields, ProcessedDocument
    from backend.review.staged import gate

    class Cir:
        def put(self, key, data, content_type):
            return f"s3://dcl-cir/{key}"

    doc = _indexed(session, "itar2.pdf")
    doc.status = "PROCESSING"
    evidence = SensitiveEvidence(pattern="ITAR", redacted_preview="marking 'ITAR' on page 1", page=1)
    flag = Flag(flag_type="SENSITIVE_CONTENT", severity="HARD", anchor=FlagAnchor(page=1), evidence=evidence)
    sha = "ab" * 32
    processed = ProcessedDocument(
        blob_sha256=sha,
        route="A1",
        parser_version=1,
        cir_uri=f"s3://dcl-cir/{sha}/A1/v1/",
        document=DocumentFields(title="itar2"),
        flags=[flag],
    )
    result = gate(session, Cir(), doc, processed)
    assert (result.halted, doc.status, _chunks(session, doc)) == (True, "HALTED", [])


def test_excluding_a_file_takes_its_content_out_of_the_index(session, seeded):
    doc = _indexed(session, "itar3.pdf")
    evidence = SensitiveEvidence(pattern="ITAR", redacted_preview="marking 'ITAR' on page 1", page=1)
    flag = Flag(flag_type="SENSITIVE_CONTENT", severity="HARD", anchor=FlagAnchor(page=1), evidence=evidence)
    row = upsert_document_flag(session, doc.doc_id, flag, "A1")
    session.commit()
    _resolve(session, row.case_key, row, "exclude")
    session.commit()
    assert (doc.status, _chunks(session, doc)) == ("QUARANTINED", [])
