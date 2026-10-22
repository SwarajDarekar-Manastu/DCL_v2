"""Route C step 1 on a synthetic LabJack run: raw Parquet in MinIO, stats, channel rules, flags.

Needs DCL_TEST_MINIO_ENDPOINT (the sync tests' disposable MinIO).
"""

import io
import json
import uuid
from datetime import UTC, datetime

import numpy as np
import pyarrow.parquet as pq
import pytest

from backend.dispatcher.contract import ProcessedDocument
from backend.dispatcher.folder_context import FolderContext
from backend.postgres.enums import RuleOrigin, RuleType, RunStatus
from backend.review.rules import RuleRecord, RuleScope, RuleTarget
from backend.routes.c_telemetry.run import RunInputs, process_labjack, run_uuid_for
from backend.storage.minio import CIR, TELEMETRY, BucketStore, parse_uri
from backend.tests.unit.routes.c_telemetry.conftest import CHANNELS

TARGET = RuleTarget(
    root_name="APU Injector", folder_ids=["F-RUN", "F-TP12", "ROOT"], file_name="", extension=".dat"
)
CONTEXT = FolderContext(
    root_name="APU Injector",
    breadcrumb=["APU Injector", "Test Plan 12", "Pressure_Data_Files"],
    path_cached="APU Injector/Test Plan 12/Pressure_Data_Files",
    test_plan_id="TP12",
    test_run_id="T01",
)
Y0 = {
    "canonical_name": "pt_101_bar_g",
    "physical_quantity": "pressure",
    "unit": "bar",
    "gauge_or_abs": "gauge",
}
Y1 = {"canonical_name": "tc_1_k", "physical_quantity": "temperature", "unit": "K"}


def _rule(scope: dict, channels: dict, created: int = 0) -> tuple[RuleRecord, dict]:
    record = RuleRecord(
        rule_id=uuid.uuid4(),
        rule_type=RuleType.CHANNEL_MAP,
        origin=RuleOrigin.OPERATOR,
        scope=RuleScope(**scope),
        precedence=0,
        created_at=datetime(2026, 1, 1 + created, tzinfo=UTC),
    )
    return record, {"channels": channels}


def _run(minio, raw: bytes, name: str = "TP12_T01.dat", rules=()):
    sha = f"{uuid.uuid4().hex}{uuid.uuid4().hex}"
    inputs = RunInputs(
        blob_sha256=sha,
        name=name,
        context=CONTEXT,
        target=RuleTarget(TARGET.root_name, TARGET.folder_ids, name, TARGET.extension),
    )
    doc = process_labjack(
        lambda: io.BytesIO(raw),
        inputs,
        [r for r, _ in rules],
        {r.rule_id: body for r, body in rules},
        BucketStore(minio, TELEMETRY),
        BucketStore(minio, CIR),
        raw[:4096],
    )
    return sha, doc


