import pytest

pytest.importorskip("rocketcea")

from backend.llm_engine.engine.tools import Provenance  # noqa: E402
from backend.llm_engine.engine.tools.physics import PhysicsArgs, physics_calculator  # noqa: E402


def calc(operation, **parameters):
    return physics_calculator(PhysicsArgs(operation=operation, parameters=parameters))


def test_mass_flow_for_5_newton_at_225_seconds():
    out = calc("mass_flow_from_thrust", thrust="5 N", isp="225 s")
    assert out.result["mass_flow_g_s"] == pytest.approx(5 / (225 * 9.80665) * 1000)
    assert "2.266 g/s" in out.display
    assert out.provenance[0].provenance is Provenance.CALCULATION


def test_inputs_in_other_units_are_converted_and_echoed_in_si():
    out = calc("mass_flow_from_thrust", thrust="1.124 lbf", isp="225 s")
    assert "5 N" in out.display or "5.0" in out.display


def test_htp90_decomposition_temperature_matches_the_published_value():
    out = calc("cea_performance", propellant="90% HTP", pc="10 bar", eps="50")
    assert out.result["propellant"] == "HTP90"
    assert out.result["tc_k"] == pytest.approx(1022, rel=0.015)
    assert "equilibrium" in out.display and "Tc 1030 K" in out.display


def test_isentropic_sizing_is_consistent_with_mass_flow_from_thrust():
    out = calc(
        "isentropic_sizing", pc="10 bar", tc="1030 K", gamma="1.265", mw="22.1 g/mol", eps="50", thrust="1 N"
    )
    r = out.result
    assert r["exit_mach"] > 3 and r["cf"] > 1.5
    assert r["mass_flow_g_s"] == pytest.approx(1 / (r["isp_s"] * 9.80665) * 1000)
    assert "Throat area" in out.display and "ideal rocket" in out.display


def test_unit_convert_and_scaling():
    assert calc("unit_convert", value="12.4 bar", to="psi").display.startswith("12.4 bar = 179.8 psi")
    scaled = calc("scale_thruster", thrust_ref="1 N", throat_area_ref="0.8 mm^2", thrust_new="5 N")
    assert scaled.result["throat_area_mm2"] == pytest.approx(4.0)


def test_errors_are_reported_not_raised():
    out = calc("cea_performance", propellant="unobtainium", pc="10 bar", eps="50")
    assert out.result is None and "unknown propellant" in out.warnings[0]
    assert "missing parameter 'isp'" in calc("mass_flow_from_thrust", thrust="5 N").warnings[0]
