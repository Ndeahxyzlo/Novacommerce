from sqlalchemy import func, select

from app.extensions import db
from app.models import CartItem, Customer, Inventory, Order, Product

from .conftest import (
    create_customer,
    create_customer_user,
    create_owner,
    create_product,
    csrf_token,
    login,
)


def form_post(client, path, data, token_from):
    payload = dict(data)
    payload["csrf_token"] = csrf_token(client, token_from)
    return client.post(path, data=payload)


def test_tenant_isolation_products(client, ctx):
    company_a, _ = create_owner("Empresa Uno", "uno@example.com")
    company_b, _ = create_owner("Empresa Dos", "dos@example.com")
    product_b = create_product(company_b, sku="B-1", name="Producto de B")
    login(client, "uno@example.com")

    listing = client.get("/productos/").get_data(as_text=True)
    assert "Producto de B" not in listing
    assert client.get("/productos/{}".format(product_b.id)).status_code == 404
    assert client.get("/productos/{}/editar".format(product_b.id)).status_code == 404
    response = form_post(client, "/productos/{}/eliminar".format(product_b.id), {}, "/productos/")
    assert response.status_code == 404
    response = form_post(client, "/productos/{}/stock".format(product_b.id), {"delta": 5, "reason": "restock"}, "/productos/")
    assert response.status_code == 404
    assert db.session.get(Product, product_b.id) is not None
    assert db.session.scalar(select(Inventory.quantity).where(Inventory.product_id == product_b.id)) == 10


def test_tenant_isolation_customers_and_orders(client, ctx):
    from app.services.orders import place_order

    company_a, _ = create_owner("Empresa Uno", "uno@example.com")
    company_b, _ = create_owner("Empresa Dos", "dos@example.com")
    customer_b = create_customer(company_b)
    product_b = create_product(company_b, sku="B-1")
    order_b = place_order(company_b.id, [(product_b.id, 1)], customer_id=customer_b.id)
    login(client, "uno@example.com")

    assert client.get("/clientes/{}".format(customer_b.id)).status_code == 404
    assert client.get("/clientes/{}/editar".format(customer_b.id)).status_code == 404
    assert client.get("/pedidos/{}".format(order_b.id)).status_code == 404
    response = form_post(client, "/pedidos/{}/estado".format(order_b.id), {"status": "cancelled"}, "/pedidos/")
    assert response.status_code == 404
    assert db.session.get(Order, order_b.id).status == "pending"
    assert "Luis" not in client.get("/clientes/").get_data(as_text=True)
    assert client.get("/api/v1/products/{}/forecast".format(product_b.id)).get_json() == []


def test_owner_creates_product_and_customer(client, ctx):
    company, _ = create_owner("Empresa Uno", "uno@example.com")
    login(client, "uno@example.com")
    response = form_post(
        client,
        "/productos/nuevo",
        {"sku": "NUEVO-1", "name": "Café", "category": "Alimentos", "price": "12000", "cost": "7000", "quantity": "20", "active": "y"},
        "/productos/nuevo",
    )
    assert response.status_code == 302
    product = db.session.scalar(select(Product).where(Product.sku == "NUEVO-1"))
    assert product.company_id == company.id and product.inventory.quantity == 20

    duplicate = form_post(
        client,
        "/productos/nuevo",
        {"sku": "NUEVO-1", "name": "Otro", "category": "Alimentos", "price": "1", "cost": "1", "quantity": "1"},
        "/productos/nuevo",
    )
    assert duplicate.status_code == 409

    response = form_post(
        client,
        "/clientes/nuevo",
        {"first_name": "Marta", "last_name": "Ruiz", "email": "marta@example.com"},
        "/clientes/nuevo",
    )
    assert response.status_code == 302
    assert db.session.scalar(select(Customer.company_id).where(Customer.email == "marta@example.com")) == company.id


