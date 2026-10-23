"""Smoke test: every S6 route's entry point over every file in ``data/samples`` (real and web) that its
``can_handle`` accepts, vision off. Each accepted file must give a ``ProcessedDocument`` with at least one
node and no exception. A one-line summary per route (files, nodes, flags by type) goes to the terminal so
coverage is visible without ``-s``. Skipped when ``data/samples`` is not exported.

LaTeX files are run as the folder-level assembler plans them (a part is covered by its master's run).
"""

import hashlib
from collections import Counter
from functools import cache
from pathlib import Path

import pytest

SAMPLES = Path(__file__).resolve().parents[4] / "data" / "samples"
HEAD = 4096

pytestmark = pytest.mark.skipif(not SAMPLES.is_dir(), reason="data/samples not exported locally")


def _files() -> list[Path]:
    return sorted(p for p in SAMPLES.rglob("*") if p.is_file() and p.name != "real_samples.yaml")


def _entry(path: Path) -> Path:
    relative = path.relative_to(SAMPLES)
    return SAMPLES / relative.parts[0] if relative.parts[0] != "web" else SAMPLES / "web" / relative.parts[1]


def _folder(path: Path):
    from backend.dispatcher.folder_context import FolderContext

    parts = list(path.relative_to(SAMPLES).parent.parts)
    return FolderContext(root_name="samples", breadcrumb=parts, path_cached="/".join(parts))


def _report(request, route: str, files: int, nodes: int, flags: Counter, failures: list[str]) -> None:
    flag_text = ", ".join(f"{k} {v}" for k, v in sorted(flags.items())) or "none"
    line = f"[smoke] route {route}: {files} files, {nodes} nodes, flags: {flag_text}"
    if failures:
        line += f"; {len(failures)} failed"
    reporter = request.config.pluginmanager.get_plugin("terminalreporter")
    if reporter is not None:
        reporter.write_line(line)
    print(line)


def _check(results: list[tuple[Path, object]]) -> tuple[int, Counter, list[str]]:
    nodes, flags, failures = 0, Counter(), []
    for path, outcome in results:
        if isinstance(outcome, Exception):
            failures.append(f"{path.relative_to(SAMPLES)}: {type(outcome).__name__}: {outcome}")
            continue
        if not outcome.nodes:
            failures.append(
                f"{path.relative_to(SAMPLES)}: no nodes (flags {[str(f.flag_type) for f in outcome.flags]})"
            )
        nodes += len(outcome.nodes)
        flags.update(str(f.flag_type) for f in outcome.flags)
    return nodes, flags, failures


def _run_each(paths, run) -> list[tuple[Path, object]]:
    results = []
    for path in paths:
        try:
            results.append((path, run(path)))
        except Exception as exc:  # noqa: BLE001 — collected and reported per file
            results.append((path, exc))
    return results


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def test_route_a2_smoke(request):
    pytest.importorskip("pylatexenc")
    from backend.dispatcher.assembler import FileRef, assemble, load_section_file_sets
    from backend.postgres.enums import DocumentSourceRole
    from backend.routes.a2_source.route import (
        SourceFile,
        Stores,
        can_handle_json,
        can_handle_tex,
        process_json,
        process_latex,
    )

    stores = Stores(put_cir=lambda k, v: k, put_asset=lambda k, v: f"s3://dcl-assets/{k}")
    accepted = [
        p
        for p in _files()
        if can_handle_tex(p.read_bytes()[:HEAD], p.name) or can_handle_json(p.read_bytes()[:HEAD], p.name)
    ]

    @cache
    def plans(entry: Path):
        kinds = {".tex": "tex", ".pdf": "pdf", ".json": "json"}
        refs = [
            FileRef(str(p.relative_to(entry)), _sha(p.read_bytes()), kinds.get(p.suffix.lower(), "other"))
            for p in entry.rglob("*")
            if p.is_file()
        ]
        return refs, assemble(
            refs, lambda f: (entry / f.path).read_text(errors="replace"), load_section_file_sets()
        )

    results = []
    for path in accepted:
        entry = _entry(path)
        refs, entry_plans = plans(entry)
        relative = str(path.relative_to(entry))
        plan = next((p for p in entry_plans if p.primary.path == relative), None)
        if plan is None:
            continue  # a part: covered by its master's or set's run

        def run(_path, plan=plan, entry=entry, refs=refs):
            files = [
                SourceFile(
                    plan.primary.path,
                    plan.primary.blob_sha256,
                    (entry / plan.primary.path).read_bytes(),
                    DocumentSourceRole.PRIMARY,
                )
            ]
            files += [
                SourceFile(f.path, f.blob_sha256, (entry / f.path).read_bytes(), role)
                for f, role in plan.parts
            ]
            if plan.primary.kind == "json":
                return process_json(files, title=plan.title, folder=_folder(_path), stores=stores)
            return process_latex(
                files,
                title=plan.title,
                folder=_folder(_path),
                stores=stores,
                folder_files=[r.path for r in refs],
                read_file=lambda name, entry=entry: (
                    (entry / name).read_bytes() if (entry / name).is_file() else None
                ),
                conflicts=plan.conflicts,
            )

        results += _run_each([path], run)
    nodes, flags, failures = _check(results)
    _report(request, "A2", len(results), nodes, flags, failures)
    if not results:
        pytest.skip("no sample in data/samples is accepted by this route")
    assert not failures, "\n".join(failures)


def _single_route(request, route: str, can_handle, process) -> None:
    accepted = [p for p in _files() if can_handle(p.read_bytes()[:HEAD], p.name)]
    results = _run_each(accepted, process)
    nodes, flags, failures = _check(results)
    _report(request, route, len(results), nodes, flags, failures)
    if not results:
        pytest.skip("no sample in data/samples is accepted by this route")
    assert not failures, "\n".join(failures)


def test_route_b_smoke(request):
    pytest.importorskip("tree_sitter_python")
    from backend.routes.b_code.route import Stores, can_handle, process_code

    def run(path: Path):
        data = path.read_bytes()
        return process_code(
            data,
            blob_sha256=_sha(data),
            file_name=path.name,
            folder=_folder(path),
            stores=Stores(lambda k, v: k),
        )

    _single_route(request, "B", can_handle, run)


def test_route_e_smoke(request):
    pytest.importorskip("ezdxf")
    from backend.routes.e_diagrams.route import Stores, can_handle, process_diagram

    def run(path: Path):
        data = path.read_bytes()
        return process_diagram(
            data,
            blob_sha256=_sha(data),
            file_name=path.name,
            folder=_folder(path),
            stores=Stores(lambda k, v: k, lambda k, v: f"s3://dcl-assets/{k}"),
        )

    _single_route(request, "E", can_handle, run)


def test_route_g_smoke(request):
    pytest.importorskip("trimesh")
    from backend.routes.g_archives.route import Stores, can_handle, process

    def run(path: Path):
        data = path.read_bytes()
        siblings = [str(p.relative_to(SAMPLES)) for p in path.parent.iterdir() if p.is_file()]
        return process(
            data,
            blob_sha256=_sha(data),
            file_name=path.name,
            folder=_folder(path),
            stores=Stores(lambda k, v: k),
            path=str(path.relative_to(SAMPLES)),
            folder_files=siblings,
        )

    _single_route(request, "G", can_handle, run)
