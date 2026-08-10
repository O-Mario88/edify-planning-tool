# Final Live Production Ecosystem Audit — 2026-08-09

**Target:** `https://edifyplanning.app`  
**DigitalOcean app:** `edify-planning-fra` (`8f8682cd-a00a-42d9-b9a6-4fa4b4140bde`)  
**Final decision:** **NO-GO — NOT PRODUCTION CERTIFIED**  
**Production impact from this audit:** no deployment and no manual database edits. The only live mutation was the platform's existing, idempotent fiscal-rollover command; it completed successfully.

Evidence in this report is labelled as **LIVE PRODUCTION VERIFIED**, **REPAIRED IN SOURCE**, or **NOT VERIFIED**. A passing local test is not treated as production evidence.

---

## 1. Certification decision

The current production release is coherent, available, and serving a healthy readiness response. It cannot receive the requested end-to-end production certification because the mandatory promotion chain cannot be completed and material production gates remain open:

1. There is no staging app or production clone. The required same-artifact staging verification, destructive/concurrency testing, rollback rehearsal, and promotion cannot be performed safely.
2. The repairs described below are in the working tree only. Production remains on commit `3dd2d6da6033193ee412aa78310335393368af2f`.
3. Production email is configured with the console provider and has no Resend credentials. Invitations, password resets, MFA email, and notification delivery are therefore not operational.
4. Only the Program Lead role was available in the authenticated production session. The other nine required role experiences and permissions were not live-verified.
5. Live System Health contains unresolved ownership, planning, classification, documentation, incident, and data-quality findings.
6. Several authenticated pages exceeded the requested interactive performance target.

Deploying the working tree directly to the only production app would violate the user's staging-first rule. The app is configured to deploy `main` on push, so no commit, push, or deployment was made.

## 2. Production release and infrastructure — LIVE PRODUCTION VERIFIED

| Item | Evidence |
|---|---|
| Active deployment | `d6305165-6f04-4c1d-9a48-998d3c779e22`, phase `ACTIVE` |
| Commit and release | `3dd2d6da6033193ee412aa78310335393368af2f` |
| Created | 2026-08-09 11:33:22 UTC |
| Build metadata | build time `2026-08-09T11:35:45Z`, static manifest `7ed43bfe409d8875`, immutable image reported |
| Web | 2 × `apps-s-1vcpu-2gb`, readiness at `/api/health/ready` |
| Scheduler | 1 × `apps-s-1vcpu-1gb`, 18 jobs registered |
| Database/cache | managed PostgreSQL 17 and Valkey 8, one node each |
| Migration path | dedicated pre-deploy migration job; no pending migrations detected |
| Final live check | `/api/health/build` reported the commit above; `/api/health/ready` returned `status=ok`, `db=up` |
| Deployment activity by this audit | none; no in-progress deployment at final check |

All 14 steps of the active deployment report success. Twelve build probes across both web instances previously returned the same commit, manifest, and build time; no mixed release was observed. The last 1,200 sampled web and scheduler log lines contained no application errors.

TLS, canonical-domain routing, HSTS delivery, static manifests, immutable asset caching, Brotli HTML compression, the web manifest, and `/sw.js` were live-verified. HSTS advertises `preload`, but its 30-day `max-age` is below the one-year preload requirement. The CSP still permits `unsafe-inline` and `unsafe-eval` for scripts.

## 3. Live route, browser, and access evidence

### Anonymous boundary — LIVE PRODUCTION VERIFIED

The parameterless production route sweep exercised 545 routes:

| Result | Count |
|---|---:|
| 302 authentication redirects | 365 |
| 401 API authentication failures | 137 |
| 405 method rejection | 20 |
| legitimate public 200 responses | 12 |
| closed 403 responses | 6 |
| canonical 301 redirect | 1 |
| production-disabled API-doc 404 responses | 2 |
| 5xx | **0** |

No anonymous data exposure was found. Six `/work-plan/*` endpoints return 403 instead of preserving the destination through a login redirect; this fails closed but is inconsistent with the rest of the product.

### Authenticated Program Lead — LIVE PRODUCTION VERIFIED

The existing authenticated session was a Program Lead (`domario@edify.org`). Twenty-four primary Program Lead routes were opened in the live browser with no visible server error, including Planning, Schools, Core Schools, Clusters, Partner Oversight, Projects, Coverage, Team Oversight, My Plan, Calendar, To-Dos, Actions, Debriefs, Work Plan, Fund Requests, Approvals, Monthly Planning, Performance, Targets, Analytics, Staff, and Reviews.

Direct requests to System Health, admin, IA, and disbursement surfaces redirected this role to the dashboard, as expected. Responsive checks at 390, 768, and 1440 CSS pixels found no horizontal overflow. The sampled authenticated pages had no missing image alternatives, unnamed buttons, or unlabeled form inputs.

