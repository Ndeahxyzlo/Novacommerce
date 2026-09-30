import ipaddress
import random
import secrets
from datetime import timedelta

import numpy as np
from faker import Faker
from sqlalchemy import insert, select, text, update

from .extensions import db
from .models import (
    AccessLog,
    Company,
    Customer,
    Inventory,
    Order,
    OrderItem,
    Product,
    ROLE_ADMIN,
    ROLE_CUSTOMER,
    ROLE_OWNER,
    User,
)
from .utils import slugify, utcnow

COMPANIES = [
    {"name": "Tienda Andina", "city": "Bogotá", "categories": ["Hogar", "Alimentos", "Libros"], "prefix": "AND", "weight": 0.40},
    {"name": "TecnoHogar", "city": "Medellín", "categories": ["Electrónica", "Hogar"], "prefix": "TEC", "weight": 0.35},
    {"name": "ModaViva", "city": "Cali", "categories": ["Ropa", "Deportes"], "prefix": "MOD", "weight": 0.25},
]

CATALOG = {
    "Electrónica": (
        ["Audífonos inalámbricos", "Cargador rápido", "Teclado mecánico", "Mouse ergonómico", "Parlante portátil", "Cámara web", "Batería externa", "Monitor de 24 pulgadas", "Hub USB", "Soporte para portátil"],
        (60000, 900000),
        (0.35, 44),
    ),
    "Hogar": (
        ["Juego de sábanas", "Licuadora", "Set de ollas", "Lámpara de mesa", "Organizador de cocina", "Toallas de baño", "Cafetera", "Aspiradora manual", "Cojines decorativos", "Termo de acero"],
        (25000, 450000),
        (0.20, 40),
    ),
    "Alimentos": (
        ["Café de origen", "Chocolate artesanal", "Aceite de oliva", "Granola", "Miel de abeja", "Mix de frutos secos", "Té aromático", "Salsa picante", "Arequipe", "Pasta artesanal"],
        (8000, 90000),
        (0.25, 45),
    ),
    "Libros": (
        ["Novela histórica", "Guía de programación", "Libro de cocina", "Atlas ilustrado", "Cuentos infantiles", "Manual de finanzas", "Ensayos de filosofía", "Biografía", "Poesía contemporánea", "Cómic"],
        (22000, 120000),
        (0.30, 30),
    ),
    "Ropa": (
        ["Camiseta básica", "Jean clásico", "Chaqueta ligera", "Vestido casual", "Sudadera", "Camisa de lino", "Falda midi", "Bufanda", "Gorra", "Pantaloneta"],
        (30000, 320000),
        (0.40, 10),
    ),
    "Deportes": (
        ["Balón de fútbol", "Tenis de correr", "Mancuernas", "Colchoneta de yoga", "Botella deportiva", "Guantes de gimnasio", "Bicicleta estática", "Cuerda para saltar", "Casco de ciclismo", "Mochila deportiva"],
        (20000, 780000),
        (0.30, 14),
    ),
}

VARIANTS = ["Classic", "Plus", "Lite", "Pro", "Max", "Eco"]

CITIES = [
    ("Bogotá", 0.30),
    ("Medellín", 0.16),
    ("Cali", 0.12),
    ("Barranquilla", 0.08),
    ("Cartagena", 0.06),
    ("Bucaramanga", 0.05),
    ("Pereira", 0.04),
    ("Manizales", 0.04),
    ("Cúcuta", 0.04),
    ("Santa Marta", 0.04),
    ("Ibagué", 0.04),
    ("Villavicencio", 0.03),
]


def next_ids(table_name, count):
    rows = db.session.execute(
        text("select nextval(pg_get_serial_sequence(:t, 'id')) from generate_series(1, :n)"),
        {"t": table_name, "n": count},
    ).scalars().all()
    return [int(value) for value in rows]


