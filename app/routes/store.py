from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user
from sqlalchemy import func, or_, select

from ..extensions import db
from ..forms import CheckoutForm, EmptyForm, QuantityForm
from ..models import Company, Customer, Inventory, Order, Product, Wishlist
from ..services import cart as cart_service
from ..services.orders import OrderError, change_status
from ..services.security import customer_required
from ..services.tenancy import paginate
from ..models import STATUS_LABELS

bp = Blueprint("store", __name__, url_prefix="/tienda")


@bp.route("/")
def index():
    rows = db.session.execute(
        select(Company, func.count(Product.id).label("total"))
        .join(Product, (Product.company_id == Company.id) & Product.active.is_(True))
        .where(Company.active.is_(True))
        .group_by(Company.id)
        .order_by(Company.name)
    ).all()
    return render_template("store/index.html", stores=rows)


@bp.route("/<slug>")
def store_detail(slug):
    company = db.session.scalar(select(Company).where(Company.slug == slug, Company.active.is_(True)))
    if company is None:
        abort(404)
    q = request.args.get("q", "").strip()
    category = request.args.get("category", "").strip()
    query = (
        select(Product, Inventory)
        .join(Inventory, Inventory.product_id == Product.id)
        .where(Product.company_id == company.id, Product.active.is_(True))
        .order_by(Product.name)
    )
    if q:
        query = query.where(or_(Product.name.ilike("%{}%".format(q)), Product.sku.ilike("%{}%".format(q))))
    if category:
        query = query.where(Product.category == category)
    categories = db.session.scalars(
        select(Product.category).where(Product.company_id == company.id, Product.active.is_(True)).distinct().order_by(Product.category)
    ).all()
    wished = set()
    if current_user.is_authenticated and current_user.is_customer:
        wished = set(db.session.scalars(select(Wishlist.product_id).where(Wishlist.user_id == current_user.id)))
    return render_template(
        "store/store_detail.html",
        company=company,
        pagination=paginate(query),
        categories=categories,
        q=q,
        category=category,
        wished=wished,
        quantity_form=QuantityForm(),
        action_form=EmptyForm(),
    )


@bp.route("/producto/<int:product_id>")
def product(product_id):
    found = cart_service.visible_product(product_id)
    if found is None:
        abort(404)
    product_row, inventory = found
    wished = False
    if current_user.is_authenticated and current_user.is_customer:
        wished = db.session.scalar(
            select(Wishlist.id).where(Wishlist.user_id == current_user.id, Wishlist.product_id == product_id)
        ) is not None
    return render_template(
        "store/product.html",
        product=product_row,
        inventory=inventory,
        company=product_row.company,
        wished=wished,
        quantity_form=QuantityForm(),
        action_form=EmptyForm(),
    )


@bp.route("/carrito")
@customer_required
def cart():
    return render_template(
        "store/cart.html",
        groups=cart_service.cart_groups(current_user.id),
        quantity_form=QuantityForm(),
        checkout_form=CheckoutForm(),
        action_form=EmptyForm(),
    )


@bp.route("/carrito/agregar/<int:product_id>", methods=["POST"])
@customer_required
def cart_add(product_id):
    form = QuantityForm()
    if form.validate_on_submit():
        try:
            cart_service.add_to_cart(current_user.id, product_id, form.quantity.data)
            flash("Producto agregado al carrito.", "success")
        except OrderError as error:
            flash(str(error), "danger")
    else:
        flash("Cantidad no válida.", "danger")
    return redirect(request.referrer or url_for("store.cart"))


@bp.route("/carrito/actualizar/<int:product_id>", methods=["POST"])
@customer_required
def cart_update(product_id):
    form = QuantityForm()
    if form.validate_on_submit():
        try:
            cart_service.set_cart_quantity(current_user.id, product_id, form.quantity.data)
        except OrderError as error:
            flash(str(error), "danger")
    else:
        flash("Cantidad no válida.", "danger")
    return redirect(url_for("store.cart"))


@bp.route("/carrito/quitar/<int:product_id>", methods=["POST"])
@customer_required
def cart_remove(product_id):
    form = EmptyForm()
    if form.validate_on_submit():
        cart_service.remove_from_cart(current_user.id, product_id)
    return redirect(url_for("store.cart"))


@bp.route("/carrito/pagar/<int:company_id>", methods=["POST"])
@customer_required
def checkout(company_id):
    form = CheckoutForm()
    if not form.validate_on_submit():
        flash("No se pudo procesar el pedido.", "danger")
        return redirect(url_for("store.cart"))
    try:
        order = cart_service.checkout(current_user, company_id, form.notes.data or None)
    except OrderError as error:
        flash(str(error), "danger")
        return redirect(url_for("store.cart"))
    flash("Pedido {} creado.".format(order.code), "success")
    return redirect(url_for("store.order_detail", order_id=order.id))


def own_orders_query():
    return (
        select(Order)
        .join(Customer, Customer.id == Order.customer_id)
        .where(Customer.user_id == current_user.id)
    )


@bp.route("/pedidos")
@customer_required
def orders():
    query = own_orders_query().order_by(Order.created_at.desc())
    return render_template("store/orders.html", pagination=paginate(query), status_labels=STATUS_LABELS)


@bp.route("/pedidos/<int:order_id>")
@customer_required
def order_detail(order_id):
    order = db.session.scalar(own_orders_query().where(Order.id == order_id))
    if order is None:
        abort(404)
    return render_template(
        "store/order_detail.html",
        order=order,
        company=db.session.get(Company, order.company_id),
        action_form=EmptyForm(),
    )


@bp.route("/pedidos/<int:order_id>/cancelar", methods=["POST"])
@customer_required
def order_cancel(order_id):
    order = db.session.scalar(own_orders_query().where(Order.id == order_id))
    if order is None:
        abort(404)
    form = EmptyForm()
    if form.validate_on_submit():
        if order.status != "pending":
            flash("Solo se pueden cancelar pedidos pendientes.", "danger")
        else:
            try:
                change_status(order.company_id, order.id, "cancelled", current_user.id)
                flash("Pedido cancelado.", "success")
            except OrderError as error:
                flash(str(error), "danger")
    return redirect(url_for("store.order_detail", order_id=order.id))


@bp.route("/favoritos")
@customer_required
def wishlist():
    rows = db.session.execute(
        select(Product, Inventory)
        .join(Wishlist, Wishlist.product_id == Product.id)
        .join(Inventory, Inventory.product_id == Product.id)
        .where(Wishlist.user_id == current_user.id, Product.active.is_(True))
        .order_by(Wishlist.created_at.desc())
    ).all()
    return render_template(
        "store/wishlist.html", rows=rows, quantity_form=QuantityForm(), action_form=EmptyForm()
    )


@bp.route("/favoritos/<int:product_id>", methods=["POST"])
@customer_required
def wishlist_toggle(product_id):
    form = EmptyForm()
    if form.validate_on_submit():
        try:
            added = cart_service.toggle_wishlist(current_user.id, product_id)
            flash("Agregado a favoritos." if added else "Quitado de favoritos.", "info")
        except OrderError as error:
            flash(str(error), "danger")
    return redirect(request.referrer or url_for("store.wishlist"))
