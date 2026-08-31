# Production monitoring report

## Observed

- Public liveness and readiness endpoints responded successfully on `https://www.edifyplanning.app`.
- Production readiness reported `db: up` and `cache: up` at the validation time.
- Local readiness correctly reported `cache: unshared` while Redis was unavailable and the application used per-process LocMemCache.
- Existing tests cover correlation/audit failure behavior, scheduler health, dependency readiness, and job locking/retry semantics.

## Monitoring added in this change

No new external monitoring vendor, dashboard, or alert was provisioned. The repository gained CI browser gates and retained browser failure artifacts, which improve pre-deployment detection but are not production observability.

## Live monitoring update — 2026-08-29

The statement above is retained as the evidence from the original validation
run. It is no longer the current platform state.

- DigitalOcean Uptime check `e0084876-47de-467c-bcb8-324a128744ef` is enabled
  against `https://edifyplanning.app/api/health/ready` from `eu_west`,
  `us_east`, `us_west`, and `se_asia`.
- Global unavailability alert `9228ce39-80d6-430b-b6ec-1318fa85c5af` triggers
  after two minutes.
- Sustained-latency alert `2c40dfaa-133f-41aa-9cb3-aa14ba8a1e7a` triggers when
  readiness exceeds the documented 3,200 ms degraded ceiling for five minutes.
- TLS-expiry alert `49eda02e-81c2-4200-aabd-2bfa38b918c9` triggers within 30
  days of certificate expiry.
- All three alerts route to the same account email already receiving the live
  App Platform and managed-database resource alerts. The email is intentionally
  omitted from this repository record.
- App Platform separately has active deployment-failure, domain-failure,
  restart-count, CPU, and memory alerts for web and scheduler. Managed database
  CPU, memory, and disk alerts are active.
- `scripts/configure_uptime_monitoring.sh` reconciles this state. It deliberately
  avoids `doctl monitoring uptime update`: doctl v1.167.0 was observed setting
  `enabled=false` during an update even though its help says it cannot disable
  checks. The script uses the documented API with `enabled=true` and verifies
  the resulting state.

This closes the absence of an external availability dashboard and alert rules.
It does **not** close the full operations gate: alert delivery has not been
deliberately triggered and the organisation has not named the accountable
incident owner or escalation substitute.

## Required before GO

- Extend the now-active availability and resource dashboards to route latency/status, database/query time, Redis, connections, queue delay, scheduler/jobs, integrations, HTMX failures, JavaScript errors, uploads, and Core Web Vitals.
- Tested alerts for 5xx/latency spikes, readiness, Redis/database/scheduler failure, queue backlog, integration/upload/browser errors, authentication anomalies, and duplicate-payment protection.
- Low-volume authenticated synthetic journeys isolated from operational analytics and external side effects.
- Named operational owners and escalation/runbook links for every alert.

The remaining alert-delivery and ownership evidence is a release condition under the requested standard.
