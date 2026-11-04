#!/bin/sh
set -eu
exec uv run --no-sync gunicorn config.wsgi:application \
    --bind "${BIND_HOST:-0.0.0.0}:${PORT:-8000}" \
    --workers 1 --threads 2 --timeout 45 --error-logfile - --capture-output
