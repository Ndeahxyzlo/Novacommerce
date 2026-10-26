from datetime import datetime, timezone
from pathlib import Path

from flask import current_app
from sqlalchemy import text

from ..extensions import db

WAREHOUSE_DIR = Path(__file__).resolve().parent.parent.parent / "warehouse"
SCHEMA_FILES = (WAREHOUSE_DIR / "medallion.sql", WAREHOUSE_DIR / "schema.sql")
PROCESS = "fact_ventas"

LOAD_TIME = text(
    """
    insert into dw.dim_tiempo (tiempo_id, fecha, anio, trimestre, mes, nombre_mes, semana, dia, dia_semana, nombre_dia, es_fin_semana)
    select
        to_char(d, 'YYYYMMDD')::int,
        d::date,
        extract(year from d)::smallint,
        extract(quarter from d)::smallint,
        extract(month from d)::smallint,
        (array['Enero','Febrero','Marzo','Abril','Mayo','Junio','Julio','Agosto','Septiembre','Octubre','Noviembre','Diciembre'])[extract(month from d)::int],
        extract(week from d)::smallint,
        extract(day from d)::smallint,
        extract(isodow from d)::smallint,
        (array['Lunes','Martes','Miércoles','Jueves','Viernes','Sábado','Domingo'])[extract(isodow from d)::int],
        extract(isodow from d) >= 6
    from generate_series(
        coalesce((select min(created_at)::date from orders), current_date) - 7,
        greatest(coalesce((select max(created_at)::date from orders), current_date), current_date) + 90,
        interval '1 day'
    ) as d
    on conflict (tiempo_id) do nothing
    """
)

BRONZE_COMPANIES = text(
    """
    insert into bronze.empresas (id, name, city, country, extraido_en)
    select id, name, city, country, :lote from companies
    on conflict (id) do update
    set name = excluded.name, city = excluded.city, country = excluded.country, extraido_en = excluded.extraido_en
    """
)

BRONZE_PRODUCTS = text(
    """
    insert into bronze.productos (id, company_id, sku, name, category, price, cost, active, extraido_en)
    select id, company_id, sku, name, category, price, cost, active, :lote from products
    on conflict (id) do update
    set company_id = excluded.company_id, sku = excluded.sku, name = excluded.name, category = excluded.category,
        price = excluded.price, cost = excluded.cost, active = excluded.active, extraido_en = excluded.extraido_en
    """
)

BRONZE_CUSTOMERS = text(
    """
    insert into bronze.clientes (id, company_id, first_name, last_name, city, country, created_at, email_cifrado, extraido_en)
    select c.id, c.company_id, c.first_name, c.last_name, c.city, c.country, c.created_at,
        case when c.email is not null
            and not exists (select 1 from dw.dim_cliente d where d.cliente_id = c.id and d.email_cifrado is not null)
            then pgp_sym_encrypt(c.email, :clave) end,
        :lote
    from customers c
    on conflict (id) do update
    set company_id = excluded.company_id, first_name = excluded.first_name, last_name = excluded.last_name,
        city = excluded.city, country = excluded.country, created_at = excluded.created_at,
        email_cifrado = excluded.email_cifrado, extraido_en = excluded.extraido_en
    """
)

BRONZE_SALES = text(
    """
    insert into bronze.ventas (
        item_id, order_id, number, company_id, customer_id, product_id, status, channel, created_at, updated_at,
        quantity, unit_price, unit_cost, line_total, extraido_en
    )
    select
        oi.id, o.id, o.number, o.company_id, o.customer_id, oi.product_id, o.status, o.channel, o.created_at, o.updated_at,
        oi.quantity, oi.unit_price, oi.unit_cost, oi.line_total, :lote
    from order_items oi
    join orders o on o.id = oi.order_id
    where o.updated_at >= :watermark
    on conflict (item_id) do update
    set order_id = excluded.order_id, number = excluded.number, company_id = excluded.company_id,
        customer_id = excluded.customer_id, product_id = excluded.product_id, status = excluded.status,
        channel = excluded.channel, created_at = excluded.created_at, updated_at = excluded.updated_at,
        quantity = excluded.quantity, unit_price = excluded.unit_price, unit_cost = excluded.unit_cost,
        line_total = excluded.line_total, extraido_en = excluded.extraido_en
    """
)

