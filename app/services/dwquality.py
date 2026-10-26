from datetime import datetime, timezone

from sqlalchemy import text

from ..extensions import db

CHECKS = [
    (
        "Filas de hechos igual a items de orden",
        "select count(*) from order_items",
        "select count(*) from dw.fact_ventas",
    ),
    (
        "Ingreso total igual a la suma de lineas operativas",
        "select coalesce(sum(line_total), 0) from order_items",
        "select coalesce(sum(ingreso), 0) from dw.fact_ventas",
    ),
    (
        "Costo total igual a costo unitario por cantidad",
        "select coalesce(sum(unit_cost * quantity), 0) from order_items",
        "select coalesce(sum(costo_total), 0) from dw.fact_ventas",
    ),
    (
        "Unidades vendidas iguales",
        "select coalesce(sum(quantity), 0) from order_items",
        "select coalesce(sum(cantidad), 0) from dw.fact_ventas",
    ),
    (
        "Ordenes distintas iguales",
        "select count(distinct order_id) from order_items",
        "select count(distinct orden_id) from dw.fact_ventas",
    ),
    (
        "Ingreso por empresa reconciliado",
        "select count(*) from (select o.company_id, sum(oi.line_total) v from order_items oi join orders o on o.id = oi.order_id group by o.company_id) a",
        "select count(*) from (select o.company_id, sum(oi.line_total) v from order_items oi join orders o on o.id = oi.order_id group by o.company_id) a join (select empresa_id, sum(ingreso) v from dw.fact_ventas group by empresa_id) b on b.empresa_id = a.company_id and b.v = a.v",
    ),
    (
        "Capa bronce igual a items de orden",
        "select count(*) from order_items",
        "select count(*) from bronze.ventas",
    ),
    (
        "Capa plata mas rechazos igual a bronce",
        "select count(*) from bronze.ventas",
        "select (select count(*) from silver.ventas) + (select count(distinct r.orden_item_id) from silver.rechazos r where not exists (select 1 from silver.ventas v where v.orden_item_id = r.orden_item_id))",
    ),
    (
        "Snapshot de inventario igual a productos con inventario",
        "select count(*) from inventory",
        "select count(*) from dw.fact_inventario_snapshot where tiempo_id = (select max(tiempo_id) from dw.fact_inventario_snapshot)",
    ),
    (
        "Empresas en dimension",
        "select count(*) from companies",
        "select count(*) from dw.dim_empresa",
    ),
    (
        "Productos en dimension",
        "select count(*) from products",
        "select count(*) from dw.dim_producto where vigente",
    ),
    (
        "Clientes en dimension",
        "select count(*) from customers",
        "select count(*) from dw.dim_cliente where vigente",
    ),
    (
        "Clientes con correo cifrado",
        "select count(*) from customers where email is not null",
        "select count(*) from dw.dim_cliente where vigente and email_cifrado is not null",
    ),
]

