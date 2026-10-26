#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
ROOT="$PWD"
BIN=$(ls -d /usr/lib/postgresql/*/bin 2>/dev/null | sort -V | tail -1)
[ -n "$BIN" ] && export PATH="$BIN:$PATH"
command -v initdb >/dev/null || { echo "Falta PostgreSQL: sudo apt install postgresql python3-venv"; exit 1; }
command -v python3 >/dev/null || { echo "Falta python3"; exit 1; }
export PGDATA="$ROOT/pgdata" PGPORT=5433 PGHOST=localhost
[ -f "$PGDATA/PG_VERSION" ] || initdb -D "$PGDATA" -U postgres -A trust -E UTF8 --locale=C >/dev/null
pg_ctl -D "$PGDATA" -o "-p 5433 -c listen_addresses=localhost -c unix_socket_directories=/tmp" -l "$ROOT/pg.log" -w start
trap 'pg_ctl -D "$PGDATA" stop' EXIT
psql -q -U postgres -c "create role novacommerce login password 'novacommerce' createdb" 2>/dev/null || true
createdb -U postgres -O novacommerce novacommerce 2>/dev/null || true
if ! psql -U novacommerce -d novacommerce -tAc "select to_regclass('public.orders')" | grep -q orders; then
  gunzip -c database/novacommerce_completa.sql.gz | psql -q -U novacommerce -d novacommerce >/dev/null
fi
[ -d .venv ] || python3 -m venv .venv
.venv/bin/pip install -q -r requirements.txt
export DATABASE_URL=postgresql://novacommerce:novacommerce@localhost:5433/novacommerce
export FLASK_ENV=development
(sleep 3; xdg-open http://127.0.0.1:5000 >/dev/null 2>&1 || true) &
.venv/bin/python -m flask --app wsgi run
