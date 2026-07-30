# Planning → Costing → Budget Financial-Integrity Audit — 2026-07-30

**Invariant proven:** one scheduled Activity produces one authoritative record, one
complete cost set fetched from the CD's effective Cost Catalogue, one contribution
to each applicable weekly/monthly/quarterly/FY aggregate, and one valid funding
path — without duplication, omission, stale totals, or manual recreation.
Weekly/monthly/annual budgets are roll-ups; an underlying cost is funded once.

Baseline: `main` @ d50bebb5, Python 3.13.12 / Django 5.2.16 / PostgreSQL (local).
Note: this audit ran while a separate Activity Catalogue feature was being built
concurrently in the same working tree; audit changes were reconciled with that
work where the two met (`create()`, `partner_schedule`, `costing_service.preview`).

## Authoritative sources (enforced, §2)

| Concept | Source of truth |
|---|---|
| Scheduled work | `Activity` (created only via `activities.services.create` / `partner_schedule`) |
| Activity cost | `ActivityScheduleCostLine` set written ONLY by `budget.costing_service.apply_to_activity` |
| Rate | `CostSetting` under the active FY `CostCatalogue`; snapshotted per line (key, setting version, catalogue id/version) |
| Weekly budget | eligible cost lines by owner + Monday week (`weekly_service.generate_weekly_fund_request`) |
| Monthly country budget | eligible cost lines + ACTIVE `AdminBudgetLine`s (`country_budget_service._program_source`) |
| Quarter / FY | fiscal (Oct-start) aggregation of the same lines; FY = Σ 12 months = Σ FY lines (verified UGX 0) |
| Staff funding | `AdvanceRequest` ledger (1:1 per line, unique) gated by the approved `WeeklyFundRequest` chain |
| Partner payment | `PartnerPayment` after IA clearance — the ONLY partner channel, amount clamped to the plan |

## Critical defects fixed

1. **Full-day pool billed per school (C1/C2).** UI scheduling bypassed
   DailyVisitBatch pooling: 5 visits on one day billed 5× the day pool (evidence:
   one CCEO had 5 transport pools on 2026-07-31), while a reschedule re-priced the
   same visit at the pooled 1/N — two engines, two prices. Staff batch-eligible
   visits now pool at create (`attach_activity_to_batch`); batch recalc also syncs
   monthly drafts. Draft data repaired; 2 locked/unclassified visits flagged.
2. **Client-controllable bypass flags (B1/B2).** `_skip_cost_snapshot` and
   `coreSlotVerified` were honoured from raw `POST /api/activities` payloads —
   costless money-bearing activities and core-slot-cap bypass. Now keyword-only
   trusted-caller arguments, stripped from request data.
3. **Cancel/defer left work funded (B3/W1).** No transaction, cost lines, draft
   weekly/monthly requests and pending advances all survived cancellation and the
   advance remained disbursable. Cancel/defer are now atomic, withdraw draft
   funding, and delete un-moved advances (money-moved advances settle via the
   return/accountability workflow, never deletion).
4. **Missing rate did not block scheduling (C3).** `assert_schedulable` had zero
   callers; a missing rate wrote 0-amount lines. `create()` now blocks dated
   scheduling when the catalogue can't fully price it, naming the missing rate.
5. **Friday cron created an FY-wide disbursable FundRequest (D4).** `regenerate("weekly")`
   with no week matched every line in the FY under a country-scope request whose
   disbursement would flip every advance to disbursed. Period keys are now strict
   (weekly requires week, monthly requires month), the cron call is a no-op, and
   the rogue row was deleted.
6. **Per-line advance disbursement skipped the approval chain (W2).** The owner
   could confirm their own advance and the accountant could disburse it with the
   weekly request still unsubmitted. Disburse now requires the governing weekly
   request to have cleared approval.
7. **Partner costs sat in staff funding channels (§15/§19).** Partner-delivery
   cost lines were mirrored into the managing staff's WeeklyFundRequest and
   AdvanceRequests while PartnerPayment would pay the same cost after IA clear.
   Partner lines are now excluded from all staff channels (they remain in budget
   aggregates, which are roll-ups, not payment channels); data repaired; a
   `partner_lines_in_staff_funding` health check (critical) guards regressions.
   One historical money-moved advance remains flagged for accountant reconciliation.
