# Testing strategy and evidence

## Verification by layer

| Layer | Planned coverage |
| --- | --- |
| Unit | Money rounding and integer totals, delivery zone rules, order transitions, permission helpers, callback parsing and message templates |
| PostgreSQL integration | Fresh and upgrade migrations, constraints, deterministic seed data, rollback, separate-connection checkout races, idempotency and inventory restoration. Use Django transaction tests for operations that depend on actual commit or locking |
| HTTP integration | Guest and account sessions, ownership and staff permissions, CSRF, validation, filters, stale totals, duplicate submits, upload limits and provider error handling |
| Browser | Guest and registered browse-to-payment journeys, cart persistence, delivery fees, and staff catalogue, zone and order operations. Exercise narrow and wide viewports, keyboard navigation and key accessibility checks |
| External providers | Opt-in sandbox or test-account calls for valid, failed, cancelled and repeated payments, as well as notification acceptance and available delivery evidence. Verify forged or mismatched callbacks separately. Record explicit blockers |
| Security and performance | Authorization, session fixation, injection, output escaping, upload processing, abuse limits, secret review, query plans, image weight, response latency and production checks |

Phase 1 will install and pin the verification tools, then document exact setup commands. Planned entry points include `ruff check .`, `python -m django check`, `python manage.py makemigrations --check --dry-run`, `python manage.py test` and `python manage.py collectstatic --noinput` with project settings loaded. Document the type checker, PostgreSQL-backed concurrency tests and Playwright invocation when configured. Run applicable checks before each checkpoint and repeat affected regressions after fixes.

## Phase 0 results

| Check | Result |
| --- | --- |
| Repository inventory and upstream comparison | PASS. The initial tracked tree contained only `README.md` and `.gitignore`. Local `main` matched the first commit advertised by GitHub |
| Ignore rules | PASS. Git ignored representative environment files, credential files, dependencies and generated output, and allowed `.env.example` |
| Planning document checks | Recorded in [IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md) |
| Unit tests, integration tests, type checking, application lint, build and browser checks | N/A. The baseline has no application or test suite |
