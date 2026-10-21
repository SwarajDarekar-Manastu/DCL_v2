"""pipeline_config: versions, current value view, gate seeding from config/gate.yaml, scopes."""

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.postgres import pipeline_config as pc
from backend.sync.gate import GateConfig


@pytest.fixture()
def session(migrated):
    with Session(migrated) as s:
        yield s


def test_set_appends_versions_and_get_returns_the_latest(session):
    assert pc.set_value(session, "sync.download_concurrency", 8, "ops@x") == 1
    assert pc.set_value(session, "sync.download_concurrency", 4, "ops@x") == 2
    assert pc.set_value(session, "sync.download_concurrency", 8, "ops@x", "rollback to v1") == 3
    session.commit()
    assert pc.get(session, "sync.download_concurrency") == 8
    rows = session.execute(text("SELECT key, version, value FROM v_config_current")).all()
    assert [tuple(r) for r in rows] == [("sync.download_concurrency", 3, 8)]


def test_missing_key_raises_unless_a_default_is_given(session):
    with pytest.raises(pc.ConfigMissing):
        pc.get(session, "nothing.here")
    assert pc.get(session, "nothing.here", default=None) is None


def test_gate_from_the_table_equals_the_yaml_after_seeding(session):
    yaml_gate = pc.load_gate_yaml()
    written = pc.seed_gate(session, yaml_gate)
    session.commit()
    assert set(written) == {f"gate.{k}" for k in yaml_gate}
    assert pc.gate_config(session) == GateConfig.from_mapping(yaml_gate)


def test_first_start_seed_is_idempotent_and_reseed_writes_only_differences(session):
    yaml_gate = pc.load_gate_yaml()
    pc.seed_gate(session, yaml_gate)
    pc.set_value(session, "gate.max_download_bytes", 1024, "admin@x")  # edited in the Settings UI
    assert pc.seed_gate(session, yaml_gate) == []
    assert pc.gate_config(session).max_download_bytes == 1024
    assert pc.seed_gate(session, yaml_gate, reseed=True) == ["gate.max_download_bytes"]
    assert pc.gate_config(session).max_download_bytes == yaml_gate["max_download_bytes"]


def test_unseeded_gate_is_refused(session):
    with pytest.raises(pc.ConfigMissing, match="seed-gate"):
        pc.gate_config(session)


def test_a_gate_mapping_the_gate_cannot_use_is_not_seeded(session):
    with pytest.raises(ValueError):
        pc.seed_gate(session, {"junk_extensions": [0.1], "max_download_bytes": 1})


def test_empty_or_missing_scopes_mean_everything(session):
    assert pc.download_scope(session) == []
    assert pc.processing_scope(session) == []
    pc.set_value(session, pc.PROCESSING_SCOPE, ["APU Injector/Test Plan 30/*"], "s5")
    assert pc.processing_scope(session) == ["APU Injector/Test Plan 30/*"]


def test_sanity_ranges_seed_once_and_reseed_only_on_change(session):
    assert pc.seed_sanity_ranges(session) is True
    seeded = pc.sanity_ranges(session)
    assert seeded["version"] == 2 and seeded["ranges"]
    assert pc.seed_sanity_ranges(session) is False
    assert pc.seed_sanity_ranges(session, reseed=True) is False
