# Production monitoring report

## Observed

- Public liveness and readiness endpoints responded successfully on `https://www.edifyplanning.app`.
- Production readiness reported `db: up` and `cache: up` at the validation time.
- Local readiness correctly reported `cache: unshared` while Redis was unavailable and the application used per-process LocMemCache.
- Existing tests cover correlation/audit failure behavior, scheduler health, dependency readiness, and job locking/retry semantics.

## Monitoring added in this change

No new external monitoring vendor, dashboard, or alert was provisioned. The repository gained CI browser gates and retained browser failure artifacts, which improve pre-deployment detection but are not production observability.

## Required before GO

- Owner-accessible dashboards for route latency/status, database/query time, Redis, CPU/memory, connections, queue delay, scheduler/jobs, integrations, HTMX failures, JavaScript errors, uploads, and Core Web Vitals.
- Tested alerts for 5xx/latency spikes, readiness, Redis/database/scheduler failure, queue backlog, integration/upload/browser errors, authentication anomalies, and duplicate-payment protection.
- Low-volume authenticated synthetic journeys isolated from operational analytics and external side effects.
- Named operational owners and escalation/runbook links for every alert.

The absence of direct dashboard and alert evidence is a release blocker under the requested standard.

