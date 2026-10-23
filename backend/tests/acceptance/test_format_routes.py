"""Route-level acceptance over the public format samples (Lead ruling 2026-10-23: they never become stack
documents). Each check calls the route's entry point on the local sample in data/samples/web, the way S6's
smoke test does (vision off), and asserts the extraction recorded in data/benchmark/formats.local.yaml.
Skipped when the samples, the values file or a route library are absent. See FORMATS.md."""

import hashlib
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[3]
WEB = REPO / "data" / "samples" / "web"
VALUES = REPO / "data" / "benchmark" / "formats.local.yaml"

pytestmark = pytest.mark.skipif(
    not (WEB.is_dir() and VALUES.is_file()), reason="data/samples/web or formats.local.yaml not local"
)


def _values() -> dict:
    return yaml.safe_load(VALUES.read_text(encoding="utf-8")) if VALUES.is_file() else {}


def _sample(case: dict) -> Path:
    [citation] = case["expected_citations"]
    [path] = [p for p in WEB.rglob(citation["file_name"]) if p.is_file()]
    return path


def _folder(path: Path):
    from backend.dispatcher.folder_context import FolderContext

    parts = list(path.relative_to(WEB.parent).parent.parts)
    return FolderContext(root_name="samples", breadcrumb=parts, path_cached="/".join(parts))


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _soffice(data: bytes, source: str, target: str) -> bytes:
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / f"in.{source}"
        src.write_bytes(data)
        subprocess.run(
            ["soffice", "--headless", f"-env:UserInstallation=file://{tmp}/profile", "--convert-to", target,
             "--outdir", tmp, str(src)],
            check=True, capture_output=True, timeout=300,
        )  # fmt: skip
        return (Path(tmp) / f"in.{target}").read_bytes()


# ---------------------------------------------------------------- route runners


def run_a1(path: Path):
    if shutil.which("soffice") is None:
        pytest.skip("LibreOffice (soffice) not installed")
    if path.suffix.lower() == ".docx" and shutil.which("tesseract") is None:
        pytest.skip("Docling's PDF pipeline needs tesseract (present in the parse image)")
    pytest.importorskip("docling")
    from backend.routes.a1_office.office import process_office
    from backend.routes.a1_office.route import Stores

    data = path.read_bytes()
    return process_office(
        data,
        blob_sha256=_sha(data),
        file_name=path.name,
        stores=Stores(lambda k, v: k, lambda k, v: f"s3://dcl-assets/{k}"),
        vision=None,
        convert_office=_soffice,
        folder=_folder(path),
        cloud_allowed=False,
    )


def run_b(path: Path):
    pytest.importorskip("tree_sitter")
    from backend.routes.b_code.route import Stores, process_code

    data = path.read_bytes()
    return process_code(
        data, blob_sha256=_sha(data), file_name=path.name, folder=_folder(path), stores=Stores(lambda k, v: k)
    )


def run_e(path: Path):
    pytest.importorskip("ezdxf")
    from backend.routes.e_diagrams.route import Stores, process_diagram

    data = path.read_bytes()
    return process_diagram(
        data,
        blob_sha256=_sha(data),
        file_name=path.name,
        folder=_folder(path),
        stores=Stores(lambda k, v: k, lambda k, v: f"s3://dcl-assets/{k}"),
    )


def run_g(path: Path):
    pytest.importorskip("trimesh")
    from backend.routes.g_archives.route import Stores, process_full

    data = path.read_bytes()
    return process_full(
        data,
        blob_sha256=_sha(data),
        file_name=path.name,
        folder=_folder(path),
        stores=Stores(lambda k, v: k),
        path=str(path.relative_to(WEB.parent)),
        folder_files=[str(p.relative_to(WEB.parent)) for p in path.parent.iterdir() if p.is_file()],
    )


ROUTES = {
    ".docx": run_a1,
    ".pptx": run_a1,
    ".c": run_b,
    ".m": run_b,
    ".ipynb": run_b,
    ".drawio": run_e,
    ".svg": run_e,
    ".vsdx": run_e,
    ".dxf": run_e,
    ".zip": run_g,
    ".stl": run_g,
    ".step": run_g,
}


def _text(processed) -> str:
    """Everything a retrieval or a reviewer would see: node text and metadata, document fields, mentions,
    archive member paths."""
    parts = [n.content for n in processed.nodes]
    parts += [json.dumps(n.metadata, default=str) for n in processed.nodes]
    parts.append(processed.document.model_dump_json() if processed.document else "")
    parts += [m.model_dump_json() for m in getattr(processed, "mentions", []) or []]
    parts += [d.member_path for d in getattr(processed, "derived_blobs", []) or []]
    return "\n".join(parts).casefold()


def _measured(processed) -> dict:
    measurement = ((processed.document.catalog or {}) if processed.document else {}).get("measurement", {})
    extents = measurement.get("extents") or [None, None, None]
    return {
        "extent_x": extents[0],
        "extent_y": extents[1],
        "extent_z": extents[2],
        "solid_count": measurement.get("solids"),
    }


def _close(found, expected: dict) -> bool:
    if found is None:
        return False
    tolerance = abs(expected["value"]) * expected["tolerance_pct"] / 100
    return abs(float(found) - expected["value"]) <= tolerance


ROUTE_CASES = sorted(k for k in _values() if k != "fmt-c-tdms-chamber-peak")


@pytest.mark.parametrize("case_id", ROUTE_CASES)
def test_route_extracts_the_expected_values(case_id):
    case = _values()[case_id]
    path = _sample(case)
    processed = ROUTES[path.suffix.lower()](path)
    assert processed.nodes, f"{case_id}: no nodes"
    text = _text(processed)
    missing = [e for e in case.get("expected_entities", []) if e.casefold() not in text]
    assert not missing, f"{case_id}: not extracted {missing}"
    measured = _measured(processed)
    for expected in case.get("expected_numeric", []):
        found = measured.get(expected["metric"])
        assert _close(found, expected), (
            f"{case_id}: {expected['metric']} = {found}, expected {expected['value']}"
        )


def test_archive_members_are_kept_and_junk_is_skipped():
    case = _values()["fmt-g-zip-members"]
    processed = run_g(_sample(case))
    members = [Path(d.member_path).name for d in processed.derived_blobs]
    assert sorted(members) == sorted(case["expected_entities"])
    assert ".DS_Store" not in members
    assert processed.document.catalog["skipped"] == 1


def test_tdms_units_and_peak():
    pytest.importorskip("nptdms")
    import pyarrow.compute as pc

    from backend.routes.c_telemetry.tdms import tdms_source

    case = _values()["fmt-c-tdms-chamber-peak"]
    path = _sample(case)
    source = tdms_source(path, path.name)
    assert not source.failed
    assert source.units["Chamber Pressure"] in case["expected_entities"]
    peak = max(pc.max(batch.column("Chamber Pressure")).as_py() for batch in source.open_batches())
    [expected] = case["expected_numeric"]
    assert _close(peak, expected), f"peak {peak}, expected {expected['value']}"