The live mobile header still exposes 30–36 px controls and KPI cards use an `h4` without an intervening page heading. Both issues are **REPAIRED IN SOURCE**, with 44 px targets and a corrected `h2` KPI heading, but are not deployed.

The remaining nine roles are **NOT VERIFIED** in production: Administrator, Country Director, Regional Vice President, International Assistance, Managing Staff, Staff, Partner, Accountant, and Finance/Disbursement operators where separately scoped. A redirect observed under the Program Lead account is not evidence for those roles' workflows.

## 4. Live performance evidence

Public-route server-time sampling was generally within the 800 ms target; `/login` p95 was 880 ms. Authenticated browser timings showed material breaches:

| Route | Observed elapsed time |
|---|---:|
| Program Lead analytics | 6,619 ms |
| Core schools | 3,892 ms |
| To-Dos | 2,951 ms |
| Targets | 1,974 ms |
| Planning | 1,888 ms |
| Reviews | 1,544 ms |
| Debriefs | 1,489 ms |
| Schools | 1,362 ms |
| Partner oversight | 1,317 ms |
| Weekly requests | 1,300 ms |

These browser samples include network and rendering time and are not a load test. They are sufficient to reject a blanket claim that every high-value production surface meets the requested latency objective. Load, soak, failover, and chaos evidence is **NOT VERIFIED** because no safe production clone exists.

## 5. Scheduler, storage, and platform services — LIVE PRODUCTION VERIFIED

- The scheduler is alive with 18 registered jobs. Repeated executions were observed for analytics delivery, notification escalation, target-ledger sync, and school-action sweep. Daily, weekly, and annual jobs that did not fall in the observation window cannot be certified solely from a process heartbeat.
- The existing fiscal-rollover command was invoked once as a safe, idempotent operational check and completed successfully.
- Managed object-storage read, write, and delete probes succeeded.
- Referential-integrity, audit-chain, permission-guard, UI-health, professional-development, and finance-integrity checks in the deployed release returned clean results, subject to the finance detection gap repaired in source below.
- Production dependency and migration checks completed without a pending migration or known package vulnerability.

## 6. Live System Health findings — OPEN

| Severity | Finding | Status |
|---|---|---|
| Critical | Email provider is `console`; `EMAIL_PROVIDER=resend` and `RESEND_API_KEY` are absent | Open; delivery workflows cannot be certified |
| Critical | 5 incidents were unacknowledged for more than 60 minutes | Open |
| High | 2 recurring incidents have no owner | Open |
| High | 16,134 schools are unclustered | Open operational backlog |
| High | 1,060 core schools are missing annual plans | Open operational backlog |
| High | 244 active core plans are missing recommendations | Deterministic repair exists; not applied pending staged release |
| High | 54 active schools have no district | Open data-quality backlog |
| High | 1 cluster (`Akokoro - Cluster`) has no owner | Open; the only suggested person is not auto-assigned without authority |
| Medium | 2 staff candidates and 2 owner invitations are pending | Open operational work |
| Medium | 136 districts lack classification | Open data-quality backlog |
| Medium | 172 SSA records are unmatched and have no suggestion | Open data-quality backlog |
| Medium | 364 records have weak location data | Open data-quality backlog |
| Medium | 3 catalogue mappings are ambiguous | Open configuration decision |
| Medium | 2 documents have no owner and 2 mandatory documents lack Help mappings | Open governance/documentation work |
| Warning | 1 IDE milestone issue | Open |

SMS uses the console provider as well, although no enrolled SMS delivery requirement was found in the inspected data.

## 7. Remediation ledger — REPAIRED IN SOURCE, NOT DEPLOYED

### R1. Cross-channel duplicate-payment exposure

The audit found that period, dashboard, and weekly disbursement paths did not consistently require and lock the same approved `AdvanceRequest`. Some missing, self-funded, returned, cancelled, or already-paid advance states could pass one path, while the prior System Health detector looked only at weekly funding rows.

Repair:

- Added one canonical funding guard that locks the budget line and its advance with `select_for_update`.
- Period disbursement accepts only `pending_responsible_confirmation`, `confirmed_for_advance`, or `submitted_to_accountant`; weekly disbursement accepts only confirmed/submitted states.
- Missing, self-funded, not-requested, returned, cancelled, and already-paid states fail before the parent request is mutated.
- Dashboard and service write-backs update only the locked advance IDs.
- Added a critical System Health detector for payable funding lines without an approved advance.
- Added regression coverage for cross-channel duplicates, ineligible states, missing advances, atomicity, and authenticated workflow behavior.

This closes the discovered source defect, but production remains on the earlier implementation. It is a hard deployment gate until the repaired artifact passes staging and live verification.

### R2. Scheduler health false negatives across processes

Web-process health relied too strongly on in-process scheduler state. The repaired implementation accepts persisted worker evidence, calculates cron next-due time, and applies a 20-minute heartbeat boundary. Five cross-process regression tests were added.

### R3. Scheduling-rule repair auditability

