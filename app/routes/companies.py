from flask import Blueprint, flash, redirect, render_template, url_for
from flask_login import current_user

from ..extensions import db
from ..forms import CompanyForm
from ..models import Company
from ..services.security import owner_required

bp = Blueprint("companies", __name__, url_prefix="/empresa")


@bp.route("/")
@owner_required
def view():
    company = db.session.get(Company, current_user.company_id)
    return render_template("companies/view.html", company=company)


@bp.route("/editar", methods=["GET", "POST"])
@owner_required
def edit():
    company = db.session.get(Company, current_user.company_id)
    form = CompanyForm(obj=company)
    if form.validate_on_submit():
        company.name = form.name.data
        company.description = form.description.data or None
        company.email = form.email.data or None
        company.phone = form.phone.data or None
        company.city = form.city.data or None
        company.country = form.country.data
        company.currency = form.currency.data
        company.lead_time_days = form.lead_time_days.data
        company.order_cost = form.order_cost.data
        company.holding_rate = form.holding_rate.data
        company.service_level = form.service_level.data
        db.session.commit()
        flash("Datos de la empresa actualizados.", "success")
        return redirect(url_for("companies.view"))
    return render_template("companies/edit.html", form=form, company=company)
