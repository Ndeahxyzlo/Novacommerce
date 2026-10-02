import csv
import io
from datetime import datetime, time, timedelta, timezone

from flask import Blueprint, Response, flash, redirect, render_template, request, url_for
from flask_login import current_user
from sqlalchemy import func, select

from ..extensions import db
from ..forms import EmptyForm
from ..ml import demand
from ..models import DemandForecast, Inventory, Order, OrderItem, Product
from ..services import analytics, etl, purchasing
from ..services.security import owner_required
from ..utils import parse_amount, utcnow

bp = Blueprint("reports", __name__, url_prefix="/reportes")


def date_range():
    today = utcnow().date()
    try:
        start = datetime.strptime(request.args.get("from", ""), "%Y-%m-%d").date()
    except ValueError:
        start = today - timedelta(days=30)
    try:
        end = datetime.strptime(request.args.get("to", ""), "%Y-%m-%d").date()
    except ValueError:
        end = today
    if start > end:
        start, end = end, start
    return start, end


@bp.route("/")
@owner_required
def dashboard():
    company_id = current_user.company_id
    ready = analytics.warehouse_ready()
    context = {"ready": ready, "action_form": EmptyForm()}
    if ready:
        monthly = analytics.monthly_sales(company_id)
        weekdays = analytics.sales_by_weekday(company_id)
        context.update(
            kpis=analytics.kpis(company_id),
            monthly=monthly,
            monthly_series=[
                {"label": "{} {}".format(row["nombre_mes"][:3], str(row["anio"])[2:]), "value": float(row["ingresos"])}
                for row in monthly
            ],
            weekday_series=[{"label": row["nombre_dia"][:3], "value": float(row["ingresos"])} for row in weekdays],
            top=analytics.top_products(company_id),
            channels=analytics.sales_by_channel(company_id),
        )
    return render_template("reports/dashboard.html", **context)


@bp.route("/actualizar", methods=["POST"])
@owner_required
def refresh():
    form = EmptyForm()
    if form.validate_on_submit():
        result = etl.run_etl()
        flash("Almacén de datos actualizado ({} filas procesadas).".format(result["rows"]), "success")
    return redirect(url_for("reports.dashboard"))


@bp.route("/olap")
@owner_required
def olap():
    company_id = current_user.company_id
    if not analytics.warehouse_ready():
        return render_template("reports/olap.html", ready=False)
    return render_template(
        "reports/olap.html",
        ready=True,
        rollup=analytics.rollup_category(company_id),
        abc=analytics.abc_analysis(company_id),
        rfm=analytics.rfm_segments(company_id),
    )


@bp.route("/inventario")
@owner_required
def inventory():
    company_id = current_user.company_id
    forecast_sum = (
        select(DemandForecast.product_id, func.sum(DemandForecast.predicted_units).label("units"))
        .where(DemandForecast.company_id == company_id)
        .group_by(DemandForecast.product_id)
        .subquery()
    )
    rows = db.session.execute(
        select(Product, Inventory, forecast_sum.c.units)
        .join(Inventory, Inventory.product_id == Product.id)
        .outerjoin(forecast_sum, forecast_sum.c.product_id == Product.id)
        .where(Product.company_id == company_id, Product.active.is_(True))
        .order_by(Product.name)
    ).all()
    total_value = sum((inv.quantity * product.cost for product, inv, _ in rows), 0)
    low = sum(1 for _, inv, _ in rows if inv.needs_restock)
    if request.args.get("format") == "csv":
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(["sku", "producto", "stock", "punto_reorden", "stock_seguridad", "eoq", "demanda_proyectada"])
        for product, inv, units in rows:
            writer.writerow([product.sku, product.name, inv.quantity, inv.reorder_point, inv.safety_stock, inv.eoq, round(units or 0, 1)])
        return Response(
            buffer.getvalue(),
            mimetype="text/csv",
            headers={"Content-Disposition": "attachment; filename=inventario.csv"},
        )
    return render_template("reports/inventory.html", rows=rows, total_value=total_value, low=low)


@bp.route("/ventas")
@owner_required
def sales():
    company_id = current_user.company_id
    start, end = date_range()
    start_dt = datetime.combine(start, time.min, tzinfo=timezone.utc)
    end_dt = datetime.combine(end, time.max, tzinfo=timezone.utc)
    rows = db.session.execute(
        select(
            OrderItem.sku,
            OrderItem.product_name,
            func.sum(OrderItem.quantity).label("units"),
            func.sum(OrderItem.line_total).label("revenue"),
            func.sum(OrderItem.line_total - OrderItem.unit_cost * OrderItem.quantity).label("margin"),
        )
        .join(Order, Order.id == OrderItem.order_id)
        .where(
            Order.company_id == company_id,
            Order.status != "cancelled",
            Order.created_at >= start_dt,
            Order.created_at <= end_dt,
        )
        .group_by(OrderItem.sku, OrderItem.product_name)
        .order_by(func.sum(OrderItem.line_total).desc())
    ).all()
    if request.args.get("format") == "csv":
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(["sku", "producto", "unidades", "ingresos", "margen"])
        for row in rows:
            writer.writerow([row.sku, row.product_name, row.units, row.revenue, row.margin])
        return Response(
            buffer.getvalue(),
            mimetype="text/csv",
            headers={"Content-Disposition": "attachment; filename=ventas.csv"},
        )
    total_revenue = sum((row.revenue for row in rows), 0)
    total_margin = sum((row.margin for row in rows), 0)
    return render_template(
        "reports/sales.html",
        rows=rows,
        start=start,
        end=end,
        total_revenue=total_revenue,
        total_margin=total_margin,
    )


@bp.route("/compras")
@owner_required
def purchases():
    budget = parse_amount(request.args.get("presupuesto"))
    capacity = parse_amount(request.args.get("capacidad"))
    plan = purchasing.purchase_plan(current_user.company_id, budget, capacity)
    return render_template("reports/purchases.html", plan=plan, custom=budget is not None or capacity is not None)


@bp.route("/ml")
@owner_required
def ml():
    company_id = current_user.company_id
    run = demand.latest_run(company_id)
    top = db.session.execute(
        select(Product.name, Product.sku, func.sum(DemandForecast.predicted_units).label("units"), Inventory.quantity, Inventory.reorder_point, Inventory.eoq)
        .join(Product, Product.id == DemandForecast.product_id)
        .join(Inventory, Inventory.product_id == Product.id)
        .where(DemandForecast.company_id == company_id)
        .group_by(Product.name, Product.sku, Inventory.quantity, Inventory.reorder_point, Inventory.eoq)
        .order_by(func.sum(DemandForecast.predicted_units).desc())
        .limit(20)
    ).all()
    return render_template("reports/ml.html", run=run, top=top, action_form=EmptyForm())


@bp.route("/ml/ejecutar", methods=["POST"])
@owner_required
def ml_run():
    form = EmptyForm()
    if form.validate_on_submit():
        metrics = demand.run_company_pipeline(current_user.company_id)
        if metrics.get("trained"):
            flash("Modelo entrenado. MAE {} frente a {} de la línea base.".format(metrics["mae"], metrics["baseline_mae"]), "success")
        else:
            flash("Pronóstico generado con la línea base: {}.".format(metrics.get("reason", "sin detalle")), "info")
    return redirect(url_for("reports.ml"))
