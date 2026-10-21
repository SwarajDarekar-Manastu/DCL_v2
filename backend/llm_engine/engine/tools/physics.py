"""T5 `physics_calculator` (file 07 §4): deterministic propulsion arithmetic. The model never computes.

Operations (parameters are strings with units, parsed by S1's registry):
- `unit_convert`: `{value: "12.4 bar", to: "psi"}`.
- `mass_flow_from_thrust`: `{thrust, isp}` → ṁ = F / (Isp·g0).
- `isentropic_sizing`: `{pc, tc, gamma, mw, eps, thrust, pamb?}` → c*, exit Mach, pe, CF, throat and exit
  area, mass flow (ideal rocket, frozen composition, no losses).
- `cea_performance`: `{propellant, pc, eps, pamb?, frozen?}` → Isp (vacuum, ambient), c*, Tc, γ, MW from
  RocketCEA with S5's `config/propellants.yaml` cards (equilibrium unless `frozen`).
- `scale_thruster`: `{thrust_ref, throat_area_ref, thrust_new}` → throat area at the same chamber pressure.
Results are formatted to 4 significant figures once, in `display`; inputs are echoed in SI with the equations
and assumptions used. Identical inputs give identical outputs (cached by the normalized arguments).
"""

import json
import math
from functools import cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field

from backend.common.units import UnitError, parse_unit, registry
from backend.llm_engine.engine.tools import Provenance, Source, ToolResult

G0 = 9.80665
R_UNIVERSAL = 8.314462618
PROPELLANTS_FILE = Path(__file__).resolve().parents[4] / "config" / "propellants.yaml"
NAME = "physics_calculator"
DESCRIPTION = (
    "Deterministic propulsion arithmetic: unit conversion, mass flow from thrust and Isp, isentropic nozzle "
    "sizing, RocketCEA performance for the team's propellants, thruster scaling. "
    "Parameters are strings with units."
)


class PhysicsArgs(BaseModel):
    operation: Literal[
        "unit_convert", "mass_flow_from_thrust", "isentropic_sizing", "cea_performance", "scale_thruster"
    ]
    parameters: dict[str, str] = Field(
        description='quantities with units, e.g. {"thrust": "5 N", "isp": "225 s"}'
    )


class PhysicsError(ValueError):
    pass


def fmt(value: float, unit: str) -> str:
    return f"{value:.4g} {unit}".strip()


def _q(parameters: dict[str, str], name: str, unit: str) -> float:
    if name not in parameters:
        raise PhysicsError(f"missing parameter {name!r}")
    text = parameters[name].strip()
    try:
        quantity = registry().Quantity(text) if any(c.isalpha() or c in "°%" for c in text) else None
    except Exception:  # noqa: BLE001 (pint raises many types; reported below)
        quantity = None
    if quantity is None:
        try:
            value = float(text)
        except ValueError as exc:
            raise PhysicsError(f"cannot read {name}={text!r}") from exc
        return value if unit == "" else float(registry().Quantity(value, unit).magnitude)
    try:
        return float(quantity.to(unit).magnitude) if unit else float(quantity.to("dimensionless").magnitude)
    except Exception as exc:  # noqa: BLE001
        raise PhysicsError(f"{name}={text!r} cannot be expressed in {unit or 'a plain number'}") from exc


@cache
def _propellants() -> dict[str, dict]:
    data = yaml.safe_load(PROPELLANTS_FILE.read_text(encoding="utf-8"))
    table = {}
    for entry in data.get("propellants", []):
        for alias in [entry["id"], *entry.get("aliases", [])]:
            table[alias.lower().replace(" ", "")] = entry
    return table


@cache
def _cea(propellant_id: str):
    from rocketcea.cea_obj import CEA_Obj, add_new_fuel, add_new_oxidizer, add_new_propellant

    entry = next(e for e in _propellants().values() if e["id"] == propellant_id)
    register = {"monopropellant": add_new_propellant, "oxidizer": add_new_oxidizer, "fuel": add_new_fuel}
    register[entry["kind"]](entry["id"], entry["card"])
    return CEA_Obj(propName=entry["id"])


