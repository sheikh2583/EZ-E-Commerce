#!/bin/sh
set -eu
uv run --no-sync python manage.py expire_orders
uv run --no-sync python manage.py reconcile_payments
uv run --no-sync python manage.py send_notifications
uv run --no-sync python manage.py prune_rate_limits
