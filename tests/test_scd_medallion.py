from sqlalchemy import text

from app.extensions import db
from app.models import Product
from app.services import analytics, dwquality, etl
from app.services.orders import place_order

from .conftest import create_customer, create_owner, create_product


def scalar(sql, **params):
    return db.session.scalar(text(sql), params)


def test_medallion_layers_are_populated(ctx):
    company, _ = create_owner("Empresa Uno", "uno@example.com")
    product = create_product(company, quantity=50)
    customer = create_customer(company)
    place_order(company.id, [(product.id, 2)], customer_id=customer.id, status="paid")
    etl.run_etl()
    assert scalar("select count(*) from bronze.ventas") == 1
    assert scalar("select count(*) from silver.ventas") == 1
    assert scalar("select count(*) from dw.fact_ventas") == 1
    assert scalar("select count(*) from silver.rechazos") == 0
    assert scalar("select count(*) from bronze.clientes where email_cifrado is not null") == 1


def test_scd2_product_price_change_keeps_history(ctx):
    company, _ = create_owner("Empresa Uno", "uno@example.com")
    product = create_product(company, quantity=50, price=2000, cost=1200)
    place_order(company.id, [(product.id, 1)], status="paid")
    etl.run_etl()
    assert scalar("select count(*) from dw.dim_producto") == 1
    first_sk = scalar("select producto_sk from dw.dim_producto")
    assert scalar("select fecha_inicio::text from dw.dim_producto") == "1900-01-01"

    row = db.session.get(Product, product.id)
    row.price = 2500
    db.session.commit()
    result = etl.run_etl()
    assert result["product_versions"] == 1
    assert scalar("select count(*) from dw.dim_producto") == 2
    assert scalar("select count(*) from dw.dim_producto where vigente") == 1
    assert scalar("select precio_lista from dw.dim_producto where vigente") == 2500
    assert scalar("select vigente from dw.dim_producto where producto_sk = :s", s=first_sk) is False
    assert scalar("select fecha_fin is not null from dw.dim_producto where producto_sk = :s", s=first_sk) is True

    place_order(company.id, [(product.id, 1)], status="paid")
    etl.run_etl()
    sks = db.session.execute(text("select producto_sk from dw.fact_ventas order by orden_item_id")).scalars().all()
    assert sks[0] == first_sk
    assert sks[1] != first_sk
    assert scalar("select count(distinct producto_id) from dw.fact_ventas") == 1


def test_scd2_unchanged_product_does_not_version(ctx):
    company, _ = create_owner("Empresa Uno", "uno@example.com")
    product = create_product(company, quantity=50)
    place_order(company.id, [(product.id, 1)], status="paid")
    etl.run_etl()
    result = etl.run_etl()
    assert result["product_versions"] == 0
    assert result["customer_versions"] == 0
    assert scalar("select count(*) from dw.dim_producto") == 1


def test_scd2_customer_city_change_keeps_history_and_email(ctx, app):
    company, _ = create_owner("Empresa Uno", "uno@example.com")
    product = create_product(company, quantity=50)
    customer = create_customer(company)
    customer.city = "Bogota"
    db.session.commit()
    place_order(company.id, [(product.id, 1)], customer_id=customer.id, status="paid")
    etl.run_etl()
    customer.city = "Medellin"
    db.session.commit()
    result = etl.run_etl()
    assert result["customer_versions"] == 1
    assert scalar("select count(*) from dw.dim_cliente where cliente_id = :c", c=customer.id) == 2
    assert scalar("select ciudad from dw.dim_cliente where vigente") == "Medellin"
    assert scalar("select count(*) from dw.dim_cliente where email_cifrado is not null") == 2
    key = app.config["DW_ENCRYPTION_KEY"]
    assert scalar("select dw.revelar_email(:c, :k)", c=customer.id, k=key) == customer.email


def test_full_reload_preserves_dimension_history(ctx):
    company, _ = create_owner("Empresa Uno", "uno@example.com")
    product = create_product(company, quantity=50)
    place_order(company.id, [(product.id, 1)], status="paid")
    etl.run_etl()
    db.session.get(Product, product.id).cost = 900
    db.session.commit()
    etl.run_etl()
    etl.run_etl(full=True)
    assert scalar("select count(*) from dw.dim_producto") == 2
    assert scalar("select count(*) from dw.fact_ventas") == 1
    report = dwquality.verify()
    assert [row for row in report["controles"] if not row["ok"]] == []


def test_inventory_snapshot_is_periodic_and_idempotent(ctx):
    company, _ = create_owner("Empresa Uno", "uno@example.com")
    product = create_product(company, quantity=8)
    product.inventory.reorder_point = 10
    db.session.commit()
    etl.run_etl()
    etl.run_etl()
    assert scalar("select count(*) from dw.fact_inventario_snapshot") == 1
    assert scalar("select requiere_reposicion from dw.fact_inventario_snapshot") is True
    status = analytics.inventory_status(company.id)
    assert len(status) == 1 and status[0]["cantidad_disponible"] == 8


def test_invalid_rows_are_rejected_in_silver(ctx):
    company, _ = create_owner("Empresa Uno", "uno@example.com")
    product = create_product(company, quantity=50)
    place_order(company.id, [(product.id, 1)], status="paid")
    etl.run_etl(full=True)
    db.session.execute(text("update bronze.ventas set line_total = line_total + 1"))
    db.session.commit()
    lote = scalar("select extraido_en from bronze.ventas")
    db.session.execute(text("truncate silver.ventas, silver.rechazos"))
    db.session.execute(etl.SILVER_REJECTS, {"lote": lote})
    db.session.execute(etl.SILVER_SALES, {"lote": lote})
    db.session.commit()
    assert scalar("select count(*) from silver.ventas") == 0
    assert scalar("select motivo from silver.rechazos") == "ingreso_inconsistente"


def test_legacy_dw_layout_is_rebuilt(ctx):
    company, _ = create_owner("Empresa Uno", "uno@example.com")
    product = create_product(company, quantity=50)
    place_order(company.id, [(product.id, 1)], status="paid")
    etl.run_etl()
    db.session.execute(text("drop schema dw cascade"))
    db.session.execute(text("create schema dw"))
    db.session.execute(text("create table dw.dim_producto (producto_id integer primary key)"))
    db.session.commit()
    assert etl.is_legacy_layout() is True
    result = etl.run_etl()
    assert result["rows"] == 1
    assert etl.is_legacy_layout() is False