def test_pos_sale_via_form(client, ctx):
    company, _ = create_owner("Empresa Uno", "uno@example.com")
    product = create_product(company, quantity=4, price=5000)
    login(client, "uno@example.com")
    response = form_post(
        client,
        "/pedidos/nuevo",
        {"product_id": [str(product.id)], "quantity": ["2"], "paid": "1"},
        "/pedidos/nuevo",
    )
    assert response.status_code == 302
    order = db.session.scalar(select(Order))
    assert order.status == "paid" and order.channel == "pos" and float(order.total) == 10000
    over = form_post(
        client,
        "/pedidos/nuevo",
        {"product_id": [str(product.id)], "quantity": ["9"]},
        "/pedidos/nuevo",
    )
    assert over.status_code == 400


def test_store_checkout_flow(client, ctx):
    company, _ = create_owner("Empresa Uno", "uno@example.com")
    product = create_product(company, quantity=6, price=3000)
    create_customer_user("ana@example.com")
    login(client, "ana@example.com")

    response = form_post(client, "/tienda/carrito/agregar/{}".format(product.id), {"quantity": "2"}, "/tienda/")
    assert response.status_code == 302
    cart = client.get("/tienda/carrito").get_data(as_text=True)
    assert "Producto" in cart

    too_many = form_post(client, "/tienda/carrito/agregar/{}".format(product.id), {"quantity": "50"}, "/tienda/")
    assert too_many.status_code == 302
    assert db.session.scalar(select(func.sum(CartItem.quantity))) == 2

    response = form_post(client, "/tienda/carrito/pagar/{}".format(company.id), {"notes": "Entregar en portería"}, "/tienda/carrito")
    assert response.status_code == 302
    order = db.session.scalar(select(Order))
    assert order.status == "pending" and order.channel == "store" and float(order.total) == 6000
    assert order.customer.email == "ana@example.com"
    assert db.session.scalar(select(func.count(CartItem.id))) == 0
    assert db.session.scalar(select(Inventory.quantity).where(Inventory.product_id == product.id)) == 4

    detail = client.get("/tienda/pedidos/{}".format(order.id))
    assert detail.status_code == 200

    other = client.application.test_client()
    create_customer_user("beto@example.com")
    login(other, "beto@example.com")
    assert other.get("/tienda/pedidos/{}".format(order.id)).status_code == 404

    response = form_post(client, "/tienda/pedidos/{}/cancelar".format(order.id), {}, "/tienda/carrito")
    assert response.status_code == 302
    assert db.session.get(Order, order.id).status == "cancelled"
    assert db.session.scalar(select(Inventory.quantity).where(Inventory.product_id == product.id)) == 6


def test_checkout_fails_when_stock_changed(client, ctx):
    from app.services.orders import adjust_stock

    company, owner = create_owner("Empresa Uno", "uno@example.com")
    product = create_product(company, quantity=3)
    create_customer_user("ana@example.com")
    login(client, "ana@example.com")
    form_post(client, "/tienda/carrito/agregar/{}".format(product.id), {"quantity": "3"}, "/tienda/")
    adjust_stock(company.id, product.id, -2, "adjustment", owner.id)
    response = form_post(client, "/tienda/carrito/pagar/{}".format(company.id), {}, "/tienda/carrito")
    assert response.status_code == 302
    assert db.session.scalar(select(func.count(Order.id))) == 0
    assert db.session.scalar(select(func.count(CartItem.id))) == 1


def test_inactive_products_not_purchasable(client, ctx):
    company, _ = create_owner("Empresa Uno", "uno@example.com")
    product = create_product(company)
    product.active = False
    db.session.commit()
    create_customer_user("ana@example.com")
    login(client, "ana@example.com")
    form_post(client, "/tienda/carrito/agregar/{}".format(product.id), {"quantity": "1"}, "/tienda/")
    assert db.session.scalar(select(func.count(CartItem.id))) == 0
    assert client.get("/tienda/producto/{}".format(product.id)).status_code == 404


def test_wishlist_toggle(client, ctx):
    company, _ = create_owner("Empresa Uno", "uno@example.com")
    product = create_product(company)
    create_customer_user("ana@example.com")
    login(client, "ana@example.com")
    form_post(client, "/tienda/favoritos/{}".format(product.id), {}, "/tienda/")
    assert "Producto" in client.get("/tienda/favoritos").get_data(as_text=True)
    form_post(client, "/tienda/favoritos/{}".format(product.id), {}, "/tienda/")
    assert "Producto" not in client.get("/tienda/favoritos").get_data(as_text=True)
