# 30. The third save in Go: cancelling a school visit (mapped; a decision needed)

M5 (04): "schedule, reschedule, cancel … Each write appends the same audit
and timeline rows as today." The owner's rule (2026-10-08, "Cancel undoes
scheduling"): cancelled work stops counting everywhere and its day's costs
follow. This piece follows 29's decisions: the pricing's refusals asked of a
read-only Django check before Go's transaction, the costs to follow written
by Go and settled by Django after commit, an acting seat handed on, and the
writer role changing `activity.status` and `daily_visit_batch_id` and no
other lifecycle column (29.4, 03 §3.7).

**Where it stops.** The map (30.3), the measured writes (30.2), the
scenario and the contract (30.5) are built. The writer role, the Go save,
the shadow proof and the switch are **not** built: the cancel deletes the
visit's un-disbursed advance inside its own transaction, which the writer
role cannot do without a new kind of right (30.4). That is the owner's
decision.

## 30.1 Scope

- **In:** one scheduled staff school visit of the first save's kind (a
  `purpose_type` among the six, its activity type the purpose's, a school, no
  cluster, project, partner, pair or end date, never begun), still
  `scheduled` or `rescheduled`, pooled into a draft day, called off by its own
  owner, at a school in their own portfolio that is not a Core school, from
  My Plan's Cancel drawer (`/my-plan/{id}/cancel-drawer` posting to
  `/my-plan/{id}/cancel`; the app reaches the same drawer through
  `PageDrawerService.SaveDrawer`, as the Reschedule drawer, 29.7).
