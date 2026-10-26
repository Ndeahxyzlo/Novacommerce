from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user
from sqlalchemy import exists, func, or_, select
from sqlalchemy.exc import IntegrityError

from ..extensions import db
from ..forms import CustomerForm, EmptyForm
from ..models import Customer, Order
from ..services.security import owner_required
from ..services.tenancy import paginate, scoped_get_or_404

bp = Blueprint("customers", __name__, url_prefix="/clientes")


def email_taken(company_id, email, ignore_id=None):
    if not email:
        return False
    query = select(Customer.id).where(Customer.company_id == company_id, Customer.email == email)
    if ignore_id is not None:
        query = query.where(Customer.id != ignore_id)
    return db.session.scalar(query) is not None


@bp.route("/")
@owner_required
def index():
    q = request.args.get("q", "").strip()
    query = select(Customer).where(Customer.company_id == current_user.company_id).order_by(Customer.last_name, Customer.first_name)
    if q:
        like = "%{}%".format(q)
        query = query.where(
            or_(
                Customer.first_name.ilike(like),
                Customer.last_name.ilike(like),
                Customer.email.ilike(like),
                Customer.city.ilike(like),
            )
        )
    return render_template("customers/list.html", pagination=paginate(query), q=q)


@bp.route("/nuevo", methods=["GET", "POST"])
@owner_required
def create():
    form = CustomerForm()
    if form.validate_on_submit():
        if email_taken(current_user.company_id, form.email.data):
            form.email.errors.append("Ya existe un cliente con este correo.")
            return render_template("customers/create.html", form=form), 409
        customer = Customer(
            company_id=current_user.company_id,
            first_name=form.first_name.data,
            last_name=form.last_name.data,
            email=form.email.data or None,
            phone=form.phone.data or None,
            city=form.city.data or None,
            country=form.country.data or None,
        )
        try:
            db.session.add(customer)
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            flash("No se pudo guardar el cliente.", "danger")
            return render_template("customers/create.html", form=form), 409
        flash("Cliente creado.", "success")
        return redirect(url_for("customers.view", customer_id=customer.id))
    return render_template("customers/create.html", form=form)


@bp.route("/<int:customer_id>")
@owner_required
def view(customer_id):
    customer = scoped_get_or_404(Customer, customer_id)
    orders = db.session.scalars(
        select(Order)
        .where(Order.customer_id == customer.id, Order.company_id == current_user.company_id)
        .order_by(Order.created_at.desc())
        .limit(25)
    ).all()
    totals = db.session.execute(
        select(func.count(Order.id), func.coalesce(func.sum(Order.total), 0)).where(
            Order.customer_id == customer.id, Order.company_id == current_user.company_id, Order.status != "cancelled"
        )
    ).one()
    return render_template(
        "customers/view.html",
        customer=customer,
        orders=orders,
        order_count=totals[0],
        spent=totals[1],
        action_form=EmptyForm(),
    )


@bp.route("/<int:customer_id>/editar", methods=["GET", "POST"])
@owner_required
def edit(customer_id):
    customer = scoped_get_or_404(Customer, customer_id)
    form = CustomerForm(obj=customer)
    if form.validate_on_submit():
        if email_taken(current_user.company_id, form.email.data, customer.id):
            form.email.errors.append("Ya existe un cliente con este correo.")
            return render_template("customers/edit.html", form=form, customer=customer), 409
        customer.first_name = form.first_name.data
        customer.last_name = form.last_name.data
        customer.email = form.email.data or None
        customer.phone = form.phone.data or None
        customer.city = form.city.data or None
        customer.country = form.country.data or None
        db.session.commit()
        flash("Cliente actualizado.", "success")
        return redirect(url_for("customers.view", customer_id=customer.id))
    return render_template("customers/edit.html", form=form, customer=customer)


@bp.route("/<int:customer_id>/eliminar", methods=["POST"])
@owner_required
def delete(customer_id):
    customer = scoped_get_or_404(Customer, customer_id)
    form = EmptyForm()
    if not form.validate_on_submit():
        return redirect(url_for("customers.view", customer_id=customer.id))
    has_orders = db.session.scalar(select(exists().where(Order.customer_id == customer.id)))
    if has_orders:
        flash("El cliente tiene pedidos registrados y no se puede eliminar.", "danger")
        return redirect(url_for("customers.view", customer_id=customer.id))
    db.session.delete(customer)
    db.session.commit()
    flash("Cliente eliminado.", "success")
    return redirect(url_for("customers.index"))
