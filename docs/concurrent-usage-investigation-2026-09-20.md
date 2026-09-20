# Concurrent usage investigation — 20 September 2026

## Scope and limits

Reviewed request middleware, database admission control, fiscal-year initialization, dashboard caching, session writes, telemetry, realtime streaming, worker configuration and browser mutation processing. Exercised dashboard, My Plan, Schools and Analytics concurrently and ran the existing 27-combination role/page latency sweep. This is a local investigation, not confirmation of the production incident's cause or an audit of every endpoint.

Production credentials/log access were unavailable. Local PostgreSQL host is loopback. No load was sent to production. Local data: 706 schools, 292 activities, 48 users. Measurements below are short exploratory samples on a shared developer machine, not production capacity estimates or a controlled before/after benchmark.

## Reproduction

| Local ASGI configuration | Simultaneous requests | Accounts | Responses | Overall p95 | Throughput |
| --- | ---: | ---: | ---: | ---: | ---: |
| One worker, six active database requests | 12 | 1 PL | 121/121 HTTP 200 | 3,977 ms | 7.30 requests/s |
| Three workers, six active requests each | 12 | 1 PL | 117/117 HTTP 200 | 3,787 ms | 7.43 requests/s |
| Three workers, six active requests each | 12 | PL, CCEO, CD | 261/261 HTTP 200 | 2,094 ms | 10.23 requests/s |

The 1,500 ms load-probe target failed in all three runs despite zero HTTP errors. More workers alone did not resolve latency. The separate single-request sweep passed all 27 permitted page/role budgets, with two measured samples per combination: useful screening, insufficient for a stable tail-latency estimate.

Four snapshots of pg_stat_activity during the multi-account run showed no Lock wait events. This does not exclude transient locking or production database exhaustion. A profiled warm My Plan request spent about 201 ms in 30 SQL executions (375 ms total with profiler overhead); planning context construction accounted for 283 ms.

## Confirmed defects and changes

1. FiscalYearRolloverMiddleware lacked synchronization. Multiple simultaneous first requests per worker could all execute ensure_current_fiscal_year, which takes a database row lock. A threaded regression failed before the fix because the second login waited for the same work. A nonblocking process lock now allows one attempt; other requests proceed, and failure backoff remains. Cross-process database serialization remains intentional for correctness. This fixes a startup/year-boundary risk, not a proven explanation for every freeze.
2. My Plan issued nine separate count queries for period/type/completion KPIs. Replaced them with two filtered aggregates, preserving ownership, period, status, upcoming-date and activity-type conditions. No cross-user response cache or stale plan data was introduced. Compared old and new KPI outputs across 18 combinations (three roles and six filter selections): all identical. A warmed PL context dropped from 25 SQL queries to 18.
3. SchoolIdentityMiddleware performed its post-render database lookup outside the database admission guard. Moved it inside the guard so those response-time queries count toward the same connection budget as view queries.
4. The read probe previously modeled only one account. Added repeatable --additional-email so role-specific scopes and caches are exercised separately. Each account is warmed independently; workers retain separate cookies.

Earlier local changes bounded the overload queue, aligned Procfile worker defaults with Docker, prevented automatic retry of writes, and skipped chart/map internal mutation scans. They are still uncommitted and undeployed.

## Reproduce in an isolated environment

Start ASGI against a local/test database with WEB_MAX_CONCURRENT_REQUESTS=6. Run scripts/concurrent_read_probe.py with an explicit local base URL, --email pl1@edify.org, --additional-email cceo1@edify.org, --additional-email cd@edify.org, --concurrency 12, --duration 25 and paths /dashboard /my-plan /schools /analytics. Existing test accounts are required. The probe creates sessions; requests under pressure are GETs. Stop the isolated server afterward.

## Required to finish production diagnosis

Obtain the freeze timestamp and hosting logs/metrics. Correlate route latency and queue waits with CPU/memory, worker termination/restart events, database connections/locks and slow queries, Redis availability, replica count and actual startup command. Review synchronous telemetry/incident writes if database latency spikes. Size workers against measured memory and the shared database budget, including rolling deployments and scheduler. Do not infer live configuration from repository deployment templates.

## Verification completed

- 58 tests passed across the 15,000-school scale gate, analytics query checks, realtime transport/stream caps, cache behavior, rollover concurrency, admission control and probe transport.
- After moving school-ID response work inside the admission guard, all 11 focused concurrency/rollover checks passed again.
- Old/new My Plan KPIs matched across 18 local role/filter combinations; warmed planning context SQL count fell from 25 to 18.
- Python compilation, Ruff checks on changed Python code and git diff whitespace checks passed.
- Test-only ASGI processes were stopped. No deployment or production load test was performed. Concurrent latency targets remain unmet in the exploratory local runs; live freeze resolution is unconfirmed.
