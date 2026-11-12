# 29. The second save in Go: rescheduling a school visit

M5 (04): "schedule, reschedule … Each write appends the same audit and
timeline rows as today." The first save (27) put a visit on a day; this one
moves it to another. It follows 27.8's decisions: the pricing's refusals are
asked of a read-only Django check before Go's transaction, the costs to
follow are settled by Django after commit, a person in an acting seat is
handed on. (The school lock of 27.8 §2 is not needed: a move locks the
activity's own row, as the existing save does.)

## 29.1 Scope

- **In:** one scheduled staff school visit of the first save's kind (a
  `purpose_type` among the six, its activity type the purpose's, a school, no
  cluster, project, partner, pair or end date), still `scheduled` or
  `rescheduled` and never begun, pooled into a day, moved by its own owner,
  at a school in their own portfolio that is not a Core school, from the
  Reschedule drawer (`/my-plan/{id}/reschedule-drawer` posting to
  `/my-plan/{id}/reschedule`).
- **Handed on, unchanged** (the gateway forwards the request whole): an
  In-school Training pair (`apps/activities/pairs.py`), group reschedule
  (`group_actions.py`), Core package visits, partner work, cluster work,
  another person's activity (the view's own doors and their audit rows),
  a person in an acting seat, and work whose money has moved: a sent week
  the move would take back (`take_back_for_plan_change`), a day it leaves
  whose week has left draft (the day is left frozen), lines in more than one
  week or month. Also handed on, because the existing save then writes
  notices after commit: an open "Action Required: Overdue" notice on the
  activity (`_resolve_overdue_reminder`) and an open day-off notice for the
  owner (`_settle_day_off_notices`).

## 29.2 What one move writes (measured, 2026-11-12)

`cmd/shadow/scenarios/reschedule_visit.json` on a fresh copy through the
existing application (`django_runner.py`; a step may now name an activity an
earlier step made, `{activity:<purpose text>}`): six visits scheduled, then
moved. Besides what the scheduling steps write (27.1), each move writes:

| Table | Row | Written by |
|---|---|---|
| `activity` | UPDATE of `scheduled_date, fy, quarter, planned_date, planned_month, planned_week, reschedule_count (+1), last_reason, status ('rescheduled'), daily_visit_batch_id, updated_at` (`partner_date_set_by, end_date, expected_participants, execution_started_at` are in the save's field list but unchanged for this case) | `services.reschedule`, `_detach_from_daily_visit_batch`, `reschedule_within_batch` |
| `activity_schedule_change` | the timeline row: `kind 'rescheduled'`, from/to day, from/to status, `reason` (`last_reason[:512]`); none when the day is the same | `schedule_trail._record_schedule_change` (post_save) |
| `daily_visit_batch` | the new day, made with its defaults when the owner has none that day; its `reason` set to the move's reason when that differs | `reschedule_within_batch` |
| `daily_visit_costs_to_follow` | `steps.days = [[old day, owner], [new day, owner]]` (one day when the move stays on its day), `weeks`/`months` = the activity's cost lines' owner-weeks and owner-months, `notes = [reschedule_note]` (`old`: the stored `scheduled_date` in UTC ISO form, `new`: the new date as Kampala midnight ISO, `reason`), `change` = `_named(activity)` ("Donor Visit at Central Division …"), provenance | `costs_follow._hand_over` |
| `target_ledger_dirty` | (owner, FY of the old day) and (owner, FY of the new day) upserted on commit, for credited types | `ledger_sync._changed` |
| `audit_log`, `domain_event_log` | `reschedule_activity`, payload `{"new_date", "reason"}`, the actor's role, the request's ip, agent, correlation, the leave-cover stamp | the view (`my_plan_views.py:1319`), `audit.services.log` |

Then the pricing that follows (Django's, settled after the answer): cost
snapshots and lines, both days' figures, the week's and month's requests,
transport and advance rows, the route batch and its checks. The service
writes no audit row of its own for a move; the view's `reschedule_activity`
row and the schedule-change row are the audit and timeline rows.

Measured run, last lines (`agent12_a1.json`): `19 steps on edify_shadow_a:
14 answered ok, 5 refused`; against the untouched base 22 tables changed
(the 21 of 26.2, `activity_schedule_change`, and for the refused other
officer's drawer an `admin_system_incident`, its `notification` and
`document_acknowledgement` rows, which are the view's door, handed on).

## 29.3 The path, line by line (this branch, 71c3a6476)

**The drawer and the view** (`apps/frontend/views/my_plan_views.py`):

| Step | Lines | What it does for this case | Go |
|---|---|---|---|
| Page gate | 1278 | `require_page_permission("my_plan")` | the drawer's form request (29.6) is Django's; Go takes only a form Django opened |
| Record gate | 1280–1293 | `can_view_record`; refused: `unauthorized_mutation_attempt` audit row and 403 "Access Denied: You do not have permission to reschedule this activity." | own activity only; anything else handed on (the door and its row stay Django's) |
| Fields | 1295–1307 | `scheduled_date`, `reason` (stripped); `plannedMonth`, `plannedWeek = min(5, (day-1)//7+1)` when the date parses | same |
| Pair | 1311 | `pairs.joins(a, RESCHEDULE)`: none for a visit with no pair | a pair (either half) → hand on |
| Move | 1315 | `pairs.reschedule` → `services.reschedule` (no other half) | the save below |
| Audit | 1317–1331 | `audit_log("reschedule_activity", payload {"new_date", "reason"})` after the move | the same row on the chain after commit |
| Answer | 1332–1333 | `saved_in_place()`: "Saved. Press Refresh to see it on the page.", `HX-Trigger: close-drawer` | the same |
| Refusal | 1335–1337 | any exception → `error_fragment(e, 400)`: its words | the same words |

**The move** (`apps/activities/services.py`, `reschedule` 5201–5435):

| Step | Lines | Reads / refuses | Go |
|---|---|---|---|
| Scope | 5202 | `_get_for_execution` → `_get_in_scope` (own school passes), `_assert_may_execute` (own work passes) | own work at own school |
| May schedule | 5203 | `_assert_may_schedule`: own work passes | — |
| Partner | 5204 | `_assert_partner_dates_own_work`: staff delivery, nothing | partner work → hand on |
| Closed | 5207 | `lifecycle_service.assert_operating(a.school)` → `CLOSED_SCHOOL_MESSAGE` | same words (rules.json) |
| Awaiting | 5208 | `_assert_not_awaiting_owner`: a request → refused | status outside scheduled/rescheduled → hand on |
| Executed | 5217 | `assert_not_executed` (`editing.py:76`) | status outside scheduled/rescheduled → hand on |
| Date | 5219 | `_parse_date(scheduledDate)`: blank or unparsable → "Invalid date: {value}" | same words |
| Past | 5222 | `fy_policy.assert_date_plannable`: "{d M Y} has passed. Schedule work from {today} onwards." | same (Kampala's day) |
| FY | 5225 | `assert_same_fiscal_year`: a no-op since 2026-09-17 | — |
| Calendar | 5230–5234 | `SchedulingPolicyService.refusal`: empty while `CALENDAR_BLOCKS_REFUSE = False` | rules.json; refuse only if on (hand on) |
| Period | 5236–5238 | `get_operational_fy` (UTC rule), `get_quarter_for_date`, `_schedule_period` (Kampala day, month, week) | the first save's helpers |
| Blocks | 5251–5255 | `planner_change` (named change for the costs row), `transaction.atomic`, `costs_follow` (answers first) | one read-write transaction |
| Lock | 5263 | `Activity … select_for_update()` | `SELECT … FOR UPDATE` on the activity (the writer role's UPDATE grant allows it) |
| Executed again | 5266 | `assert_not_executed` on the locked row | status re-read under the lock |
| Ceilings | 5267–5272 | `reserve_for_move` only for trainings | — |
| Duplicates | 5279–5301 | `assert_not_duplicate_client_visit` (same school, day, type, item, not gone, not the companion, not this one): "{school} already has this visit on {d b Y}. Open that visit instead of planning a second one for the same day."; the Core test is a no-op off Core schools | same, under the lock |
| Take back | 5306–5312 | `take_back_for_plan_change`: sent, unpaid weeks of the old and new days | non-empty (asked of the relay) → hand on |
| End date | 5316–5325 | none for this case | end date → hand on |
| Row | 5326–5378 | the fields of 29.2; `status` → `rescheduled` | one UPDATE |
| Money | 5379 → 5438 | `_reprice_moved_activity`: prior buckets from the cost lines; `day_to_join` (`daily_visit_batches/services.py:812`): the new day locked, "This date's visits have already left draft status. Choose another date." when its week has left draft, "You scheduled {n} school(s). The CD target is {t} schools per day. This will increase cost per school. Reason required." for a short day with no reason (the catalogue's `required_school_visits_per_day`); same day → found again after leaving; `_detach_from_daily_visit_batch` → `remove_school` (the old day kept for pricing; a locked old day is left frozen); `reschedule_within_batch` (the day made if none; its reason set); `sync_weekly/monthly_*` (the owner-weeks and months kept) | the join, the batch insert and the reason are Go's; every refusal here and `_assert_days_can_follow` are asked of the relay (29.5) |
| Note | 5381–5393 | `once_days_are_priced(LeaveBudgetImpactService.handle_reschedule, note=reschedule_note)` when the day changed: kept as a note | the note in the costs row |
| Hand-over | `costs_follow.py` 219–275 | `_assert_days_can_follow`, then the `CostsToFollow` row, then the settling thread on commit | the row; refusals from the relay; settled by Django after commit |
| Trail | `schedule_trail.py:63` | one `activity_schedule_change` when the day moved | the same INSERT |
| Ledger | `targets/ledger_sync.py:232` | old and new FY marked on commit | the same upserts after commit |
| Partner tell | 5398–5433 | partner work only | — |
| Notices | 5434–5435 | `_resolve_overdue_reminder`, `_settle_day_off_notices` on commit | an open notice of either kind → hand on (29.1) |

## 29.4 Decided, and what needs a decision

Covered by 27.8 and decided here:

1. **The pricing's refusals** are asked of a second read-only relay,
   `POST /api/auth/internal/visit-move-check` (beside 27.9's), before Go's
   transaction. It plays the move's money on the activity as Go will leave it
   (new dates, `_reprice_moved_activity`'s day refusals, `_assert_days_can_follow`
   on the days the move keeps), inside a transaction it rolls back, and
   answers the refusal and its stage, whether the move would take a sent
   week back, and whether the day left is frozen. Go meets the day's refusal
   where the existing save meets it: after its duplicate test.
2. **The costs to follow** are written by Go exactly as `_hand_over` writes
   them and settled by Django after commit with 27.9's relay.
3. **An acting seat** is handed on.

**Decided by the owner, 2026-11-12: "Yes, allow both"** (not covered by
27.8; built as proposed, then put to the owner): `dbguard.protectedColumns` refused any gateway role that can
change `activity.status` or `activity.daily_visit_batch_id` ("the later
saves' work", guard.go). A move must change both. The writer role grants
`UPDATE` on exactly the move's columns (29.2), and the guard now refuses
every other lifecycle, money, evidence, verification and ownership column of
`activity` instead (29.7).

## 29.5 Contract and writer role (built)

- **Contract:** `ActivityService.RescheduleSchoolVisit` in
  `edify/activities/v1/activities.proto`: the drawer's fields in
  (`activity_id`, `scheduled_date`, `reason`), the moved activity (id, status,
  planned date, FY, reschedule count, the toast's words) or the refusal's
  words out. `buf lint`, `buf format` and `buf breaking` against the migration
  branch pass; the Go and the web's TypeScript are generated. The app's
  TypeScript (`platform/mobile/src/gen`) is not regenerated here: this piece
  may not touch `platform/mobile`.
- **Writer role** (`activities_roles.sql`, appended): `UPDATE` of the move's
  eleven activity columns (which also allows the row's `FOR UPDATE` lock),
  `UPDATE (reason)` of a day, `INSERT` of the timeline row, `SELECT` of the
  cost lines' owner, year, month and week, and of a notice's recipient,
  event, context and resolution (never its words).
- **Guard (29.4, flagged):** `dbguard.protectedColumns` no longer names
  `activity.status` and `activity.daily_visit_batch_id`, and now names the
  activity's owner, school, cluster, project, partner, delivery, kind, item,
  removal, start, delivery date, Salesforce ID, IA submission, PL review and
  pair, a day's owner and date, and the timeline row's day, kind and reason;
  `activity_schedule_change` is undeletable. `TestGatewayRoleCanNeitherWriteNorReadSecrets`
  refuses each of them, removing the trail and reading a notice's words;
  `TestStagingIdentityCheckAcceptsOnlyTheReadOnlyRole` still passes.

## 29.6 The move, built and proved in shadow (2026-11-12)

| Piece | Where |
|---|---|
| The move | `internal/activities/reschedule.go` (`Service.Reschedule`): 29.3 in its order. Before the transaction: the hand-ons, the closed school, the date (blank: "Invalid date: "), the past date, the relay's verdict, the lines' week and month. One read-write transaction: the activity's lock (anything changed since the read: handed on, nothing written), the duplicate test, the day's refusal where the existing save meets it, the day joined (made with its defaults when the owner has none; the move's reason kept on it), the activity's UPDATE, the timeline row when the day changed, the costs to follow. After commit: the ledger's marks (sorted, distinct, one statement, as `_write_marks`), the `reschedule_activity` row on the chain with the leave-cover stamp, then Django settles the costs and announces |
| Money (27.8 §1) | `POST /api/auth/internal/visit-move-check` in `apps/daily_visit_batches/gateway_relay.py` (route in `apps/accounts/urls.py`): the move played on the activity inside a transaction it rolls back (`will_take_back`, the frozen day, `_reprice_moved_activity`'s day refusals, `_assert_days_can_follow`); settling reuses 27.9's `costs-to-follow` door |
| Vocabularies | `rules.json` `move`: the two notice events and `saved_in_place`'s words, exported by `export_schedule_visit_rules` |
| The shadow's Go half | `cmd/shadow/goplay` plays a step that opens `/my-plan/{id}/reschedule-drawer` through `Service.Reschedule` (the activity found on copy B by its purpose text, as the runner finds it); a step whose drawer copy A refused is played on copy B by the existing application, as the gateway reads every drawer there. `cmd/shadow` now also reads an incident's `samples` (request tags) as `<chain>` and a path naming a row the run made as `<new>` |

**The scenario** (`cmd/shadow/scenarios/reschedule_visit.json`, 19 steps):
six visits scheduled through the first save (all six purposes), then moved:
to a new day (the day left empties), onto another visit's day (leaving a
shared one), within the same day, to a past date, onto a day of the
submitted week that already has a batch (refused, "left draft"), to a new
day in that week, out of that week into the next fiscal year (handed on:
the day left is frozen), with no date, onto a short day with no reason
(refused, "Reason required"), a second move of a moved visit; a
training-and-visit pair, a Core school's visit and another officer's opening
of a visit's drawer are handed on.

**The run** (copy A through the existing application, copy B through Go
with Django on 8196 over copy B; `agent12_shadow4.txt`), last lines exactly as
printed:

```
0 of 19 steps answered differently
goplay exit 0
366 tables, 22 changed by the runs
  ...
0 of 22 changed tables differ
shadow exit 0
verify_chain {'ok': True, 'brokenAt': None, 'checkedRows': 15978, 'fromSeq': None}
```

Fifteen steps were Go's (the six schedules; five moves; four refusals: the
past date, the left-draft day, no date, the short day), four handed on. The
first run found two things, both fixed: Go marked the ledger once per day
rather than once per distinct year in one statement (the ledger's serial
ids then drifted), and the harness compared the request tags and the new
incident's id inside a path written by Django's own refused-drawer door.

**Not proved here.** A closed school, an open overdue reminder or day-off
notice, a take-back of a sent week and lines in two weeks cannot be reached
with the seed data; they are the code path and the hand-on rule only.

## 29.7 The app's Reschedule save reaches Go (behind a switch, development only, 2026-11-12)

**How it reaches Go.** The app is unchanged: it still reads the drawer with
`PageDrawerService.GetDrawer("/my-plan/{id}/reschedule-drawer")` and saves
it with `SaveDrawer(path, {scheduled_date, reason})`. With
`EDIFY_GO_SAVES=reschedule_visit` the gateway (`internal/screens/reschedule_save.go`,
called from `SaveDrawer` for that path and no page-form key) first asks the
existing application for the form: `POST /api/mobile/v1/drawer?form_only=1`,
the same `DrawerFeedView.post` with the same drawer read and refusals,
answering `{"form": drawer_blocks.form_data(html, values), "save": the path
the form posts to, "origin": {ip, agent, correlation}}` and saving nothing;
every other drawer asked for a form is refused (400). Then, as 27.10: a
form-request refusal is answered as is; a form Go does not take, a hand-on,
or an acting seat is forwarded whole; a Go move answers `{saved: true,
message: "Saved. Press Refresh to see it on the page. ×"}` (the toast and
its close button, as `_saved_outcome` reads `saved_in_place`); a Go refusal
answers `{saved: false, error}` in `error_fragment`'s words read back; a
failure before the move answers `Unavailable`, nothing written. A move is
never made by both.

**The switch.** `config.GoSaves.RescheduleVisit`, named
`reschedule_visit`; off unless named, refused in test and production, and
needing the existing application's address and internal key, exactly as
`schedule_visit`. It has been on only in this proof's own gateway (8097).

**The proof at the app's level** (`cmd/shadow/appplay`, which now plays a
Reschedule step as the app does and finds the step's activity on its own
copy with `-db`): copy A through gateway 8096 with the switch off over
Django 8196 on `edify_shadow_a`; copy B through gateway 8097 with
`EDIFY_GO_SAVES=reschedule_visit` over Django 8197 on `edify_shadow_b`. The
six scheduling steps are forwarded on both. On B Django served 12 form-only
requests and 3 forwarded saves (the frozen day, the pair, the Core visit);
Go made the other 9 (five moves, four refusals); the other officer's drawer
was refused at its read on both. Last lines exactly as printed
(`agent12_app_shadow1.txt`):

```
0 of 19 steps answered differently
compare exit 0
366 tables, 19 changed by the runs
0 of 19 changed tables differ
shadow exit 0
verify_chain {'ok': True, 'brokenAt': None, 'checkedRows': 15976, 'fromSeq': None}
```

**Tests.** `internal/activities/reschedule_test.go` (Python's isoformat,
the calendar day, the exported words, the hand-ons before any read);
`internal/screens/reschedule_save_test.go` (forwarded while off; Go takes
the move with the form's fields and origin and forwards nothing; every
hand-on, another drawer, a save elsewhere and a non-text form forwarded;
the refusal's words; a failure); `internal/config/go_saves_test.go` (the
move's switch); `TestGatewayRoleCanNeitherWriteNorReadSecrets`,
`TestStagingIdentityCheckAcceptsOnlyTheReadOnlyRole`,
`TestGatewaySourcesContainNoSchemaChanges` (the timeline row added to the
activities package's tables); Django `test_gateway_relay` (the move check's
doors). The form-only door in `DrawerFeedView` has no Django test of its
own (the suite's DB-backed tests are not run by this piece); it is proved by
the app-level run above.

**Not done.** Switching the move off in Django in the same release
(03 §3.7) and any cutover wait for the owner; the switch is on nowhere but
this proof's processes. The web (Next.js) does not call this path. The app's
TypeScript stubs are not regenerated (no change reaches the app: it calls
`SaveDrawer`, not the new RPC). No replayed month on a sanitised restore.

**Merged and re-proved by the coordinator (2026-11-12)**, with the first
save's same-day check now skipping deleted visits as Django's does: the
schedule and reschedule scenarios at the service and the app level, from
fresh copies, no step answered differently and no changed table differing
(schedule 0 of 20 and 0 of 19, reschedule 0 of 22 and 0 of 19), the audit
chain verifying on each; race and the integration suite pass. The owner
allowed the writer role to change an activity's status and day (29.4).
