# Functional Product Readiness Audit — 2026-05-30

Read-only audit mapping the codebase against the merged "Functional Product Readiness System" spec
(SSA → Planning → Scheduling → Budget → My Plan → Start Activity → Evidence → Review → Approval →
Payment → Analytics → Donor Reporting → Leadership Decision). Produced by a 10-agent mapping workflow.

## Overall readiness: **Workflow Connected (~55–60%)**

Most workflows have live state machines and UI, but the **cross-stage handlers** (Planning→My Plan,
reviewer→transition, start-activity) are stubbed, and one role (Accountant) 404s on landing — so no
role can be run end-to-end yet. Strong skeleton + muscle; the *nerves* (wires carrying an action from
one stage to the next) are cut in a few load-bearing places.

### Strongest dimensions (architecturally "one system")
- **Navigation** — single role-aware AppShell, 9 per-role menu builders, 34/35 routes live.
- **Messaging V2** — email-as-identity, multi-context, context-required sends, context-inheriting
  replies, floating drawers — all live. (Gap: persistence is mock; not yet DB-backed.)
- **Budget/cost engine** — district-classified, plan-derived, per-school transport / per-day meals /
  per-night accommodation, FY/quarter logic — locked by tests.
- **Workflow state machines** — partner CCEO→PL→**IA**→Accountant payment chain, scheduled-plan
  status machine, reschedule routing — all correct server-side.

## Success-criteria scorecard (spec §19)
| # | Criterion | Status |
|---|---|---|
| 1 | Planning Tool is source of all activities | partial |
| 2 | SSA locks/unlocks planning | partial |
| 3 | planned items move to My Plan / Partner Planning | **missing** |
| 4 | scheduling rules (exact date vs month+week) | partial |
| 5 | reschedule reasons required & routed | partial |
| 6 | start-activity & evidence | partial |
| 7 | partner confirm/return/reject | partial |
| 8 | PL approval & accountant payment | partial |
| 9 | weekly/monthly/quarterly/yearly budgets from plans | partial |
| 10 | Monthly Fund Request PL→CD→RVP | partial |
| 11 | messages require context | **met** |
| 12 | replies inherit context | **met** |
| 13 | notifications & messages floating drawers | **met** |
| 14 | analytics & donor reporting use verified data | **missing** |
| 15 | every meaningful tile drills into real records | **missing** |
| 16 | all filters role-aware | partial |
| 17 | all missing pages exist | partial |
| 18 | no fake buttons / href="#" | partial |
| 19 | unified nav + role switching + audit + system-health | partial |

## Top blockers
1. **Planning gap-card type mismatch** — `PlanningGapCard.tsx:209-214` reads
   `gap.primaryActionKind / secondaryActionKinds / ssaCompleted / weakestArea.area`, none of which
   exist on `PlanningGap` (real field is `gap.recommendation.primaryAction`, see `gap-types.ts:115,182`).
   Breaks action-button rendering — blocks step 1→3 of the whole chain.
2. **`/dashboards/accountant` does not exist** but `ROLE_REDIRECT` (`auth-public.ts:32`) points there —
   the Accountant role 404s on login; payment-endpoint QA impossible.
3. **Cross-stage handlers are stubs/toasts, not transitions** — `PlanningGapBoard.handleAction`
   console.logs (line 111); `StaffPartnerMonitoring.handleAction` toasts only (line 75);
   `PartnerReviewActions` orphaned (no caller); `startActivityAction` console.logs
   (`partner/schedule/actions.ts:62-70`). State machines are correct but nothing advances state in the UI.
4. **Analytics/donor reporting is 100% hardcoded mock** — no pipeline to workflow records, no FilterBar
   rendered, no InteractiveTile wiring. Criteria 14 & 15 essentially unbuilt at the data layer.

## Quick wins (cheap, high-value)
- Create `src/app/(shell)/dashboards/accountant/page.tsx` (mirror an existing dashboard) → stops the
  ProgramAccountant 404. One file gates a whole role's QA.
- Fix `PlanningGapCard` field reads → map `gap.recommendation.primaryAction.action`, `.secondary`,
  derive ssaComplete from `gap.ssaGate`, guard `gap.weakestArea`. Pure refactor; unblocks criterion 3.
- Replace 3 `href="#"` dead links (`OperatingTargetsView.tsx:519`, `CdFundApprovalQueue.tsx:202`,
  `RvpCountryBudgetCard.tsx:184`).
- Wire or disable+title the ~10 onClick-less Export/Filter buttons (`CceoAnalytics.tsx:274-277`,
  `OperatingTargetsView.tsx:548`, `MyActivitiesTable.tsx:125-127`, `CountryAnalytics.tsx:304`,
  `ReplicaFilterBar.tsx:128,148`).
- Convert `/reports` & `/settings` stub buttons/toggles to handlers or explicit disabled "coming soon".

## Roadmap (spec implementation order §15)
1. **Close route + dead-UI gaps** [M] — accountant page; scaffold `/system-health` + `/action-audit`
   (spec #16); replace href="#"; shared RouteRegistry; shell-level role gating.
2. **Central Action Registry + audit** [L] — one `ACTION_REGISTRY` (label/type/permission/handler);
   CI test asserting every state-changing action calls `emitAudit`; transactional audit writes.
3. **Make Planning move items** [L] — fix gap-card reads; implement `handleAction` routing
   (self→My Plan, CCEO→CCEO My Plan, partner→/partner/planning); gap-disappearance; page-level SSA gate.
4. **Wire partner evidence→payment transitions** [L] — real `onAction` firing partner-workflow
   transitions; integrate orphaned `PartnerReviewActions`; real start-activity persistence;
   surface IA-verified gate in disbursement/PL queues + Clear Payment handler.
5. **Budget/MFR enforcement + reschedule effects** [L] — server-side RVP-visibility gate; CD admin-item
   CRUD; event-driven reschedule→budget recalc + MFR regen; quarterly/yearly aggregation.
6. **Notifications/messages on workflow actions + persistence** [M] — DB-back send/reply; reply
   recipient auto-fill; render suggestedReceivers; ensure transitions emit context-bound messages.
7. **Analytics/donor reporting → verified data + tiles/filters** [XL] — replace hardcoded metrics with
   calculations over workflow records (dedupe reach by identity); InteractiveTile drill-downs;
   FilterBar + `?tileFilter=`; export respects filter.
8. **Role-based QA pass** [M] — walk all 9 roles through the full chain; verify audit/notifications/
   filters/drill-downs; confirm no dead UI / 404s remain.

> Note: app runs on mock data (year-1 manual upload → year-2 Salesforce). "Partial/mock-only" wiring is
> expected — readiness is judged on whether workflow LOGIC and connectivity exist, not whether a real DB
> is attached.
