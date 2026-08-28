# Load, reliability, and failure-injection report

## Completed local evidence

| Area | Result |
|---|---|
| Scale tests | 21 passed at 15,000 schools plus 3,000 growth records |
| Reliability/cache/jobs/integrations group | 138 passed |
| Security/upload group | 126 passed |
| Deep route crawl | 8 passed; all registered routes resolved under supported contracts |
| Demo seed replay | Passed twice with identical fixture counts |
| Browser release suite | 27 passed, 75 deliberate skips, 0 unexpected/flaky |
| Production public smoke | Passed across configured desktop/mobile/tablet profiles |

Existing failure-injection tests cover cache unavailability, request-cache behavior, dependency/readiness failures, storage failure handling, integration/outbox behavior, job retry and locking, scheduler behavior, and realtime reliability. The readiness endpoint differentiates local cache fallback as `unshared`; production reported shared cache `up` at test time.

The suite also exercises idempotency and conflict behavior across core workflows. The demo seed was hardened to avoid global destructive deletes and to update deterministic fixture records in place, including SSA records protected by activity references.

## Not a capacity or soak result

No production-equivalent environment was supplied. Therefore no concurrency, throughput, p50/p99, CPU, memory, connection, queue-delay, stress-limit, spike-recovery, or extended-soak measurements are reported. Running those tests against production would violate the stated safety rules without a maintenance window and owner approval.

## External reliability not end-to-end verified

No real sandbox credentials were available for Salesforce, NetSuite, lending-partner APIs, email/SMS delivery providers, maps, payments, or object storage. Contract/failure tests pass locally, but actual sandbox latency, retry, idempotency, replay, and monitoring remain unverified.

