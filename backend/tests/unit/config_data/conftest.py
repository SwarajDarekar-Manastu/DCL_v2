"""Fixtures for the configuration-data load tests (feature quality/config-data).

The suite runs with --import-mode=importlib, so helpers are exposed as fixtures instead of
being imported from this file.
"""

import re
import unicodedata
from pathlib import Path

import pint
import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[4]
CONFIG_DIR = REPO_ROOT / "config"
UNITS_FILE = CONFIG_DIR / "units.txt"
ALIAS_LINE = re.compile(r"^#= (?P<surface>.+?) => (?P<expr>.+?) \| (?P<dim>.+)$")


def _load_yaml(name: str):
    with open(CONFIG_DIR / name, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _unit_aliases() -> list[tuple[str, str, str]]:
    out = []
    for line in UNITS_FILE.read_text(encoding="utf-8").splitlines():
        if line.startswith("#= "):
            m = ALIAS_LINE.match(line)
            assert m, f"malformed alias line: {line!r}"
            out.append((m["surface"], m["expr"], m["dim"]))
    return out


def _apply_unit_aliases(unit_string: str) -> str:
    """Reference implementation of the rule documented in config/units.txt:
    longest surface first, exact case-sensitive substring replacement."""
    for surface, expr, _ in sorted(_unit_aliases(), key=lambda a: len(a[0]), reverse=True):
        unit_string = unit_string.replace(surface, expr)
    return unit_string


def _canonical_key(surface: str) -> str:
    """Generic part of the alias canonicalization of 04 §3.3 step 1 (identifier rules are S2's)."""
    s = unicodedata.normalize("NFKC", surface).lower()
    s = re.sub(r"[‐‑‒–—―−]", "-", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s.rstrip(".,;:")


@pytest.fixture(scope="session")
def load_config():
    return _load_yaml


@pytest.fixture(scope="session")
def ureg() -> pint.UnitRegistry:
    registry = pint.UnitRegistry()
    registry.load_definitions(str(UNITS_FILE))
    return registry


@pytest.fixture(scope="session")
def unit_aliases():
    return _unit_aliases()


@pytest.fixture(scope="session")
def apply_unit_aliases():
    return _apply_unit_aliases


@pytest.fixture(scope="session")
def canonical_key():
    return _canonical_key


@pytest.fixture(params=_unit_aliases(), ids=lambda a: a[0])
def unit_alias(request):
    return request.param


@pytest.fixture(params=_load_yaml("propellants.yaml")["propellants"], ids=lambda p: p["id"])
def propellant(request):
    return request.param
