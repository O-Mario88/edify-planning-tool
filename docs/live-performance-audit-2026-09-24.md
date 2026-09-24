# Live Performance, Reliability, Interaction Testing and Legacy Remediation — 2026-09-24

Branch `claude/laughing-babbage-bzciwc`. Baseline `4404c24` (main at the
start). Release candidate for every measurement below: `37d1386`. Two later
commits add the observability trace test, an audit-failure log line and this
report; neither touches a request path that was measured.

**Decision: NO-GO** (§9). The code in this branch removes measured freeze
causes, two dead workflow controls and a body of legacy code, and it adds a
CI-enforced interaction inventory. It is safe to merge and deploy as an
improvement. It does **not** clear the production gates the brief defines:
no staging or production environment was available to this session, the
platform still saturates one vCPU at the tested load, and the six-hour soak,
fault-injection, canary and restore gates were not run.

## 1. What was tested, and where

| Item | Reality |
|---|---|
| Live production access used | **None.** No credentials, telemetry, logs, `pg_stat_statements` or App Platform access were available. No request was sent to production. |
| Staging used | **None available.** Everything ran in an isolated local environment built for this session. |
| Environment | Python 3.13, Django 5.2.17, PostgreSQL 16, Redis 7 (absent for load tests, as in production), gunicorn + `UvicornWorker`, `config.settings.loadtest` (`DEBUG=False`), `MALLOC_ARENA_MAX=2` |
| Production shape for load tests | Server pinned to **one CPU**, **two** workers, admission guard 6 per worker, no Redis, `CONN_MAX_AGE=0` — the `apps-s-1vcpu-1gb-fixed` web service in `.do/app.yaml` |
| Stress dataset | Demo seed grown with `scripts/scale_local_dataset.py` to **50,000 schools**, 74,210 activities, 65,096 SSA records, 520,768 SSA scores, 2,577 clusters, spread over the 20 demo CCEO accounts (≈2,500 schools each — several times any real portfolio, so officer-scoped pages are measured pessimistically) |
| Realistic dataset | The same 50,000 schools spread over **150 CCEOs and 16 Programme Leads** (≈330 schools per officer, ≈9 officers per lead) |
| Baseline freeze | `4404c24` in its own worktree; every before/after pair ran the two builds against fresh copies of the same database |
| Roles swept | 15 accounts: CCEO, PL, CD, IA, Accountant, HR, Project Coordinator, Partner Admin, Partner Field Officer, Business Transformation, Lending Partner Admin, Lending Partner Officer, Regional Programme Lead, RVP, Admin |

**Roles the brief names that no fixture represents:** temporary covering user,
inactive user, user with no assignment, user with multiple assignments. Their
scope rules are covered by existing unit suites (`apps/core/tests`,
`apps/hr` leave coverage); they were not swept.

## 2. Baseline-versus-final performance (29.1)

Every figure is the builds' own output, measured by the repository's scripts
(`scripts/route_timing_sweep.py`: in-process, one request at a time, exact
query count, database time and body size per request).

### Route sweep (every argument-free GET route × 15 roles, 50,000 schools)

| Measure | Baseline | Final | Change |
|---|---:|---:|---:|
| Route/role requests | 7,425 | 7,410 | 0 % less |
| HTTP 200 | 2,028 | 2,021 | 0 % less |
| 5xx or exception | 0 | 0 | — |
| p50 latency (ms, HTTP 200) | 23 | 24 | 5 % more |
| p95 latency (ms) | 1,805 | 1,694 | 6 % less |
| p99 latency (ms) | 13,595 | 5,202 | 62 % less |
| Slowest pair (ms) | 18,423 | 10,529 | 43 % less |
| Sum of latencies (s) | 920.8 | 586.9 | 36 % less |
| Pairs over 600 ms | 193 | 171 | 11 % less |
| Pairs over 1 s | 141 | 136 | 4 % less |
| Pairs over 3 s | 80 | 66 | 18 % less |
| Queries, total | 33,475 | 23,967 | 28 % less |
| Database time, total (s) | 213.3 | 201.5 | 6 % less |
| HTML bytes, total (MB) | 320.8 | 317.6 | 1 % less |
| Pairs repeating one statement ≥ 10× | 74 | 58 | 22 % less |
| Pages over 500 KB of HTML | 52 | 51 | 2 % less |

Status changes between runs: 0

**Reading it.** The sweep ran two processes side by side, so single samples
carry noise; the cohort below re-times every slow pair three times on each
build, one build after the other on an idle machine. The 15 fewer requests are
the removed `/planning/intelligence` route × 15 roles. No route changed status.

### Slow-route cohort (141 pairs over 1 s in the baseline sweep; median of 3 each)

| Measure | Baseline | Final | Improvement |
|---|---:|---:|---:|
| p50 | 3,389 | 2,429 | 28.3 % |
| p95 | 15,080 | 4,948 | 67.2 % |
| p99 | 15,547 | 5,952 | 61.7 % |
| sum (s) | 762.6 | 389.9 | 48.9 % |

Per-pair improvement: median 4 %, ≥90 %: 9, ≥50 %: 42, slower: 37 of 141
Pairs still over 1 s after: 121; over 3 s: 57

