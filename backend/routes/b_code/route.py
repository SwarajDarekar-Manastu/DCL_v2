"""Route B (file 03 §6): team scripts and tooling documents → ``ProcessedDocument`` + CIR.

Source code (Python, C, MATLAB; ``symbols.py``):
- a ``module_header`` node: module docstring or leading comment, imports, module-level constants (with units
  from their names), dataclasses;
- one ``code_symbol`` node per function, class, method, C type, and per group of script statements. Each
  node's content starts with the context header ``# File: … | Module: … | Class: … | Imports: …``; a
  method also carries its class preamble (signature, docstring, class attributes, ``__init__``
  assignments). Symbols longer than ~1,500 tokens are split at statement boundaries with the signature
  repeated. ``metadata`` holds qualname, signature, docstring, parameters (with units) and ``calls``.
- ``TODO``/``FIXME`` comments become ``annotation`` mentions; constants with units ``quantity`` mentions.
- A file Tree-sitter cannot parse cleanly (syntax error, Python 2 leftovers it rejects) is indexed as text
  windows with ``PARSE_FAILURE`` SOFT naming the lines.
- Generated files (``ui_*.py`` from Qt Designer, "generated" banners) are tagged ``catalog.generated``.

Documents (``text_docs.py``): Markdown by headings, ``.txt``/``.bat`` by line windows, ``requirements.txt``
as ``dependency`` mentions, notebooks one node per cell (outputs ignored).

Every node has ``line_start``/``line_end`` in the file itself. A hard-coded credential is
``SENSITIVE_CONTENT`` HARD (second pass after the gate). CIR ``dcl-cir/{sha256}/B/v1/``: ``ast.json``,
``module_header.md``. Unit hashes: one per symbol.
"""

import hashlib
import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import PurePosixPath

from backend.dispatcher.contract import (
    DocumentFields,
    Flag,
    FlagAnchor,
    Mention,
    ParseFailureEvidence,
    ProcessedDocument,
    ProcessedNode,
    SensitiveEvidence,
    UnitHash,
)
from backend.dispatcher.folder_context import FolderContext
from backend.postgres.enums import DocKind, FlagSeverity, FlagType, NodeSource, NodeType, Route
from backend.routes.b_code import text_docs
from backend.routes.b_code.symbols import MAX_SYMBOL_CHARS, Module, Symbol
from backend.sync.gate import scan_secrets

PARSER_VERSION = 1
SOURCE_LANGUAGES = {".py": "python", ".pyw": "python", ".c": "c", ".h": "c", ".m": "matlab"}
MARKDOWN = (".md", ".markdown")
TEXT = (".txt", ".bat", ".cmd")
NOTEBOOK = ".ipynb"
HANDLED = (*SOURCE_LANGUAGES, *MARKDOWN, *TEXT, NOTEBOOK)
GENERATED = re.compile(
    r"Created by: PyQt\d? UI code generator|WARNING! All changes made in this file will be lost|"
    r"@generated|DO NOT EDIT|auto-?generated",
    re.IGNORECASE,
)
SEPARATOR = " › "


@dataclass(frozen=True)
class Stores:
    """``put_cir(relative_key, bytes) -> uri`` under ``dcl-cir/{sha256}/B/v1/`` (Route B writes no assets)."""

    put_cir: Callable[[str, bytes], str]


def decode(data: bytes) -> str:
    """UTF-16 with a BOM (PowerShell ``pip freeze >``), UTF-8, else the detected encoding; LF newlines."""
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        text = data.decode("utf-16")
    else:
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            from charset_normalizer import from_bytes

            best = from_bytes(data).best()
            text = str(best) if best is not None else data.decode("latin-1")
    return text.replace("\x00", "").replace("\r\n", "\n").replace("\r", "\n")


def can_handle(head: bytes, name: str) -> bool:
    if not name.casefold().endswith(HANDLED):
        return False
    return head.startswith((b"\xff\xfe", b"\xfe\xff")) or b"\x00" not in head[:4096]


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _secret_flags(text: str, blob_sha256: str) -> list[Flag]:
    return [
        Flag(
            flag_type=FlagType.SENSITIVE_CONTENT,
            severity=FlagSeverity.HARD,
            anchor=FlagAnchor(line=hit.line, content_sha256=blob_sha256),
            evidence=SensitiveEvidence(
                pattern=hit.pattern, redacted_preview=hit.redacted_preview, line=hit.line
            ),
        )
        for hit in scan_secrets(text)
    ]


