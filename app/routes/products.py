from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user
from sqlalchemy import exists, or_, select
from sqlalchemy.exc import IntegrityError

from ..extensions import db
from ..forms import EmptyForm, ProductForm, StockAdjustForm
from ..models import DemandForecast, Inventory, InventoryMovement, OrderItem, Product
from ..services.orders import OrderError, adjust_stock
from ..services.security import owner_required
from ..services.tenancy import paginate, scoped_get_or_404

bp = Blueprint("products", __name__, url_prefix="/productos")


def category_choices(company_id):
    return db.session.scalars(
        select(Product.category).where(Product.company_id == company_id).distinct().order_by(Product.category)
    ).all()


@bp.route("/")
@owner_required
def index():
    company_id = current_user.company_id
    q = request.args.get("q", "").strip()
    category = request.args.get("category", "").strip()
    state = request.args.get("state", "").strip()

    query = (
        select(Product, Inventory)
        .join(Inventory, Inventory.product_id == Product.id)
        .where(Product.company_id == company_id)
        .order_by(Product.name)
    )
    if q:
        like = "%{}%".format(q)
        query = query.where(or_(Product.name.ilike(like), Product.sku.ilike(like)))
    if category:
        query = query.where(Product.category == category)
    if state == "active":
        query = query.where(Product.active.is_(True))
    elif state == "inactive":
        query = query.where(Product.active.is_(False))
    elif state == "low":
        query = query.where(Inventory.reorder_point > 0, Inventory.quantity <= Inventory.reorder_point)

    pagination = paginate(query)
    return render_template(
        "products/list.html",
        pagination=pagination,
        categories=category_choices(company_id),
        q=q,
        category=category,
        state=state,
    )


@bp.route("/nuevo", methods=["GET", "POST"])
@owner_required
def create():
    form = ProductForm()
    if form.validate_on_submit():
        company_id = current_user.company_id
        duplicate = db.session.scalar(
            select(Product.id).where(Product.company_id == company_id, Product.sku == form.sku.data)
        )
        if duplicate is not None:
            form.sku.errors.append("Ya existe un producto con este SKU.")
            return render_template("products/create.html", form=form), 409
        try:
            product = Product(
                company_id=company_id,
                sku=form.sku.data,
                name=form.name.data,
                description=form.description.data or None,
                category=form.category.data,
                price=form.price.data,
                cost=form.cost.data,
                active=form.active.data,
            )
            product.inventory = Inventory(company_id=company_id, quantity=form.quantity.data or 0)
            db.session.add(product)
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            flash("No se pudo guardar el producto.", "danger")
            return render_template("products/create.html", form=form), 409
        flash("Producto creado.", "success")
        return redirect(url_for("products.view", product_id=product.id))
    return render_template("products/create.html", form=form)


@bp.route("/<int:product_id>")
@owner_required
def view(product_id):
    product = scoped_get_or_404(Product, product_id)
    movements = db.session.scalars(
        select(InventoryMovement)
        .where(InventoryMovement.product_id == product.id, InventoryMovement.company_id == current_user.company_id)
        .order_by(InventoryMovement.created_at.desc())
        .limit(15)
    ).all()
    forecast = db.session.scalars(
        select(DemandForecast)
        .where(DemandForecast.product_id == product.id, DemandForecast.company_id == current_user.company_id)
        .order_by(DemandForecast.week_start)
    ).all()
    return render_template(
        "products/view.html",
        product=product,
        movements=movements,
        forecast=forecast,
        forecast_series=[{"label": row.week_start.strftime("%d/%m"), "value": round(row.predicted_units, 1)} for row in forecast],
        adjust_form=StockAdjustForm(),
        action_form=EmptyForm(),
    )


@bp.route("/<int:product_id>/editar", methods=["GET", "POST"])
@owner_required
def edit(product_id):
    product = scoped_get_or_404(Product, product_id)
    form = ProductForm(obj=product)
    if request.method == "GET":
        form.quantity.data = product.inventory.quantity if product.inventory else 0
    if form.validate_on_submit():
        duplicate = db.session.scalar(
            select(Product.id).where(
                Product.company_id == current_user.company_id,
                Product.sku == form.sku.data,
                Product.id != product.id,
            )
        )
        if duplicate is not None:
            form.sku.errors.append("Ya existe un producto con este SKU.")
            return render_template("products/edit.html", form=form, product=product), 409
        product.sku = form.sku.data
        product.name = form.name.data
        product.description = form.description.data or None
        product.category = form.category.data
        product.price = form.price.data
        product.cost = form.cost.data
        product.active = form.active.data
        db.session.commit()
        flash("Producto actualizado.", "success")
        return redirect(url_for("products.view", product_id=product.id))
    return render_template("products/edit.html", form=form, product=product)


@bp.route("/<int:product_id>/stock", methods=["POST"])
@owner_required
def stock(product_id):
    product = scoped_get_or_404(Product, product_id)
    form = StockAdjustForm()
    if form.validate_on_submit():
        try:
            adjust_stock(current_user.company_id, product.id, form.delta.data, form.reason.data, current_user.id)
            flash("Inventario actualizado.", "success")
        except OrderError as error:
            flash(str(error), "danger")
    else:
        flash("Ingresa una cantidad válida.", "danger")
    return redirect(url_for("products.view", product_id=product.id))


@bp.route("/<int:product_id>/eliminar", methods=["POST"])
@owner_required
def delete(product_id):
    product = scoped_get_or_404(Product, product_id)
    form = EmptyForm()
    if not form.validate_on_submit():
        return redirect(url_for("products.view", product_id=product.id))
    has_orders = db.session.scalar(select(exists().where(OrderItem.product_id == product.id)))
    if has_orders:
        product.active = False
        db.session.commit()
        flash("El producto tiene ventas registradas, por eso se desactivó en lugar de eliminarse.", "info")
        return redirect(url_for("products.view", product_id=product.id))
    db.session.delete(product)
    db.session.commit()
    flash("Producto eliminado.", "success")
    return redirect(url_for("products.index"))
