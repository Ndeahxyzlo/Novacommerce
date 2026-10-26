from sqlalchemy import select

from app.extensions import db
from app.models import AccessLog, Company, User

from .conftest import PASSWORD, csrf_token, create_admin, create_customer_user, create_owner, login, post


def test_register_customer_and_login(client, ctx):
    token = csrf_token(client, "/auth/register")
    response = client.post(
        "/auth/register",
        data={
            "csrf_token": token,
            "account_type": "customer",
            "first_name": "Ana",
            "last_name": "Pérez",
            "email": "ana@example.com",
            "password": PASSWORD,
            "confirm": PASSWORD,
        },
    )
    assert response.status_code == 302
    user = db.session.scalar(select(User).where(User.email == "ana@example.com"))
    assert user is not None and user.role == "customer" and user.company_id is None
    response = login(client, "ana@example.com")
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/tienda/")


def test_register_owner_creates_company(client, ctx):
    token = csrf_token(client, "/auth/register")
    client.post(
        "/auth/register",
        data={
            "csrf_token": token,
            "account_type": "owner",
            "first_name": "Luis",
            "last_name": "Gómez",
            "email": "luis@example.com",
            "company_name": "Mi Empresa",
            "password": PASSWORD,
            "confirm": PASSWORD,
        },
    )
    user = db.session.scalar(select(User).where(User.email == "luis@example.com"))
    assert user.role == "owner"
    company = db.session.get(Company, user.company_id)
    assert company.name == "Mi Empresa"
    response = login(client, "luis@example.com")
    assert response.headers["Location"].endswith("/dashboard")


def test_register_cannot_escalate_role(client, ctx):
    token = csrf_token(client, "/auth/register")
    response = client.post(
        "/auth/register",
        data={
            "csrf_token": token,
            "account_type": "admin",
            "role": "admin",
            "first_name": "Mal",
            "last_name": "Actor",
            "email": "mal@example.com",
            "password": PASSWORD,
            "confirm": PASSWORD,
        },
    )
    assert response.status_code == 200
    assert db.session.scalar(select(User).where(User.email == "mal@example.com")) is None


def test_profile_edit_cannot_change_role(client, ctx):
    create_customer_user("ana@example.com")
    login(client, "ana@example.com")
    token = csrf_token(client, "/auth/profile/edit")
    client.post(
        "/auth/profile/edit",
        data={"csrf_token": token, "first_name": "Ana", "last_name": "Nueva", "phone": "300", "role": "admin", "company_id": "1"},
    )
    user = db.session.scalar(select(User).where(User.email == "ana@example.com"))
    assert user.role == "customer" and user.company_id is None and user.last_name == "Nueva"


def test_login_requires_csrf(client, ctx):
    create_customer_user("ana@example.com")
    response = client.post("/auth/login", data={"email": "ana@example.com", "password": PASSWORD})
    assert response.status_code == 400


def test_login_blocks_open_redirect(client, ctx):
    create_customer_user("ana@example.com")
    token = csrf_token(client)
    response = client.post(
        "/auth/login?next=https://evil.example.com/",
        data={"email": "ana@example.com", "password": PASSWORD, "csrf_token": token},
    )
    assert response.status_code == 302
    assert "evil.example.com" not in response.headers["Location"]


def test_login_lockout_after_repeated_failures(client, ctx):
    create_customer_user("ana@example.com")
    for _ in range(5):
        response = login(client, "ana@example.com", "incorrecta1")
        assert response.status_code == 401
    response = login(client, "ana@example.com", PASSWORD)
    assert response.status_code == 429
    assert db.session.scalar(select(AccessLog.id).where(AccessLog.event == "login_blocked")) is not None


def test_logout_requires_post_with_csrf(client, ctx):
    create_customer_user("ana@example.com")
    login(client, "ana@example.com")
    assert client.get("/auth/logout").status_code == 405
    assert client.post("/auth/logout").status_code == 400
    response = post(client, "/auth/logout", token_from="/auth/profile")
    assert response.status_code == 302
    assert client.get("/auth/profile").status_code == 302


def test_password_reset_token_is_single_use(client, ctx, app):
    from app.services.security import make_reset_token, read_reset_token

    user = create_customer_user("ana@example.com")
    with app.test_request_context():
        token = make_reset_token(user)
        assert read_reset_token(token).id == user.id
    token_page = csrf_token(client, "/auth/reset/{}".format(token))
    response = client.post(
        "/auth/reset/{}".format(token),
        data={"csrf_token": token_page, "password": "NuevaClave123", "confirm": "NuevaClave123"},
    )
    assert response.status_code == 302
    with app.test_request_context():
        assert read_reset_token(token) is None
    assert login(client, "ana@example.com", "NuevaClave123").status_code == 302


def test_change_password_requires_current(client, ctx):
    create_customer_user("ana@example.com")
    login(client, "ana@example.com")
    token = csrf_token(client, "/auth/password")
    response = client.post(
        "/auth/password",
        data={"csrf_token": token, "current_password": "equivocada1", "password": "NuevaClave123", "confirm": "NuevaClave123"},
    )
    assert response.status_code == 400


def test_role_gates(client, ctx):
    create_owner("Empresa Uno", "uno@example.com")
    create_customer_user("ana@example.com")
    login(client, "uno@example.com")
    assert client.get("/admin/").status_code == 403
    assert client.get("/tienda/carrito").status_code == 403
    client.get("/auth/logout")
    other = client.application.test_client()
    login(other, "ana@example.com")
    assert other.get("/productos/").status_code == 403
    assert other.get("/dashboard").status_code == 403
    assert other.get("/admin/").status_code == 403


def test_anonymous_redirected_to_login(client, ctx):
    for path in ("/dashboard", "/productos/", "/pedidos/", "/tienda/carrito", "/admin/"):
        response = client.get(path)
        assert response.status_code == 302
        assert "/auth/login" in response.headers["Location"]


def test_admin_can_access_admin_area(client, ctx):
    create_admin()
    login(client, "admin@example.com")
    for path in ("/admin/", "/admin/empresas", "/admin/usuarios", "/admin/seguridad"):
        assert client.get(path).status_code == 200


def test_no_unauthenticated_database_endpoints(client, ctx):
    for path in ("/init-db", "/init_db", "/create-tables", "/setup"):
        assert client.get(path).status_code == 404


def test_security_headers(client, ctx):
    response = client.get("/")
    assert "default-src 'self'" in response.headers["Content-Security-Policy"]
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
