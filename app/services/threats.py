import itertools
from fractions import Fraction

import numpy as np

from . import optimization

MODE_CLASS = "clase"
MODE_EXTENDED = "ampliado"
MODES = (MODE_CLASS, MODE_EXTENDED)
MAX_ENUMERATION = 250000

SCENARIOS = [
    {
        "key": "ransomware",
        "name": "Ransomware en entorno aislado (sandbox)",
        "short": "Ransomware",
        "servers": 2.0,
        "analysts": 1.0,
        "points": 5.0,
        "origin": "ejercicio",
    },
    {
        "key": "phishing",
        "name": "Phishing e ingeniería social",
        "short": "Phishing",
        "servers": 1.0,
        "analysts": 2.0,
        "points": 4.0,
        "origin": "ejercicio",
    },
    {
        "key": "brute",
        "name": "Fuerza bruta contra el inicio de sesión",
        "short": "Fuerza bruta",
        "servers": 1.0,
        "analysts": 2.0,
        "points": 3.0,
        "origin": "supuesto",
    },
    {
        "key": "stuffing",
        "name": "Relleno de credenciales (credential stuffing)",
        "short": "Relleno de credenciales",
        "servers": 3.0,
        "analysts": 1.0,
        "points": 6.0,
        "origin": "supuesto",
    },
]

DEFAULT_HOURS = {
    MODE_CLASS: (10.0, 8.0),
    MODE_EXTENDED: (16.0, 12.0),
}

MINIMUM_COVERAGE = {MODE_CLASS: 0, MODE_EXTENDED: 1}


def scenarios_for(mode):
    if mode == MODE_CLASS:
        return [dict(item) for item in SCENARIOS[:2]]
    return [dict(item) for item in SCENARIOS]


def fraction_text(value):
    value = float(value)
    if abs(value) < 1e-9:
        return "0"
    fraction = Fraction(value).limit_denominator(1000)
    if abs(float(fraction) - value) > 1e-7:
        return "{:.3f}".format(value).replace(".", ",")
    if fraction.denominator == 1:
        return str(fraction.numerator)
    return "{}/{}".format(fraction.numerator, fraction.denominator)


def variable_names(variables, slacks, prefix="x"):
    return ["{}{}".format(prefix, i + 1) for i in range(variables)] + ["s{}".format(i + 1) for i in range(slacks)]


def describe_tableaus(result, variables, slacks, prefix="x"):
    names = variable_names(variables, slacks, prefix)
    basis = [variables + row for row in range(slacks)]
    steps = []
    labels = ["Tabla inicial"]
    for number, (entering, leaving) in enumerate(result["pivots"], start=1):
        labels.append("Iteración {} (entra {}, sale {})".format(number, names[entering], names[leaving]))
    for position, tableau in enumerate(result["tableaus"]):
        rows = []
        for row in range(slacks):
            rows.append({"base": names[basis[row]], "cells": [fraction_text(v) for v in tableau[row]]})
        rows.append({"base": "Z", "cells": [fraction_text(v) for v in tableau[-1]]})
        steps.append({"label": labels[position], "rows": rows})
        if position < len(result["pivots"]):
            entering, leaving = result["pivots"][position]
            basis[basis.index(leaving)] = entering
    return {"header": names + ["Derecha"], "steps": steps}


def integer_search(points, matrix, limits):
    bounds = []
    for column in range(matrix.shape[1]):
        caps = [limits[row] / matrix[row, column] for row in range(matrix.shape[0]) if matrix[row, column] > 0]
        bounds.append(int(np.floor(min(caps) + 1e-9)) if caps else 0)
    size = 1
    for bound in bounds:
        size *= bound + 1
    if size > MAX_ENUMERATION:
        return None
    best = None
    best_value = -1.0
    best_used = None
    for candidate in itertools.product(*[range(bound + 1) for bound in bounds]):
        vector = np.array(candidate, dtype=float)
        used = matrix @ vector
        if np.any(used > limits + 1e-9):
            continue
        value = float(points @ vector)
        total = float(used.sum())
        if value > best_value + 1e-9 or (abs(value - best_value) <= 1e-9 and total < best_used - 1e-9):
            best, best_value, best_used = vector, value, total
    return best


