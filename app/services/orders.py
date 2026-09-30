from decimal import Decimal

from sqlalchemy import select, update

from ..extensions import db
from ..models import (
    ORDER_CHANNELS,
    Company,
    Customer,
    Inventory,
    InventoryMovement,
    Order,
    OrderItem,
    Product,
)

ALLOWED_TRANSITIONS = {
    "pending": {"paid", "cancelled"},
    "paid": {"shipped", "cancelled"},
    "shipped": {"delivered"},
    "delivered": set(),
    "cancelled": set(),
}


class OrderError(Exception):
    pass


def normalize_lines(lines):
    merged = {}
    for product_id, quantity in lines:
        try:
            pid = int(product_id)
            qty = int(quantity)
        except (TypeError, ValueError):
            raise OrderError("Los datos del producto no son válidos.")
        if qty <= 0 or qty > 10000:
            raise OrderError("La cantidad debe estar entre 1 y 10000.")
        merged[pid] = merged.get(pid, 0) + qty
    if not merged:
        raise OrderError("El pedido no tiene productos.")
    return merged


def place_order(company_id, lines, customer_id=None, channel="store", status="pending", created_by=None, notes=None, commit=True):
    merged = normalize_lines(lines)
    if channel not in ORDER_CHANNELS or status not in ("pending", "paid"):
        raise OrderError("Canal o estado inicial inválido.")

    try:
        rows = db.session.execute(
            select(Inventory, Product)
            .join(Product, Product.id == Inventory.product_id)
            .where(
                Inventory.product_id.in_(list(merged)),
                Product.company_id == company_id,
                Product.active.is_(True),
            )
            .order_by(Inventory.product_id)
            .with_for_update(of=Inventory)
        ).all()
        if len(rows) != len(merged):
            raise OrderError("Uno o más productos no están disponibles.")

        if customer_id is not None:
            found = db.session.scalar(
                select(Customer.id).where(Customer.id == customer_id, Customer.company_id == company_id)
            )
            if found is None:
                raise OrderError("El cliente seleccionado no es válido.")

        total = Decimal("0")
        items = []
        for inventory, product in rows:
            quantity = merged[product.id]
            if inventory.quantity < quantity:
                raise OrderError(
                    "Stock insuficiente para {} (disponible: {}).".format(product.name, inventory.quantity)
                )
            line_total = product.price * quantity
            total += line_total
            items.append(
                OrderItem(
                    product_id=product.id,
                    sku=product.sku,
                    product_name=product.name,
                    quantity=quantity,
                    unit_price=product.price,
                    unit_cost=product.cost,
                    line_total=line_total,
                )
            )

        number = db.session.execute(
            update(Company)
            .where(Company.id == company_id)
            .values(order_seq=Company.order_seq + 1)
            .returning(Company.order_seq)
            .execution_options(synchronize_session=False)
        ).scalar_one()

        order = Order(
            company_id=company_id,
            customer_id=customer_id,
            number=number,
            status=status,
            channel=channel,
            total=total,
            notes=notes,
            created_by=created_by,
            items=items,
        )
        db.session.add(order)
        db.session.flush()

        for inventory, product in rows:
            quantity = merged[product.id]
            inventory.quantity -= quantity
            db.session.add(
                InventoryMovement(
                    company_id=company_id,
                    product_id=product.id,
                    delta=-quantity,
                    reason="sale",
                    reference=order.code,
                    user_id=created_by,
                )
            )

        if commit:
            db.session.commit()
        else:
            db.session.flush()
        return order
    except Exception:
        db.session.rollback()
        raise


def change_status(company_id, order_id, new_status, user_id=None):
    try:
        order = db.session.scalar(
            select(Order).where(Order.id == order_id, Order.company_id == company_id).with_for_update()
        )
        if order is None:
            raise OrderError("Pedido no encontrado.")
        if new_status not in ALLOWED_TRANSITIONS.get(order.status, set()):
            raise OrderError("No se puede pasar el pedido de {} a {}.".format(order.status, new_status))

        if new_status == "cancelled":
            product_ids = sorted({item.product_id for item in order.items if item.product_id is not None})
            if product_ids:
                inventories = {
                    inv.product_id: inv
                    for inv in db.session.scalars(
                        select(Inventory)
                        .where(Inventory.product_id.in_(product_ids), Inventory.company_id == company_id)
                        .order_by(Inventory.product_id)
                        .with_for_update()
                    )
                }
                for item in order.items:
                    inventory = inventories.get(item.product_id)
                    if inventory is None:
                        continue
                    inventory.quantity += item.quantity
                    db.session.add(
                        InventoryMovement(
                            company_id=company_id,
                            product_id=item.product_id,
                            delta=item.quantity,
                            reason="cancellation",
                            reference=order.code,
                            user_id=user_id,
                        )
                    )

        order.status = new_status
        db.session.commit()
        return order
    except Exception:
        db.session.rollback()
        raise


def adjust_stock(company_id, product_id, delta, reason, user_id=None):
    try:
        inventory = db.session.scalar(
            select(Inventory)
            .where(Inventory.product_id == product_id, Inventory.company_id == company_id)
            .with_for_update()
        )
        if inventory is None:
            raise OrderError("Producto no encontrado.")
        if delta == 0:
            raise OrderError("El ajuste no puede ser cero.")
        if inventory.quantity + delta < 0:
            raise OrderError("El ajuste dejaría el inventario en negativo.")
        inventory.quantity += delta
        db.session.add(
            InventoryMovement(
                company_id=company_id,
                product_id=product_id,
                delta=delta,
                reason=reason,
                user_id=user_id,
            )
        )
        db.session.commit()
        return inventory
    except Exception:
        db.session.rollback()
        raise
