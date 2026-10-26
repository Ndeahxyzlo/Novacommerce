create extension if not exists pgcrypto;

create schema if not exists dw;

create table if not exists dw.dim_tiempo (
    tiempo_id integer primary key,
    fecha date not null unique,
    anio smallint not null,
    trimestre smallint not null,
    mes smallint not null,
    nombre_mes varchar(12) not null,
    semana smallint not null,
    dia smallint not null,
    dia_semana smallint not null,
    nombre_dia varchar(12) not null,
    es_fin_semana boolean not null
);

create table if not exists dw.dim_empresa (
    empresa_id integer primary key,
    nombre varchar(150) not null,
    ciudad varchar(80),
    pais varchar(80)
);

create table if not exists dw.dim_producto (
    producto_sk bigserial primary key,
    producto_id integer not null,
    empresa_id integer not null references dw.dim_empresa (empresa_id),
    sku varchar(60) not null,
    nombre varchar(200) not null,
    categoria varchar(80) not null,
    precio_lista numeric(12, 2) not null,
    costo numeric(12, 2) not null,
    fecha_inicio date not null,
    fecha_fin date,
    vigente boolean not null default true,
    check (fecha_fin is null or fecha_fin >= fecha_inicio)
);

create table if not exists dw.dim_cliente (
    cliente_sk bigserial primary key,
    cliente_id integer not null,
    empresa_id integer not null references dw.dim_empresa (empresa_id),
    nombre varchar(170) not null,
    ciudad varchar(80),
    pais varchar(80),
    fecha_registro date not null,
    email_cifrado bytea,
    fecha_inicio date not null,
    fecha_fin date,
    vigente boolean not null default true,
    check (fecha_fin is null or fecha_fin >= fecha_inicio)
);

create unique index if not exists ux_dim_producto_vigente on dw.dim_producto (producto_id) where vigente;
create unique index if not exists ux_dim_cliente_vigente on dw.dim_cliente (cliente_id) where vigente;
create index if not exists ix_dim_producto_version on dw.dim_producto (producto_id, fecha_inicio);
create index if not exists ix_dim_cliente_version on dw.dim_cliente (cliente_id, fecha_inicio);

create table if not exists dw.dim_canal (
    canal_id smallint primary key,
    codigo varchar(20) not null unique,
    nombre varchar(40) not null
);

create table if not exists dw.fact_ventas (
    orden_item_id bigint primary key,
    orden_id integer not null,
    orden_numero integer not null,
    tiempo_id integer not null references dw.dim_tiempo (tiempo_id),
    empresa_id integer not null references dw.dim_empresa (empresa_id),
    producto_id integer,
    cliente_id integer,
    producto_sk bigint references dw.dim_producto (producto_sk),
    cliente_sk bigint references dw.dim_cliente (cliente_sk),
    canal_id smallint not null references dw.dim_canal (canal_id),
    estado varchar(20) not null,
    cantidad integer not null,
    precio_unitario numeric(12, 2) not null,
    costo_unitario numeric(12, 2) not null,
    ingreso numeric(14, 2) not null,
    costo_total numeric(14, 2) not null,
    margen numeric(14, 2) not null
);

create index if not exists ix_fact_ventas_tiempo on dw.fact_ventas (tiempo_id);
create index if not exists ix_fact_ventas_empresa_tiempo on dw.fact_ventas (empresa_id, tiempo_id);
create index if not exists ix_fact_ventas_producto on dw.fact_ventas (producto_id);
create index if not exists ix_fact_ventas_cliente on dw.fact_ventas (cliente_id);
create index if not exists ix_fact_ventas_producto_sk on dw.fact_ventas (producto_sk);
create index if not exists ix_fact_ventas_cliente_sk on dw.fact_ventas (cliente_sk);
create index if not exists ix_fact_ventas_orden on dw.fact_ventas (orden_id);
create index if not exists ix_dim_producto_empresa on dw.dim_producto (empresa_id, categoria);
create index if not exists ix_dim_cliente_empresa on dw.dim_cliente (empresa_id);

