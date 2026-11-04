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

## Phase 1 results

Python 3.13.18 and PostgreSQL 17.11 were used. `uv sync --locked`, `ruff check .`, `mypy config accounts storefront tests`, Django system checks, migration application and drift checks, and four Django tests passed. Production-mode `collectstatic` produced the hashed manifest. Local HTTP readiness returned `ready`, and Chromium verified the base layout, stylesheet, keyboard skip link and absence of horizontal overflow at 375px and 1440px. PostgreSQL ran from the same Docker image declared in Compose, started with the Docker CLI because the Compose plugin was unavailable on this machine.

## Phase 2 results

The shop migrations applied to the existing Phase 1 database and to a fresh test database. Ten tests passed, including database uniqueness and check constraints, historical snapshot preservation, atomic rollback, repeatable seeding, and a race using two separate PostgreSQL connections to claim the last unit. All 120 fixture SKUs persisted after restarting the PostgreSQL container. Lint, type checks, migration drift and static asset build passed.

## Phase 3 — Authentication and authorization results

Fifteen tests passed, covering registration, Argon2 hashing, email normalization, session rotation, invalid sign-in, sign-out and CSRF, address ownership, and staff permissions on direct requests. The storefront remained accessible as a guest. Lint, type checking, migration drift and the asset build passed.

## Phase 4 — Storefront and product catalogue results

Twenty-one Django tests passed. Chromium verified the homepage, loaded imagery, combined search/category/price/sort filters and product details at 375px and 1440px. Pagination, private visibility for inactive catalogue entries, gallery markup and stock visibility passed. Original category illustrations act as demo fallbacks. Lint, type checking, migration drift and the static build passed.

## Phase 5 — Persistent cart results

Twenty-five tests passed. Guest and account carts persist, merge after sign-in, enforce stock and valid quantities, ignore submitted prices and require CSRF. Chromium verified add, refresh persistence, update and removal at mobile width. Lint, type checking, migration drift and static build passed.

## Phase 6 — Checkout and order backend results

Twenty-nine tests passed. Checkout calculates BDT totals and zone fees on the server, detects a stale or altered quote, stores historical snapshots and supports replay of the same submission without a second order. Separate PostgreSQL transactions verified that only one cart can reserve the last unit. Expiry released inventory once. Chromium verified mobile guest checkout and order privacy. Lint, types, migration drift and static build passed.

## Phase 7 — Payment gateway results

Thirty-five tests passed, including six gateway scenarios with controlled provider HTTP responses. Verified payments consume stock once, confirmed failures release stock, and mismatches or late captures require review. Local simulation never marks an order paid. Real SSLCOMMERZ sandbox verification is externally blocked by merchant test credentials and a public callback endpoint. Lint, types, migration drift and static build passed.

## Phase 8 — Administrative dashboard results

Forty tests passed. Verified staff authorization, catalogue and zone creation and updates, protected history, product inventory updates, validated raster uploads and removal, storefront settings, order search and payment details, fulfillment transitions and cancellation with inventory release. Local image storage was exercised. Cloudinary acceptance awaits credentials. Lint, types, migration drift and static build passed.

## Phase 9 — Email and SMS notifications results

Forty-six tests passed. Verified event deduplication, stable email retry payloads, provider acceptance handling, unknown SMS outcomes, expired leases, suppressed delivery when credentials are absent and expiring guest order access. Actual email and SMS acceptance or delivery is externally blocked by sender credentials and approvals. Lint, types, migration drift and the static build passed.

## Phase 10 — Responsive and accessible UI results

Forty-seven tests passed, including Chromium at 375px and 1440px across storefront, catalogue, product, cart, checkout, login, account and staff views. Keyboard skip navigation passed. Axe WCAG A/AA rules passed after fixing product link names and making the horizontally scrollable orders table keyboard focusable. Checkout progress, pending feedback and browser autofill were added. Lint, types, migration drift and static build passed.

## Phase 11 — Security and performance audit results

Fifty-three tests passed, including Chromium and axe. Added shared per-IP and per-login rate limits, request-size limits, CSP and fragment-based private guest access. Verified CSRF, secure cookies, escaping, parameterized search, authorization, upload safety and replay controls. Replaced vulnerable Pillow 12.3.0 with 13.0.0; pip-audit then found no known runtime dependency vulnerabilities. Django deploy checks had no errors and two documented domain-level HSTS advisories. At 120 fixture SKUs, catalogue rendering stayed within seven queries. Fifteen local requests per route gave median responses of 21.5 ms for home, 23.5 ms for browse and 24.9 ms for filtered browse. PostgreSQL measured the example filtered query at 0.155 ms. Storefront CSS, JS and all demo SVGs totalled 25,721 uncompressed bytes. These measurements cover the local development stack.

Run the complete browser suite from a development-configured checkout with Chromium installed:

```sh
uv run playwright install chromium
RUN_BROWSER_TESTS=1 uv run python manage.py test
```

Set `AXE_SCRIPT` to the path to `axe.min.js` and run the specific responsive and keyboard test to repeat the automated accessibility review. The payment browser fixture intercepts the documented hosted handoff and validates the callback and independent lookup against controlled SSLCOMMERZ responses. It does not submit a payment to the actual gateway.

## Phase 12 — End-to-end testing results

Fifty-five tests passed including three Chromium tests. Guest and registered journeys covered browsing, search, multiple items, quantity updates, refresh persistence, server-calculated delivery and discounts, order creation, hosted handoff and callback verification against a controlled provider fixture. Staff exercised catalogue creation, stock updates, photo upload, delivery fees, order search, payment details and tracking. Guest access was recovered in a fresh browser. Real SSLCOMMERZ sandbox checkout remains externally blocked. Lint, types, migration drift and static build passed.
