create schema if not exists bronze;
create schema if not exists silver;

create table if not exists bronze.empresas (
    id integer primary key,
    name varchar(150),
    city varchar(80),
    country varchar(80),
    extraido_en timestamptz not null
);

create table if not exists bronze.productos (
    id integer primary key,
    company_id integer,
    sku varchar(60),
    name varchar(200),
    category varchar(80),
    price numeric(12, 2),
    cost numeric(12, 2),
    active boolean,
    extraido_en timestamptz not null
);

create table if not exists bronze.clientes (
    id integer primary key,
    company_id integer,
    first_name varchar(80),
    last_name varchar(80),
    city varchar(80),
    country varchar(80),
    created_at timestamptz,
    email_cifrado bytea,
    extraido_en timestamptz not null
);

create table if not exists bronze.ventas (
    item_id bigint primary key,
    order_id integer not null,
    number integer,
    company_id integer,
    customer_id integer,
    product_id integer,
    status varchar(20),
    channel varchar(20),
    created_at timestamptz,
    updated_at timestamptz,
    quantity integer,
    unit_price numeric(12, 2),
    unit_cost numeric(12, 2),
    line_total numeric(14, 2),
    extraido_en timestamptz not null
);

create table if not exists bronze.inventario (
    product_id integer primary key,
    company_id integer,
    quantity integer,
    reorder_point integer,
    safety_stock integer,
    eoq integer,
    extraido_en timestamptz not null
);

create index if not exists ix_bronze_ventas_extraido on bronze.ventas (extraido_en);

create table if not exists silver.empresas (
    empresa_id integer primary key,
    nombre varchar(150) not null,
    ciudad varchar(80),
    pais varchar(80)
);

create table if not exists silver.productos (
    producto_id integer primary key,
    empresa_id integer not null,
    sku varchar(60) not null,
    nombre varchar(200) not null,
    categoria varchar(80) not null,
    precio_lista numeric(12, 2) not null,
    costo numeric(12, 2) not null
);

create table if not exists silver.clientes (
    cliente_id integer primary key,
    empresa_id integer not null,
    nombre varchar(170) not null,
    ciudad varchar(80),
    pais varchar(80),
    fecha_registro date not null,
    email_cifrado bytea
);

create table if not exists silver.ventas (
    orden_item_id bigint primary key,
    orden_id integer not null,
    orden_numero integer not null,
    fecha date not null,
    empresa_id integer not null,
    producto_id integer,
    cliente_id integer,
    canal_codigo varchar(20) not null,
    estado varchar(20) not null,
    cantidad integer not null,
    precio_unitario numeric(12, 2) not null,
    costo_unitario numeric(12, 2) not null,
    ingreso numeric(14, 2) not null,
    costo_total numeric(14, 2) not null,
    margen numeric(14, 2) not null,
    procesado_en timestamptz not null
);

create index if not exists ix_silver_ventas_procesado on silver.ventas (procesado_en);

create table if not exists silver.inventario (
    producto_id integer primary key,
    empresa_id integer not null,
    cantidad integer not null,
    punto_reorden integer not null,
    stock_seguridad integer not null,
    eoq integer not null
);

create table if not exists silver.rechazos (
    rechazo_id bigserial primary key,
    orden_item_id bigint not null,
    motivo varchar(60) not null,
    detectado_en timestamptz not null default now(),
    unique (orden_item_id, motivo)
);
