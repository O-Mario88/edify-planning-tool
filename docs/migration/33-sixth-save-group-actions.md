# 33. The sixth save in Go: group reschedule and group cancel

M5 (04): "schedule, reschedule, cancel … Each write appends the same audit
and timeline rows as today." The bar for ticked rows (My Plan, the Work
Plan, a profile's Planned table, the Calendar) opens two drawers,
`/activity-selection/reschedule` and `/activity-selection/cancel` (owner,
2026-10-05: "group reschedule … Make sure group cancel also is there").
Each ticked activity goes through the single save it would go through
alone, so this piece reuses Go's single Reschedule (29) and Cancel (30) and
ports only what the group adds. It follows 27.8's, 29.4's and 30.4's
decisions: the pricing's refusals asked of the read-only Django checks before
Go's transaction, the costs to follow written by Go and settled by Django
after commit, an acting seat handed on, the writer role kept to what the
save writes (no new right is used).

**Where it stands (2026-11-13).** Mapped (33.2, 33.3), built (33.5) and
proved in shadow at the service and the app level for both saves, and the
single reschedule's and cancel's scenarios re-proved on this code (33.6).
Nothing is switched on outside this proof's own processes.

## 33.1 Scope

Go takes a group only when **every** ticked activity (every `activity_ids`
the drawer's form posts) is one Go's single move (29.1) or single cancel
(30.1) takes, read before anything is written: a staff school visit of the
first save's kind, owned by the person, at a school in their own portfolio
that is not a Core school, still a plan (`scheduled`/`rescheduled`; a
cancel also takes `cancelled`, which the group leaves "Already
cancelled."), with no open overdue reminder or day-off notice. Then the
group's own rules are Go's (33.3), and each activity's money is asked of the
same read-only check its single save asks.

**Handed on whole** (the gateway forwards the original request unchanged;
nothing is written by Go): a ticked activity Go's single save would hand on
(another person's, partner, cluster or Core work, either half of an
In-school Training pair, an activity with no date, …); no tick, or more than
100; a person in an acting seat or an asking role; a date in another form
than `YYYY-MM-DD` (Python's `date.fromisoformat` reads more); a cancel reason
longer than 512; a place name beyond ASCII when there are several picks (the
drawer's order casefolds it); any activity whose check says its money has
moved (a sent week taken back, a frozen day left, a milestone credit, a
frozen week, a cancel priced inside the save, lines in two weeks or months);
any pricing refusal the group meets as a whole (33.4 §1); and **two or more
visits moving onto a day the owner has no visits on yet** (33.4 §2). A group
is never split between the two applications, and no activity is saved by
both.

## 33.2 What one group writes (measured, 2026-11-13)

`cmd/shadow/scenarios/group_reschedule.json` through the existing
application on a fresh copy: steps 1–7 on copy A, steps 1–6 on copy B, then
`go run ./cmd/shadow` (`agent17_m7a.json`); step 7 alone again with the
settling thread held (`agent17_keep_runner.py`, `_when_the_save_commits`
stubbed, as 30.2) to read the save's own rows. Step 7 moves A (17 Nov), B and
C (18 Nov) onto D's day (19 Nov) together.

| Table | Rows | Written by |
|---|---|---|
| `activity` | each moved visit: 29.2's UPDATE (dates, FY, quarter, count + 1, reason, `rescheduled`, the day) | `services.reschedule` per visit, inside the group's transaction, each in a savepoint |
| `activity_schedule_change` | one `rescheduled` row a visit | `schedule_trail` (post_save) |
| `daily_visit_costs_to_follow` | **one** row for the group: `steps.days` = every day left and joined, in the order last asked (`[[17 Nov], [18 Nov], [19 Nov]]`), `together: true`, the owner-weeks and owner-months once each, one `reschedule_note` a visit, `change: "3 activities"` (the group's `planner_change(what=…)`), one correlation | `costs_follow._hand_over` once, at the end of `_together` |
| `target_ledger_dirty` | (owner, FY) for every year a moved visit left or joined, one upsert on commit | `ledger_sync._MarksOnCommit` (one callback a transaction) |
| `audit_log`, `domain_event_log` | `reschedule_activity` per moved visit, `success true`, no reason, payload `{"new_date", "reason", "group": true}`; then per visit left, `success false`, `reason` its refusal, the same payload | the view's `_audit`, after the group |

Then the pricing that follows (Django's, settled after the answer, as for
the single saves): each day priced once, read from its members
(`together`): cost snapshots and lines, the days' figures and route batch,
the week's and month's requests, transport and advance rows. Measured step
7 against the six-step copy: `366 tables, 18 changed by the runs` (the save
and its pricing; `daily_visit_costs_to_follow` is settled away).

A group cancel writes the same shape (the full proof's 15 changed tables,
33.6): each visit 30.2's rows (`cancelled`, `last_reason`, its timeline row,
off its day unless the day's week has left draft, its unmoved advances
deleted through `gateway_money.withdraw_unmoved_advances`), one costs row for
the group (`together: true`, `notes: []`, `change: null`: a group cancel
has no `planner_change`), the ledger marks once, and the view's
`cancel_activity` rows (`success true`, no reason, payload
`{"reason", "group": true}`; a refused pick `success false` with its reason).

A group of one changing activity is not a group to the pricing: `_apply`
changes it alone (`_one_at_a_time` outside any transaction), so it writes
exactly the single save's rows (its own costs row, `together: false`, the
single `change`), with the group's audit rows.

## 33.3 The path, line by line (this branch, 721c6e9c5)

**The views** (`apps/frontend/views/activity_group_views.py`):

| Step | Lines | What it does | Go |
|---|---|---|---|
| Gate | 116, 144 | `require_page_permission("my_plan")` | the drawer's form request is Django's (as 29.7) |
| Drawer | 98–113 | GET: `selection(ids)`; the form posts one `activity_ids` per pick it can take (`ready`), not the ones it leaves | the form-only door gives exactly those ids |
| Fields | 122–123, 160 | `scheduled_date`, `reason` stripped | same |
| Refusal | 124–127, 161–164 | a `BadRequest` from the group → `error_fragment` (cancel: "Cancellation Error: …"), no audit row | the same words, nothing written |
| Audit | 74–95, 128, 165 | after the group: a row per pick changed, then a row per pick left (its refusal as the reason), payload plus `"group": true` | the same rows on the chain after commit, in that order |
| Answer | 54–71 | anything changed: flash "N activit{y,ies} moved to {d Month YYYY}." / "N … cancelled.", then " Not {verb}: {title} at {where} ({why without its full stop}); …" for the first three left and " and N more"; 204 + `HX-Refresh`. Nothing changed: `group_outcome.html` ("Nothing was {verb}." and each pick "{title} · {where}: {why}") | the same words (`finishAnswer`); the app reads the flash (`_saved_outcome`) or the partial's text |

**The group** (`apps/activities/group_actions.py`):

| Step | Lines | Reads / refuses | Go |
|---|---|---|---|
| Date, reason | 192–198 (reschedule), 233–235 (cancel) | `date.fromisoformat` fails → "Choose the date these activities move to."; blank reason → "Give the reason these activities are moving." / "… are being cancelled." | the same, in that order; another date form is handed on |
| Ids | 130–145 | strip, once each, in order; none → "Tick at least one activity first."; more than 100 → "Tick at most 100 …" | none or > 100 → hand on |
| Selection | 148–185 | found, not deleted, `can_view_record`; an unseen id dropped; pairs joined (`_units`); `_refusal` (cancel: "Already cancelled." / "Already completed. …"; reschedule: carried out, a partner's, the services' scope, awaiting the owner) | every id must be Go's single save's case (33.1), so none is dropped or joined; "Already cancelled." for a cancelled visit; the services' doors pass for own work |
| Order | 184 | by (day, place casefolded, title), stable | `sortPicks` (ASCII place names; others handed on) |
| On the day | 209–216 | a pick already on the new date → "Already on this date." | same |
| Count | 271–275 | `changing`: the picks the group did not leave; more than one (and `PRICE_A_DAY_ONCE_PER_SAVE`, default on) → `_together`, else `_one_at_a_time` | the same count; the setting is assumed on, as the single saves assume `SAVES_ANSWER_FIRST` |
| Together | 299–330 | one `transaction.atomic`; reschedule: `planner_change(what="{count} activities")`; `costs_follow()`, `fund_requests_follow_once()`, `each_day_priced_once(leaving_too=True)` (`kept.together`); each unit in its own savepoint (`_change` 354–375), a refusal undone to it (`priced_once_back_to`) and kept as the pick's reason (`_message`: the exception's words) | one read-write transaction, a savepoint per visit, Go's single in-transaction writes (`moveInTx`, `cancelInTx`) in the group's order; the kept days, weeks, months and notes folded as the blocks fold them; one costs row |
| Each move | `services.reschedule` | 29.3 in its order: closed school, past date, the lock, the duplicate test (it sees the visits moved before it), the day's refusals, the row, the money kept | `prepareMove` for each pick before the transaction (its refusals become the pick's reason; its hand-ons hand the group on), `moveInTx` inside |
| Each cancel | `services.cancel` | 30.3 in its order | `prepareCancel` before, `cancelInTx` inside |
| End | `costs_follow._hand_over` | `_assert_days_can_follow(days, together=True)` on every day; a refusal undoes the whole group and `_apply` changes it again one unit at a time | not ported: a group any of whose checks refuses is handed on (33.4 §1) |
| Commit | | the ledger's one callback; the settling thread | the marks in one statement, then the audit rows, then Django settles the one row |
| Partner notices, money moved | `_refusal`, `money_moved_ids` 243–258 | a partner's work and its notice; the drawer's count of disbursed advances | out of scope: partner work is handed on, and a disbursed advance stays (30.1) |

## 33.4 Decisions

Covered by 27.8, 29.4 and 30.4 and kept. Three choices made here, none a
rule change; the second needs a decision before Go can take more.

1. **The group's own pricing check is not asked.** Django meets
   `_assert_days_can_follow` once for the whole group when its block ends
   (`together=True`, each day read as the others will be priced), and a
   refusal there changes the group again one unit at a time, each with its
   own costs row. Go asks each activity's single check (29's and 30's doors)
   and hands the whole group on if any says the pricing would refuse; when
   none does, Go takes it as one. This is exact for every refusal that turns
   on one visit (a missing rate, a member's money moved, a paid transport the
   visit changes); a refusal that only the end state of several visits on one
   day could meet (a paid day's transport that one more school leaves as it
   is but several change) is not reachable with the seed and is not proved.
   A group-shaped read-only check door would make it exact.
2. **Several visits onto a day with none yet are handed on** (needs a
   decision to go further). The first visit makes the day; the second then
   meets it, and is refused "This date's visits have already left draft
   status." if the day's week has left draft (`_day_to_join`: only a day that
   exists is asked). Measured: B and C moved together onto 1 December (the
   submitted week, no visits yet): B moves, C is refused. Go would need to
   know whether the week has left draft, which is a read of
   `weekly_fund_request (responsible_user, week_start_date, week_end_date,
   status)` that the writer role `edify_activities_rw` does not have. It was
   not granted (the brief: stop and report). **For the coordinator:** grant
   that read (or answer it in the move check) and Go can take groups onto a
   new day; until then such groups are Django's.
