import ast
import io
import re
import tokenize
from pathlib import Path

import pytest
from sqlalchemy import func, select, text

from app.extensions import db
from app.ml import anomaly, demand
from app.models import AccessLog, DemandForecast, Inventory, MlRun
from app.seed import seed_demo
from app.services import analytics, etl
from app.services.orders import change_status, place_order

from .conftest import create_customer, create_owner, create_product, login

ROOT = Path(__file__).resolve().parent.parent


def test_etl_loads_facts_and_propagates_changes(ctx):
    company, owner = create_owner("Empresa Uno", "uno@example.com")
    product = create_product(company, quantity=50, price=2000, cost=1200)
    customer = create_customer(company)
    first = place_order(company.id, [(product.id, 2)], customer_id=customer.id, status="paid")
    place_order(company.id, [(product.id, 3)], customer_id=customer.id, status="paid")

    result = etl.run_etl()
    assert result["rows"] == 2
    assert db.session.scalar(text("select count(*) from dw.fact_ventas")) == 2
    assert db.session.scalar(text("select sum(margen) from dw.fact_ventas")) == (2000 - 1200) * 5

    again = etl.run_etl()
    assert db.session.scalar(text("select count(*) from dw.fact_ventas")) == 2
    assert again["rows"] <= 2

    change_status(company.id, first.id, "cancelled", owner.id)
    etl.run_etl()
    assert db.session.scalar(text("select estado from dw.fact_ventas where orden_id = :o"), {"o": first.id}) == "cancelled"
    kpis = analytics.kpis(company.id)
    assert kpis["ordenes"] == 1
    assert float(kpis["ingresos"]) == 6000


def test_etl_full_reload_is_idempotent(ctx):
    company, _ = create_owner("Empresa Uno", "uno@example.com")
    product = create_product(company, quantity=50)
    for _ in range(3):
        place_order(company.id, [(product.id, 1)])
    etl.run_etl()
    etl.run_etl(full=True)
    assert db.session.scalar(text("select count(*) from dw.fact_ventas")) == 3


@pytest.fixture()
def seeded(ctx):
    return seed_demo(customers=600, orders=6000, seed=7, password="Demo12345x")


def test_seed_and_pipeline(seeded, ctx):
    assert seeded["companies"] == 3
    etl.run_etl(full=True)
    company_id = db.session.scalar(text("select id from companies order by id limit 1"))
    metrics = demand.run_company_pipeline(company_id, refresh_warehouse=False)
    assert metrics["products"] > 0
    assert metrics["model_kind"] in ("gradient_boosting", "baseline_mean")
    forecasts = db.session.scalar(select(func.count(DemandForecast.id)).where(DemandForecast.company_id == company_id))
    assert forecasts == metrics["products"] * 4
    assert db.session.scalar(select(func.count(Inventory.id)).where(Inventory.company_id == company_id, Inventory.reorder_point > 0)) > 0
    run = demand.latest_run(company_id)
    assert run is not None and run.status == "ok"


def test_analytics_queries_on_seed(seeded, ctx):
    etl.run_etl(full=True)
    company_id = db.session.scalar(text("select id from companies order by id limit 1"))
    assert analytics.kpis(company_id)["ordenes"] > 0
    assert analytics.monthly_sales(company_id)
    assert analytics.top_products(company_id)[0]["posicion"] == 1
    assert analytics.rollup_category(company_id)
    assert {row["clase"] for row in analytics.abc_analysis(company_id)} >= {"A"}
    assert analytics.rfm_segments(company_id)
    assert analytics.sales_by_channel(company_id)
    assert analytics.sales_by_weekday(company_id)
    assert analytics.platform_overview()


def test_anomaly_model_trains_and_scores(seeded, ctx):
    metrics = anomaly.train()
    assert metrics["trained"] is True
    assert metrics["accuracy"] > 0.9
    ranked = anomaly.score_recent(days=60)
    assert ranked and ranked[0]["risk"] >= ranked[-1]["risk"]
    assert db.session.scalar(select(func.count(AccessLog.id)).where(AccessLog.risk.is_not(None))) > 0
    assert db.session.scalar(select(func.count(MlRun.id)).where(MlRun.kind == "anomaly")) == 1


def test_anomaly_without_labels_is_skipped(ctx):
    assert anomaly.train()["trained"] is False