The repair command now emits hash-chained audit events for deterministic changes and remains idempotent. The single known stale activity scheduling rule was not mutated in production; it should be repaired only after the command itself is released through staging.

### R4. Activity rate semantics

The intentional `PARTNER_MEETINGS_ADMIN` staff-delivery profile no longer raises the false “staff using Partner rate” critical finding. A regression test captures the policy distinction.

### R5. Planning and school-data query efficiency

SSA lookup and core-school self-healing were changed from repeated per-school queries to bulk operations, with regression coverage. Planning benchmark vocabulary now recognizes `schools_invited`.

### R6. Cluster ownership semantics

Cluster-owner resolution no longer silently overwrites an intentionally ownerless cluster. Explicit direct-portfolio ownership remains the contract for country-level administrative scope, with stale fixtures corrected and owner behavior covered.

### R7. Mobile and design-system defects

The top-bar touch targets, KPI heading hierarchy, table/identifier typography, and stale visual-contract assertions were corrected. The Tailwind bundle and platform inventories were regenerated.

### R8. Production email boot gate

Production preflight now requires `EMAIL_PROVIDER=resend` and a Resend API key. The deployment spec contains secret-reference placeholders only; no credential was invented or stored. The next release will intentionally refuse to boot until an authorized operator provisions the real secret.

## 8. Repaired-source verification

The final clean-schema suite and release gates passed on the working tree:

| Gate | Result |
|---|---|
| Django tests | **4,834 run; suite OK** in 758.751 s; 2 skipped, 1 expected failure |
| Finance-focused tests | **171 passed**, including authenticated smoke coverage |
| Ruff lint | pass |
| Ruff formatting | 1,290 files conform; pass |
| Django system check | pass |
| Migration drift | none detected |
| CSS/Tailwind build | pass |
| Bandit medium/high | 0 findings |
| `pip-audit` | no known vulnerabilities |
| `npm audit --audit-level=high` | 0 vulnerabilities |
| Patch whitespace | pass |

Local Redis was unavailable during the concise Django gates, so Django explicitly used its LocMem fallback for those commands. The full test suite still passed; cross-process cache behavior was separately covered by the new persisted scheduler-health tests. This local fallback is not production evidence.

## 9. Required path to certification

1. Provision an authorized staging app and production-like database/cache/object-storage clone without exposing production secrets or personal data.
2. Provision and verify Resend credentials in staging, then production through the platform secret store.
3. Build one immutable artifact from the reviewed repair commit; record its digest and migration set.
4. Run the complete ten-role workflow matrix, finance concurrency tests, repair-command dry runs, performance/load tests, scheduler-cycle observation, and rollback rehearsal on staging.
5. Apply the recommendation and scheduling repairs on staging, verify counts and hash-chain evidence, and promote that exact artifact.
6. Drain the prior production instances, confirm the live build digest/commit, run migrations and repair commands once, invalidate stale caches, and repeat the authenticated browser/database/log checks.
7. Resolve or formally accept every open System Health item above. Certification requires live before-and-after evidence, not the local results in this report.

Until those steps are completed, the objective result is **NOT APPROVED / INSUFFICIENT LIVE EVIDENCE**. The existing production release was left available and unchanged.

---

## 10. Follow-up repair pass — R9–R11

Three further defects were repaired in source after the report above. All remain
**REPAIRED IN SOURCE, NOT DEPLOYED**; production is still on `3dd2d6da`.

### R9. The duplicate-payment guard still failed open on unlinked requests

`funding_guard.lock_disbursable_advances` is correctly inverted — an allowlist
that treats a missing advance as a blocker — and the dashboard and weekly
channels call it unconditionally, so an empty line set raises. **The period
channel did not.** `services.disburse` wrapped the call in `if line_ids:`, so a
FundRequest whose items all carried an empty `activity_schedule_cost_line_id`
skipped the shared ledger entirely and released money with no traceable
Planning source — the one property every funding path is required to prove.

`FundRequestItem.activity_schedule_cost_line_id` is a plain
`CharField(max_length=30)` with no null/blank guard, so that state is
representable.

Repair: the guard is now called unconditionally in all three channels.
Regression test `test_period_disbursement_refuses_items_with_no_cost_line_linkage`
asserts the request stays `approved` and the shared advance is untouched.

### R10. The country-wide analytics map was rebuilt on every page load

`country_map_context` is country-wide by contract — the fiscal year is its only
filter — yet four surfaces (PL analytics, CD analytics, the analytics dashboard,
projects impact) each rebuilt it independently on every request: 9 aggregate
queries spanning 136 districts, 2,562 sub-counties, 16,274 schools and 123,496
SSA scores. The per-district N+1s had already been fixed, so the query count is
constant — but each of the 9 is a full-country scan.

