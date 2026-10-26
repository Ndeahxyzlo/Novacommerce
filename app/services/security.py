import hashlib
from datetime import timedelta
from functools import wraps

from flask import abort, current_app
from flask_login import current_user
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy import func, select

from ..extensions import db
from ..models import AccessLog, ROLE_ADMIN, ROLE_CUSTOMER, ROLE_OWNER, User
from ..utils import client_ip, user_agent, utcnow


def roles_required(*roles):
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if not current_user.is_authenticated:
                return current_app.login_manager.unauthorized()
            if current_user.role not in roles:
                abort(403)
            if current_user.role == ROLE_OWNER and current_user.company_id is None:
                abort(403)
            return view(*args, **kwargs)

        return wrapped

    return decorator


admin_required = roles_required(ROLE_ADMIN)
owner_required = roles_required(ROLE_OWNER)
customer_required = roles_required(ROLE_CUSTOMER)
staff_required = roles_required(ROLE_ADMIN, ROLE_OWNER)


def tenant_id():
    return current_user.company_id


def record_access(event, success, email=None, user_id=None):
    entry = AccessLog(
        user_id=user_id,
        email=(email or "")[:255] or None,
        ip=client_ip(),
        event=event,
        success=bool(success),
        path=None,
        user_agent=user_agent(),
    )
    db.session.add(entry)
    db.session.commit()
    return entry


def is_locked_out(email):
    window = timedelta(minutes=current_app.config["LOGIN_WINDOW_MINUTES"])
    limit = current_app.config["LOGIN_MAX_FAILURES"]
    since = utcnow() - window
    ip = client_ip()

    last_success = db.session.scalar(
        select(func.max(AccessLog.created_at)).where(
            AccessLog.event == "login", AccessLog.success.is_(True), AccessLog.email == email
        )
    )
    email_since = since if last_success is None or last_success < since else last_success

    email_failures = db.session.scalar(
        select(func.count(AccessLog.id)).where(
            AccessLog.event == "login",
            AccessLog.success.is_(False),
            AccessLog.email == email,
            AccessLog.created_at >= email_since,
        )
    )
    ip_failures = db.session.scalar(
        select(func.count(AccessLog.id)).where(
            AccessLog.event == "login",
            AccessLog.success.is_(False),
            AccessLog.ip == ip,
            AccessLog.created_at >= since,
        )
    )
    return email_failures >= limit or ip_failures >= limit * 4


def _serializer():
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt="password-reset")


def _fingerprint(user):
    return hashlib.sha256(user.password_hash.encode("utf-8")).hexdigest()[:16]


def make_reset_token(user):
    return _serializer().dumps({"id": user.id, "fp": _fingerprint(user)})


def read_reset_token(token):
    try:
        data = _serializer().loads(token, max_age=current_app.config["PASSWORD_RESET_MAX_AGE"])
    except (BadSignature, SignatureExpired):
        return None
    user = db.session.get(User, data.get("id"))
    if user is None or not user.active or data.get("fp") != _fingerprint(user):
        return None
    return user
