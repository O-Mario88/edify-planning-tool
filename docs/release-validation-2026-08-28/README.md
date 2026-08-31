# Release validation decision — 2026-08-28

> **APPROVED WITH CONDITIONS — infrastructure update**

The original audit below correctly recorded a No-Go when no recoverable
production backup, retained runtime logs, production-equivalent staging, or
database standby existed. Those infrastructure blockers have now been closed
and are evidenced in [the rollout infrastructure closure](11-rollout-infrastructure-closure.md)
and [the isolated restore rehearsal](10-production-backup-restore-rehearsal.md).
The release remains conditional on independent approval and merge of PR #76,
acceptance of or improvement to the measured 2,570 ms staging p95, and the
manual physical-device/integration checks that require product-owned accounts
or hardware.

## Original audit decision

> **NO-GO at the time of the initial audit**

The local release candidate is materially safer and faster, and its automated browser, scale, reliability, security, and formatting gates pass. It is not eligible for a production-readiness declaration under the requested acceptance standard because there is no production-equivalent staging clone, no approved isolated production test tenancy/accounts, and no access to production infrastructure telemetry or external integration sandboxes. Consequently, destructive workflows, every state-dependent control, production-authenticated role coverage, full device coverage, capacity/stress/soak testing, service-worker upgrade across two real deployments, and production alert verification remain unproven.

The candidate is an uncommitted working tree on branch `main`, based on commit `a16f9763e68b483c237b3c92d1227c9fffa39e1d`. This distinction matters: the base commit is not the finished release artifact.

## Evidence summary

- Current generated inventory: 1,043 routes, 359 API routes, 575 routed surfaces, 203 full pages, 14 roles, 112 permission keys, and 23 scheduled jobs.
- Django resolver/security crawl: all 1,043 registered routes exercised under its supported method/role contracts.
- Authenticated browser audit: 879 role-route visits over 159 distinct argument-free page URLs; 97,699 rendered control instances inventoried, including 47,554 visible instances; zero crawl errors.
- Browser matrix: 27 executed Playwright cases passed, 75 deliberately skipped combinations; authenticated role crawl ran in Chromium and public/freeze checks ran in Chromium, Firefox, WebKit, Android 360, iPhone 390, and tablet 768.
- Demo fixture setup ran twice with stable counts: 700 schools, 1,006 SSA records, 860 activities, 6 partners, 5 projects, and a linked coordinator.
- Scale suite passed at 15,000 schools plus 3,000 growth records. Recorded p95 values were 251 ms to 631 ms across eight representative routes.
- Production-safe public smoke passed for login and liveness/readiness. Production readiness reported database and shared cache up at test time.
- Local readiness truthfully reports cache `unshared` because local Redis was unavailable; Redis failure/degradation tests pass.
- Complete Django suite: 6,194 tests passed in 1,029.953 seconds, with two expected failures and no unexpected failures.
- Security/build gates: pip-audit found no known vulnerabilities after upgrading the local audit runner to pip 26.2; Bandit passed the CI medium-severity/medium-confidence gate; npm high-severity audit, Ruff, formatting, migration drift, CSS build, workflow YAML, and diff whitespace checks passed.

## Rate-card outcome

The costing engine now applies the two governed layers to all canonical cost components:

- Staff/CCEO planning uses Country Operational Cost. For ten training participants at UGX 12,000, staff sees UGX 120,000.
- CD/RVP management views receive both layers and the submission is governed by the Regional Standard Funding Ceiling. At UGX 22,000 for the same ten participants, the regional amount is UGX 220,000.
- The difference is explicit Country Strategic Reserve rather than being misrepresented as staff activity need.
- Staff payloads exclude regional/reference and reserve fields.
- Missing regional configuration fails closed instead of copying or inventing a benchmark.
- Submission snapshots persist regional, operational, reserve, deferred, shortfall, and per-line amounts for later audit.

## Reports

- [Live interaction coverage](01-live-interaction-coverage.md)
- [Broken links and controls](02-broken-links-and-controls.md)
- [Freeze root-cause report](03-freeze-root-causes.md)
- [Frontend performance](04-frontend-performance.md)
- [Backend and database performance](05-backend-and-database.md)
- [Load, reliability, and failure injection](06-load-and-reliability.md)
- [Production monitoring](07-production-monitoring.md)
- [Optimization change log](08-optimization-change-log.md)
- [Acceptance gates](09-acceptance-gates.md)
- [Production backup and isolated restore rehearsal](10-production-backup-restore-rehearsal.md)
- [Rollout infrastructure closure](11-rollout-infrastructure-closure.md)
- [Nine-gate progress correction](12-gate-progress-2026-08-29.md)
- [Machine-readable evidence](evidence-summary.json)