create table if not exists dw.fact_inventario_snapshot (
    tiempo_id integer not null references dw.dim_tiempo (tiempo_id),
    producto_id integer not null,
    producto_sk bigint not null references dw.dim_producto (producto_sk),
    empresa_id integer not null references dw.dim_empresa (empresa_id),
    cantidad_disponible integer not null,
    punto_reorden integer not null,
    stock_seguridad integer not null,
    eoq integer not null,
    requiere_reposicion boolean not null,
    primary key (tiempo_id, producto_id)
);

create index if not exists ix_fact_inventario_empresa on dw.fact_inventario_snapshot (empresa_id, tiempo_id);

create table if not exists dw.etl_control (
    proceso varchar(60) primary key,
    ultima_marca timestamptz not null,
    filas_cargadas bigint not null default 0,
    ejecutado_en timestamptz not null default now()
);

insert into dw.dim_canal (canal_id, codigo, nombre)
values (1, 'store', 'Tienda en línea'), (2, 'pos', 'Venta directa')
on conflict (canal_id) do nothing;

create table if not exists dw.etl_ejecuciones (
    ejecucion_id bigserial primary key,
    proceso varchar(60) not null,
    modo varchar(12) not null,
    estado varchar(12) not null,
    filas_cargadas bigint not null default 0,
    inicio timestamptz not null,
    fin timestamptz not null default now(),
    mensaje text
);

create table if not exists dw.audit_log (
    audit_id bigserial primary key,
    tabla varchar(60) not null,
    operacion varchar(10) not null,
    filas bigint not null,
    usuario_sesion text not null default session_user,
    usuario_actual text not null default current_user,
    aplicacion text not null default coalesce(current_setting('application_name', true), ''),
    ocurrio_en timestamptz not null default now()
);

create index if not exists ix_audit_log_fecha on dw.audit_log (ocurrio_en);
create index if not exists ix_audit_log_tabla on dw.audit_log (tabla, ocurrio_en);

create or replace function dw.fn_auditar() returns trigger
language plpgsql security definer set search_path = dw, pg_temp as $fn$
declare
    total bigint;
begin
    if tg_op = 'DELETE' then
        select count(*) into total from filas_viejas;
    else
        select count(*) into total from filas_nuevas;
    end if;
    if total > 0 then
        insert into dw.audit_log (tabla, operacion, filas) values (tg_table_name, tg_op, total);
    end if;
    return null;
end
$fn$;

create or replace function dw.fn_proteger_auditoria() returns trigger
language plpgsql as $fn$
begin
    raise exception 'dw.audit_log es de solo insercion';
end
$fn$;

drop trigger if exists tr_audit_log_inmutable on dw.audit_log;
create trigger tr_audit_log_inmutable before update or delete on dw.audit_log
for each row execute function dw.fn_proteger_auditoria();

do $do$
declare
    t text;
begin
    foreach t in array array['fact_ventas', 'fact_inventario_snapshot', 'dim_tiempo', 'dim_empresa', 'dim_producto', 'dim_cliente', 'dim_canal']
    loop
        execute format('drop trigger if exists tr_audit_ins on dw.%I', t);
        execute format('drop trigger if exists tr_audit_upd on dw.%I', t);
        execute format('drop trigger if exists tr_audit_del on dw.%I', t);
        execute format('create trigger tr_audit_ins after insert on dw.%I referencing new table as filas_nuevas for each statement execute function dw.fn_auditar()', t);
        execute format('create trigger tr_audit_upd after update on dw.%I referencing new table as filas_nuevas for each statement execute function dw.fn_auditar()', t);
        execute format('create trigger tr_audit_del after delete on dw.%I referencing old table as filas_viejas for each statement execute function dw.fn_auditar()', t);
    end loop;
