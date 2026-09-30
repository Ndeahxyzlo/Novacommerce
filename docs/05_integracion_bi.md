# 5. Integracion con herramienta de Business Intelligence

## 5.1 Capa semantica para BI

La bodega expone seis vistas en `dw`, pensadas para consumirse sin escribir SQL:

| Vista | Uso |
|---|---|
| `v_ventas_detalle` | Detalle por linea con todas las dimensiones (cliente anonimizado) |
| `v_ventas_mensual` | Ingresos, margen, ordenes y unidades por empresa y mes |
| `v_ventas_categoria` | Ventas por categoria |
| `v_ventas_canal` | Ventas por canal |
| `v_top_productos` | Ranking de productos por empresa (RANK) |
| `v_clientes_rfm` | Recencia, frecuencia, monto y quintiles RFM (NTILE) |

Usuario de conexion: `bi_reader` (solo lectura sobre estas vistas).

## 5.2 Conexion desde Power BI

1. Obtener datos, conector PostgreSQL.
2. Servidor `host:5432`, base `novacommerce`, modo Importar o DirectQuery.
3. Credenciales de base de datos: usuario `bi_reader`.
4. Seleccionar las seis vistas del esquema `dw`.
5. Relaciones: `v_ventas_detalle` es la tabla principal; las demas vistas son agregados independientes.
6. Medidas DAX sugeridas:
   - `Ingresos = SUM(v_ventas_detalle[ingreso])`
   - `Margen % = DIVIDE(SUM(v_ventas_detalle[margen]), [Ingresos])`
   - `Ticket promedio = DIVIDE([Ingresos], DISTINCTCOUNT(v_ventas_detalle[orden_id]))`
   - `Tasa cancelacion = DIVIDE(CALCULATE(DISTINCTCOUNT(v_ventas_detalle[orden_id]), v_ventas_detalle[estado] = "cancelled"), DISTINCTCOUNT(v_ventas_detalle[orden_id]))`

## 5.3 Conexion desde Metabase (Docker)

    docker compose -f docker-compose.metabase.yml up -d

Abrir http://localhost:3000, agregar base PostgreSQL con host `host.docker.internal`, base `novacommerce`, usuario `bi_reader`, y activar SSL en produccion.

## 5.4 Tablero de control

Indicadores incluidos en el tablero de demostracion:

| Indicador | Vista de origen |
|---|---|
| Ingresos, margen, ordenes, unidades y clientes activos | v_ventas_detalle |
| Ingresos mensuales por empresa | v_ventas_mensual |
| Ventas por categoria | v_ventas_categoria |
| Participacion por canal | v_ventas_canal |
| Top 3 productos por empresa | v_top_productos |
| Segmentacion RFM de clientes | v_clientes_rfm |
| Ingresos por dia de la semana | v_ventas_detalle |
| Ordenes por estado (control de cancelacion) | v_ventas_detalle |

La aplicacion tambien incluye tableros propios en `/reportes` para cada empresa, alimentados por la misma bodega.

## 5.5 Alcance

En este entorno no se ejecuto Power BI Desktop ni Metabase (no hay Docker ni acceso de red para descargarlos). Lo entregado y verificado es la capa de vistas, el usuario de solo lectura probado, la guia de conexion y un tablero de demostracion construido sobre esas mismas vistas.