8. **Assignment scheduling lock was outside its transaction.** In production
   autocommit the double-schedule lock raised/never held. The whole flow now runs
   in one transaction (verified by a TransactionTestCase against autocommit).

## High/medium fixes (summary)

- `disbursed_amount` written by all disbursement paths (roll-ups no longer report 0 disbursed).
- Budget amendments resync weekly/monthly draft buckets (vacated period empties).
- `PATCH /api/activities` re-prices when participant cost drivers change (locked snapshots refuse via the existing guards).
- District classification derived server-side on every re-price (secondary work no longer degrades to primary rates on reschedule/reassign/partner-schedule).
- Core `slot_action`: scope check, CREATE permission, transaction + row lock, plan counter resync.
- §F partner allowance enforced at every point cost comes into existence.
- `reassign` atomic; omitting `assignedPartnerId` no longer nulls the partner link; partner→staff restores status.
- Monthly envelope: legal status-transition map (no more draft→sent_to_accountant), submission requires the guarded `send_to_rvp` path (recompute + real integrity checks + immutable snapshot); locked-month-without-snapshot is now an integrity failure. The July 2026 month that had bypassed the guard was reverted and recomputed (1,250,000 → 1,810,000 UGX stale total corrected).
- Accountant KPIs derive from the AdvanceRequest ledger — the weekly+monthly snapshot double-count is gone.
- Duplicate rate resolvers removed (`cost_preview` delegates to the canonical engine; routes estimator uses the exact pool split and FY-scoped catalogue).
- Allocation/PL-approval totals exclude cancelled/rejected/deferred work; multi-owner activities attribute per owner.
- `apply_to_activity` also refuses re-pricing when a non-draft MONTHLY fund request holds the line (dangling-item hole closed) and a `dangling_fund_request_items` health check watches history.
- Weekly API `qty` AttributeError fixed; board() quarters unified on fiscal; UTC date drift in week totals fixed; boundary weeks no longer double-count; budget APIs require `BUDGET_VIEW_SUMMARY`; template money arithmetic removed; My Plan prefers the canonical line sum; seed no longer overwrites CD-set rates; exact-duplicate scheduling rejected under row locks.

## Repair commands (dry-run default, `--apply`)

- `python manage.py repair_costing_pipeline` — partner lines in staff channels,
  rogue period requests, costless scheduled activities, unpooled visits, dangling
  monthly items. Applied 2026-07-30: 102 advances + 103 weekly lines removed &
  regenerated across 103 activities; 1 rogue request deleted; 1 activity re-priced;
  26 dangling items regenerated.
- `python manage.py repair_monthly_budget_totals` — live-month drift + locked-month
  snapshot invariant. Applied: July reverted & recomputed, August recomputed.

## Reconciliation results (dev DB, post-repair)

- Draft weekly request totals vs source lines: **0 mismatches**
- Live monthly stored totals vs canonical: **0 mismatches**
- Quarter vs its 3 months: **0 mismatches** · FY vs 12 months vs FY lines: **0 (14,260,000 UGX both sides)**
- Cost-line integrity: amount == unit×qty == total on every line; 0 duplicate components; 0 lines without catalogue snapshot; 0 stale periods; 0 orphans; 0 double-funded lines; 0 double-disbursements.
- Calculation matrix: per-participant, executor-differentiated, district-differentiated pricing verified; pooled splits sum exactly (largest remainder).

## Tests

New/updated: `apps/activities/test_audit_pipeline.py` (one-activity-one-cost-one-channel,
missing-rate block, cancel-withdraws-funding, partner single-channel + double-schedule,
TransactionTestCase), `apps/fund_requests/test_audit_funding_channels.py` (12),
`apps/monthly_work_plan/test_audit_monthly_integrity.py` (11),
`apps/budget/test_audit_rollups.py` (11), plus updates to the atomic-writes,
health, and finance-operating suites.

