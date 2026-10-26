from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from ..extensions import db
from ..models import CartItem, Company, Customer, Inventory, Product, Wishlist
from .orders import OrderError, place_order


def visible_product(product_id):
    return db.session.execute(
        select(Product, Inventory)
        .join(Inventory, Inventory.product_id == Product.id)
        .join(Company, Company.id == Product.company_id)
        .where(Product.id == product_id, Product.active.is_(True), Company.active.is_(True))
    ).first()


def add_to_cart(user_id, product_id, quantity):
    found = visible_product(product_id)
    if found is None:
        raise OrderError("El producto no está disponible.")
    product, inventory = found
    if quantity < 1 or quantity > 10000:
        raise OrderError("La cantidad no es válida.")
    item = db.session.scalar(select(CartItem).where(CartItem.user_id == user_id, CartItem.product_id == product.id))
    new_quantity = quantity + (item.quantity if item else 0)
    if new_quantity > inventory.quantity:
        raise OrderError("Solo hay {} unidades disponibles.".format(inventory.quantity))
    if item:
        item.quantity = new_quantity
    else:
        db.session.add(CartItem(user_id=user_id, product_id=product.id, quantity=new_quantity))
    db.session.commit()


def set_cart_quantity(user_id, product_id, quantity):
    item = db.session.scalar(select(CartItem).where(CartItem.user_id == user_id, CartItem.product_id == product_id))
    if item is None:
        raise OrderError("El producto no está en el carrito.")
    if quantity <= 0:
        db.session.delete(item)
        db.session.commit()
        return
    inventory = db.session.scalar(select(Inventory).where(Inventory.product_id == product_id))
    if inventory is None or quantity > inventory.quantity:
        raise OrderError("La cantidad supera el stock disponible.")
    item.quantity = min(quantity, 10000)
    db.session.commit()


def remove_from_cart(user_id, product_id):
    db.session.execute(delete(CartItem).where(CartItem.user_id == user_id, CartItem.product_id == product_id))
    db.session.commit()


def cart_groups(user_id):
    rows = db.session.execute(
        select(CartItem, Product, Inventory, Company)
        .join(Product, Product.id == CartItem.product_id)
        .join(Inventory, Inventory.product_id == Product.id)
        .join(Company, Company.id == Product.company_id)
        .where(CartItem.user_id == user_id)
        .order_by(Company.name, Product.name)
    ).all()
    groups = {}
    for item, product, inventory, company in rows:
        group = groups.setdefault(company.id, {"company": company, "lines": [], "total": Decimal("0")})
        line_total = product.price * item.quantity
        group["lines"].append(
            {
                "item": item,
                "product": product,
                "inventory": inventory,
                "line_total": line_total,
                "available": product.active and inventory.quantity >= item.quantity,
            }
        )
        group["total"] += line_total
    return list(groups.values())


def get_or_create_customer(user, company_id):
    existing = db.session.scalar(select(Customer).where(Customer.company_id == company_id, Customer.user_id == user.id))
    if existing:
        return existing
    by_email = db.session.scalar(
        select(Customer).where(Customer.company_id == company_id, Customer.email == user.email)
    )
    if by_email and by_email.user_id is None:
        by_email.user_id = user.id
        db.session.flush()
        return by_email
    try:
        with db.session.begin_nested():
            customer = Customer(
                company_id=company_id,
                user_id=user.id,
                first_name=user.first_name,
                last_name=user.last_name,
                email=user.email,
                phone=user.phone,
            )
            db.session.add(customer)
    except IntegrityError:
        customer = db.session.scalar(
            select(Customer).where(Customer.company_id == company_id, Customer.user_id == user.id)
        )
    return customer


def checkout(user, company_id, notes=None):
    rows = db.session.execute(
        select(CartItem)
        .join(Product, Product.id == CartItem.product_id)
        .where(CartItem.user_id == user.id, Product.company_id == company_id)
    ).scalars().all()
    if not rows:
        raise OrderError("El carrito de esta tienda está vacío.")
    try:
        customer = get_or_create_customer(user, company_id)
        order = place_order(
            company_id,
            [(item.product_id, item.quantity) for item in rows],
            customer_id=customer.id,
            channel="store",
            status="pending",
            created_by=user.id,
            notes=notes,
            commit=False,
        )
        db.session.execute(delete(CartItem).where(CartItem.id.in_([item.id for item in rows])))
        db.session.commit()
        return order
    except Exception:
        db.session.rollback()
        raise


def toggle_wishlist(user_id, product_id):
    if visible_product(product_id) is None:
        raise OrderError("El producto no está disponible.")
    existing = db.session.scalar(select(Wishlist).where(Wishlist.user_id == user_id, Wishlist.product_id == product_id))
    if existing:
        db.session.delete(existing)
        added = False
    else:
        db.session.add(Wishlist(user_id=user_id, product_id=product_id))
        added = True
    db.session.commit()
    return added
