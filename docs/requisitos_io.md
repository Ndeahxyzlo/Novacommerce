# Cobertura de los requisitos de Investigación de Operaciones

Este documento relaciona cada requisito con el archivo, la función y la prueba que lo verifica. Los datos marcados como supuesto de demostración (costos, horas, probabilidades, impactos, capacidades y rangos de las distribuciones) no provienen de mediciones reales y sirven únicamente para ilustrar el método.

## Matriz de requisitos

| Requisito | Archivo | Función | Prueba | Resultado |
|---|---|---|---|---|
| 1. Optimización de recursos de seguridad | `app/services/io_extra.py` | `plan_de_controles` | `tests/test_io_requisitos.py::test_plan_de_controles_respeta_restricciones_y_coincide_con_linprog` | Verificamos que el valor óptimo coincide con `scipy.optimize.linprog` y que se respetan las restricciones. |
| Método simplex y precios sombra | `app/services/optimization.py` | `simplex_max` (sin cambios) | `test_simplex_coincide_con_linprog_en_problemas_aleatorios` | Comparamos 25 problemas aleatorios en valor objetivo y precios sombra. |
| 2. Simulación de escenarios | `app/services/io_extra.py` | `montecarlo` | `test_montecarlo_es_reproducible_con_la_misma_semilla` | Con 10.000 corridas y semilla fija el resultado es idéntico en cada ejecución. |
| 3. Análisis cuantitativo de vulnerabilidades | `app/services/io_extra.py` | `registro_de_riesgos`, `reduccion_por_control` | `test_reduccion_de_cada_control_sale_del_registro_de_riesgos` | El riesgo es probabilidad por impacto y la reducción de cada control sale del registro. |
| 4. Flujo de trabajo seguro | `app/services/io_extra.py` | `flujo_maximo`, `flujo_costo_minimo`, `analisis_de_flujo` | `test_flujo_maximo_coincide_con_linprog`, `test_flujo_de_costo_minimo_coincide_con_linprog` | Comparamos Edmonds-Karp y Bellman-Ford contra `linprog` en grafos aleatorios. |
| 5. Apoyo a la toma de decisiones | `app/services/optimization.py` | `sensibilidad` | `test_sensibilidad_de_recursos_dentro_del_rango`, `test_sensibilidad_de_recursos_fuera_del_rango_cambia_el_precio_sombra`, `test_sensibilidad_de_coeficientes_dentro_y_fuera_del_rango` | Perturbamos coeficientes y recursos dentro y fuera de los rangos calculados. |
| Pantalla de decisiones | `app/routes/admin.py` | `decisions` | `tests/test_consultas.py::test_administrador_ve_consultas_decisiones_y_exporta_csv` | La página `/admin/decisiones` reúne los cinco requisitos. |

## Módulo de consultas

| Elemento | Archivo | Prueba |
|---|---|---|
| ROLLUP, CUBE y GROUPING SETS | `app/services/consultas.py` | `test_rollup_total_es_la_suma_del_detalle`, `test_rollup_subtotal_de_empresa_es_la_suma_de_sus_filas`, `test_cube_incluye_ciudad_sin_dato_y_total`, `test_grouping_sets_total_general` |
| Versión SCD2 según la fecha de la venta | `app/services/consultas.py` | `test_scd2_usa_la_version_vigente_en_la_fecha_de_la_venta` |
| Cubo MOLAP simulado | `app/services/consultas.py` | `test_cubo_molap_se_actualiza_solo_al_refrescar` |
| Filtros, búsqueda y paginación | `app/services/consultas.py` | `test_detalle_filtra_por_empresa_busqueda_y_fechas`, `test_detalle_pagina_los_resultados` |
| Protección contra inyección SQL | `app/services/consultas.py` | `test_inyeccion_sql_en_la_busqueda_no_tiene_efecto`, `test_filtros_invalidos_se_ignoran` |
| Transacción de solo lectura | `app/services/consultas.py` | `test_las_consultas_corren_en_transaccion_de_solo_lectura` |
| Control de acceso y CSRF | `app/routes/admin.py` | `test_acceso_solo_para_administrador`, `test_refrescar_cubo_exige_csrf_y_funciona_con_token` |

## Decisiones de diseño

- La regla SCD2 que usamos para cruzar una venta con la dimensión es `fecha_inicio <= fecha AND (fecha_fin IS NULL OR fecha < fecha_fin)`, con la fecha de la venta tomada de `dim_tiempo`.
- PostgreSQL no tiene un motor MOLAP nativo. La vista materializada `dw.cubo_ventas_mensual` es una aproximación con índice único para poder usar `REFRESH MATERIALIZED VIEW CONCURRENTLY`. La fecha de la última actualización queda como comentario de la vista.
- Las consultas corren en una transacción `READ ONLY` con tiempo máximo de 20 segundos y parámetros enlazados. Solo el administrador accede, y ninguna consulta incluye la columna cifrada del correo.
- Para mantener el proyecto simple y desplegable en Vercel con Neon no creamos roles de base de datos adicionales: la restricción de solo lectura se aplica en cada transacción.
- La base de pruebas debe ser siempre una base local: las pruebas eliminan y recrean el esquema `dw`.

## Limitaciones

- La prueba de referencia con la carga completa de 40.000 órdenes no se implementó. Las pruebas usan una bodega pequeña construida a mano para que sean rápidas.
- No existe un rol de BI separado del administrador.
