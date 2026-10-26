import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, ProgrammingError

from app.extensions import db
from app.services import dwquality, etl
from app.services.orders import place_order

from .conftest import create_customer, create_owner, create_product


def roles_available():
    found = db.session.scalar(
        text("select count(*) from pg_roles where rolname in ('dw_reader', 'dw_etl', 'dw_auditor')")
    )
    return found == 3


@pytest.fixture()
def loaded(ctx):
    company, owner = create_owner("Empresa Uno", "uno@example.com")
    product = create_product(company, quantity=50, price=2000, cost=1200)
    customer = create_customer(company)
    place_order(company.id, [(product.id, 2)], customer_id=customer.id, status="paid")
    place_order(company.id, [(product.id, 3)], customer_id=customer.id, status="paid")
    etl.run_etl()
    return company, customer


def test_quality_controls_all_pass(loaded):
    report = dwquality.verify()
    failed = [row for row in report["controles"] if not row["ok"]]
    assert failed == []
    assert report["aprobados"] == report["total"]
    assert report["volumenes"]["fact_ventas"] == 2


def test_etl_run_is_logged(loaded):
    row = db.session.execute(text("select modo, estado, filas_cargadas from dw.etl_ejecuciones order by ejecucion_id desc limit 1")).one()
    assert row.estado == "ok" and row.filas_cargadas == 2 and row.modo == "incremental"


def test_audit_log_records_statements(loaded):
    rows = db.session.execute(
        text("select tabla, operacion, sum(filas) as filas from dw.audit_log group by tabla, operacion")
    ).all()
    seen = {(row.tabla, row.operacion): row.filas for row in rows}
    assert seen[("fact_ventas", "INSERT")] == 2
    assert seen[("dim_cliente", "INSERT")] == 1


def test_audit_log_is_append_only(loaded):
    with pytest.raises(DBAPIError):
        db.session.execute(text("update dw.audit_log set filas = 0"))
    db.session.rollback()
    with pytest.raises(DBAPIError):
        db.session.execute(text("delete from dw.audit_log"))
    db.session.rollback()


def test_email_is_encrypted_and_revealable(loaded, app):
    company, customer = loaded
    stored = db.session.scalar(text("select email_cifrado from dw.dim_cliente where cliente_id = :c"), {"c": customer.id})
    assert customer.email.encode() not in bytes(stored)
    key = app.config["DW_ENCRYPTION_KEY"]
    revealed = db.session.scalar(text("select dw.revelar_email(:c, :k)"), {"c": customer.id, "k": key})
    assert revealed == customer.email
    wrong = None
    with pytest.raises(DBAPIError):
        wrong = db.session.scalar(text("select dw.revelar_email(:c, 'clave-incorrecta')"), {"c": customer.id})
    db.session.rollback()
    assert wrong is None


def test_reader_role_sees_views_only(loaded):
    if not roles_available():
        pytest.skip("roles de la bodega no creados")
    db.session.execute(text("set local role dw_reader"))
    assert db.session.scalar(text("select count(*) from dw.v_ventas_detalle")) == 2
    assert db.session.scalar(text("select ingresos from dw.v_ventas_mensual limit 1")) == 10000
    with pytest.raises(ProgrammingError):
        db.session.execute(text("select * from dw.fact_ventas"))
    db.session.rollback()
    db.session.execute(text("set local role dw_reader"))
    with pytest.raises(ProgrammingError):
        db.session.execute(text("select * from dw.audit_log"))
    db.session.rollback()
    db.session.execute(text("set local role dw_reader"))
    with pytest.raises(ProgrammingError):
        db.session.execute(text("select dw.revelar_email(1, 'x')"))
    db.session.rollback()


def test_reader_view_masks_customer_name(loaded):
    if not roles_available():
        pytest.skip("roles de la bodega no creados")
    db.session.execute(text("set local role dw_reader"))
    masked = db.session.scalar(text("select cliente_anonimo from dw.v_ventas_detalle limit 1"))
    assert masked.endswith("***") and len(masked) == 4
    db.session.rollback()


def test_auditor_role_can_read_audit_but_not_facts(loaded):
    if not roles_available():
        pytest.skip("roles de la bodega no creados")
    db.session.execute(text("set local role dw_auditor"))
    assert db.session.scalar(text("select count(*) from dw.audit_log")) > 0
    with pytest.raises(ProgrammingError):
        db.session.execute(text("select * from dw.fact_ventas"))
    db.session.rollback()


def test_etl_role_cannot_alter_audit(loaded):
    if not roles_available():
        pytest.skip("roles de la bodega no creados")
    db.session.execute(text("set local role dw_etl"))
    assert db.session.scalar(text("select count(*) from dw.fact_ventas")) == 2
    with pytest.raises(ProgrammingError):
        db.session.execute(text("delete from dw.audit_log"))
    db.session.rollback()


def test_failed_etl_is_logged(ctx, monkeypatch):
    company, _ = create_owner("Empresa Uno", "uno@example.com")

    def boom(full):
        raise RuntimeError("fallo simulado")

    monkeypatch.setattr(etl, "execute", boom)
    with pytest.raises(RuntimeError):
        etl.run_etl()
    row = db.session.execute(text("select estado, mensaje from dw.etl_ejecuciones order by ejecucion_id desc limit 1")).one()
    assert row.estado == "error" and "fallo simulado" in row.mensaje


def test_reader_and_auditor_cannot_reach_medallion_layers(loaded):
    if not roles_available():
        pytest.skip("roles de la bodega no creados")
    for role in ("dw_reader", "dw_auditor"):
        for table in ("bronze.ventas", "silver.ventas", "silver.clientes"):
            db.session.execute(text("set local role {}".format(role)))
            with pytest.raises(ProgrammingError):
                db.session.execute(text("select count(*) from {}".format(table)))
            db.session.rollback()


def test_etl_role_can_use_medallion_layers(loaded):
    if not roles_available():
        pytest.skip("roles de la bodega no creados")
    db.session.execute(text("set local role dw_etl"))
    assert db.session.scalar(text("select count(*) from silver.ventas")) == 2
    db.session.rollback()
