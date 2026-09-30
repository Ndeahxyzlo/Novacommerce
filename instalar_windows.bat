@echo off
setlocal
cd /d "%~dp0"
set "PATH=C:\Program Files\PostgreSQL\18\bin;C:\Program Files\PostgreSQL\17\bin;C:\Program Files\PostgreSQL\16\bin;%PATH%"
set "PY=python"
python --version >nul 2>nul || set "PY=py -3"
%PY% --version >nul 2>nul || (echo Falta Python 3.11 o 3.12. & pause & exit /b 1)
where initdb >nul 2>nul || (echo No se encontro PostgreSQL. & pause & exit /b 1)
set "PGDATA=%~dp0pgdata"
set PGPORT=5433
set PGHOST=localhost
if not exist "%PGDATA%\PG_VERSION" initdb -D "%PGDATA%" -U postgres -A trust -E UTF8 --locale=C >nul
pg_ctl -D "%PGDATA%" -o "-p 5433 -c listen_addresses=localhost" -l "%~dp0pg.log" -w start
psql -q -U postgres -c "create role novacommerce login password 'novacommerce' createdb" 2>nul
createdb -U postgres -O novacommerce novacommerce 2>nul
psql -U novacommerce -d novacommerce -tAc "select to_regclass('public.orders')" | findstr orders >nul || (%PY% -c "import gzip,shutil;shutil.copyfileobj(gzip.open('database/novacommerce_completa.sql.gz'),open('novacommerce_completa.sql','wb'))" & psql -q -U novacommerce -d novacommerce -f novacommerce_completa.sql >nul)
if not exist .venv %PY% -m venv .venv
.venv\Scripts\python -m pip install -q -r requirements.txt
set DATABASE_URL=postgresql://novacommerce:novacommerce@localhost:5433/novacommerce
set FLASK_ENV=development
start "" http://127.0.0.1:5000
.venv\Scripts\python -m flask --app wsgi run
pg_ctl -D "%PGDATA%" stop
pause