BRONZE_INVENTORY = text(
    """
    insert into bronze.inventario (product_id, company_id, quantity, reorder_point, safety_stock, eoq, extraido_en)
    select product_id, company_id, quantity, reorder_point, safety_stock, eoq, :lote from inventory
    on conflict (product_id) do update
    set company_id = excluded.company_id, quantity = excluded.quantity, reorder_point = excluded.reorder_point,
        safety_stock = excluded.safety_stock, eoq = excluded.eoq, extraido_en = excluded.extraido_en
    """
)

SILVER_RESET = (
    "truncate silver.empresas, silver.productos, silver.clientes, silver.inventario",
)

SILVER_COMPANIES = text(
    """
    insert into silver.empresas (empresa_id, nombre, ciudad, pais)
    select id, trim(name), nullif(trim(city), ''), nullif(trim(country), '') from bronze.empresas
    """
)

SILVER_PRODUCTS = text(
    """
    insert into silver.productos (producto_id, empresa_id, sku, nombre, categoria, precio_lista, costo)
    select id, company_id, upper(trim(sku)), trim(name), coalesce(nullif(trim(category), ''), 'General'), price, cost
    from bronze.productos
    where price >= 0 and cost >= 0 and company_id is not null
    """
)

SILVER_CUSTOMERS = text(
    """
    insert into silver.clientes (cliente_id, empresa_id, nombre, ciudad, pais, fecha_registro, email_cifrado)
    select id, company_id, trim(coalesce(first_name, '') || ' ' || coalesce(last_name, '')),
        initcap(nullif(trim(city), '')), nullif(trim(country), ''), created_at::date, email_cifrado
    from bronze.clientes
    where company_id is not null
    """
)

SILVER_INVENTORY = text(
    """
    insert into silver.inventario (producto_id, empresa_id, cantidad, punto_reorden, stock_seguridad, eoq)
    select product_id, company_id, quantity, reorder_point, safety_stock, eoq from bronze.inventario
    where quantity >= 0
    """
)

SILVER_REJECTS = text(
    """
    insert into silver.rechazos (orden_item_id, motivo)
    select b.item_id,
        case
            when b.quantity is null or b.quantity <= 0 then 'cantidad_no_positiva'
            when b.unit_price is null or b.unit_price < 0 then 'precio_invalido'
            when b.unit_cost is null or b.unit_cost < 0 then 'costo_invalido'
            when lower(trim(b.status)) not in ('pending', 'paid', 'shipped', 'delivered', 'cancelled') then 'estado_desconocido'
            when not exists (select 1 from dw.dim_canal c where c.codigo = lower(trim(b.channel))) then 'canal_desconocido'
            else 'ingreso_inconsistente'
        end
    from bronze.ventas b
    where b.extraido_en = :lote and not (
        b.quantity > 0 and b.unit_price >= 0 and b.unit_cost >= 0
        and lower(trim(b.status)) in ('pending', 'paid', 'shipped', 'delivered', 'cancelled')
        and exists (select 1 from dw.dim_canal c where c.codigo = lower(trim(b.channel)))
        and b.line_total = b.quantity * b.unit_price
    )
    on conflict (orden_item_id, motivo) do nothing
    """
)