| Role | Route | Before ms | After ms | Δ % | Queries before → after | KiB before → after |
|---|---|---:|---:|---:|---|---|
| accountant | `/accounts/blocked` | 16,873 | 455 | 97 | 14 → 6 | 138 → 138 |
| cd | `/cluster-oversight/` | 15,780 | 2,021 | 87 | 54 → 48 | 668 → 668 |
| admin | `/work-plan/export.xlsx` | 15,198 | 2,675 | 82 | 13 → 13 | 236 → 234 |
| admin | `/accounts/blocked` | 15,163 | 432 | 97 | 14 → 6 | 258 → 258 |
| ia | `/cluster-oversight/` | 15,154 | 2,004 | 87 | 64 → 53 | 650 → 650 |
| accountant | `/cluster-oversight/` | 15,128 | 1,968 | 87 | 54 → 51 | 601 → 601 |
| admin | `/accounts/blocked/` | 15,085 | 461 | 97 | 14 → 6 | 258 → 258 |
| accountant | `/accounts/blocked/` | 15,080 | 392 | 97 | 14 → 6 | 138 → 138 |
| admin | `/cluster-oversight/` | 15,010 | 2,017 | 87 | 54 → 46 | 748 → 748 |
| rvp | `/cluster-oversight/` | 14,779 | 1,948 | 87 | 67 → 49 | 617 → 617 |
| cd | `/work-plan/export.xlsx` | 14,681 | 2,720 | 81 | 17 → 15 | 235 → 234 |
| rvp | `/work-plan/export.xlsx` | 14,407 | 2,618 | 82 | 26 → 16 | 236 → 234 |
| accountant | `/team-planning-oversight/` | 14,387 | 6,017 | 58 | 38 → 48 | 726 → 726 |
| rvp | `/team-planning-oversight/` | 14,386 | 5,982 | 58 | 48 → 38 | 742 → 742 |
| accountant | `/work-plan/export.xlsx` | 14,241 | 2,339 | 84 | 13 → 13 | 236 → 234 |
| admin | `/team-planning-oversight/` | 13,842 | 5,908 | 57 | 38 → 48 | 850 → 850 |
| cd | `/team-planning-oversight/` | 13,627 | 5,845 | 57 | 40 → 38 | 770 → 770 |
| ia | `/country-planning-oversight/` | 13,565 | 4,871 | 64 | 23 → 17 | 188 → 188 |
| ia | `/team-planning-oversight/` | 13,563 | 5,891 | 57 | 48 → 38 | 750 → 750 |
| rvp | `/country-planning-oversight/` | 13,546 | 5,316 | 61 | 35 → 33 | 182 → 182 |
| regional_lead | `/team-planning-oversight/` | 13,404 | 4,851 | 64 | 31 → 26 | 398 → 398 |
| rvp | `/country-planning-oversight/export` | 13,380 | 4,578 | 66 | 17 → 17 | 0 → 0 |
| admin | `/country-planning-oversight/` | 13,245 | 4,948 | 63 | 23 → 23 | 290 → 290 |
| cd | `/country-planning-oversight/` | 12,877 | 4,890 | 62 | 23 → 17 | 210 → 210 |
| regional_lead | `/team-planning-oversight/export` | 12,636 | 4,578 | 64 | 11 → 11 | 0 → 0 |
| ia | `/team-planning-oversight/export` | 12,607 | 3,771 | 70 | 28 → 16 | 0 → 0 |
| admin | `/country-planning-oversight/export` | 12,595 | 4,430 | 65 | 9 → 7 | 0 → 0 |
| cd | `/team-planning-oversight/export` | 12,543 | 3,722 | 70 | 16 → 18 | 0 → 0 |
| rvp | `/team-planning-oversight/export` | 12,505 | 3,978 | 68 | 26 → 16 | 0 → 0 |
| admin | `/team-planning-oversight/export` | 12,469 | 4,460 | 64 | 16 → 28 | 0 → 0 |
| accountant | `/team-planning-oversight/export` | 12,435 | 3,732 | 70 | 16 → 26 | 0 → 0 |
| ia | `/country-planning-oversight/export` | 12,426 | 4,142 | 67 | 7 → 7 | 0 → 0 |
| regional_lead | `/cluster-oversight/` | 12,244 | 80 | 99 | 35 → 27 | 120 → 120 |
| cd | `/country-planning-oversight/export` | 12,223 | 4,375 | 64 | 7 → 7 | 0 → 0 |
| pl | `/cluster-oversight/` | 7,475 | 2,239 | 70 | 67 → 66 | 615 → 615 |
| pl | `/team-planning-oversight/` | 6,306 | 2,744 | 56 | 46 → 41 | 1637 → 1637 |
| rvp | `/ssa` | 5,146 | 4,673 | 9 | 26 → 21 | 280 → 280 |
| regional_lead | `/team-targets/` | 5,093 | 4,668 | 8 | 68 → 66 | 153 → 153 |
| rvp | `/ssa/export` | 5,030 | 4,402 | 12 | 20 → 30 | 1932 → 1932 |
| pl | `/team-planning-oversight/export` | 5,028 | 2,137 | 57 | 23 → 23 | 0 → 0 |
| bt | `/ssa` | 5,027 | 4,839 | 4 | 23 → 18 | 248 → 248 |
| accountant | `/ssa` | 5,022 | 4,771 | 5 | 23 → 20 | 266 → 266 |
| admin | `/ssa` | 4,972 | 4,748 | 5 | 23 → 23 | 390 → 390 |
| cd | `/ssa` | 4,923 | 4,845 | 2 | 20 → 20 | 309 → 309 |
| accountant | `/ssa/export` | 4,919 | 5,314 | -8 | 17 → 27 | 1932 → 1932 |
| bt | `/ssa/export` | 4,915 | 4,823 | 2 | 17 → 17 | 1932 → 1932 |
| ia | `/ssa` | 4,893 | 4,582 | 6 | 35 → 32 | 299 → 299 |
| admin | `/team-targets/export` | 4,883 | 4,742 | 3 | 71 → 71 | 0 → 0 |
| cd | `/ssa/export` | 4,870 | 4,885 | -0 | 19 → 19 | 1932 → 1932 |
| regional_lead | `/ssa` | 4,857 | 4,937 | -2 | 36 → 31 | 260 → 260 |
| admin | `/ssa/export` | 4,831 | 4,626 | 4 | 17 → 17 | 1932 → 1932 |
| ia | `/ssa/export` | 4,821 | 4,782 | 1 | 29 → 19 | 1932 → 1932 |
| regional_lead | `/ssa/export` | 4,816 | 4,665 | 3 | 30 → 20 | 1932 → 1932 |
| admin | `/team-targets/` | 4,767 | 4,652 | 2 | 73 → 71 | 278 → 278 |
| admin | `/team-targets` | 4,741 | 4,698 | 1 | 71 → 71 | 278 → 278 |
| admin | `/team-targets/recovery` | 4,733 | 4,636 | 2 | 72 → 72 | 4 → 4 |
| regional_lead | `/team-targets/export` | 4,717 | 4,771 | -1 | 66 → 66 | 0 → 0 |
| cd | `/team-targets` | 4,684 | 4,639 | 1 | 64 → 64 | 198 → 198 |
| cd | `/team-targets/` | 4,668 | 4,527 | 3 | 69 → 64 | 198 → 198 |
| regional_lead | `/team-targets` | 4,661 | 4,791 | -3 | 66 → 66 | 153 → 153 |
| cd | `/team-targets/recovery` | 4,544 | 4,728 | -4 | 65 → 65 | 4 → 4 |
| cd | `/team-targets/export` | 4,498 | 4,437 | 1 | 64 → 64 | 0 → 0 |
| regional_lead | `/team-targets/recovery` | 4,447 | 4,634 | -4 | 67 → 67 | 4 → 4 |
| accountant | `/analytics/export` | 4,354 | 3,994 | 8 | 72 → 72 | 0 → 0 |
| ia | `/analytics/export` | 4,213 | 4,179 | 1 | 64 → 64 | 0 → 0 |
| admin | `/ia/learning/` | 4,159 | 3,821 | 8 | 19 → 19 | 260 → 260 |
| cd | `/analytics/export` | 4,142 | 4,327 | -4 | 64 → 64 | 0 → 0 |
| ia | `/ia/learning/` | 3,795 | 3,801 | -0 | 11 → 11 | 162 → 162 |
| cd | `/ia/learning/` | 3,741 | 4,173 | -12 | 11 → 11 | 180 → 180 |
| pl | `/projects/my-plan` | 3,581 | 3,584 | -0 | 24 → 24 | 164 → 164 |
| admin | `/projects/my-plan` | 3,389 | 3,276 | 3 | 23 → 13 | 259 → 259 |
| coordinator | `/projects/my-plan` | 3,257 | 3,120 | 4 | 16 → 16 | 142 → 142 |
| ia | `/projects/my-plan` | 3,199 | 3,148 | 2 | 20 → 20 | 161 → 161 |
| cd | `/projects/my-plan` | 3,074 | 3,223 | -5 | 20 → 20 | 179 → 179 |
| rvp | `/declining-schools` | 3,040 | 2,896 | 5 | 23 → 13 | 154 → 154 |
| admin | `/ia/dashboard/` | 2,942 | 2,888 | 2 | 28 → 28 | 376 → 376 |
| ia | `/ia/dashboard/` | 2,888 | 2,640 | 9 | 25 → 25 | 278 → 278 |
| ia | `/declining-schools` | 2,882 | 2,634 | 9 | 12 → 12 | 169 → 169 |
| admin | `/declining-schools` | 2,839 | 2,766 | 3 | 10 → 10 | 260 → 260 |
| cd | `/ia/dashboard/` | 2,826 | 2,846 | -1 | 30 → 30 | 296 → 296 |
| pl | `/ssa/export` | 2,724 | 2,611 | 4 | 23 → 23 | 505 → 505 |
| pl | `/ssa` | 2,662 | 2,676 | -1 | 24 → 24 | 289 → 289 |
| cd | `/declining-schools` | 2,608 | 2,904 | -11 | 12 → 12 | 179 → 179 |
| pl | `/analytics/export` | 2,521 | 2,429 | 4 | 68 → 68 | 0 → 0 |
| regional_lead | `/analytics/export` | 2,263 | 2,095 | 7 | 63 → 63 | 0 → 0 |
| cd | `/clusters` | 2,258 | 2,087 | 8 | 23 → 28 | 402 → 402 |
| pl | `/work-plan/export.xlsx` | 2,246 | 1,033 | 54 | 20 → 20 | 62 → 62 |
| ia | `/ssa/unmatched` | 2,228 | 2,131 | 4 | 13 → 13 | 4058 → 4058 |
| admin | `/analytics/country-director/drilldown` | 2,166 | 1,898 | 12 | 86 → 86 | 6 → 6 |
| admin | `/clusters` | 2,155 | 1,991 | 8 | 21 → 26 | 482 → 482 |
| cd | `/analytics/country-director/drilldown` | 2,141 | 2,166 | -1 | 88 → 88 | 6 → 6 |
| admin | `/ssa/unmatched` | 2,133 | 1,976 | 7 | 11 → 11 | 4153 → 4153 |
| ia | `/clusters` | 2,102 | 2,271 | -8 | 23 → 23 | 384 → 384 |
| admin | `/analytics/export` | 2,090 | 1,805 | 14 | 60 → 60 | 0 → 0 |
| admin | `/core-schools` | 2,007 | 2,051 | -2 | 76 → 76 | 470 → 470 |
| accountant | `/core-schools` | 1,991 | 1,935 | 3 | 76 → 76 | 334 → 334 |
| rvp | `/analytics/export` | 1,976 | 2,036 | -3 | 63 → 63 | 0 → 0 |
| ia | `/core-schools` | 1,967 | 1,909 | 3 | 78 → 78 | 372 → 372 |
| cd | `/core-schools-oversight/` | 1,745 | 1,633 | 6 | 33 → 28 | 300 → 300 |
| cd | `/core-schools` | 1,725 | 1,813 | -5 | 78 → 80 | 390 → 390 |
| admin | `/calendar` | 1,680 | 1,638 | 3 | 15 → 15 | 5423 → 5423 |
| ia | `/core-schools-oversight/` | 1,665 | 1,576 | 5 | 28 → 30 | 282 → 282 |
| admin | `/core-schools-oversight/` | 1,620 | 1,573 | 3 | 26 → 26 | 380 → 380 |
| regional_lead | `/core-schools-oversight/` | 1,604 | 1,572 | 2 | 34 → 29 | 255 → 255 |
| rvp | `/core-schools-oversight/` | 1,601 | 1,704 | -6 | 29 → 29 | 276 → 276 |
| cceo | `/activities/closure` | 1,556 | 140 | 91 | 1624 → 8 | 350 → 350 |
| pl | `/team-targets/recovery` | 1,535 | 1,427 | 7 | 58 → 58 | 4 → 4 |
| pl | `/analytics/program-lead/export` | 1,533 | 1,686 | -10 | 26 → 26 | 462 → 463 |
| ia | `/planning` | 1,524 | 1,393 | 9 | 99 → 99 | 302 → 302 |
| accountant | `/planning` | 1,442 | 1,388 | 4 | 97 → 97 | 278 → 278 |
| pl | `/team-targets` | 1,428 | 1,379 | 3 | 57 → 57 | 181 → 181 |
| admin | `/planning` | 1,398 | 1,354 | 3 | 97 → 97 | 400 → 400 |
| cd | `/planning` | 1,383 | 1,355 | 2 | 99 → 99 | 320 → 320 |
| rvp | `/work-plan/` | 1,347 | 1,298 | 4 | 16 → 16 | 172 → 172 |
| pl | `/team-targets/` | 1,340 | 1,347 | -1 | 57 → 57 | 181 → 181 |
| pl | `/team-targets/export` | 1,336 | 1,337 | -0 | 57 → 59 | 0 → 0 |
| cd | `/work-plan/` | 1,335 | 1,259 | 6 | 15 → 15 | 199 → 199 |
| admin | `/work-plan` | 1,326 | 1,304 | 2 | 13 → 13 | 279 → 279 |
| admin | `/work-plan/` | 1,302 | 1,418 | -9 | 13 → 13 | 279 → 279 |
| cceo | `/clusters` | 1,260 | 1,320 | -5 | 24 → 29 | 289 → 289 |
| pl | `/core-schools-oversight/` | 1,232 | 1,240 | -1 | 32 → 32 | 270 → 270 |
| pl | `/declining-schools` | 1,172 | 1,090 | 7 | 16 → 16 | 161 → 161 |
| ia | `/ia/compare/` | 1,138 | 1,036 | 9 | 18 → 18 | 2676 → 2676 |
| regional_lead | `/team-targets/matrix` | 1,085 | 973 | 10 | 113 → 113 | 8 → 8 |
| ia | `/analytics/verification-quality` | 1,075 | 1,117 | -4 | 49 → 49 | 254 → 254 |
| accountant | `/work-plan/` | 1,031 | 1,247 | -21 | 13 → 13 | 158 → 158 |
| cd | `/analytics/visit-effectiveness` | 978 | 799 | 18 | 12 → 12 | 180 → 180 |
| pl | `/analytics` | 972 | 998 | -3 | 19 → 19 | 686 → 686 |
| rvp | `/work-plan` | 951 | 1,214 | -28 | 16 → 16 | 172 → 172 |
| admin | `/schools` | 928 | 894 | 4 | 33 → 33 | 726 → 726 |
| pl | `/analytics/` | 923 | 1,159 | -26 | 19 → 19 | 686 → 686 |
| rvp | `/analytics/visit-effectiveness` | 893 | 907 | -2 | 12 → 12 | 155 → 155 |
| admin | `/leave/calendar/` | 641 | 659 | -3 | 7 → 7 | 2569 → 2569 |
| ia | `/analytics` | 479 | 458 | 4 | 12 → 12 | 685 → 685 |
| regional_lead | `/analytics/` | 448 | 426 | 5 | 13 → 13 | 655 → 655 |
| cd | `/analytics/` | 440 | 494 | -12 | 14 → 14 | 705 → 705 |
| accountant | `/activities/closure/blocked/` | 436 | 12 | 97 | 4 → 4 | 135 → 120 |
| ia | `/activities/closure/blocked` | 381 | 15 | 96 | 6 → 6 | 157 → 141 |
| admin | `/activities/closure/blocked` | 363 | 16 | 96 | 4 → 4 | 255 → 240 |
| pl | `/analytics/program-lead` | 234 | 248 | -6 | 14 → 14 | 408 → 408 |
| ia | `/activities/closure` | 173 | 271 | -57 | 7 → 7 | 361 → 361 |

