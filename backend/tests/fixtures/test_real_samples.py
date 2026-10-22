"""Local real-corpus samples (DECISIONS.md 2026-10-22: local only, never in the public repo).

backend/tests/fixtures/real_samples.yaml lists the sample files with the registry's sha256 and
size. A developer copies them from MinIO into the git-ignored data/samples/ (see the fixtures
README). These tests check the manifest always, and check a local copy only when data/samples/
exists; they are skipped otherwise.
"""

import hashlib
import subprocess
from pathlib import Path

import jsonschema
import pytest
import yaml

REPO = Path(__file__).resolve().parents[3]
MANIFEST = Path(__file__).resolve().parent / "real_samples.yaml"
SAMPLES = REPO / "data" / "samples"
ROUTES = ["A1", "A2", "B", "C", "D", "E", "F", "G"]
SCHEMA = {
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
                "required": ["entry", "path", "size_bytes", "sha256", "route", "purpose"],
                "additionalProperties": False,
                "properties": {
                    "entry": {"type": "string", "pattern": "^E([1-9]|1[0-9])$"},
                    "path": {"type": "string", "minLength": 3},
                    "size_bytes": {"type": "integer", "minimum": 1},
                    "sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
                    "route": {"enum": ROUTES},
                    "purpose": {"type": "string", "minLength": 5},
                },
            },
        },
    },
}


def manifest() -> list[dict]:
    return yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))["samples"]


def test_manifest_schema_and_uniqueness():
    data = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    jsonschema.validate(data, SCHEMA)
    keys = [(s["entry"], s["path"]) for s in data["samples"]]
    assert len(keys) == len(set(keys))


def test_samples_cover_every_route_with_a_real_file():
    assert {s["route"] for s in manifest()} >= {"A1", "A2", "B", "C", "D", "E", "F"}


def test_no_real_sample_is_tracked_by_git():
    tracked = subprocess.run(
        ["git", "ls-files", "data"], cwd=REPO, capture_output=True, text=True, check=True
    )
    assert tracked.stdout == ""
    ignored = subprocess.run(["git", "check-ignore", "-q", "data/samples/E1/x.dat"], cwd=REPO, check=False)
    assert ignored.returncode == 0, "data/samples/ must be git-ignored"


@pytest.mark.skipif(not SAMPLES.is_dir(), reason="data/samples/ not exported locally")
@pytest.mark.parametrize("sample", manifest(), ids=lambda s: f"{s['entry']}:{s['path']}")
def test_local_copy_matches_the_registry(sample):
    path = SAMPLES / sample["entry"] / sample["path"]
    assert path.is_file(), f"missing; re-run the export for {sample['entry']}"
    assert path.stat().st_size == sample["size_bytes"]
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    assert digest.hexdigest() == sample["sha256"]
