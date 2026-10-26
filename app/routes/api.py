from datetime import timedelta

from flask import Blueprint, jsonify, request
from flask_login import current_user
from sqlalchemy import func, or_, select

from ..extensions import db
from ..models import DemandForecast, Order, Product
from ..services.security import owner_required
from ..utils import utcnow

bp = Blueprint("api", __name__, url_prefix="/api/v1")


@bp.route("/sales/daily")
@owner_required
def sales_daily():
    days = min(max(request.args.get("days", 30, type=int), 1), 365)
    since = utcnow() - timedelta(days=days)
    day = func.date(Order.created_at)
    rows = db.session.execute(
        select(day.label("d"), func.sum(Order.total).label("total"), func.count(Order.id).label("orders"))
        .where(Order.company_id == current_user.company_id, Order.status != "cancelled", Order.created_at >= since)
        .group_by(day)
        .order_by(day)
    ).all()
    return jsonify([{"date": row.d.isoformat(), "total": float(row.total), "orders": row.orders} for row in rows])


@bp.route("/products/search")
@owner_required
def products_search():
    q = request.args.get("q", "").strip()
    query = select(Product).where(Product.company_id == current_user.company_id, Product.active.is_(True))
    if q:
        query = query.where(or_(Product.name.ilike("%{}%".format(q)), Product.sku.ilike("%{}%".format(q))))
    rows = db.session.scalars(query.order_by(Product.name).limit(20)).all()
    return jsonify([{"id": p.id, "sku": p.sku, "name": p.name, "price": float(p.price)} for p in rows])


@bp.route("/products/<int:product_id>/forecast")
@owner_required
def product_forecast(product_id):
    rows = db.session.scalars(
        select(DemandForecast)
        .where(DemandForecast.product_id == product_id, DemandForecast.company_id == current_user.company_id)
        .order_by(DemandForecast.week_start)
    ).all()
    return jsonify([{"week_start": row.week_start.isoformat(), "units": row.predicted_units, "model": row.model_kind} for row in rows])