**Improvement against the 90 % target.** The cohort's p95 fell 67.2 % and its
total time 48.9 %; nine pairs improved by 90 % or more: the Finance Blocked
page (four pairs), the CCEO closure queue, the regional lead's Cluster
Oversight, and the Blocked Closures page (three pairs — but see the fair
re-measurement under P-02 in §3: in the final run that page had fewer
persisted blockers than in the baseline run, so its cohort figures are not
like for like). The 90 % latency-reduction target is
**not met**: the pages still over one second are whole-country analytics and
targets pages this round did not rebuild (§9).

**Pairs that measured slower.** 37 of 141 read slower; 36 of them by under
28 % with identical query counts and overlapping samples (run-to-run noise on
cached analytics pages). One is a real, intended cost: IA's closure queue,
173 → 271 ms (7 queries both). The baseline paid its checklist writes on the
warm-up request, which the measurement discards, and read fresh rows
afterwards; the new queue derives its facts on every view — eight correlated
`EXISTS` per row for up to 300 rows. That is ≈100 ms on every view instead of
~1,000 statements and ~300 writes whenever a checklist is stale, repeated by
each concurrent viewer (25 s p50 under load in the 2026-09-23 report).

## 3. Freeze root-cause report (29.3)

Every entry was reproduced on the 50,000-school copy before it was fixed, and
re-measured on the same data after. "Equivalence" says how the change was
proven not to alter what a user sees.

