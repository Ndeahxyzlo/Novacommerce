import hashlib
import logging
import os
from datetime import date

from flask import Flask, render_template, url_for
from flask_wtf.csrf import CSRFError
from werkzeug.middleware.proxy_fix import ProxyFix

from .config import config_by_name
from .extensions import csrf, db, login_manager
from .utils import format_money, slugify

CONTENT_SECURITY_POLICY = (
    "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; "
    "form-action 'self'; frame-ancestors 'none'; base-uri 'self'"
)


def create_app(config_name=None):
    config_name = config_name or os.getenv("FLASK_ENV", "development")
    if config_name not in config_by_name:
        config_name = "development"
    if config_name == "production" and not (os.getenv("SECRET_KEY") and os.getenv("DW_ENCRYPTION_KEY")):
        raise RuntimeError("SECRET_KEY y DW_ENCRYPTION_KEY son obligatorias en producción")

    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(config_by_name[config_name])
    if app.config.get("SEND_FILE_MAX_AGE_DEFAULT") is None:
        app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 31536000
    try:
        os.makedirs(app.instance_path, exist_ok=True)
    except OSError:
        pass

    if app.config["PROXY_COUNT"] > 0:
        count = app.config["PROXY_COUNT"]
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=count, x_proto=count, x_host=count)

    db.init_app(app)
    login_manager.init_app(app)
    csrf.init_app(app)

    from . import models

    from .routes import ALL_BLUEPRINTS

    for blueprint in ALL_BLUEPRINTS:
        app.register_blueprint(blueprint)

    register_filters(app)
    register_handlers(app)
    register_static_versioning(app)

    from .cli import register_cli

    register_cli(app)

    if not app.testing:
        logging.basicConfig(level=logging.INFO)

    return app


def register_static_versioning(app):
    versions = {}

    def asset_version(filename):
        path = os.path.join(app.static_folder, filename)
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            return None
        cached = versions.get(filename)
        if cached and cached[0] == mtime:
            return cached[1]
        with open(path, "rb") as handle:
            digest = hashlib.sha256(handle.read()).hexdigest()[:10]
        versions[filename] = (mtime, digest)
        return digest

    @app.url_defaults
    def static_cache_buster(endpoint, values):
        if endpoint == "static" and "filename" in values and "v" not in values:
            version = asset_version(values["filename"])
            if version:
                values["v"] = version


def register_filters(app):
    from flask_login import current_user

    from .models import CHANNEL_LABELS, STATUS_LABELS

    @app.template_filter("money")
    def money_filter(value):
        currency = "COP"
        if current_user.is_authenticated and current_user.company is not None:
            currency = current_user.company.currency
        return format_money(value, currency)

    @app.template_filter("number")
    def number_filter(value):
        if value is None:
            return "-"
        return "{:,.0f}".format(value).replace(",", ".")

    @app.template_filter("decimal")
    def decimal_filter(value, places=1):
        if value is None:
            return "-"
        return "{:,.{p}f}".format(float(value), p=places).replace(",", "_").replace(".", ",").replace("_", ".")

    @app.template_filter("initials")
    def initials_filter(value):
        words = [word for word in (value or "").split() if len(word) > 2 or word[:1].isupper()]
        return "".join(word[0] for word in words[:2]).upper() or (value or "?")[:1].upper()

    @app.template_filter("product_image")
    def product_image_filter(product):
        name = product.get("name") if isinstance(product, dict) else getattr(product, "name", None)
        words = (name or "").split()
        for end in (len(words), len(words) - 1):
            if end < 1:
                continue
            filename = "img/productos/{}.jpg".format(slugify(" ".join(words[:end])))
            if os.path.isfile(os.path.join(app.static_folder, filename)):
                return url_for("static", filename=filename)
        return None

    @app.template_filter("datefmt")
    def date_filter(value):
        return value.strftime("%d/%m/%Y") if value else "-"

    @app.template_filter("datetimefmt")
    def datetime_filter(value):
        return value.strftime("%d/%m/%Y %H:%M") if value else "-"

    @app.template_filter("status_label")
    def status_label(value):
        return STATUS_LABELS.get(value, value)

    @app.template_filter("channel_label")
    def channel_label(value):
        return CHANNEL_LABELS.get(value, value)

    @app.context_processor
    def inject_globals():
        from sqlalchemy import func, select

        from .models import CartItem

        cart_count = 0
        if current_user.is_authenticated and current_user.is_customer:
            cart_count = db.session.scalar(
                select(func.coalesce(func.sum(CartItem.quantity), 0)).where(CartItem.user_id == current_user.id)
            )
        return {"cart_count": cart_count, "now_year": date.today().year}

    @app.after_request
    def security_headers(response):
        response.headers.setdefault("Content-Security-Policy", CONTENT_SECURITY_POLICY)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        if not app.debug and not app.testing:
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        if response.mimetype == "text/html":
            response.headers.setdefault("Cache-Control", "no-store")
        return response


def register_handlers(app):
    def error_page(code, title, message):
        return render_template("errors/error.html", code=code, title=title, message=message), code

    @app.errorhandler(CSRFError)
    def csrf_error(error):
        return error_page(400, "Sesión de formulario vencida", "Recarga la página e inténtalo de nuevo.")

    @app.errorhandler(403)
    def forbidden(error):
        return error_page(403, "Acceso denegado", "No tienes permiso para ver esta página.")

    @app.errorhandler(404)
    def not_found(error):
        return error_page(404, "Página no encontrada", "El recurso que buscas no existe.")

    @app.errorhandler(405)
    def method_not_allowed(error):
        return error_page(405, "Método no permitido", "Esta acción no está disponible por ese medio.")

    @app.errorhandler(413)
    def too_large(error):
        return error_page(413, "Solicitud demasiado grande", "El contenido enviado supera el límite permitido.")

    @app.errorhandler(429)
    def too_many(error):
        return error_page(429, "Demasiadas solicitudes", "Espera un momento antes de reintentar.")

    @app.errorhandler(500)
    def server_error(error):
        db.session.rollback()
        return error_page(500, "Error interno", "Ocurrió un problema. Inténtalo de nuevo en unos minutos.")