def unit_convert(p: dict[str, str]) -> tuple[dict, str, list[str]]:
    try:
        source = registry().Quantity(p["value"])
        parse_unit(p["to"])
        converted = source.to(p["to"])
    except (KeyError, UnitError, Exception) as exc:  # noqa: BLE001
        raise PhysicsError(f"cannot convert {p.get('value')!r} to {p.get('to')!r}: {exc}") from exc
    text = fmt(float(converted.magnitude), p["to"])
    return (
        {"value": float(converted.magnitude), "unit": p["to"]},
        f"{p['value']} = {text}",
        ["pint conversion"],
    )


def mass_flow_from_thrust(p: dict[str, str]) -> tuple[dict, str, list[str]]:
    thrust, isp = _q(p, "thrust", "N"), _q(p, "isp", "s")
    mdot = thrust / (isp * G0)
    display = f"Mass flow for {fmt(thrust, 'N')} at Isp {fmt(isp, 's')}: {fmt(mdot * 1000, 'g/s')}"
    return {"mass_flow_g_s": mdot * 1000, "thrust_n": thrust, "isp_s": isp}, display, ["mdot = F / (Isp g0)"]


def _exit_mach(eps: float, gamma: float) -> float:
    def area_ratio(mach: float) -> float:
        term = (2 / (gamma + 1)) * (1 + (gamma - 1) / 2 * mach**2)
        return term ** ((gamma + 1) / (2 * (gamma - 1))) / mach

    low, high = 1.0001, 50.0
    for _ in range(200):
        mid = (low + high) / 2
        if area_ratio(mid) < eps:
            low = mid
        else:
            high = mid
    return (low + high) / 2


def isentropic_sizing(p: dict[str, str]) -> tuple[dict, str, list[str]]:
    pc, tc = _q(p, "pc", "Pa"), _q(p, "tc", "K")
    gamma, mw, eps = _q(p, "gamma", ""), _q(p, "mw", "g/mol"), _q(p, "eps", "")
    thrust = _q(p, "thrust", "N")
    pamb = _q(p, "pamb", "Pa") if "pamb" in p else 0.0
    r_specific = R_UNIVERSAL / (mw / 1000)
    gamma_term = (2 / (gamma + 1)) ** ((gamma + 1) / (gamma - 1))
    cstar = math.sqrt(gamma * r_specific * tc) / (gamma * math.sqrt(gamma_term))
    mach = _exit_mach(eps, gamma)
    pe = pc * (1 + (gamma - 1) / 2 * mach**2) ** (-gamma / (gamma - 1))
    cf = math.sqrt(2 * gamma**2 / (gamma - 1) * gamma_term * (1 - (pe / pc) ** ((gamma - 1) / gamma)))
    cf += (pe - pamb) / pc * eps
    throat = thrust / (cf * pc)
    mdot = pc * throat / cstar
    result = {
        "cstar_m_s": cstar,
        "exit_mach": mach,
        "pe_pa": pe,
        "cf": cf,
        "throat_area_mm2": throat * 1e6,
        "exit_area_mm2": throat * eps * 1e6,
        "mass_flow_g_s": mdot * 1000,
        "isp_s": thrust / (mdot * G0),
    }
    display = "\n".join(
        [
            f"Inputs (SI): pc {fmt(pc / 1e5, 'bar')}, Tc {fmt(tc, 'K')}, gamma {gamma:.4g}, "
            f"MW {fmt(mw, 'g/mol')}, "
            f"eps {eps:.4g}, thrust {fmt(thrust, 'N')}, pamb {fmt(pamb / 1e5, 'bar')}",
            f"c* {fmt(cstar, 'm/s')}; exit Mach {mach:.4g}; pe {fmt(pe / 1e5, 'bar')}; CF {cf:.4g}",
            f"Throat area {fmt(throat * 1e6, 'mm²')}; exit area {fmt(throat * eps * 1e6, 'mm²')}; "
            f"throat diameter {fmt(2 * math.sqrt(throat / math.pi) * 1000, 'mm')}",
            f"Mass flow {fmt(mdot * 1000, 'g/s')}; ideal Isp {fmt(result['isp_s'], 's')}",
        ]
    )
    return (
        result,
        display,
        [
            "ideal rocket, frozen composition, no nozzle or combustion losses",
            "c* = sqrt(gamma R Tc) / (gamma sqrt((2/(gamma+1))^((gamma+1)/(gamma-1))))",
            "CF from isentropic expansion to the exit Mach of eps, pressure thrust included",
        ],
    )