def day_weights(span):
    start_index = np.arange(span)
    end = utcnow().replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=1)
    start = end - timedelta(days=span - 1)
    dates = [start + timedelta(days=int(i)) for i in start_index]
    dow = np.array([d.weekday() for d in dates])
    doy = np.array([d.timetuple().tm_yday for d in dates])
    factor_dow = np.array([1.0, 0.95, 0.95, 1.0, 1.25, 1.4, 1.1])[dow]
    season = 1 + 0.25 * np.sin(2 * np.pi * (doy - 80) / 365.0) + 0.6 * np.exp(-(((doy - 340) / 18.0) ** 2))
    trend = 1 + 0.7 * start_index / span
    weights = factor_dow * season * trend
    return dates, weights / weights.sum()


def build_products(company, rng):
    products = []
    counter = 1
    for category in company["categories"]:
        names, price_range, _ = CATALOG[category]
        for base in names:
            for variant in rng.sample(VARIANTS, 2):
                low, high = price_range
                price = int(rng.uniform(low, high) / 100) * 100
                cost = int(price * rng.uniform(0.45, 0.75) / 100) * 100
                products.append(
                    {
                        "sku": "{}-{:04d}".format(company["prefix"], counter),
                        "name": "{} {}".format(base, variant),
                        "category": category,
                        "price": price,
                        "cost": cost,
                    }
                )
                counter += 1
    return products


def seed_access_logs(rng, emails, total_normal=6000, attackers=90):
    now = utcnow()
    base_ips = [str(ipaddress.IPv4Address(rng.randint(16777216, 3758096383))) for _ in range(350)]
    agents = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 Safari/605.1.15",
        "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 Chrome/126.0 Mobile Safari/537.36",
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148",
    ]
    rows = []
    hours = np.array([0.5, 0.3, 0.2, 0.2, 0.3, 0.8, 2, 4, 6, 7, 7, 6, 6, 6, 6, 6, 6, 6, 5, 4, 3, 2, 1, 0.7])
    hours = hours / hours.sum()
    for _ in range(total_normal):
        day = rng.randint(0, 29)
        hour = int(np.random.choice(24, p=hours))
        moment = now - timedelta(days=day) - timedelta(hours=rng.randint(0, 23)) + timedelta(seconds=rng.randint(0, 3599))
        moment = moment.replace(hour=hour)
        rows.append(
            {
                "email": rng.choice(emails),
                "ip": rng.choice(base_ips),
                "event": "login",
                "success": rng.random() < 0.93,
                "user_agent": rng.choice(agents),
                "label": 0,
                "created_at": moment,
            }
        )
    for _ in range(attackers):
        kind = rng.choice(["brute", "stuffing"])
        ip = str(ipaddress.IPv4Address(rng.randint(16777216, 3758096383)))
        start = now - timedelta(days=rng.randint(0, 29))
        start = start.replace(hour=rng.choice([0, 1, 2, 3, 4, 5, 23, 22, 14]), minute=rng.randint(0, 50))
        agent = rng.choice(["", "python-requests/2.31", agents[0]])
        if kind == "brute":
            target = rng.choice(emails)
            attempts = rng.randint(8, 40)
            for i in range(attempts):
                rows.append(
                    {
                        "email": target,
                        "ip": ip,
                        "event": "login",
                        "success": i == attempts - 1 and rng.random() < 0.15,
                        "user_agent": agent,
                        "label": 1,
                        "created_at": start + timedelta(seconds=i * rng.randint(2, 20)),
                    }
                )
        else:
            attempts = rng.randint(20, 60)
            for i in range(attempts):
                rows.append(
                    {
                        "email": "victima{}@example.com".format(rng.randint(1, 5000)),
                        "ip": ip,
                        "event": "login",
                        "success": False,
                        "user_agent": agent,
                        "label": 1,
                        "created_at": start + timedelta(seconds=i * rng.randint(1, 12)),
                    }
                )
    for row in rows:
        row["path"] = "/auth/login"
    db.session.execute(insert(AccessLog.__table__), rows)
    return len(rows)