end
$do$;

create or replace function dw.revelar_email(p_cliente integer, p_clave text) returns text
language sql security definer set search_path = dw, public, pg_temp as $fn$
    select pgp_sym_decrypt(email_cifrado, p_clave) from dw.dim_cliente where cliente_id = p_cliente and vigente
$fn$;

revoke all on function dw.revelar_email(integer, text) from public;
revoke all on function dw.fn_auditar() from public;

create or replace view dw.v_ventas_detalle as
select
    f.orden_item_id,
    f.orden_id,
    f.orden_numero,
    t.fecha,
    t.anio,
    t.trimestre,
    t.mes,
    t.nombre_mes,
    t.nombre_dia,
    t.es_fin_semana,
    e.empresa_id,
    e.nombre as empresa,
    e.ciudad as empresa_ciudad,
    p.producto_id,
    p.sku,
    p.nombre as producto,
    p.categoria,
    c.cliente_id,
    left(c.nombre, 1) || '***' as cliente_anonimo,
    c.ciudad as cliente_ciudad,
    ch.codigo as canal_codigo,
    ch.nombre as canal,
    f.estado,
    f.cantidad,
    f.precio_unitario,
    f.costo_unitario,
    f.ingreso,
    f.costo_total,
    f.margen
from dw.fact_ventas f
join dw.dim_tiempo t on t.tiempo_id = f.tiempo_id
join dw.dim_empresa e on e.empresa_id = f.empresa_id
join dw.dim_canal ch on ch.canal_id = f.canal_id
left join dw.dim_producto p on p.producto_sk = f.producto_sk
left join dw.dim_cliente c on c.cliente_sk = f.cliente_sk;

create or replace view dw.v_ventas_mensual as
select
    e.empresa_id,
    e.nombre as empresa,
    t.anio,
    t.mes,
    make_date(t.anio, t.mes, 1) as periodo,
    count(distinct f.orden_id) as ordenes,
    sum(f.cantidad) as unidades,
    sum(f.ingreso) as ingresos,
    sum(f.margen) as margen,
    round(100 * sum(f.margen) / nullif(sum(f.ingreso), 0), 2) as margen_pct
from dw.fact_ventas f
join dw.dim_tiempo t on t.tiempo_id = f.tiempo_id
join dw.dim_empresa e on e.empresa_id = f.empresa_id
where f.estado <> 'cancelled'
group by e.empresa_id, e.nombre, t.anio, t.mes;

create or replace view dw.v_ventas_categoria as
select
    e.empresa_id,
    e.nombre as empresa,
    p.categoria,
    count(distinct f.orden_id) as ordenes,
    sum(f.cantidad) as unidades,
    sum(f.ingreso) as ingresos,
    sum(f.margen) as margen
from dw.fact_ventas f
join dw.dim_empresa e on e.empresa_id = f.empresa_id
join dw.dim_producto p on p.producto_sk = f.producto_sk
where f.estado <> 'cancelled'
group by e.empresa_id, e.nombre, p.categoria;

create or replace view dw.v_ventas_canal as
select
    e.empresa_id,
    e.nombre as empresa,
    ch.nombre as canal,
    count(distinct f.orden_id) as ordenes,
    sum(f.ingreso) as ingresos,
    sum(f.margen) as margen
from dw.fact_ventas f
join dw.dim_empresa e on e.empresa_id = f.empresa_id
join dw.dim_canal ch on ch.canal_id = f.canal_id
where f.estado <> 'cancelled'
group by e.empresa_id, e.nombre, ch.nombre;

create or replace view dw.v_top_productos as
select
    empresa_id,
    empresa,
    producto_id,
    producto,
    categoria,
    unidades,
    ingresos,
    margen,
    rank() over (partition by empresa_id order by ingresos desc) as posicion
