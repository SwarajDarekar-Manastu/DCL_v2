"""Typed access to ``pipeline_config`` (file 05 §4.6): versioned, append-only, non-secret settings.

Reads take the highest version of a key (``v_config_current``). Writes append a version.
The ``gate.*`` keys are seeded from ``config/gate.yaml``: on first start only the missing keys
are written; ``reseed`` appends a version wherever the YAML differs. The gate reads the table,
never the YAML (file 02 §4).

``sanity_ranges`` is one key holding S5's ``config/sanity_ranges.yaml`` mapping, seeded the same way.

CLI: ``python -m backend.postgres.pipeline_config seed-config [--reseed]`` (gate + sanity ranges;
``seed-gate`` seeds the gate only). Uses DCL_DATABASE_URL.
"""

import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.postgres.models import PipelineConfig
from backend.sync.gate import GateConfig

CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"
GATE_YAML = CONFIG_DIR / "gate.yaml"
SANITY_RANGES_YAML = CONFIG_DIR / "sanity_ranges.yaml"
SANITY_RANGES = "sanity_ranges"
GATE_PREFIX = "gate."
DOWNLOAD_SCOPE = "sync.download_scope"
PROCESSING_SCOPE = "processing.scope"
MISSING = object()
_ABSENT = object()


class ConfigMissing(LookupError):
    pass


def get(session: Session, key: str, default: Any = MISSING) -> Any:
    value = session.scalar(
        select(PipelineConfig.value)
        .where(PipelineConfig.key == key)
        .order_by(PipelineConfig.version.desc())
        .limit(1)
    )
    if value is None:
        if default is MISSING:
            raise ConfigMissing(f"pipeline_config has no value for {key!r}")
        return default
    return value


def get_prefix(session: Session, prefix: str) -> dict[str, Any]:
    """Current value of every key starting with ``prefix``."""
    latest = (
        select(PipelineConfig.key, func.max(PipelineConfig.version).label("version"))
        .where(PipelineConfig.key.startswith(prefix))
        .group_by(PipelineConfig.key)
        .subquery()
    )
    rows = session.execute(
        select(PipelineConfig.key, PipelineConfig.value).join(
            latest, (PipelineConfig.key == latest.c.key) & (PipelineConfig.version == latest.c.version)
        )
    )
    return dict(rows.all())


def set_value(session: Session, key: str, value: Any, updated_by: str, description: str | None = None) -> int:
    """Append a version of ``key``; returns the new version number."""
    current = session.scalar(select(func.max(PipelineConfig.version)).where(PipelineConfig.key == key)) or 0
    session.add(
        PipelineConfig(
            key=key, version=current + 1, value=value, updated_by=updated_by, description=description
        )
    )
    session.flush()
    return current + 1


def seed_gate(
    session: Session, gate: Mapping[str, Any], updated_by: str = "seed", reseed: bool = False
) -> list[str]:
    """Write ``gate.<name>`` keys from the gate YAML mapping; returns the keys written."""
    GateConfig.from_mapping(gate)  # refuse a file the gate could not use
    current = get_prefix(session, GATE_PREFIX)
    written = []
    for name, value in gate.items():
        key = GATE_PREFIX + name
        if key in current and (not reseed or current[key] == value):
            continue
        set_value(session, key, value, updated_by, description="seeded from config/gate.yaml")
        written.append(key)
    return written


def load_gate_yaml(path: Path = GATE_YAML) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def seed_key(
    session: Session, key: str, value: Any, source: str, updated_by: str = "seed", reseed: bool = False
) -> bool:
    """First start: write ``key`` if missing; re-seed: append a version if the value differs."""
    current = get(session, key, default=_ABSENT)
    if current is not _ABSENT and (not reseed or current == value):
        return False
    set_value(session, key, value, updated_by, description=f"seeded from {source}")
    return True


def seed_sanity_ranges(session: Session, reseed: bool = False, path: Path = SANITY_RANGES_YAML) -> bool:
    return seed_key(
        session,
        SANITY_RANGES,
        yaml.safe_load(path.read_text(encoding="utf-8")),
        "config/sanity_ranges.yaml",
        reseed=reseed,
    )


def sanity_ranges(session: Session) -> dict[str, Any]:
    """S5's sanity ranges mapping (``version``, ``ranges[]``) as seeded; raises if not seeded."""
    return get(session, SANITY_RANGES)


def gate_config(session: Session) -> GateConfig:
    values = get_prefix(session, GATE_PREFIX)
    if not values:
        raise ConfigMissing(
            "the gate.* keys are not seeded; run `python -m backend.postgres.pipeline_config seed-gate`"
        )
    return GateConfig.from_mapping({key.removeprefix(GATE_PREFIX): value for key, value in values.items()})


def download_scope(session: Session) -> list[str]:
    """``sync.download_scope``; empty or missing means everything."""
    return list(get(session, DOWNLOAD_SCOPE, default=[]) or [])


def processing_scope(session: Session) -> list[str]:
    """``processing.scope``; empty or missing means everything."""
    return list(get(session, PROCESSING_SCOPE, default=[]) or [])


def main(argv: list[str]) -> int:
    import os

    from sqlalchemy import create_engine

    from backend.postgres.session import normalize_url

    if not argv or argv[0] not in ("seed-gate", "seed-config"):
        print(
            "usage: python -m backend.postgres.pipeline_config seed-gate | seed-config [--reseed]",
            file=sys.stderr,
        )
        return 2
    reseed = "--reseed" in argv
    engine = create_engine(normalize_url(os.environ["DCL_DATABASE_URL"]))
    with Session(engine) as session:
        written = seed_gate(session, load_gate_yaml(), reseed=reseed)
        if argv[0] == "seed-config" and seed_sanity_ranges(session, reseed=reseed):
            written.append(SANITY_RANGES)
        session.commit()
    print(f"wrote {len(written)} keys" + (f": {', '.join(written)}" if written else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