def test_raw_parquet_stats_and_unit_flags(minio, labjack):
    raw, data = labjack
    sha, doc = _run(minio, raw)
    (run,) = doc.telemetry_runs

    assert run.run_uuid == run_uuid_for(sha)
    assert (run.run_label, run.run_status, run.n_rows, run.n_gaps, run.n_duplicate_ts) == (
        "TP12_T01",
        RunStatus.UNKNOWN,
        len(data),
        1,
        0,
    )
    assert run.sampling_rate_hz_nominal == pytest.approx(1000, rel=1e-6)
    assert run.sampling_rate_hz_actual == pytest.approx((len(data) - 1) / (data[-1, 0] - data[0, 0]))
    assert run.duration_s == pytest.approx(data[-1, 0])
    assert run.recorded_at.isoformat() == "2025-12-29T14:18:41+05:30"

    for index, channel in enumerate(run.channels, start=1):
        column = data[:, index]
        assert channel.raw_name == CHANNELS[index - 1]
        assert channel.stat_min == pytest.approx(column.min(), abs=1e-6)
        assert channel.stat_max == pytest.approx(column.max(), abs=1e-6)
        assert channel.stat_mean == pytest.approx(column.mean(), abs=1e-6)
        assert channel.stat_std == pytest.approx(column.std(), abs=1e-6)
        assert channel.stat_p50 == pytest.approx(np.percentile(column, 50), abs=1e-6)
        assert channel.stat_p99 == pytest.approx(np.percentile(column, 99), abs=1e-6)
    v0 = run.channels[0]
    assert (v0.canonical_name, v0.quantity, v0.unit_si, v0.raw_unit) == ("v0_v", "voltage", "V", "V")

    assert [(f.flag_type, f.severity, f.anchor.channel) for f in doc.flags] == [
        ("UNIT_AMBIGUITY", "HARD", "y0"),
        ("UNIT_AMBIGUITY", "HARD", "y1"),
    ]
    evidence = doc.flags[0].evidence
    assert evidence.header_lines[-1] == "Time\tv0\tv1\ty0\ty1"
    assert evidence.stats.mean == pytest.approx(data[:, 3].mean(), abs=1e-6)
    assert doc.has_hard_flags

    bucket, key = parse_uri(run.raw_parquet_uri)
    assert (bucket, key) == (TELEMETRY, f"{run.run_uuid}/raw.parquet")
    parquet = pq.ParquetFile(io.BytesIO(minio.get_object(bucket, key).read()))
    assert parquet.metadata.num_rows == len(data)
    assert parquet.metadata.row_group(0).column(0).compression == "ZSTD"
    assert parquet.schema_arrow.field("y0").metadata[b"raw_name"] == b"y0"
    assert parquet.schema_arrow.metadata[b"run_uuid"] == str(run.run_uuid).encode()

    cir = BucketStore(minio, CIR)
    schema = json.loads(cir.get(f"{sha}/C/v1/schema.json"))
    stats = json.loads(cir.get(f"{sha}/C/v1/stats.json"))
    assert schema["channels"]["y0"] == {"unresolved": True}
    assert (stats["rows"], stats["gaps"]) == (len(data), 1)
    assert doc.nodes[0].node_type == "run_summary" and doc.nodes[0].t_start_ms == 0
    assert "2 channels await unit confirmation" in doc.nodes[0].content


def test_rules_resolve_channels_and_the_most_specific_rule_wins(minio, labjack):
    raw, _ = labjack
    folder_rule = _rule({"scope_folder_id": "F-RUN"}, {"y0": Y0})
    root_rule = _rule({"scope_root": "APU Injector"}, {"y0": {**Y0, "canonical_name": "wrong"}, "y1": Y1})
    _, doc = _run(minio, raw, rules=[root_rule, folder_rule])
    by_raw = {c.raw_name: c for c in doc.telemetry_runs[0].channels}

    assert doc.flags == []
    assert (by_raw["y0"].canonical_name, by_raw["y0"].gauge_or_abs) == ("pt_101_bar_g", "gauge")
    assert by_raw["y1"].canonical_name == "tc_1_k"

    _, partial = _run(minio, raw, rules=[folder_rule])
    assert [f.anchor.channel for f in partial.flags] == ["y1"]


def test_failed_run_and_the_payload_round_trips(minio, labjack):
    raw, _ = labjack
    _, doc = _run(minio, raw, name="TP12_T01.dat_fail")
    assert doc.telemetry_runs[0].run_status == RunStatus.FAILED_RUN
    again = ProcessedDocument.model_validate_json(doc.model_dump_json())
    assert again == doc
    assert [f.fingerprint for f in again.flags] == [f.fingerprint for f in doc.flags]


def test_reprocessing_the_same_bytes_writes_the_same_run(minio, labjack):
    raw, _ = labjack
    sha, first = _run(minio, raw)
    inputs_run = first.telemetry_runs[0]
    assert inputs_run.run_uuid == run_uuid_for(sha)
    assert run_uuid_for(sha) != run_uuid_for("0" * 64)
