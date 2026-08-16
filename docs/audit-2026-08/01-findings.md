# End-to-End Audit — Findings Register (2026-08-16)

Baseline: commit 5ef10c98 · see [00-baseline.md](00-baseline.md).
Every finding below was **dynamically reproduced** before being recorded.
Repro tests live in `apps/core/tests/test_audit_2026_08_repros.py` and are kept
as the regression contract.

Severity model per mandate §30.

---

## AUD-004 · CRITICAL · Separation of duties defeated: Admin can verify work and release its money

**Law violated:** §3.19 ("No staff member may approve, verify, and disburse the
same chain of work") and §3.6 ("Only authorized finance roles may move money").

**What was wrong.** The platform has two authorization layers that disagreed.
`ADMIN_EXCLUDED_PERMISSIONS` (apps/core/rbac.py) correctly withholds `ia.verify`,
`payment.act`, and `budget.approve` from Admin, and the **DRF layer honoured it**
(`RequirePermissions` → 403). The **server-rendered layer did not**: it gated on
role membership instead of the permission key.

| Door | Gate before | Result |
| --- | --- | --- |
| `RolePermissionService.can_verify_ia` | `role in ["ImpactAssessment", "Admin"]` | Admin could verify |
| `finance_views.disburse_advance_action` | `active_role not in ("Accountant","Admin")` | Admin could disburse |
| `finance_views.clear_partner_payment_action` | same tuple | Admin could pay partners |
| `finance_views.process_reimbursement_action` | same tuple | Admin could reimburse |
| `finance_views.confirm_accountability_action` | same tuple | Admin could clear accountability |
| `budget_views.weekly_fund_request_disburse_action` | same tuple | second disburse door |
| `weekly_service.disburse` (service) | no check at all | inherited whatever the caller allowed |

`can_view_page` also grants Admin a blanket page bypass (apps/core/permissions.py),
so the page guard above these actions never stopped it either.

**Reproduced.** `test_admin_cannot_verify_an_activity` showed `can_verify_ia`
returning True for Admin; `test_admin_cannot_reach_the_disbursement_action`
returned **HTTP 400, not 403** — proof the request passed authorization and
reached the service body, failing only on a fake request id.

**Independently corroborated** by two separate sweeps that reached this
conclusion without contact.

**Fixed.**
- `can_verify_ia` now reads `Permission.IA_VERIFY` from the matrix.
- The five money actions call `_lacks_payment_authority()` → `Permission.PAYMENT_ACT`.
- `weekly_service.disburse` asserts `payment.act` **inside the service**, so a
  future endpoint cannot re-open the hole.
- Reading the disbursement queue remains open to Admin — seeing a queue is not
  authority to pay from it (the platform's own stated doctrine).

**Residual risk:** `budget.approve` / `countryBudget.approve` were not part of
this repro. `countryBudget.approve` is still *held* by Admin and `RVP_ROLES` /
budget-amendment `REVIEWER_ROLES` still include Admin by name — recorded as
**AUD-007** below rather than changed unilaterally, because whether Admin should
hold the country envelope authority is a governance decision, not a bug.

---

## AUD-005 · HIGH · Partner-delivered work booked as a named staff member's verified achievement

**Law violated:** §3.4 ("Partner-delivered work must not become personal staff
achievement") and §3.3 (only IA-verified *own* work earns credit).

**What was wrong.** The platform runs two achievement engines. The personal
ledger (`apps/targets/my_targets.py`) excludes partner work explicitly and says
so: *"no silent partner→CCEO credit"*. The milestone / Uganda-cascade engine
(`apps/hr/milestone_progress.py`) had **no such guard**: `_rule_matches` only
rejects a partner delivery when the rule sets `required_executor_type`, and
**45 of the 51 seeded rules leave it blank**. `refresh_period_targets` then
aggregated those credits into the employee- and team-scope period actuals.

Aggravating data fact: **230 of 231** partner activities in the dev database
carry a `responsible_staff_id`, which is exactly the field the employee scope
matches on.

**Reproduced.** A partner-delivered, IA-verified activity naming a CCEO as
responsible staff moved that CCEO's personal period target to `actual_value =
1.00`. The same event shows 0 in the personal ledger — two engines, two truths.

**Note on method:** my first fixture passed *tautologically* (the milestone
defaulted to `active=False`, so nothing matched). The finding was only confirmed
after asserting that a credit was actually created. The kept test asserts both
halves — credit exists, personal actual stays zero — so it can never pass for
the wrong reason again.

**Fixed.** Employee- and team-scope aggregation now excludes
`delivery_type="partner"`. Country scope deliberately still counts it: a partner
visit is real programme delivery and belongs in the country total — it is simply
never a person's personal result.

---

## AUD-006 · HIGH · Stored XSS: an operator-supplied school name could run script in any viewer's browser

**Law violated:** §3.20 / mandate §13.4 (XSS), and the privilege boundary.

**What was wrong.** `templates/pages/map/index.html` rendered
`{{ points_json|safe }}` inside a `<script>` block, where `points_json` was
`json.dumps()` of school, district and sub-county **names**. Verified directly:
`json.dumps` does **not** escape `</script>`, and `|safe` disables autoescaping.
A school named `</script><img src=x onerror=…>` therefore breaks out and executes.

Both aggravating factors confirmed in this codebase:
- CSP is `script-src 'self' 'unsafe-inline' 'unsafe-eval'` — inline injection runs.
- `CSRF_COOKIE_HTTPONLY = False` — the injected script can read the CSRF token
  and make authenticated state-changing requests as the victim.

School names arrive by CSV upload and are only `.strip()`ed. So a data-entry role
could execute script in the browser of any Admin/CD/PL who later opens the map:
privilege escalation, not just defacement.

A second sink of the same class: `headcount_by_department.labels` (free-text
`StaffProfile.department`) on the HR dashboard.

**Fixed.** Both converted to `{{ …|json_script:"id" }}` + `JSON.parse` — the
pattern the codebase already uses elsewhere. Verified that `json_script` escapes
the breakout to `<`. A regression test asserts a hostile school name renders
escaped **and** still reaches the page.

**Checked and found NOT exploitable:** the remaining `|safe` chart arrays carry
numbers or code-generated month abbreviations, not operator input.

---

## AUD-002 · HIGH · CI had been failing for weeks, so the test suite never ran on GitHub

`ruff format --check` failed on the last **eight** consecutive pushes (~2m40s
each). Because it runs before the tests, the 5,195-test suite had not executed in
CI for weeks — the same silent-red failure mode a previous pipeline audit fixed
once before. **Fixed** in 5ef10c98 (65 files reformatted; gates re-run locally).

**Residual risk:** nothing prevents recurrence. Recommend making the formatter a
separate always-first job with an alert, or a pre-push hook.

---

## AUD-003 · HIGH · Runtime image shipped a vulnerable setuptools

Scheduled Trivy scan failing on `setuptools 70.3.0` — **CVE-2025-47273** (path
traversal, HIGH), fixed in ≥78.1.1. **Fixed** in 5ef10c98 by upgrading in place in
the runtime stage (a build-stage `--prefix` copy would merge the new dist-info
beside the old one the scanner reads). Verification: next scheduled scan must
pass.

---

## AUD-001 · MEDIUM · Platform documentation materially understates the system

`PLATFORM_GUIDE.md` claims 509 surfaces / 914 routes / 11 roles / 70 permissions.
Live: **532 / 952 / 14 / 85**. The guide predates Business Transformation
entirely. Acceptance gate §33.20 ("documentation matches the audited system")
**cannot pass** until it is regenerated.

---

## AUD-007 · MEDIUM · Recorded, not fixed — Admin retains country-budget approval authority

`countryBudget.approve` is **not** in `ADMIN_EXCLUDED_PERMISSIONS`, and
`RVP_ROLES` (country_budget_service) plus budget-amendment `REVIEWER_ROLES`
include `"Admin"` by name. With AUD-004 fixed, Admin can no longer verify or
disburse, so the three-legged break is closed — but "approve the country
envelope" remains an operational authority held by the technical super-role.

**Not changed unilaterally:** whether Admin should hold it is a governance
decision for the platform owner, not an audit correction. Decide, then either add
it to the exclusion set or record the exception with its reason.

---

## AUD-008 · LOW · Seed data manufactures a state the application cannot produce

23,560 of 38,997 `SsaRecord` rows are `verification_status='confirmed'` with
**both** `verified_at` and `verified_by_user_id` NULL. All are `uploaded_by='seed'`.
The real confirmation paths (`ssa/services.py:541`, `ssa/upload_service.py:504`)
always stamp both. Not a production defect (production holds no operational
data), but any test or dashboard reading verification metadata off seeded data is
reasoning about an impossible state.

---

## AUD-009 · LOW · Two latent engine asymmetries recorded for the owner

1. **SF-ID gate asymmetry.** The personal ledger requires a Salesforce ID for
   "validated" credit; `record_activity_progress` never checks one, and the live
   IA workspace enforces none (the DRF path enforces it for Core only). A
   non-Core activity verified through the workspace with a blank SF ID earns full
   milestone credit while remaining provisional in the personal ledger.
2. **Mixed counting bases.** `refresh_period_targets` picks its aggregation by
   first-match on a set of counting bases; a milestone mixing bases (e.g.
   `UNIQUE_SCHOOLS_SUPPORTED` + `TEACHERS_TRAINED`) would silently count only the
   first. Not currently triggered by seeded data.

Also noted: `MilestoneActivityRule.minimum_completion_state` is never read — a
silent no-op for anyone who sets it.

---

## AUD-010 · LOW · Browser login has no per-IP throttle

DRF's `LoginRateThrottle` guards `/api/auth/login`; the HTML form login is bounded
only by per-account lockout. Password-spraying (one guess each across many
accounts from one IP) is not volume-limited on the browser surface. Mitigated by
per-account lockout + escalation + optional MFA. The two login doors have
asymmetric protection.

---

## Verified UPHELD (coverage record — no defect found)

**Finance.** One activity → one cost → one channel (`costing_service.apply_to_activity`
is the sole funnel and refuses to re-cost once money moved). Approved figures lock;
`BudgetAmendment` carries all five required fields. Double payment is genuinely
hardened: `select_for_update` + status recheck inside the atomic block +
`funding_guard.lock_disbursable_advances` in stable order + a
`uniq_partner_payment_per_activity` DB constraint. Integration failure
dead-letters and never un-verifies internal work.

**Targets.** Planned/actual/verified are distinct columns; no code writes planned
into actual. Both IA doors credit through one engine and nothing else creates
credit. Rates cascade as levels and are never summed (`SUMMABLE_MEASUREMENTS`
gates the reconciliation); count quarters sum to annual, months to quarter.
Return reverses credit by recomputation, and re-verification restores it to the
**original planned month**. Credit is idempotent per (rule, activity) with a DB
unique constraint, and provenance is snapshotted.

**Authorization.** All 952 routes walked: DRF defaults to `IsAuthenticated`, the
only `AllowAny` endpoints are the auth flows, and API docs are non-production
only. Record-level scope cleanly separates supervision from ownership
(`own_*` twins, `direct_portfolio_schools`, `may_write_school`). No
`Model.objects.get(id=…)`-then-render without a scope gate was found. Partner and
MFI isolation hold. Notifications are strictly recipient-scoped.

**Data integrity.** Fourteen invariant queries run against the live dev database:
zero orphans, zero duplicate school business ids, zero negative participants or
costs, zero impossible dates, zero verified-without-IA-actor, zero
paid-without-verification, zero duplicate open data-quality conditions. A DB CHECK
constraint enforces the Salesforce-ID-on-close law.

**Scale (§33.13).** See [02-scale.md](02-scale.md) — **PARTIAL PASS**.