| # | Trigger (what a user sees) | Root cause | Layer | Evidence | Fix | Equivalence | Regression test |
|---|---|---|---|---|---|---|---|
| P-01 | IA, accountants and CCEOs wait seconds on the closure queue; concurrent viewers make it worse | Every GET re-derived and **wrote** each stale checklist (≈12 statements and several inserts per row, in its own transaction) — R10 in the 2026-09-23 report | Backend / DB writes on read | CCEO `/activities/closure`: 2,854 queries, 690 repeated `INSERT INTO closure_blocker` in one view | Facts arrive as eight `EXISTS`/subquery annotations on the listing query; GET writes nothing; a scheduled `closure_checklist_refresh` job persists changed checklists for the Blocked page and System Health | Annotated facts compared with the old per-query derivation on 15 branches (every check, both finance systems, quarantined evidence, SSA-gathering, partner paid/unpaid) — identical. The refresh job at 50,000 schools: 43,151 open activities, first run 14.9 s (writes every checklist), a rerun with nothing changed 6.1 s and zero writes | `apps/activities/test_closure_read_only_queue.py` (7) |
| P-02 | Any paged table fed a queryset (Blocked Closures and others) loads for seconds | `paginate_rows` called `list(queryset)` and the `{% paginate %}` tag tested `rows or []`, whose truth test fetches every row — the page drew ten rows from the whole table | Backend / template layer | Blocked Closures loaded every blocker in scope with activity and school joined. Same database for both builds, after a full checklist refresh (166,368 blockers at 50,000 schools): **23.1–23.7 s → 49 ms** (median of 3, accountant and IA) | `COUNT` + `LIMIT/OFFSET` for an unevaluated queryset; no truth test | Lists and lazy sequences unchanged; evaluated querysets reuse their cache | `apps/core/test_queryset_pagination.py` (7) |
| P-03 | Accountant's Finance Blocked page: 14–18 s | Loaded **every activity in the country** with budget lines and school to test four rules in Python and draw ten rows | Backend / unbounded query | `/accounts/blocked` 18,423 ms (accountant), 18,007 ms (admin) | The four rules as one SQL `WHERE`; counted and sliced in the database; reasons built per page | SQL filter compared with `get_blocked_reasons` on 12 branches (status, evidence, budget, SF ID null/empty, snapshot NONE/none/SSA_DATA_GATHERING/TRAINING) — identical | `apps/fund_requests/test_finance_blocked_sql.py` (3) |
| P-04 | Team, country and cluster oversight for country roles: 11–16 s; PL team oversight 7 s | Every item was built from model instances with six joined relations: ≈520,000 objects for the country; cost totals bound 74,000 ids as literal parameters | Backend / Python object cost | cProfile: `_activities_in_scope` 11.4 s of a 22 s request | Items built from `values_list` rows with shared nested records; cost query binds one array parameter; order made total | Every item (all fields, in order) identical for PL, CD, regional lead and CCEO | Existing oversight suites (unchanged, passing) |
| P-05 | Cluster Oversight: 15 s for country roles | Built **every** oversight item in the country (74,210) to keep the cluster sessions | Backend / over-fetch | `cluster_oversight_table_data` 22 s profiled | `build_items(activity_types=…, cluster_work_only=True)` narrows in SQL before building | Table data identical for PL, CD, CCEO, IA | Existing cluster oversight suites |
| P-06 | Cluster performance and SSA breakdowns slow for country roles | Literal `IN` lists of ≈34,000 school ids and 2,577 cluster ids | DB / query shape | `_split_query` and adaptation time in profile | Shared `apps.core.scoping.id_array()` (one array parameter); the SSA service's own copy now uses it | `cluster_performance` output identical for PL, CD, regional lead | Existing suites |
| P-07 | Work Plan Excel export: 13–15 s | `sheet[row_index]` recomputes the sheet width on every call: styling row by row was quadratic (231 million generator steps for 4,220 rows); one new style object per cell | Backend / algorithm | cProfile: 44 s of 63 s in `max_column` | One `iter_rows` pass with shared style objects, in `apps.core.excel`; the Work Plan export now uses the shared helper instead of its own copy | Workbook compared cell by cell (value, fill, font, border, alignment, number format, widths, freeze panes, filter) — identical | `apps/core/tests/test_plan_excel_export.py` (+2) |
| P-08 | My Plan: 3.0 MB of HTML for one field officer; a phone parses and lays out every row | The school visit, training, meeting and programme tables drew the whole fiscal year (owner decision R3 keeps the whole-FY default) | Frontend / DOM size | 3,088 KB, 1.2 s | The four tables page at ten with the shared pager, like the core-school tables beside them; the count badge and the export still cover the whole year | Export unchanged (test); rows per page from the same list | `apps/my_plan/test_my_plan_table_pages.py` (3) |
| P-09 | My Plan server time | `planned_minimum_amounts` decoded five JSON documents per activity to read one | Backend | 226 ms per 3,698 activities | Reads only the five columns it needs | Output identical on all 74,210 activities | Existing costing suites |
| P-10 | Activity catalogue settings: 130 extra queries per load | `item.activities.count` twice per card | Backend / N+1 | 140 queries | One correlated count on the listing query | Soft-deleted activities still excluded (test) | `apps/activity_catalogue/test_catalogue_page_queries.py` (2) |
| P-11 | A message with attachments could hold a database transaction open for the whole upload (R9) | `FileField.save` to object storage inside `transaction.atomic()` | Backend / transaction scope | Code audit (previous report R9) | Files stored first, then one short insert transaction; stored files deleted if the message fails | Existing messaging suite unchanged | `apps/messaging/tests.py` (+2; the first fails on the old code) |
| P-12 | Work Plan rows shuffle between loads and between the page and its export | `order_by("planned_date", "created_at")` ties on bulk-created rows (R14) | Backend / determinism | Two consecutive builds of the same plan differed in order | `id` tie-breaker | Same multiset, now one order | `apps/frontend/test_activity_plan_summary.py` (+1) |
| P-13 | Scheduler history table grows without bound (R13) | Nothing deleted `ScheduledJobExecution` rows (~525,000 a year from the every-minute outbox drain alone) | DB growth | Code audit | Daily `scheduler_history_prune`: successes after 90 days, failures after 365, never a job's latest success | Health reads unchanged | `apps/realtime/tests.py` (+2) |
| D-01 | The closure workspace's **Close & Lock Activity** did nothing but a 404 | Form posted to `/activities/<id>/closure/close/`; the route has no trailing slash | Frontend / dead control | Found by the new interaction inventory's route check; confirmed with `resolve()` | Form action corrected | — | `apps/frontend/test_closure_workspace_forms.py` (2) |
| D-02 | **Reopen Closed Activity** likewise 404'd | Form posted to `/activities/<id>/reopen/` | Frontend / dead control | As D-01 | As D-01 | — | As D-01 |

