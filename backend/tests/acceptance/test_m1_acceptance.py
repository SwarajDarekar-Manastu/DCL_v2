"""M1 acceptance (file 10 §5): the criteria that the registry state alone can prove.
The event-driven criteria are procedures in M1.md."""


def test_crawl_counts_match_the_inventory(m1, live_session):
    assert m1.band_violations(m1.item_counts(live_session)) == []


def test_every_item_is_decided_with_a_reason(m1, live_session):
    assert m1.decision_violations(m1.item_counts(live_session)) == []


def test_all_accepted_items_download(m1, live_session):
    assert m1.download_scope(live_session) == []
    assert m1.download_violations(m1.item_counts(live_session)) == []


def test_processing_scope_is_the_decided_allowlist(m1, live_session):
    decided = m1.decided_allowlist()
    assert len(decided) == 11, "DECISIONS.md 'Processing allowlist' row: E1-E11"
    assert sorted(m1.processing_scope(live_session)) == sorted(decided)


def test_only_the_allowlist_is_dispatched(m1, live_session):
    assert m1.out_of_scope_documents(live_session) == []
