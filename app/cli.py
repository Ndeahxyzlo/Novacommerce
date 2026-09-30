import os
import click
from flask.cli import with_appcontext
from sqlalchemy import select, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable

from .extensions import db
from .models import ROLE_ADMIN, User
from .services import etl


def register_cli(app):
    @app.cli.command("init-db")
    @with_appcontext
    def init_db():
        db.create_all()
        etl.ensure_schema()
        click.echo("Tablas operacionales y esquema dw creados.")

    @app.cli.command("reset-db")
    @click.option("--yes", is_flag=True, help="Confirma el borrado")
    @with_appcontext
    def reset_db(yes):
        if not yes:
            click.confirm("Esto elimina todos los datos. Continuar?", abort=True)
        db.session.execute(text("drop schema if exists dw cascade"))
        db.session.execute(text("drop schema if exists bronze cascade"))
        db.session.execute(text("drop schema if exists silver cascade"))
        db.session.commit()
        db.drop_all()
        db.create_all()
        etl.ensure_schema()
        click.echo("Base de datos reiniciada.")

    @app.cli.command("create-admin")
    @click.option("--email", required=True)
    @click.option("--password", prompt=True, hide_input=True, confirmation_prompt=True)
    @with_appcontext
    def create_admin(email, password):
        email = email.strip().lower()
        if db.session.scalar(select(User.id).where(User.email == email)) is not None:
            raise click.ClickException("Ya existe un usuario con ese correo.")
        user = User(email=email, first_name="Administrador", last_name="Plataforma", role=ROLE_ADMIN)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        click.echo("Administrador creado.")

    @app.cli.command("seed-demo")
    @click.option("--customers", default=15000, show_default=True)
    @click.option("--orders", default=40000, show_default=True)
    @click.option("--seed", default=42, show_default=True)
    @click.option("--password", default=None, help="Contraseña común de las cuentas demo")
    @click.option("--pipeline/--no-pipeline", default=True, show_default=True)
    @with_appcontext
    def seed_demo_command(customers, orders, seed, password, pipeline):
        from .seed import seed_demo

        summary = seed_demo(customers=customers, orders=orders, seed=seed, password=password)
        click.echo(
            "Sembrado: {companies} empresas, {customers} clientes, {orders} pedidos, {items} líneas, {access_logs} accesos.".format(**summary)
        )
        click.echo("Cuentas demo: " + ", ".join(summary["accounts"]))
        click.echo("Contraseña de las cuentas demo: " + summary["password"])
        if pipeline:
            from .ml import anomaly, demand

            result = etl.run_etl(full=True)
            click.echo("ETL: {} filas de hechos.".format(result["rows"]))
            outcome = demand.run_all_companies()
            for company_id, metrics in outcome.items():
                click.echo("Demanda empresa {}: {}".format(company_id, metrics))
            click.echo("Anomalías: {}".format(anomaly.train()))

    @app.cli.command("etl")
    @click.option("--full", is_flag=True)
    @with_appcontext
    def etl_command(full):
        result = etl.run_etl(full=full)
        click.echo("ETL completado: {} filas.".format(result["rows"]))

    @app.cli.command("dw-verify")
    @click.option("--output", default=None)
    @with_appcontext
    def dw_verify(output):
        import json

        from .services import dwquality

        report = dwquality.verify()
        for row in report["controles"]:
            click.echo("{}  {}  esperado={} obtenido={}".format("OK " if row["ok"] else "ERR", row["control"], row["esperado"], row["obtenido"]))
        click.echo("Aprobados: {}/{}".format(report["aprobados"], report["total"]))
        if output:
            with open(output, "w", encoding="utf-8") as handle:
                json.dump(report, handle, ensure_ascii=False, indent=2, default=str)
            click.echo("Reporte escrito en {}".format(output))
        if report["aprobados"] != report["total"]:
            raise SystemExit(1)

    @app.cli.command("dw-dump")
    @click.option("--output", default="database/dw_carga.sql.gz", show_default=True)
    @with_appcontext
    def dw_dump(output):
        import gzip
        import subprocess

        from sqlalchemy.engine import make_url

        url = make_url(app.config["SQLALCHEMY_DATABASE_URI"])
        command = ["pg_dump", "--schema=dw", "--schema=bronze", "--schema=silver", "--no-owner", "--no-privileges", "--host", url.host or "localhost", "--port", str(url.port or 5432), "--username", url.username, url.database]
        environment = dict(os.environ, PGPASSWORD=url.password or "")
        completed = subprocess.run(command, capture_output=True, env=environment, check=True)
        with gzip.open(output, "wb") as handle:
            handle.write(completed.stdout)
        click.echo("Volcado escrito en {}".format(output))

    @app.cli.command("ml-run")
    @click.option("--company-id", type=int, default=None)
    @with_appcontext
    def ml_run(company_id):
        from .ml import demand

        if company_id:
            click.echo(demand.run_company_pipeline(company_id))
        else:
            for cid, metrics in demand.run_all_companies().items():
                click.echo("Empresa {}: {}".format(cid, metrics))

    @app.cli.command("train-anomaly")
    @with_appcontext
    def train_anomaly():
        from .ml import anomaly

        click.echo(anomaly.train())

    @app.cli.command("export-schema")
    @click.option("--output", default="database/schema.sql", show_default=True)
    @with_appcontext
    def export_schema(output):
        dialect = postgresql.dialect()
        statements = []
        for table in db.metadata.sorted_tables:
            statements.append(str(CreateTable(table).compile(dialect=dialect)).strip() + ";")
            for index in sorted(table.indexes, key=lambda i: i.name or ""):
                statements.append(str(CreateIndex(index).compile(dialect=dialect)).strip() + ";")
        with open(output, "w", encoding="utf-8") as handle:
            handle.write("\n\n".join(statements) + "\n")
        click.echo("Esquema escrito en {}".format(output))