## 4. Interaction coverage report (29.2)

**What was built.** `apps/system_health/interaction_inventory.py` scans every
template for controls (buttons, links, fields, disclosures, tabs; hidden
inputs excluded), resolves each control's request against the URL resolver,
maps each template to the routed pages that render it and their roles (from
the page inventory), and grades the automated evidence behind it. The result
is committed as `docs/platform-interaction-inventory.json` (one control per
line, stable `INT-…` ids) with a summary in `.md`, rebuilt by
`python manage.py build_interaction_inventory`.

**The CI gate** (`apps/system_health/test_interaction_inventory.py`, runs in
the ordinary Django suite):
- the committed manifest must equal the live scan, so a new control without
  a regenerated manifest fails;
- no control may point at a path that resolves to no route (the check that
  found D-01 and D-02);
- the number of controls with no automated evidence, and of state-changing
  controls with none, may not rise above the committed ceilings (363 and 26).

**Evidence levels are declared, not inflated.** `request-tested` means a
Django test or browser spec requests the control's destination route;
`browser-rendered` means the control sits on a page the authenticated route
audit opens for every permitted role (that audit fails on console errors,
page errors, stuck requests and unnamed controls) but its own request is not
exercised; `page-tested` means a Django test renders a page carrying it.
None of these is a recorded click of that element with a verified outcome.