Repair: one FY-keyed entry through the existing `stampede_safe_get_or_compute`
primitive (fail-open; tests bypass it via `COUNTRY_MAP_CACHE_SECONDS=0`).
Sharing across viewers is sound precisely because the payload carries no role,
portfolio or user scope, and the calling view still enforces permission before
this code is reached. Three regression tests cover payload equality with the
uncached builder, zero queries on the second build, and FY-keyed isolation.

**The production latency effect is NOT VERIFIED** — it cannot be until the
artifact is deployed. What is proven is that 9 country-wide aggregations are
eliminated per cache hit on four surfaces.

### R11. 244 CorePlans carry no recommendation

Confirmed against the live database: all 244 active CorePlans have an empty
`interventions`, all 244 have a `baseline_ssa_record_id`, and none has a
completed assessment. `CorePlan.interventions` records *why* a school's
nine-slot package targets the interventions it does — the four weakest verified
interventions, the two most critical assigned to a Partner.

Repair: `python manage.py repair_core_plan_recommendations` — dry run by
default, idempotent, batched, and audited per plan
(`data_repair.core_plan.recommendation_backfill`). It replays the canonical
`CoreInterventionRecommendationService.recommend`, never a hand-written value,
and **refuses to write for a school without verified SSA**, reporting it for
manual review instead. Repaired records are marked `"backfilled": True` so they
can never be mistaken for an onboarding-time capture. Seven regression tests.

Not yet run against production — it belongs to the staged release like every
other repair here.

### Verification for this pass

| Gate | Result |
|---|---|
| `apps.fund_requests`, `apps.analytics`, `apps.core_schools` | **562 tests OK** (1 pre-existing expected failure) |
| Ruff lint / format | pass |

### What this pass deliberately did NOT do

Most remaining System Health items are **operational work, not defects**, and
inventing data for them would breach the no-fabrication rule:

- **16,134 unclustered schools** — only 140 `school_cluster_assignment` rows
  exist for 16,274 schools. Cluster assignment has not been carried out yet.
- **1,060 core schools missing annual plans**, 5 unacknowledged incidents,
  2 pending invitations, 2 recurring incidents without an owner, 1 ownerless
  cluster — each needs an authorized human decision.
- **54 schools with no district, 136 unclassified districts, 172 unmatched SSA
  records, 364 weak-location records** — data-quality backlogs whose correct
  values are not derivable from what the database holds.

A repair command can only replay a deterministic rule over existing evidence.
None of the above has that evidence.

---

## 11. R12 — the email boot gate was an outage risk under the revised scope

The acceptance scope was revised to exclude external email delivery: *"Email
delivery must not be included as a hard production blocker"*, and GO may not be
withheld for it.

R8 had done the opposite. `boot_gates.verify_or_exit` treated a missing mail
provider as a fatal gate and called `SystemExit(1)`, so **the next release would
have refused to boot** without a `RESEND_API_KEY` — taking both web instances
and the scheduler down to protect invitations and password resets. Under the
old scope that was a defensible trade. Under the revised scope it is a
self-inflicted outage waiting for the first deploy.

Verified there was no second gate: `config/settings/prod.py` exits only on JWT
secret strength, `SUPER_ADMIN_PASSWORD`, `FIELD_ENCRYPTION_KEY` and
`ALLOWED_HOSTS`. `boot_gates.py` was the only email blocker.

Repair: the check is retained and still runs on every production boot, but it
now writes to stderr under "Production environment warnings (not blocking
boot)" instead of exiting. The condition remains a standing System Health
finding (`apps/core/health.py:143`) with an owner, the real consequence and a
resolution link — so a broken mail channel can still never pass silently.

Regression test
`test_a_missing_provider_warns_but_never_stops_the_process_booting` asserts
`verify_or_exit()` does not raise and that the warning is printed;
`test_production_reports_a_missing_provider` (renamed from
`..._fails_closed_...`, which no longer described the behaviour) still asserts
the condition is detected.

**Email is now correctly a visible degradation rather than a deployment gate.**
Invitations, password resets and email MFA still will not deliver until a
provider is provisioned — that is a real operational limitation, now excluded
from GO by decision rather than hidden.

---

## 12. §43 historical-data integrity scan — LIVE PRODUCTION VERIFIED

Read-only detection queries against the production database
(`default_transaction_read_only=on`, SELECT only, no writes).

| Check | Result |
|---|---:|
| Activities with no cost line | **0** |
| Cost lines with no Cost Catalogue snapshot | **0** |
| Activities with no Planning source | **0** |
| FundRequestItems with no cost line | **0** |
| WeeklyFundRequestLines with no budget line | **0** |
| Active schools with no staff owner | **0** (all 16,274 assigned) |
| Closed schools still operationally active | **0** |
| More than one AdvanceRequest per budget line | **0** |
| Active CorePlans without exactly 9 slots | **0** (all 244 correct) |
| Duplicate target credits (same source counted twice) | **0** |
| Target credits with an invalid validation status | **0** |
| SSA records not confirmed | **0** of 15,437 |
| Active schools with no district | **54** (known backlog) |
| Active clusters with no owner | **1** (known backlog) |
| Cost line in more than one active FundRequest | **1** (own + team scope, by design) |

