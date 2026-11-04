# Payment integration plan

## Provider and onboarding

Propose SSLCOMMERZ hosted checkout for Bangladesh. Its published channels include cards, bKash, Nagad and Rocket. Confirm which channels and settlement terms the merchant account enables. Create a sandbox store for Phase 7 and configure an externally reachable HTTPS IPN endpoint. For live operation, complete the provider's merchant onboarding and confirm business documentation, settlement account, refund workflow and public-IP requirements for any enabled operations. Keep sandbox and live credentials separate. [Developer documentation](https://developer.sslcommerz.com/doc/v4/index.html), [sandbox registration](https://developer.sslcommerz.com/registration/), [merchant signup and pricing](https://sslcommerz.com/pricing/).

shurjoPay is the fallback candidate because it also offers separate test/live environments and server-side transaction verification. Confirm its onboarding terms and required payment methods if a switch becomes necessary. [shurjoPay REST API](https://shurjopay.com.bd/frontend-developers/direct-integration-with-api).

## Proposed configuration and processing

- Use `PAYMENT_MODE` with explicit `sandbox` or `live`, plus `SSLCOMMERZ_STORE_ID`, `SSLCOMMERZ_STORE_PASSWORD` and `PUBLIC_BASE_URL`. Map modes to approved provider hosts in server code. Require a stable HTTPS base URL for deployed callbacks.
- Start a hosted session only after the order is committed. Use the attempt's unique merchant transaction reference and amount from the order. Persist the reference before initiating the external call. On an unknown initiation outcome, reconcile by merchant reference before allowing a replacement.
- Treat browser returns and IPN payloads as inputs to verification. Use the Order Validation API and compare provider status, transaction reference, exact amount and currency against the stored attempt. A successful documented result (`VALID` or `VALIDATED`) with matching data and no risk hold can finalize payment. Queue risk holds and discrepancies for staff review. Amount conversions or currency mismatches require explicit handling before acceptance.
- Use the provider's Transaction Query API for reconciliation after timeouts, missing callbacks or an uncertain expiry. Before releasing an attempt's reservation, require a definitive terminal outcome or a reviewed expiry policy supported by sandbox evidence. Leave unknown cases pending and alert staff. A valid capture after release is recorded and held for manual resolution. Repeated callbacks use the same verification and state transition path.
- Store a sanitized event trail with transaction identifiers, outcomes and timestamps. Redact provider request URLs and query strings because validation can put secrets there. Keep card details, raw provider payloads and credentials out of application records and logs.
- Run demo payments with sandbox credentials. If access is unavailable, use an explicitly labelled development-only fake with distinct simulated results. A fake result cannot enter the verified paid state or revenue metrics.

## Phase 7 evidence

Test real sandbox success, failure and cancellation. Record gateway evidence for invalid, repeated, late and mismatched callbacks, missing notifications, pending reconciliation, verification timeouts and unknown initiation. Confirm reservation behavior, audit events and repeat delivery of notification inputs. Phase 7 must document any provider operation that could not be exercised and why.
