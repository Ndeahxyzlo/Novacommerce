from collections import deque

import numpy as np

from . import optimization, threats

SUPUESTO = "supuesto de demostración"
UMBRAL_RIESGO = 12
SEMILLA = 42
CORRIDAS = 10000

CONTROLES = [
    {"id": "mfa", "nombre": "Autenticación multifactor (MFA)", "costo": 8.0, "horas_personal": 20.0, "horas_respuesta": 4.0},
    {"id": "waf", "nombre": "Cortafuegos de aplicación web (WAF)", "costo": 15.0, "horas_personal": 30.0, "horas_respuesta": 6.0},
    {"id": "respaldos", "nombre": "Respaldos automáticos", "costo": 10.0, "horas_personal": 25.0, "horas_respuesta": 10.0},
    {"id": "monitoreo", "nombre": "Monitoreo y alertas", "costo": 12.0, "horas_personal": 40.0, "horas_respuesta": 12.0},
    {"id": "capacitacion", "nombre": "Capacitación antiphishing", "costo": 4.0, "horas_personal": 30.0, "horas_respuesta": 2.0},
    {"id": "codigo", "nombre": "Revisión de código", "costo": 6.0, "horas_personal": 60.0, "horas_respuesta": 5.0},
]

VULNERABILIDADES = [
    {"id": "V1", "nombre": "Relleno de credenciales", "probabilidad": 4, "impacto": 5, "control": "mfa", "probabilidad_residual": 2, "fuente": SUPUESTO},
    {"id": "V2", "nombre": "Fuerza bruta contra el inicio de sesión", "probabilidad": 4, "impacto": 3, "control": "monitoreo", "probabilidad_residual": 1, "fuente": "bloqueo verificado en tests/test_auth_security.py:102; valores: " + SUPUESTO},
    {"id": "V3", "nombre": "Inyección y XSS en la tienda", "probabilidad": 3, "impacto": 5, "control": "waf", "probabilidad_residual": 2, "fuente": "cabeceras verificadas en tests/test_auth_security.py:184; valores: " + SUPUESTO},
    {"id": "V4", "nombre": "Ransomware", "probabilidad": 3, "impacto": 5, "control": "respaldos", "probabilidad_residual": 1, "fuente": SUPUESTO},
    {"id": "V5", "nombre": "Phishing a usuarios", "probabilidad": 4, "impacto": 4, "control": "capacitacion", "probabilidad_residual": 2, "fuente": SUPUESTO},
    {"id": "V6", "nombre": "Fuga de datos entre empresas", "probabilidad": 2, "impacto": 5, "control": "codigo", "probabilidad_residual": 1, "fuente": "aislamiento verificado en tests/test_tenancy_store.py:22; valores: " + SUPUESTO},
    {"id": "V7", "nombre": "Fraude en pagos", "probabilidad": 3, "impacto": 4, "control": "monitoreo", "probabilidad_residual": 2, "fuente": SUPUESTO},
]

ESTADOS_ORDEN = "app/services/orders.py:17"

NODOS_FLUJO = ["creacion", "antifraude", "aprobacion_pago", "pago", "aprobacion_despacho", "envio", "entrega"]

ARISTAS_FLUJO = [
    {"origen": "creacion", "destino": "antifraude", "capacidad": 10, "costo": 1, "control": True},
    {"origen": "antifraude", "destino": "aprobacion_pago", "capacidad": 9, "costo": 2, "control": True},
    {"origen": "aprobacion_pago", "destino": "pago", "capacidad": 8, "costo": 3, "control": True},
    {"origen": "creacion", "destino": "pago", "capacidad": 4, "costo": 1, "control": False},
    {"origen": "pago", "destino": "aprobacion_despacho", "capacidad": 8, "costo": 3, "control": True},
    {"origen": "aprobacion_despacho", "destino": "envio", "capacidad": 7, "costo": 2, "control": True},
    {"origen": "pago", "destino": "envio", "capacidad": 3, "costo": 1, "control": False},
    {"origen": "envio", "destino": "entrega", "capacidad": 10, "costo": 1, "control": True},
]

FLUJO_REQUERIDO = 9


def registro_de_riesgos():
    filas = []
    for item in VULNERABILIDADES:
        inherente = item["probabilidad"] * item["impacto"]
        residual = item["probabilidad_residual"] * item["impacto"]
        filas.append(
            dict(
                item,
                inherente=inherente,
                residual=residual,
                supera_umbral=inherente >= UMBRAL_RIESGO,
                residual_supera_umbral=residual >= UMBRAL_RIESGO,
            )
        )
    return filas


