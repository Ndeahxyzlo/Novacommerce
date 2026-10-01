import numpy as np
import pytest
from sqlalchemy import text

from app.extensions import db
from app.ml import demand
from app.services import etl, optimization, purchasing
from .conftest import login
from .test_warehouse_ml import seeded

WYNDOR_C = [3, 5]
WYNDOR_A = [[1, 0], [0, 2], [3, 2]]
WYNDOR_B = [4, 12, 18]


def test_simplex_textbook_problem():
    result = optimization.simplex_max(WYNDOR_C, WYNDOR_A, WYNDOR_B)
    assert result["status"] == "optimal"
    assert np.allclose(result["x"], [2, 6])
    assert result["objective"] == pytest.approx(36.0)
    assert np.allclose(result["duals"], [0, 1.5, 1])


def test_simplex_records_tableaus():
    result = optimization.simplex_max(WYNDOR_C, WYNDOR_A, WYNDOR_B, record=True)
    assert len(result["tableaus"]) == len(result["pivots"]) + 1
    first = result["tableaus"][0]
    assert np.allclose(first[-1, :2], [-3, -5])
    assert result["tableaus"][-1][-1, -1] == pytest.approx(36.0)


def test_simplex_detects_unbounded():
    result = optimization.simplex_max([1, 0], [[-1, 1]], [1])
    assert result["status"] == "unbounded"
    assert result["x"] is None


def test_simplex_zero_objective_and_degenerate():
    result = optimization.simplex_max([0, 0], [[1, 1]], [5])
    assert result["status"] == "optimal"
    assert result["objective"] == 0
    degenerate = optimization.simplex_max([2, 1], [[1, 0], [0, 1], [1, 1]], [0, 4, 4])
    assert degenerate["status"] == "optimal"
    assert degenerate["objective"] == pytest.approx(4.0)


def test_simplex_rejects_negative_rhs():
    with pytest.raises(ValueError):
        optimization.simplex_max([1], [[1]], [-1])


def test_simplex_matches_scipy_on_random_problems():
    linprog = pytest.importorskip("scipy.optimize").linprog
    generator = np.random.default_rng(11)
    for _ in range(60):
        rows = int(generator.integers(2, 9))
        columns = int(generator.integers(2, 9))
        a = generator.uniform(0.1, 5.0, size=(rows, columns))
        b = generator.uniform(1.0, 30.0, size=rows)
        c = generator.uniform(0.0, 10.0, size=columns)
        ours = optimization.simplex_max(c, a, b)
        reference = linprog(-c, A_ub=a, b_ub=b, bounds=(0, None), method="highs")
        assert ours["status"] == "optimal"
        assert ours["objective"] == pytest.approx(-reference.fun, rel=1e-6, abs=1e-6)
        assert np.all(a @ ours["x"] <= b + 1e-6)


def test_elimination_and_substitution_agree_with_numpy():
    generator = np.random.default_rng(5)
    for size in range(1, 9):
        a = generator.uniform(-5, 5, size=(size, size)) + np.eye(size) * 6
        b = generator.uniform(-10, 10, size=size)
        expected = np.linalg.solve(a, b)
        assert np.allclose(optimization.solve_elimination(a, b), expected)
        assert np.allclose(optimization.solve_substitution(a, b), expected)


def test_two_by_two_example_by_hand():
    a = [[2, 1], [1, -1]]
    b = [10, 2]
    assert np.allclose(optimization.solve_elimination(a, b), [4, 2])
    assert np.allclose(optimization.solve_substitution(a, b), [4, 2])


def test_singular_systems_raise():
    singular = [[1, 2], [2, 4]]
    with pytest.raises(optimization.SingularSystem):
        optimization.solve_elimination(singular, [1, 2])
    with pytest.raises(optimization.SingularSystem):
        optimization.solve_substitution(singular, [1, 2])
    with pytest.raises(ValueError):
        optimization.solve_elimination([[1, 2, 3], [4, 5, 6]], [1, 2])


def test_vertex_is_verified_by_elimination():
    result = optimization.simplex_max(WYNDOR_C, WYNDOR_A, WYNDOR_B)
    check = optimization.verify_vertex(WYNDOR_A, WYNDOR_B, result["x"])
    assert check["verified"] is True
    assert np.allclose(check["solution"], [2, 6])
    assert len(check["active"]) == 2
    interior = optimization.verify_vertex(WYNDOR_A, WYNDOR_B, [1, 1])
    assert interior["verified"] is False


def test_purchase_plan_respects_constraints(seeded, ctx):
    etl.run_etl(full=True)
    company_id = db.session.scalar(text("select id from companies order by id limit 1"))
    demand.run_company_pipeline(company_id, refresh_warehouse=False)
    plan = purchasing.purchase_plan(company_id)
    assert plan["status"] == "ok"
    assert plan["verified"] is True
    assert plan["totals"]["cost"] <= plan["budget"] + 1e-6
    assert plan["totals"]["units"] <= plan["capacity"]
    assert plan["totals"]["margin"] <= plan["unrestricted"]["margin"] + 1e-6
    assert plan["totals"]["margin"] <= plan["objective_lp"] + 1e-6
    for item in plan["items"]:
        assert 0 <= item["quantity"] <= item["eoq"]

    generous = purchasing.purchase_plan(company_id, budget=1e12, capacity=1e9)
    assert generous["totals"]["units"] == generous["unrestricted"]["units"]
    assert generous["binding"] == {"budget": False, "capacity": False}

    none = purchasing.purchase_plan(company_id, budget=0, capacity=0)
    assert none["totals"]["units"] == 0

    with pytest.raises(ValueError):
        purchasing.purchase_plan(company_id, budget=-1)


def test_purchase_page_renders(seeded, client, ctx):
    etl.run_etl(full=True)
    demand.run_all_companies()
    login(client, "owner.tienda-andina@novacommerce.local", "Demo12345x")
    assert client.get("/reportes/compras").status_code == 200
    assert client.get("/reportes/compras?presupuesto=500000&capacidad=40").status_code == 200
    assert client.get("/reportes/compras?presupuesto=abc&capacidad=-5").status_code == 200


def test_demand_model_is_adopted_only_when_it_beats_baseline(seeded, ctx):
    etl.run_etl(full=True)
    company_id = db.session.scalar(text("select id from companies order by id limit 1"))
    panel = demand.load_panel(company_id)
    features = demand.build_features(panel)
    bundle, metrics = demand.train_model(features)
    if bundle is None:
        assert metrics["mae"] >= metrics["baseline_mae"]
    else:
        assert metrics["mae"] < metrics["baseline_mae"]


def test_worked_example_used_in_documentation():
    c = [50, 90]
    a = [[60, 120], [1, 1]]
    b = [6000, 80]
    result = optimization.simplex_max(c, a, b, record=True)
    assert np.allclose(result["x"], [60, 20])
    assert result["objective"] == pytest.approx(4800.0)
    assert np.allclose(result["duals"], [2 / 3, 10])
    assert result["pivots"] == [(1, 2), (0, 3)]
    assert len(result["tableaus"]) == 3
    reduced = [[1, 2], [1, 1]]
    assert np.allclose(optimization.solve_substitution(reduced, [100, 80]), [60, 20])
    assert np.allclose(optimization.solve_elimination(reduced, [100, 80]), [60, 20])
