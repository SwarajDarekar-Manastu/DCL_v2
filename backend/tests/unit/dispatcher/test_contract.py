"""ProcessedDocument contract: JSON round trip (staged payload), fingerprints, references, anchors."""

import uuid

import pytest
from pydantic import ValidationError

from backend.dispatcher.contract import (
    Anchor,
    AnchorError,
    BBox,
    ChannelStats,
    DocumentFields,
    Flag,
    FlagAnchor,
    Mention,
    PageBox,
    ProcessedAsset,
    ProcessedDocument,
    ProcessedNode,
    TelemetryChannelRecord,
    TelemetryRunRecord,
    UnitHash,
    UnitTelemetryEvidence,
    format_anchor,
    parse_anchor,
)
from backend.postgres.enums import (
    AssetKind,
    DocKind,
    FlagSeverity,
    FlagType,
    GaugeOrAbs,
    NodeSource,
    NodeType,
    Route,
    TelemetrySourceFormat,
)

SHA = "ab" * 32
DOC_ID = uuid.UUID("00000000-0000-4000-8000-000000000001")
CIR = f"s3://dcl-cir/{SHA}/C/v1/"


def unit_flag(page=None, sheet="Run 1", channel="AIN0", bbox=None, flag_type=FlagType.UNIT_AMBIGUITY):
    anchor = FlagAnchor(page=page, sheet=sheet, channel=channel, bbox=bbox)
    evidence = UnitTelemetryEvidence(channel=channel or "AIN0", stats=ChannelStats(max=12.4))
    return Flag(flag_type=flag_type, severity=FlagSeverity.HARD, anchor=anchor, evidence=evidence)


def sample(**overrides) -> ProcessedDocument:
    data = dict(
        blob_sha256=SHA,
        route=Route.C,
        parser_version=1,
        cir_uri=CIR + "schema.json",
        document=DocumentFields(title="TP07_T01", doc_kind=DocKind.TELEMETRY_RUN, test_plan_id="TP07"),
        nodes=[
            ProcessedNode(
                ref="run",
                node_type=NodeType.RUN_SUMMARY,
                ordinal=0,
                content="Run TP07_T01, 1 kHz, 42 s",
                source=NodeSource.STRUCTURED,
                sheet_name="Run 1",
                cell_range="A1:D20",
                bboxes=[PageBox(page_no=1, x0=0.1, y0=0.2, x1=0.5, y1=0.3)],
                asset_ref="spark",
            ),
            ProcessedNode(
                ref="run/t",
                parent_ref="run",
                node_type=NodeType.TABLE,
                ordinal=1,
                content="<table/>",
                source=NodeSource.STRUCTURED,
            ),
        ],
        assets=[
            ProcessedAsset(
                ref="spark",
                kind=AssetKind.SPARKLINE,
                minio_uri="s3://dcl-assets/sparklines/r/ain0.png",
                width=200,
                height=40,
            )
        ],
        telemetry_runs=[
            TelemetryRunRecord(
                run_uuid=uuid.UUID("00000000-0000-4000-8000-0000000000aa"),
                run_label="TP07_T01",
                source_format=TelemetrySourceFormat.LABJACK_DAT,
                channels=[
                    TelemetryChannelRecord(
                        canonical_name="pt_101_chamber_bar_abs",
                        raw_name="AIN0",
                        gauge_or_abs=GaugeOrAbs.ABSOLUTE,
                        sparkline_asset_ref="spark",
                    )
                ],
            )
        ],
        mentions=[Mention(node_ref="run", kind="test_run_id", surface="TP07_T01", span_start=4, span_end=12)],
        flags=[unit_flag()],
        unit_hashes=[UnitHash(unit="sheet", key="Run 1", sha256="cd" * 32)],
    )
    data.update(overrides)
    return ProcessedDocument(**data)


# ---------- staged payload ----------


def test_json_round_trip_is_lossless():
    doc = sample()
    restored = ProcessedDocument.model_validate_json(doc.model_dump_json())
    assert restored == doc
    assert restored.flags[0].fingerprint == doc.flags[0].fingerprint


def test_tampered_fingerprint_in_a_staged_payload_is_refused():
    data = sample().model_dump(mode="json")
    data["flags"][0]["fingerprint"] = "0" * 64
    with pytest.raises(ValidationError, match="fingerprint does not match"):
        ProcessedDocument.model_validate(data)


def test_has_hard_flags():
    assert sample().has_hard_flags
    assert not sample(flags=[]).has_hard_flags


# ---------- fingerprints and case keys ----------


def test_fingerprint_is_stable_across_runs_key_order_and_float_noise():
    first = unit_flag(page=4, sheet=None, bbox=BBox(x0=0.1, y0=0.2, x1=0.3, y1=0.4))
    again = Flag.model_validate(
        {
            "severity": "HARD",
            "anchor": {
                "bbox": {"y1": 0.4, "x1": 0.300001, "y0": 0.2, "x0": 0.1},
                "channel": "AIN0",
                "page": 4,
            },
            "flag_type": "UNIT_AMBIGUITY",
            "evidence": {
                "kind": "conflict",
                "subject": "evidence does not matter",
                "a": {"label": "a", "value": "1", "provenance": "x"},
                "b": {"label": "b", "value": "2", "provenance": "y"},
            },
        }
    )
    assert first.fingerprint == again.fingerprint
    assert len(first.fingerprint) == 64


