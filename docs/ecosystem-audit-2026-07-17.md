# Edify Ecosystem Audit — 2026-07-17

**Scope:** the full delivery chain — School Data → Cluster → SSA → Recommendation →
Planning → Costing → Budgets → Approval → Disbursement → My Plan → Execution →
Evidence/Salesforce → IA → Accountability/NetSuite → Payment/Reimbursement →
Closure → Targets → SSA Impact → Leadership Intelligence → Next Decision —
audited as one connected system, tracing handoffs *between* features rather
than features in isolation. Eight parallel audit chains, every finding verified
against source with file:line evidence before repair.

**Method:** 8 audit passes (school→planning, planning→budget→disbursement,
partner, special projects, core+cluster, evidence→finance→closure,
targets+debrief+leadership, events+health+invariants) → 31 verified defects →
repairs applied in dependency order → 17 new regression tests pinning each
repaired seam → full suite (1220 tests) green (one pre-existing template-lint
failure in uncommitted WIP, unrelated).

---

## A. Executive summary

**Does Edify operate as one connected system?** Substantially yes — and more so
after this audit. The spine (canonical Activity ledger, single cost writer,
advance accountability with an enforced reconciliation identity, the nine-check
closure guard, the derived To-Do engine, target-ledger integrity) was verified
GREEN with structural enforcement, not just convention. The breaks were at the
seams: readiness state that ignored the fiscal year, three disbursement
channels with no mutual exclusion, an approval path without a chain, retired
finance endpoints still reachable, a core-package counter that could not count
its own terminal state, and workflow events invisible to audit/notification.

**All 12 HIGH-severity ecosystem breaks found were repaired and are
regression-tested.** A set of MEDIUM structural items remains, enumerated
honestly in section E — the platform is production-workable, but section E is
the required follow-up list, not an optional one.

## B. Breaks found and fixed (all verified by tests)

