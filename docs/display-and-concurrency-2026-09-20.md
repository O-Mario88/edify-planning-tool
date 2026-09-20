# Display density and busy-period resilience

## Changes

- Desktop form controls use 38 CSS pixels and 14px text; mobile keeps 44px controls and 16px text. No inverse device-pixel-ratio scaling or forced zoom. Windows accessibility scaling and browser zoom remain user-controlled.
- Removed font-size-adjust from the body to avoid fallback-font metric adjustments changing apparent typography across systems. Shared bundled font remains in use.
- UI enhancement observer ignores internal ApexCharts and Leaflet pane mutations. Application controls outside those internal rendering surfaces remain observed.
- Procfile now uses the same configurable three-worker and timeout defaults as Docker, instead of relying on Gunicorn's one-worker default. WEB_CONCURRENCY still overrides this. This default requires the existing documented 2 GiB instance budget; smaller instances must set a lower value.
- Database guard queue is bounded to WEB_MAX_QUEUED_REQUESTS (24 per process by default). Existing active-request limits and queue timeout remain. Requests beyond the queue return 503 with Retry-After and no-store. Failed writes never receive an automatic refresh.

## Operational verification still needed

Local tests verify overload refusal and recovery, not production throughput or the cause of a specific outage. Compare freeze timestamps with request queue warnings, worker restarts, CPU/RSS, PostgreSQL connection use, lock waits and slow queries. Confirm instance count and memory before deployment. Budget total database connections across workers, replicas, rolling-deploy overlap and scheduler; do not increase worker count without that check. Load-test staging using representative authenticated read journeys before increasing capacity. Do not load-test production without a planned window.
