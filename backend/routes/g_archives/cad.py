"""CAD files of Route G (file 03 §11 step 6; Lead 2026-10-23: ``.dwg`` like ``.scdoc``, STL/STEP measured).

- ``.scdoc`` (SpaceClaim) and ``.dwg`` have no open parser: a ``cad_reference`` document whose catalog holds
  the file name, size, folder and link, and the drawings and exports found next to it.
- STL (trimesh) and STEP/IGES (trimesh through cascadio, OpenCASCADE): bounding box, extents, volume,
  surface area, triangle and vertex counts, watertightness, number of solids or bodies. STL carries no units,
  so its numbers are in model units; STEP comes back in metres from cascadio and is reported in mm.
- "Related" files: in the same folder, CAD exports and drawings (``.pdf .dxf .dwg .drawio .scdoc .step .stp
  .stl .igs .iges``) whose stem matches this file's stem (case and separators ignored), else every CAD or
  drawing file in the folder as context. S1 writes them as ``document_relations(REFERENCES)``.
"""

import io
import re
from collections.abc import Sequence
from pathlib import PurePosixPath
from typing import Any

DRAWING_SUFFIXES = (".pdf", ".dxf", ".dwg", ".drawio", ".scdoc", ".step", ".stp", ".stl", ".igs", ".iges")
MESH_SUFFIXES = (".stl",)
BREP_SUFFIXES = (".step", ".stp", ".igs", ".iges")
MEASURED_SUFFIXES = (".stl", ".step", ".stp")  # IGES is not measured (03 §11 item 6)
REFERENCE_SUFFIXES = (".scdoc", ".dwg")
MAX_SPLIT_FACES = 2_000_000


class CadError(ValueError):
    pass


def _stem_key(name: str) -> str:
    return re.sub(r"[\W_]+", "", PurePosixPath(name).stem.casefold())


def related_files(path: str, folder_files: Sequence[str]) -> tuple[list[str], list[str]]:
    """(same-stem files, other drawings/CAD in the folder), both without ``path`` itself."""
    folder = str(PurePosixPath(path).parent)
    here = [
        f
        for f in folder_files
        if str(PurePosixPath(f).parent) == folder and f != path and f.casefold().endswith(DRAWING_SUFFIXES)
    ]
    key = _stem_key(path)
    same = [
        f
        for f in here
        if _stem_key(f) == key or (key and (_stem_key(f).startswith(key) or key.startswith(_stem_key(f))))
    ]
    return sorted(same), sorted(f for f in here if f not in same)


def _round(value: float) -> float:
    return float(f"{value:.4g}")


def measure(data: bytes, file_name: str) -> dict[str, Any]:
    import trimesh

    suffix = PurePosixPath(file_name).suffix.casefold()
    file_type = suffix.lstrip(".")
    try:
        loaded = trimesh.load(io.BytesIO(data), file_type="step" if file_type == "stp" else file_type)
    except Exception as exc:  # noqa: BLE001 — trimesh and cascadio raise many types for broken files
        raise CadError(f"{file_name}: the converter could not read it ({type(exc).__name__})") from exc
    if isinstance(loaded, trimesh.Scene):
        meshes = [g for g in loaded.geometry.values() if isinstance(g, trimesh.Trimesh)]
        units = loaded.units
    else:
        meshes, units = [loaded], getattr(loaded, "units", None)
    if not meshes or not any(len(m.faces) for m in meshes):
        raise CadError(f"{file_name}: no geometry")
    scale, shown_units = (1000.0, "mm") if units in ("meters", "m") else (1.0, units or "model units")
    combined = trimesh.util.concatenate(meshes) if len(meshes) > 1 else meshes[0].copy()
    combined.merge_vertices()  # OpenCASCADE tessellates face by face: closed solids arrive unwelded
    lower, upper = combined.bounds
    watertight = combined.is_watertight
    volume = sum(abs(m.volume) for m in meshes)
    result: dict[str, Any] = {
        "format": "STL mesh" if suffix in MESH_SUFFIXES else "B-rep (tessellated by OpenCASCADE)",
        "units": shown_units,
        "units_stated": units is not None,
        "bounding_box_min": [_round(v * scale) for v in lower],
        "bounding_box_max": [_round(v * scale) for v in upper],
        "extents": [_round(v * scale) for v in combined.extents],
        "volume": _round(volume * scale**3),
        "volume_exact": watertight,
        "surface_area": _round(sum(m.area for m in meshes) * scale**2),
        "triangles": int(sum(len(m.faces) for m in meshes)),
        "vertices": int(sum(len(m.vertices) for m in meshes)),
        "watertight": watertight,
    }
    bodies = len(combined.split(only_watertight=False)) if len(combined.faces) <= MAX_SPLIT_FACES else None
    if suffix in BREP_SUFFIXES:
        result["solids"] = bodies if bodies is not None else len(meshes)
        result["solid_names"] = (
            sorted(k for k, g in loaded.geometry.items() if isinstance(g, trimesh.Trimesh))[:50]
            if isinstance(loaded, trimesh.Scene)
            else []
        )
    elif bodies is not None:
        result["bodies"] = bodies
    return result


def describe(
    file_name: str,
    size: int,
    folder: str,
    measurement: dict[str, Any] | None,
    same: list[str],
    other: list[str],
) -> str:
    kind = {".scdoc": "SpaceClaim document", ".dwg": "AutoCAD drawing (DWG)"}.get(
        PurePosixPath(file_name).suffix.casefold(), "CAD model"
    )
    lines = [f"{kind} {file_name} ({size:,} bytes) in {folder}"]
    if measurement:
        unit = measurement["units"]
        x, y, z = measurement["extents"]
        lines.append(f"{measurement['format']}; bounding box {x} × {y} × {z} {unit}")
        lines.append(
            f"from ({', '.join(map(str, measurement['bounding_box_min']))}) to "
            f"({', '.join(map(str, measurement['bounding_box_max']))}) {unit}"
        )
        exact = "" if measurement["volume_exact"] else " (approximate: mesh not watertight)"
        area = measurement["surface_area"]
        lines.append(f"volume {measurement['volume']} {unit}³{exact}; surface area {area} {unit}²")
        count = f"{measurement['triangles']:,} triangles, {measurement['vertices']:,} vertices"
        if "solids" in measurement:
            count += f", {measurement['solids']} solids" + (
                f" ({', '.join(measurement['solid_names'])})" if measurement.get("solid_names") else ""
            )
        if "bodies" in measurement:
            count += f", {measurement['bodies']} bod{'y' if measurement['bodies'] == 1 else 'ies'}"
        lines.append(count)
        if not measurement["units_stated"]:
            lines.append("STL files carry no units: values are in the model's own units")
    elif PurePosixPath(file_name).suffix.casefold() not in MEASURED_SUFFIXES:
        lines.append("No open parser for this format: indexed by name, folder and related files only")
    if same:
        lines.append("Related files (same name): " + ", ".join(PurePosixPath(f).name for f in same))
    if other:
        lines.append(
            "Other drawings and CAD in the folder: " + ", ".join(PurePosixPath(f).name for f in other[:30])
        )
    return "\n".join(lines)