- **Handed on, unchanged:** an In-school Training pair and group cancel
  (`pairs.cancel`, `group_actions.py`); Core package visits (their V/T slots
  reset by the model's save); partner work (`undo_assignment_scheduling`,
  the partner's notice); cluster work; another person's activity (the view's
  doors and their audit rows); a person in an acting seat; work whose money
  has moved (a submitted or approved week carrying the visit, which is told
  after commit, `_notify_frozen_weekly_request`; a day whose week has left
  draft, which `remove_school` refuses and the cancel leaves frozen; a
  disbursed advance; a milestone credit to reverse, `reverse_activity_progress`
  on commit); anything that writes a notice after commit (an open overdue
  reminder, an open day-off notice, as 29.1); a visit already cancelled
  (the existing save cancels it again; Go takes only a plan).

## 30.2 What one cancel writes (measured, 2026-11-12)

`cmd/shadow/scenarios/cancel_visit.json` (19 steps: six visits scheduled, two
moved, then eleven cancels and their doors) through the existing application
(`django_runner.py`) on copy A, and its first eight steps on copy B; then
`go run ./cmd/shadow` A against B (`agent13_measure.txt`), and the cancels
played once more with the settling thread held (`_when_the_save_commits`
stubbed, `agent13_keep_runner.py`) to read the rows before the pricing.

Each cancel of 30.1's case writes, in the save:

| Table | Row | Written by |
|---|---|---|
| `activity` | UPDATE of `status ('cancelled'), last_reason, updated_at`; then `daily_visit_batch_id = NULL, updated_at` | `_cancel_or_defer` 6624–6626; `remove_school` (`daily_visit_batches/services.py:710`) |
| `activity_schedule_change` | `kind 'cancelled'`, `from_day = to_day` = the visit's day, `from_status` (`scheduled` or `rescheduled`), `to_status 'cancelled'`, `reason ''` | `schedule_trail._record_schedule_change` (post_save) |
| **`advance_request`** | **DELETE** of the visit's advances whose money has not moved (every priced visit on the seed has one, `pending_responsible_confirmation`) | `_cancel_or_defer` 6656–6658 |
| `daily_visit_costs_to_follow` | `steps = {days: [[the day left, owner]], together: false, weeks: [[owner, week]], months: [[owner, fy, month]], notes: [], change: null}`, `owners`, `asked_by`, role, provenance | `costs_follow._hand_over` (the day kept by `remove_school`, the week and month by `sync_weekly/monthly_*_for_activity` from the prior buckets) |
| `target_ledger_dirty` | (owner, FY of the day) on commit | `ledger_sync._changed` |
| `audit_log`, `domain_event_log` | `cancel_activity`, `success true`, `reason "Activity cancelled"`, payload `{"reason"}`, the actor's role, ip, agent, correlation | the view (`my_plan_views.py:2839–2855`), `audit.services.log` |

A refusal writes one row: `cancel_activity`, `success false`, `reason` the
refusal's words, no payload (`my_plan_views.py:2827–2837`). Then the pricing
that follows (Django's, settled after the answer): the day left re-priced
(its other visits' snapshots and lines, the empty day's route batch and
checks, transport rows), the week's and month's requests filed again
(`fund_request_item`, `weekly_fund_request_line` rows removed with the
visit's amount). The settled costs row is removed by the settling.

Measured run, last lines (copy A): `19 steps on edify_shadow_a: 17 answered
ok, 2 refused` (the blank reason; the other officer's drawer, 403 "Access
Denied."). The comparison with the eight-step copy:
`366 tables, 23 changed by the runs`, among them `advance_request` (8 rows
removed on A), `activity_schedule_change` (9 more), `audit_log` and
`domain_event_log` (15 more), and for the handed-on steps `core_activity_slot`,
`partner_assignment`, and the refused drawer's `admin_system_incident`,
`notification` and `document_acknowledgement`.

## 30.3 The path, line by line (this branch, d65401aa1)

**The drawer and the view** (`apps/frontend/views/my_plan_views.py`):

| Step | Lines | What it does for this case | Go |
|---|---|---|---|
| Page gate | 2799 | `require_page_permission("my_plan")` | the drawer's form request is Django's (as 29.7) |
| Team member | 2801, 2787 | a partner's team member: 403 "Only your organisation's Partner Admin cancels its work." | a partner → hand on |
| Record | 2804 | `get_object_or_404(Activity, deleted_at__isnull=True)` | none → hand on |
| Record gate | 2805–2817 | `can_view_record`; refused: `unauthorized_mutation_attempt` row and 403 "Access Denied: You do not have permission to cancel this activity." | own activity only; anything else handed on |
| Reason | 2820 | `reason` stripped | same |
| Pair | 2825 | `pairs.joins(a, CANCEL)`; none for 30.1's case (`pairs.cancel` 117 → `services.cancel`) | a pair → hand on |
| Refusal | 2826–2837 | any exception: the `cancel_activity` failure row, then `error_fragment(exc, action="Cancellation Error", 400)` ("Cancellation Error: {words}") | the same row on the chain, the same words |
| Audit | 2839–2855 | `cancel_activity` success row, payload `{"reason"}` (no `cancelled_with` without a pair) | the same row after commit |
| Answer | 2857–2858 | `saved_in_place()`: "Saved. Press Refresh to see it on the page." | the same (`rules.json` `move.savedMessage`) |

**The cancel** (`apps/activities/services.py`, `cancel` 6706 →
`_cancel_or_defer` 6527–6703):

| Step | Lines | Reads / refuses | Go |
|---|---|---|---|
| Scope | 6572–6574 | `_get_for_execution` → `_get_in_scope` ("Activity not found."), `_assert_may_execute` (own work passes; the Director's `TEAM_READ_ONLY_MESSAGE`) | own work at own school; else hand on |
| Reason | 6595–6596 | blank → "Give a reason this activity is being cancelled." (before any lock) | same words, and the view's failure row |
| Blocks | 6600 | `transaction.atomic()`, `costs_follow(principal)` | one read-write transaction |
| Lock | 6601 | `Activity … select_for_update()` | `SELECT … FOR UPDATE` (the UPDATE grant allows it); changed since read → hand on |
| Partner | 6604–6606 | `partner_has_dated` for partner work | partner → hand on |
| Buckets | 6607–6611 | the cost lines' owner, FY, month, week | the costs row's weeks and months (29's `lineBuckets`) |
| Frozen weeks | 6618–6623 | submitted/approved weekly requests holding the visit's lines; each told after commit (6666) | any → hand on |
| Row | 6624–6626 | `status`, `last_reason`, `updated_at` | one UPDATE (columns already granted, 29.5) |
| Trail | `schedule_trail.py:63` | `cancelled` row (30.2) | the same INSERT (granted) |
| Partner undo | 6627–6644 | partner work only | — |
| Credits | 6652–6654 | `reverse_activity_progress` on commit: a no-op with no live `milestone_progress_credit` | any live credit → hand on |
| Day | 6655 → `_detach_from_daily_visit_batch` 6468 → `remove_school` 693 | `_is_locked` (week left draft): refused and swallowed, the visit kept on the frozen day; else `daily_visit_batch = NULL`, the day kept for pricing (`_price_when_the_save_ends`) | the day's lock asked of the relay (a frozen day → hand on); the UPDATE of the batch column (granted) |
| **Advances** | 6656–6658 | `AdvanceRequest … exclude(MONEY_MOVED_ADVANCE_STATUSES).delete()` | **needs DELETE on `advance_request` (30.4)** |
| Week, month | 6659–6660 | kept by `fund_requests_kept` into the costs row | the row |
| Pair training | 6664–6665 | `school_visit` type only: none of the six purposes' types | — |
| Hand-over | `costs_follow.py` 219–275 | `_assert_days_can_follow` on the day left (`_plan_day`, paid transport, the finance guards), then the row, then the settling thread | refusals asked of the relay before the transaction; the row; settled by Django after commit (27.9's door) |
| Ledger | `ledger_sync.py:232` | (owner, FY) on commit | the same upsert after commit |
| Partner tell | 6670–6696 | partner work only | — |
| Notices | 6697–6698 | `_resolve_overdue_reminder`, `_settle_day_off_notices` on commit | an open notice of either kind → hand on (29's `moveNotices`) |

The read-only Django check this needs is a third door beside 29's
(`POST /api/auth/internal/visit-cancel-check`): the cancel played on the
visit inside a transaction it rolls back, answering the day's lock, the
frozen weeks, `_assert_days_can_follow`'s refusal and its words. That is
27.8 §1's decided pattern; it is not built here, because the save it serves
is not.

## 30.4 Decided: the cancelled visit's advance (owner, 2026-11-12: "Narrow function")

The owner chose the narrow function (option 1 below): `gateway_money.withdraw_unmoved_advances(activity_id)`, a `SECURITY DEFINER` function owned by a NOLOGIN role holding `DELETE` on `advance_request` and nothing else, deleting only that activity's advances whose money has not moved, by the existing save's own filter, inside the cancel's transaction. The gateway gets `EXECUTE` only and still holds no `DELETE` anywhere. A new database object: production needs the owner's approval at cutover.


The owner's rule says cancelled work's money is withdrawn, and the drawer
promises it ("Its cost and any undisbursed advance are withdrawn."). The
existing save does it inside the cancel's own transaction: it **deletes**
the visit's `advance_request` rows whose money has not moved. Every priced
visit has one (the seed's 283 advances are all
`pending_responsible_confirmation`), so every cancel of 30.1's case deletes
a row of a money table.

The writer role has no `DELETE` on anything (27.4: "No `DELETE`"), the guard
refuses a role that can remove rows of the tables Go writes, and money is
the existing application's until M12 (27.2, 01 risk 7). No column of
`activity` beyond status and the day is needed (status, `last_reason`,
`daily_visit_batch_id` and `updated_at` are already granted), but this is a
new kind of right on a money table, so it is put to the owner and nothing is
built past the contract:

1. **A narrow function, like the school lock (27.8 §2).**
   `gateway_money.withdraw_unmoved_advances(activity_id)`, `SECURITY
   DEFINER`, owned by a NOLOGIN role that holds `DELETE` on `advance_request`
   and nothing else, deleting only that activity's rows outside
   `MONEY_MOVED_ADVANCE_STATUSES` (exported to `rules.json`, drift-tested),
   in the caller's transaction. The gateway gets `EXECUTE` only and still
   cannot delete or change any advance otherwise;
   `TestGatewayRoleCanNeitherWriteNorReadSecrets` and the guard keep refusing
   a direct `DELETE`. The cancel then stays one transaction, as today. A new
   database object: production needs the owner's approval at cutover.
   *Recommended.*
2. **Django withdraws the advance after commit**, in the settling relay.
   Keeps every money write in Django, but the cancel is no longer one
   transaction: until the relay answers, a cancelled visit holds a pending,
   fundable advance, and if the relay fails nothing repairs it (the sweep
   prices days; it does not withdraw advances). That is the defect
   `_cancel_or_defer`'s docstring says the cancel was written to close.
3. **Hand on every cancel with an un-moved advance.** No rule changes, but
   Go would take only refusals: every priced visit has an advance.

## 30.5 Built

- **Scenario** `cmd/shadow/scenarios/cancel_visit.json` (19 steps): the six
  purposes scheduled (A–F, `[shadow-c]`), E moved into the submitted week
  (the base's fixture) and F moved first; then cancels of A (its day
  empties), B (its day keeps C), D with no reason (refused), F (a
  `rescheduled` visit), A again (already cancelled), E (in the submitted
  week: frozen day and frozen week), the training-and-visit pair
  (`cmwclue57008yjsdhhc9v`), a Core school's visit (`cmwd518kt00mo8bdhhc6v`),
  another officer opening a visit's drawer (refused at the drawer), D with
  a reason, C (the last of its day). On copy A: 17 answered ok, 2 refused.
- **Contract** `ActivityService.CancelSchoolVisit` in
  `edify/activities/v1/activities.proto`: the drawer's fields in
  (`activity_id`, `reason`), the cancelled activity (id, status, reason, the
  toast's words) or the refusal's words out. `buf lint`, `buf format
  --diff --exit-code`, and `buf breaking` against
  `origin/feature/edify-go-rn-migration` and against this branch's head pass.
  The Go (`backend/gen`), the web's (`web/src/gen`) and the app's
  (`mobile/src/gen`) generated code is regenerated with the pinned
  generators; only the activities files changed. Nothing implements or calls
  the RPC.

## 30.6 Not done

The writer role's extension, `internal/activities` `Service.Cancel`, the
cancel check door, the shadow proof at the service and the app level, and
the `EDIFY_GO_SAVES=cancel_visit` switch all wait for 30.4. No Django file
was changed. Nothing is switched on or cut over anywhere.
