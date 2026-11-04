# Architecture and technology decisions

Status: proposed for Gate 0 review.

## Technology decision record

| Area | Proposed choice and rationale | Alternative considered |
| --- | --- | --- |
| Frontend | Django templates, semantic HTML, responsive CSS and small JavaScript modules. The server renders catalogue pages and forms, while JavaScript enhances cart and checkout interactions | A React SPA would add a separate build and API contract for flows that can use server-rendered pages |
| Application | Python 3.13 and Django 5.2 LTS, pinned to a supported patch in Phase 1. Django provides forms, validation, CSRF, sessions, ORM, migrations and testing in one deployable app | Next.js with separate auth and ORM is viable when richer client-side interaction drives the design. Laravel is viable for a team already operating PHP |
| Database | PostgreSQL 17 with Django ORM and psycopg. Transactions, uniqueness and row locks support safe stock and payment updates. Use the same major version locally, in CI and on the host | SQLite is simpler to start but cannot exercise the PostgreSQL locking design. MySQL could support the workload but would require a different locking and constraint design |
| Authentication | Django sessions, built-in password handling and groups/permissions, with an email-based custom user created in the initial migration. Configure Argon2id and retain framework-supported password migration | Hosted identity adds a vendor and integration surface for basic customer accounts and staff roles |
| Media | Cloudinary for persisted product images, transformations and CDN delivery. Keep provider asset IDs in PostgreSQL. Local development can use filesystem media | S3-compatible storage offers more portability but needs image resizing and delivery configuration |
| Payments | SSLCOMMERZ hosted checkout, with explicit sandbox/live configuration, IPN and server-side validation. Use a small provider boundary | shurjoPay also documents hosted sandbox checkout and independent verification. Keep it as a fallback if onboarding terms or supported methods change |
| Messaging | Resend transactional API for email and MiMSMS transactional API for Bangladesh SMS. Both sit behind channel-specific adapters and use a PostgreSQL outbox | SMTP is broadly portable, but acceptance, dedupe and delivery event handling require more work. BulkSMSBD is a domestic SMS alternative |
| Deployment | Render web service with Gunicorn, managed PostgreSQL and a scheduled Django command. WhiteNoise serves versioned static assets. Store uploads externally | A VPS could reduce the invoice but transfers patching, backup and runtime ownership to the business |
| Testing | Django test runner, PostgreSQL integration tests and Playwright for core journeys. Ruff for lint and a Python type checker for service boundaries | A second test framework is optional if the initial test runner proves insufficient |

