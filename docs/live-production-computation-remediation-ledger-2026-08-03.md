# Live Production Computation Remediation Ledger — 2026-08-03

Production URL: `https://www.edifyplanning.app`

Evidence labels in this ledger are deliberately strict:

- **LIVE PRODUCTION VERIFIED** — observed in the authenticated production UI or public production health endpoint.
- **REGRESSION VERIFIED** — reproduced and checked by the repository's automated tests.
- **NOT VERIFIED** — requires infrastructure, database, worker, log, or another-role access that was not available to the Program Lead browser session.

## LP-2026-08-03-001 — Admin plan classified as field work

- Severity: High
- Calculation/feature: Planning taxonomy → Work Plan → Weekly Fund Request → Monthly Budget
- Production URLs: `/work-plan`, `/fund-requests/weekly`, `/accounts/monthly-request/`
- Role: Program Lead
- Activity ID: `cmsd88qu800qrc8ds4z79`
- Weekly request ID: `cmsd88qyh00c2u7ds4ze0`
- Expected: one Admin activity and one Admin Budget line totalling UGX 40,000
- Actual before: Work Plan showed Admin, but Weekly labelled the source Cluster Training and Monthly grouped it as School Visits/Other
- Difference: monetary total UGX 0; category attribution incorrect on two downstream surfaces
- Source data/formula: one `ActivityScheduleCostLine`, `1 × UGX 40,000 = UGX 40,000`
- Root cause: downstream category functions ignored `programme_activity_type=admin` and used field-activity fallbacks
- Source repair: canonical category mapping now gives Admin precedence and uses the persisted activity name snapshot
- Frontend repair: downstream weekly/monthly labels consume the repaired canonical category
- Tests: `apps/frontend/test_fund_request_periods.py`
- Production release before: `2bafebe994c1ed9ac61a43e6d6ef615b9c5f8fa0`
- Production release after: `860f6e828ec3df8d807eeaf7ff2e7b7ae16da766`
- After evidence: Work Plan = Admin/UGX 40,000; Weekly = Admin/one request/one exact row/UGX 40,000; Monthly = Admin Budget/UGX 40,000; Q4 = UGX 40,000; FY = UGX 40,000; live CSV = one request row with `Total Amount (UGX)=40000`, `Disbursed (UGX)=0`, and `pending_responsible_confirmation`
- Idempotency: three live reloads retained one source activity, one exact cost row, and UGX 40,000
- Status: **Closed — LIVE PRODUCTION VERIFIED**

## LP-2026-08-03-002 — Governed school recommendation omitted on submit

- Severity: High
- Calculation/feature: Planning drawer → atomic Activity creation → Cost Catalogue provenance
- Production URL: `/planning`
- Role: Program Lead
- School ID: `27962`
- Recommended catalogue item ID: `cmsa71dyd00px2me0exl6`
- Expected: the visible EdTech Foundations recommendation is submitted as the governed catalogue item
- Actual before: the form submitted only the broad `in_school_training` purpose; production had multiple approved matching catalogue items, so the server correctly refused to guess and returned a sanitized error
- Difference: no Activity was created; atomicity held and no partial cost/request/budget row existed
- Root cause: the drawer displayed the selected catalogue recommendation but did not include its ID in the POST
- Source/frontend repair: the form now submits one hidden `catalogue_item_id` sourced from the visible governed recommendation
- Tests: `apps/frontend/test_schedule_drawer_purpose.py`, `apps/frontend/tests.py`
- Production release after: `860f6e828ec3df8d807eeaf7ff2e7b7ae16da766`
- After evidence: live drawer contains exactly one catalogue ID, `cmsa71dyd00px2me0exl6`, for EdTech Foundations and validates the dated form inputs
- Mutation boundary: the post-deployment form was deliberately discarded because the current audit rules prohibit fabricated programme records
- Status: **Production Browser Verified (non-destructive); financial mutation NOT VERIFIED by design**

## LP-2026-08-03-003 — Program Lead dashboard monthly request uses the wrong period and scope

