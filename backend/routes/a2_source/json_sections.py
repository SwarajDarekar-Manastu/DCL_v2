"""Report JSON (file 03 §A2.1): schema sniffing, key → section mapping, generic flatten.

``sniff`` names the shape of a parsed file:
- ``report_section``: a schema of ``config/report_json_schemas.yaml`` whose required keys are all present;
  its keys become sections in the schema's order, ``test_id_key`` sets ``test_run_id``.
- ``section_file``: the file name is in a ``section_file_sets`` entry (the assembler grouped the set);
  the file is one section titled by the set entry.
- ``data_array``: numbers, or records with a time key (Route C's input; recorded so the dispatcher can
  route it there).
- ``config``: keys like ``channels``, ``sampling_rate``, ``scaling`` (a ``config`` node and a candidate
  channel map for Route C).
- ``unknown``: generic flatten (``path.to.key: value``, depth ≤ 4, lists summarized beyond 20 items) and
  ``SCHEMA_UNKNOWN`` SOFT.

Lists of steps become numbered lines, one child node per ~8 steps. Numbers with units in strings
(``"preheat": "28 W"``) become ``quantity`` mentions.
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any

import yaml

STEPS_PER_NODE = 8
FLATTEN_DEPTH = 4
LIST_SUMMARY_AFTER = 20
TIME_KEYS = frozenset({"t", "time", "time_s", "time_ms", "timestamp", "ts", "elapsed", "seconds"})
CONFIG_KEYS = frozenset(
    {"channels", "sampling_rate", "sample_rate", "scaling", "scan_rate", "resolution", "range", "gain"}
)
QUANTITY = re.compile(
    r"(?<![\w.])[-+]?\d+(?:[.,]\d+)?\s?(?:bar[ga]?|psi[ga]?|k?Pa|MPa|°C|degC|K|W|kW|V|mV|A|mA|N|kN|g/s|kg/s|"
    r"g|kg|mg|s|ms|min|h|Hz|kHz|mm|cm|m|%|Ns|L|mL)(?![\w])"
)


@dataclass(frozen=True)
class ReportSchema:
    id: str
    required_keys: tuple[str, ...]
    sections: tuple[tuple[str, str], ...]
    test_id_key: str | None = None


@dataclass(frozen=True)
class SchemaConfig:
    schemas: tuple[ReportSchema, ...] = ()
    section_titles: Mapping[str, str] = field(default_factory=dict)  # file name (casefold) → title


def load_schema_config(data: Mapping[str, Any]) -> SchemaConfig:
    schemas = tuple(
        ReportSchema(
            id=spec["id"],
            required_keys=tuple(spec.get("required_keys", [])),
            sections=tuple((s["key"], s.get("title", s["key"])) for s in spec.get("sections", [])),
            test_id_key=spec.get("test_id_key"),
        )
        for spec in data.get("schemas", [])
    )
    titles = {
        entry["file"].casefold(): entry.get("title", PurePosixPath(entry["file"]).stem)
        for spec in data.get("section_file_sets", [])
        for entry in spec.get("files", [])
    }
    return SchemaConfig(schemas, titles)


def read_schema_config(path) -> SchemaConfig:
    with open(path, encoding="utf-8") as handle:
        return load_schema_config(yaml.safe_load(handle) or {})


@dataclass
class Section:
    title: str
    lines: list[list[str]]  # one inner list per child node
    key: str | None = None


@dataclass
class Sniffed:
    shape: str
    schema_id: str | None = None
    test_run_id: str | None = None
    sections: list[Section] = field(default_factory=list)
    top_level_keys: list[str] = field(default_factory=list)
    flattened: list[str] = field(default_factory=list)
    closest_schema: str | None = None
    missing_keys: list[str] = field(default_factory=list)


def _humanize(key: str) -> str:
    return re.sub(r"\s+", " ", key.replace("_", " ").replace("-", " ")).strip().capitalize()


def _scalar(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def flatten(value: Any, prefix: str = "", depth: int = 0) -> list[str]:
    """``path.to.key: value`` lines, depth ≤ 4, lists beyond 20 items summarized."""
    if isinstance(value, Mapping):
        if not value:
            return [f"{prefix}: {{}}"] if prefix else []
        if depth >= FLATTEN_DEPTH:
            return [f"{prefix}: {{{len(value)} keys: {', '.join(map(str, list(value)[:10]))}}}"]
        lines = []
        for key, item in value.items():
            lines += flatten(item, f"{prefix}.{key}" if prefix else str(key), depth + 1)
        return lines
    if isinstance(value, list):
        if not value:
            return [f"{prefix}: []"]
        if all(not isinstance(v, (Mapping, list)) for v in value):
            shown = ", ".join(_scalar(v) for v in value[:LIST_SUMMARY_AFTER])
            more = f" … ({len(value)} items)" if len(value) > LIST_SUMMARY_AFTER else ""
            return [f"{prefix}: [{shown}{more}]"]
        if depth >= FLATTEN_DEPTH:
            return [f"{prefix}: [{len(value)} items]"]
        lines = []
        for i, item in enumerate(value[:LIST_SUMMARY_AFTER]):
            lines += flatten(item, f"{prefix}[{i}]", depth + 1)
        if len(value) > LIST_SUMMARY_AFTER:
            lines.append(f"{prefix}: … {len(value) - LIST_SUMMARY_AFTER} more items")
        return lines
    text = _scalar(value)
    return [f"{prefix}: {text}" if prefix else text]


def section_lines(value: Any) -> list[list[str]]:
    """A section's value as child groups: prose paragraphs, numbered steps in groups of 8, or flattened."""
    if isinstance(value, str):
        paragraphs = [p.strip() for p in re.split(r"\n\s*\n", value) if p.strip()]
        return [[p] for p in paragraphs]
    if isinstance(value, list) and value and all(isinstance(v, (str, int, float)) for v in value):
        steps = [f"{i}. {v}" for i, v in enumerate(value, 1)]
        return [steps[i : i + STEPS_PER_NODE] for i in range(0, len(steps), STEPS_PER_NODE)]
    if isinstance(value, list) and value and all(isinstance(v, Mapping) for v in value):
        groups = []
        steps = [f"{i}. " + "; ".join(flatten(v)) for i, v in enumerate(value, 1)]
        for i in range(0, len(steps), STEPS_PER_NODE):
            groups.append(steps[i : i + STEPS_PER_NODE])
        return groups
    lines = flatten(value)
    return [lines] if lines else []


