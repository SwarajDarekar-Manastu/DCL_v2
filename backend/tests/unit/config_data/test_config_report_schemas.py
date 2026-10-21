"""config/report_json_schemas.yaml loads and its match rule separates a report-section JSON from
a configuration JSON."""

import jsonschema
import pytest

SCHEMA = {
    "type": "object",
    "required": ["version", "schemas", "section_file_sets"],
    "additionalProperties": False,
    "properties": {
        "version": {"const": 1},
        "schemas": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "required": ["id", "description", "required_keys", "sections", "source", "sme_confirmed"],
                "additionalProperties": False,
                "properties": {
                    "id": {"type": "string", "pattern": "^[a-z0-9_]+$"},
                    "description": {"type": "string"},
                    "required_keys": {"type": "array", "minItems": 1, "items": {"type": "string"}},
                    "test_id_key": {"type": "string"},
                    "sections": {
                        "type": "array",
                        "minItems": 1,
                        "items": {
                            "type": "object",
                            "required": ["key", "title"],
                            "additionalProperties": False,
                            "properties": {
                                "key": {"type": "string"},
                                "title": {"type": "string", "minLength": 1},
                            },
                        },
                    },
                    "source": {"type": "string"},
                    "sme_confirmed": {"type": "boolean"},
                },
            },
        },
        "section_file_sets": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["id", "description", "files", "source", "sme_confirmed"],
                "additionalProperties": False,
                "properties": {
                    "id": {"type": "string", "pattern": "^[a-z0-9_]+$"},
                    "description": {"type": "string"},
                    "files": {
                        "type": "array",
                        "minItems": 2,
                        "items": {
                            "type": "object",
                            "required": ["file", "title"],
                            "additionalProperties": False,
                            "properties": {
                                "file": {"type": "string", "pattern": r"^[a-z0-9_]+\.json$"},
                                "title": {"type": "string", "minLength": 1},
                            },
                        },
                    },
                    "source": {"type": "string"},
                    "sme_confirmed": {"type": "boolean"},
                },
            },
        },
    },
}


@pytest.fixture(scope="module")
def data(load_config):
    return load_config("report_json_schemas.yaml")


def matches(schema, doc: dict) -> bool:
    return set(schema["required_keys"]) <= set(doc)


def test_schema(data):
    jsonschema.validate(data, SCHEMA)


def test_ids_keys_and_files_unique(data):
    ids = [s["id"] for s in data["schemas"]] + [s["id"] for s in data["section_file_sets"]]
    assert len(ids) == len(set(ids))
    for s in data["schemas"]:
        keys = [x["key"] for x in s["sections"]]
        assert len(keys) == len(set(keys))
        if "test_id_key" in s:
            assert s["test_id_key"] in s["required_keys"]
    for fs in data["section_file_sets"]:
        files = [f["file"] for f in fs["files"]]
        assert len(files) == len(set(files))


def test_manual_example_keys_are_covered(data):
    # 03 §A2.1 step 1 example: {objectives, pre_firing_checklist, emergency_procedures,
    # observations, conclusions, test_id}; 03 §1.3 section files.
    s = next(x for x in data["schemas"] if x["id"] == "test_report_sections")
    assert {"objectives", "pre_firing_checklist", "emergency_procedures", "observations", "conclusions"} == {
        x["key"] for x in s["sections"]
    }
    fs = next(x for x in data["section_file_sets"] if x["id"] == "test_report_section_files")
    assert [f["file"] for f in fs["files"]] == [
        "objectives.json",
        "checklist.json",
        "observations.json",
        "conclusions.json",
    ]


def test_report_json_matches_and_config_json_does_not(data):
    s = next(x for x in data["schemas"] if x["id"] == "test_report_sections")
    report = {
        "test_id": "T01",
        "objectives": ["Verify ignition"],
        "observations": ["Nominal"],
        "conclusions": "Pass",
    }
    config = {"channels": [{"name": "AIN0"}], "sampling_rate": 1000, "scaling": {"AIN0": [50, -25]}}
    assert matches(s, report)
    assert not matches(s, config)