- Severity: High
- Calculation/feature: Program Lead `Monthly Fund Request` KPI and drilldown
- Production URLs: `/dashboard`, `/fund-requests/weekly`, `/accounts/monthly-request/`
- Role: Program Lead
- Expected live result for August FY2026: UGX 40,000, matching the persisted monthly request visible on Weekly and Monthly Team Budget
- Actual live result: UGX 0 on the Program Lead dashboard
- Difference: UGX -40,000
- Independent cross-surface oracle: one persisted Admin cost line at UGX 40,000; Work Plan, Weekly, Monthly, Q4, and FY all independently render UGX 40,000
- Root cause: `_monthly_fund_total` summed `WeeklyFundRequest` rows for the entire FY, omitted the Program Lead's own request, and did not filter a month. The KPI link routed to an unrelated `Funded — Not Completed` activity query.
- Source repair: use persisted monthly `FundRequest` rows for the exact FY/month and complete Program Lead team (PL plus supervised CCEOs); exclude rejected requests
- Frontend repair: add a matching monthly fund-request drilldown with owner, activity count, exact UGX amount, and status
- Tests: `PLDashboardTest.test_monthly_fund_request_uses_exact_month_and_complete_pl_team`
- Before production release: `860f6e828ec3df8d807eeaf7ff2e7b7ae16da766`
- Regression result: cross-team, cross-month, PL-owned, supervised-CCEO, exact total, and rendered-drawer assertions pass
- After production evidence: pending deployment
- Status: **Regression Tested — production deployment pending**

## LP-2026-08-03-004 — Missing target denominators rendered as 0%

- Severity: High
- Calculation/feature: Program Lead targets and CCEO performance
- Production URL: `/dashboard?fy=2026`
- Role: Program Lead
- Expected: absent target/planned denominators display Not measured/Not measurable
- Actual live result: personal cards displayed `0/0` and `0%`; CCEOs with zero planned activities displayed `0 (0%)`
- Difference: missing data was represented as measured failure
- Root cause: service helpers replaced absent denominators with numeric zero and templates always appended `%`
- Source repair: preserve `None` for unmeasurable percentages, track measurable CCEOs separately, and do not classify targetless CCEOs as below target
- Frontend repair: display `0/—`, `Not measurable`, or `—` instead of fabricated percentages
- Tests: `PLDashboardTest.test_missing_target_denominators_are_not_rendered_as_zero_percent`; PL analytics and command-center regression suites
- Before production release: `860f6e828ec3df8d807eeaf7ff2e7b7ae16da766`
- After production evidence: pending deployment
- Status: **Regression Tested — production deployment pending**

## LP-2026-08-03-005 — Fund-request period cards fabricate or leak state

- Severity: High
- Calculation/feature: Weekly Fund Requests KPI strip and insights panel
- Production URL: `/fund-requests/weekly?fy=2026&month=July&week=2026-07-27`
- Role: Program Lead
- Expected live result for July FY2026: UGX 0 requested; no percentage without a prior-month denominator; zero July/week attention items; July 25 shown as overdue on August 3
- Actual live result: UGX 0 paired with a hard-coded `12% vs Last Month`; one August request counted as July attention; July 25 labelled `Upcoming` with `0 days remaining`
- Difference: one fabricated percentage, one cross-period request, and one false due-state label
- Root cause: a literal 12% fallback when the previous month was zero; status KPI querysets and attention querysets were not narrowed to the selected period; negative due-date deltas were clamped to zero while the heading remained Upcoming
- Source repair: exact calendar year/month plus FY scoping for all monetary/status KPIs; exact selected-week scoping for attention; denominator-aware month-over-month calculation with half-up integer rounding and cross-FY comparison; explicit upcoming/due-today/overdue states
- Frontend repair: show `No prior-month baseline` without a trend arrow and render the computed due-state heading/timing label
- Tests: `FundRequestPeriodIntegrityTest` covers zero denominator, exact positive delta, cross-FY negative delta, cross-period status and attention isolation, and all three due states
- Before production release: `860f6e828ec3df8d807eeaf7ff2e7b7ae16da766`
- After production evidence: pending deployment
- Status: **Regression Tested — production deployment pending**

## Evidence boundaries

- Production health/build/readiness: **LIVE PRODUCTION VERIFIED** (`live=ok`, `ready=ok`, `db=up`, release `860f6e82…`).
- Authenticated Program Lead pages and role gate: **LIVE PRODUCTION VERIFIED**.
- Program Lead access to `/system-health`: correctly denied/redirected; admin-only report contents are **NOT VERIFIED**.
- Raw production PostgreSQL queries, container digest, runtime package inventory, scheduler/worker release, production logs, feature flags, and every other role: **NOT VERIFIED** because the available session and hosting CLI do not authorize those surfaces.
- Payments, disbursements, accountability mutations, chaos, load, and concurrency fault injection: **NOT VERIFIED**; these require genuine authorized operational records or an isolated production clone.