Three findings worth stating plainly:

1. **Cost lineage in production is intact.** Every Activity has a cost line,
   every cost line carries its catalogue snapshot, every funding line traces to
   a budget line. §47's "Activity without cost" and "Fund Request without source
   ActivityBudgetLine" hard gates are clean *in the data*.
2. **R9's hole is latent, not live.** Zero FundRequestItems carry an empty
   `activity_schedule_cost_line_id`, so the fail-open path could not have been
   taken with current data. The defect was real and is fixed; production was
   never exposed to it.
3. **No unverified SSA is driving decisions.** All 15,437 SSA records are
   `confirmed`. §47's "Unverified SSA driving official decisions" gate is clean.

The single "cost line in more than one active FundRequest" is the own-scope +
team-scope pair on the one production Activity. That overlap is intentional (a
PL's team request aggregates their members' own lines) and is now correctly
prevented from paying twice by `funding_guard.lock_disbursable_advances`.

---

## 13. The certification path is one decision, and the platform already supports it

Every gate still open — the ten-role matrix, the 25 end-to-end journeys, the
same-artifact promotion loop, destructive/load/soak testing, and rollback
rehearsal — is blocked on the same missing thing: **there is no non-production
environment.** One DigitalOcean app exists.

This codebase was built for that environment. Nothing new has to be written:

- `EnvironmentStamp.ENVIRONMENTS = ("local", "staging", "production")` —
  `staging` is a first-class stamp, and `manage.py stamp_environment --to
  staging` is the supported way to set it. The boot guard then refuses the
  cross-environment mistakes that make clones dangerous.
- `manage.py seed --demo` creates demo accounts **for every role**, sample
  geography and sample operational data. It refuses to run in production by
  design. That single command answers both "nine roles cannot be
  authenticated" and "production has no operational data to certify."
- Seeding rather than copying means **no real school, staff or financial data
  leaves production** — the privacy problem a database clone would create
  simply does not arise.

### Proposed sequence

1. Create a staging app on the same repo, pinned to the reviewed repair commit
   (one small web instance, one dev-tier database; the cache is optional —
   `stampede_safe_get_or_compute` is fail-open).
2. `stamp_environment --to staging`, then `seed --demo`.
3. Run the ten-role matrix and the 25 journeys there. Label everything
   **STAGING VERIFIED** — never live-production evidence.
4. Run the destructive, concurrency, load, soak and rollback tests there, which
   §3 forbids against production.
5. Apply `repair_core_plan_recommendations` on staging first, verify the counts
   and the audit chain, and only then promote.
6. Promote the **exact same artifact** to production, apply migrations, drain
   the old instances, invalidate caches, and repeat the live browser and
   database checks.
7. Re-run the live production evidence in this report against the new release.

Until step 1 exists, steps 3–7 cannot produce evidence, and no amount of
further source-level work changes that. **This is an authorization decision
about provisioning, not an engineering problem.**

---

## 14. Staging is now buildable — R13

Provisioning was authorized. Two artifacts now exist; neither has been applied,
and **production has not been touched**.

### `config/settings/staging.py`

Inherits `prod` wholesale, so every fail-closed gate production runs, staging
runs. Two values differ, both about identity rather than strictness:

- `IS_PRODUCTION = False` — `seed --demo` refuses to run when true, and demo
  data is the entire point of staging. This opens no hole: the authoritative
  protection is the database stamp, and `seed --demo` still refuses any
  database stamped `production` regardless of what the process believes.
- `ENVIRONMENT = "staging"` — `prod` hardcodes `"production"` so a missing env
  var can never weaken the stamp guard on a live host. Staging needs its own
  identity for that guard to work in the other direction.

Verified by loading the module: `IS_PRODUCTION=False`, `ENVIRONMENT=staging`,
`DEBUG=False`, `AUTHZ_MODE=enforce`, `SPACES_PREFIX=edify-staging`,
`USE_SPACES_STORAGE=True`. It was also confirmed to *reject* an incomplete
configuration exactly as `prod` does (missing field key, dev-seed enabled,
shadow authz) — staging is not a softer environment.

### `.do/staging.yaml`

A separate app, `edify-staging-fra`. Deliberate differences from production:

| | Production | Staging |
|---|---|---|
| Branch | `main` (deploy on push) | `staging` (deploy on push) |
| Web instances | 2 × 1vcpu-2gb | 1 × 1vcpu-1gb (raise to 2 for the race tests) |
| Database | managed, `production: true` | dev tier, `production: false` |
| Spaces prefix | `edify-production` | `edify-staging` |
| Email | resend | console — no staging run can mail a real person |
| Data | real | seeded via `seed --demo` |

