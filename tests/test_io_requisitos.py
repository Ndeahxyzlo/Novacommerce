import numpy as np
from scipy.optimize import linprog

from app.services import io_extra, optimization


def problema_aleatorio(generador):
    variables = int(generador.integers(2, 6))
    restricciones = int(generador.integers(2, 5))
    c = generador.uniform(1, 10, variables)
    a = generador.uniform(0.5, 6, (restricciones, variables))
    b = generador.uniform(10, 40, restricciones)
    return c, a, b


def resolver_con_linprog(c, a, b):
    return linprog(-np.array(c), A_ub=a, b_ub=b, bounds=[(0, None)] * len(c), method="highs")


def test_simplex_coincide_con_linprog_en_problemas_aleatorios():
    generador = np.random.default_rng(2026)
    for _ in range(25):
        c, a, b = problema_aleatorio(generador)
        propio = optimization.simplex_max(c, a, b)
        referencia = resolver_con_linprog(c, a, b)
        assert propio["status"] == "optimal"
        assert abs(propio["objective"] - (-referencia.fun)) < 1e-6
        assert np.allclose(propio["duals"], -referencia.ineqlin.marginals, atol=1e-6)


def test_sensibilidad_de_recursos_dentro_del_rango():
    generador = np.random.default_rng(7)
    comprobados = 0
    for _ in range(15):
        c, a, b = problema_aleatorio(generador)
        base = optimization.sensibilidad(c, a, b)
        objetivo = base["optimo"]["objective"]
        for recurso in base["recursos"]:
            if recurso["maximo"] is None:
                continue
            nuevo = recurso["valor"] + (recurso["maximo"] - recurso["valor"]) * 0.5
            b_nuevo = b.copy()
            b_nuevo[recurso["indice"]] = nuevo
            resultado = optimization.simplex_max(c, a, b_nuevo)
            esperado = objetivo + recurso["precio_sombra"] * (nuevo - recurso["valor"])
            assert abs(resultado["objective"] - esperado) < 1e-6
            comprobados += 1
    assert comprobados > 0


def test_sensibilidad_de_recursos_fuera_del_rango_cambia_el_precio_sombra():
    generador = np.random.default_rng(11)
    comprobados = 0
    for _ in range(15):
        c, a, b = problema_aleatorio(generador)
        base = optimization.sensibilidad(c, a, b)
        for recurso in base["recursos"]:
            if recurso["maximo"] is None or recurso["precio_sombra"] < 1e-9:
                continue
            nuevo = recurso["maximo"] + 1.0
            b_nuevo = b.copy()
            b_nuevo[recurso["indice"]] = nuevo
            resultado = optimization.simplex_max(c, a, b_nuevo)
            esperado = base["optimo"]["objective"] + recurso["precio_sombra"] * (nuevo - recurso["valor"])
            assert abs(resultado["objective"] - esperado) > 1e-6
            comprobados += 1
    assert comprobados > 0


def test_sensibilidad_de_coeficientes_dentro_y_fuera_del_rango():
    generador = np.random.default_rng(13)
    dentro = 0
    fuera = 0
    for _ in range(20):
        c, a, b = problema_aleatorio(generador)
        base = optimization.sensibilidad(c, a, b)
        x_base = base["optimo"]["x"]
        for item in base["objetivo"]:
            j = item["indice"]
            if item["maximo"] is not None:
                c_dentro = c.copy()
                c_dentro[j] = item["valor"] + (item["maximo"] - item["valor"]) * 0.5
                assert np.allclose(optimization.simplex_max(c_dentro, a, b)["x"], x_base, atol=1e-6)
                dentro += 1
                if not item["basica"]:
                    c_fuera = c.copy()
                    c_fuera[j] = item["maximo"] + 1.0
                    assert not np.allclose(optimization.simplex_max(c_fuera, a, b)["x"], x_base, atol=1e-6)
                    fuera += 1
            if item["minimo"] is not None and item["basica"]:
                c_fuera = c.copy()
                c_fuera[j] = item["minimo"] - 1.0
                assert not np.allclose(optimization.simplex_max(c_fuera, a, b)["x"], x_base, atol=1e-6)
                fuera += 1
    assert dentro > 0 and fuera > 0


def test_plan_de_controles_respeta_restricciones_y_coincide_con_linprog():
    plan = io_extra.plan_de_controles(30.0, 120.0, 25.0)
    c, a, b = io_extra.sistema_de_controles(30.0, 120.0, 25.0)
    referencia = resolver_con_linprog(c, np.array(a), np.array(b))
    assert abs(plan["reduccion_total"] - (-referencia.fun)) < 1e-6
    for control in plan["controles"]:
        assert -1e-9 <= control["fraccion"] <= 1 + 1e-9
    for recurso in plan["recursos"]:
        assert recurso["holgura"] >= -1e-6
    assert len(plan["recursos"]) == 3


