"""M2 acceptance (file 10 §5) over Route C's live result, and the TP7 footer CONFLICT (file 03 §1.2).
Read-only; see M2.md."""


def test_tp7_footer_raises_a_test_plan_conflict(m2, live_session):
    assert m2.tp7_violations(live_session) == []


def test_route_c_status_counts(m2, live_session):
    assert m2.status_count_violations(m2.route_c_status_counts(live_session)) == []


def test_route_c_status_agrees_with_open_flags(m2, live_session):
    assert m2.flag_status_violations(live_session) == []


def test_every_halted_series_is_a_unit_case_with_evidence(m2, live_session):
    assert m2.unit_case_violations(live_session, require_suggestion=False) == []


def test_every_unit_case_has_a_suggestion(m2, live_session):
    assert m2.unit_case_violations(live_session, require_suggestion=True) == []


def test_one_committed_run(m2, live_session):
    assert m2.run_count_violations(m2.committed_runs(live_session)) == []


def test_committed_runs_have_si_parquet_columns(m2, live_session, live_minio):
    assert m2.si_column_violations(live_session, m2.committed_runs(live_session), live_minio) == []


def test_flags_are_not_duplicated(m2, live_session):
    assert m2.duplicate_flag_violations(live_session) == []
