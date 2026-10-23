"""ANSYS Workbench packages (``.wbpz``, file 03 §11 step 5).

- Solver ``.out`` logs: the solver-summary lines (solver, version, elements, nodes, iterations,
  convergence, CPU and elapsed time, warnings and errors) parsed into key/value pairs; each log is a node.
- Engineering data (MatML XML, ``EngineeringData.xml`` or ``*.engd`` / ``MatML`` parts): materials with their
  property values and units → one table node per material and ``material`` mentions.
- The project file (``.wbpj``): analysis system names found in it.
- Report images go on to Route D as archive members; the rest of the package is described by the manifest.
"""

import re
from dataclasses import dataclass, field

from lxml import etree

SUMMARY = [
    (
        "solver",
        re.compile(
            r"\b(ANSYS (?:Mechanical|Fluent|CFX|LS-DYNA)[^\n]*?|MAPDL[^\n]*?)"
            r"\s*(?:Release|Version)?\s*([\d.]+R?\d*)?\s*$",
            re.I | re.M,
        ),
    ),
    ("elements", re.compile(r"(?:number of|total)\s+elements\s*[:=]?\s*([\d,]+)", re.I)),
    ("nodes", re.compile(r"(?:number of|total)\s+nodes\s*[:=]?\s*([\d,]+)", re.I)),
    (
        "iterations",
        re.compile(r"(?:total\s+)?(?:number of\s+)?(?:equilibrium\s+)?iterations?\s*(?:=|:)\s*(\d+)", re.I),
    ),
    (
        "converged",
        re.compile(r"\b(solution (?:is )?converged[^\n]*|converged after[^\n]*|not converged[^\n]*)", re.I),
    ),
    ("cpu_time", re.compile(r"(?:total\s+)?CPU\s+time[^\n=:]*[=:]\s*([\d.]+\s*\w*)", re.I)),
    ("elapsed_time", re.compile(r"elapsed\s+time[^\n=:]*[=:]\s*([\d.]+\s*\w*)", re.I)),
]
PROBLEMS = re.compile(r"^\s*\*{0,3}\s*(WARNING|ERROR)\b[^\n]*", re.I | re.M)
SYSTEMS = re.compile(
    r"(Static Structural|Transient Structural|Modal|Harmonic Response|Steady-State Thermal|Transient Thermal|"
    r"Fluid Flow \((?:Fluent|CFX)\)|Fluent|CFX|Explicit Dynamics|Eigenvalue Buckling|Random Vibration|"
    r"Response Spectrum|Thermal-Electric|Engineering Data|Geometry|Mesh)"
)


@dataclass
class Material:
    name: str
    properties: list[tuple[str, str, str]] = field(default_factory=list)  # (property, value, unit)


def solver_summary(text: str) -> dict[str, str | list[str]]:
    found: dict[str, str | list[str]] = {}
    for key, pattern in SUMMARY:
        match = pattern.search(text)
        if match:
            found[key] = (
                " ".join(g for g in match.groups() if g).strip() if match.groups() else match.group(0)
            )
    problems = [m.group(0).strip()[:200] for m in PROBLEMS.finditer(text)]
    if problems:
        found["warnings_errors"] = problems[:20]
    return found


def _units(details) -> str:
    units = []
    for unit in details.iter("Unit"):
        name = (unit.findtext("Name") or "").strip()
        power = unit.get("power")
        if name:
            units.append(f"{name}^{power}" if power and power != "1" else name)
    return " ".join(units)


def materials(xml: bytes) -> list[Material]:
    """MatML (``<MatML_Doc>``): ``<Material><BulkDetails><Name>`` with ``<PropertyData>`` →
    ``<ParameterValue parameter="pa1"><Data>``, names and units in ``<Metadata><ParameterDetails id>``."""
    try:
        root = etree.fromstring(xml, etree.XMLParser(resolve_entities=False, no_network=True))
    except etree.XMLSyntaxError:
        return []
    for element in root.iter():
        if isinstance(element.tag, str) and "}" in element.tag:
            element.tag = element.tag.split("}", 1)[1]
    parameters = {
        d.get("id"): ((d.findtext("Name") or d.get("id") or "").strip(), _units(d))
        for d in root.iter("ParameterDetails")
    }
    properties = {d.get("id"): (d.findtext("Name") or "").strip() for d in root.iter("PropertyDetails")}
    out = []
    for material in root.iter("Material"):
        bulk = material.find("BulkDetails")
        if bulk is None:
            continue
        item = Material((bulk.findtext("Name") or "unnamed material").strip())
        for data in bulk.iter("PropertyData"):
            group = properties.get(data.get("property"), "")
            for value in data.iter("ParameterValue"):
                name, unit = parameters.get(value.get("parameter"), (value.get("parameter") or "", ""))
                raw = (value.findtext("Data") or "").strip()
                if raw and name and not name.casefold().startswith(("options variable", "temperature")):
                    label = name if not group or group == name else f"{group}: {name}"
                    item.properties.append((label, raw.split(",")[0].strip(), unit))
        out.append(item)
    return out


def project_systems(text: str) -> list[str]:
    return sorted(set(SYSTEMS.findall(text)))
