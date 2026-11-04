#!/bin/sh
set -eu
uv run --no-sync python manage.py migrate --noinput
uv run --no-sync python manage.py setup_roles
if [ "${DJANGO_DEMO_CATALOGUE:-0}" = "1" ]; then
    uv run --no-sync python manage.py seed_demo --allow-hosted-demo
fi
