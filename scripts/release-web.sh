#!/bin/sh
set -eu
uv run --no-sync python manage.py migrate --noinput
uv run --no-sync python manage.py setup_roles