Security posture is otherwise identical — `AUTHZ_MODE=enforce`, all dev flags
false, SSL/cookie hardening on, migrations in a `PRE_DEPLOY` job so the
two-instances-racing-migrate failure is rehearsed the same way.

Tracking the `staging` branch rather than `main` is deliberate: production
deploys on every push to main, so a staging app on main would rebuild in
lockstep and prove nothing.

### What blocks app creation

Production's secrets are stored encrypted per-app (`EV[1:...]`) and are not
readable outside that app — correctly. They cannot be copied to a new app, and
I will not invent object-storage credentials. Seven values must be set by an
authorized operator before the app can boot; the spec carries `REPLACE_ME`
placeholders and `prod`'s validation refuses to start until they are real.

The one that needs a decision rather than a value: staging reuses the
production Spaces **bucket** under a different prefix. That is enough to keep
staging uploads out of production evidence, but a shared access key can still
reach the production prefix. If hard isolation is required, create a dedicated
staging bucket and key. That is a policy call, not a default to assume.

---

## 15. Authenticated Admin session — LIVE PRODUCTION VERIFIED

An Admin session (`omario.edwin@gmail.com`) was supplied and used **read-only**:
GET requests only, with logout/delete/approve/disburse/withdraw/submit routes
excluded from every sweep so the session could not mutate production.

### System Health, rendered live at `/system-health`

Roughly 48 of ~50 checks report **✓ Clean** on the live database, including
several that map directly onto §47 hard gates:

| Live check | Result |
|---|---|
| Data Leakage Scan | ✓ no test data in production |
| RBAC Gating Scan | ✓ **100% of routes guarded, no vulnerabilities** |
| Audit Chain Integrity | ✓ hash chain re-verified end-to-end, no tampering |
| Demo/seed data on production | ✓ Clean |
| Environment stamp | ✓ Stamped |
| Duplicate partner payments | ✓ Clean |
| Partner activities paid without a ledger row | ✓ Clean |
| Budget lines missing a Cost Catalogue reference | ✓ Clean |
| Finance-cleared activities not closed | ✓ Clean |
| Over-spend accountability without a reimbursement | ✓ Clean |
| Skipped IA verification / clearance before IA | ✓ Clean |
| Current-FY SSA satisfied by a prior-FY record | ✓ Clean |
| Static links / HX targets that do not resolve | ✓ Clean |
| HTMX controls targeting a missing element | ✓ Clean |
| Buttons with no action or disabled state | ✓ Clean |
| Templates with mock/sample data markers | ✓ Clean |
| All 12 Daily Visit Batch integrity checks | ✓ Clean |

The last four are §37's "dead routes: 0 / dead controls: 0" and §47's "analytics
returning fabricated fallback values", verified live by the platform's own
detectors rather than by inspection.

### R14 — System Health reports a false "Scheduler Disabled" on production

**Severity: HIGH. LIVE PRODUCTION VERIFIED. Fixed in source (R2), not deployed.**

The live page reports:

> Background Automation → Scheduler → **Disabled (ENABLE_BACKGROUND_JOBS=false)**
> "Provision the dedicated worker process and set ENABLE_BACKGROUND_JOBS."

The worker it says to provision **is already running**. Scheduler logs from the
same window show `target_ledger_sync_job` and `analytics_report_delivery_job`
executing successfully at 19:30 EAT, with 18 jobs registered.

Root cause: `ENABLE_BACKGROUND_JOBS` is correctly `false` on the web service
and `true` only on the scheduler worker — but System Health renders in a web
process and read its **own** process's flag as if it were the platform's state.

This matters beyond cosmetics. §47 makes "required scheduler disabled" a hard
gate, so the one page an operator would consult to clear that gate currently
asserts the gate is failing, and tells them to fix something that is not broken.

The R2 repair already in the working tree resolves it exactly:
`scheduler_available = enabled or SchedulerHealthService.is_scheduler_process_alive()`,
reporting "Dedicated scheduler activity observed" from shared execution history
rather than trusting one process's env var. **Live production has now confirmed
both the defect and the fix's necessity.**

### Remaining non-clean checks (all previously known, all operational backlog)

- 16,134 schools without cluster assignments
- 136 districts missing primary/secondary classification
- 364 schools with no coordinates and weak address data
- 172 unmatched SSA records with no suggested match — the page itself names the
  deterministic remedy, `manage.py recompute_unmatched_ssa_suggestions`, which
  already exists in the repo and should be run on staging first.

### Performance

`/system-health` served in **6.4 s** against its own 1500 ms SLO
(`SLO_MS` in `apps/system_health/test_load_scale.py`). Measured once, including
network from outside the region — not a p95 — but far enough outside the budget
to record as a real finding rather than noise.

---

## 16. R15–R18 — the fixable remainder

### R15. The existing core-recommendation repair wrote empty recommendations

**Severity: HIGH. Found while checking my own work for duplication.**