def empty_threat_plan(mode, servers, analysts, reason):
    return {
        "status": reason,
        "mode": mode,
        "scenarios": [],
        "servers": servers,
        "analysts": analysts,
        "usage": [],
        "totals": {"points": 0.0, "servers": 0.0, "analysts": 0.0, "simulations": 0},
        "objective_lp": 0.0,
        "objective_integer": 0.0,
        "shadow": {"servers": 0.0, "analysts": 0.0},
        "binding": {"servers": False, "analysts": False},
        "pivots": 0,
        "verified": False,
        "active_constraints": 0,
        "tableaus": {"header": [], "steps": []},
        "integer_exact": False,
        "lp_is_integer": False,
    }


def threat_plan(mode=MODE_CLASS, servers=None, analysts=None):
    if mode not in MODES:
        raise ValueError("modo desconocido")
    default_servers, default_analysts = DEFAULT_HOURS[mode]
    servers = default_servers if servers is None else float(servers)
    analysts = default_analysts if analysts is None else float(analysts)
    if servers < 0 or analysts < 0:
        raise ValueError("las horas disponibles no pueden ser negativas")

    scenarios = scenarios_for(mode)
    size = len(scenarios)
    points = np.array([item["points"] for item in scenarios])
    matrix = np.array([[item["servers"] for item in scenarios], [item["analysts"] for item in scenarios]])
    minimum = np.full(size, float(MINIMUM_COVERAGE[mode]))
    limits = np.array([servers, analysts])
    remaining = limits - matrix @ minimum
    if np.any(remaining < -1e-9):
        return empty_threat_plan(mode, servers, analysts, "infactible")

    result = optimization.simplex_max(points, matrix, remaining, record=True)
    shifted_lp = np.clip(result["x"], 0.0, None)
    check = optimization.verify_vertex(matrix, remaining, shifted_lp)
    x_lp = shifted_lp + minimum
    objective_lp = float(points @ x_lp)

    exact = True
    shifted_int = integer_search(points, matrix, remaining)
    if shifted_int is None:
        exact = False
        shifted_int = np.floor(shifted_lp + 1e-9)
    x_int = shifted_int + minimum
    used = matrix @ x_int
    objective_int = float(points @ x_int)
    duals = result["duals"]

    items = []
    for position, scenario in enumerate(scenarios):
        items.append(
            {
                "index": position + 1,
                "var": "x{}".format(position + 1),
                "key": scenario["key"],
                "name": scenario["name"],
                "short": scenario["short"],
                "origin": scenario["origin"],
                "servers": scenario["servers"],
                "analysts": scenario["analysts"],
                "points": scenario["points"],
                "minimum": int(minimum[position]),
                "quantity": int(round(x_int[position])),
                "quantity_lp": float(x_lp[position]),
            }
        )

    usage = [
        {
            "resource": "Horas de servidores virtuales",
            "available": servers,
            "used": float(used[0]),
            "slack": float(servers - used[0]),
            "shadow": float(duals[0]),
        },
        {
            "resource": "Horas de analistas del Red Team",
            "available": analysts,
            "used": float(used[1]),
            "slack": float(analysts - used[1]),
            "shadow": float(duals[1]),
        },
    ]
    return {
        "status": "ok",
        "mode": mode,
        "scenarios": items,
        "servers": servers,
        "analysts": analysts,
        "usage": usage,
        "totals": {
            "points": objective_int,
            "servers": float(used[0]),
            "analysts": float(used[1]),
            "simulations": int(round(x_int.sum())),
        },
        "objective_lp": objective_lp,
        "objective_integer": objective_int,
        "shadow": {"servers": float(duals[0]), "analysts": float(duals[1])},
        "binding": {
            "servers": float(duals[0]) > optimization.TOLERANCE,
            "analysts": float(duals[1]) > optimization.TOLERANCE,
        },
        "pivots": len(result["pivots"]),
        "verified": check["verified"],
        "active_constraints": len(check["active"]),
        "tableaus": describe_tableaus(result, size, 2, "y" if MINIMUM_COVERAGE[mode] else "x"),
        "integer_exact": exact,
        "lp_is_integer": bool(np.allclose(x_lp, np.round(x_lp), atol=1e-7)),
    }
