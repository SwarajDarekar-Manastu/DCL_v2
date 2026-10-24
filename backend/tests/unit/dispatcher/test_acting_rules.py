"""Rules that act (user, 2026-10-24, option A; plan task 4): a preset rule made once resolves the same kind of
flag on a second, different file without a click; switching it off takes it back; decisions change the data.

Needs DCL_TEST_DATABASE_URL and DCL_TEST_MINIO_ENDPOINT.
"""

from sqlalchemy import select

from backend.dispatcher.contract import (
    ConflictEvidence,
    ConflictSide,
    DocumentFields,
    Flag,
    FlagAnchor,
    ProcessedNode,
)
from backend.dispatcher.routing import dispatch
from backend.postgres.enums import FlagSeverity, FlagType, NodeSource, NodeType, SourceOrigin
from backend.postgres.models import Document, DocumentNode, ReviewFlag
from backend.review import cases
from backend.review.api_models import FlagResolution, ResolveRequest, RuleDraft, RulePreviewRequest
from backend.review.rules import RuleScope
from backend.tests.unit.dispatcher.test_dispatch import _file
from backend.tests.unit.dispatcher.test_runner_flags_and_fields import _document, _run

INCOMPLETE = Flag(
    flag_type=FlagType.CONFLICT,
    severity=FlagSeverity.SOFT,
    anchor=FlagAnchor(content_sha256="9" * 64),
    evidence=ConflictEvidence(
        subject="diagram graph incomplete: unlabeled edges",
        relation="check_failed",
        a=ConflictSide(label="unlabeled edges", value="13 of 13", provenance="parsed diagram"),
        b=ConflictSide(label="limit", value="at most 30%", provenance="file 06 §4"),
    ),
)
IGNORE_INCOMPLETE = RuleDraft(
    rule_type="ignore_pattern",
    scope=RuleScope(scope_folder_id="F-TP12"),
    body={
        "reason": "dimensioned drawings have free dimension lines",
        "flag_type": "CONFLICT",
        "relation": "check_failed",
        "subject_contains": "graph incomplete",
    },
)
FIELDS = DocumentFields(title="tool")


def _second(session, minio) -> Document:
    _file(session, minio, "s2", "F-TP12", "tool2.py", b"def other():\n    return 2\n", "text/x-python")
    session.commit()
    (release,) = dispatch(session, minio, section_file_sets=()).to_process
    return session.get(Document, release.doc_id)


def _flag(session, document) -> ReviewFlag:
    (row,) = session.scalars(select(ReviewFlag).where(ReviewFlag.doc_id == document.doc_id)).all()
    return row


def _rebuild(session, minio, document, flags):
    """What the rebuild task does for a document an acting rule queued (status PROCESSING)."""
    assert document.status == "PROCESSING"
    return _run(session, minio, document, FIELDS, flags, [])


def test_a_rule_made_once_resolves_the_same_finding_on_a_second_file_without_a_click(session, minio):
    first = _document(session, minio)
    assert _run(session, minio, first, FIELDS, [INCOMPLETE], []).status == "ACTIVE_WITH_SOFT_FLAGS"
    flag = _flag(session, first)
    cases.resolve_case(
        session,
        flag.case_key,
        ResolveRequest(resolutions=[FlagResolution(flag_id=flag.flag_id, resolution={"action": "ignore"})]),
        "reviewer@test",
        is_admin=False,
    )
    rule = cases.create_rule(session, IGNORE_INCOMPLETE, "reviewer@test")
    session.commit()

    second = _second(session, minio)
    assert _run(session, minio, second, FIELDS, [INCOMPLETE], []).status == "ACTIVE"  # nobody clicked
    answered = _flag(session, second)
    assert (answered.status, answered.resolution, answered.resolution_rule_id, answered.resolved_by) == (
        "AUTO_RESOLVED",
        {"action": "ignore"},
        rule.rule_id,
        "rule",
    )
    assert _flag(session, first).status == "RESOLVED"  # the person's own decision is untouched