def _is_data_array(data: Any) -> bool:
    if isinstance(data, list) and len(data) >= 2:
        if all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in data):
            return True
        if all(isinstance(v, list) and v and all(isinstance(x, (int, float)) for x in v) for v in data):
            return True
        if all(isinstance(v, Mapping) for v in data):
            keys = {str(k).casefold() for k in data[0]}
            return bool(keys & TIME_KEYS)
    if isinstance(data, Mapping) and data:
        arrays = [v for v in data.values() if isinstance(v, list) and len(v) >= 2]
        if arrays and all(all(isinstance(x, (int, float)) for x in v) for v in arrays):
            return {str(k).casefold() for k in data} & TIME_KEYS != set() or len(arrays) == len(data)
    return False


def sniff(data: Any, file_name: str, config: SchemaConfig) -> Sniffed:
    keys = [str(k) for k in data] if isinstance(data, Mapping) else []
    if isinstance(data, Mapping):
        for schema in config.schemas:
            if schema.required_keys and all(k in data for k in schema.required_keys):
                sections = [
                    Section(title, section_lines(data[key]), key)
                    for key, title in schema.sections
                    if key in data and data[key] not in (None, "", [], {})
                ]
                known = {key for key, _ in schema.sections} | set(schema.required_keys)
                extra = {k: v for k, v in data.items() if k not in known}
                if extra:
                    sections.append(Section("Other fields", [flatten(extra)]))
                test_id = data.get(schema.test_id_key) if schema.test_id_key else None
                return Sniffed(
                    "report_section",
                    schema_id=schema.id,
                    test_run_id=str(test_id) if test_id not in (None, "") else None,
                    sections=sections,
                    top_level_keys=keys,
                )
    title = config.section_titles.get(PurePosixPath(file_name).name.casefold())
    if title is not None:
        return Sniffed("section_file", sections=[Section(title, section_lines(data))], top_level_keys=keys)
    if _is_data_array(data):
        return Sniffed("data_array", top_level_keys=keys, flattened=flatten(data)[:40])
    if isinstance(data, Mapping) and {k.casefold() for k in keys} & CONFIG_KEYS:
        return Sniffed("config", top_level_keys=keys, flattened=flatten(data))
    closest, missing = None, []
    if isinstance(data, Mapping) and config.schemas:
        best = max(config.schemas, key=lambda s: len({k for k, _ in s.sections} & set(keys)))
        closest = best.id
        missing = [k for k in best.required_keys if k not in data]
    return Sniffed(
        "unknown", top_level_keys=keys, flattened=flatten(data), closest_schema=closest, missing_keys=missing
    )


EMPTY_VALUES = frozenset({"", "null", "{}", "[]"})


def has_content(flattened: list[str]) -> bool:
    """True when some flattened line carries a value, not only empty containers or nulls."""
    return any(line.rpartition(": ")[2].strip() not in EMPTY_VALUES for line in flattened)


def quantities(text: str) -> list[tuple[str, int, int]]:
    return [(m.group(0), m.start(), m.end()) for m in QUANTITY.finditer(text)]
