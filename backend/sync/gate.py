"""The metadata-only junk gate, tiers 1–3 (file 02 §4). Rejected items are never downloaded.

Matching is case-insensitive (OneDrive names are). Path patterns are shell globs matched
against one folder name at a time; extensions and junk names are matched against the end
of the file name, so ``.synctex.gz`` is junk while a plain ``.gz`` is not. Tier 4 runs
after the download (``backend/sync/downloader.py``).

Config keys (one mapping; the source file is ``config/gate.yaml``):
    junk_path_segments       globs; a match anywhere in the path → SKIPPED_JUNK  (T1:<segment>)
    quarantine_path_patterns globs; a match anywhere in the path → QUARANTINED   (T1:quarantine:<segment>)
    junk_extensions          name endings → SKIPPED_JUNK                          (T2:<ending>)
    junk_names               exact names → SKIPPED_JUNK                           (T2:<name>)
    junk_name_prefixes       name starts → SKIPPED_JUNK                           (T2:<prefix>)
    junk_extensions_under    {ending: [segment globs]}: junk only below such a folder (T2:<ending>)
    kept_endings_by_parent_kind {kind: [endings]}: for archive members gated with that
                             parent_kind (e.g. ``wbpz``), these endings skip the Tier-2 ending checks
    shortcut_extensions      name endings → SKIPPED_SHORTCUT                      (T3:shortcut)
    max_download_bytes       larger files → HELD_LARGE_FILE                        (T3:size)
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Any

import yaml

from backend.postgres.enums import DriveItemStatus


@dataclass(frozen=True)
class GateConfig:
    junk_path_segments: tuple[str, ...]
    quarantine_path_patterns: tuple[str, ...]
    junk_extensions: tuple[str, ...]
    junk_names: frozenset[str]
    junk_name_prefixes: tuple[str, ...]
    junk_extensions_under: Mapping[str, tuple[str, ...]]
    kept_endings_by_parent_kind: Mapping[str, frozenset[str]]
    shortcut_extensions: tuple[str, ...]
    max_download_bytes: int

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "GateConfig":
        def lower(key: str) -> tuple[str, ...]:
            return tuple(_text(value, key) for value in data.get(key, ()))

        return cls(
            junk_path_segments=lower("junk_path_segments"),
            quarantine_path_patterns=lower("quarantine_path_patterns"),
            junk_extensions=lower("junk_extensions"),
            junk_names=frozenset(lower("junk_names")),
            junk_name_prefixes=lower("junk_name_prefixes"),
            junk_extensions_under={
                _text(ending, "junk_extensions_under"): tuple(
                    _text(g, "junk_extensions_under") for g in globs
                )
                for ending, globs in (data.get("junk_extensions_under") or {}).items()
            },
            kept_endings_by_parent_kind={
                _text(kind, "kept_endings_by_parent_kind"): frozenset(
                    _text(ending, "kept_endings_by_parent_kind") for ending in endings
                )
                for kind, endings in (data.get("kept_endings_by_parent_kind") or {}).items()
            },
            shortcut_extensions=lower("shortcut_extensions"),
            max_download_bytes=int(data["max_download_bytes"]),
        )

    @classmethod
    def load(cls, path: Path) -> "GateConfig":
        return cls.from_mapping(yaml.safe_load(path.read_text(encoding="utf-8")))


def _text(value: object, key: str) -> str:
    """Gate patterns must be strings: YAML reads a bare ``.1`` as the float 0.1, a silent wrong ending."""
    if not isinstance(value, str):
        raise ValueError(f"gate config {key}: {value!r} is not a string; quote it in the YAML")
    return value.casefold()


@dataclass(frozen=True)
class Verdict:
    status: DriveItemStatus
    gate_reason: str


@dataclass(frozen=True)
class GateInput:
    """What the gate sees of one file item: Graph metadata plus the folder names from the root down.

    ``parent_kind`` is set for archive members (Route G): the kind of the containing archive.
    """

    name: str
    size_bytes: int | None
    folder_names: Sequence[str]
    parent_kind: str | None = None
    is_package: bool = False
    is_shortcut: bool = False


def _first_match(names: Sequence[str], globs: Sequence[str]) -> str | None:
    for name in names:
        folded = name.casefold()
        if any(fnmatchcase(folded, glob) for glob in globs):
            return name
    return None


def folder_flags(folder_names: Sequence[str], config: GateConfig) -> tuple[bool, bool]:
    """``(is_junk, is_quarantine)`` for a folder whose path from the root is ``folder_names``."""
    return (
        _first_match(folder_names, config.junk_path_segments) is not None,
        _first_match(folder_names, config.quarantine_path_patterns) is not None,
    )


def gate_item(item: GateInput, config: GateConfig) -> Verdict | None:
    """Tiers 1–3 in order. ``None`` means accepted (the download scope is decided separately)."""
    segment = _first_match(item.folder_names, config.junk_path_segments)
    if segment is not None:
        return Verdict(DriveItemStatus.SKIPPED_JUNK, f"T1:{segment}")
    segment = _first_match(item.folder_names, config.quarantine_path_patterns)
    if segment is not None:
        return Verdict(DriveItemStatus.QUARANTINED, f"T1:quarantine:{segment}")

    name = item.name.casefold()
    if name in config.junk_names:
        return Verdict(DriveItemStatus.SKIPPED_JUNK, f"T2:{item.name}")
    for prefix in config.junk_name_prefixes:
        if name.startswith(prefix):
            return Verdict(DriveItemStatus.SKIPPED_JUNK, f"T2:{prefix}")
    kept = config.kept_endings_by_parent_kind.get((item.parent_kind or "").casefold(), frozenset())
    for ending in config.junk_extensions:
        if name.endswith(ending) and ending not in kept:
            return Verdict(DriveItemStatus.SKIPPED_JUNK, f"T2:{ending}")
    for ending, globs in config.junk_extensions_under.items():
        if (
            name.endswith(ending)
            and ending not in kept
            and _first_match(item.folder_names, globs) is not None
        ):
            return Verdict(DriveItemStatus.SKIPPED_JUNK, f"T2:{ending}")

    if item.is_package:
        return Verdict(DriveItemStatus.SKIPPED_UNSUPPORTED_PACKAGE, "T3:package")
    if item.is_shortcut or any(name.endswith(ending) for ending in config.shortcut_extensions):
        return Verdict(DriveItemStatus.SKIPPED_SHORTCUT, "T3:shortcut")
    if not item.size_bytes:
        return Verdict(DriveItemStatus.SKIPPED_EMPTY, "T3:empty")
    if item.size_bytes > config.max_download_bytes:
        return Verdict(DriveItemStatus.HELD_LARGE_FILE, "T3:size")
    return None
