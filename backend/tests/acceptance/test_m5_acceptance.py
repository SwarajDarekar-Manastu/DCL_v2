"""M5 acceptance (file 10 §5) over Route A1's stored crops, table crops, figure readings and contact
sheets. Read-only; see M5.md."""


def test_crops_have_a_sane_size_and_page_share(m5, live_session):
    assert m5.crop_violations(live_session) == []


def test_every_a1_table_node_has_a_table_crop(m5, live_session):
    assert m5.table_crop_violations(live_session) == []


def test_every_a1_figure_node_has_content(m5, live_session):
    assert m5.figure_content_violations(live_session) == []


def test_every_a1_document_has_a_contact_sheet(m5, live_session, live_minio_exists):
    assert m5.contact_sheet_violations(live_session, live_minio_exists) == []