SILVER_SALES = text(
    """
    insert into silver.ventas (
        orden_item_id, orden_id, orden_numero, fecha, empresa_id, producto_id, cliente_id, canal_codigo, estado,
        cantidad, precio_unitario, costo_unitario, ingreso, costo_total, margen, procesado_en
    )
    select
        b.item_id, b.order_id, b.number, b.created_at::date, b.company_id, b.product_id, b.customer_id,
        lower(trim(b.channel)), lower(trim(b.status)), b.quantity, b.unit_price, b.unit_cost, b.line_total,
        b.unit_cost * b.quantity, b.line_total - b.unit_cost * b.quantity, :lote
    from bronze.ventas b
    where b.extraido_en = :lote
        and b.quantity > 0 and b.unit_price >= 0 and b.unit_cost >= 0
        and lower(trim(b.status)) in ('pending', 'paid', 'shipped', 'delivered', 'cancelled')
        and exists (select 1 from dw.dim_canal c where c.codigo = lower(trim(b.channel)))
        and b.line_total = b.quantity * b.unit_price
    on conflict (orden_item_id) do update
    set orden_id = excluded.orden_id, orden_numero = excluded.orden_numero, fecha = excluded.fecha,
        empresa_id = excluded.empresa_id, producto_id = excluded.producto_id, cliente_id = excluded.cliente_id,
        canal_codigo = excluded.canal_codigo, estado = excluded.estado, cantidad = excluded.cantidad,
        precio_unitario = excluded.precio_unitario, costo_unitario = excluded.costo_unitario,
        ingreso = excluded.ingreso, costo_total = excluded.costo_total, margen = excluded.margen,
        procesado_en = excluded.procesado_en
    """
)

GOLD_COMPANIES = text(
    """
    insert into dw.dim_empresa (empresa_id, nombre, ciudad, pais)
    select empresa_id, nombre, ciudad, pais from silver.empresas
    on conflict (empresa_id) do update
    set nombre = excluded.nombre, ciudad = excluded.ciudad, pais = excluded.pais
    """
)

CLOSE_PRODUCTS = text(
    """
    update dw.dim_producto d
    set fecha_fin = current_date, vigente = false
    from silver.productos s
    where d.producto_id = s.producto_id and d.vigente
        and (d.empresa_id, d.sku, d.nombre, d.categoria, d.precio_lista, d.costo)
            is distinct from (s.empresa_id, s.sku, s.nombre, s.categoria, s.precio_lista, s.costo)
    """
)

OPEN_PRODUCTS = text(
    """
    insert into dw.dim_producto (producto_id, empresa_id, sku, nombre, categoria, precio_lista, costo, fecha_inicio, fecha_fin, vigente)
    select s.producto_id, s.empresa_id, s.sku, s.nombre, s.categoria, s.precio_lista, s.costo,
        case when exists (select 1 from dw.dim_producto x where x.producto_id = s.producto_id)
            then current_date else date '1900-01-01' end,
        null, true
    from silver.productos s
    where not exists (select 1 from dw.dim_producto d where d.producto_id = s.producto_id and d.vigente)
        and exists (select 1 from dw.dim_empresa e where e.empresa_id = s.empresa_id)
    """
)

CLOSE_CUSTOMERS = text(
    """
    update dw.dim_cliente d
    set fecha_fin = current_date, vigente = false
    from silver.clientes s
    where d.cliente_id = s.cliente_id and d.vigente
        and (d.empresa_id, d.nombre, d.ciudad, d.pais) is distinct from (s.empresa_id, s.nombre, s.ciudad, s.pais)
    """
)

OPEN_CUSTOMERS = text(
    """
    insert into dw.dim_cliente (cliente_id, empresa_id, nombre, ciudad, pais, fecha_registro, email_cifrado, fecha_inicio, fecha_fin, vigente)
    select s.cliente_id, s.empresa_id, s.nombre, s.ciudad, s.pais, s.fecha_registro,
        coalesce(s.email_cifrado, (
            select x.email_cifrado from dw.dim_cliente x
            where x.cliente_id = s.cliente_id and x.email_cifrado is not null
            order by x.cliente_sk desc limit 1
        )),
        case when exists (select 1 from dw.dim_cliente x where x.cliente_id = s.cliente_id)
            then current_date else date '1900-01-01' end,
        null, true
    from silver.clientes s
    where not exists (select 1 from dw.dim_cliente d where d.cliente_id = s.cliente_id and d.vigente)
        and exists (select 1 from dw.dim_empresa e where e.empresa_id = s.empresa_id)
    """
)

