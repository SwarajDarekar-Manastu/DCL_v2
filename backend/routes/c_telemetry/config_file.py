"""Configuration files of Route C (``.cfg``, ``.ini``; file 03 §C.0, edge cases "INI vs JSON vs key=value,
all three parsers tried"): a ``config`` document with one ``config`` node listing every setting, and the
parsed structure in ``documents.catalog``.

A LabJack ``LJStreamM.cfg`` also feeds the folder's ``UNIT_AMBIGUITY`` evidence (``ljstream_cfg.py``); as a
document it is indexed like any other configuration, so "what scan rate did TP7 log at?" finds it.
"""

import configparser
import json
import re
from pathlib import PurePosixPath
from typing import Any

from backend.dispatcher.contract import DocumentFields, ProcessedDocument, ProcessedNode
from backend.dispatcher.folder_context import FolderContext
from backend.postgres.enums import DocKind, NodeSource, NodeType, Route

PARSER_VERSION = 1
KEY_VALUE = re.compile(r"^\s*([^=:#;\s][^=:]*?)\s*[=:]\s*(.*?)\s*$")
MAX_VALUE_CHARS = 400
CONFIG_EXTENSIONS = (".cfg", ".ini", ".conf")


def parse_config(text: str) -> tuple[str, dict[str, Any]]:
    """``(format, values)``: INI sections, a JSON document, or flat key=value lines, tried in that order."""
    stripped = text.lstrip("﻿ \t\r\n")
    if _is_json(stripped):
        return "json", json.loads(stripped)
    parser = configparser.ConfigParser(interpolation=None, strict=False)
    parser.optionxform = str
    try:
        parser.read_string(stripped)
        if parser.sections():
            return "ini", {section: dict(parser[section]) for section in parser.sections()}
    except configparser.Error:
        pass
    values = {}
    for line in stripped.splitlines():
        match = KEY_VALUE.match(line)
        if match:
            values[match.group(1)] = match.group(2)
    return "key_value", values


def _is_json(text: str) -> bool:
    if not text.startswith(("{", "[")):
        return False
    try:
        json.loads(text)
    except ValueError:
        return False
    return True


def flatten(values: Any, prefix: str = "") -> list[str]:
    if isinstance(values, dict):
        return [line for k, v in values.items() for line in flatten(v, f"{prefix}{k}.")]
    if isinstance(values, list):
        return [line for i, v in enumerate(values) for line in flatten(v, f"{prefix}{i}.")]
    text = str(values)
    if len(text) > MAX_VALUE_CHARS:
        text = text[:MAX_VALUE_CHARS] + "…"
    return [f"{prefix.rstrip('.')} = {text.replace('#!#', ' | ').rstrip(' |')}"]


def can_handle(head: bytes, name: str) -> bool:
    if not name.casefold().endswith(CONFIG_EXTENSIONS):
        return False
    return b"\x00" not in head[:4096]


def process_config(
    data: bytes, blob_sha256: str, name: str, context: FolderContext, cir_put
) -> ProcessedDocument:
    text = data.decode("utf-8-sig", errors="replace")
    kind, values = parse_config(text)
    lines = flatten(values)
    prefix = f"{blob_sha256}/{Route.C}/v{PARSER_VERSION}"
    cir_put(f"{prefix}/config.json", json.dumps({"format": kind, "values": values}, indent=1).encode())
    content = f"Configuration {name} ({kind}, {len(lines)} settings)\n" + "\n".join(lines)
    return ProcessedDocument(
        blob_sha256=blob_sha256,
        route=Route.C,
        parser_version=PARSER_VERSION,
        cir_uri=f"s3://dcl-cir/{prefix}/",
        document=DocumentFields(
            title=PurePosixPath(name).name,
            doc_kind=DocKind.CONFIG,
            source_origin=context.source_origin,
            trust_tier=context.trust_tier,
            test_plan_id=context.test_plan_id,
            test_run_id=context.test_run_id,
            hardware_item=context.hardware_item,
            catalog={"config_format": kind, "values": values},
        ),
        nodes=[
            ProcessedNode(
                ref="config",
                node_type=NodeType.CONFIG,
                ordinal=0,
                breadcrumb=" › ".join(context.breadcrumb),
                content=content,
                line_start=1,
                line_end=max(1, text.count("\n") + 1),
                source=NodeSource.STRUCTURED,
                metadata={"format": kind},
            )
        ],
    )