def test_reduccion_de_cada_control_sale_del_registro_de_riesgos():
    reduccion = io_extra.reduccion_por_control()
    esperado = sum(f["inherente"] - f["residual"] for f in io_extra.registro_de_riesgos())
    assert sum(reduccion.values()) == esperado
    for fila in io_extra.registro_de_riesgos():
        assert fila["inherente"] == fila["probabilidad"] * fila["impacto"]
        assert fila["supera_umbral"] == (fila["inherente"] >= io_extra.UMBRAL_RIESGO)
        assert fila["fuente"]


def test_montecarlo_es_reproducible_con_la_misma_semilla():
    primero = io_extra.montecarlo(semilla=99)
    segundo = io_extra.montecarlo(semilla=99)
    otro = io_extra.montecarlo(semilla=100)
    assert primero == segundo
    assert primero["probabilidad_cabe"] != otro["probabilidad_cabe"]
    assert primero["corridas"] == 10000
    assert primero["resiliencia_p5"] <= primero["resiliencia_p50"] <= primero["resiliencia_p95"]
    assert 0.0 <= primero["probabilidad_cabe"] <= 1.0


def grafo_aleatorio(generador):
    nodos = ["s", "a", "b", "c", "d", "t"]
    aristas = []
    for origen in range(len(nodos) - 1):
        for destino in range(origen + 1, len(nodos)):
            if generador.random() < 0.6:
                aristas.append(
                    {
                        "origen": nodos[origen],
                        "destino": nodos[destino],
                        "capacidad": int(generador.integers(1, 8)),
                        "costo": int(generador.integers(0, 6)),
                    }
                )
    return nodos, aristas


def matriz_de_conservacion(nodos, aristas):
    indice = {nodo: posicion for posicion, nodo in enumerate(nodos)}
    matriz = np.zeros((len(nodos), len(aristas)))
    for columna, arista in enumerate(aristas):
        matriz[indice[arista["origen"]], columna] = 1
        matriz[indice[arista["destino"]], columna] = -1
    return matriz, indice


def test_flujo_maximo_coincide_con_linprog():
    generador = np.random.default_rng(5)
    comprobados = 0
    for _ in range(15):
        nodos, aristas = grafo_aleatorio(generador)
        if not aristas:
            continue
        propio, _ = io_extra.flujo_maximo(aristas, nodos, "s", "t")
        matriz, indice = matriz_de_conservacion(nodos, aristas)
        interior = [i for nodo, i in indice.items() if nodo not in ("s", "t")]
        referencia = linprog(
            -matriz[indice["s"]],
            A_eq=matriz[interior],
            b_eq=np.zeros(len(interior)),
            bounds=[(0, arista["capacidad"]) for arista in aristas],
            method="highs",
        )
        assert abs(propio - (-referencia.fun)) < 1e-6
        comprobados += 1
    assert comprobados > 0


def test_flujo_de_costo_minimo_coincide_con_linprog():
    generador = np.random.default_rng(8)
    comprobados = 0
    for _ in range(20):
        nodos, aristas = grafo_aleatorio(generador)
        if not aristas:
            continue
        maximo, _ = io_extra.flujo_maximo(aristas, nodos, "s", "t")
        if maximo == 0:
            continue
        requerido = max(1, maximo // 2 + 1)
        enviado, costo, _ = io_extra.flujo_costo_minimo(aristas, nodos, "s", "t", requerido)
        assert enviado == requerido
        matriz, indice = matriz_de_conservacion(nodos, aristas)
        demanda = np.zeros(len(nodos))
        demanda[indice["s"]] = requerido
        demanda[indice["t"]] = -requerido
        referencia = linprog(
            [arista["costo"] for arista in aristas],
            A_eq=matriz,
            b_eq=demanda,
            bounds=[(0, arista["capacidad"]) for arista in aristas],
            method="highs",
        )
        assert abs(costo - referencia.fun) < 1e-6
        comprobados += 1
    assert comprobados > 0


def test_flujo_de_la_orden_con_y_sin_rutas_alternas():
    analisis = io_extra.analisis_de_flujo()
    assert analisis["maximo"] >= analisis["maximo_controlado"]
    assert analisis["enviado"] == analisis["requerido"]
    assert analisis["enviado_controlado"] <= analisis["maximo_controlado"]
    assert analisis["flujo_sin_control"] > 0