def seed_demo(customers=15000, orders=40000, seed=42, password=None):
    if db.session.scalar(select(User.id).limit(1)) is not None:
        raise RuntimeError("La base de datos ya contiene datos. Ejecuta reset-db antes de sembrar.")

    rng = random.Random(seed)
    generator = np.random.default_rng(seed)
    np.random.seed(seed)
    faker = Faker("es_CO")
    Faker.seed(seed)
    password = password or secrets.token_urlsafe(12)
    now = utcnow()

    admin = User(email="admin@novacommerce.local", first_name="Administrador", last_name="Plataforma", role=ROLE_ADMIN)
    admin.set_password(password)
    db.session.add(admin)

    company_rows = []
    owner_emails = []
    for spec in COMPANIES:
        company = Company(
            name=spec["name"],
            slug=slugify(spec["name"]),
            city=spec["city"],
            country="Colombia",
            email="contacto@{}.example.com".format(slugify(spec["name"])),
            lead_time_days=rng.choice([5, 7, 10, 14]),
        )
        db.session.add(company)
        db.session.flush()
        owner_email = "owner.{}@novacommerce.local".format(slugify(spec["name"]))
        owner = User(
            email=owner_email,
            first_name="Propietario",
            last_name=spec["name"],
            role=ROLE_OWNER,
            company_id=company.id,
        )
        owner.set_password(password)
        db.session.add(owner)
        owner_emails.append(owner_email)
        company_rows.append((spec, company))

    shopper = User(email="cliente@novacommerce.local", first_name="Cliente", last_name="Demostración", role=ROLE_CUSTOMER)
    shopper.set_password(password)
    db.session.add(shopper)
    db.session.flush()

    span = 730
    dates, weights = day_weights(span)
    hour_weights = np.array([0.3, 0.2, 0.1, 0.1, 0.1, 0.4, 1, 2, 4, 6, 7, 7, 6, 6, 6, 6, 6, 6, 6, 5, 4, 3, 1.5, 0.7])
    hour_weights = hour_weights / hour_weights.sum()
    city_names = [c for c, _ in CITIES]
    city_probs = np.array([w for _, w in CITIES])
    city_probs = city_probs / city_probs.sum()
    now_naive_limit = now

    total_weight = sum(spec["weight"] for spec, _ in company_rows)
    customer_rows = []
    order_rows = []
    item_rows = []
    unit_sales = {}

    for spec, company in company_rows:
        product_specs = build_products(spec, rng)
        product_objects = []
        for item in product_specs:
            product = Product(company_id=company.id, **item)
            product_objects.append(product)
            db.session.add(product)
        db.session.flush()

        product_count = len(product_objects)
        popularity = 1.0 / np.arange(1, product_count + 1) ** 0.8
        generator.shuffle(popularity)
        amplitude = np.array([CATALOG[p.category][2][0] for p in product_objects])
        phase = np.array([CATALOG[p.category][2][1] for p in product_objects])
        prices = [p.price for p in product_objects]
        costs = [p.cost for p in product_objects]

        n_customers = max(int(customers * spec["weight"] / total_weight), 1)
        n_orders = max(int(orders * spec["weight"] / total_weight), 1)
        customer_ids = next_ids("customers", n_customers)
        activity = generator.lognormal(mean=0.0, sigma=1.1, size=n_customers)
        activity = activity / activity.sum()

        day_index = np.sort(generator.choice(span, size=n_orders, p=weights))
        hour_index = generator.choice(24, size=n_orders, p=hour_weights)
        minute_index = generator.integers(0, 60, size=n_orders)
        stamps = []
        for d, h, m in zip(day_index, hour_index, minute_index):
            stamps.append(dates[int(d)].replace(hour=int(h), minute=int(m)))
        order_order = sorted(range(n_orders), key=lambda i: stamps[i])
        stamps = [stamps[i] for i in order_order]
        day_index = day_index[order_order]

        order_ids = next_ids("orders", n_orders)
        customer_choice = generator.choice(n_customers, size=n_orders, p=activity)
        channel_choice = generator.random(n_orders)
        status_choice = generator.random(n_orders)
        first_order = {}
        weeks = day_index // 7

        for week in np.unique(weeks):
            positions = np.where(weeks == week)[0]
            week_number = (int(week) * 7) % 365 / 7.0
            week_weight = popularity * (1 + amplitude * np.sin(2 * np.pi * (week_number - phase) / 52.0))
            week_weight = np.clip(week_weight, 0.01, None)
            week_weight = week_weight / week_weight.sum()
            for pos in positions:
                lines = 1 + int(generator.poisson(0.8))
                chosen = generator.choice(product_count, size=min(lines, 5), replace=False, p=week_weight)
                created_at = stamps[pos]
                age_days = (now - created_at).days
                channel = "store" if channel_choice[pos] < 0.85 else "pos"
                draw = status_choice[pos]
                if age_days > 14:
                    status = "delivered" if draw < 0.88 else "cancelled"
                else:
                    if draw < 0.12:
                        status = "pending"
                    elif draw < 0.25:
                        status = "paid"
                    elif draw < 0.45:
                        status = "shipped"
                    elif draw < 0.90:
                        status = "delivered"
                    else:
                        status = "cancelled"
                customer_index = int(customer_choice[pos])
                customer_id = customer_ids[customer_index]
                if channel == "pos" and generator.random() < 0.6:
                    customer_id = None
                else:
                    first_order.setdefault(customer_index, created_at)
                total = 0
                order_id = order_ids[pos]
                for product_index in chosen:
                    quantity = int(generator.choice([1, 2, 3, 4, 5], p=[0.6, 0.22, 0.1, 0.05, 0.03]))
                    line_total = prices[product_index] * quantity
                    total += line_total
                    item_rows.append(
                        {
                            "order_id": order_id,
                            "product_id": product_objects[product_index].id,
                            "sku": product_objects[product_index].sku,
                            "product_name": product_objects[product_index].name,
                            "quantity": quantity,
                            "unit_price": prices[product_index],
                            "unit_cost": costs[product_index],
                            "line_total": line_total,
                        }
                    )
                    if status != "cancelled" and age_days <= 56:
                        key = product_objects[product_index].id
                        unit_sales[key] = unit_sales.get(key, 0) + quantity
                order_rows.append(
                    {
                        "id": order_id,
                        "company_id": company.id,
                        "customer_id": customer_id,
                        "number": int(pos) + 1,
                        "status": status,
                        "channel": channel,
                        "total": total,
                        "created_by": None,
                        "created_at": created_at,
                        "updated_at": min(created_at + timedelta(days=2 if status != "pending" else 0), now_naive_limit),
                    }
                )

        for index, customer_id in enumerate(customer_ids):
            first = faker.first_name()
            last = faker.last_name()
            joined = first_order.get(index)
            if joined is None:
                joined = now - timedelta(days=int(generator.integers(1, span)))
            else:
                joined = joined - timedelta(days=int(generator.integers(0, 4)))
            customer_rows.append(
                {
                    "id": customer_id,
                    "company_id": company.id,
                    "first_name": first,
                    "last_name": last,
                    "email": "{}.{}.{}@example.com".format(slugify(first), slugify(last), customer_id),
                    "phone": "3{:09d}".format(int(generator.integers(0, 10**9))),
                    "city": str(generator.choice(city_names, p=city_probs)),
                    "country": "Colombia",
                    "created_at": joined,
                }
            )

        company.order_seq = n_orders

        for product in product_objects:
            weekly = unit_sales.get(product.id, 0) / 8.0
            quantity = int(weekly * float(generator.uniform(0.4, 5.0))) + int(generator.integers(0, 15))
            db.session.add(Inventory(product_id=product.id, company_id=company.id, quantity=quantity))
        db.session.flush()

    order_rows.sort(key=lambda r: (r["company_id"], r["number"]))
    db.session.execute(insert(Customer.__table__), customer_rows)
    db.session.execute(insert(Order.__table__), order_rows)
    db.session.execute(insert(OrderItem.__table__), item_rows)
    for _, company in company_rows:
        db.session.execute(update(Company).where(Company.id == company.id).values(order_seq=company.order_seq))

    log_count = seed_access_logs(rng, owner_emails + ["cliente@novacommerce.local", "admin@novacommerce.local"])
    db.session.commit()

    return {
        "password": password,
        "companies": len(company_rows),
        "customers": len(customer_rows),
        "orders": len(order_rows),
        "items": len(item_rows),
        "access_logs": log_count,
        "accounts": ["admin@novacommerce.local", "cliente@novacommerce.local"] + owner_emails,
    }
