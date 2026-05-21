#!/usr/bin/env bash
# Startup para Fly.io. Hace migraciones Alembic solo si hay DATABASE_URL.
# Si no hay Postgres conectado, igual arranca uvicorn para que `/health`
# responda (los endpoints que dependen de DB devolveran 500 hasta que se
# attachee una base).
set -euo pipefail

if [[ -n "${DATABASE_URL:-}" ]]; then
  echo "[start-fly] DATABASE_URL presente, aplicando migraciones alembic..."
  alembic upgrade head
else
  echo "[start-fly] DATABASE_URL ausente; salto migraciones. Solo /health funcionara."
fi

echo "[start-fly] arrancando uvicorn en 0.0.0.0:${PORT:-8080}"
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8080}" --workers 1
