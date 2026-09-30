from datetime import timedelta

from flask import Blueprint, redirect, render_template
from flask_login import current_user
from sqlalchemy import func, select, text

from ..extensions import db
from ..models import Customer, Inventory, Order, OrderItem, Product
from ..services.security import owner_required
from ..utils import utcnow
from .auth import home_for

bp = Blueprint("main", __name__)


@bp.route("/")
def index():
    if current_user.is_authenticated:
        return redirect(home_for(current_user))
    return render_template("index.html")


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

    month_revenue = db.session.scalar(
        select(func.coalesce(func.sum(Order.total), 0)).where(
            Order.company_id == company_id, valid, Order.created_at >= month_start
        )
    )
    month_orders = db.session.scalar(
        select(func.count(Order.id)).where(Order.company_id == company_id, valid, Order.created_at >= month_start)
    )
    pending_orders = db.session.scalar(
        select(func.count(Order.id)).where(Order.company_id == company_id, Order.status == "pending")
    )
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