def _context_header(file_name: str, module: str, imports: list[str], parent: str | None) -> str:
    parts = [f"File: {file_name}", f"Module: {module}"]
    if parent:
        parts.append(f"Class: {parent}")
    if imports:
        parts.append("Imports: " + ", ".join(imports[:12]))
    return "# " + " | ".join(parts)


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip())


def split_symbol(symbol: Symbol) -> list[tuple[int, int, str]]:
    """(first line, last line, text) parts of at most ~``MAX_SYMBOL_CHARS``, cut at statement starts (the
    body's statements, else lines at the body's indentation), each later part led by the signature."""
    if len(symbol.text) <= MAX_SYMBOL_CHARS:
        return [(symbol.start_line, symbol.end_line, symbol.text)]
    lines = symbol.text.split("\n")
    base = symbol.start_line
    boundaries = {line - base for line in symbol.statement_lines if base < line <= symbol.end_line}
    body = [line for line in lines[1:] if line.strip()]
    inner = min((_indent(line) for line in body), default=0)
    boundaries |= {i for i, line in enumerate(lines) if i and line.strip() and _indent(line) <= inner}
    parts: list[tuple[int, int]] = []
    start, size = 0, 0
    for i, line in enumerate(lines):
        if i > start and (
            (size + len(line) > MAX_SYMBOL_CHARS and i in boundaries) or size > 1.5 * MAX_SYMBOL_CHARS
        ):
            parts.append((start, i - 1))
            start, size = i, 0
        size += len(line) + 1
    parts.append((start, len(lines) - 1))
    out = []
    for k, (a, b) in enumerate(parts):
        text = "\n".join(lines[a : b + 1])
        if k and symbol.signature:
            text = f"{symbol.signature}  # … part {k + 1}/{len(parts)}\n{text}"
        out.append((base + a, base + b, text))
    return out


@dataclass
class _Out:
    nodes: list[ProcessedNode]
    mentions: list[Mention]
    flags: list[Flag]
    hashes: list[UnitHash]
    catalog: dict
    cir: dict[str, bytes]
    doc_kind: DocKind


def _node(
    ref,
    node_type,
    content,
    start,
    end,
    crumb,
    ordinal,
    metadata,
    parent_ref=None,
    source=NodeSource.SOURCE_CODE,
):
    return ProcessedNode(
        ref=ref,
        parent_ref=parent_ref,
        node_type=node_type,
        level=crumb.count(SEPARATOR) + 1,
        ordinal=ordinal,
        breadcrumb=crumb,
        language="en",
        content=content,
        line_start=start,
        line_end=max(end, start),
        source=source,
        metadata=metadata,
    )