from (
    select
        e.empresa_id,
        e.nombre as empresa,
        p.producto_id,
        p.nombre as producto,
        p.categoria,
        sum(f.cantidad) as unidades,
        sum(f.ingreso) as ingresos,
        sum(f.margen) as margen
    from dw.fact_ventas f
    join dw.dim_empresa e on e.empresa_id = f.empresa_id
    join dw.dim_producto p on p.producto_id = f.producto_id and p.vigente
    where f.estado <> 'cancelled'
    group by e.empresa_id, e.nombre, p.producto_id, p.nombre, p.categoria
) base;

create or replace view dw.v_clientes_rfm as
with base as (
    select
        f.empresa_id,
        f.cliente_id,
        max(t.fecha) as ultima_compra,
        count(distinct f.orden_id) as frecuencia,
        sum(f.ingreso) as monto
    from dw.fact_ventas f
    join dw.dim_tiempo t on t.tiempo_id = f.tiempo_id
    where f.estado <> 'cancelled' and f.cliente_id is not null
    group by f.empresa_id, f.cliente_id
),
ref as (
    select max(t.fecha) as fecha_ref from dw.fact_ventas f join dw.dim_tiempo t on t.tiempo_id = f.tiempo_id
)
select
    b.empresa_id,
    b.cliente_id,
    (ref.fecha_ref - b.ultima_compra) as recencia_dias,
    b.frecuencia,
    b.monto,
    ntile(5) over (partition by b.empresa_id order by ref.fecha_ref - b.ultima_compra desc) as r,
    ntile(5) over (partition by b.empresa_id order by b.frecuencia) as f,
    ntile(5) over (partition by b.empresa_id order by b.monto) as m
from base b cross join ref;

create or replace view dw.v_inventario_actual as
select
    s.empresa_id,
    p.producto_id,
    p.sku,
    p.nombre as producto,
    p.categoria,
    t.fecha,
    s.cantidad_disponible,
    s.punto_reorden,
    s.stock_seguridad,
    s.eoq,
    s.requiere_reposicion
from dw.fact_inventario_snapshot s
join dw.dim_tiempo t on t.tiempo_id = s.tiempo_id
join dw.dim_producto p on p.producto_sk = s.producto_sk
where s.tiempo_id = (select max(tiempo_id) from dw.fact_inventario_snapshot);

create or replace view dw.v_producto_historial as
select
    p.producto_id,
    p.empresa_id,
    p.sku,
    p.nombre,
    p.categoria,
    p.precio_lista,
    p.costo,
    p.fecha_inicio,
    p.fecha_fin,
    p.vigente
from dw.dim_producto p;

do $do$
begin
    if exists (select 1 from pg_roles where rolname = 'dw_reader') then
        grant usage on schema dw to dw_reader;
        grant select on dw.v_ventas_detalle, dw.v_ventas_mensual, dw.v_ventas_categoria,
            dw.v_ventas_canal, dw.v_top_productos, dw.v_clientes_rfm, dw.v_inventario_actual,
            dw.v_producto_historial to dw_reader;
    end if;
    if exists (select 1 from pg_roles where rolname = 'dw_etl') then
        grant usage on schema dw to dw_etl;
        grant select, insert, update, delete on all tables in schema dw to dw_etl;
        revoke update, delete, truncate on dw.audit_log from dw_etl;
        grant usage, select on all sequences in schema dw to dw_etl;
        grant usage on schema bronze, silver to dw_etl;
        grant select, insert, update, delete, truncate on all tables in schema bronze to dw_etl;
        grant select, insert, update, delete, truncate on all tables in schema silver to dw_etl;
        grant usage, select on all sequences in schema silver to dw_etl;
    end if;
    if exists (select 1 from pg_roles where rolname = 'dw_auditor') then
        grant usage on schema dw to dw_auditor;
        grant select on dw.audit_log, dw.etl_ejecuciones, dw.etl_control to dw_auditor;
        grant execute on function dw.revelar_email(integer, text) to dw_auditor;
    end if;
end
$do$;
