#!/bin/sh
set -eu
uv sync --locked --no-dev
uv run --no-sync python manage.py check --deploy --fail-level ERROR
uv run --no-sync python manage.py collectstatic --noinput