def _source_code(text: str, file_name: str, language: str) -> _Out:
    from backend.routes.b_code.symbols import PARSERS

    module: Module = PARSERS[language](text.encode("utf-8"))
    stem = PurePosixPath(file_name).stem
    generated = bool(re.fullmatch(r"ui_\w+\.py", file_name.casefold())) or bool(GENERATED.search(text[:2000]))
    catalog = {"language": language, "generated": generated}
    if module.error_lines:
        out = _plain_text(text, file_name, DocKind.CODE)
        out.flags.append(
            Flag(
                flag_type=FlagType.PARSE_FAILURE,
                severity=FlagSeverity.SOFT,
                anchor=FlagAnchor(line=module.error_lines[0]),
                evidence=ParseFailureEvidence(
                    error=f"{language} syntax errors at lines "
                    f"{', '.join(map(str, module.error_lines[:20]))}; indexed as text",
                    extension=PurePosixPath(file_name).suffix.lstrip("."),
                    size_bytes=len(text.encode("utf-8")),
                ),
            )
        )
        out.catalog.update(catalog, syntax_error_lines=module.error_lines[:50])
        return out

    lines = text.split("\n")
    nodes: list[ProcessedNode] = []
    mentions: list[Mention] = []
    hashes: list[UnitHash] = []
    first_symbol = min((sym.start_line for sym in module.symbols), default=len(lines) + 1)
    header_lines = [*(module.doc_lines or ()), *module.import_lines]
    header_lines += [c.line for c in module.constants if c.line < first_symbol]
    header_end = max(header_lines, default=1)
    first_line = next((i + 1 for i, line in enumerate(lines) if line.strip()), 1)
    head_comments = [line for line in lines[: first_line + 2] if line.startswith(("#!", "# -*-", "# coding"))]
    header_parts = [_context_header(file_name, stem, module.import_names, None)]
    header_parts += head_comments
    if module.docstring:
        header_parts.append(module.docstring)
    if module.imports:
        header_parts.append("Imports:\n" + "\n".join(module.imports))
    if module.constants:
        header_parts.append(
            "Constants:\n"
            + "\n".join(
                f"{c.name} = {c.value.splitlines()[0][:120]}" + (f"  [{c.unit}]" if c.unit else "")
                for c in module.constants
            )
        )
    if module.dataclasses:
        header_parts.append("Dataclasses: " + "; ".join(module.dataclasses))
    symbol_names = [s.qualname for s in module.symbols if s.kind != "body"]
    if symbol_names:
        header_parts.append("Defines: " + ", ".join(symbol_names[:80]))
    header_text = "\n".join(header_parts)
    nodes.append(
        _node(
            "module",
            NodeType.MODULE_HEADER,
            header_text,
            1,
            header_end,
            file_name,
            0,
            {
                "language": language,
                "imports": module.import_names,
                "constants": [c.__dict__ for c in module.constants],
                "generated": generated,
            },
        )
    )
    for constant in module.constants:
        if constant.unit:
            mentions.append(
                Mention(node_ref="module", kind="quantity", surface=f"{constant.value} {constant.unit}")
            )

    refs: dict[str, str] = {}
    for symbol in module.symbols:
        parent_ref = refs.get(symbol.parent) if symbol.parent else None
        header = _context_header(file_name, stem, module.import_names, symbol.parent)
        crumb = SEPARATOR.join(
            [
                file_name,
                *([symbol.parent] if symbol.parent else []),
                symbol.name if symbol.kind != "body" else "script",
            ]
        )
        metadata = {
            "qualname": symbol.qualname,
            "symbol_kind": symbol.kind,
            "language": language,
            "signature": symbol.signature,
            "docstring": symbol.docstring,
            "params": [p.as_dict() for p in symbol.params],
            "calls": symbol.calls,
            "generated": generated,
        }
        if symbol.members:
            metadata["members"] = symbol.members
        parts = split_symbol(symbol)
        for k, (start, end, body) in enumerate(parts):
            ref = f"sym:{symbol.qualname}" + (f"#{k + 1}" if k else "")
            pieces = [header]
            if symbol.preamble:
                pieces.append(symbol.preamble if language != "python" else f"{symbol.preamble}\n    ...")
            if symbol.kind == "class" and symbol.members:
                body = body + "\n# Methods: " + ", ".join(f"{m}()" for m in symbol.members)
            pieces.append(body)
            meta = dict(metadata, part=f"{k + 1}/{len(parts)}") if len(parts) > 1 else metadata
            nodes.append(
                _node(
                    ref,
                    NodeType.CODE_SYMBOL,
                    "\n".join(pieces),
                    start,
                    end,
                    crumb,
                    len(nodes),
                    meta,
                    parent_ref,
                )
            )
            if k == 0:
                refs[symbol.qualname] = ref
        hashes.append(UnitHash(unit="symbol", key=symbol.qualname, sha256=_sha(symbol.text)))

    for line, note in module.annotations:
        owner = next(
            (
                n
                for n in reversed(nodes)
                if n.ref != "module" and n.line_start <= line <= (n.line_end or n.line_start)
            ),
            nodes[0],
        )
        mentions.append(Mention(node_ref=owner.ref, kind="annotation", surface=note[:300]))
    ast = {
        "language": language,
        "docstring": module.docstring,
        "imports": module.imports,
        "constants": [c.__dict__ for c in module.constants],
        "dataclasses": module.dataclasses,
        "symbols": [
            {
                "qualname": s.qualname,
                "kind": s.kind,
                "lines": [s.start_line, s.end_line],
                "parent": s.parent,
                "signature": s.signature,
                "docstring": s.docstring,
                "params": [p.as_dict() for p in s.params],
                "calls": s.calls,
            }
            for s in module.symbols
        ],
        "annotations": module.annotations,
    }
    catalog.update(symbols=len(symbol_names))
    cir = {
        "ast.json": json.dumps(ast, ensure_ascii=False, indent=1).encode("utf-8"),
        "module_header.md": header_text.encode("utf-8"),
    }
    return _Out(nodes, mentions, [], hashes, catalog, cir, DocKind.CODE)