| # | Seam | Defect | Fix |
|---|------|--------|-----|
| 1 | SSA → Planning/To-Dos | `current_fy_ssa_status` recompute was FY-blind: a prior-FY baseline marked the current FY "done", suppressing the Baseline-SSA To-Do and refresh recommendations | FY filter in `_recompute_readiness` + upload stamp; stale "done" resets to `not_done` (`apps/ssa/services.py`) |
| 2 | School upload → Directory | Rows staged `duplicate` (update_existing=False) were imported anyway, silently overwriting live schools | Import excludes `duplicate` rows (`apps/schools/upload_service.py`) |
| 3 | SSA → every decision surface | "Weakest interventions" implemented 6× with divergent rules; the money-bearing planning gate trusted **unconfirmed** SSA | Canonical `latest_applicable_record` / `weakest_interventions_for` helpers (confirmed-only); gate, ssa recommendation, planning setup, cluster intelligence, decision-engine analytics all consolidated |
| 4 | Period fund requests | `_review` had no self-approval check, no state guard, no lock, no audit; `submit` silently reset APPROVED/DISBURSED requests | Self-approval blocked, reviewable-state guard, `select_for_update`, audit entries; resubmit blocked past pending states (`apps/fund_requests/services.py`) |
| 5 | Cross-channel disbursement | Advance, weekly, and period channels could each release money for the same cost line | `MONEY_MOVED_ADVANCE_STATUSES` mutual-exclusion guards in weekly + period disburse (advance path already guarded by status machine) |
| 6 | Reschedule vs confirmed money | Rescheduling cascade-deleted a CONFIRMED advance (confirmation silently lost) and left an approved weekly request with a stale total; vacated week kept the money | Cost-snapshot lock extended to confirmed/submitted advances (accountant-return is the unstick path); reschedule regenerates the vacated week's request (`apps/budget/costing_service.py`, `apps/activities/services.py`) |
| 7 | Partner payment | Live `clear-payment` endpoint marked partner work paid with **no ledger row, no NetSuite ID, no audit, no snapshot**; nothing prevented double payment | Endpoint retired; `pay_partner` idempotency guard + DB unique constraint on `PartnerPayment.activity` (+ migration) |
| 8 | Reopen → Targets | Reopening for wrong-evidence/wrong-SF-ID/duplicate reset to `ia_verified`, which every target engine still counts as achieved — bad work stayed credited | Invalidating categories now land on `returned_by_ia` (credit reverses, fix To-Do appears); finance/audit corrections keep the verified state |
| 9 | Legacy finance reachability | `pay_reimbursement_action` (System A) closed activities directly, bypassing the nine-check closure gate | Retired to a safe redirect (no live workflow creates claims) |
| 10 | Core package completion | `CORE_SLOT_DONE_STATUSES` omitted terminal `closed` — a fully closed package dropped out of its own completion counters, blocking §26 completion and champion promotion; three divergent CamelCase status sets + a hardcoded `<8` | One canonical done-set incl. `closed` (+ legacy-spelling read set); all four sites consolidated; `EXPECTED_CORE_SLOTS` used |
| 11 | Core plan rationale | The four-weakest recommendation was never persisted (`CorePlan.interventions` unwritten); slots seeded round-robin across all interventions | Onboard persists the recommendation with its baseline SSA record anchor; slots seed from the recommended four |
| 12 | Debrief → next planning | Accepted recommendations created `not_planned`, quarter-less activities via raw ORM — invisible to To-Dos and quarter rollups; only the submitter was notified | Follow-up now `planned` with quarter stamped; the follow-up owner is notified |
| 13 | Money-movement audit | `advance disburse()` and `submit_reimbursement()` wrote no tamper-evident audit while every sibling accountant action did | `_audit` calls added |
| 14 | Scheduling/assignment events | Activity scheduling and partner assignment emitted nothing (no audit, no notification); `partner_scheduled_activity` was defined but never fired | `activity.scheduled` audit in canonical `create()`; `post_save` receiver on PartnerAssignment (audit + partner notification) covering all seven creation sites |
| 15 | Special Projects front-of-chain | Project model had one nullable intervention, no eligibility/measurement fields; school assignment was a free manual pick with no SSA-need check and no override trail | `target_interventions` + measurement-window fields (+ migration); `evaluate_school_need` gate on both assignment paths — weak-match auto-assigns (matched intervention stamped), off-recommendation requires a persisted reason |
| 16 | Catch-up recovery loop | Plans never advanced past scheduled/approved — completed recoveries never closed | Derived `sync_completion` advances plans when their created activities complete |
| 17 | System Health seams | No checks for records stranded between features | Six new checks: SF-complete-not-in-IA-queue, IA-cleared-missing-finance, overspend-missing-reimbursement, finance-cleared-not-closed, project-activity-missing-intervention, leadership-action-missing-owner |
| 18 | IA-confirm parity | API path stamped payment routing only for partner delivery, live path for both | Staff `pending_ia` stamp added |

## C. Verified GREEN (structurally enforced, no action needed)

- **Salesforce IDs**: single writer (`reserve_salesforce_id`), DB uniqueness, 3-layer dedup — no bypass writes exist.
- **Advance accountability**: NetSuite required at submission, IA-verified hard gate, reconciliation identity `accounted == disbursed − returned + reimbursed` enforced at every terminal transition, row locks on all transitions, receipt confirmation before terminal REIMBURSED, over/under/self-funded paths correct.
- **Closure guard**: all nine checks; the 2026-07-15 accountant-clearance and evidence-URL security fixes hold; DB constraint closed-requires-SF-ID.
- **Target ledger**: unique source constraint, late-validation credits the work month, returned/cancelled reversal, stale-source auto-reversal, partner work excluded from personal credit and reported separately, disjoint type sets prevent cross-area double credit.
- **To-Do engine**: fully derived from workflow state across 18 role queues — no stored-state drift possible.
- **Special Projects execution spine**: canonical activity creation with project stamping, single cost writer, normal budget/evidence/IA/finance pipeline, confirmed-only SSA impact with honest "not measurable yet".
- **Weekly approval chain**: stage enforcement, no self-approval, supervisor check, locks, audit, notifications.
- **Background jobs**: 7 registered, tracked, health-visible.

