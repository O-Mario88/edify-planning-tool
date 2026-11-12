# 30. The third save in Go: cancelling a school visit

M5 (04): "schedule, reschedule, cancel … Each write appends the same audit
and timeline rows as today." The owner's rule (2026-10-08, "Cancel undoes
scheduling"): cancelled work stops counting everywhere and its day's costs
follow. This piece follows 29's decisions: the pricing's refusals asked of a
read-only Django check before Go's transaction, the costs to follow written
by Go and settled by Django after commit, an acting seat handed on, and the
writer role changing `activity.status` and `daily_visit_batch_id` and no
other lifecycle column (29.4, 03 §3.7).

**Where it stands (2026-11-12).** Mapped (30.3) and measured (30.2); the
owner decided the advance (30.4); the function, the cancel check, the Go
cancel and the app's switch are built and proved in shadow at the service
and the app level (30.7, 30.8). Nothing is switched on outside this proof's
own processes.

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
  milestone credit to reverse, `reverse_activity_progress` on commit;
  a cancel whose pricing would be done inside the save); anything that
  writes a notice after commit (an open overdue reminder, an open day-off
  notice, as 29.1); a reason longer than `last_reason` holds (512).
- **Kept as the existing save does them** (the coordinator: reproduce, do
  not fix): a visit already cancelled is cancelled again (its reason
  replaced, a new audit row, no timeline row); a visit on a day whose week
  has left draft (and holds none of its lines in a sent week) stays on that
  day; a disbursed advance stays (only unmoved ones are withdrawn).

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
| **Advances** | 6656–6658 | `AdvanceRequest … exclude(MONEY_MOVED_ADVANCE_STATUSES).delete()` | `gateway_money.withdraw_unmoved_advances` in the transaction (30.4, 30.6) |
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
27.8 §1's decided pattern; it is built (30.7).

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

## 30.6 The function (the owner's decision, built)

`platform/deploy/db/advance_withdraw_roles.sql`, applied after
`activities_roles.sql` by `apply-roles.sh` and the integration TestMain:
`gateway_money.withdraw_unmoved_advances(activity_id) RETURNS integer`,
`SECURITY DEFINER`, `search_path` pinned, owned by
`edify_advance_withdraw_owner` (NOLOGIN, NOINHERIT, no members), which holds
`SELECT (activity_id, status)` and `DELETE` on `advance_request` and nothing
else. It deletes that activity's rows whose status is not one of
`MONEY_MOVED_ADVANCE_STATUSES` (status is NOT NULL, so this is the
existing `exclude()`), and answers how many. `edify_activities_rw` gets
`USAGE` on the schema and `EXECUTE` on the function only.

- The statuses are exported to `rules.json` (`cancel.money_moved_advance_statuses`,
  `export_schedule_visit_rules`, drift-tested); `TestTheWithdrawFunctionNamesTheMovedStatuses`
  fails when the SQL's list differs.
- `TestTheWithdrawFunctionRemovesOnlyThatActivitysUnmovedAdvances`: one of
  an activity's advances marked disbursed for the test (put back after);
  the gateway's call removes exactly the others, the moved one and another
  activity's stay; the gateway cannot `DELETE` an advance itself or
  `SET ROLE edify_advance_withdraw_owner` (42501).
- `TestGatewayRoleCanNeitherWriteNorReadSecrets` also refuses deleting or
  changing an advance, becoming the owner role, and writing a milestone
  credit; `dbguard.undeletableTables` names `advance_request`, so staging
  refuses any gateway role that can delete an advance;
  `TestStagingIdentityCheckAcceptsOnlyTheReadOnlyRole` passes.
- The writer role needed nothing else: the cancel's columns (status,
  `last_reason`, the batch, `updated_at`) and the timeline insert were
  granted for the move (29.5).

## 30.7 The cancel, built and proved in shadow

| Piece | Where |
|---|---|
| The cancel | `internal/activities/cancel.go` (`Service.Cancel`), 30.3 in its order. Before the transaction: the hand-ons, the reason ("Give a reason this activity is being cancelled.", with the view's `cancel_activity` failure row), the notices, the relay's verdict and its refusal (with the failure row). One read-write transaction: the activity's lock (changed since the read: handed on), `status 'cancelled'`, `last_reason`, the `cancelled` timeline row unless it was already off the plan, the day left (unless its week has left draft), `withdraw_unmoved_advances`, the costs to follow exactly as the relay says the existing save keeps them (no row when nothing is kept). After commit: the ledger mark, the `cancel_activity` row (`reason "Activity cancelled"`, payload `{"reason"}`, the leave-cover stamp), then Django settles |
| Money | `POST /api/auth/internal/visit-cancel-check` in `apps/daily_visit_batches/gateway_relay.py` (route in `apps/accounts/urls.py`): the cancel played on the activity in a transaction it rolls back; answers whether a sent week holds its lines, whether a credit would be reversed, whether its day has left draft, whether the save would price inside itself, the days, owner-weeks and owner-months it keeps, and `_assert_days_can_follow`'s refusal |
| The audit chain | `internal/audit` now projects a row with no payload as `{"value": null}`, as `publish_audit_event` does (it wrote `{}`); found by the first run, whose only differing row was the refusal's event |
| The shadow's Go half | `cmd/shadow/goplay` plays a step that opens `/my-plan/{id}/cancel-drawer` through `Service.Cancel` |

The scenario's last steps were reordered (the pair, the Core visit and the
other officer last) after the first run: the person's `last_seen_*` is the
last request the existing application served them, and Go's saves are not
its requests, so two of Go's cancels at the end left it on an earlier
path. That run's only other difference was the projection above.

