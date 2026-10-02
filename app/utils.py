import re
import unicodedata
from datetime import datetime, timezone
from decimal import Decimal
from urllib.parse import urljoin, urlparse

from flask import request


def utcnow():
    return datetime.now(timezone.utc)


def slugify(value):
    normalized = unicodedata.normalize("NFKD", value or "").encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "-", normalized.lower()).strip("-")
    return slug or "item"


def money(value):
    return Decimal(str(value)).quantize(Decimal("0.01"))


def is_safe_redirect(target):
    if not target or not target.startswith("/") or target.startswith("//"):
        return False
    reference = urlparse(request.host_url)
    candidate = urlparse(urljoin(request.host_url, target))
    return candidate.scheme in ("http", "https") and reference.netloc == candidate.netloc


def client_ip():
    return (request.remote_addr or "0.0.0.0")[:45]


def user_agent():
    return (request.headers.get("User-Agent") or "")[:255]


def format_money(value, currency="COP"):
    if value is None:
        return "-"
    amount = Decimal(str(value))
    if currency == "COP":
        return "$ {:,.0f}".format(amount).replace(",", ".")
    return "{:,.2f} {}".format(amount, currency)


def parse_amount(value):
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return None
    if amount < 0 or amount != amount or amount == float("inf"):
        return None
    return amount
