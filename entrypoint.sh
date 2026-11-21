#!/bin/sh
set -e

echo "========================================================"
echo "    SirfBill Restaurant Platform - Backend Service     "
echo "========================================================"

# 1. Wait for database connection if DB_HOST is configured
if [ -n "$DB_HOST" ]; then
    DB_PORT_VAL="${DB_PORT:-5432}"
    DB_USER_VAL="${DB_USER:-postgres}"
    echo "[Entrypoint] Waiting for PostgreSQL at ${DB_HOST}:${DB_PORT_VAL} (user: ${DB_USER_VAL})..."
    
    until pg_isready -h "$DB_HOST" -p "$DB_PORT_VAL" -U "$DB_USER_VAL" > /dev/null 2>&1; do
        sleep 1
    done
    echo "[Entrypoint] PostgreSQL is online and accepting connections."
fi

# 2. Automatically apply latest consolidated Alembic migrations
echo "[Entrypoint] Running database migrations (alembic upgrade head)..."
if alembic upgrade head; then
    echo "[Entrypoint] Migrations applied successfully."
else
    echo "[Entrypoint] Warning: Alembic migration reported an issue; continuing service startup..."
fi

# 3. Launch Uvicorn Server
SERVER_PORT="${PORT:-8033}"
echo "[Entrypoint] Starting FastAPI server on port ${SERVER_PORT}..."
exec uvicorn main:app --host 0.0.0.0 --port "${SERVER_PORT}" "$@"
