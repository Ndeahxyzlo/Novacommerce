import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import func, select

from app.extensions import db
from app.models import Inventory, InventoryMovement, Order
from app.services.orders import OrderError, adjust_stock, change_status, place_order

from .conftest import create_customer, create_owner, create_product


def test_place_order_decrements_stock_and_records_movement(ctx):
    company, owner = create_owner("Empresa Uno", "uno@example.com")
    product = create_product(company, quantity=5, price=2500)
    order = place_order(company.id, [(product.id, 3)], channel="pos", status="paid", created_by=owner.id)
    assert order.number == 1
    assert float(order.total) == 7500
    assert db.session.scalar(select(Inventory.quantity).where(Inventory.product_id == product.id)) == 2
    movement = db.session.scalar(select(InventoryMovement).where(InventoryMovement.product_id == product.id))
    assert movement.delta == -3 and movement.reason == "sale"


def test_place_order_rejects_insufficient_stock(ctx):
    company, _ = create_owner("Empresa Uno", "uno@example.com")
    product = create_product(company, quantity=2)
    with pytest.raises(OrderError):
        place_order(company.id, [(product.id, 3)])
    assert db.session.scalar(select(func.count(Order.id))) == 0
    assert db.session.scalar(select(Inventory.quantity).where(Inventory.product_id == product.id)) == 2


def test_place_order_rejects_foreign_product(ctx):
    company_a, _ = create_owner("Empresa Uno", "uno@example.com")
    company_b, _ = create_owner("Empresa Dos", "dos@example.com")
    product_b = create_product(company_b, sku="B-1")
    with pytest.raises(OrderError):
        place_order(company_a.id, [(product_b.id, 1)])


def test_place_order_rejects_invalid_quantities(ctx):
    company, _ = create_owner("Empresa Uno", "uno@example.com")
    product = create_product(company)
    for bad in (0, -1, "x", None, 10001):
        with pytest.raises(OrderError):
            place_order(company.id, [(product.id, bad)])
    with pytest.raises(OrderError):
        place_order(company.id, [])


def test_cancel_restores_stock_once(ctx):
    company, owner = create_owner("Empresa Uno", "uno@example.com")
    product = create_product(company, quantity=5)
    order = place_order(company.id, [(product.id, 4)], created_by=owner.id)
    change_status(company.id, order.id, "cancelled", owner.id)
    assert db.session.scalar(select(Inventory.quantity).where(Inventory.product_id == product.id)) == 5
    with pytest.raises(OrderError):
        change_status(company.id, order.id, "cancelled", owner.id)
    assert db.session.scalar(select(Inventory.quantity).where(Inventory.product_id == product.id)) == 5


def test_status_transitions_are_enforced(ctx):
    company, owner = create_owner("Empresa Uno", "uno@example.com")
    product = create_product(company, quantity=5)
    order = place_order(company.id, [(product.id, 1)])
    with pytest.raises(OrderError):
        change_status(company.id, order.id, "delivered", owner.id)
    change_status(company.id, order.id, "paid", owner.id)
    change_status(company.id, order.id, "shipped", owner.id)
    change_status(company.id, order.id, "delivered", owner.id)
    with pytest.raises(OrderError):
        change_status(company.id, order.id, "cancelled", owner.id)


def test_status_change_scoped_to_company(ctx):
    company_a, _ = create_owner("Empresa Uno", "uno@example.com")
    company_b, _ = create_owner("Empresa Dos", "dos@example.com")
    product = create_product(company_a, quantity=5)
    order = place_order(company_a.id, [(product.id, 1)])
    with pytest.raises(OrderError):
        change_status(company_b.id, order.id, "paid")


def test_adjust_stock_cannot_go_negative(ctx):
    company, owner = create_owner("Empresa Uno", "uno@example.com")
    product = create_product(company, quantity=3)
    with pytest.raises(OrderError):
        adjust_stock(company.id, product.id, -4, "adjustment", owner.id)
    adjust_stock(company.id, product.id, 7, "restock", owner.id)
    assert db.session.scalar(select(Inventory.quantity).where(Inventory.product_id == product.id)) == 10


def test_order_numbers_are_sequential_per_company(ctx):
    company_a, _ = create_owner("Empresa Uno", "uno@example.com")
    company_b, _ = create_owner("Empresa Dos", "dos@example.com")
    product_a = create_product(company_a, sku="A-1", quantity=50)
    product_b = create_product(company_b, sku="B-1", quantity=50)
    numbers_a = [place_order(company_a.id, [(product_a.id, 1)]).number for _ in range(3)]
    numbers_b = [place_order(company_b.id, [(product_b.id, 1)]).number for _ in range(2)]
    assert numbers_a == [1, 2, 3]
    assert numbers_b == [1, 2]


def test_concurrent_orders_never_oversell(app, ctx):
    company, _ = create_owner("Empresa Uno", "uno@example.com")
    product = create_product(company, quantity=5)
    company_id = company.id
    product_id = product.id
    db.session.remove()
    barrier = threading.Barrier(12)
    results = []

    def attempt(_):
        with app.app_context():
            barrier.wait()
            try:
                order = place_order(company_id, [(product_id, 1)])
                results.append(("ok", order.number))
            except OrderError:
                results.append(("fail", None))
            finally:
                db.session.remove()

    with ThreadPoolExecutor(max_workers=12) as pool:
        list(pool.map(attempt, range(12)))

    successes = sorted(number for status, number in results if status == "ok")
    assert len(successes) == 5
    assert successes == [1, 2, 3, 4, 5]
    db.session.remove()
    assert db.session.scalar(select(Inventory.quantity).where(Inventory.product_id == product_id)) == 0


def test_customer_link_validated(ctx):
    company_a, _ = create_owner("Empresa Uno", "uno@example.com")
    company_b, _ = create_owner("Empresa Dos", "dos@example.com")
    product = create_product(company_a, quantity=5)
    foreign_customer = create_customer(company_b)
    with pytest.raises(OrderError):
        place_order(company_a.id, [(product.id, 1)], customer_id=foreign_customer.id)