| Measure | Count |
|---|---:|
| Routed surfaces (page inventory, regenerated) | 823 |
| URL patterns | 1,295 (API 360) |
| Full pages / partials and drawers | 260 / 270 |
| Templates with controls | 529 |
| Control declarations | 3,392 (1,100 buttons, 981 links, 1,177 fields, 69 disclosures, 65 tabs) |
| Request-tested | 1,041 |
| Browser-rendered only | 755 |
| Page-tested only | 1,233 |
| No automated evidence | 363 |
| State-changing | 410 — request-tested 231, browser-rendered 77, page-tested 76, none 26 |
| High-consequence (state-changing and named approve/pay/return/verify/…) | 182 — none 13 |
| Controls whose destination resolves to no route | 2 found (D-01, D-02) → **0** |
| Destructive actions executed in staging | **0** — no staging environment was available to this session |
| Production-safe smoke interactions | **0** — no production access was used |

**Not done, and not claimed.** Every control was *not* clicked in every
materially different state for every role. The inventory makes that gap
countable (363 declarations with no automated evidence, 26 of them
state-changing) and stops it growing; closing it is test-writing work
against the list in `docs/platform-interaction-inventory.md`.

## 5. Legacy deletion report (29.4)

**Method.** A candidate was removed only when its name appeared nowhere else:
no import, no URL pattern, no template include or render, no JavaScript or
browser spec, no test, no dynamic template name. Views were also checked
against the URL resolver, and the template sweep also checked dynamic
`{% include variable %}` values. The generated manifests (page, permission,
traceability, card, KPI and interaction inventories) were regenerated in the
same change, so no manifest names a deleted thing. Models, fields, migrations
and workflow states were not touched: none was proven unused, and applied
migration history stays.

### Removed