def test_owner_pages_render_with_data(seeded, client, ctx):
    etl.run_etl(full=True)
    demand.run_all_companies()
    login(client, "owner.tienda-andina@novacommerce.local", "Demo12345x")
    paths = [
        "/dashboard",
        "/productos/",
        "/productos/?state=low",
        "/clientes/",
        "/pedidos/",
        "/pedidos/?status=paid&q=1",
        "/pedidos/nuevo",
        "/pedidos/exportar.csv",
        "/reportes/",
        "/reportes/olap",
        "/reportes/inventario",
        "/reportes/inventario?format=csv",
        "/reportes/ventas",
        "/reportes/ventas?format=csv",
        "/reportes/ml",
        "/empresa/",
        "/empresa/editar",
        "/auth/profile",
        "/api/v1/sales/daily?days=60",
    ]
    for path in paths:
        response = client.get(path)
        assert response.status_code == 200, path
    product_id = db.session.scalar(text("select id from products where company_id = 1 order by id limit 1"))
    assert client.get("/productos/{}".format(product_id)).status_code == 200
    assert client.get("/productos/{}/editar".format(product_id)).status_code == 200
    order_id = db.session.scalar(text("select id from orders where company_id = 1 order by id limit 1"))
    assert client.get("/pedidos/{}".format(order_id)).status_code == 200
    customer_id = db.session.scalar(text("select id from customers where company_id = 1 order by id limit 1"))
    assert client.get("/clientes/{}".format(customer_id)).status_code == 200


def test_admin_and_store_pages_render(seeded, client, ctx):
    etl.run_etl(full=True)
    login(client, "admin@novacommerce.local", "Demo12345x")
    for path in ("/admin/", "/admin/empresas", "/admin/usuarios?q=owner", "/admin/seguridad"):
        assert client.get(path).status_code == 200, path
    other = client.application.test_client()
    for path in ("/", "/tienda/", "/tienda/tienda-andina", "/tienda/tienda-andina?q=a&category=Hogar", "/auth/login", "/auth/register", "/healthz"):
        assert other.get(path).status_code == 200, path


def test_reports_dashboard_empty_state(client, ctx):
    create_owner("Empresa Uno", "uno@example.com")
    login(client, "uno@example.com")
    response = client.get("/reportes/")
    assert response.status_code == 200
    assert client.get("/reportes/ml").status_code == 200
    assert client.get("/reportes/olap").status_code == 200


EMOJI_PATTERN = re.compile(
    "[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F000-\U0001F2FF\U00002B00-\U00002BFF\U0000FE0F\U0000200D]"
)

SOURCE_SUFFIXES = {".py", ".html", ".css", ".js", ".sql", ".txt", ".toml", ".example"}


def source_files():
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(ROOT)
        if any(part in {".git", "__pycache__", ".pytest_cache", "instance", ".venv", "venv"} for part in relative.parts):
            continue
        if path.suffix in SOURCE_SUFFIXES or path.name in {"Procfile", ".gitignore", ".env.example"}:
            yield path


def test_sources_have_no_emojis():
    offenders = []
    for path in source_files():
        if EMOJI_PATTERN.search(path.read_text(encoding="utf-8")):
            offenders.append(str(path.relative_to(ROOT)))
    assert offenders == []


def test_sources_have_no_comments():
    offenders = []
    for path in source_files():
        content = path.read_text(encoding="utf-8")
        relative = str(path.relative_to(ROOT))
        if path.suffix == ".py":
            for token in tokenize.generate_tokens(io.StringIO(content).readline):
                if token.type == tokenize.COMMENT:
                    offenders.append("{}:{}".format(relative, token.start[0]))
            tree = ast.parse(content)
            for node in ast.walk(tree):
                if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and ast.get_docstring(node, clean=False):
                    offenders.append("{}: docstring".format(relative))
        elif path.suffix == ".html":
            if "<!--" in content or "{#" in content:
                offenders.append(relative)
        elif path.suffix == ".css":
            if "/*" in content:
                offenders.append(relative)
        elif path.suffix == ".js":
            for number, line in enumerate(content.splitlines(), 1):
                stripped = line.strip()
                if stripped.startswith("//") or "/*" in stripped or re.search(r"\s//\s", line):
                    offenders.append("{}:{}".format(relative, number))
        elif path.suffix == ".sql":
            for number, line in enumerate(content.splitlines(), 1):
                if line.strip().startswith("--") or "/*" in line:
                    offenders.append("{}:{}".format(relative, number))
    assert offenders == []