def cea_performance(p: dict[str, str]) -> tuple[dict, str, list[str]]:
    key = p.get("propellant", "").lower().replace(" ", "")
    entry = _propellants().get(key)
    if entry is None:
        known = sorted({e["id"] for e in _propellants().values()})
        raise PhysicsError(f"unknown propellant {p.get('propellant')!r}; known: {', '.join(known)}")
    pc_bar, eps = _q(p, "pc", "bar"), _q(p, "eps", "")
    frozen = p.get("frozen", "false").lower() in ("true", "1", "yes")
    cea = _cea(entry["id"])
    pc_psia = pc_bar * 14.503773773
    isp_vac = float(cea.get_Isp(Pc=pc_psia, eps=eps, frozen=1 if frozen else 0))
    cstar = float(cea.get_Cstar(Pc=pc_psia)) * 0.3048
    tc = float(cea.get_Tcomb(Pc=pc_psia)) / 1.8
    mw, gamma = (float(x) for x in cea.get_Chamber_MolWt_gamma(Pc=pc_psia, eps=eps))
    result = {
        "propellant": entry["id"],
        "isp_vac_s": isp_vac,
        "cstar_m_s": cstar,
        "tc_k": tc,
        "gamma": gamma,
        "mw_g_mol": mw,
        "frozen": frozen,
    }
    lines = [
        f"{entry['id']} at pc {fmt(pc_bar, 'bar')}, eps {eps:.4g} ({'frozen' if frozen else 'equilibrium'}):",
        f"Isp vacuum {fmt(isp_vac, 's')}; c* {fmt(cstar, 'm/s')}; Tc {fmt(tc, 'K')}; gamma {gamma:.4g}; "
        f"MW {fmt(mw, 'g/mol')}",
    ]
    if "pamb" in p:
        pamb_bar = _q(p, "pamb", "bar")
        isp_amb, mode = cea.estimate_Ambient_Isp(Pc=pc_psia, eps=eps, Pamb=pamb_bar * 14.503773773)
        result["isp_ambient_s"] = float(isp_amb)
        lines.append(f"Isp at {fmt(pamb_bar, 'bar')} ambient {fmt(float(isp_amb), 's')} ({mode})")
    return (
        result,
        "\n".join(lines),
        [
            f"RocketCEA {'frozen' if frozen else 'equilibrium'} composition",
            f"card from config/propellants.yaml ({entry['id']})",
        ],
    )


def scale_thruster(p: dict[str, str]) -> tuple[dict, str, list[str]]:
    thrust_ref, thrust_new = _q(p, "thrust_ref", "N"), _q(p, "thrust_new", "N")
    area_ref = _q(p, "throat_area_ref", "mm**2")
    area = area_ref * thrust_new / thrust_ref
    display = (
        f"Throat area for {fmt(thrust_new, 'N')} (from {fmt(thrust_ref, 'N')} at "
        f"{fmt(area_ref, 'mm²')}): {fmt(area, 'mm²')}; diameter {fmt(2 * math.sqrt(area / math.pi), 'mm')}"
    )
    return {"throat_area_mm2": area}, display, ["same chamber pressure and CF: At scales with thrust"]


OPERATIONS = {
    "unit_convert": unit_convert,
    "mass_flow_from_thrust": mass_flow_from_thrust,
    "isentropic_sizing": isentropic_sizing,
    "cea_performance": cea_performance,
    "scale_thruster": scale_thruster,
}


@cache
def _calculate(operation: str, parameters_json: str) -> tuple[dict, str, tuple[str, ...]]:
    result, display, assumptions = OPERATIONS[operation](json.loads(parameters_json))
    return result, display, tuple(assumptions)


def physics_calculator(args: PhysicsArgs) -> ToolResult:
    try:
        result, display, assumptions = _calculate(args.operation, json.dumps(args.parameters, sort_keys=True))
    except PhysicsError as exc:
        return ToolResult(
            tool=NAME, result=None, warnings=[str(exc)], display=f"Calculation not possible: {exc}"
        )
    source = Source(label=f"calculation: {args.operation}", provenance=Provenance.CALCULATION)
    return ToolResult(
        tool=NAME,
        result={**result, "assumptions": list(assumptions)},
        provenance=[source],
        display=display + "\nAssumptions: " + "; ".join(assumptions),
    )
