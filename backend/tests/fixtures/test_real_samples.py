"""Local real-corpus samples (DECISIONS.md 2026-10-22: local only, never in the public repo).

The committed real_samples.template.yaml lists each sample by entry, registry sha256, size, route
and purpose, without file names. The full manifest with paths is the git-ignored
data/samples/real_samples.yaml. Copies live in data/samples/<entry>/ (export procedure in the
fixtures README). The template is checked always; the full manifest when present; a copy when its
entry directory exists (found by sha256, so file names never enter the repository).
"""

import hashlib
import subprocess
from functools import cache
from pathlib import Path

import jsonschema
import pytest
import yaml

REPO = Path(__file__).resolve().parents[3]
TEMPLATE = Path(__file__).resolve().parent / "real_samples.template.yaml"
SAMPLES = REPO / "data" / "samples"
FULL = SAMPLES / "real_samples.yaml"
ROUTES = ["A1", "A2", "B", "C", "D", "E", "F", "G"]
ITEM = {
    "entry": {"type": "string", "pattern": "^(E([1-9]|1[0-9])|X[1-9])$"},
    "sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
    "size_bytes": {"type": "integer", "minimum": 1},
    "route": {"enum": ROUTES},
    "purpose": {"type": "string", "minLength": 5},
}


def schema(with_path: bool) -> dict:
    props = dict(ITEM, **({"path": {"type": "string", "minLength": 3}} if with_path else {}))
    return {
        "type": "object",
        "required": ["version", "samples"],
        "additionalProperties": False,
        "properties": {
            "version": {"const": 1},
            "samples": {
                "type": "array",
                "minItems": 1,
                "items": {
                    "type": "object",
                    "required": list(props),
                    "additionalProperties": False,
                    "properties": props,
                },
            },
        },
    }


def load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def template() -> list[dict]:
    return load(TEMPLATE)["samples"]


@cache
def digests(entry: str) -> dict[str, int]:
    """sha256 -> size of every file under data/samples/<entry>/."""
    out = {}
    for path in (SAMPLES / entry).rglob("*"):
        if path.is_file() and path.name != "real_samples.yaml":
            digest = hashlib.sha256()
            with path.open("rb") as fh:
                for chunk in iter(lambda: fh.read(1 << 20), b""):
                    digest.update(chunk)
            out[digest.hexdigest()] = path.stat().st_size
    return out


def test_template_has_no_file_names_and_is_valid():
    data = load(TEMPLATE)
    jsonschema.validate(data, schema(with_path=False))
    keys = [(s["entry"], s["sha256"]) for s in data["samples"]]
    assert len(keys) == len(set(keys))
    assert {s["route"] for s in data["samples"]} >= {"A1", "A2", "B", "C", "D", "E", "F", "G"}


def test_no_real_sample_or_manifest_is_tracked_by_git():
    tracked = subprocess.run(
        ["git", "ls-files", "data"], cwd=REPO, capture_output=True, text=True, check=True
    )
    assert tracked.stdout == ""
    for probe in ("data/samples/E1/x.dat", "data/samples/real_samples.yaml"):
        ignored = subprocess.run(["git", "check-ignore", "-q", probe], cwd=REPO, check=False)
        assert ignored.returncode == 0, f"{probe} must be git-ignored"


@pytest.mark.skipif(not FULL.is_file(), reason="full manifest data/samples/real_samples.yaml not present")
def test_full_manifest_matches_the_template():
    full = load(FULL)
    jsonschema.validate(full, schema(with_path=True))
    # Several paths may share one blob (identical files); the template has one row per blob.
    assert {(s["entry"], s["sha256"], s["size_bytes"]) for s in full["samples"]} == {
        (s["entry"], s["sha256"], s["size_bytes"]) for s in template()
    }


@pytest.mark.parametrize("sample", template(), ids=lambda s: f"{s['entry']}:{s['sha256'][:12]}")
def test_local_copy_matches_the_registry(sample):
    if not (SAMPLES / sample["entry"]).is_dir():
        pytest.skip(f"data/samples/{sample['entry']} not exported locally")
    found = digests(sample["entry"])
    assert sample["sha256"] in found, f"no file with this sha256 under data/samples/{sample['entry']}"
    assert found[sample["sha256"]] == sample["size_bytes"]