`repair_ecosystem_data --only core-recommendations` already existed. It called
`CoreInterventionRecommendationService.recommend(school)` but never checked the
`available` flag. For a school with no verified SSA the service correctly
returns `{"available": False, "rows": []}` — and the command persisted that as:

```python
{"recommended": [], "maintenance": False,
 "captured_at": ..., "algorithm_version": 1, "backfilled": True}
```

An **empty recommendation wearing the shape of a real one**, for a school
nobody has assessed. `CorePlan.interventions` decides which four interventions
a nine-slot package targets and which two go to a Partner, so this is the
fabrication the no-mock-data rule exists to prevent. Running it against
production would have stamped all 244 plans.

Repair: check `available`, skip anything not derivable, and report it as
MANUAL REVIEW in the summary line. Orphan plans (no School row) are counted
separately rather than silently `continue`d. The audit payload now records the
real row count and maintenance flag instead of a hardcoded `[]`.

I had written a second, safer command for this before finding the original.
That duplicate has been **deleted** — one repair path, not two — and its seven
regression tests retargeted onto the canonical command. The test that matters
(`test_a_school_without_verified_ssa_is_left_for_manual_review`) fails against
the old behaviour.

### R16. Work Plan routes answered 403 instead of the sign-in form

Six routes returned a bare `HttpResponseForbidden("Sign in first.")` to signed
-out visitors where 366 other guarded routes redirect to `/login` with the
destination preserved. With a 30-minute idle session, following a stale Work
Plan link meant an error page instead of a login form.

Fixed to match `require_page_permission`. Deliberately method-aware: safe
methods redirect, mutations still return 403 — bouncing a signed-out POST to a
login page would drop its body and imply it could be replayed.
Authenticated-but-unauthorized stays 403 everywhere; that is a real refusal.

### R17. HSTS advertised `preload` on a 30-day max-age

`SECURE_HSTS_SECONDS` was 30 days with `SECURE_HSTS_PRELOAD = True`. No browser
accepts a preload claim under 31536000, so the directive was inert and the site
advertised a protection it did not have. Raised to one year, the standard
production value. Actual submission to the preload list stays a deliberate
human step — it is much harder to undo than to set.

### R18. System Health rebuilt every 30 seconds

`/system-health` is stampede-cached, but on a 30-second TTL against a report
measured at **6.4 s cold on production**. One operator reading one page
triggered a full rebuild roughly every other scroll. Raised to 120 s: what it
reports moves on the timescale of imports and scheduling, not seconds.
Deliberately not longer — this is the page someone refreshes during an incident
to see whether a repair landed, and a five-minute stale window would make it
lie to them.

**This does not make the report faster.** The underlying 6.4 s is unchanged and
remains unprofiled at production scale. Note the open question: the scale test's
own 1500 ms SLO for this page **passes** at 15,000 schools locally, so the
fixture does not reproduce whatever production is paying for. That gap is
unresolved.

### Deliberately NOT changed: the CSP

`script-src` allows `'unsafe-inline'` and `'unsafe-eval'`. On reading the
policy's own documentation this is a justified, recorded constraint rather than
an oversight: Alpine.js compiles `x-data` and `@click` expressions with
`new Function()`, and its CSP-friendly build accepts a restricted syntax every
component here would have to be rewritten into. That is a project, not a
settings change, and it is not something to attempt with no staging environment
to verify against. Downgrading this from "medium defect" to "known constraint"
— my earlier severity was wrong.

### Verification

| Gate | Result |
|---|---|
| `apps.system_health`, `apps.core_schools`, work-plan signed-out | **227 tests OK** |
| CSP / DO deployment contract / production gates | **64 tests OK** |
| Ruff check + format | pass (1,293 files) |
| Platform inventories | regenerated after every edit |

---

## 17. Correction — the public-route latency findings were a measurement artifact

**Section 4 of this report claimed `/login` served a p95 of 880 ms against the
800 ms target. That finding is withdrawn: it was my measurement, not the site.**

`time_starttransfer − time_pretransfer` was used as "server think-time". It is
not. It spans end-of-connection-setup to first byte, which still contains a
full request/response network leg to Frankfurt.

Calibrated against a control: `/api/health/live` returns a 16-byte JSON literal
and performs **no database work at all**. Measured from the same client:

| Route | p50 | min | p95 |
|---|---:|---:|---:|
| `/api/health/live` (zero work — this is the floor) | 311 ms | **300 ms** | 320 ms |
| `/login` | 346 ms | 327 ms | 409 ms |

A JSON literal cannot take 300 ms to produce. That 300 ms is the network floor
from this client. Subtracting it:

| Route | Real server time | Verdict |
|---|---:|---|
| `/login` | **~35 ms** | well inside target |
| `/` | ~33 ms | inside target |
| `/api/health/ready` | ~40 ms | inside target |
| `/system-health` | **~6.1 s** | genuinely over its 1500 ms SLO |

Confirmed independently: `GET /login` executes **0 queries in 1 ms** locally, so
there was never 880 ms of work there to find.