def test_saving_a_rule_resolves_files_already_processed_and_switching_it_off_takes_it_back(session, minio):
    first = _document(session, minio)
    _run(session, minio, first, FIELDS, [INCOMPLETE], [])
    second = _second(session, minio)
    _run(session, minio, second, FIELDS, [INCOMPLETE], [])

    preview = cases.preview_rule(
        session,
        RulePreviewRequest(
            rule_type="ignore_pattern", scope=IGNORE_INCOMPLETE.scope, body=IGNORE_INCOMPLETE.body
        ),
    )
    assert (preview.effect, preview.resolves_flags, preview.matched_documents) == ("resolves", 2, 2)

    rule = cases.create_rule(session, IGNORE_INCOMPLETE, "reviewer@test")
    effect = cases.apply_rule(session, rule)
    session.commit()
    assert (effect.resolved_flags, sorted(effect.rebuild)) == (2, sorted([first.doc_id, second.doc_id]))
    for document in (first, second):
        assert _rebuild(session, minio, document, [INCOMPLETE]).status == "ACTIVE"

    rule, effect = cases.switch_off_rule(session, rule.rule_id, "reviewer@test")
    session.commit()
    assert (effect.reopened_flags, len(effect.rebuild)) == (2, 2)
    for document in (first, second):
        assert _flag(session, document).status == "OPEN"
        assert _rebuild(session, minio, document, [INCOMPLETE]).status == "ACTIVE_WITH_SOFT_FLAGS"


def test_a_flag_a_person_reopened_waits_for_that_person_even_when_a_rule_matches(session, minio):
    document = _document(session, minio)
    _run(session, minio, document, FIELDS, [INCOMPLETE], [])
    flag = _flag(session, document)
    flag.status = "REOPENED"
    cases.create_rule(session, IGNORE_INCOMPLETE, "reviewer@test")
    session.commit()
    document.status = "PROCESSING"
    session.commit()
    assert _run(session, minio, document, FIELDS, [INCOMPLETE], []).status == "ACTIVE_WITH_SOFT_FLAGS"
    assert _flag(session, document).status == "REOPENED"


def test_a_source_choice_rule_decides_which_test_plan_id_the_document_keeps(session, minio):
    cases.create_rule(
        session,
        RuleDraft(
            rule_type="source_choice",
            scope=RuleScope(scope_folder_id="F-TP12"),
            body={"subject": "test_plan_id", "prefer": "content"},
        ),
        "reviewer@test",
    )
    session.commit()
    document = _document(session, minio)
    assert document.test_plan_id == "TP12"  # from the folder
    outcome = _run(session, minio, document, DocumentFields(title="tool", test_plan_id="TP37"), [], [])
    session.refresh(document)
    flag = _flag(session, document)
    assert (flag.status, flag.resolution) == ("AUTO_RESOLVED", {"action": "choose_source", "choice": "B"})
    assert (outcome.status, document.test_plan_id) == ("ACTIVE", "TP37")


def test_an_origin_override_rule_changes_the_document_and_its_nodes(session, minio):
    cases.create_rule(
        session,
        RuleDraft(
            rule_type="origin_override",
            scope=RuleScope(scope_folder_id="F-TP12"),
            body={"source_origin": "external_kept", "trust_tier": 4},
        ),
        "reviewer@test",
    )
    session.commit()
    document = _document(session, minio)
    node = ProcessedNode(
        ref="m",
        node_type=NodeType.PARENT,
        ordinal=0,
        breadcrumb="tool",
        content="x",
        source=NodeSource.PRINTED,
    )
    _run(session, minio, document, FIELDS, [], [], nodes=[node])
    session.refresh(document)
    assert (document.source_origin, document.trust_tier) == (SourceOrigin.EXTERNAL_KEPT, 4)
    rows = session.scalars(select(DocumentNode).where(DocumentNode.doc_id == document.doc_id)).all()
    assert {(r.source_origin, r.trust_tier) for r in rows} == {("external_kept", 4)}