def _plain_text(text: str, file_name: str, kind: DocKind) -> _Out:
    nodes = [
        _node(
            f"l{p.start}", NodeType.CHILD, p.text, p.start, p.end, file_name, i, {}, source=NodeSource.PRINTED
        )
        for i, p in enumerate(text_docs.text_windows(text))
    ]
    mentions = []
    catalog: dict = {}
    if text_docs.is_requirements(file_name) and nodes:
        dependencies = text_docs.requirements(text)
        mentions = [Mention(node_ref=nodes[0].ref, kind="dependency", surface=d) for d in dependencies]
        catalog["dependencies"] = dependencies
    return _Out(nodes, mentions, [], [], catalog, {}, kind)


def _markdown(text: str, file_name: str) -> _Out:
    passages, _ = text_docs.markdown_passages(text)
    nodes = [
        _node(
            f"l{p.start}",
            NodeType.CHILD,
            p.text,
            p.start,
            p.end,
            SEPARATOR.join([file_name, *p.crumbs]),
            i,
            {"code": True} if p.kind == "code" else {},
            source=NodeSource.PRINTED,
        )
        for i, p in enumerate(passages)
    ]
    return _Out(nodes, [], [], [], {}, {}, DocKind.TOOLING_DOC)


def _notebook(text: str, file_name: str) -> _Out:
    passages, kernel = text_docs.notebook_passages(text)
    nodes = []
    for i, p in enumerate(passages):
        crumb = SEPARATOR.join([file_name, *p.crumbs])
        if p.kind == "cell_code":
            content = (
                f"# Notebook: {file_name} | Cell {p.meta['cell']} | Kernel: {kernel or 'unknown'}\n{p.text}"
            )
            nodes.append(
                _node(
                    f"cell{p.meta['cell']}", NodeType.CODE_SYMBOL, content, p.start, p.end, crumb, i, p.meta
                )
            )
        else:
            ref = f"cell{p.meta['cell']}.{i}"
            nodes.append(
                _node(
                    ref, NodeType.CHILD, p.text, p.start, p.end, crumb, i, p.meta, source=NodeSource.PRINTED
                )
            )
    return _Out(
        nodes,
        [],
        [],
        [],
        {"language": kernel, "cells": len({p.meta["cell"] for p in passages})},
        {},
        DocKind.CODE,
    )


def process_code(
    data: bytes, *, blob_sha256: str, file_name: str, folder: FolderContext, stores: Stores
) -> ProcessedDocument:
    suffix = PurePosixPath(file_name).suffix.casefold()
    text = decode(data)
    cir_uri = f"s3://dcl-cir/{blob_sha256}/{Route.B}/v{PARSER_VERSION}/"
    flags = _secret_flags(text, blob_sha256)
    try:
        if suffix in SOURCE_LANGUAGES:
            out = _source_code(text, file_name, SOURCE_LANGUAGES[suffix])
        elif suffix == NOTEBOOK:
            out = _notebook(text, file_name)
        elif suffix in MARKDOWN:
            out = _markdown(text, file_name)
        else:
            out = _plain_text(text, file_name, DocKind.TOOLING_DOC)
    except (json.JSONDecodeError, ValueError) as exc:
        out = _plain_text(text, file_name, DocKind.CODE if suffix == NOTEBOOK else DocKind.TOOLING_DOC)
        out.flags.append(
            Flag(
                flag_type=FlagType.PARSE_FAILURE,
                severity=FlagSeverity.SOFT,
                evidence=ParseFailureEvidence(
                    error=f"{exc}; indexed as text", extension=suffix.lstrip("."), size_bytes=len(data)
                ),
            )
        )
    for key, payload in out.cir.items():
        stores.put_cir(key, payload)
    document = DocumentFields(
        title=file_name,
        doc_kind=out.doc_kind,
        source_origin=folder.source_origin,
        trust_tier=folder.trust_tier,
        test_plan_id=folder.test_plan_id,
        test_run_id=folder.test_run_id,
        hardware_item=folder.hardware_item,
        language="en",
        unit_count=len(out.hashes) or None,
        catalog=out.catalog or None,
    )
    return ProcessedDocument(
        blob_sha256=blob_sha256,
        route=Route.B,
        parser_version=PARSER_VERSION,
        cir_uri=cir_uri,
        document=document,
        nodes=out.nodes,
        mentions=out.mentions,
        flags=flags + out.flags,
        unit_hashes=out.hashes,
    )
