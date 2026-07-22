#!/bin/bash
# ── AAA v2 Backend Entrypoint ────────────────────────────────────────────────
# Runs Alembic migrations before starting the application server.
# Fails fast and loud if migrations cannot be applied — no silent drift.
set -euo pipefail

echo "=== AAA v2: Running database migrations ==="
alembic upgrade head
echo "=== AAA v2: Migrations complete, starting server ==="

exec uvicorn app.main:app --host "${API_HOST:-0.0.0.0}" --port "${API_PORT:-8000}" --workers "${WEB_CONCURRENCY:-1}"