FILL_EMAILS = text(
    """
    update dw.dim_cliente d
    set email_cifrado = s.email_cifrado
    from silver.clientes s
    where d.cliente_id = s.cliente_id and d.vigente and d.email_cifrado is null and s.email_cifrado is not null
    """
)

GOLD_FACTS = text(
    """
    insert into dw.fact_ventas (
        orden_item_id, orden_id, orden_numero, tiempo_id, empresa_id, producto_id, cliente_id, producto_sk, cliente_sk,
        canal_id, estado, cantidad, precio_unitario, costo_unitario, ingreso, costo_total, margen
    )
    select
        v.orden_item_id, v.orden_id, v.orden_numero, to_char(v.fecha, 'YYYYMMDD')::int, v.empresa_id,
        case when p.producto_sk is not null then v.producto_id end,
        case when c.cliente_sk is not null then v.cliente_id end,
        p.producto_sk, c.cliente_sk,
        canal.canal_id, v.estado, v.cantidad, v.precio_unitario, v.costo_unitario, v.ingreso, v.costo_total, v.margen
    from silver.ventas v
    join dw.dim_canal canal on canal.codigo = v.canal_codigo
    left join lateral (
        select dp.producto_sk from dw.dim_producto dp
        where dp.producto_id = v.producto_id and dp.fecha_inicio <= v.fecha
        order by dp.fecha_inicio desc, dp.producto_sk desc limit 1
    ) p on true
    left join lateral (
        select dc.cliente_sk from dw.dim_cliente dc
        where dc.cliente_id = v.cliente_id and dc.fecha_inicio <= v.fecha
        order by dc.fecha_inicio desc, dc.cliente_sk desc limit 1
    ) c on true
    where v.procesado_en = :lote
    on conflict (orden_item_id) do update
    set estado = excluded.estado,
        cantidad = excluded.cantidad,
        precio_unitario = excluded.precio_unitario,
        costo_unitario = excluded.costo_unitario,
        ingreso = excluded.ingreso,
        costo_total = excluded.costo_total,
        margen = excluded.margen,
        producto_id = coalesce(dw.fact_ventas.producto_id, excluded.producto_id),
        cliente_id = coalesce(dw.fact_ventas.cliente_id, excluded.cliente_id),
        producto_sk = coalesce(dw.fact_ventas.producto_sk, excluded.producto_sk),
        cliente_sk = coalesce(dw.fact_ventas.cliente_sk, excluded.cliente_sk)
    """
)

GOLD_INVENTORY = text(
    """
    insert into dw.fact_inventario_snapshot (
        tiempo_id, producto_id, producto_sk, empresa_id, cantidad_disponible, punto_reorden, stock_seguridad, eoq, requiere_reposicion
    )
    select to_char(current_date, 'YYYYMMDD')::int, i.producto_id, p.producto_sk, i.empresa_id, i.cantidad,
        i.punto_reorden, i.stock_seguridad, i.eoq, i.punto_reorden > 0 and i.cantidad <= i.punto_reorden
    from silver.inventario i
    join dw.dim_producto p on p.producto_id = i.producto_id and p.vigente
    on conflict (tiempo_id, producto_id) do update
    set producto_sk = excluded.producto_sk, empresa_id = excluded.empresa_id,
        cantidad_disponible = excluded.cantidad_disponible, punto_reorden = excluded.punto_reorden,
        stock_seguridad = excluded.stock_seguridad, eoq = excluded.eoq,
        requiere_reposicion = excluded.requiere_reposicion
    """
)


def is_legacy_layout():
    return bool(
        db.session.scalar(
            text(
                """
                select exists (select 1 from information_schema.tables where table_schema = 'dw' and table_name = 'dim_producto')
                and not exists (
                    select 1 from information_schema.columns
                    where table_schema = 'dw' and table_name = 'dim_producto' and column_name = 'producto_sk'
                )
                """
            )
        )
    )


def ensure_schema():
    if is_legacy_layout():
        db.session.execute(text("drop schema dw cascade"))
        db.session.commit()
    for path in SCHEMA_FILES:
        db.session.execute(text(path.read_text(encoding="utf-8")))
    db.session.commit()


