from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user
from sqlalchemy import func, select

from ..extensions import db
from ..forms import EmptyForm
from ..ml import anomaly, demand
from ..models import AccessLog, Company, MlRun, Order, Product, User
from ..services import analytics, etl, threats
from ..services.security import admin_required
from ..services.tenancy import paginate
from ..utils import parse_amount

bp = Blueprint("admin", __name__, url_prefix="/admin")


@bp.route("/")
@admin_required
def dashboard():
    totals = {
        "companies": db.session.scalar(select(func.count(Company.id))),
        "users": db.session.scalar(select(func.count(User.id))),
        "products": db.session.scalar(select(func.count(Product.id))),
        "orders": db.session.scalar(select(func.count(Order.id))),
    }
    overview = analytics.platform_overview() if analytics.warehouse_ready() else []
    runs = db.session.scalars(select(MlRun).order_by(MlRun.id.desc()).limit(8)).all()
    return render_template(
        "admin/dashboard.html", totals=totals, overview=overview, runs=runs, action_form=EmptyForm()
    )


@bp.route("/empresas")
@admin_required
def companies():
    query = (
        select(Company, func.count(Product.id).label("products"))
        .outerjoin(Product, Product.company_id == Company.id)
        .group_by(Company.id)
        .order_by(Company.name)
    )
    return render_template("admin/companies.html", pagination=paginate(query), action_form=EmptyForm())


@bp.route("/empresas/<int:company_id>/estado", methods=["POST"])
@admin_required
def toggle_company(company_id):
    company = db.session.get(Company, company_id)
    form = EmptyForm()
    if company is not None and form.validate_on_submit():
        company.active = not company.active
        db.session.commit()
        flash("Empresa {}.".format("activada" if company.active else "desactivada"), "success")
    return redirect(url_for("admin.companies"))


@bp.route("/usuarios")
@admin_required
def users():
    q = request.args.get("q", "").strip()
    query = select(User).order_by(User.created_at.desc())
    if q:
        query = query.where(User.email.ilike("%{}%".format(q)))
    return render_template("admin/users.html", pagination=paginate(query), q=q, action_form=EmptyForm())


@bp.route("/usuarios/<int:user_id>/estado", methods=["POST"])
@admin_required
def toggle_user(user_id):
    user = db.session.get(User, user_id)
    form = EmptyForm()
    if user is None or not form.validate_on_submit():
        return redirect(url_for("admin.users"))
    if user.id == current_user.id:
        flash("No puedes desactivar tu propia cuenta.", "danger")
    else:
        user.active = not user.active
        db.session.commit()
        flash("Usuario {}.".format("activado" if user.active else "desactivado"), "success")
    return redirect(url_for("admin.users"))


@bp.route("/seguridad")
@admin_required
def security():
    recent = db.session.scalars(select(AccessLog).order_by(AccessLog.created_at.desc()).limit(30)).all()
    risky = anomaly.score_recent()
    run = db.session.scalar(select(MlRun).where(MlRun.kind == "anomaly").order_by(MlRun.id.desc()).limit(1))
    return render_template("admin/security.html", recent=recent, risky=risky, run=run, action_form=EmptyForm())


@bp.route("/simulaciones")
@admin_required
def threat_simulations():
    mode = request.args.get("modo", threats.MODE_CLASS)
    if mode not in threats.MODES:
        mode = threats.MODE_CLASS
    servers = parse_amount(request.args.get("servidores"))
    analysts = parse_amount(request.args.get("analistas"))
    plan = threats.threat_plan(mode, servers, analysts)
    observed = {
        "events": db.session.scalar(select(func.count(AccessLog.id))),
        "attacks": db.session.scalar(select(func.count(AccessLog.id)).where(AccessLog.label == 1)),
        "attacker_ips": db.session.scalar(select(func.count(func.distinct(AccessLog.ip))).where(AccessLog.label == 1)),
    }
    return render_template(
        "admin/threats.html",
        plan=plan,
        mode=mode,
        custom=servers is not None or analysts is not None,
        observed=observed,
        modes=threats.MODES,
    )


@bp.route("/seguridad/entrenar", methods=["POST"])
@admin_required
def train_anomaly():
    form = EmptyForm()
    if form.validate_on_submit():
        metrics = anomaly.train()
        if metrics.get("trained"):
            flash("Modelo de accesos entrenado. Exactitud {}.".format(metrics["accuracy"]), "success")
        else:
            flash("No hay datos etiquetados suficientes para entrenar.", "info")
    return redirect(url_for("admin.security"))


@bp.route("/pipeline", methods=["POST"])
@admin_required
def pipeline():
    form = EmptyForm()
    if form.validate_on_submit():
        etl.run_etl()
        summary = demand.run_all_companies()
        flash("Pipeline completo para {} empresas.".format(len(summary)), "success")
    return redirect(url_for("admin.dashboard"))
