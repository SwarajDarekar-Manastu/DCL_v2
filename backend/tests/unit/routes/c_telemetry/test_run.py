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
from backend.routes.c_telemetry.normalize import sanity_ranges_from
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


def _run(minio, raw: bytes, name: str = "TP12_T01.dat", rules=(), folder_config=None, sanity=()):
    sha = f"{uuid.uuid4().hex}{uuid.uuid4().hex}"
    inputs = RunInputs(
        blob_sha256=sha,
        name=name,
        context=CONTEXT,
        target=RuleTarget(TARGET.root_name, TARGET.folder_ids, name, TARGET.extension),
        folder_config=folder_config,
    )
    doc = process_labjack(
        lambda: io.BytesIO(raw),
        inputs,
        [r for r, _ in rules],
        {r.rule_id: body for r, body in rules},
        BucketStore(minio, TELEMETRY),
        BucketStore(minio, CIR),
        raw[:4096],
        sanity=sanity,
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
    assert schema["channels"]["y0"] == {"unresolved": True, "note": "the file states no unit"}
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


def test_the_folder_cfg_scaling_is_evidence_not_a_mapping(minio, labjack):
    from backend.routes.c_telemetry.ljstream_cfg import parse_ljstream_cfg
    from backend.routes.c_telemetry.run import FolderConfig

    cfg = parse_ljstream_cfg(
        "[Main]\nScanRate=1000\nNumChan=2\nScaling=y=a*24.943-12.385#!#y=b*50.044#!#y=c#!#"
    )
    raw, _ = labjack
    sha, doc = _run(minio, raw, folder_config=FolderConfig("LJStreamM.cfg", cfg))
    assert [f.anchor.channel for f in doc.flags] == ["y0", "y1"]  # still HARD: no unit stated anywhere
    y0 = doc.flags[0].evidence
    assert (y0.scaling_equation, y0.scaling_source) == ("y=a*24.943-12.385", "LJStreamM.cfg")
    schema = json.loads(BucketStore(minio, CIR).get(f"{sha}/C/v1/schema.json"))
    assert schema["folder_config"]["equations"] == {"y0": "y=a*24.943-12.385", "y1": "y=b*50.044"}


SANITY = sanity_ranges_from(
    {
        "ranges": [
            {
                "id": "chamber_pressure",
                "physical_quantity": "pressure",
                "canonical_name_glob": "*chamber*",
                "unit": "bar",
                "min": 0,
                "max": 150,
            },
            {
                "id": "temperature",
                "physical_quantity": "temperature",
                "canonical_name_glob": "*",
                "unit": "K",
                "min": 200,
                "max": 2000,
            },
        ]
    }
)


def _mapped(unit: str):
    return _rule(
        {"scope_folder_id": "F-RUN"},
        {
            "y0": {
                "canonical_name": "pt_101_chamber_bar_g",
                "physical_quantity": "pressure",
                "unit": unit,
                "gauge_or_abs": "gauge",
            },
            "y1": {"canonical_name": "tc_1_k", "physical_quantity": "temperature", "unit": "degC"},
        },
    )


def test_a_fully_mapped_run_is_normalized_and_catalogued_in_si(minio, labjack):
    raw, data = labjack
    record, body = _mapped("bar")
    body["ambient_condition"] = "SEA_LEVEL"
    _, doc = _run(minio, raw, rules=[(record, body)], sanity=SANITY)
    (run,) = doc.telemetry_runs

    assert doc.flags == [] or not doc.has_hard_flags
    assert (run.ambient_condition, run.ambient_pressure_bar_abs) == ("SEA_LEVEL", None)
    bucket, key = parse_uri(run.normalized_parquet_uri)
    assert key == f"{run.run_uuid}/normalized.parquet"
    table = pq.read_table(io.BytesIO(minio.get_object(bucket, key).read()))
    assert table.column_names == [
        "t_rel_ms",
        "t_from_ignition_ms",
        "v0_v",
        "v1_v",
        "pt_101_chamber_bar_g",
        "pt_101_chamber_bar_abs",
        "tc_1_k",
    ]
    by = {c.canonical_name: c for c in run.channels}
    assert by["pt_101_chamber_bar_abs"].stat_mean == pytest.approx(data[:, 3].mean() + 1.01325, abs=1e-6)
    assert (by["pt_101_chamber_bar_abs"].gauge_or_abs, by["pt_101_chamber_bar_g"].gauge_or_abs) == (
        "absolute",
        "gauge",
    )
    assert by["tc_1_k"].stat_min == pytest.approx(data[:, 4].min() + 273.15, abs=1e-6)
    assert by["tc_1_k"].unit_si == "kelvin" and by["pt_101_chamber_bar_g"].peak_raw is not None
    assert by["pt_101_chamber_bar_g"].conversion["abs_column"] == "pt_101_chamber_bar_abs"
    assert "channels: pt_101_chamber_bar_g pressure (bar" in doc.nodes[0].content


def test_a_value_outside_its_sanity_range_after_conversion_halts(minio, labjack):
    raw, _ = labjack
    _, doc = _run(minio, raw, rules=[_mapped("ksi")], sanity=SANITY)  # ~12 ksi is ~830 bar: not a chamber
    (flag,) = doc.flags
    assert (flag.flag_type, flag.severity, flag.anchor.channel) == ("UNIT_AMBIGUITY", "HARD", "y0")
    assert flag.evidence.sanity.max == 150 and "chamber_pressure" in flag.evidence.note
    assert flag.evidence.header_lines[-1].startswith("Time")
    assert doc.telemetry_runs[0].normalized_parquet_uri is None