**The run** (`agent13_shadow2.txt`), last lines exactly as printed:

```
0 of 19 steps answered differently
goplay exit 0
366 tables, 17 changed by the runs
0 of 17 changed tables differ
shadow exit 0
verify_chain {'ok': True, 'brokenAt': None, 'checkedRows': 15972, 'fromSeq': None}
```

Eight cancel steps were Go's: seven cancels (A, whose day empties; B, whose
day keeps C; F, rescheduled first; A again, already cancelled; E, on the
sent week's locked day, kept on it; D; C) and the blank reason's refusal.
Three were handed on: the pair, the Core visit, the other officer's drawer
(refused at its read).

## 30.8 The app's Cancel save reaches Go (behind a switch, development only)

The app is unchanged: it reads `/my-plan/{id}/cancel-drawer` with
`PageDrawerService.GetDrawer` and saves it with `SaveDrawer(path,
{reason})`. With `EDIFY_GO_SAVES=cancel_visit` the gateway
(`internal/screens/cancel_save.go`) asks the existing application for the
form (`POST /api/mobile/v1/drawer?form_only=1`; `DrawerFeedView` now gives a
form for the cancel's save as for the reschedule's, `FORM_ONLY_SAVES`, and
saves nothing), then as 29.7: a form refusal is answered as is; a form Go
does not take, a hand-on or an acting seat is forwarded whole; a Go cancel
answers `{saved: true, message: "Saved. Press Refresh to see it on the
page. ×"}`; a Go refusal `{saved: false, error: "Cancellation Error:
{words}"}` (`error_fragment(exc, action="Cancellation Error")` read back); a
failure before the cancel `Unavailable`, nothing written.

`config.GoSaves.CancelVisit`, named `cancel_visit`: off unless named,
refused in test and production, needing the existing application's address
and internal key. It has been on only in this proof's gateway (8097).

**The proof at the app's level** (`cmd/shadow/appplay` plays a Cancel step as
the app does): copy A through gateway 8096 (switch off) over Django 8196 on
`edify_shadow_a`, copy B through gateway 8097 with
`EDIFY_GO_SAVES=cancel_visit` over Django 8197 on `edify_shadow_b`. On B
Django served 10 form-only requests, 7 cancel checks and 4 forwarded drawer
saves (the two moves, the pair, the Core visit); Go made the other 8. Last
lines exactly as printed (`agent13_app_shadow1.txt`):

```
0 of 19 steps answered differently
compare exit 0
366 tables, 14 changed by the runs
0 of 14 changed tables differ
shadow exit 0
verify_chain {'ok': True, 'brokenAt': None, 'checkedRows': 15970, 'fromSeq': None}
```

(The script's own "forwarded drawer saves" line printed 0: its pattern does
not match this server's log format; the 4 above are counted from the log.)

**Tests.** `internal/activities/cancel_test.go` (the function's statuses,
the hand-ons before any read, no costs row when nothing is kept);
`internal/screens/cancel_save_test.go` (forwarded while off; Go takes the
cancel with the form's reason and origin and forwards nothing; hand-on,
another drawer, a save elsewhere, a non-text form forwarded; the refusal's
words; a failure); `internal/config/go_saves_test.go`; integration
`TestTheGoCancelIsOffByDefaultAndRefusedInProduction`,
`TestTheWithdrawFunctionRemovesOnlyThatActivitysUnmovedAdvances`, the
gateway-role and staging tests; Django `test_gateway_relay` (the cancel
check's door) and the rules drift test.

## 30.9 Not done

Switching the cancel off in Django in the same release (03 §3.7) and any
cutover wait for the owner; the function is a new database object needing
the owner's approval for production. No replayed month on a sanitised
restore. Not reachable with the seed data, so covered by the code path and
the hand-on rule only: a sent week holding the visit's lines, a milestone
credit, an open overdue reminder or day-off notice, a disbursed advance
beside a cancelled visit (the function's test covers the filter), and a
pricing refusal on the day left. The form-only door for the cancel has no
Django test of its own (DB-backed); the app-level run proves it.
