import csv
import io
import time
from datetime import date, datetime, timezone

from sqlalchemy import text

from ..extensions import db

NOTA_MOLAP = (
    "PostgreSQL no tiene un motor MOLAP nativo. La vista materializada dw.cubo_ventas_mensual es una "
    "aproximación: guarda los agregados ya calculados y se actualiza con REFRESH MATERIALIZED VIEW CONCURRENTLY."
)

VISTA_CUBO = "dw.cubo_ventas_mensual"
POR_PAGINA = 20
MAXIMO_FILAS = 1000
MAXIMO_CSV = 50000
TIEMPO_MAXIMO_MS = 20000

UNION_PRODUCTO = """join dw.dim_producto p on p.producto_id = f.producto_id
    and p.fecha_inicio <= t.fecha and (p.fecha_fin is null or t.fecha < p.fecha_fin)"""

UNION_CLIENTE = """left join dw.dim_cliente c on c.cliente_id = f.cliente_id
    and c.fecha_inicio <= t.fecha and (c.fecha_fin is null or t.fecha < c.fecha_fin)"""

ORIGEN_CUBO = """from dw.fact_ventas f
join dw.dim_tiempo t on t.tiempo_id = f.tiempo_id
join dw.dim_empresa e on e.empresa_id = f.empresa_id
{producto}
{cliente}
where f.estado <> 'cancelled'
  and (cast(:empresa as integer) is null or f.empresa_id = :empresa)""".format(
    producto=UNION_PRODUCTO, cliente=UNION_CLIENTE
)

FILTROS_DETALLE = """
  and (cast(:q as text) is null or p.nombre ilike '%' || :q || '%' or c.nombre ilike '%' || :q || '%')
  and (cast(:desde as date) is null or t.fecha >= :desde)
  and (cast(:hasta as date) is null or t.fecha <= :hasta)"""


def etiqueta(expresion):
    return "case when grouping({e}) = 1 then 'Total' else coalesce(cast({e} as text), 'Sin dato') end".format(
        e=expresion
    )


def consulta_de_cubo(dimensiones, agrupacion):
    columnas = ",\n    ".join("{} as {}".format(etiqueta(expr), alias) for expr, alias in dimensiones)
    nivel = "grouping({})".format(", ".join(expr for expr, _ in dimensiones))
    return """select
    {columnas},
    sum(f.ingreso) as ingresos,
    sum(f.cantidad) as unidades,
    {nivel} as nivel
{origen}
group by {agrupacion}
order by nivel desc, 1, 2
limit {limite}""".format(
        columnas=columnas, nivel=nivel, origen=ORIGEN_CUBO, agrupacion=agrupacion, limite=MAXIMO_FILAS
    )


SQL_ROLLUP = consulta_de_cubo(
    [("e.nombre", "empresa"), ("t.anio", "anio"), ("p.categoria", "categoria")],
    "rollup (e.nombre, t.anio, p.categoria)",
)

SQL_CUBE = consulta_de_cubo(
    [("t.anio", "anio"), ("p.categoria", "categoria"), ("c.ciudad", "ciudad")],
    "cube (t.anio, p.categoria, c.ciudad)",
)

SQL_GROUPING_SETS = consulta_de_cubo(
    [("t.anio", "anio"), ("p.categoria", "categoria"), ("p.nombre", "producto"), ("c.ciudad", "ciudad"), ("e.nombre", "empresa")],
    "grouping sets ((t.anio, p.categoria), (p.nombre), (c.ciudad), (e.nombre), ())",
)

SQL_MOLAP = """select anio, mes, categoria, sum(ingresos) as ingresos, sum(unidades) as unidades
from dw.cubo_ventas_mensual
where cast(:empresa as integer) is null or empresa_id = :empresa
group by anio, mes, categoria
order by anio, mes, categoria
limit {limite}""".format(limite=MAXIMO_FILAS)

SQL_DETALLE_COLUMNAS = """select
    t.fecha,
    e.nombre as empresa,
    f.orden_numero as orden,
    p.nombre as producto,
    p.categoria,
    c.nombre as cliente,
    c.ciudad,
    f.cantidad,
    f.ingreso"""

SQL_DETALLE = """{columnas}
{origen}{filtros}
order by t.fecha desc, f.orden_item_id desc
limit :limite offset :desplazamiento""".format(
    columnas=SQL_DETALLE_COLUMNAS, origen=ORIGEN_CUBO, filtros=FILTROS_DETALLE
)

SQL_DETALLE_TOTAL = "select count(*)\n{origen}{filtros}".format(origen=ORIGEN_CUBO, filtros=FILTROS_DETALLE)