def test_fingerprint_changes_with_anchor_or_type():
    base = unit_flag()
    assert unit_flag(channel="AIN1").fingerprint != base.fingerprint
    assert unit_flag(sheet="Run 2").fingerprint != base.fingerprint
    assert unit_flag(flag_type=FlagType.SCHEMA_UNKNOWN).fingerprint != base.fingerprint


def test_page_or_sheet_feeds_the_case_key():
    assert unit_flag(page=4, sheet=None).page_or_sheet == "4"
    assert unit_flag(sheet="Run 1").page_or_sheet == "Run 1"
    assert unit_flag(sheet=None).page_or_sheet == ""


def test_two_flags_with_one_fingerprint_are_rejected():
    with pytest.raises(ValidationError, match="duplicate flag fingerprint"):
        sample(flags=[unit_flag(), unit_flag()])


# ---------- references ----------


def _node(ref, **kw):
    return ProcessedNode(
        ref=ref, node_type=NodeType.PARENT, ordinal=0, content="x", source=NodeSource.PRINTED, **kw
    )


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"nodes": [_node("a"), _node("a")]}, "duplicate node ref"),
        ({"nodes": [_node("a", parent_ref="missing")]}, "parent_ref 'missing' is not a node"),
        ({"nodes": [_node("a", asset_ref="nope")], "assets": []}, "asset_ref 'nope' is not an asset"),
        (
            {"nodes": [_node("a")], "mentions": [Mention(node_ref="b", kind="id", surface="PT-101")]},
            "node_ref 'b' is not a node",
        ),
        ({"cir_uri": f"s3://dcl-cir/{SHA}/A1/v1/x"}, "cir_uri must start with"),
        ({"cir_uri": f"s3://dcl-cir/{SHA}/C/v2/x"}, "cir_uri must start with"),
    ],
)
def test_broken_references_are_rejected(overrides, message):
    defaults = {"telemetry_runs": [], "mentions": [], "flags": []}
    with pytest.raises(ValidationError, match=message):
        sample(**{**defaults, **overrides})


def test_bbox_must_be_normalized_and_ordered():
    with pytest.raises(ValidationError):
        BBox(x0=0.5, y0=0, x1=0.4, y1=1)
    with pytest.raises(ValidationError):
        PageBox(page_no=1, x0=0, y0=0, x1=612, y1=792)


# ---------- stable anchors ----------

LINKS = {
    "page:12:9f86d081884c7d65": {"page_no": 12, "content_sha256": "9f86d081884c7d65"},
    "line:120:ab12cd34ef56ab78": {"line_start": 120, "content_sha256": "ab12cd34ef56ab78"},
    "t:83500:": {"t_start_ms": 83500},
    "cells:Run 1!A1:D20:0c1d2e3f4a5b6c7d": {
        "sheet_name": "Run 1",
        "cell_range": "A1:D20",
        "content_sha256": "0c1d2e3f4a5b6c7d",
    },
    "page:3:": {"page_no": 3},
}


@pytest.mark.parametrize(("link", "fields"), LINKS.items())
def test_anchor_links_parse_to_field_names_and_back(link, fields):
    assert parse_anchor(link) == fields
    anchor = Anchor.parse(DOC_ID, link)
    assert anchor.locator_fields() == fields
    assert anchor.serialize() == link
    assert format_anchor(fields) == link


def test_link_without_a_hash_part_parses():
    assert parse_anchor("page:7") == {"page_no": 7}


@pytest.mark.parametrize(
    "bad", ["page", "page:0:", "line:x:", "t:-1:", "cells:A1:", "node:12:", "page:1:ABC"]
)
def test_malformed_anchor_links_are_rejected(bad):
    with pytest.raises(AnchorError):
        parse_anchor(bad)


def test_anchor_needs_exactly_one_locator():
    with pytest.raises(ValidationError, match="exactly one"):
        Anchor(doc_id=DOC_ID)
    with pytest.raises(ValidationError, match="exactly one"):
        Anchor(doc_id=DOC_ID, page_no=1, line_start=3)
    with pytest.raises(ValidationError, match="A1 cell_range"):
        Anchor(doc_id=DOC_ID, sheet_name="Run 1")
    assert Anchor(doc_id=DOC_ID, page_no=2, breadcrumb="Report › Results").serialize() == "page:2:"


# ---------- evidence and suggestions ----------


def test_evidence_and_suggestion_parse_by_their_discriminators_from_a_staged_payload():
    flag = Flag.model_validate(
        {
            "flag_type": "SCHEMA_UNKNOWN",
            "severity": "HARD",
            "evidence": {
                "kind": "array_schema",
                "shape": [10000, 4],
                "dtype": "float64",
                "columns": [{"index": 0, "min": 0.0, "max": 9.999}],
            },
            "suggested_resolution": {
                "resolution": {
                    "action": "map_columns",
                    "columns": [{"index": 0, "canonical_name": "t_rel_ms"}],
                },
                "confidence": 0.71,
            },
        }
    )
    assert flag.evidence.columns[0].max == 9.999
    assert flag.suggested_resolution.resolution.action == "map_columns"
    assert Flag.model_validate_json(flag.model_dump_json()) == flag


def test_unknown_evidence_kind_is_refused():
    with pytest.raises(ValidationError):
        Flag.model_validate({"flag_type": "CONFLICT", "severity": "SOFT", "evidence": {"kind": "free_text"}})
