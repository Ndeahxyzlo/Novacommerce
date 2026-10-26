import csv
import io
from datetime import datetime, time, timezone

from flask import Blueprint, Response, flash, redirect, render_template, request, url_for
from flask_login import current_user
from sqlalchemy import or_, select

from ..extensions import db
from ..forms import EmptyForm
from ..models import CHANNEL_LABELS, ORDER_STATUSES, STATUS_LABELS, Customer, Order, Product
from ..services.orders import ALLOWED_TRANSITIONS, OrderError, change_status, place_order
from ..services.security import owner_required
from ..services.tenancy import paginate, scoped_get_or_404

bp = Blueprint("orders", __name__, url_prefix="/pedidos")


def parse_date(value, end=False):
    if not value:
        return None
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None
    moment = time.max if end else time.min
    return datetime.combine(parsed, moment, tzinfo=timezone.utc)


def filtered_query(company_id):
    status = request.args.get("status", "").strip()
    q = request.args.get("q", "").strip()
    start = parse_date(request.args.get("from"))
    end = parse_date(request.args.get("to"), end=True)

    query = (
        select(Order, Customer)
        .outerjoin(Customer, Customer.id == Order.customer_id)
        .where(Order.company_id == company_id)
        .order_by(Order.created_at.desc(), Order.id.desc())
    )
    if status in ORDER_STATUSES:
        query = query.where(Order.status == status)
    if q:
        conditions = [
            Customer.first_name.ilike("%{}%".format(q)),
            Customer.last_name.ilike("%{}%".format(q)),
            Customer.email.ilike("%{}%".format(q)),
        ]
        if q.isdigit():
            conditions.append(Order.number == int(q))
        query = query.where(or_(*conditions))
    if start:
        query = query.where(Order.created_at >= start)
    if end:
        query = query.where(Order.created_at <= end)
    return query


@bp.route("/")
@owner_required
def index():
    pagination = paginate(filtered_query(current_user.company_id))
    return render_template(
        "orders/list.html",
        pagination=pagination,
        statuses=ORDER_STATUSES,
        status_labels=STATUS_LABELS,
        filters={
            "status": request.args.get("status", ""),
            "q": request.args.get("q", ""),
            "from": request.args.get("from", ""),
            "to": request.args.get("to", ""),
        },
    )


@bp.route("/exportar.csv")
@owner_required
def export():
    rows = db.session.execute(filtered_query(current_user.company_id).limit(50000)).all()
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["numero", "fecha", "cliente", "canal", "estado", "total"])
    for order, customer in rows:
        writer.writerow(
            [
                order.code,
                order.created_at.strftime("%Y-%m-%d %H:%M"),
                customer.full_name if customer else "Venta directa",
                CHANNEL_LABELS.get(order.channel, order.channel),
                STATUS_LABELS.get(order.status, order.status),
                order.total,
            ]
        )
    return Response(
        buffer.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=pedidos.csv"},
    )


@bp.route("/nuevo", methods=["GET", "POST"])
@owner_required
def create():
    company_id = current_user.company_id
    form = EmptyForm()
    products = db.session.execute(
        select(Product).where(Product.company_id == company_id, Product.active.is_(True)).order_by(Product.name).limit(1000)
    ).scalars().all()

    if form.validate_on_submit():
        product_ids = request.form.getlist("product_id")
        quantities = request.form.getlist("quantity")
        lines = [(pid, qty) for pid, qty in zip(product_ids, quantities) if pid and qty]
        email = request.form.get("customer_email", "").strip().lower()
        notes = request.form.get("notes", "").strip()[:500] or None
        paid = request.form.get("paid") == "1"
        customer_id = None
        if email:
            customer_id = db.session.scalar(
                select(Customer.id).where(Customer.company_id == company_id, Customer.email == email)
            )
            if customer_id is None:
                flash("No existe un cliente con ese correo. Regístralo primero o deja el campo vacío.", "danger")
                return render_template("orders/create.html", form=form, products=products), 400
        try:
            order = place_order(
                company_id,
                lines,
                customer_id=customer_id,
                channel="pos",
                status="paid" if paid else "pending",
                created_by=current_user.id,
                notes=notes,
            )
        except OrderError as error:
            flash(str(error), "danger")
            return render_template("orders/create.html", form=form, products=products), 400
        flash("Venta registrada.", "success")
        return redirect(url_for("orders.view", order_id=order.id))
    return render_template("orders/create.html", form=form, products=products)


@bp.route("/<int:order_id>")
@owner_required
def view(order_id):
    order = scoped_get_or_404(Order, order_id)
    return render_template(
        "orders/view.html",
        order=order,
        next_states=sorted(ALLOWED_TRANSITIONS.get(order.status, set())),
        status_labels=STATUS_LABELS,
        action_form=EmptyForm(),
    )


@bp.route("/<int:order_id>/estado", methods=["POST"])
@owner_required
def update_status(order_id):
    order = scoped_get_or_404(Order, order_id)
    form = EmptyForm()
    if form.validate_on_submit():
        try:
            change_status(current_user.company_id, order.id, request.form.get("status", ""), current_user.id)
            flash("Estado del pedido actualizado.", "success")
        except OrderError as error:
            flash(str(error), "danger")
    return redirect(url_for("orders.view", order_id=order.id))
