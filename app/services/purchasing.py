import math

import numpy as np
from sqlalchemy import select

from ..extensions import db
from ..models import Inventory, Product
from . import optimization

DEFAULT_BUDGET_SHARE = 0.6
DEFAULT_CAPACITY_SHARE = 0.7
FALLBACK_COST_RATE = 0.6


def unit_cost(product):
    cost = float(product.cost)
    return cost if cost > 0 else float(product.price) * FALLBACK_COST_RATE


def restock_candidates(company_id):
    return db.session.execute(
        select(Product, Inventory)
        .join(Inventory, Inventory.product_id == Product.id)
        .where(
            Product.company_id == company_id,
            Product.active.is_(True),
            Inventory.reorder_point > 0,
            Inventory.quantity <= Inventory.reorder_point,
            Inventory.eoq > 0,
        )
        .order_by(Product.name)
    ).all()


def empty_plan(budget, capacity):
    return {
        "status": "sin_candidatos",
        "usage": [],
        "at_limit": 0,
        "items": [],
        "budget": budget or 0.0,
        "capacity": capacity or 0.0,
        "totals": {"cost": 0.0, "units": 0, "margin": 0.0},
        "unrestricted": {"cost": 0.0, "units": 0, "margin": 0.0},
        "shadow": {"budget": 0.0, "capacity": 0.0},
        "binding": {"budget": False, "capacity": False},
        "slack": {"budget": 0.0, "capacity": 0.0},
        "objective_lp": 0.0,
        "pivots": 0,
        "verified": False,
        "active_constraints": 0,
        "variables": 0,
    }


def purchase_plan(company_id, budget=None, capacity=None):
    if budget is not None and budget < 0:
        raise ValueError("el presupuesto no puede ser negativo")
    if capacity is not None and capacity < 0:
        raise ValueError("la capacidad no puede ser negativa")
    candidates = restock_candidates(company_id)
    if not candidates:
        return empty_plan(budget, capacity)

    costs = np.array([unit_cost(product) for product, _ in candidates])
    margins = np.array([float(product.price) - unit_cost(product) for product, _ in candidates])
    limits = np.array([float(inventory.eoq) for _, inventory in candidates])
    size = len(candidates)

    full_cost = float(costs @ limits)
    full_units = float(limits.sum())
    if budget is None:
        budget = float(round(DEFAULT_BUDGET_SHARE * full_cost))
    if capacity is None:
        capacity = float(math.floor(DEFAULT_CAPACITY_SHARE * full_units))

    matrix = np.vstack([costs, np.ones(size), np.eye(size)])
    bounds = np.concatenate([[budget, capacity], limits])
    result = optimization.simplex_max(margins, matrix, bounds)
    solution = np.clip(result["x"], 0.0, limits)
    check = optimization.verify_vertex(matrix, bounds, solution)
    quantities = np.floor(solution + 1e-9)

    items = []
    for position, (product, inventory) in enumerate(candidates):
        items.append(
            {
                "index": position + 1,
                "var": "x{}".format(position + 1),
                "product_id": product.id,
                "sku": product.sku,
                "name": product.name,
                "stock": inventory.quantity,
                "reorder_point": inventory.reorder_point,
                "eoq": inventory.eoq,
                "cost": float(costs[position]),
                "margin": float(margins[position]),
                "quantity": int(quantities[position]),
                "quantity_lp": float(solution[position]),
            }
        )
    items.sort(key=lambda item: (-item["quantity"], item["name"]))

    spent = float(costs @ quantities)
    units = int(quantities.sum())
    slack_budget = budget - spent
    slack_capacity = capacity - float(quantities.sum())
    duals = result["duals"]
    usage = [
        {
            "resource": "Presupuesto",
            "equivalent": "materia prima",
            "available": float(budget),
            "used": spent,
            "slack": float(slack_budget),
            "shadow": float(duals[0]),
            "money": True,
        },
        {
            "resource": "Capacidad de bodega",
            "equivalent": "capacidad de producción",
            "available": float(capacity),
            "used": float(units),
            "slack": float(slack_capacity),
            "shadow": float(duals[1]),
            "money": False,
        },
    ]
    return {
        "status": "ok",
        "usage": usage,
        "at_limit": sum(1 for item in items if item["quantity"] >= item["eoq"]),
        "items": items,
        "budget": float(budget),
        "capacity": float(capacity),
        "totals": {"cost": spent, "units": units, "margin": float(margins @ quantities)},
        "unrestricted": {"cost": full_cost, "units": int(full_units), "margin": float(margins @ limits)},
        "shadow": {"budget": float(duals[0]), "capacity": float(duals[1])},
        "binding": {
            "budget": float(duals[0]) > optimization.TOLERANCE,
            "capacity": float(duals[1]) > optimization.TOLERANCE,
        },
        "slack": {"budget": float(slack_budget), "capacity": float(slack_capacity)},
        "pivots": len(result["pivots"]),
        "verified": check["verified"],
        "active_constraints": len(check["active"]),
        "variables": size,
        "objective_lp": float(result["objective"]),
    }