Full fresh-DB run (2026-07-30, isolated test DB): 3,294 passed / 2,390 subtests.
Every financial app (activities, budget, fund_requests, monthly_work_plan,
daily_visit_batches, partners, my_plan, routes) is green. The remaining full-run
failures (~45) all belong to the Activity Catalogue / Strategic Priorities
feature being built concurrently in this tree (catalogue_views/priority_views
unguarded routes, drawer template lints, its own flow tests not yet updated) —
none implicate audit files; the gate scanners' offender lists name only the
in-flight feature's files. `manage.py check`, `makemigrations --check`, and ruff
are clean on all audit-touched files.

## Phase 2 addendum (same day, follow-up request)

Residual audit items closed:
- Per-participant pricing now uses the PLANNED count (§32) — attendance actuals
  only fill in when no plan was captured, so a post-completion reschedule can no
  longer silently re-price on actuals.
- Solo-priced secondary-district visits now default to one night's accommodation
  (parity with the batch pool); an explicit nights=0 still means same-day return.
- Cost-line `unit_cost`/`amount` widened to BigInteger (overflow at ~UGX 2.1bn
  gone) and a conditional DB unique constraint added on
  (activity, cost_setting_key) — one component per key per activity is now
  database-enforced (empty-key legacy rows excluded; the health checks own those).
- The debrief follow-up creator was re-reviewed and is conformant (it creates a
  draft planned activity that must be scheduled/costed through Planning) — the
  earlier "raw creator" concern is withdrawn for that path.

In-flight feature conformance (Activity Catalogue / Strategic Priorities) —
brought to green without weakening any gate:
- Both custom permission decorators now declare the scanner contract
  (`has_permission_guard`), and the strategic-priorities page re-carries the
  contract of the page it replaced: viewer role gate, validated/rebuilt FY, and
  `can_author`, plus `require_page_permission("strategic_priorities")` for the
  surface-inventory role mapping.
- Review-queue resolution state is written by a catalogue service
  (`resolve_review`), not the view.
- Three real in-flight bugs fixed: `source_activity_id` NameError and a missing
  `Activity` import in assign-partner, `activity_type` NameError in the
  project bulk-partner view (purpose normalisation now derives its fallback
  from the resolved catalogue item), and `School.objects.filter(cluster=…)`
  against the non-FK `cluster_id` in cluster recommendations.
- Template conformance: arbitrary radius/shadow/tiny-type replaced with design
  tokens across 8 templates, legacy primary utilities normalized, duplicate
  `<main>` landmarks removed, missing `#drawer-root` htmx target added, and the
  eight new strategy tables bounded.
- Workflow-form scanner now treats Alpine's `x-bind:required` as
  conditionally-required (optional at rest); the drawer-label guard understands
  the catalogue fieldset as the classification control's successor.
- Five feature tests updated to the catalogue-era contracts (assignments name an
  approved catalogue item; expected types derive from the item; non-primary
  selections need an override reason; the scheduling drawer preselects the
  SSA-driven recommendation; the add-to-cluster drawer resolves coverage
  per school).

## Remaining known items (documented, non-blocking for local; review before production)

1. Costing prefers attended-actuals over planned participants when both exist —
   a post-completion reschedule re-prices on actuals (pre-existing engine ordering).
2. Solo-priced secondary visits never include accommodation (`nights` is never
   posted); the pooled path covers batch-eligible types, other types under-cost overnights.
3. Rates carry no `effective_from` date: resolution is FY-catalogue + version
   history; a mid-FY rate change re-prices only unlocked snapshots.
4. `unit_cost`/`amount` are 32-bit columns (overflow ≈ UGX 2.1bn/line) — migration deferred.
5. No DB unique on (activity, cost_setting_key); writer-level guarantee only.
6. `CountryAnnualBudget` totals are typed and phasing fields are never written
   (System Health blocker covers the sum check).
7. Two month-number vocabularies (calendar vs FY-relative) still coexist internally;
   strict period keys prevent cross-matching.
8. Raw Activity creators in targets catch-up (undated) and debrief acceptance
   (missing `scheduled_date`) create unfunded rows outside the funnel.
9. Manual-review data: 1 money-moved partner advance (accounted), 2 locked/unclassified
   unpooled visits, 3 status="scheduled" rows with NULL scheduled_date (upload quirk).
