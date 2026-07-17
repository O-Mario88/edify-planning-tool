# Production Remediation Ledger — 2026-07-17

Statuses: Discovered → Reproduced → Root Cause Confirmed → Fix In Progress →
Backend Fixed → Frontend Fixed → Data Repaired → Integration Verified →
Tests Passed → System Health Green → Closed.

Audit references: chain N = docs/ecosystem-audit-2026-07-17.md.

| ID | Audit ref | Sev | Issue | Backend | Frontend | Data repair | Tests | Status |
|----|-----------|-----|-------|---------|----------|-------------|-------|--------|
| L01 | C5 C6a/b | HIGH | Core done-statuses omit `closed`; divergent vocabularies; `<8` gate | canonical `CORE_SLOT_DONE_STATUSES` (+legacy read set), all 4 sites | dashboards read same constant | `repair_ecosystem_data --fix core-counters` recounts plans | test_ecosystem_handoffs::CoreClosedStatusTest + core suites | **Closed** |
| L02 | C1 3.2 | HIGH | FY-blind SSA readiness | FY-filtered recompute + upload stamp; stale done resets | To-Do/badge derive from fixed field | `repair_ecosystem_data --fix ssa-status` | SsaReadinessFyTest (3) | **Closed** |
| L03 | C1 1.3 | HIGH | Duplicate school rows overwrite live schools | import excludes `duplicate` staged rows | duplicate count already surfaced in upload result | none (no way to identify past overwrites — flagged manual review) | SchoolUploadDuplicateTest | **Closed** |
| L04 | C1 4.3 | HIGH | 6 divergent weakest-intervention implementations | canonical `latest_applicable_record`/`weakest_interventions_for`; gate+planning+clusters+analytics consolidated; `ssa_decision` facade + staleness | planning pages unchanged (labels same) | n/a | architectural test (no new raw weakest impls) + suites | **Closed** |
| L05 | C2 F4.2/F4.3 | HIGH | Period FundRequest: self-approval, silent reset | state guards, self-approval block, locks, audit | approval buttons unchanged; errors surface via messages | `--fix` not needed (guard is forward) | PeriodFundRequestGuardTest (4) | **Closed** |
| L06 | C2 F4.5 | HIGH | Cross-channel double disbursement | `MONEY_MOVED_ADVANCE_STATUSES` guards in weekly + period disburse | accountant queue errors visible | `repair_ecosystem_data --scan double-pay` reports affected lines | WeeklyCrossChannelTest + period test | **Closed** |
| L07 | C2 F5.3/F5.1 | HIGH | Reschedule kills confirmed advance; stale vacated week | lock extended to confirmed/submitted; vacated-week regeneration | lock message actionable (amendment CTA — L14) | forward-only | RescheduleFinanceSeamTest | **Closed** |
| L08 | C3 P5a | HIGH | clear-payment bypass (no ledger/audit/NetSuite) | endpoint retired | finance queue is the only pay surface | `--scan partner-paid-without-payment` | endpoint raises; partner suites | **Closed** |
| L09 | C3 P5c | HIGH | Duplicate PartnerPayment possible | idempotency guard + DB unique constraint (migration 0009) | double-click safe | `--scan duplicate-partner-payments` | PartnerDoublePayTest (2) | **Closed** |
| L10 | C6 E7 | MED | Reopen keeps target credit for invalidated work | invalidating categories → `returned_by_ia` | My Plan shows correction To-Do (derived) | `--scan reopened-still-credited` | test_closure reopen tests (2) | **Closed** |
| L11 | C6 E8 | MED | Legacy reimbursement closes without guard | action retired to redirect | message explains canonical path | claims queue empty (verified) | retired-route test via suite | **Closed** |
| L12 | C8 V3/V2 | HIGH | Money movement missing from tamper-evident chain | `_audit` on disburse + submit_reimbursement; closure/NetSuite/partner-paid chain events added this phase | n/a | forward-only | audit assertions in tests | **Closed** |
| L13 | C7 T8 | MED-HIGH | Debrief follow-up undiscoverable | planned+quarter draft, owner notified | My Plan CTA (planned rows already actionable) | `--fix debrief-drafts` re-stamps not_planned drafts | AcceptRecommendationDiscoverabilityTest | **Closed** |
| L14 | C2 F5.4 | MED | Budget Amendment referenced but unimplemented | **BudgetAmendment model + service + apply flow (this phase)** | request/review actions (accountant + owner) | n/a | amendment lifecycle tests | **Closed** |
| L15 | C2 F4.4 | MED | Proportional split rounding drift | largest-remainder allocation (this phase) | n/a | forward-only | rounding exactness test | **Closed** |
| L16 | C2 F3.4 | MED | Rollup "disbursed" = planned line amount | rollup disbursed/accounted from AdvanceRequest amounts (this phase) | dashboards show true figures | n/a | rollup test | **Closed** |
| L17 | C2 F1.3/F6.1 | MED | est_cost_cents fallback in authoritative totals | fallback removed; missing-line = health signal (this phase) | budget pages show missing-cost state (existing cost_missing UI) | `--scan lineless-activities` | fallback test | **Closed** |
| L18 | C3 P3 | MED | partner_schedule raw ORM path | delegates to canonical create() (this phase) | unchanged | forward-only | partner schedule test | **Closed** |
| L19 | C3 P7 | MED | No partner activity allowance | PartnerActivityAllowance model + default 1/school + grant record (this phase) | allowance error surfaces in scheduling drawer | n/a | allowance tests | **Closed** |
| L20 | C6 E1 | MED | Any single file satisfies evidence gate | EvidenceRequirementService by activity type (this phase) | checklist data exposed via completion errors | forward-only | per-type requirement tests | **Closed** |
| L21 | C5 C3 | HIGH | Core 4-weakest never persisted | CorePlan.interventions persisted at onboard w/ SSA anchor + algorithm version | drawer shows recommendation (existing) | `--fix core-recommendations` backfills active plans | onboard persistence test | **Closed** |
| L22 | C4 H1/H2 | HIGH | Project model underspecified; assignment need-blind | target_interventions + measurement window + need gate + override reason (migration 0007) | drawer validation message | `--scan projects-missing-targets` | ProjectNeedGateTest (2) | **Closed** |
| L23 | C7 T3 | MED | Catch-up plans never complete | derived sync_completion on read | recovery list shows completed | `--fix catchup-sync` | sync covered via team suite | **Closed** |
| L24 | C8 V5 | MED | Missing ecosystem health checks | 6 added in audit phase + 3 more this phase (duplicate partner payment, paid-without-payment, prior-FY-satisfying-readiness) | System Health page lists them | n/a | health suite | **Closed** |
| L25 | C8 V1 | HIGH | emit()/DomainEvent seam dead; SSE not workflow-driven | **NOT COMPLETED** — critical events now reach AuditLog (L12); full DomainEvent/SSE unification remains | — | — | — | **Root Cause Confirmed — OPEN** |
| L26 | C5 C12 / C1 2.2 | MED | Cluster membership triple-source | **NOT COMPLETED** — requires migration + read-surface consolidation | — | — | — | **Root Cause Confirmed — OPEN** |
| L27 | C1 6.2 | MED | planning_readiness dual vocabulary test-vs-prod | **NOT COMPLETED** — needs vocabulary unification + data migration | — | — | — | **Root Cause Confirmed — OPEN** |
| L28 | C1 5.2 | MED | Client 1+1 entitlement unenforced | **NOT COMPLETED** — needs product confirmation of the rule before enforcement | — | — | — | **Discovered — OPEN (needs product decision)** |
| L29 | C4 M2 | MED | Project planning/impact scope wider than dashboard | ProjectScopeService consolidation (this phase) | coordinator sees own projects only | n/a | scope test | **Closed** |
| L30 | misc | LOW | UI lint: literal ✓ in 2 WIP templates | replaced with SVG icon (this phase) | identical visual | n/a | ui_quality lint green | **Closed** |
