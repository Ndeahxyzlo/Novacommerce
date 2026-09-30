# NovaCommerce

Plataforma multiempresa de comercio electronico con tienda publica, panel para duenos de empresa, administracion de la plataforma, bodega de datos (esquema estrella en PostgreSQL), consultas OLAP y modelos de aprendizaje automatico.

## Requisitos

- Python 3.11 o superior
- PostgreSQL 14 o superior

## Documentacion de la bodega de datos

En docs/: modelo conceptual y logico, implementacion fisica y seguridad, modelo de despliegue, carga y evidencias, integracion con BI. Los roles de la bodega se crean con `psql -v bi_password=... -v auditor_password=... -f warehouse/roles.sql` como superusuario. Metabase: `docker compose -f docker-compose.metabase.yml up -d`.

## Windows en un paso

Con Python 3.11 o 3.12 y PostgreSQL 14 o superior instalados, ejecuta `instalar_windows.bat`: crea la base, restaura los datos, instala las dependencias y abre la aplicacion en http://127.0.0.1:5000.

## Puesta en marcha

    python -m venv .venv
    source .venv/bin/activate
    pip install -r requirements.txt
    cp .env.example .env
    createdb novacommerce
    createdb novacommerce_test
    flask --app wsgi init-db
    flask --app wsgi seed-demo
    flask --app wsgi etl --full
    flask --app wsgi ml-run
    flask --app wsgi train-anomaly
    flask --app wsgi run

Abre http://127.0.0.1:5000.

## Variables de entorno

- SECRET_KEY: obligatoria en produccion, cadena larga y aleatoria.
- DATABASE_URL: conexion PostgreSQL.
- TEST_DATABASE_URL: base usada por las pruebas.
- PROXY_COUNT: cantidad de proxies confiables delante de la aplicacion.
- DW_ENCRYPTION_KEY: clave de cifrado de columnas de la bodega, obligatoria en produccion.
- MAIL_SERVER, MAIL_PORT, MAIL_USERNAME, MAIL_PASSWORD, MAIL_USE_TLS, MAIL_SENDER: correo para recuperar contrasena. Sin servidor, el enlace se registra en el log.

## Comandos

- init-db: crea tablas y esquema dw.
- reset-db: borra y recrea todo.
- create-admin: crea un administrador de plataforma.
- seed-demo: genera 3 empresas, catalogo, unos 15000 clientes y ordenes sinteticas con Faker es_CO.
- etl [--full]: carga incremental o completa de la bodega desde la base operativa.
- ml-run: entrena pronostico de demanda y recalcula punto de reorden, stock de seguridad y EOQ.
- train-anomaly: entrena el modelo de anomalias de acceso.
- export-schema: escribe database/schema.sql.
- dw-verify [--output archivo.json]: 30 controles de integridad y reconciliacion de la bodega.
- dw-dump: volcado del esquema dw en database/dw_carga.sql.gz.

## Cuentas de demostracion (solo desarrollo)

- admin@novacommerce.local
- owner.<empresa>@novacommerce.local, por ejemplo owner.tienda-andina@novacommerce.local
- cliente@novacommerce.local

Contrasena de todas: Demo12345x. Cambiala o no uses el seed en produccion.

## Arquitectura

- app/models: modelos SQLAlchemy con Numeric para dinero y restricciones CHECK.
- app/services: reglas de negocio (pedidos, carrito, ETL, analitica, seguridad, correo).
- app/routes: blueprints por area (auth, panel, tienda, admin, API).
- app/ml: demanda (HistGradientBoosting con perdida poisson y linea base) y anomalias (regresion logistica).
- warehouse/medallion.sql (capas bronze y silver) y warehouse/schema.sql (capa oro: esquema estrella dw con SCD Tipo 2 en producto y cliente y hechos de ventas e inventario).
- tests: 65 pruebas (concurrencia sin sobreventa, aislamiento entre empresas, CSRF, bloqueo de login, ETL, ML, render de paginas).

## Seguridad

- Aislamiento por company_id en toda consulta.
- Roles admin, owner y customer; el registro publico solo permite customer y owner.
- CSRF global, CSP sin scripts ni estilos en linea, cabeceras de seguridad.
- Bloqueo tras 5 intentos fallidos en 15 minutos, tokens de recuperacion de un solo uso.
- Stock protegido con SELECT FOR UPDATE y numeracion de pedidos atomica por empresa.

## Nota sobre las metricas

Los datos son sinteticos. La mejora del pronostico frente a la linea base es modesta y la exactitud del modelo de anomalias se mide sobre registros etiquetados sinteticamente; no son evidencia de rendimiento real.

## Despliegue

El Procfile ejecuta init-db y luego gunicorn. Define SECRET_KEY, DATABASE_URL y PROXY_COUNT en el entorno del proveedor.

## Despliegue en Vercel

La aplicacion corre como funcion Python (index.py) y usa una base PostgreSQL externa, por ejemplo Neon.

1. Importar el repositorio en Vercel (framework Flask, detectado solo).
2. Crear la base Neon desde Vercel Marketplace y usar su cadena de conexion como DATABASE_URL.
3. Definir SECRET_KEY, DW_ENCRYPTION_KEY y PROXY_COUNT=1 en las variables de entorno del proyecto.
4. Restaurar los datos una sola vez desde un equipo con psql: `gunzip -c database/novacommerce_completa.sql.gz | psql "$DATABASE_URL"`.
5. Las tareas pesadas (etl, ml-run, train-anomaly) se ejecutan con la CLI apuntando a la misma DATABASE_URL, no dentro de la funcion.

Los archivos estaticos se sirven desde public/static, copia de app/static.

## Pruebas

    FLASK_ENV=testing python -m pytest -q
