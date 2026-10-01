# 4. Implementacion, carga y evidencias

## 4.1 Archivos de despliegue y carga

| Archivo | Contenido |
|---|---|
| `warehouse/schema.sql` | Estructura completa de `dw`: tablas, indices, auditoria, cifrado, vistas y permisos |
| `warehouse/roles.sql` | Roles y usuarios de la bodega |
| `database/dw_carga.sql.gz` | Volcado del esquema `dw` con estructura y datos cargados |
| `database/schema.sql` | Estructura de las tablas operativas |
| `docs/evidencias/integridad.json` | Resultado de los 30 controles de calidad |
| `docs/evidencias/seguridad_acceso.txt` | Salida real de los intentos de acceso por rol |

Restaurar: `gunzip -c database/dw_carga.sql.gz | psql -d <base>`.

## 4.2 Proceso ETL

- **Arquitectura Medallion en PostgreSQL**: esquema `bronze` (copia cruda de la operacion, correo ya cifrado), esquema `silver` (datos limpios, tipados y validados; los invalidos van a `silver.rechazos`) y esquema `dw` (oro, modelo estrella).
- **Extraccion**: tablas operativas `orders`, `order_items`, `products`, `customers`, `companies`.
- **Transformacion**: calculo de ingreso, costo total y margen; asignacion de canal; llave de fecha; cifrado del correo; resolucion de llaves faltantes a nulo.
- **Carga**: dimensiones por `UPSERT`; hechos incrementales por marca de agua sobre `orders.updated_at`, idempotentes; carga completa opcional (`--full`).
- **Bitacora**: cada ejecucion queda en `dw.etl_ejecuciones` con estado y filas; los errores se registran y se relanzan.

Comandos: `flask etl [--full]`, `flask dw-verify --output reporte.json`, `flask dw-dump`.

## 4.3 Datos cargados

| Tabla | Filas |
|---|---|
| dim_tiempo | 828 |
| dim_empresa | 3 |
| dim_producto | 140 |
| dim_cliente | 15.000 |
| dim_canal | 2 |
| fact_ventas | 72.078 (40.000 ordenes) |

Los datos son sinteticos (Faker es_CO), con tres empresas, ordenes entre 2024-09-29 y 2026-09-28 y 15.000 clientes.

## 4.4 Evidencias de integridad

Resultado de `flask dw-verify`: **30 de 30 controles aprobados.**

| Grupo | Controles | Resultado |
|---|---|---|
| Reconciliacion con la base operativa | Filas de hechos (72.078), ingreso total ($27.529.714.400), costo total ($16.864.374.400), unidades (121.580), ordenes (40.000), ingreso por empresa | Coinciden exactamente |
| Dimensiones | Empresas (3), productos (140), clientes (15.000), correos cifrados (15.000) | Coinciden |
| Calidad de hechos | Duplicados, fechas huerfanas, empresa, producto y cliente inexistentes, cantidades no positivas, margen = ingreso - costo, ingreso = cantidad x precio, nulos, productos o clientes de otra empresa | 0 incidencias en cada uno |

## 4.5 Evidencias de funcionamiento

- Idempotencia: `tests/test_warehouse_ml.py` ejecuta el ETL varias veces y una carga completa; el conteo se mantiene.
- Propagacion de cambios: cancelar una orden y correr el ETL actualiza el estado en el hecho.
- Auditoria: `dw.audit_log` registra cada carga (por ejemplo, 72.078 filas insertadas en `fact_ventas`).
- Seguridad por rol: ver `evidencias/seguridad_acceso.txt`.
- Suite de pruebas: 79 pruebas, todas pasan.