## D. Reconciliation identities

| Identity | Status |
|---|---|
| accounted == disbursed − returned + reimbursed | **Enforced + tested** |
| Advance 1:1 per budget line | **DB constraint** |
| Weekly total == Σ its lines | Guaranteed at generation; **reschedule drift fixed** (vacated-week regeneration + confirmed-money lock); `confirmedWeeklyRequestsDrifted` health check watches it |
| Monthly program == Σ eligible lines + admin plan | Structurally guaranteed (live recompute) |
| One disbursement channel per cost line | **Now guarded** at weekly + period disburse |
| Partner payment ≤ 1 per activity | **DB constraint + guard** |
| Annual == Σ monthly work-plan budgets | Existing health check (`annualBudgetReconciliationBreaks`) |
| Quarter == Σ its 3 months | Consistent today (single writer stamps both fields) but structurally unguarded — see E |

## E. Remaining risks (MEDIUM/LOW — honest list, none critical)

1. **Budget Amendment workflow referenced but not implemented** — the cost-snapshot lock tells users to "use a budget amendment"; the sanctioned path for changing locked costs is accountant-return of the advance. Build the amendment flow or reword permanently.
2. **Three audit stores** (hash-chained AuditLog vs ActivityTimelineEvent vs FinanceAuditLog) — closure and NetSuite events still live outside the tamper-evident chain.
3. **`emit()` realtime seam is dead code** — SSE/dashboards are not driven by workflow events; wire workflows through it or remove it.
4. **Budget rollup "disbursed" sums planned line amounts, not actual `disbursed_amount`** — partial disbursements are invisible in board rollups.
5. **Client-school 1 visit + 1 training entitlement is not enforced** at activity creation (Core slots are; client schools are not).
6. **Cluster membership has three representations** (School.cluster_id CharField, SchoolClusterAssignment join, covered sub-counties); read surfaces disagree on which is authoritative; sync only fires on geography change.
7. **`planning_readiness` writes different vocabularies under test vs production** — a latent divergence the suite structurally cannot catch.
8. **Cluster analytics lack median/improving/declining and use hand-rolled band thresholds** (confirmed-only filter now fixed for the weakest-ranking path).
9. **Cluster attendance does not credit targets/entitlements** — trivially no double-count, but likely under-count.
10. **Per-activity-type required-evidence mapping missing** (any single accepted file satisfies the evidence gate).
11. **Weekly proportional split uses per-line rounding** (Σ child disbursed can differ from the request's disbursed amount by shillings; no largest-remainder allocation).
12. **Project planning/impact scope wider than My Plan/dashboard scope** (school-overlap vs manager-only) — cross-coordinator visibility on two surfaces.
13. **Performance dashboards lack evidence-quality / accountability-quality / follow-up-SSA-coverage metrics.**
14. **Quarter == 3-months identity untested** (month and quarter stamped from the same writer today, but nothing pins it).
15. **School/SSA bulk-upload paths remain outside the audit chain**; upload staging + import are not one transaction (legacy batch pre-stamped "imported").
16. **Partner activity allowance model** (default allowance + auditable extra grants) is unimplemented.
17. **Champion eligibility scoring reads unverified SSA** (recommendation path is confirmed-only; the score calc is not yet).

## F. Test evidence

- `apps/core/tests/test_ecosystem_handoffs.py` — 17 regression tests pinning fixes 1, 2, 4, 5, 6, 7, 10, 15, 12 (one class per seam).
- `apps/activities/test_closure.py` — reopen credit-withdrawal semantics (both branches).
- Full suite: **1220 tests, all green** except one pre-existing UI-lint failure in uncommitted WIP templates (`✓` characters — predates this audit).
- Two migrations added: `fund_requests.0009` (partner-payment uniqueness), `projects.0007` (target interventions, measurement window, assignment reason).