3. **The words live in Go**, as the single cancel's do, because they are
   literals inside the group's functions and nothing else in Django may
   change; `TestTheGroupWordsAreTheExistingApplications` reads the Python
   and the template and fails if any word differs.

`dbguard` and the writer role are unchanged: the group writes only columns
and tables the single saves already write, and a savepoint needs no right.

## 33.5 Built

| Piece | Where |
|---|---|
| The group | `internal/activities/group.go`: `Service.GroupReschedule` and `Service.GroupCancel`, 33.3 in its order; `writeGroupMove` / `writeGroupCancel` (`_together`), `writeOneMove` / `writeCancel` (`_one_at_a_time` for one), `keepGroupCosts`, the ledger's savepoint rule (`groupMarks`), `afterGroup` (marks, the view's rows, the settle) |
| Reuse | `reschedule.go`: the move's transaction body is `moveInTx` (the single `writeMove` calls it, unchanged); `cancel.go`: `cancelInTx` likewise. `movedVisit` now hands on an activity with no `scheduled_date` (it failed to scan one, an error rather than a hand-on, met by the group's "another officer's" step) |
| The app's save | `internal/screens/group_save.go`, called from `SaveDrawer` for the two drawer paths: asks for the form (`?form_only=1`), reads `activity_ids` as a text or a list, calls the group, and answers `{saved: true, message: the flash}`, `{saved: false, error: the partial's words}` when nothing changed, `{saved: false, error: error_fragment's words}` for a refusal of the group (cancel prefixed "Cancellation Error: "), `Unavailable` for a failure before the group (nothing written); a hand-on is forwarded whole |
| Django | `apps/mobile_feed/views.py`: `FORM_ONLY_SAVES` names `activity_group_reschedule` and `activity_group_cancel` (behaviour-neutral: the form-only door saves nothing). Tests `test_a_group_form_is_what_the_save_would_post_and_nothing_is_saved`, `test_a_group_form_keeps_the_drawers_refusals` in `PageDrawerFeedTest` |
| The switch | `config.GoSaves.GroupReschedule` / `GroupCancel`, named `group_reschedule` / `group_cancel`: off unless named, refused in test and production, needing the existing application's address and internal key; each moves only its own drawer |
| The shadow | `django_runner.py` records a reloading save's flash messages and the posted activities' purpose texts; `goplay` plays a group step through Go (the ids found on copy B by those texts) and compares the flash; `appplay` plays a group step as the app does (`selectionPath`, then `SaveDrawer` with the date and reason) and takes `-settle`, a pause after each step (33.6) |

## 33.6 Proof in shadow

**The scenarios** (`cceo@edify.org` unless named).
`group_reschedule.json` (20 steps, `[shadow-g]`): six visits scheduled
(A–F); A, B, C onto D's day together (3); E and A onto F's day (2); D, A, F
to 25 Nov with A and F already there (one moves alone, two "Already on this
date."); B and C to a past date (nothing moved); B and C onto 2 Dec, the
submitted week's day (nothing moved: "left draft"); B and C onto 1 Dec, the
submitted week with no visits yet (handed on, 33.4 §2: B moves, C refused);
no date; no reason; C with the training pair's visit (handed on: the pair
joins); D with a Core school's visit (handed on); `cceo1@edify.org` ticking
two of cceo's visits (the drawer posts none: handed on); D with an
undated activity (handed on); five ticked onto 27 Nov (three move, two
already there); the five moving together to 25 Nov.
`group_cancel.json` (23 steps, `[shadow-gc]`): thirteen visits scheduled
(A–M), E moved into the submitted week; A and B cancelled together; F alone;
A, C, D ticked with A already cancelled (the drawer posts C and D); no
reason; E (on the sent week's locked day, kept on it) with G; H with the
training pair (handed on); H, already cancelled, with a Core visit (handed
on); `cceo1@edify.org` ticking H and I (handed on); I, J, K, L, M together.

**Service level** (`agent17_shadow_run.sh`: copy A through the existing
application, copy B through Go with Django on 8196 over copy B; the window
now closes once that Django has stopped, since a Go save's pricing and route
check run in its threads after the answer). Group reschedule
(`agent17_run1.txt`), last lines exactly as printed:

```
20 steps on edify_shadow_a: 17 answered ok, 3 refused
0 of 20 steps answered differently
goplay exit 0
366 tables, 20 changed by the runs
0 of 20 changed tables differ
shadow exit 0
verify_chain {'ok': True, 'brokenAt': None, 'checkedRows': 16037, 'fromSeq': None}
```

Go made the six schedules and nine groups (steps 7–11, 13, 14, 19, 20: five
saves of 1–5 activities, two "nothing moved" outcomes, the two refusals of
the group); five were handed on (the new day in the submitted week, the
pair, the Core visit, cceo1's empty form, the undated activity). Group
cancel (`agent17_run3.txt`):

```
23 steps on edify_shadow_a: 21 answered ok, 2 refused
0 of 23 steps answered differently
goplay exit 0
366 tables, 15 changed by the runs
0 of 15 changed tables differ
shadow exit 0
verify_chain {'ok': True, 'brokenAt': None, 'checkedRows': 15999, 'fromSeq': None}
```

Go made the thirteen schedules, the move, and six groups (2, 1, 2, the blank
reason, 2 with the sent week's day kept, 5); three were handed on.

**App level** (`agent17_app_shadow2.sh`: copy A through gateway 8096 with
the switches off over Django 8196 on `edify_shadow_a`; copy B through gateway
8097 with `EDIFY_GO_SAVES=group_reschedule` or `group_cancel` over Django
8197 on `edify_shadow_b`; `appplay -settle 3s`). Group reschedule
(`agent17_run9.txt`):

```
0 of 20 steps answered differently
compare exit 0
366 tables, 19 changed by the runs
0 of 19 changed tables differ
shadow exit 0
verify_chain {'ok': True, 'brokenAt': None, 'checkedRows': 16037, 'fromSeq': None}
form-only requests on B: 14
forwarded drawer saves on B: 5
forwarded schedule saves on B: 6
```

Group cancel (`agent17_run10.txt`):

```
0 of 23 steps answered differently
compare exit 0
366 tables, 14 changed by the runs
0 of 14 changed tables differ
shadow exit 0
verify_chain {'ok': True, 'brokenAt': None, 'checkedRows': 15999, 'fromSeq': None}
form-only requests on B: 9
forwarded drawer saves on B: 4
forwarded schedule saves on B: 13
```

On B Go made 9 group reschedules (14 forms asked, 5 forwarded) and 6 group
cancels (9 forms, 3 forwarded; the fourth forwarded drawer save is the
single move, whose switch was off). The schedules were forwarded (their
switches off).

**Why `-settle`.** The first app-level group reschedule run, with no pause
(`agent17_run2.txt`), answered every step the same and left every table
the same but one, exactly as printed:

```
  domain_event_log                         DIFFERS: 9 rows only in a, 9 only in b
1 of 19 changed tables differ
```

Every differing row differs only in `payload.auditSeq`: on copy A the
existing application's settling thread for step 9 (a move made alone, priced
after its answer) sealed its `activity.cost.calculated` rows after step 10's
two `reschedule_activity` refusal rows; on B Go waits for Django to settle
before it answers, so they came first. The web's next request waits for the
costs that follow (the `edify_costs_following` cookie); the app's does not,
so on A the order is a race between two requests, not a difference in what
the save writes (the rows and the chain are the same; `cmd/shadow` reads
`audit_log.seq` as `<chain>` but not the sequence copied into an event's
payload). With a three-second pause after each step, as a person's next
request takes, the run above leaves nothing differing. The group cancel's
run without the pause (`agent17_run4.txt`) also left nothing differing
(`0 of 23 steps answered differently`, `0 of 14 changed tables differ`,
`verify_chain … 'checkedRows': 15999`).

**The single saves re-run on this code** (they share `moveInTx`,
`cancelInTx`, `movedVisit` and the runner), last lines exactly as printed:
reschedule service (`agent17_run5.txt`): `19 steps on edify_shadow_a: 14
answered ok, 5 refused`, `0 of 19 steps answered differently`, `366 tables,
22 changed by the runs`, `0 of 22 changed tables differ`, `shadow exit 0`,
`verify_chain {'ok': True, 'brokenAt': None, 'checkedRows': 15978,
'fromSeq': None}`; reschedule app with `EDIFY_GO_SAVES=reschedule_visit`
(`agent17_run6.txt`): `0 of 19 steps answered differently`, `compare exit 0`,
`366 tables, 19 changed by the runs`, `0 of 19 changed tables differ`,
`shadow exit 0`, `verify_chain {'ok': True, 'brokenAt': None, 'checkedRows':
15976, 'fromSeq': None}`, `form-only requests on B: 12`; cancel service
(`agent17_run7.txt`): `19 steps on edify_shadow_a: 17 answered ok, 2
refused`, `0 of 19 steps answered differently`, `366 tables, 17 changed by
the runs`, `0 of 17 changed tables differ`, `shadow exit 0`, `verify_chain
{'ok': True, 'brokenAt': None, 'checkedRows': 15972, 'fromSeq': None}`;
cancel app with `EDIFY_GO_SAVES=cancel_visit` (`agent17_run8.txt`): `0 of 19
steps answered differently`, `compare exit 0`, `366 tables, 14 changed by
the runs`, `0 of 14 changed tables differ`, `shadow exit 0`, `verify_chain
{'ok': True, 'brokenAt': None, 'checkedRows': 15970, 'fromSeq': None}`,
`form-only requests on B: 10`. (Those four app runs used the first copy of
the script, whose "forwarded" counts printed 0: its patterns did not match
the server's log format; the second copy's do.)

## 33.7 Tests

`internal/activities/group_test.go`: the words against the Python source;
the ids cleaned as `clean_ids` cleans them; the hand-ons before any read;
the drawer's order; the kept days in the order last asked, weeks and months
once; the ledger's savepoint rule; the view's words (count, date, three
named and "and N more", the full stop dropped, the outcome partial).
`internal/screens/group_save_test.go`: forwarded while the switch is off
(each switch moves only its own drawer); Go takes the group with every tick
and the form's origin and forwards nothing; one tick read as text; a
hand-on, a save elsewhere, a non-text form and another bar's drawer
forwarded whole; the refusal's, the cancel's and the outcome's words; a
failure `Unavailable` with nothing forwarded. `internal/config/go_saves_test.go`
`TestTheGroupSavesAreOffUnlessNamed`; integration
`TestTheGoGroupSavesAreOffByDefaultAndRefusedInProduction`; the
gateway-role and staging tests (no new right). Django: the two
`PageDrawerFeedTest` tests above, run with the rest of the class on a
private test database (`TEST_DATABASE_NAME=edify_test_agent17`): `Ran 21
tests`, `OK`.

## 33.8 Not done

Switching the group off in Django in the same release (03 §3.7) and any
cutover wait for the owner; the switches are on nowhere but this proof's
processes. 33.4 §2 (groups onto a new day) waits for a decision on the
writer role's read. The group's whole-day pricing refusal (33.4 §1) is not
ported. Not reachable with the seed data, so covered by the code path and
the hand-on rule only: a closed school in a group, a duplicate refusal met
because of an earlier visit in the same group, a school with no district (a
day refusal after the row, which the ledger's savepoint rule follows), an
open notice on a ticked visit, lines in two weeks. No replayed month on a
sanitised restore. The web (Next.js) does not call this path.
