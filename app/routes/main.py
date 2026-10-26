import time
from datetime import timedelta

from flask import Blueprint, current_app, redirect, render_template
from flask_login import current_user
from sqlalchemy import func, select, text

from ..extensions import db
from ..models import Company, Customer, Inventory, Order, OrderItem, Product
from ..services.security import owner_required
from ..utils import utcnow
from .auth import home_for

bp = Blueprint("main", __name__)


LANDING_TTL_SECONDS = 120
_landing_cache = {"expires": 0.0, "data": None}


def active_stores(limit=None):
    query = (
        select(Company, func.count(Product.id).label("total"))
        .join(Product, (Product.company_id == Company.id) & Product.active.is_(True))
        .where(Company.active.is_(True))
        .group_by(Company.id)
        .order_by(Company.name)
    )
    if limit:
        query = query.limit(limit)
    return db.session.execute(query).all()


def landing_data():
    use_cache = not current_app.testing
    now = time.monotonic()
    if use_cache and _landing_cache["data"] is not None and _landing_cache["expires"] > now:
        return _landing_cache["data"]

    visible = (Product.active.is_(True), Company.active.is_(True))
    featured = db.session.execute(
        select(Product, Inventory, Company)
        .join(Inventory, Inventory.product_id == Product.id)
        .join(Company, Company.id == Product.company_id)
        .where(*visible, Inventory.quantity > 0)
        .order_by(Product.created_at.desc(), Product.id.desc())
        .limit(8)
    ).all()
    counts = db.session.execute(
        select(
            func.count(func.distinct(Company.id)).label("stores"),
            func.count(Product.id).label("products"),
            func.count(func.distinct(Product.category)).label("categories"),
        )
        .select_from(Product)
        .join(Company, Company.id == Product.company_id)
        .where(*visible)
    ).one()
    data = {
        "featured": [
            (
                {"id": p.id, "name": p.name, "category": p.category, "price": p.price},
                {"quantity": inv.quantity},
                {"name": c.name},
            )
            for p, inv, c in featured
        ],
        "stores": [
            (
                {"id": c.id, "slug": c.slug, "name": c.name, "description": c.description, "city": c.city, "country": c.country},
                total,
            )
            for c, total in active_stores(limit=6)
        ],
        "stats": {"stores": counts.stores, "products": counts.products, "categories": counts.categories},
    }
    if use_cache:
        _landing_cache.update(data=data, expires=now + LANDING_TTL_SECONDS)
    return data


@bp.route("/")
def index():
    if current_user.is_authenticated:
        return redirect(home_for(current_user))
    return render_template("index.html", **landing_data())


@bp.route("/healthz")
def healthz():
    db.session.execute(text("select 1"))
    return {"status": "ok"}


@bp.route("/dashboard")
@owner_required
def dashboard():
    company_id = current_user.company_id
    now = utcnow()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    since = now - timedelta(days=30)
    valid = Order.status != "cancelled"

    in_month = valid & (Order.created_at >= month_start)
    month_revenue, month_orders, pending_orders = db.session.execute(
        select(
            func.coalesce(func.sum(Order.total).filter(in_month), 0),
            func.count(Order.id).filter(in_month),
            func.count(Order.id).filter(Order.status == "pending"),
        ).where(Order.company_id == company_id)
    ).one()
    customers = db.session.scalar(select(func.count(Customer.id)).where(Customer.company_id == company_id))
    low_stock = db.session.scalar(
        select(func.count(Inventory.id)).where(
            Inventory.company_id == company_id,
            Inventory.reorder_point > 0,
            Inventory.quantity <= Inventory.reorder_point,
        )
    )
    products = db.session.scalar(
        select(func.count(Product.id)).where(Product.company_id == company_id, Product.active.is_(True))
    )

    day = func.date(Order.created_at)
    daily = db.session.execute(
        select(day.label("d"), func.sum(Order.total).label("total"))
        .where(Order.company_id == company_id, valid, Order.created_at >= since)
        .group_by(day)
        .order_by(day)
    ).all()
    series = [{"label": row.d.strftime("%d/%m"), "value": float(row.total)} for row in daily]

    top = db.session.execute(
        select(OrderItem.product_name, func.sum(OrderItem.quantity).label("units"), func.sum(OrderItem.line_total).label("revenue"))
        .join(Order, Order.id == OrderItem.order_id)
        .where(Order.company_id == company_id, valid, Order.created_at >= since)
        .group_by(OrderItem.product_name)
        .order_by(func.sum(OrderItem.line_total).desc())
        .limit(5)
    ).all()

    recent = db.session.scalars(
        select(Order).where(Order.company_id == company_id).order_by(Order.created_at.desc()).limit(8)
    ).all()

    return render_template(
        "dashboard.html",
        month_revenue=month_revenue,
        month_orders=month_orders,
        pending_orders=pending_orders,
        customers=customers,
        low_stock=low_stock,
        products=products,
        series=series,
        top=top,
        recent=recent,
    )