def reduccion_por_control():
    reduccion = {control["id"]: 0 for control in CONTROLES}
    for fila in registro_de_riesgos():
        reduccion[fila["control"]] += fila["inherente"] - fila["residual"]
    return reduccion


def sistema_de_controles(presupuesto, horas_personal, horas_respuesta):
    reduccion = reduccion_por_control()
    tamano = len(CONTROLES)
    c = [reduccion[control["id"]] for control in CONTROLES]
    a = [
        [control["costo"] for control in CONTROLES],
        [control["horas_personal"] for control in CONTROLES],
        [control["horas_respuesta"] for control in CONTROLES],
    ]
    a.extend(np.eye(tamano).tolist())
    b = [presupuesto, horas_personal, horas_respuesta] + [1.0] * tamano
    return c, a, b


def plan_de_controles(presupuesto=30.0, horas_personal=120.0, horas_respuesta=25.0):
    c, a, b = sistema_de_controles(presupuesto, horas_personal, horas_respuesta)
    sens = optimization.sensibilidad(c, a, b)
    optimo = sens["optimo"]
    x = np.clip(optimo["x"], 0.0, 1.0)
    nombres = ["Presupuesto (millones COP)", "Horas de personal", "Horas de respuesta"]
    recursos = []
    for indice, nombre in enumerate(nombres):
        usado = float(np.array(a[indice]) @ x)
        recursos.append(
            dict(
                sens["recursos"][indice],
                nombre=nombre,
                usado=usado,
                holgura=float(b[indice] - usado),
            )
        )
    controles = []
    for posicion, control in enumerate(CONTROLES):
        controles.append(
            dict(control, reduccion=c[posicion], fraccion=float(x[posicion]), sens=sens["objetivo"][posicion])
        )
    riesgo_total = sum(fila["inherente"] for fila in registro_de_riesgos())
    return {
        "controles": controles,
        "recursos": recursos,
        "reduccion_total": float(optimo["objective"]),
        "riesgo_inherente_total": riesgo_total,
        "presupuesto": presupuesto,
        "horas_personal": horas_personal,
        "horas_respuesta": horas_respuesta,
        "fuente": SUPUESTO,
    }


SUPUESTOS_MONTECARLO = [
    {"variable": "Horas de servidor por simulación", "distribucion": "triangular", "minimo": 0.8, "maximo": 1.4, "fuente": SUPUESTO},
    {"variable": "Horas de analista por simulación", "distribucion": "triangular", "minimo": 0.8, "maximo": 1.4, "fuente": SUPUESTO},
    {"variable": "Puntos por simulación", "distribucion": "triangular", "minimo": 0.7, "maximo": 1.1, "fuente": SUPUESTO},
]


def montecarlo(modo=threats.MODE_EXTENDED, corridas=CORRIDAS, semilla=SEMILLA):
    plan = threats.threat_plan(modo)
    if plan["status"] != "ok":
        return None
    escenarios = plan["scenarios"]
    cantidades = np.array([item["quantity"] for item in escenarios], dtype=float)
    generador = np.random.default_rng(semilla)
    forma = (corridas, len(escenarios))

    def triangular(clave, bajo, alto):
        base = np.array([item[clave] for item in escenarios], dtype=float)
        return generador.triangular(bajo * base, base, alto * base, size=forma)

    servidores = triangular("servers", 0.8, 1.4)
    analistas = triangular("analysts", 0.8, 1.4)
    puntos = triangular("points", 0.7, 1.1)
    uso_servidores = servidores @ cantidades
    uso_analistas = analistas @ cantidades
    cabe = (uso_servidores <= plan["servers"]) & (uso_analistas <= plan["analysts"])
    resiliencia = puntos @ cantidades
    p5, p50, p95 = np.percentile(resiliencia, [5, 50, 95])
    return {
        "corridas": corridas,
        "semilla": semilla,
        "modo": modo,
        "plan_optimo": plan["totals"]["points"],
        "horas_servidores": plan["servers"],
        "horas_analistas": plan["analysts"],
        "probabilidad_cabe": float(cabe.mean()),
        "resiliencia_p5": float(p5),
        "resiliencia_p50": float(p50),
        "resiliencia_p95": float(p95),
        "supuestos": SUPUESTOS_MONTECARLO,
    }


