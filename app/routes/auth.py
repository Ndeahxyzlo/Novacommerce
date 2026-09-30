from flask import Blueprint, flash, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required, login_user, logout_user
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from werkzeug.security import check_password_hash, generate_password_hash

from ..extensions import db
from ..forms import (
    ChangePasswordForm,
    EmptyForm,
    ForgotPasswordForm,
    LoginForm,
    ProfileForm,
    RegisterForm,
    ResetPasswordForm,
)
from ..models import ROLE_ADMIN, ROLE_CUSTOMER, ROLE_OWNER, Company, User
from ..services.mailer import send_reset_email
from ..services.security import is_locked_out, make_reset_token, read_reset_token, record_access
from ..utils import is_safe_redirect, slugify, utcnow

bp = Blueprint("auth", __name__, url_prefix="/auth")

DUMMY_HASH = generate_password_hash("novacommerce-dummy-password")


def home_for(user):
    if user.role == ROLE_ADMIN:
        return url_for("admin.dashboard")
    if user.role == ROLE_OWNER:
        return url_for("main.dashboard")
    return url_for("store.index")


def unique_slug(name):
    base = slugify(name)
    candidate = base
    counter = 2
    while db.session.scalar(select(Company.id).where(Company.slug == candidate)) is not None:
        candidate = "{}-{}".format(base, counter)
        counter += 1
    return candidate


@bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(home_for(current_user))
    form = LoginForm()
    if form.validate_on_submit():
        email = form.email.data
        if is_locked_out(email):
            record_access("login_blocked", False, email)
            flash("Demasiados intentos fallidos. Espera unos minutos antes de intentarlo de nuevo.", "danger")
            return render_template("auth/login.html", form=form), 429
        user = db.session.scalar(select(User).where(User.email == email))
        if user is None:
            check_password_hash(DUMMY_HASH, form.password.data)
        valid = user is not None and user.active and user.check_password(form.password.data)
        if not valid:
            record_access("login", False, email)
            flash("Correo o contraseña incorrectos.", "danger")
            return render_template("auth/login.html", form=form), 401
        session.clear()
        login_user(user, remember=form.remember.data)
        user.last_login_at = utcnow()
        db.session.commit()
        record_access("login", True, email, user.id)
        target = request.args.get("next")
        if target and is_safe_redirect(target):
            return redirect(target)
        return redirect(home_for(user))
    return render_template("auth/login.html", form=form)


@bp.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(home_for(current_user))
    form = RegisterForm()
    if form.validate_on_submit():
        existing = db.session.scalar(select(User.id).where(User.email == form.email.data))
        if existing is not None:
            form.email.errors.append("Ya existe una cuenta con este correo.")
            return render_template("auth/register.html", form=form), 409
        try:
            company = None
            role = ROLE_CUSTOMER
            if form.account_type.data == "owner":
                role = ROLE_OWNER
                company = Company(
                    name=form.company_name.data,
                    slug=unique_slug(form.company_name.data),
                    email=form.email.data,
                )
                db.session.add(company)
                db.session.flush()
            user = User(
                email=form.email.data,
                first_name=form.first_name.data,
                last_name=form.last_name.data,
                phone=form.phone.data or None,
                role=role,
                company_id=company.id if company else None,
            )
            user.set_password(form.password.data)
            db.session.add(user)
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            flash("No se pudo crear la cuenta. Intenta con otros datos.", "danger")
            return render_template("auth/register.html", form=form), 409
        record_access("register", True, user.email, user.id)
        flash("Cuenta creada. Ya puedes iniciar sesión.", "success")
        return redirect(url_for("auth.login"))
    return render_template("auth/register.html", form=form)


@bp.route("/logout", methods=["POST"])
@login_required
def logout():
    form = EmptyForm()
    if form.validate_on_submit():
        logout_user()
        session.clear()
        flash("Sesión cerrada.", "info")
    return redirect(url_for("main.index"))


@bp.route("/profile")
@login_required
def profile():
    return render_template("auth/profile.html")


@bp.route("/profile/edit", methods=["GET", "POST"])
@login_required
def edit_profile():
    form = ProfileForm(obj=current_user)
    if form.validate_on_submit():
        current_user.first_name = form.first_name.data
        current_user.last_name = form.last_name.data
        current_user.phone = form.phone.data or None
        db.session.commit()
        flash("Perfil actualizado.", "success")
        return redirect(url_for("auth.profile"))
    return render_template("auth/edit_profile.html", form=form)


@bp.route("/password", methods=["GET", "POST"])
@login_required
def change_password():
    form = ChangePasswordForm()
    if form.validate_on_submit():
        if not current_user.check_password(form.current_password.data):
            form.current_password.errors.append("La contraseña actual no es correcta.")
            return render_template("auth/change_password.html", form=form), 400
        current_user.set_password(form.password.data)
        db.session.commit()
        flash("Contraseña actualizada.", "success")
        return redirect(url_for("auth.profile"))
    return render_template("auth/change_password.html", form=form)


@bp.route("/forgot", methods=["GET", "POST"])
def forgot_password():
    if current_user.is_authenticated:
        return redirect(home_for(current_user))
    form = ForgotPasswordForm()
    if form.validate_on_submit():
        user = db.session.scalar(select(User).where(User.email == form.email.data))
        if user is not None and user.active:
            token = make_reset_token(user)
            send_reset_email(user, url_for("auth.reset_password", token=token, _external=True))
        record_access("reset_request", True, form.email.data)
        flash("Si el correo existe, recibirás instrucciones para recuperar tu contraseña.", "info")
        return redirect(url_for("auth.login"))
    return render_template("auth/forgot_password.html", form=form)


@bp.route("/reset/<token>", methods=["GET", "POST"])
def reset_password(token):
    user = read_reset_token(token)
    if user is None:
        flash("El enlace no es válido o ya venció.", "danger")
        return redirect(url_for("auth.forgot_password"))
    form = ResetPasswordForm()
    if form.validate_on_submit():
        user.set_password(form.password.data)
        db.session.commit()
        record_access("reset_done", True, user.email, user.id)
        flash("Contraseña actualizada. Inicia sesión.", "success")
        return redirect(url_for("auth.login"))
    return render_template("auth/reset_password.html", form=form, token=token)