ZERO_CHECKS = [
    (
        "Hechos duplicados por orden_item_id",
        "select count(*) - count(distinct orden_item_id) from dw.fact_ventas",
    ),
    (
        "Hechos sin fecha en dim_tiempo",
        "select count(*) from dw.fact_ventas f left join dw.dim_tiempo t on t.tiempo_id = f.tiempo_id where t.tiempo_id is null",
    ),
    (
        "Hechos sin empresa en dim_empresa",
        "select count(*) from dw.fact_ventas f left join dw.dim_empresa e on e.empresa_id = f.empresa_id where e.empresa_id is null",
    ),
    (
        "Hechos con producto inexistente",
        "select count(*) from dw.fact_ventas f left join dw.dim_producto p on p.producto_sk = f.producto_sk where f.producto_id is not null and p.producto_sk is null",
    ),
    (
        "Hechos con cliente inexistente",
        "select count(*) from dw.fact_ventas f left join dw.dim_cliente c on c.cliente_sk = f.cliente_sk where f.cliente_id is not null and c.cliente_sk is null",
    ),
    (
        "Productos con mas de una version vigente",
        "select count(*) from (select producto_id from dw.dim_producto where vigente group by producto_id having count(*) > 1) a",
    ),
    (
        "Clientes con mas de una version vigente",
        "select count(*) from (select cliente_id from dw.dim_cliente where vigente group by cliente_id having count(*) > 1) a",
    ),
    (
        "Versiones de producto con intervalos solapados",
        "select count(*) from dw.dim_producto a join dw.dim_producto b on a.producto_id = b.producto_id and a.producto_sk < b.producto_sk and a.fecha_inicio < coalesce(b.fecha_fin, date 'infinity') and b.fecha_inicio < coalesce(a.fecha_fin, date 'infinity')",
    ),
    (
        "Versiones de cliente con intervalos solapados",
        "select count(*) from dw.dim_cliente a join dw.dim_cliente b on a.cliente_id = b.cliente_id and a.cliente_sk < b.cliente_sk and a.fecha_inicio < coalesce(b.fecha_fin, date 'infinity') and b.fecha_inicio < coalesce(a.fecha_fin, date 'infinity')",
    ),
    (
        "Hechos con version de producto posterior a la venta",
        "select count(*) from dw.fact_ventas f join dw.dim_tiempo t on t.tiempo_id = f.tiempo_id join dw.dim_producto p on p.producto_sk = f.producto_sk where t.fecha < p.fecha_inicio",
    ),
    (
        "Hechos con version de cliente posterior a la venta",
        "select count(*) from dw.fact_ventas f join dw.dim_tiempo t on t.tiempo_id = f.tiempo_id join dw.dim_cliente c on c.cliente_sk = f.cliente_sk where t.fecha < c.fecha_inicio",
    ),
    (
        "Cantidades no positivas",
        "select count(*) from dw.fact_ventas where cantidad <= 0",
    ),
    (
        "Margen distinto de ingreso menos costo",
        "select count(*) from dw.fact_ventas where margen <> ingreso - costo_total",
    ),
    (
        "Ingreso distinto de cantidad por precio",
        "select count(*) from dw.fact_ventas where ingreso <> cantidad * precio_unitario",
    ),
    (
        "Valores nulos en columnas obligatorias",
        "select count(*) from dw.fact_ventas where estado is null or ingreso is null or costo_total is null or tiempo_id is null",
    ),
    (
        "Producto de otra empresa en un hecho",
        "select count(*) from dw.fact_ventas f join dw.dim_producto p on p.producto_sk = f.producto_sk where p.empresa_id <> f.empresa_id",
    ),
    (
        "Cliente de otra empresa en un hecho",
        "select count(*) from dw.fact_ventas f join dw.dim_cliente c on c.cliente_sk = f.cliente_sk where c.empresa_id <> f.empresa_id",
    ),
]


def scalar(sql):
    return db.session.scalar(text(sql))


def normalize(value):
    return float(value) if hasattr(value, "quantize") else value


def verify():
    results = []
    for name, operational, warehouse in CHECKS:
        expected = normalize(scalar(operational))
        obtained = normalize(scalar(warehouse))
        results.append({"control": name, "esperado": expected, "obtenido": obtained, "ok": expected == obtained})
    for name, sql in ZERO_CHECKS:
        obtained = normalize(scalar(sql))
        results.append({"control": name, "esperado": 0, "obtenido": obtained, "ok": obtained == 0})
    volumes = {
        table: scalar("select count(*) from dw.{}".format(table))
        for table in ("dim_tiempo", "dim_empresa", "dim_producto", "dim_cliente", "dim_canal", "fact_ventas", "fact_inventario_snapshot")
    }
    volumes.update(
        {
            "bronce_ventas": scalar("select count(*) from bronze.ventas"),
            "plata_ventas": scalar("select count(*) from silver.ventas"),
            "plata_rechazos": scalar("select count(*) from silver.rechazos"),
        }
    )
    last = db.session.execute(
        text("select modo, estado, filas_cargadas, inicio, fin from dw.etl_ejecuciones order by ejecucion_id desc limit 5")
    ).mappings().all()
    audit = db.session.execute(
        text("select tabla, operacion, sum(filas) filas, count(*) eventos from dw.audit_log group by tabla, operacion order by tabla, operacion")
    ).mappings().all()
    return {
        "generado": datetime.now(timezone.utc).isoformat(),
        "aprobados": sum(1 for row in results if row["ok"]),
        "total": len(results),
        "controles": results,
        "volumenes": volumes,
        "ultimas_ejecuciones": [
            {"modo": r["modo"], "estado": r["estado"], "filas": r["filas_cargadas"], "inicio": r["inicio"].isoformat(), "fin": r["fin"].isoformat()}
            for r in last
        ],
        "auditoria": [dict(r) for r in audit],
    }
