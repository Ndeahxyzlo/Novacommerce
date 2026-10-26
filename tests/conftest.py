import re

import pytest
from flask import g, has_app_context
from flask.testing import FlaskClient
from sqlalchemy import text

from app import create_app
from app.extensions import db
from app.models import Company, Customer, Inventory, Product, ROLE_ADMIN, ROLE_CUSTOMER, ROLE_OWNER, User
from app.services import etl

PASSWORD = "Segura12345"


@pytest.fixture(scope="session")
def app():
    application = create_app("testing")
    with application.app_context():
        db.drop_all()
        db.session.execute(text("drop schema if exists dw cascade"))
        db.session.execute(text("drop schema if exists bronze cascade"))
        db.session.execute(text("drop schema if exists silver cascade"))
        db.session.commit()
        db.create_all()
        etl.ensure_schema()
    yield application
    with application.app_context():
        db.session.remove()
        db.drop_all()
        db.session.execute(text("drop schema if exists dw cascade"))
        db.session.execute(text("drop schema if exists bronze cascade"))
        db.session.execute(text("drop schema if exists silver cascade"))
        db.session.commit()


@pytest.fixture(autouse=True)
def clean_database(app):
    with app.app_context():
        db.session.remove()
        tables = ", ".join('"{}"'.format(table.name) for table in db.metadata.sorted_tables)
        db.session.execute(text("truncate table {} restart identity cascade".format(tables)))
        db.session.execute(
            text(
                "truncate table dw.fact_ventas, dw.fact_inventario_snapshot, dw.dim_producto, dw.dim_cliente, dw.dim_empresa, dw.dim_tiempo, dw.etl_control, dw.etl_ejecuciones, dw.audit_log, bronze.empresas, bronze.productos, bronze.clientes, bronze.ventas, bronze.inventario, silver.empresas, silver.productos, silver.clientes, silver.ventas, silver.inventario, silver.rechazos cascade"
            )
        )
        db.session.commit()
    yield


class IsolatedClient(FlaskClient):
    def open(self, *args, **kwargs):
        if has_app_context():
            for name in ("csrf_token", "_login_user"):
                g.pop(name, None)
        return super().open(*args, **kwargs)


def new_client(application):
    application.test_client_class = IsolatedClient
    return application.test_client()


@pytest.fixture()
def client(app):
    return new_client(app)


@pytest.fixture()
def ctx(app):
    with app.app_context():
        yield


def csrf_token(client, path="/auth/login"):
    response = client.get(path)
    match = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', response.get_data(as_text=True))
    assert match, "no se encontró el token CSRF en {}".format(path)
    return match.group(1)


def login(client, email, password=PASSWORD, follow=False):
    token = csrf_token(client)
    return client.post(
        "/auth/login",
        data={"email": email, "password": password, "csrf_token": token},
        follow_redirects=follow,
    )


def post(client, path, data=None, token_from="/"):
    payload = dict(data or {})
    payload["csrf_token"] = csrf_token(client, token_from)
    return client.post(path, data=payload)


def create_owner(name, email):
    company = Company(name=name, slug=name.lower().replace(" ", "-"), country="Colombia")
    db.session.add(company)
    db.session.flush()
    owner = User(email=email, first_name="Dueño", last_name=name, role=ROLE_OWNER, company_id=company.id)
    owner.set_password(PASSWORD)
    db.session.add(owner)
    db.session.commit()
    return company, owner


def create_customer_user(email="comprador@example.com"):
    user = User(email=email, first_name="Ana", last_name="Compradora", role=ROLE_CUSTOMER)
    user.set_password(PASSWORD)
    db.session.add(user)
    db.session.commit()
    return user


def create_admin(email="admin@example.com"):
    user = User(email=email, first_name="Admin", last_name="Root", role=ROLE_ADMIN)
    user.set_password(PASSWORD)
    db.session.add(user)
    db.session.commit()
    return user


def create_product(company, sku="SKU-1", name="Producto", price=1000, cost=600, quantity=10):
    product = Product(company_id=company.id, sku=sku, name=name, category="General", price=price, cost=cost)
    product.inventory = Inventory(company_id=company.id, quantity=quantity)
    db.session.add(product)
    db.session.commit()
    return product


def create_customer(company, email="cliente@example.com"):
    customer = Customer(company_id=company.id, first_name="Luis", last_name="Cliente", email=email)
    db.session.add(customer)
    db.session.commit()
    return customer
