# Deployment runbook

The Render Blueprint, build, migration, startup and maintenance scripts are ready for a demo deployment. This runbook separates the locally verified release from the hosted checks that require account access and provider credentials.

## Environments and configuration

- Local and CI use PostgreSQL 17 and synthetic data. Local images may use filesystem storage. Provider tests use fakes by default, with explicitly opted-in sandbox verification.
- Demo uses a Render web service, a separate managed PostgreSQL database, external product image storage and scheduled Django tasks when needed. Publish the demo with HTTPS and SSLCOMMERZ sandbox credentials.
- Live uses a separate database, media scope, secrets and callback URLs. Start with an empty production catalogue and configure real delivery zones and fees. Apply migrations as a controlled release step and create the first administrator through an authenticated, audited command.
- Configure database URL, Django secret key, public host and trusted origins, media credentials, payment mode and credentials, email sender/domain and SMS sender credentials in the hosting secret store. Keep `.env.example` limited to placeholders. Scope provider credentials by environment and restrict database access to the application and scheduled commands.
- Before handoff, exercise the production build, static asset collection, HTTPS, liveness and database readiness, migrations, durable product images, scheduled jobs and a database restore. Define retention and recovery objectives with the business, verify media backup or export, and document rollback and incident response. [Django deployment checklist](https://docs.djangoproject.com/en/5.2/howto/deployment/checklist/), [Render recovery and backups](https://render.com/docs/postgresql-backups).

## Budget estimate

Provider list prices reviewed on 4 November 2026. These estimates assume a low-volume deployment. Recheck them at provisioning and validate sizing in Phase 11.

| Item | Estimate and assumptions |
| --- | --- |
| Render | US$7/month starter web service, US$6/month entry paid PostgreSQL compute, US$0.30/GB/month database storage and at least US$1/month for one scheduled service. Budget about US$15–20/month for base hosting at low usage. A 1 GB database compute tier raises this estimate by about US$13/month. [Render pricing](https://render.com/pricing), [storage pricing](https://render.com/articles/how-much-does-cloud-application-hosting-cost-for-small-businesses), [cron pricing](https://render.com/docs/cronjobs#compute-plans-and-billing) |
| Product media and email | Cloudinary has a US$0 tier with 25 monthly credits. Resend has a US$0 tier with a daily send cap. Track usage and validate eligibility before relying on these tiers for production. [Cloudinary pricing](https://cloudinary.com/pricing), [Resend pricing](https://resend.com/pricing) |
| SMS | MiMSMS advertises bulk rates starting at BDT 0.25 per SMS. Confirm the transactional rate, minimum purchase, sender approval, taxes and segment pricing with the provider. [MiMSMS](https://www.mimsms.com/) |
| Payments | SSLCOMMERZ lists a BDT 25,500 one-time Basic setup fee and 2.5% per successful transaction, with 3.5% for American Express. Confirm the merchant quote and settlement terms. [SSLCOMMERZ pricing](https://sslcommerz.com/pricing/) |

Domain registration, separate demo and production instances, taxes, overages and paid provider tiers add to the estimate.

## Notification configuration

Set `RESEND_API_KEY` and a verified `RESEND_FROM` sender. Set `MIMSMS_USERNAME`, `MIMSMS_API_KEY` and the approved `MIMSMS_SENDER` for transactional SMS, and confirm MiMSMS permits the scheduled job's outbound IPs and domain. Optionally set `NOTIFICATION_ADMIN_EMAIL` and `NOTIFICATION_ADMIN_PHONE` for new-order alerts. Use the public HTTPS origin for links in email. Run `python manage.py send_notifications` periodically.

Outbox rows distinguish queued, accepted, suppressed, failed and unknown. Acceptance includes a provider reference and represents provider intake. Confirm actual delivery in the provider dashboard. Suppressed rows require an intentional resend decision after configuration. Investigate unknown sends before retrying, especially SMS. Use synthetic recipients in tests. [Resend idempotency behavior](https://resend.com/changelog/idempotency-keys), [MiMSMS v2 API](https://apidoc.mimsms.com/).

## Security operations

The application limits sensitive POST endpoints using PostgreSQL counters shared across processes. Schedule `python manage.py prune_rate_limits`. By default, source limits use the socket address. Set `DJANGO_FORWARDED_FOR_HOPS` only behind verified, trusted ingress and test with two independent client IPs and a forged forwarding prefix before enabling public traffic. Set `DJANGO_TRUST_HTTPS_PROXY=1` only when the ingress controls `X-Forwarded-Proto`. HSTS applies to the storefront host. The deployment check reports advisory warnings for including subdomains and preloading. Those settings depend on ownership and HTTPS readiness of the wider domain.

Private guest access tokens stay in the browser URL fragment and are submitted with CSRF protection. They expire 30 days from order creation. Treat any manually copied access code as private. The application accepts only JPEG, PNG and WebP images, enforces byte and pixel limits, and re-encodes uploads before serving them. [Render proxy guidance](https://render.com/articles/how-render-handles-ddos-attacks), [Django deployment checks](https://docs.djangoproject.com/en/5.2/howto/deployment/checklist/).

## Deploy the demo on Render

1. Connect the GitHub repository to Render and create a Blueprint from `main` using [render.yaml](render.yaml). Review the paid web service, paid PostgreSQL 17 instance and scheduled maintenance job before provisioning. Git pushes do not automatically deploy with the supplied Blueprint.
2. Confirm the demo web host and trusted ingress settings. The generated secret seed is shared by the web and maintenance services. Keep that seed private and stable. Use `DJANGO_ALLOWED_HOSTS` for custom domains. Update `PUBLIC_BASE_URL` to the canonical HTTPS origin once the domain is working. The app includes Render's assigned external hostname automatically on the web service.
3. The build installs the production lock and collects static files. Pre-deploy runs migrations and prepares the three staff groups. The platform readiness probe calls `/readyz`; `/healthz` checks that the process is serving. Check Gunicorn and maintenance output for errors.
4. Open the web service shell and run `uv run --no-sync python manage.py createsuperuser` interactively. Use a unique password and a named administrator account. Assign operational accounts only the staff roles they need. Set the store name, contacts and delivery fees in the admin area.
5. Configure a demo Cloudinary scope for uploads. Test that an uploaded image remains accessible after a web redeploy. Configure SSLCOMMERZ sandbox mode as described in [PAYMENT_INTEGRATION.md](PAYMENT_INTEGRATION.md). To seed the hosted sandbox, run `uv run --no-sync python manage.py seed_demo --allow-hosted-sandbox`. This command refuses to run in live mode.
6. Exercise a real sandbox payment through the public callback path, then verify payment status and inventory in the staff area. Confirm that the scheduled job processes reservations, gateway reconciliation, notifications and expired rate counters. Add sender credentials only when test recipients and providers are approved.

Use the Render domain setup flow for a custom domain. Publish the exact DNS records Render supplies, wait for certificate issuance, verify HTTPS, and update the canonical origin, allowed hosts and callback settings. [Render Blueprint reference](https://render.com/docs/blueprint-spec), [custom domains](https://render.com/docs/custom-domains).

## Backups, rollback and operational checks

- Use Render Postgres point-in-time recovery and export encrypted logical backups to business-controlled storage under the agreed retention policy. Periodically restore into an isolated database and verify schema, order and product counts, and representative order totals. Back up the Cloudinary product assets separately and test restoring their mappings.
- Before a release, review migration compatibility with the currently running version and take a recoverable backup. For an application regression, redeploy the last verified commit if its schema is compatible. For a data or schema failure, restore into a separate database, verify it and only then switch the application connection. Retain incident records and reconcile any intervening payments before resuming fulfillment.
- Review staff payment flags and unknown notification sends routinely. A failed or cancelled provider-confirmed payment releases held stock once. Pending attempts with an unknown outcome require provider reconciliation. Staff can cancel unpaid orders without an unresolved attempt. Paid cancellations require merchant refund and inventory reconciliation.
- Monitor readiness, errors, rate-limit volume, reconciliation age, notification failures and storage usage. Keep real customer data, exports and credentials out of Git. Apply dependency security updates through the test suite and release checks.

## Live cutover

Provision a distinct live database, media scope, public domain and environment group. Start with real products, shipping rules and branding. Verify merchant onboarding, settlement channels and refund handling. Set `PAYMENT_MODE=live` and the live store credentials in the live environment only. Verify DNS, TLS, staff access, backups, callbacks, provider acceptance and customer support procedures. Record the first merchant-approved live transaction and independently reconcile it before widening access.

The production-mode build, Gunicorn startup, deployment schema and local database restore have been verified. Live hosting, public sandbox callbacks, persistent Cloudinary uploads and external email/SMS acceptance remain unverified until the accounts and configuration are available.
