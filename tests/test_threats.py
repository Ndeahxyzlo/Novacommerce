import numpy as np
import pytest

from app.services import optimization, threats
from .conftest import create_admin, login


def quantities(plan):
    return [item["quantity"] for item in plan["scenarios"]]


def test_class_exercise_matches_hand_solution():
    plan = threats.threat_plan("clase")
    assert plan["status"] == "ok"
    assert quantities(plan) == [4, 2]
    assert plan["totals"]["points"] == pytest.approx(28.0)
    assert plan["objective_lp"] == pytest.approx(28.0)
    assert plan["shadow"]["servers"] == pytest.approx(2.0)
    assert plan["shadow"]["analysts"] == pytest.approx(1.0)
    assert plan["binding"] == {"servers": True, "analysts": True}
    assert plan["pivots"] == 2
    assert plan["verified"] is True
    assert plan["lp_is_integer"] is True
    assert plan["usage"][0]["used"] == pytest.approx(10.0)
    assert plan["usage"][1]["used"] == pytest.approx(8.0)


def test_class_exercise_tableaus_are_the_ones_done_by_hand():
    plan = threats.threat_plan("clase")
    steps = plan["tableaus"]["steps"]
    assert plan["tableaus"]["header"] == ["x1", "x2", "s1", "s2", "Derecha"]
    assert [step["label"] for step in steps][0] == "Tabla inicial"
    assert steps[0]["rows"][2]["cells"] == ["-5", "-4", "0", "0", "0"]
    assert steps[1]["rows"][0]["base"] == "x1"
    assert steps[1]["rows"][2]["cells"] == ["0", "-3/2", "5/2", "0", "25"]
    assert steps[2]["rows"][0]["cells"] == ["1", "0", "2/3", "-1/3", "4"]
    assert steps[2]["rows"][1]["cells"] == ["0", "1", "-1/3", "2/3", "2"]
    assert steps[2]["rows"][2]["cells"] == ["0", "0", "2", "1", "28"]


def test_class_exercise_matches_substitution_and_elimination():
    reduced = [[2, 1], [1, 2]]
    assert np.allclose(optimization.solve_elimination(reduced, [10, 8]), [4, 2])
    assert np.allclose(optimization.solve_substitution(reduced, [10, 8]), [4, 2])


def test_integer_plan_beats_rounding_down_the_relaxation():
    plan = threats.threat_plan("clase", 16, 12)
    assert plan["lp_is_integer"] is False
    assert plan["objective_lp"] == pytest.approx(44.0)
    assert quantities(plan) == [7, 2]
    assert plan["totals"]["points"] == pytest.approx(43.0)
    floored = np.floor([item["quantity_lp"] for item in plan["scenarios"]])
    assert plan["totals"]["points"] > float(np.array([5.0, 4.0]) @ floored)
    assert plan["integer_exact"] is True


def test_extended_mode_respects_resources_and_coverage():
    plan = threats.threat_plan("ampliado")
    assert plan["status"] == "ok"
    assert len(plan["scenarios"]) == 4
    assert all(item["quantity"] >= 1 for item in plan["scenarios"])
    assert plan["totals"]["servers"] <= plan["servers"] + 1e-9
    assert plan["totals"]["analysts"] <= plan["analysts"] + 1e-9
    assert plan["totals"]["points"] <= plan["objective_lp"] + 1e-9
    assert plan["verified"] is True
    assert plan["tableaus"]["header"][0] == "y1"


def test_extended_mode_matches_exhaustive_search():
    plan = threats.threat_plan("ampliado", 20, 15)
    points = np.array([item["points"] for item in plan["scenarios"]])
    matrix = np.array([[item["servers"] for item in plan["scenarios"]], [item["analysts"] for item in plan["scenarios"]]])
    best = 0.0
    for a in range(1, 11):
        for b in range(1, 11):
            for c in range(1, 11):
                for d in range(1, 11):
                    vector = np.array([a, b, c, d], dtype=float)
                    if np.all(matrix @ vector <= [20, 15]):
                        best = max(best, float(points @ vector))
    assert plan["totals"]["points"] == pytest.approx(best)


def test_more_hours_never_reduce_the_index():
    small = threats.threat_plan("clase", 10, 8)["totals"]["points"]
    large = threats.threat_plan("clase", 12, 8)["totals"]["points"]
    assert large >= small


def test_edge_cases():
    assert threats.threat_plan("clase", 0, 0)["totals"]["simulations"] == 0
    assert threats.threat_plan("ampliado", 3, 3)["status"] == "infactible"
    with pytest.raises(ValueError):
        threats.threat_plan("clase", -1, 5)
    with pytest.raises(ValueError):
        threats.threat_plan("otro")


def test_threat_page_renders_formulation_for_admin(client, ctx):
    create_admin()
    login(client, "admin@example.com")
    page = client.get("/admin/simulaciones")
    assert page.status_code == 200
    html = page.get_data(as_text=True)
    for fragment in ("Variables de decisión", "Maximizar Z = 5 x1 + 4 x2", "2 x1 + 1 x2", "Forma estándar", "No negatividad", "Precio sombra"):
        assert fragment in html
    ampliado = client.get("/admin/simulaciones?modo=ampliado")
    assert ampliado.status_code == 200
    assert "Cobertura mínima" in ampliado.get_data(as_text=True)
    assert client.get("/admin/simulaciones?modo=ampliado&servidores=3&analistas=3").status_code == 200
    assert client.get("/admin/simulaciones?modo=xx&servidores=abc&analistas=-5").status_code == 200


def test_threat_page_is_admin_only(client, ctx):
    assert client.get("/admin/simulaciones").status_code == 302
