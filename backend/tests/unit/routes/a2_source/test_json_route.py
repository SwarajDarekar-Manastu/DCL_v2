"""Route A2 JSON (file 03 §A2.1): schema sniffing, section mapping, generic flatten, flags."""

import json

from backend.dispatcher.contract import ProcessedDocument
from backend.postgres.enums import DocKind, FlagSeverity, FlagType, NodeType
from backend.routes.a2_source import json_sections
from backend.routes.a2_source.route import REPORT_SCHEMAS_YAML, can_handle_json, process_json
from backend.tests.unit.routes.a2_source.conftest import primary, source

CONFIG = json_sections.load_schema_config(
    {
        "schemas": [
            {
                "id": "test_report_sections",
                "required_keys": ["test_id"],
                "test_id_key": "test_id",
                "sections": [
                    {"key": "objectives", "title": "Objectives"},
                    {"key": "pre_firing_checklist", "title": "Pre-firing checklist"},
                    {"key": "observations", "title": "Observations"},
                ],
            }
        ],
        "section_file_sets": [
            {"files": [{"file": "objectives.json", "title": "Objectives"}, {"file": "conclusions.json"}]}
        ],
    }
)


def _run(memory, folder, files):
    processed = process_json(
        files, title="Test T01", folder=folder, stores=memory.stores(), schema_config=CONFIG
    )
    assert ProcessedDocument.model_validate_json(processed.model_dump_json()) == processed
    return processed


def test_report_schema_keys_become_sections_with_grouped_steps(memory, folder):
    report = {
        "test_id": "T01",
        "objectives": "Reach 100 s burn.\n\nKeep wall below 900 °C.",
        "pre_firing_checklist": [f"Step {i}" for i in range(1, 11)],
        "observations": {"preheat": "28 W", "chamber": {"peak": "12.4 bar"}},
        "operator": "RM",
    }
    processed = _run(memory, folder, [primary("Sections/t01.json", json.dumps(report))])

    assert processed.document.test_run_id == "T01"
    assert processed.document.doc_kind == DocKind.TEST_REPORT
    crumbs = [n.breadcrumb for n in processed.nodes]
    assert crumbs[:2] == ["Test T01 › Objectives"] * 2
    checklist = [n.content for n in processed.nodes if n.breadcrumb.endswith("Pre-firing checklist")]
    assert checklist == ["\n".join(f"{i}. Step {i}" for i in range(1, 9)), "9. Step 9\n10. Step 10"]
    assert "observations" not in [n.metadata["json_key"] for n in processed.nodes][:2]
    assert {m.surface for m in processed.mentions} == {"100 s", "28 W", "12.4 bar", "900 °C"}
    assert "operator: RM" in processed.nodes[-1].content
    assert processed.flags == []


def test_an_unknown_shape_with_readable_fields_is_indexed_without_a_flag(memory, folder):
    # one report section per file, test_id only in the folder (TP07, 26 Oct): nothing for a person to decide
    data = {"id": "objectives_x", "content": {"text": "Some prose", "tables": []}, "order": 2}
    processed = _run(memory, folder, [primary("Sections/whatever.json", json.dumps(data))])

    assert [n.content for n in processed.nodes] == [
        "id: objectives_x\ncontent.text: Some prose\ncontent.tables: []\norder: 2"
    ]
    assert processed.flags == []


def test_an_unknown_shape_with_nothing_readable_is_soft_schema_unknown(memory, folder):
    data = {"x": None, "y": {}, "z": []}
    processed = _run(memory, folder, [primary("Sections/whatever.json", json.dumps(data))])

    flag = processed.flags[0]
    assert flag.flag_type == FlagType.SCHEMA_UNKNOWN and flag.severity == FlagSeverity.SOFT
    assert flag.evidence.top_level_keys == ["x", "y", "z"]
    assert flag.evidence.missing_keys == ["test_id"]


def test_a_key_mapping_turns_an_unknown_shape_into_named_sections(memory, folder):
    data = {"id": "objectives_x", "content": {"text": "Some prose"}, "order": 2}
    processed = process_json(
        [primary("Sections/whatever.json", json.dumps(data))],
        title="Test T01",
        folder=folder,
        stores=memory.stores(),
        schema_config=CONFIG,
        key_mapping={"content": "Objectives"},
    )
    crumbs = [n.breadcrumb for n in processed.nodes]
    assert crumbs[0] == "Test T01 › Objectives" and "Some prose" in processed.nodes[0].content
    assert crumbs[-1] == "Test T01 › Other fields" and "id: objectives_x" in processed.nodes[-1].content
    assert processed.flags == []


def test_section_file_set_is_one_document_in_order(memory, folder):
    files = [
        primary("Sections/objectives.json", json.dumps({"text": "Objective prose"})),
        source("Sections/conclusions.json", json.dumps(["It worked", "Repeat at 12 bar"])),
    ]
    processed = _run(memory, folder, files)

    assert [n.breadcrumb for n in processed.nodes] == ["Test T01 › Objectives", "Test T01 › conclusions"]
    assert processed.nodes[1].content == "1. It worked\n2. Repeat at 12 bar"
    assert processed.flags == []


def test_data_array_and_config_shapes(memory, folder):
    records = [{"time": i * 0.1, "pc": 1.0 + i} for i in range(30)]
    config = {"channels": ["AIN0", "AIN1"], "sampling_rate": 1000}
    assert json_sections.sniff(records, "run.json", CONFIG).shape == "data_array"
    assert json_sections.sniff([1, 2, 3], "a.json", CONFIG).shape == "data_array"
    processed = _run(memory, folder, [primary("cfg.json", json.dumps(config))])

    assert processed.document.doc_kind == DocKind.CONFIG
    assert processed.nodes[0].node_type == NodeType.CONFIG
    assert processed.document.catalog["json_shapes"]["cfg.json"]["shape"] == "config"


def test_invalid_json_is_a_hard_parse_failure(memory, folder):
    processed = _run(memory, folder, [primary("broken.json", '{"a": ')])
    assert processed.flags[0].flag_type == FlagType.PARSE_FAILURE
    assert processed.has_hard_flags


def test_flatten_limits_depth_and_long_lists():
    lines = json_sections.flatten({"a": {"b": {"c": {"d": {"e": 1}}}}, "xs": list(range(25))})
    assert lines[0] == "a.b.c.d: {1 keys: e}"
    assert lines[1].startswith("xs: [0, 1, 2") and lines[1].endswith("… (25 items)]")


def test_repository_schema_file_loads_and_adapter_predicate():
    config = json_sections.read_schema_config(REPORT_SCHEMAS_YAML)
    assert config.schemas and config.section_titles
    assert can_handle_json(b'\xef\xbb\xbf  {"a": 1}', "x.JSON")
    assert not can_handle_json(b"PK\x03\x04", "x.json")
