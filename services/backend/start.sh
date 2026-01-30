#!/bin/bash
set -e

echo "Running database migrations..."
alembic upgrade head

echo "Starting application..."
# Respect X-Forwarded-* from the gateway/tunnel so redirects keep https host/scheme.
exec uvicorn app.main:app --host 0.0.0.0 --port 8001 --proxy-headers --forwarded-allow-ips="*" "$@"
