# EZ-E-Commerce

## Local setup

Use [uv](https://docs.astral.sh/uv/getting-started/installation/) with Python 3.13 and Docker with the Compose plugin. Copy `.env.example` to `.env` and set a unique Django secret, a local database password, and `DATABASE_URL` to the matching PostgreSQL URL. The local database in `compose.yaml` listens on port 55432 with user and database `ezcommerce`. URL-encode special characters in the password when using it in the database URL.

```sh
uv sync --locked
docker compose -p ezcommerce up -d --wait
uv run python manage.py migrate
uv run python manage.py setup_roles
uv run python manage.py seed_demo
uv run python manage.py runserver
```

Open [the local storefront](http://127.0.0.1:8000/). Use `/healthz` for liveness and `/readyz` for database readiness.

See [implementation status](IMPLEMENTATION_STATUS.md) and [testing](TESTING.md) for the verified checkpoint and checks.

Create the first local administrator interactively with `uv run python manage.py createsuperuser`. Customer accounts are created through the storefront. Staff roles are assigned separately by a trusted administrator.
