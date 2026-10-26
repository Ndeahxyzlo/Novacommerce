import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.extensions import db
from app.services import consultas

from .conftest import create_admin, create_customer_user, create_owner, login, post


def ejecutar_sql(sql, **parametros):
    return db.session.execute(text(sql), parametros)


def fila_tiempo(tiempo_id, fecha, anio, mes):
    ejecutar_sql(
        "insert into dw.dim_tiempo values (:t, :f, :a, 2, :m, 'mes', 1, 1, 1, 'dia', false)",
        t=tiempo_id,
        f=fecha,
        a=anio,
        m=mes,
    )


def producto(producto_id, empresa_id, nombre, categoria, inicio, fin, vigente):
    return ejecutar_sql(
        "insert into dw.dim_producto (producto_id, empresa_id, sku, nombre, categoria, precio_lista, costo, fecha_inicio, fecha_fin, vigente) "
        "values (:p, :e, :s, :n, :c, 100, 60, :i, :f, :v) returning producto_sk",
        p=producto_id,
        e=empresa_id,
        s="SKU-{}".format(producto_id),
        n=nombre,
        c=categoria,
        i=inicio,
        f=fin,
        v=vigente,
    ).scalar()


def venta(item_id, tiempo_id, empresa_id, producto_id, producto_sk, cliente_id, cliente_sk, estado, cantidad, ingreso):
    ejecutar_sql(
        "insert into dw.fact_ventas values (:i, :i, :i, :t, :e, :p, :c, :psk, :csk, 1, :est, :q, 100, 60, :ing, 0, 0)",
        i=item_id,
        t=tiempo_id,
        e=empresa_id,
        p=producto_id,
        c=cliente_id,
        psk=producto_sk,
        csk=cliente_sk,
        est=estado,
        q=cantidad,
        ing=ingreso,
    )


@pytest.fixture()
def bodega(ctx):
    ejecutar_sql("drop materialized view if exists dw.cubo_ventas_mensual")
    ejecutar_sql("insert into dw.dim_empresa values (1, 'Empresa A', 'Bogota', 'Colombia'), (2, 'Empresa B', 'Cali', 'Colombia')")
    ejecutar_sql("insert into dw.dim_canal values (1, 'web', 'Web') on conflict do nothing")
    fila_tiempo(20240531, "2024-05-31", 2024, 5)
    fila_tiempo(20240601, "2024-06-01", 2024, 6)
    fila_tiempo(20250115, "2025-01-15", 2025, 1)
    vieja = producto(10, 1, "Cafe", "Vieja", "1900-01-01", "2024-06-01", False)
    nueva = producto(10, 1, "Cafe", "Nueva", "2024-06-01", None, True)
    bebida = producto(11, 2, "Te", "Bebidas", "1900-01-01", None, True)
    cliente = ejecutar_sql(
        "insert into dw.dim_cliente (cliente_id, empresa_id, nombre, ciudad, pais, fecha_registro, email_cifrado, fecha_inicio, vigente) "
        "values (5, 1, 'Ana', 'Cali', 'Colombia', '2024-01-01', null, '1900-01-01', true) returning cliente_sk"
    ).scalar()
    venta(1, 20240531, 1, 10, vieja, 5, cliente, "paid", 2, 200)
    venta(2, 20240601, 1, 10, nueva, 5, cliente, "paid", 3, 300)
    venta(3, 20250115, 2, 11, bebida, None, None, "paid", 5, 500)
    venta(4, 20250115, 2, 11, bebida, None, None, "cancelled", 9, 9000)
    db.session.commit()
    yield


def sk_vigente(producto_id):
    return db.session.execute(
        text("select producto_sk from dw.dim_producto where producto_id = :p and vigente"), {"p": producto_id}
    ).scalar()


def sin_filtros(**cambios):
    return consultas.normalizar_filtros(**cambios)


def test_rollup_total_es_la_suma_del_detalle(bodega):
    resultado = consultas.ejecutar("rollup", sin_filtros())
    indice = resultado["columnas"].index("ingresos")
    nivel = resultado["columnas"].index("nivel")
    detalle = [fila for fila in resultado["filas"] if fila[nivel] == 0]
    total = [fila for fila in resultado["filas"] if fila[nivel] == 7]
    assert len(total) == 1
    assert sum(fila[indice] for fila in detalle) == total[0][indice] == 1000
    directo = db.session.execute(text("select sum(ingreso) from dw.fact_ventas where estado <> 'cancelled'")).scalar()
    assert total[0][indice] == directo


