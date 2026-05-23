#!/usr/bin/env bash
# Startup para Fly.io.
# Las migraciones Alembic corren en release_command (fly.toml) ANTES de
# que este contenedor reciba trafico. No repetir aqui: un fallo de migracion
# cancela el deploy sin downtime y el app viejo sigue sirviendo.
set -euo pipefail

echo "[start-fly] arrancando uvicorn en 0.0.0.0:${PORT:-8080}"
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8080}" --workers 1