def construir_grafo(aristas, nodos):
    indice = {nodo: posicion for posicion, nodo in enumerate(nodos)}
    grafo = [[] for _ in nodos]
    referencias = []
    for arista in aristas:
        u, v = indice[arista["origen"]], indice[arista["destino"]]
        grafo[u].append([v, arista["capacidad"], arista["costo"], len(grafo[v])])
        grafo[v].append([u, 0, -arista["costo"], len(grafo[u]) - 1])
        referencias.append((u, len(grafo[u]) - 1))
    return indice, grafo, referencias


def flujos_por_arista(aristas, grafo, referencias):
    return [arista["capacidad"] - grafo[u][k][1] for arista, (u, k) in zip(aristas, referencias)]


def aumentar(grafo, previo, origen, destino, limite):
    cuello = limite
    v = destino
    while v != origen:
        u, k = previo[v]
        cuello = min(cuello, grafo[u][k][1])
        v = u
    v = destino
    while v != origen:
        u, k = previo[v]
        arista = grafo[u][k]
        arista[1] -= cuello
        grafo[v][arista[3]][1] += cuello
        v = u
    return cuello


def flujo_maximo(aristas, nodos, origen, destino):
    indice, grafo, referencias = construir_grafo(aristas, nodos)
    s, t = indice[origen], indice[destino]
    total = 0
    while True:
        previo = [None] * len(grafo)
        previo[s] = (s, -1)
        cola = deque([s])
        while cola and previo[t] is None:
            u = cola.popleft()
            for k, arista in enumerate(grafo[u]):
                if arista[1] > 0 and previo[arista[0]] is None:
                    previo[arista[0]] = (u, k)
                    cola.append(arista[0])
        if previo[t] is None:
            break
        total += aumentar(grafo, previo, s, t, float("inf"))
    return total, flujos_por_arista(aristas, grafo, referencias)


def flujo_costo_minimo(aristas, nodos, origen, destino, requerido):
    indice, grafo, referencias = construir_grafo(aristas, nodos)
    s, t = indice[origen], indice[destino]
    enviado = 0
    while enviado < requerido:
        distancia = [float("inf")] * len(grafo)
        previo = [None] * len(grafo)
        distancia[s] = 0
        for _ in range(len(grafo) - 1):
            cambio = False
            for u in range(len(grafo)):
                if distancia[u] == float("inf"):
                    continue
                for k, arista in enumerate(grafo[u]):
                    if arista[1] > 0 and distancia[u] + arista[2] < distancia[arista[0]]:
                        distancia[arista[0]] = distancia[u] + arista[2]
                        previo[arista[0]] = (u, k)
                        cambio = True
            if not cambio:
                break
        if previo[t] is None:
            break
        enviado += aumentar(grafo, previo, s, t, requerido - enviado)
    flujos = flujos_por_arista(aristas, grafo, referencias)
    costo = sum(f * arista["costo"] for f, arista in zip(flujos, aristas))
    return enviado, costo, flujos


def analisis_de_flujo(requerido=FLUJO_REQUERIDO):
    aristas = ARISTAS_FLUJO
    solo_controles = [arista for arista in aristas if arista["control"]]
    maximo, flujos_max = flujo_maximo(aristas, NODOS_FLUJO, "creacion", "entrega")
    maximo_controlado, _ = flujo_maximo(solo_controles, NODOS_FLUJO, "creacion", "entrega")
    enviado, costo, flujos_costo = flujo_costo_minimo(aristas, NODOS_FLUJO, "creacion", "entrega", requerido)
    enviado_c, costo_c, flujos_c = flujo_costo_minimo(solo_controles, NODOS_FLUJO, "creacion", "entrega", requerido)
    sin_control = sum(f for f, arista in zip(flujos_costo, aristas) if not arista["control"])
    filas = []
    for arista, f_max, f_costo in zip(aristas, flujos_max, flujos_costo):
        filas.append(dict(arista, flujo_maximo=f_max, flujo_costo_minimo=f_costo))
    return {
        "aristas": filas,
        "maximo": maximo,
        "maximo_controlado": maximo_controlado,
        "requerido": requerido,
        "costo_minimo": costo,
        "enviado": enviado,
        "flujo_sin_control": sin_control,
        "costo_controlado": costo_c,
        "enviado_controlado": enviado_c,
        "estados": ESTADOS_ORDEN,
        "fuente": SUPUESTO,
    }
