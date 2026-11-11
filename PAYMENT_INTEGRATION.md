# Payment integration

## Stripe Checkout through LCT PaP

Select your business and the **Sandbox** environment in the PaP workspace picker. Use the same workspace for the API key, grant and webhook. [PaP integration values](https://pap.ezassist.me/api-documentation#integration-values)

1. Have the merchant owner create a Developer key under **Integration → API keys**. Save it as `LCT_API_KEY`.
2. Go to **Commercial & launch → Capabilities**. Open the active Stripe one-time card route that supports BDT. Expand **Integration identifiers** and copy **Capability grant ID** into `LCT_ONE_TIME_GRANT_ID`. Confirm that the grant lists the storefront's public HTTPS origin under **Return origins**. If the route is unavailable, request a new Stripe sandbox capability under **Integration → API & checkout → Request a capability**.
3. Open **Integration → API & checkout → Payment API**. Copy **Merchant ID** into `LCT_MERCHANT_ID`.
4. Go to **Integration → Webhooks → Endpoints → Add endpoint**. Enter `<PUBLIC_BASE_URL>/payments/pap/webhook/` and select `payment.created`, `payment.processing`, `payment.succeeded`, `payment.failed` and `payment.expired`. Create the endpoint and save the displayed `whsec_` value as `LCT_WEBHOOK_SECRET`. If you lost the secret for an existing endpoint, use **Rotate key** and update the receiver.

Set these values in the application's environment. On Render, use the environment group shared by the web service and maintenance job.

```dotenv
PAYMENT_PROVIDER=pap
PAYMENT_MODE=sandbox
PUBLIC_BASE_URL=https://shop.example.com
LCT_CHECKOUT_PROVIDER=stripe
LCT_API_KEY=
LCT_ONE_TIME_GRANT_ID=
LCT_MERCHANT_ID=
LCT_WEBHOOK_SECRET=
```

Deploy the app with these settings. The Render release script applies the migration. On other hosts, run `uv run --no-sync python manage.py migrate`. Once the public endpoint is reachable, select **Verify endpoint** in PaP. The existing `scripts/maintenance.sh` job processes webhooks and reconciles payments. On other hosts, schedule `uv run --no-sync python manage.py reconcile_payments` to run periodically. [PaP webhook verification](https://pap.ezassist.me/api-documentation#webhooks)

1. The order page creates a local attempt and saves separate UUIDs for the payment and checkout requests. The backend sends the saved order reference, total in minor units and currency to `POST /v1/payments`.
2. With the returned payment ID, the backend creates a Stripe Checkout session using `POST /v1/payments/{paymentId}/checkout`. It opens `checkoutUrl` when the session state is `ready`. A retry reuses the saved request key and parameters. Success and cancellation return to `/payments/pap/return/<order-reference>/`.
3. The return handler reads `GET /v1/payments/{paymentId}`. The webhook handler verifies the signature and stores events by ID. The maintenance job reads the latest payment status for those events and reconciles pending attempts when a return or notification is missing.
4. `succeeded` with the expected payment ID, order reference, amount and currency marks the order paid and consumes reserved stock once. Confirmed `failed` or `expired` results release stock. A browser cancellation can leave the checkout open and the order pending. A mismatched successful payment or a capture after the reservation was released goes to staff review.

For live PaP, use `PAYMENT_MODE=live`, live workspace credentials and an active Stripe one-time grant that supports the order currency. Complete a sandbox checkout and verify the webhook and maintenance job before switching environments. Reconcile outstanding attempts before changing the active gateway, mode or merchant account.

## Direct SSLCOMMERZ integration

Select `PAYMENT_PROVIDER=sslcommerz` to use the existing direct integration.

### Provider and onboarding

Propose SSLCOMMERZ hosted checkout for Bangladesh. Its published channels include cards, bKash, Nagad and Rocket. Confirm which channels and settlement terms the merchant account enables. Create a sandbox store for Phase 7 and configure an externally reachable HTTPS IPN endpoint. For live operation, complete the provider's merchant onboarding and confirm business documentation, settlement account, refund workflow and public-IP requirements for any enabled operations. Keep sandbox and live credentials separate. [Developer documentation](https://developer.sslcommerz.com/doc/v4/index.html), [sandbox registration](https://developer.sslcommerz.com/registration/), [merchant signup and pricing](https://sslcommerz.com/pricing/).

shurjoPay is the fallback candidate because it also offers separate test/live environments and server-side transaction verification. Confirm its onboarding terms and required payment methods if a switch becomes necessary. [shurjoPay REST API](https://shurjopay.com.bd/frontend-developers/direct-integration-with-api).

### Configuration and processing

- Use `PAYMENT_MODE` with explicit `sandbox` or `live`, plus `SSLCOMMERZ_STORE_ID`, `SSLCOMMERZ_STORE_PASSWORD` and `PUBLIC_BASE_URL`. Map modes to approved provider hosts in server code. Require a stable HTTPS base URL for deployed callbacks.
- Start a hosted session only after the order is committed. Use the attempt's unique merchant transaction reference and amount from the order. Persist the reference before initiating the external call. On an unknown initiation outcome, reconcile by merchant reference before allowing a replacement.
- Treat browser returns and IPN payloads as inputs to verification. Use the Order Validation API and compare provider status, transaction reference, exact amount and currency against the stored attempt. A successful documented result (`VALID` or `VALIDATED`) with matching data and no risk hold can finalize payment. Queue risk holds and discrepancies for staff review. Amount conversions or currency mismatches require explicit handling before acceptance.
- Use the provider's Transaction Query API for reconciliation after timeouts, missing callbacks or an uncertain expiry. Before releasing an attempt's reservation, require a definitive terminal outcome or a reviewed expiry policy supported by sandbox evidence. Leave unknown cases pending and alert staff. A valid capture after release is recorded and held for manual resolution. Repeated callbacks use the same verification and state transition path.
- Store a sanitized event trail with transaction identifiers, outcomes and timestamps. Redact provider request URLs and query strings because validation can put secrets there. Keep card details, raw provider payloads and credentials out of application records and logs.
- Run demo payments with sandbox credentials. If access is unavailable, use an explicitly labelled development-only fake with distinct simulated results. A fake result cannot enter the verified paid state or revenue metrics.

### Phase 7 evidence

Test real sandbox success, failure and cancellation. Record gateway evidence for invalid, repeated, late and mismatched callbacks, missing notifications, pending reconciliation, verification timeouts and unknown initiation. Confirm reservation behavior, audit events and repeat delivery of notification inputs. Phase 7 must document any provider operation that could not be exercised and why.

### Configuring and exercising the implementation

Set `PAYMENT_MODE=sandbox` with sandbox store credentials and the application's public HTTPS origin in `PUBLIC_BASE_URL`. Register `/payments/ipn/` as the IPN listener. The checkout session sets `/payments/return/` for customer success, failure and cancellation. Run `python manage.py reconcile_payments` periodically. Unknown or missing gateway results stay pending. Staff must investigate long-running unknown cases and review flags. Release a reservation only after a confirmed terminal outcome or when payment was never initiated and the reservation expired.

For local-only testing, run with `DJANGO_DEBUG=1 PAYMENT_MODE=simulation`. The order screen labels the simulation, records a distinct attempt state, and releases the reservation. Production settings reject simulation and debug settings reject live payments. `PAYMENT_MODE=disabled` is the default. Switch to live using a separate environment and merchant credentials, then exercise callback reachability and provider acceptance under the merchant's approved launch procedure.

Phase 7 executed the application against controlled provider HTTP responses for success, failure, cancellation, wrong references, amount mismatch, gateway unavailability, duplicate callbacks and late or extra captures. Live network verification against the sandbox remains **externally blocked** by merchant test credentials and a public HTTPS callback endpoint.