def test_rollup_subtotal_de_empresa_es_la_suma_de_sus_filas(bodega):
    resultado = consultas.ejecutar("rollup", sin_filtros())
    columnas = resultado["columnas"]
    por_empresa = {}
    subtotales = {}
    for fila in resultado["filas"]:
        datos = dict(zip(columnas, fila))
        if datos["nivel"] == 0:
            por_empresa[datos["empresa"]] = por_empresa.get(datos["empresa"], 0) + datos["ingresos"]
        if datos["nivel"] == 3:
            subtotales[datos["empresa"]] = datos["ingresos"]
    assert por_empresa == subtotales == {"Empresa A": 500, "Empresa B": 500}


def test_scd2_usa_la_version_vigente_en_la_fecha_de_la_venta(bodega):
    resultado = consultas.ejecutar("rollup", sin_filtros(empresa="1"))
    columnas = resultado["columnas"]
    detalle = {}
    for fila in resultado["filas"]:
        datos = dict(zip(columnas, fila))
        if datos["nivel"] == 0:
            detalle[(datos["anio"], datos["categoria"])] = datos["ingresos"]
    assert detalle == {("2024", "Vieja"): 200, ("2024", "Nueva"): 300}


def test_cube_incluye_ciudad_sin_dato_y_total(bodega):
    resultado = consultas.ejecutar("cube", sin_filtros())
    ciudades = {dict(zip(resultado["columnas"], fila))["ciudad"] for fila in resultado["filas"]}
    assert {"Cali", "Sin dato", "Total"} <= ciudades
    total = [fila for fila in resultado["filas"] if fila[resultado["columnas"].index("nivel")] == 7]
    assert total[0][resultado["columnas"].index("ingresos")] == 1000


def test_grouping_sets_total_general(bodega):
    resultado = consultas.ejecutar("grouping_sets", sin_filtros())
    columnas = resultado["columnas"]
    totales = [dict(zip(columnas, fila)) for fila in resultado["filas"] if fila[columnas.index("nivel")] == 31]
    assert len(totales) == 1
    assert totales[0]["ingresos"] == 1000


def test_cubo_molap_se_actualiza_solo_al_refrescar(bodega):
    assert consultas.ultima_actualizacion() is None
    consultas.refrescar_cubo()
    assert consultas.ultima_actualizacion().endswith("UTC")
    resultado = consultas.ejecutar("molap", sin_filtros())
    indice = resultado["columnas"].index("ingresos")
    assert sum(fila[indice] for fila in resultado["filas"]) == 1000
    venta(5, 20250115, 2, 11, sk_vigente(11), None, None, "paid", 1, 70)
    db.session.commit()
    antes = consultas.ejecutar("molap", sin_filtros())
    assert sum(fila[indice] for fila in antes["filas"]) == 1000
    consultas.refrescar_cubo()
    despues = consultas.ejecutar("molap", sin_filtros())
    assert sum(fila[indice] for fila in despues["filas"]) == 1070


def test_detalle_filtra_por_empresa_busqueda_y_fechas(bodega):
    todas = consultas.ejecutar("detalle", sin_filtros())
    assert todas["total"] == 3
    empresa_dos = consultas.ejecutar("detalle", sin_filtros(empresa="2"))
    assert empresa_dos["total"] == 1
    assert empresa_dos["filas"][0][empresa_dos["columnas"].index("empresa")] == "Empresa B"
    por_cliente = consultas.ejecutar("detalle", sin_filtros(q="ana"))
    assert por_cliente["total"] == 2
    por_producto = consultas.ejecutar("detalle", sin_filtros(q="te"))
    assert por_producto["total"] == 1
    por_fecha = consultas.ejecutar("detalle", sin_filtros(desde="2024-06-01", hasta="2024-12-31"))
    assert por_fecha["total"] == 1