**Net effect on the ledger:** F-series latency findings against public routes
are withdrawn. The confirmed performance defects are the heavy authenticated
pages only — `/system-health` (~6.1 s) and PL analytics (6.6 s in the earlier
browser sample).

## 18. Why `/system-health` is slow, and why it is not being refactored today

Profiled directly: `system_health_report()` issues **301 queries and takes
1,128 ms against a completely empty database.** The cost is structural, not
data volume — roughly 50 integrity checks, each running its own counts.
Heaviest repeated shapes: 30 separate `COUNT(*)` over `activity`, plus 9 + 9
more joining `activity_catalogue_item`, and 13 over `pd_request`.

Exact-duplicate analysis: **300 of the 301 queries are distinct.** There is no
free win from de-duplication or request-level memoization — every query is a
different check asking a different question.

This also explains the local-passes/production-slow gap left open in §16. The
scale test meets its 1500 ms SLO because its database is a local socket. In
production the database is network-attached, so 301 sequential round trips cost
hundreds of milliseconds before a single row is read.

The real fix is to collapse the per-check counts into conditional aggregates
(`COUNT(*) FILTER (WHERE …)`) — one query per table instead of ~68 against
`activity`. **That refactor is deliberately not being attempted here.** It
rewrites the platform's own safety monitoring across ~50 checks with distinct
semantics, with no staging environment to verify against, and a health check
that silently reports a false "✓ Clean" is far more dangerous than a slow page.
It is recorded as the correct next step, scoped and diagnosed, for a change
with somewhere to be verified.

R18's TTL change (30 s → 120 s) reduces how often the cost is paid. It does not
reduce the cost.

---

## 19. R19 — `/ssa/unmatched` returned 37 MB in 61 seconds

**Severity: HIGH. LIVE PRODUCTION VERIFIED. §47 "unbounded production queryset".**

The authenticated Admin sweep measured `/ssa/unmatched` at **61,363 ms and
37,333,838 bytes**. It was the worst result on the platform by an order of
magnitude.

Cause: the page is paginated (~33 records per page), but the school picker in
**each row** rendered every active school:

```django
{% for school in schools %}
<option value="{{ school.id }}">{{ school.name }} ({{ school.school_id }})</option>
{% endfor %}
```

`schools_list = active_schools().order_by("name")` is all **16,274** rows, so
the response carried roughly 33 x 16,274 ≈ 537,000 `<option>` elements. The
queryset is per-page-bounded on records and completely unbounded on schools.

Repair: the option list is identical for every row, so it is emitted **once**
per page in a `<template>` and copied into a picker on first interaction (and
on submit, so a keyboard-only or programmatic submit cannot post an empty
select). **The posted field is unchanged** — still `name="school_id"` carrying
a School pk — so the view, its scoping and its canonical SSA-writer path were
not touched.

Measured on the same page in tests: option count grows by exactly **one per
row** (its own placeholder) instead of by the full school list. Expected
production effect ≈ 37 MB → ≈ 1.2 MB raw, before Brotli.

Four regression tests pin the properties that matter: option count does not
multiply by rows, the shared list is still shipped in full, growth per row is
the placeholder only, and the posted field name is unchanged.

> Method note: the first threshold I wrote asserted bytes-per-row < 2 KB and
> failed at 3.4 KB. That was my threshold being wrong, not the fix — a row here
> legitimately carries two forms, two CSRF tokens and a lot of utility classes.
> Isolating option **count** (68 → 86 for +18 rows) proved the list is rendered
> once; the test now asserts that directly rather than a byte proxy.

### Other results from the authenticated Admin page sweep (200 routes)

`0` server errors. One route **timed out at 20 s**:
`/core-schools/champion-candidates` — recorded as an open defect, not yet
diagnosed. Otherwise 168 x 200, 20 x 302, 6 x 405, 4 x 400, 1 x 404.

Slowest pages (total, including the ~300 ms network floor established in §17):

| Route | Time | Size |
|---|---:|---:|
| `/ssa/unmatched` | 61,363 ms | 37.3 MB |
| `/core-schools/champion-candidates` | **timeout** | — |
| `/system-health` | 18,479 ms | 208 KB |
| `/public-holidays/` | 14,254 ms | 167 KB |
| `/help/context` | 9,804 ms | 169 KB |
| `/admin-panel/page-access-matrix` | 8,393 ms | 697 KB |
| `/core-school-health` | 7,093 ms | 1.32 MB |
| `/team-planning-oversight/` | 6,595 ms | 189 KB |
| `/ssa` | 6,414 ms | 269 KB |
| `/ssa/manual/` | 5,954 ms | 1.83 MB |

Only `/ssa/unmatched` has been repaired. **The rest are open** — including two
further megabyte-scale responses (`/core-school-health`, `/ssa/manual/`) that
look like the same unbounded-render shape and deserve the same treatment.
