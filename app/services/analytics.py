from sqlalchemy import text

from ..extensions import db


def rows(sql, params):
    result = db.session.execute(text(sql), params)
    return [dict(row._mapping) for row in result]


def kpis(company_id):
    return rows(
        """
        select
            coalesce(sum(f.ingreso) filter (where f.estado <> 'cancelled'), 0) as ingresos,
            coalesce(sum(f.margen) filter (where f.estado <> 'cancelled'), 0) as margen,
            count(distinct f.orden_id) filter (where f.estado <> 'cancelled') as ordenes,
            count(distinct f.cliente_id) filter (where f.estado <> 'cancelled') as clientes,
            coalesce(sum(f.ingreso) filter (where f.estado = 'cancelled'), 0) as cancelado
        from dw.fact_ventas f
        where f.empresa_id = :company_id
        """,
        {"company_id": company_id},
    )[0]


def monthly_sales(company_id):
    return rows(
        """
        select
            t.anio,
            t.mes,
            t.nombre_mes,
            sum(f.ingreso) as ingresos,
            sum(f.margen) as margen,
            count(distinct f.orden_id) as ordenes,
            lag(sum(f.ingreso)) over (order by t.anio, t.mes) as ingresos_previos,
            round(
                100.0 * (sum(f.ingreso) - lag(sum(f.ingreso)) over (order by t.anio, t.mes))
                / nullif(lag(sum(f.ingreso)) over (order by t.anio, t.mes), 0),
                2
            ) as crecimiento_pct
        from dw.fact_ventas f
        join dw.dim_tiempo t on t.tiempo_id = f.tiempo_id
        where f.empresa_id = :company_id and f.estado <> 'cancelled'
        group by t.anio, t.mes, t.nombre_mes
        order by t.anio, t.mes
        """,
        {"company_id": company_id},
    )


def rollup_category(company_id):
    return rows(
        """
        select
            t.anio,
            p.categoria,
            sum(f.ingreso) as ingresos,
            sum(f.cantidad) as unidades,
            grouping(t.anio) as g_anio,
            grouping(p.categoria) as g_categoria
        from dw.fact_ventas f
        join dw.dim_tiempo t on t.tiempo_id = f.tiempo_id
        join dw.dim_producto p on p.producto_sk = f.producto_sk
        where f.empresa_id = :company_id and f.estado <> 'cancelled'
        group by rollup (t.anio, p.categoria)
        order by t.anio nulls last, p.categoria nulls last
        """,
        {"company_id": company_id},
    )


def top_products(company_id, limit=10):
    return rows(
        """
        select * from (
            select
                p.producto_id,
                p.nombre,
                p.categoria,
                sum(f.cantidad) as unidades,
                sum(f.ingreso) as ingresos,
                sum(f.margen) as margen,
                rank() over (order by sum(f.ingreso) desc) as posicion
            from dw.fact_ventas f
            join dw.dim_producto p on p.producto_id = f.producto_id and p.vigente
            where f.empresa_id = :company_id and f.estado <> 'cancelled'
            group by p.producto_id, p.nombre, p.categoria
        ) ranked
        where posicion <= :limit
        order by posicion
        """,
        {"company_id": company_id, "limit": limit},
    )


def abc_analysis(company_id):
    return rows(
        """
        with ventas as (
            select p.producto_id, p.nombre, sum(f.ingreso) as ingresos
            from dw.fact_ventas f
            join dw.dim_producto p on p.producto_id = f.producto_id and p.vigente
            where f.empresa_id = :company_id and f.estado <> 'cancelled'
            group by p.producto_id, p.nombre
        ),
        acumulado as (
            select
                producto_id,
                nombre,
                ingresos,
                sum(ingresos) over (order by ingresos desc, producto_id) / nullif(sum(ingresos) over (), 0) as acumulado
            from ventas
        )
        select
            producto_id,
            nombre,
            ingresos,
            round(100 * acumulado, 2) as acumulado_pct,
            case when acumulado <= 0.80 then 'A' when acumulado <= 0.95 then 'B' else 'C' end as clase
        from acumulado
        order by ingresos desc
        """,
        {"company_id": company_id},
    )


def rfm_segments(company_id):
    return rows(
        """
        with base as (
            select
                f.cliente_id,
                max(t.fecha) as ultima_compra,
                count(distinct f.orden_id) as frecuencia,
                sum(f.ingreso) as monetario
            from dw.fact_ventas f
            join dw.dim_tiempo t on t.tiempo_id = f.tiempo_id
            where f.empresa_id = :company_id and f.estado <> 'cancelled' and f.cliente_id is not null
            group by f.cliente_id
        ),
        puntuado as (
            select
                cliente_id,
                ntile(4) over (order by ultima_compra) as r,
                ntile(4) over (order by frecuencia) as f,
                ntile(4) over (order by monetario) as m,
                monetario
            from base
        )
        select
            case
                when r >= 3 and f >= 3 and m >= 3 then 'Campeones'
                when r >= 3 and f >= 2 then 'Leales'
                when r >= 3 then 'Recientes'
                when f >= 3 and m >= 3 then 'En riesgo de alto valor'
                when r = 1 and f = 1 then 'Perdidos'
                else 'Ocasionales'
            end as segmento,
            count(*) as clientes,
            sum(monetario) as ingresos
        from puntuado
        group by 1
        order by ingresos desc
        """,
        {"company_id": company_id},
    )


def sales_by_weekday(company_id):
    return rows(
        """
        select t.dia_semana, t.nombre_dia, sum(f.ingreso) as ingresos, count(distinct f.orden_id) as ordenes
        from dw.fact_ventas f
        join dw.dim_tiempo t on t.tiempo_id = f.tiempo_id
        where f.empresa_id = :company_id and f.estado <> 'cancelled'
        group by t.dia_semana, t.nombre_dia
        order by t.dia_semana
        """,
        {"company_id": company_id},
    )


def sales_by_channel(company_id):
    return rows(
        """
        select c.nombre as canal, sum(f.ingreso) as ingresos, count(distinct f.orden_id) as ordenes
        from dw.fact_ventas f
        join dw.dim_canal c on c.canal_id = f.canal_id
        where f.empresa_id = :company_id and f.estado <> 'cancelled'
        group by c.nombre
        order by ingresos desc
        """,
        {"company_id": company_id},
    )


def platform_overview():
    return rows(
        """
        select
            e.empresa_id,
            e.nombre,
            coalesce(sum(f.ingreso) filter (where f.estado <> 'cancelled'), 0) as ingresos,
            count(distinct f.orden_id) filter (where f.estado <> 'cancelled') as ordenes,
            count(distinct f.cliente_id) filter (where f.estado <> 'cancelled') as clientes
        from dw.dim_empresa e
        left join dw.fact_ventas f on f.empresa_id = e.empresa_id
        group by e.empresa_id, e.nombre
        order by ingresos desc
        """,
        {},
    )


def warehouse_ready():
    found = db.session.execute(text("select to_regclass('dw.fact_ventas')")).scalar()
    return found is not None


def inventory_status(company_id):
    return rows(
        """
        select producto_id, producto, categoria, cantidad_disponible, punto_reorden, stock_seguridad, eoq, requiere_reposicion
        from dw.v_inventario_actual
        where empresa_id = :company_id
        order by requiere_reposicion desc, cantidad_disponible
        """,
        {"company_id": company_id},
    )