def test_detalle_pagina_los_resultados(bodega):
    for numero in range(100, 130):
        venta(numero, 20250115, 2, 11, sk_vigente(11), None, None, "paid", 1, 10)
    db.session.commit()
    primera = consultas.ejecutar("detalle", sin_filtros(), pagina=1)
    segunda = consultas.ejecutar("detalle", sin_filtros(), pagina=2)
    assert len(primera["filas"]) == consultas.POR_PAGINA
    assert primera["total"] == 33
    assert primera["filas"] != segunda["filas"]


def test_inyeccion_sql_en_la_busqueda_no_tiene_efecto(bodega):
    ataque = "'; drop table dw.fact_ventas; --"
    resultado = consultas.ejecutar("detalle", sin_filtros(q=ataque))
    assert resultado["total"] == 0
    assert db.session.execute(text("select count(*) from dw.fact_ventas")).scalar() == 4
    comodin = consultas.ejecutar("detalle", sin_filtros(q="%"))
    assert comodin["total"] == 0
    assert "drop table" not in resultado["sql"]


def test_filtros_invalidos_se_ignoran(bodega):
    filtros = sin_filtros(empresa="abc", desde="no-es-fecha", hasta="2024-99-99")
    assert filtros["empresa"] is None and filtros["desde"] is None and filtros["hasta"] is None
    assert consultas.ejecutar("detalle", filtros)["total"] == 3


def test_las_consultas_corren_en_transaccion_de_solo_lectura(bodega, monkeypatch):
    monkeypatch.setitem(consultas.CONSULTAS, "peligrosa", {"titulo": "x", "tipo": "cubo", "sql": "delete from dw.fact_ventas"})
    with pytest.raises(DBAPIError):
        consultas.ejecutar("peligrosa", sin_filtros())
    db.session.rollback()
    assert db.session.execute(text("select count(*) from dw.fact_ventas")).scalar() == 4


def test_las_consultas_no_exponen_el_correo_cifrado(bodega):
    for clave in consultas.CONSULTAS:
        assert "email_cifrado" not in consultas.CONSULTAS[clave]["sql"]


def test_acceso_solo_para_administrador(client, ctx, bodega):
    create_owner("Empresa Uno", "uno@example.com")
    create_customer_user("ana@example.com")
    anonimo = client.get("/admin/consultas")
    assert anonimo.status_code == 302 and "/auth/login" in anonimo.headers["Location"]
    login(client, "uno@example.com")
    assert client.get("/admin/consultas").status_code == 403
    assert client.get("/admin/decisiones").status_code == 403
    client.get("/auth/logout")
    otro = client.application.test_client()
    login(otro, "ana@example.com")
    assert otro.get("/admin/consultas").status_code == 403
    assert otro.post("/admin/consultas/refrescar").status_code in (400, 403)


def test_administrador_ve_consultas_decisiones_y_exporta_csv(client, ctx, bodega):
    create_admin()
    login(client, "admin@example.com")
    for clave in consultas.CONSULTAS:
        respuesta = client.get("/admin/consultas?consulta={}".format(clave))
        assert respuesta.status_code == 200
        assert "SQL ejecutado" in respuesta.get_data(as_text=True)
    assert client.get("/admin/decisiones").status_code == 200
    assert client.get("/admin/decisiones?presupuesto=10&personal=50&respuesta=10").status_code == 200
    archivo = client.get("/admin/consultas?consulta=rollup&formato=csv")
    assert archivo.status_code == 200
    assert archivo.mimetype == "text/csv"
    assert archivo.get_data(as_text=True).splitlines()[0].startswith("empresa,anio,categoria")
    assert client.get("/admin/consultas?consulta=%27%3B+drop+table").status_code == 200


def test_refrescar_cubo_exige_csrf_y_funciona_con_token(client, ctx, bodega, app):
    create_admin()
    login(client, "admin@example.com")
    sin_token = client.post("/admin/consultas/refrescar")
    assert sin_token.status_code in (302, 400)
    assert consultas.ultima_actualizacion() is None
    respuesta = post(client, "/admin/consultas/refrescar", token_from="/admin/consultas?consulta=molap")
    assert respuesta.status_code == 302
    assert consultas.ultima_actualizacion() is not None
