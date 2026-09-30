# 2. Implementacion fisica y controles de seguridad

Sistema gestor: **PostgreSQL 16**. La bodega vive en el esquema `dw` de la misma base que la operacion, separada logicamente. Scripts: `warehouse/schema.sql` (objetos, disparadores, vistas, permisos) y `warehouse/roles.sql` (roles, ejecutado por un superusuario).

## 2.1 Estructura fisica

| Tabla | Filas (datos de demostracion) | Tamano |
|---|---|---|
| fact_ventas | 72.078 | 27 MB |
| dim_cliente | 15.000 | 4,8 MB |
| dim_tiempo | 828 | 160 kB |
| dim_producto | 140 | 96 kB |
| dim_empresa, dim_canal | 3 y 2 | menos de 50 kB |

Indices en la tabla de hechos: por tiempo, por (empresa, tiempo), por producto, por cliente y por orden; en dimensiones, por (empresa, categoria) y por empresa. Tipos: `numeric` para dinero, llaves enteras, `bytea` para datos cifrados.

## 2.2 Control de acceso

Modelo de minimo privilegio con roles de grupo (sin inicio de sesion) y usuarios que heredan de ellos.

| Rol | Tipo | Permisos |
|---|---|---|
| dw_etl | grupo | Leer y escribir tablas dw; no puede modificar ni borrar `audit_log` |
| dw_reader | grupo | Solo `SELECT` sobre las 6 vistas de BI; sin acceso a tablas base |
| dw_auditor | grupo | Leer `audit_log`, `etl_ejecuciones`, `etl_control`; ejecutar `dw.revelar_email` |
| bi_reader | usuario | Miembro de dw_reader, limite de 10 conexiones, `statement_timeout` de 60 s |
| auditor_dw | usuario | Miembro de dw_auditor, limite de 3 conexiones |

Las vistas se ejecutan con los privilegios de su propietario, de modo que el lector de BI consulta datos agregados y anonimizados sin poder tocar las tablas.

Evidencia real (`evidencias/seguridad_acceso.txt`): `bi_reader` lee las vistas, pero recibe `permission denied` al consultar `fact_ventas`, `audit_log`, al ejecutar `revelar_email` y al intentar borrar.

## 2.3 Confidencialidad y cifrado

- **Cifrado en columna**: el correo del cliente se guarda en `dim_cliente.email_cifrado` con `pgp_sym_encrypt` (pgcrypto, AES). La clave llega por la variable `DW_ENCRYPTION_KEY`, nunca queda en la base.
- **Descifrado controlado**: solo `dw.revelar_email(cliente, clave)` lo devuelve, con `SECURITY DEFINER` y ejecucion restringida a `dw_auditor`. Con clave incorrecta falla.
- **Anonimizacion**: la vista `v_ventas_detalle` expone el cliente como inicial + `***`.
- **Cifrado en transito**: conexiones con `sslmode=require` (ver `03_modelo_despliegue.md`).
- **Cifrado en reposo**: cifrado de disco/volumen del proveedor (ver despliegue).

## 2.4 Integridad

- Llaves primarias y foraneas hacia todas las dimensiones.
- Restricciones `NOT NULL` en medidas y llaves.
- 30 controles automaticos de calidad (`flask dw-verify`), incluidas reconciliaciones contra la base operativa.
- Carga idempotente: repetir el ETL no duplica filas (llave `orden_item_id` con `ON CONFLICT`).

## 2.5 Auditoria

- `dw.audit_log`: un registro por sentencia de escritura sobre cualquier tabla del esquema (disparadores de sentencia con tablas de transicion): tabla, operacion, cantidad de filas, usuario de sesion, usuario efectivo, aplicacion y momento.
- Es de **solo insercion**: un disparador rechaza `UPDATE` y `DELETE`, y el rol ETL no tiene esos permisos.
- `dw.etl_ejecuciones`: bitacora de cada carga (modo, estado, filas, inicio, fin, mensaje de error). Las cargas fallidas tambien quedan registradas.

## 2.6 Respaldo y recuperacion

- `flask dw-dump` genera `database/dw_carga.sql.gz` (estructura y datos del esquema).
- Recomendado en produccion: `pg_dump` diario y archivado de WAL para recuperacion a un punto en el tiempo.

## 2.7 Pruebas

`tests/test_dw_security.py` (10 pruebas): controles de calidad, bitacora de ETL, auditoria, auditoria inmutable, cifrado y descifrado, y comportamiento de cada rol.