| Item | Kind | Evidence | Replacement |
|---|---|---|---|
| `/planning/intelligence` → `planning_views.planning_intelligence_view` | Route + view | Rendered `partials/planning/right_panel.html`, which does not exist, so any request with `?school_id=` was a 500. No link, include or script reached it | None needed (orphan); its source-inspection test removed with it |
| `hr_views.strategic_priorities_view` + `pages/hr/strategic_priorities.html` | Old page of a replaced pair | Unrouted; `priority_configuration_page` replaced it (its own comment says so) | `priority_views.priority_configuration_page` |
| `extended_views.core_schools_view` | Duplicate implementation | Unrouted duplicate of the live `core_schools_views.core_schools_view` | The live view |
| `extended_views.ssa_master_view` + `pages/ssa/index.html` | Old page | Unrouted; the template was rendered only by it | `/ssa` (`ssa_views.ssa_performance_view`) |
| `extended_views.help_view` | Old page | Unrouted | `help_center.views` |
| `staff_views.today_view` | Old page | Unrouted | `today_views` (Dashboard's Today view) |
| `staff_views.notification_badge_view` | Broken view | Unrouted; rendered a template that does not exist | The shell (`layouts/shell.html`) renders the badge |
| `clusters.views.ClusterCreateView`, `ssa.views.SsaUploadView` | API views | Unrouted | `ClusterListCreateView`, `SsaFileUploadView` |
| `apps/admin_ops/middleware.py` | Compatibility shim | Pass-through classes kept "for rolling deployments", absent from `MIDDLEWARE`, referenced by nothing; `docs/ADMIN_PLATFORM_OPERATIONS.md` still described it as an active security layer — corrected | None (Admin is the platform super-role) |
| `apps/planning/checks.py` | Unwired system check | Never imported, so it never ran; had it been wired, `check --deploy` would have failed deploys on data conditions and scanned every core school one query at a time | System Health data-quality checks |
| 22 functions and classes: `staff_views._quarter_completed_counts`, `_cumulative_period_row`, `_kpi_status`; `ia_outcome_views.csv_cell` (old-name alias); `messaging.services.get_user_threads` ("legacy list shape used by the old inbox view"); `oversight_views._cluster_performance_context`; `dashboard_views._build_agenda_item`; `debrief_views._parse_submission`; `impact.framework._record_url`; `budget.services._activity_to_costable`; `fund_requests.services._to_costable`; `schools.upload_service._match_account_owner`; `accounts.auth_services._invite_ttl_days`; `monthly_work_plan.country_budget_service._team_monthly_requests`; `my_plan.services.get_weeks_for_month`; `core.pagination.page_from`; `core_schools.core_planning_services.CoreMyPlanSyncService`; `planning.recommendation_services.OwnerRecommendationService`; `accounts.serializers.InviteValidateSerializer`; `core.enums.ActivityContextType`; `outbox.services.registered_event_types`; `documents.services.administers_any` | Dead code | Zero references in the whole repository | — |
| Templates `components/input.html`, `pages/fund_requests/detail.html`, `partials/finance/accountant_insights.html`, `partials/my_plan/activity_table.html`, `partials/my_plan/priority_queue.html`, `partials/oversight/cluster_performance_workspace.html`, `partials/projects/delta_pill.html`, `partials/projects/plan_activity_table.html` | Dead templates | No render, include or literal reference; `docs/COMPONENTS.md` no longer documents the input component | Shared components already in use |
| `static/js/record-views.js` and `tests/js/record-views.test.cjs` | Dead asset | An empty IIFE loaded by no template; its test only proved it did nothing | — |

Net: 747 lines of Python removed in the second commit alone, 10 templates, one
script. The CSS bundle was rebuilt so no class survives only for a deleted
template.

### Found, not removed (unwired domain code — needs an owner decision)

These have no caller, but they are business services rather than leftovers,
and a missing caller can mean a missing wire as easily as dead code:

| Item | Why it matters |
|---|---|
| `business_transformation.signals.enqueue_ssa_confirmed_batch` | Its docstring says the SSA upload uses it to stay O(1); nothing calls it. Either the upload enqueues per record, or the function is dead — worth one look |
| `hr.leave_services.check_staff_availability`, `hr.performance_engine.decline_separation`, `hr.recruitment_service.scoped_vacancies`, `hr.milestone_progress.counts_distinct_entities` | HR services with no caller |
| `planning.partner_oversight_service.partner_contacts`, `withdrawal_history` | Partner oversight helpers with no caller |
| `ssa.services.verifier_basis`, `ssa.change_rules.rule_from_mapping` | SSA verification helpers with no caller |
| `documents.help_sync.retire_help_mapping`, `documents.storage.document_dir`, `messaging.services.get_context_target_route` | Document and messaging helpers with no caller |

`apps.core.openapi.JwtAuthenticationScheme` also has no caller by name but is
live: drf-spectacular registers it by subclassing.

## 6. Code-quality report (29.5)

| Measure | Baseline (`4404c24`) | Final | Change |
|---|---:|---:|---|
| Ruff lint / format | clean / clean | clean / clean | — |
| Bandit (`-ll -ii`, as CI) | 0 findings | 0 findings | One new finding (SHA-1 for ids) fixed with `usedforsecurity=False` before commit |
| pip-audit `--strict` (prod requirements) | — | No known vulnerabilities | — |
| Functions with cyclomatic complexity > 15 (ruff C901, non-test) | 142 | 142 | none added, none reduced |
| Functions > 30 | 30 | 30 | — |
| Non-test application Python lines | 338,596 | 338,903 | +307 (inventory module +440, closure facts; −747 dead code) |
| Templates | 737 | 727 | −10 |
| Unbounded tables (table inventory scanner) | 10 | 6 | −4 (My Plan) |
| Controls pointing at no route | 2 | 0 | fixed |
| Unrouted/broken views | 8 | 0 | removed |
| Unreferenced top-level definitions (whole-repo scan) | 38 | 12 (+1 false positive) | 23 removed; 12 unwired domain services left for an owner decision |
| Writes on a GET (closure queue) | 1 surface, ~300 writes per view | 0 | removed |
| Pages that load a whole table to draw one page | every `{% paginate queryset %}`, plus Finance Blocked | 0 known | fixed at the tag |
| Tests in the full Django suite | — | 8,641 run (33 of them new) | — |

**The 90 % code-debt target is not met, and no composite score is offered
in its place.** This programme measured and removed the defects it found
(the register in §3 and §5), but it did not run a duplication tool, did not
reduce complexity, and did not audit the 339,000-line codebase end to end.
A "debt points" percentage computed only over the findings this audit
itself raised would be 100 % by construction and would say nothing about the
platform; it is deliberately not reported.

## 7. Load and reliability report (29.6)

**Workload.** `scripts/load_test.py`: one real session per virtual user, a
weighted journey per role (full pages, HTMX search and paging, a school's
page, one harmless CSRF-protected write), 3–12 s think time, a 30 s client
timeout; role mix CCEO 45, PL 12, IA 7, partner 6, accountant 5, coordinator
4, HR 4, CD 3, BT 3, MFI 3, RVP 2, regional lead 2. Stages 25 users × 120 s,
50 × 120 s, 100 × 90 s, then 30 s with one user.

### Load test — 50,000 schools, 20 officers (stress); 1 CPU, 2 Uvicorn workers, no Redis

| Build | Stage | Requests | req/s | p50 | p95 | p99 | 503 | Error % | Timeouts | Peak RSS MB | CPU % | DB conns | Lock waits |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Baseline | 25u | 181 | 1.51 | 4,950 | 25,526 | 30,031 | 9 | 9.94 | 9 | 1,856 | 91.2 | 15 | 0 |
| Baseline | 50u | 213 | 1.77 | 20,294 | 30,027 | 30,030 | 70 | 39.91 | 15 | 2,626 | 98.3 | 14 | 0 |
| Baseline | 100u | 517 | 5.74 | 1,734 | 25,925 | 30,030 | 371 | 74.85 | 16 | 2,622 | 98.6 | 15 | 0 |
| Baseline | recovery | 59 | 1.97 | 21,884 | 30,030 | 30,031 | 36 | 72.88 | 7 | 2,626 | 98.4 | 14 | 1 |
| Final | 25u | 199 | 1.66 | 4,301 | 24,258 | 30,031 | 0 | 4.52 | 9 | 1,760 | 91.0 | 14 | 1 |
| Final | 50u | 221 | 1.84 | 17,898 | 30,025 | 30,031 | 32 | 20.81 | 14 | 2,657 | 98.1 | 15 | 0 |
| Final | 100u | 506 | 5.62 | 2,125 | 27,151 | 30,030 | 335 | 69.96 | 19 | 2,608 | 98.4 | 15 | 0 |
| Final | recovery | 60 | 2.0 | 20,914 | 30,028 | 30,030 | 23 | 46.67 | 5 | 2,316 | 98.1 | 14 | 0 |

**What changed.** At 25 users the server completed 184 requests against 157
in the same two minutes, refused none against 9, and the error rate halved
(9.9 % → 4.5 %). At 50 users completed requests rose 39 % (122 → 169) and
errors fell from 39.9 % to 20.8 %; the recovery window served twice as many
requests.

**What did not.** The single CPU is 91–98 % busy from the first stage in both
builds, so every page queues behind every other: p95 stays at 24–30 s and
p50 at ≈4–5 s at 25 users. Two workers peak at 1.8–2.7 GB against the 1 GiB
instance. This dataset is pessimistic for officer pages (≈2,500 schools per
CCEO); a run with a realistic spread was started and discarded because the
scaling script refuses a database name without "scale" — it is repeated in
the next round.

**Not run:** the six-hour soak, the spike and stress-to-failure profile, and
fault injection. The stage profile above is diagnostic, not a soak.

## 8. Live production validation (29.7)

**Not performed.** This session had no access to the production application,
its telemetry, its database or its hosting account, and no staging service.
No deployment, canary, production smoke test, synthetic check, backup,
restore, migration rehearsal or rollback rehearsal was executed. The
repository's own tooling for those steps exists (`scripts/backup_restore_rehearsal.sh`,
`scripts/rollback_rehearsal.sh`, `scripts/restore_smoke.py`,
`e2e/authenticated-route-audit.spec.js` with its fail-closed
`EDIFY_PRODUCTION_SMOKE_MODE=read-only-authenticated` guard, the `uptime`
workflow) and is the route to those gates; none of it was run here.

What the release owner should watch after deploying this branch (all already
instrumented by the 2026-09-23 release):
- **System Health → Route Performance**: queue p95 above 1 s means the web
  instance is out of CPU; the Finance Blocked, closure queue, cluster and
  team oversight routes should drop out of the slow-route list.
- **`slow_request` log lines** by route pattern.
- **Scheduler**: `closure_checklist_refresh` (every 30 min at :10/:40) and
  `scheduler_history_prune` (03:40) appear in System Health's job list; the
  first run of the refresh writes a checklist for every open activity, later
  runs only the changes. Its `records_processed` is the checklist count.