def log_run(mode, status, rows, started, message=None):
    db.session.execute(
        text(
            """
            insert into dw.etl_ejecuciones (proceso, modo, estado, filas_cargadas, inicio, mensaje)
            values (:p, :m, :s, :n, :i, :msg)
            """
        ),
        {"p": PROCESS, "m": mode, "s": status, "n": rows, "i": started, "msg": message},
    )
    db.session.commit()


def run_etl(full=False):
    started = db.session.scalar(text("select now()"))
    db.session.rollback()
    mode = "completa" if full else "incremental"
    try:
        result = execute(full)
    except Exception as error:
        db.session.rollback()
        log_run(mode, "error", 0, started, str(error)[:500])
        raise
    log_run(mode, "ok", result["rows"], started)
    return result


def load_bronze(lote, watermark):
    db.session.execute(BRONZE_COMPANIES, {"lote": lote})
    db.session.execute(BRONZE_PRODUCTS, {"lote": lote})
    db.session.execute(BRONZE_CUSTOMERS, {"lote": lote, "clave": current_app.config["DW_ENCRYPTION_KEY"]})
    db.session.execute(BRONZE_SALES, {"lote": lote, "watermark": watermark})
    db.session.execute(BRONZE_INVENTORY, {"lote": lote})


def load_silver(lote):
    for statement in SILVER_RESET:
        db.session.execute(text(statement))
    db.session.execute(SILVER_COMPANIES)
    db.session.execute(SILVER_PRODUCTS)
    db.session.execute(SILVER_CUSTOMERS)
    db.session.execute(SILVER_INVENTORY)
    db.session.execute(SILVER_REJECTS, {"lote": lote})
    db.session.execute(SILVER_SALES, {"lote": lote})


def load_gold(lote):
    db.session.execute(LOAD_TIME)
    db.session.execute(GOLD_COMPANIES)
    closed_products = db.session.execute(CLOSE_PRODUCTS).rowcount or 0
    db.session.execute(OPEN_PRODUCTS)
    closed_customers = db.session.execute(CLOSE_CUSTOMERS).rowcount or 0
    db.session.execute(OPEN_CUSTOMERS)
    db.session.execute(FILL_EMAILS)
    facts = db.session.execute(GOLD_FACTS, {"lote": lote})
    snapshot = db.session.execute(GOLD_INVENTORY)
    return {
        "rows": facts.rowcount if facts.rowcount is not None else 0,
        "inventory_rows": snapshot.rowcount if snapshot.rowcount is not None else 0,
        "product_versions": closed_products,
        "customer_versions": closed_customers,
    }


def execute(full):
    ensure_schema()
    lote = datetime.now(timezone.utc)

    if full:
        db.session.execute(text("truncate bronze.ventas, silver.ventas, silver.rechazos"))
        db.session.execute(text("delete from dw.fact_ventas"))
        db.session.execute(text("delete from dw.etl_control where proceso = :p"), {"p": PROCESS})

    watermark = db.session.scalar(
        text("select ultima_marca from dw.etl_control where proceso = :p"), {"p": PROCESS}
    )
    if watermark is None:
        watermark = db.session.scalar(text("select timestamptz '1970-01-01 00:00:00+00'"))

    new_mark = db.session.scalar(text("select coalesce(max(updated_at), :w) from orders"), {"w": watermark})
    load_bronze(lote, watermark)
    load_silver(lote)
    result = load_gold(lote)

    db.session.execute(
        text(
            """
            insert into dw.etl_control (proceso, ultima_marca, filas_cargadas, ejecutado_en)
            values (:p, :m, :n, now())
            on conflict (proceso) do update
            set ultima_marca = excluded.ultima_marca,
                filas_cargadas = dw.etl_control.filas_cargadas + excluded.filas_cargadas,
                ejecutado_en = now()
            """
        ),
        {"p": PROCESS, "m": new_mark, "n": result["rows"]},
    )
    db.session.commit()
    result["watermark"] = new_mark.isoformat() if new_mark else None
    return result
