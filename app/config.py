import os
from datetime import timedelta
from pathlib import Path

from sqlalchemy.pool import NullPool


def normalize_database_url(url):
    if url.startswith("postgres://"):
        return "postgresql+psycopg2://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        return "postgresql+psycopg2://" + url[len("postgresql://"):]
    return url


DEFAULT_DATABASE_URL = "postgresql://novacommerce:novacommerce@localhost:5432/novacommerce"
DEFAULT_TEST_DATABASE_URL = "postgresql://novacommerce:novacommerce@localhost:5432/novacommerce_test"


SERVERLESS = bool(os.getenv("VERCEL"))


class BaseConfig:
    SECRET_KEY = os.getenv("SECRET_KEY", "novacommerce-development-key-change-me")
    SQLALCHEMY_DATABASE_URI = normalize_database_url(os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL))
    SQLALCHEMY_ENGINE_OPTIONS = (
        {"poolclass": NullPool, "connect_args": {"options": "-c timezone=UTC"}}
        if SERVERLESS
        else {
            "pool_pre_ping": True,
            "pool_size": 10,
            "max_overflow": 10,
            "connect_args": {"options": "-c timezone=UTC"},
        }
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    DW_ENCRYPTION_KEY = os.getenv("DW_ENCRYPTION_KEY", "novacommerce-dw-development-key")
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = False
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SAMESITE = "Lax"
    REMEMBER_COOKIE_DURATION = timedelta(days=7)
    PERMANENT_SESSION_LIFETIME = timedelta(hours=8)
    WTF_CSRF_TIME_LIMIT = 8 * 3600
    MAX_CONTENT_LENGTH = 2 * 1024 * 1024
    ITEMS_PER_PAGE = 20
    LOGIN_MAX_FAILURES = 5
    LOGIN_WINDOW_MINUTES = 15
    PASSWORD_RESET_MAX_AGE = 3600
    PROXY_COUNT = int(os.getenv("PROXY_COUNT", "0"))
    MODEL_DIR = os.getenv("MODEL_DIR", "/tmp/novacommerce_models" if SERVERLESS else "")
    FORECAST_HORIZON_WEEKS = 4
    ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "admin@novacommerce.local")
    MAIL_SERVER = os.getenv("MAIL_SERVER", "")
    MAIL_PORT = int(os.getenv("MAIL_PORT", "587"))
    MAIL_USERNAME = os.getenv("MAIL_USERNAME", "")
    MAIL_PASSWORD = os.getenv("MAIL_PASSWORD", "")
    MAIL_USE_TLS = os.getenv("MAIL_USE_TLS", "1") == "1"
    MAIL_SENDER = os.getenv("MAIL_SENDER", "no-reply@novacommerce.local")


class DevelopmentConfig(BaseConfig):
    DEBUG = True


class ProductionConfig(BaseConfig):
    DEBUG = False
    SESSION_COOKIE_SECURE = True
    REMEMBER_COOKIE_SECURE = True
    PREFERRED_URL_SCHEME = "https"
    PROXY_COUNT = int(os.getenv("PROXY_COUNT", "1"))


class TestingConfig(BaseConfig):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = normalize_database_url(os.getenv("TEST_DATABASE_URL", DEFAULT_TEST_DATABASE_URL))
    SECRET_KEY = "testing-secret-key"
    SERVER_NAME = None
    LOGIN_MAX_FAILURES = 5


config_by_name = {
    "development": DevelopmentConfig,
    "production": ProductionConfig,
    "testing": TestingConfig,
}

BASE_DIR = Path(__file__).resolve().parent.parent