Primary sources for the proposed stack. [Django support](https://www.djangoproject.com/download/), [Django deployment checklist](https://docs.djangoproject.com/en/5.2/howto/deployment/checklist/), [PostgreSQL locking](https://www.postgresql.org/docs/17/explicit-locking.html), [Cloudinary plans](https://cloudinary.com/pricing), [SSLCOMMERZ API](https://developer.sslcommerz.com/doc/v4/index.html), [shurjoPay API](https://shurjopay.com.bd/frontend-developers/direct-integration-with-api), [Resend pricing](https://resend.com/pricing), [MiMSMS API](https://apidoc.mimsms.com/), [Render pricing](https://render.com/pricing).

## Boundaries

- Storefront and account views render Django templates. Validated same-origin POST endpoints handle cart, checkout and account mutations. Views delegate pricing, stock and status transitions to domain services.
- Catalogue, accounts, carts, orders, payments and notifications share one database. Store management begins with a customized Django admin for routine data edits, plus dedicated staff views for operational reports and order transitions. Restrict generic edits to payment and historical order data.
- The application calls external payment, media and notification APIs from the server. Browser payment returns show the stored result or a pending screen. Provider callbacks and scheduled reconciliation feed the same verification service.
- Scheduled Django commands expire eligible reservations, reconcile provider state, and process queued notifications. No external broker is required at the proposed scale. Each command uses bounded batches and retries.
- Use HTTPS, secure and HTTP-only session cookies with an explicit SameSite policy, CSRF on browser mutations, per-route rate limits, ORM parameter binding, template escaping and least privilege. Limit CSRF exemptions to provider endpoints with provider-specific verification. Validate image dimensions and size, decode and re-encode allowed raster formats, strip metadata and restrict uploads to staff.

## Proposed PostgreSQL schema

Columns below describe the intended model. Phase 2 will define migrations and verify constraints. Primary keys are internal big integers unless noted. Use UTC timestamps and integer minor units for money. Render prices in BDT. Keep required amounts nonnegative and quantities positive.

| Entity | Key fields and constraints |
| --- | --- |
| User, Group, Permission | Normalized case-insensitive unique email, password hash, active and staff flags. Django group and permission joins distinguish customer, fulfilment, catalogue and store administration privileges |
| Address | User FK, recipient, phone, address lines, locality, postcode, optional delivery zone FK. Private to its owner |
| Category | Unique slug, display name, active flag and ordering |
| Product | Category FK, unique SKU and slug, name, description, regular and optional sale price, stock on hand, reserved stock, active and featured flags, timestamps. Sale price below regular price. Reserved quantity between zero and on-hand stock |
| ProductImage | Product FK, unique provider asset ID, alt text, display position. Unique product and position |
| Cart, CartItem | Cart has optional user FK, opaque guest token digest, lifecycle status and expiry. Partial uniqueness allows one open cart per user and one open cart per guest token. A cart item references cart and product, with one row per pair |
| DeliveryZone, StoreSettings | Zone has a unique code, display label, fee and active flag. Singleton store settings hold business contacts, branding and basic promotional content |
| Order | Unique random public reference, optional user FK, originating cart, checkout key and request fingerprint, customer and delivery snapshots, nullable zone FK, subtotal, discount, delivery and total, independent order and payment states, tracking details, timestamps. Unique checkout key scoped to cart. Check total equals subtotal minus discount plus delivery |
| OrderItem | Order FK, optional product FK, immutable name/SKU, quantity, regular and charged unit prices. Store one line per SKU in an order and preserve it if a product is removed |
| InventoryReservation | Order item FK, unique per item, product FK, held/consumed/released state and expiry. Keep referenced products via soft deactivation |
| PaymentAttempt, PaymentEvent | Attempt references order and records provider, mode, unique merchant transaction reference, optional unique provider transaction ID, amount, currency and state. Limit to one in-flight attempt per order. Append sanitized provider event outcomes with a dedupe key. Link the order's accepted payment explicitly and flag additional captures for review |
| OrderStatusEvent | Order FK, optional actor FK, prior and new state, reason, timestamp and unique event identity for downstream notifications |
| Notification | Order FK, source event identity, channel, recipient, template, state, provider message ID, attempts, next attempt and lease expiry. Unique source event, channel and recipient to dedupe |

Index foreign keys where an existing unique or composite index does not cover them. Start with catalogue indexes for active category/price and pagination, order indexes by customer/time and status/time, and partial indexes for pending reservations and outbox work. Use a case-insensitive name search with stable tie-breaking and pagination. Assess trigram indexing with `EXPLAIN` if measured catalogue growth warrants it. Use protective deletes for commerce history and deactivate products or zones by default. Cart and address cleanup can remove ephemeral data independently of order snapshots.

## Transaction and state rules

1. The server merges guest and account carts under lock, caps quantities by current availability and rotates the guest identity on login. Checkout validates the actor, checkout key and fingerprint, then locks the cart and relevant rows. A repeat with the same key and payload returns the existing order. A changed payload under that key returns a conflict.
2. Checkout reads the active zone and locks products in ascending ID order. In a single transaction it recomputes the totals, snapshots address, zone and prices, creates the order and reservations, and closes the cart. A stale quote prompts customer review. Failed validation rolls back the order and reservations together. Available stock equals on-hand minus reserved.
3. Payment verification runs outside database locks. The subsequent transaction locks the order, attempt and affected products in a consistent sequence. Verified payment consumes the reservation and decrements on-hand and reserved quantities. Confirmed failure, cancellation or eligible expiry releases reserved stock once. Staff inventory adjustments respect held quantities.
4. Order state progresses through pending, confirmed, processing, shipped and delivered, with cancellation controlled by the current state and payment/refund policy. Payment state is separate and supports unpaid, pending verification, paid, failed and refunded. A paid cancellation requires refund reconciliation and a single stock adjustment for unshipped goods. Restocking shipped goods requires a confirmed return. A late capture after release or a second capture creates a review item and blocks automatic fulfillment. Authorized staff reconcile or refund based on verified provider evidence. Sandbox captures are excluded from live revenue.
5. State changes and notification rows commit together. The scheduled command leases jobs, calls providers outside the transaction, and records accepted, delivered, failed, unknown or suppressed. Retry safe failures with backoff and stable provider idempotency keys when supported. Reconcile ambiguous sends before retrying when the provider cannot deduplicate them. Acceptance is recorded separately from delivery confirmation.

Registered customers access orders by authenticated ownership. Guests access their order in the checkout session, with an expiring signed link in the confirmation email once Phase 9 lands. The public order reference alone grants no access.
