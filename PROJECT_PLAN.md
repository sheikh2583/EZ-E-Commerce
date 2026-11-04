# EZ E-Commerce project plan

## Phase 0 baseline

The project directory was empty before setup. GitHub reported `sheikh2583/EZ-E-Commerce` as an empty public repository with `main` as its default branch. The published setup commit adds a one-line README and ignore rules. The resulting repository has no application code, dependencies, frontend, backend, database, authentication, tests, deployment configuration, or reusable components. The ignore rules are the initial security control. There is no inherited application stack or technical debt to migrate.

## Scope and assumptions

One Bangladesh-based business owns the catalogue and inventory. Customers can purchase as guests or create an account. A single administrative team manages the store. Plan for BDT, domestic delivery zones configured by staff, and a catalogue of at least 100 products. Use a neutral, configurable storefront identity until the business supplies branding. Sandbox checkout is the demo default. Live checkout requires a separately configured production environment and merchant approval.

The business will confirm the real delivery zones and fees, order cancellation and refund rules, tax and receipt requirements, and retention policies before commercial launch. Demo fixtures use synthetic data. An unpaid reservation will initially target 30 minutes for the demo, subject to provider session behavior and Phase 7 testing.

## Phase roadmap and requirements coverage

| Phase | Deliverable | Gate evidence |
| --- | --- | --- |
| 0 | Repository reconnaissance, architecture and schema proposal, stack decisions, roadmap, risk and testing plans | Repository checked, scope mapped, design reviewed and committed, then explicit human approval |
| 1 | Django project, dependency lock, environment settings, PostgreSQL connection, initial user migration, logging, input validation and responsive base | Startup, migration, environment loading, database smoke test, asset build and mobile layout pass |
| 2 | Relational models, migrations and at least 100 synthetic products | Fresh and upgrade migrations, constraints, persistence, rollback and concurrent stock tests pass |
| 3 | Registration, login, logout, profile, addresses, guest access and staff permissions | Password handling, sessions, direct endpoint permissions and guest access pass. Complete account order history and tracking with Phase 6 |
| 4 | Storefront navigation, banners, featured and new products, catalogue, product details and related items | Database-backed browsing, combined search and filters, sort, pagination, imagery and responsive availability pass |
| 5 | Persistent guest and account carts, quantity changes, discounts and login merge | Cart persistence, stock limits, price calculation and tampering cases pass |
| 6 | Guest and account checkout, delivery fees, orders, snapshots, inventory and tracking | Server repricing, order persistence, delivery snapshots, concurrent checkout and duplicate submit cases pass |
| 7 | SSLCOMMERZ sandbox and live configuration, callbacks, independent verification and reconciliation | Sandbox success, failure, cancel, replay and mismatch cases pass, or record the specific external blocker |
| 8 | Staff dashboard, catalogue and image management, inventory, order and tracking management, delivery zones and store settings | Staff operations and direct authorization checks pass. Revenue is based on verified live payments |
| 9 | Customer lifecycle and admin new-order email and SMS, templates, outbox and delivery statuses | Dedupe, provider failures, safe fallback and acceptance/delivery handling pass, or record the specific external blocker |
| 10 | Responsive, accessible storefront, accounts and staff flows, with loading, empty, error and success states | Desktop and mobile walkthroughs, keyboard flow and accessibility checks pass |
| 11 | Security and performance review and remediation | Critical and high findings resolved. Query, asset, callback, upload and session checks recorded |
| 12 | Browser journeys for guest, registered customer and staff | Complete journeys, including verified sandbox payment, and relevant regressions pass. Record an external blocker if the payment journey cannot be verified |
| 13 | Deployment configuration, runbook, health checks, admin setup, backup and restore, sandbox-to-live procedure | Production build, persistence, deploy checks, restore drill and sandbox evidence reviewed for handoff |

Each phase starts with a scoped plan and ends with applicable tests, documented results, diff and secret review, a dedicated commit, and a safe push to `origin/main`. See [TESTING.md](TESTING.md) for coverage and [IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md) for checkpoint state.

## Risk assessment

| Risk | Mitigation and owner action | Review by |
| --- | --- | --- |
| Gateway onboarding, account limits or callback access delay the demo or launch | Register sandbox access early in Phase 7. Confirm supported methods, settlement, merchant documents and any IP requirements with the provider. Use a labelled development fallback if sandbox access is blocked | 7, 13 |
| Duplicate, spoofed or late payments lead to incorrect fulfillment | Verify via provider API, enforce unique references, reconcile unknown outcomes and hold fulfillment for late or duplicate captures | 6–7 |
| Concurrent checkout or timeout cleanup oversells inventory | Lock rows in consistent order, reserve and release in transactions, test races with separate PostgreSQL connections | 2, 6–7 |
| Delivery fee or address changes affect historical orders | Reprice from the current zone during checkout and snapshot fee and address. Confirm location eligibility and ambiguous addresses with the business | 6, 8 |
| Staff permission errors, data leaks or unsafe uploads | Enforce permissions and ownership on the server, restrict uploads and access to order data, redact sensitive logs and exercise direct requests | 3, 8, 11 |
| Notification credentials, sender approval or ambiguous provider responses | Obtain sender approvals and verify domains, track accepted and delivered separately, cap retries and route unknown outcomes for reconciliation | 9, 13 |
| Hosting costs, latency or restore failures | Validate regional latency and quotes, size from load tests, rehearse database and media restoration before launch | 11, 13 |
| Public repository exposes sensitive business or demo data | Commit synthetic fixtures and placeholder configuration only. Inspect staged changes and use secret scanning during implementation | Every phase |