CONSULTAS = {
    "rollup": {"titulo": "ROLLUP por empresa, año y categoría", "tipo": "cubo", "sql": SQL_ROLLUP},
    "cube": {"titulo": "CUBE por año, categoría y ciudad", "tipo": "cubo", "sql": SQL_CUBE},
    "grouping_sets": {"titulo": "GROUPING SETS por varias dimensiones", "tipo": "cubo", "sql": SQL_GROUPING_SETS},
    "molap": {"titulo": "Cubo precalculado (MOLAP simulado)", "tipo": "molap", "sql": SQL_MOLAP},
    "detalle": {"titulo": "Consulta de ventas con filtros", "tipo": "detalle", "sql": SQL_DETALLE},
}

SQL_CREAR_VISTA = """create materialized view if not exists dw.cubo_ventas_mensual as
select
    f.empresa_id,
    t.anio,
    t.mes,
    p.categoria,
    sum(f.ingreso) as ingresos,
    sum(f.cantidad) as unidades,
    count(*) as lineas
from dw.fact_ventas f
join dw.dim_tiempo t on t.tiempo_id = f.tiempo_id
{producto}
where f.estado <> 'cancelled'
group by f.empresa_id, t.anio, t.mes, p.categoria
with data""".format(producto=UNION_PRODUCTO)

SQL_INDICE_VISTA = (
    "create unique index if not exists ux_cubo_ventas_mensual "
    "on dw.cubo_ventas_mensual (empresa_id, anio, mes, categoria)"
)


def escapar_like(valor):
    return valor.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def convertir_fecha(valor):
    try:
        return date.fromisoformat(valor) if valor else None
    except ValueError:
        return None


def convertir_entero(valor):
    try:
        return int(valor) if valor not in (None, "") else None
    except ValueError:
        return None


def normalizar_filtros(empresa=None, q=None, desde=None, hasta=None):
    busqueda = (q or "").strip()[:80]
    return {
        "empresa": convertir_entero(empresa),
        "q": escapar_like(busqueda) if busqueda else None,
        "desde": convertir_fecha(desde),
        "hasta": convertir_fecha(hasta),
    }


def cubo_existe():
    return db.session.execute(text("select to_regclass('dw.cubo_ventas_mensual')")).scalar() is not None


def asegurar_cubo():
    if cubo_existe():
        return
    db.session.execute(text(SQL_CREAR_VISTA))
    db.session.execute(text(SQL_INDICE_VISTA))
    marcar_actualizacion()
    db.session.commit()


def marcar_actualizacion():
    ahora = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    db.session.execute(text("comment on materialized view dw.cubo_ventas_mensual is '{}'".format(ahora)))


def refrescar_cubo():
    asegurar_cubo()
    db.session.execute(text("refresh materialized view concurrently dw.cubo_ventas_mensual"))
    marcar_actualizacion()
    db.session.commit()


def ultima_actualizacion():
    if not cubo_existe():
        return None
    return db.session.execute(text("select obj_description('dw.cubo_ventas_mensual'::regclass)")).scalar()


def ejecutar(clave, filtros, pagina=1, completo=False):
    consulta = CONSULTAS[clave]
    parametros = {"empresa": filtros["empresa"]}
    total = None
    if consulta["tipo"] == "detalle":
        parametros.update({"q": filtros["q"], "desde": filtros["desde"], "hasta": filtros["hasta"]})
        parametros["limite"] = MAXIMO_CSV if completo else POR_PAGINA
        parametros["desplazamiento"] = 0 if completo else (max(pagina, 1) - 1) * POR_PAGINA
    if consulta["tipo"] == "molap":
        asegurar_cubo()
    with db.engine.connect() as conexion:
        conexion.execute(text("set transaction read only"))
        conexion.execute(text("set local statement_timeout = {}".format(TIEMPO_MAXIMO_MS)))
        inicio = time.perf_counter()
        resultado = conexion.execute(text(consulta["sql"]), parametros)
        columnas = list(resultado.keys())
        filas = [list(fila) for fila in resultado]
        milisegundos = (time.perf_counter() - inicio) * 1000
        if consulta["tipo"] == "detalle":
            conteo = {clave_: valor for clave_, valor in parametros.items() if clave_ in ("empresa", "q", "desde", "hasta")}
            total = conexion.execute(text(SQL_DETALLE_TOTAL), conteo).scalar()
        conexion.rollback()
    return {
        "clave": clave,
        "titulo": consulta["titulo"],
        "sql": consulta["sql"],
        "parametros": {k: v for k, v in parametros.items() if k not in ("limite", "desplazamiento")},
        "columnas": columnas,
        "filas": filas,
        "milisegundos": milisegundos,
        "total": total,
        "pagina": pagina,
        "por_pagina": POR_PAGINA,
    }


def a_csv(columnas, filas):
    salida = io.StringIO()
    escritor = csv.writer(salida)
    escritor.writerow(columnas)
    escritor.writerows(filas)
    return salida.getvalue()
