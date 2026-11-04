# Implementation status

## Phase 7 — Payment gateway

Thirty-five tests passed, including six gateway scenarios with controlled provider HTTP responses. Verified payments consume stock once, confirmed failures release stock, and mismatches or late captures require review. Local simulation never marks an order paid. Real SSLCOMMERZ sandbox verification is externally blocked by merchant test credentials and a public callback endpoint. Lint, types, migration drift and static build passed. See [TESTING.md](TESTING.md).

Checkpoint: `phase-07: integrate payment gateway`. Next: administrative dashboard.

## Phase 6 — Checkout and order backend

Twenty-nine tests passed. Checkout calculates BDT totals and zone fees on the server, detects a stale or altered quote, stores historical snapshots and supports replay of the same submission without a second order. Separate PostgreSQL transactions verified that only one cart can reserve the last unit. Expiry released inventory once. Chromium verified mobile guest checkout and order privacy. Lint, types, migration drift and static build passed. See [TESTING.md](TESTING.md).

Checkpoint: `phase-06: implement checkout and order management`. Next: payment gateway.

## Phase 5 — Persistent cart

Twenty-five tests passed. Guest and account carts persist, merge after sign-in, enforce stock and valid quantities, ignore submitted prices and require CSRF. Chromium verified add, refresh persistence, update and removal at mobile width. Lint, type checking, migration drift and static build passed. See [TESTING.md](TESTING.md).

Checkpoint: `phase-05: implement persistent shopping cart`. Next: checkout and order backend.

## Phase 4 — Storefront and product catalogue

Twenty-one Django tests passed. Chromium verified the homepage, loaded imagery, combined search/category/price/sort filters and product details at 375px and 1440px. Pagination, private visibility for inactive catalogue entries, gallery markup and stock visibility passed. Original category illustrations act as demo fallbacks. Lint, type checking, migration drift and the static build passed. See [TESTING.md](TESTING.md).

Checkpoint: `phase-04: implement storefront and product catalogue`. Next: persistent shopping cart.

## Phase 3 — Authentication and authorization

Fifteen tests passed, covering registration, Argon2 hashing, email normalization, session rotation, invalid sign-in, sign-out and CSRF, address ownership, and staff permissions on direct requests. The storefront remained accessible as a guest. Lint, type checking, migration drift and the asset build passed. See [TESTING.md](TESTING.md).

Checkpoint: `phase-03: implement authentication and authorization`. Next: storefront and catalogue.

## Phase 2 — Database and data models

Implemented PostgreSQL models and constraints for catalogue, accounts and addresses, carts, orders and historical items, reservations, delivery, store settings, payments and notifications. Verified migrations, rollback, concurrent stock updates and persistence of 120 synthetic products after restart. See [TESTING.md](TESTING.md).

Checkpoint: `phase-02: implement database schema and seed data`. Next phase: customer authentication and staff authorization.

## Phase 1 — Application foundation

Verified Django startup, the initial custom user and framework migrations, PostgreSQL readiness, the static build and the responsive base layout. The application exposes liveness and database readiness endpoints, uses environment-based settings, logs runtime failures and renders safe error pages. Lint, type checking and four tests passed. See [TESTING.md](TESTING.md).

Checkpoint: `phase-01: establish application foundation`. Next phase: relational data models and demo seed data.

## Phase 0 — Repository reconnaissance and planning

Phase 0 covers the published Git baseline, requirements map, technology decisions, database schema proposal, roadmap, risk assessment, verification strategy and deployment and integration plans. The user approved continuation after this checkpoint.

| Item | Status |
| --- | --- |
| Initial Git checkpoint | `8f51fed` (`first commit`), pushed to `origin/main` and verified against GitHub |
| Repository configuration | Local branch `main` tracks `origin/main`. The configured origin is the requested HTTPS URL. Pushes use the existing GitHub SSH agent through a repository-local URL mapping |
| Repository privacy | GitHub rejected the first local attempt due to commit email privacy. That commit is preserved on local branch `setup-local-only`. The published initial commit has the same tree and uses GitHub's no-reply address through repository-local configuration |
| Phase 0 checkpoint | `phase-00: document architecture and implementation plan` |
| Planning verification | PASS. Checked all six deliverables, local Markdown links, coverage of all 14 phase gates, staged whitespace and representative secret patterns |
| Application and provider verification | Pending the relevant implementation phases. Sandbox account, live merchant onboarding, messaging senders and hosting setup remain future work |
| Approval gate | Approved by the user |

See [PROJECT_PLAN.md](PROJECT_PLAN.md), [ARCHITECTURE.md](ARCHITECTURE.md), [TESTING.md](TESTING.md), [DEPLOYMENT.md](DEPLOYMENT.md) and [PAYMENT_INTEGRATION.md](PAYMENT_INTEGRATION.md).

## Next phase after approval

Set up the Django project and dependency lock, the environment and PostgreSQL connection, the initial user migration, logging and validation, and a responsive base layout. Verify the application starts, migrations and database connectivity work, and the build and layout pass their checks.