- **The closure workspace**: Close & Lock and Reopen now reach their actions;
  a first real close confirms it in production.

**Migrations:** none. **Rollback:** redeploy the previous image; no schema or
data change needs reversing. The two new scheduled jobs only write rows the
code already wrote (checklists, blockers) or delete history past retention.

## 9. Release acceptance gates and decision (§30)

| Gate | Status | Evidence |
|---|---|---|
| Page and route inventories regenerated | **Met** | 823 surfaces, 1,295 patterns (§4) |
| Every role, route, button, link, tab, menu, drawer, form, search, table action, export, upload, notification and To-Do link tested | **Not met** | 3,392 controls inventoried; 1,041 request-tested, 363 with no automated evidence (§4); no per-state click matrix |
| No dead controls / unexpected 404 | **Met for what the inventory can see** | 2 dead forms found and fixed; 0 controls point at no route |
| No unexpected 500 | **Met in the sweep** | 0 × 5xx across 7,410 route/role requests |
| No unhandled browser errors, no critical UI freeze | **Partly** | Not run locally this round; CI's *Browser Journeys & Role Route Audit* (chromium-desktop, two shards) runs on PR #127 |
| Every critical workflow passes; scope boundaries; reconciliation | **Existing suites pass** | 8,641 tests ran; the failures were files deleted mid-run and three tests pinning the old behaviour, all fixed and re-run green; CI re-runs the whole suite on PR #127 |
| Legacy duplicate pathways removed; no old+new implementation active | **Met for those found** | §5; 12 unwired services left for an owner |
| No raw governed-state write, unbounded critical queryset, critical N+1, page that loads all records | **Improved, not proven for the whole platform** | Fixed: closure writes-on-GET, Finance Blocked, queryset pager, catalogue N+1; 6 unbounded tables remain (scanner), 58 pages still repeat a statement ≥ 10× |
| Absolute SLOs (≤ 600 ms common page p95, etc.) | **Not met** | Sweep p95 1.7 s; 136 route/role pairs > 1 s at 50,000 schools |
| Slow-route cohort 90 % latency reduction | **Not met** | p95 15.1 s → 4.9 s (−67.2 %); 9 of 141 pairs ≥ 90 % |
| Journey wait-time 90 % reduction | **Not measured** in a browser against a production-like CDN; load-test p50 at 25 users 4.95 s → 4.30 s |
| Code-debt reduction ≥ 90 % | **Not met, not claimed** | §6 |
| Full test suite passes | **Pending CI** | 8,641 tests locally; see the row above |
| Browser suite passes | Not run locally this round; CI's *Browser Journeys & Role Route Audit* (chromium-desktop, two shards) runs on PR #127 |
| Accessibility tests | **Covered only by the existing route audit's unnamed-control check** | — |
| Security scans | **Met** | Bandit 0, pip-audit 0 |
| 6-hour soak, spike, stress-to-failure and recovery | **Not met** | Staged 25/50/100 load with a 30 s recovery only (§7); no 6-hour run |
| 50,000-school test | **Run; fails the load gate at production shape** | §7 |
| Backup restore, migration and rollback rehearsal | **Not run** | No staging |
| Production smoke, canary, monitoring confirmed | **Not run** | §8 |
| No Critical / High defect remaining | **Not met** | Capacity (one vCPU saturates) remains High, as in the 2026-09-23 report |

**NO-GO: The release candidate has not met the required production gates.**

| Failed gate | Affected routes / workflows | Risk | Required correction | Required retest |
|---|---|---|---|---|
| Capacity at production shape | All pages under concurrent use; worst for country roles and field officers' morning mix | Queue waits of 20–30 s and 5–20 % failed requests from 25–50 users at 50,000 schools; the same cliff the 2026-09-23 report measured at 16,000 | The capacity change §7.3 of the 2026-09-23 report sized (2 vCPU, 4 workers, shared Redis), then the remaining heavy pages below | `scripts/load_test.py` 25/50/100 on the resized staging service, then a 6-hour soak |
| Heavy country analytics | `/ssa`, `/ssa/export`, team and country planning oversight (+ exports), team targets (+ export, recovery), `/ia/learning/`, `/ia/dashboard/`, `/declining-schools`, `/analytics/export` — 3–8 s single-request at 50,000 schools | Each is Python-bound over the whole country's records | SQL aggregation for the SSA trend and breakdowns; per-officer lazy sections for oversight; cached, revision-invalidated snapshots where the owner accepts the staleness window | Route sweep of these pairs (median of 3) |
| Interaction coverage | 363 controls without automated evidence, 26 state-changing | A broken control can ship unnoticed | Tests requesting each listed control's route; ratchet the ceiling down | `test_interaction_inventory` |
| Staging / production gates | Deploy, migrate, restore, rollback, canary, smoke | Unrehearsed recovery | Run the repository's rehearsal scripts against staging | Rehearsal logs, smoke report |

## 10. Remaining risks

| # | Risk | Severity | Note |
|---|---|---|---|
| R1 | One vCPU saturates from ≈25 concurrent users at 50,000 schools | **High** | Unchanged in kind from 2026-09-23; this release lowers the error rate, not the ceiling (§7) |
| R1b | Two workers use 1.8–2.7 GB at 50,000 schools | **High** | Above the 1 GiB instance; restarts would look like freezes |
| R2 | Country oversight builds every item in the country for the period | Medium | 2.4–3.6× faster; still 4–7 s for country roles |
| R3 | SSA workspace and its export aggregate 520,000 scores in Python | Medium | 4–5 s for country roles |
| R7 | Role dashboards can serve the previous portfolio for ≤ 300 s after a reassignment | Low–Medium | Needs ownership-change detection (queryset `.update()` bypasses signals); not attempted |
| R8 | Every Activity save invalidates all analytics caches | Low | Unchanged |
| R11 | Exports and DOCX→PDF run in the request | Medium | The Work Plan export is 4× faster, but still synchronous |
| R12 | 12 unwired domain services (§5), including `enqueue_ssa_confirmed_batch` whose docstring claims a caller | Low–Medium | Owner decision |
| R15 | 58 route/role pairs still repeat one statement ≥ 10× (per-priority, per-month, per-member loops) | Low | Listed in the sweep evidence |
| R16 | The closure checklist is up to 30 minutes stale on the Blocked Closures page and in System Health's integrity checks | Low | The queue itself is always live; the persisted copy follows the scheduled refresh |
