# 31. The fourth save in Go: editing a scheduled school visit

M5 (04): "schedule, reschedule, cancel, edit while scheduled … Each write
appends the same audit and timeline rows as today." The owner's rules for
Edit (2026-10-02, 2026-10-07): only work still on the plan is edited; a new
day asks for a reason; a new project goes through the scheduling funnel.
This piece follows 29's and 30's decisions: read-only checks before Go's
transaction, the costs and the money left to Django, an acting seat handed
on, and the writer role kept to the columns the save writes.

**Where it stands (2026-11-12).** Mapped (31.3) and measured (31.2); the
contract, the writer role's two columns, the Go edit and the app's switch
are built and proved in shadow at the service and the app level (31.5,
31.6). Nothing is switched on outside this proof's own processes.

## 31.1 Scope

- **In:** one scheduled staff school visit of the first save's kind (a
  `purpose_type` among the six, its activity type the purpose's, a school, no
  cluster, project, partner, pair or end date, never begun), still
  `scheduled` or `rescheduled`, edited by its own owner at a school in their
  own portfolio that is not a Core school, from My Plan's Edit drawer
  (`/my-plan/{id}/edit-drawer` posting to `/my-plan/{id}/edit`; the app
  reaches it through `PageDrawerService.SaveDrawer`, as 29.7 and 30.8), when
  the edit changes only its **goal** (`activity_purpose_text`) and its
  **expected outcome**, the day, school, purpose and focus posted as they
  are. Go also makes this case's three refusals: a day that does not exist
  ("Invalid date: …"), a new day with no reason, a new purpose with no
  reason.
- **Handed on, unchanged** (the gateway forwards the request whole): a new
  day with a reason (it is the move, `services.reschedule`, with its money);
  another school (cancel and schedule again, `_schedule_again`); another
  purpose with a reason (`purpose_change`, which may re-price); another
  focus intervention (`plan_alignment.rejudge` rewrites the SSA verdict and
  releases or links recommendations: columns the writer role does not hold);
  a project, a training, a facilitator, an end date, an invitation list, a
  training named for the visit, a name posted twice; the In-school Training
  pair, Core package visits, partner work, cluster sessions; another
  person's activity (the view's doors and their rows); a person in an acting
  seat or an asking role; a date in a form other than `YYYY-MM-DD`.

## 31.2 What one edit writes (measured, 2026-11-12)

`cmd/shadow/scenarios/edit_visit.json` (21 steps, `[shadow-e]`): five visits
scheduled (A–E), E moved first; then edits of the goal and outcome (A), the
outcome alone (B), the goal of a moved visit (E), a day that does not exist
(C), a new day with no reason (C), a new purpose with no reason (D), A edited
again, D saved as opened; then the hand-ons: a new day with a reason (C), a
new focus (D), another school (B), another purpose with a reason (D), the
training-and-visit pair (`cmwclue57008yjsdhhc9v`), a Core school's visit
(`cmwd518kt00mo8bdhhc6v`), and another officer opening a visit's drawer
(`cmwd2x86z008h5khkdjob`, refused at the drawer).

Measured through the existing application only: the first 14 steps on copy
A, the first 6 on copy B, compared (`agent14_measure2.txt`):
`14 steps on edify_shadow_a: 11 answered ok, 3 refused`,
`366 tables, 18 changed by the runs`, `4 of 18 changed tables differ`. The
four are the edits' own:

| Table | Row | Written by |
|---|---|---|
| `activity` | UPDATE of `activity_purpose_text` and `expected_outcome` as posted (stripped), and `updated_at`; nothing else of the row | `services.patch_activity` 6861 (`save(update_fields=…)`) |
| `audit_log`, `domain_event_log` | `edit_activity`, `success true`, payload `{"fields": the edit's keys for what was posted, sorted (e.g. activityPurposeText, expectedOutcome, focusIntervention, purposeTrainingCourseId, purposeType, scheduledDate, schoolId), "reason", "result_activity_id"}`, the actor's role, ip, agent, correlation; a refusal: `success false`, `reason` its words, no payload | the view (`my_plan_views.py` 2672–2700), `audit.services.log` |
| `user` | the person's `last_seen_*` (the existing application's own requests; noise for a Go save, kept equal by ordering the scenario's handed-on steps last) | the request middleware |
| `target_ledger_dirty` | (owner, FY of the day) on commit, for credited types: an upsert that only moves `marked_at`, so it compares the same | `ledger_sync._changed` (post_save) |

No day, cost line, fund request or timeline row changes, and no notice is
written. The activity's save also says `plan.changed` on the realtime
stream (`live._activity_changed`, post_save, on commit): a cache stamp, no
row.

## 31.3 The path, line by line (this branch, aea45912c)

**The drawer and the view** (`apps/frontend/views/my_plan_views.py`):

| Step | Lines | What it does for this case | Go |
|---|---|---|---|
| Drawer | 2584–2618 | `edit_activity_drawer_view`: record gate, `edit_state` ("open" for own scheduled staff work) | the drawer and its form request are Django's (31.6) |
| Page gate | 2621 | `require_page_permission("my_plan")` | as above |
| Record gate | 2626–2639 | `can_view_record`; refused: `unauthorized_mutation_attempt` row and 403 "Access Denied: You do not have permission to edit this activity." | own activity only; anything else handed on |
| Fields | 2643–2666 | `reason` (stripped, always a key); `scheduled_date`/`end_date` only when non-blank; every other name whenever posted, stripped; the checklist only with `invited_schools_shown` | `EditRequestFromForm`: only 31.1's names, each once, stripped as Python strips |
| Refusal | 2673–2683 | any exception: `edit_activity` failure row, then `error_fragment(exc, action="Activity not saved", 400)` ("Activity not saved: {words}") | the same row on the chain, the same words |
| Audit | 2685–2698 | `edit_activity` success row, payload as 31.2 | the same row after commit |
| Answer | 2699 | `saved_in_place()`: "Saved. Press Refresh to see it on the page." | the same (`rules.json` `move.savedMessage`) |

**The edit** (`apps/activities/editing.py`, `edit` 215–540):

| Step | Lines | Reads / refuses | Go |
|---|---|---|---|
| Gates | 270–273 | `_get_for_execution` ("Activity not found."), `_assert_may_schedule`, `_assert_not_awaiting_owner`, `assert_editable` (executed, partner, status) | own scheduled/rescheduled visit of the six, else hand on |
| Day | 275–287 | `_parse_date(scheduledDate)` → "Invalid date: {value}"; `local_day` against `planned_date` | `YYYY-MM-DD` parsed in Kampala (no such day: the refusal); another form handed on |
| School | 289–311 | another school: `may_move_school`, `movable_schools`, "Choose a school in your own portfolio …" | another school handed on |
| Project | 311–326 | project work only | posted project handed on |
| Reasons | 328–333 | a new day with no reason: "Give the reason the date is changing." (school and project reasons follow) | refused in the same words; with a reason handed on |
| Focus | 335–368 | `catalogue_sets_intervention`, `_clean_focus`; unchanged → dropped | a different focus handed on |
| Training | 368–376 | `trainingCourseId` | posted training handed on |
| Purpose | 380–394 | another purpose with no reason: "Give the reason the purpose of this visit is changing." | refused in the same words (only when no day moved and the school is the same); with a reason handed on |
| Paired | 395–428 | In-school Training purposes, a named training | a named training handed on |
| Facilitator, invitations | 430–443 | trainings and cluster sessions | posted fields handed on |
| Block | 445–538 | `planner_change`, `transaction.atomic`; the money branch only for a day, school, project, training, facilitator, invitation or priced purpose change | none of these is Go's |
| Patch | 519–520 → `services.patch_activity` 6792–6879 | `_get_for_execution` again; the goal and outcome set when posted; `save(update_fields=[…, "updated_at"])` (no cost driver, no focus: no re-price, no `rejudge`) | one UPDATE under the row's lock (`FOR UPDATE`; the visit changed since the read → handed on); nothing posted, nothing saved |
| Model save | `models.py:578` | `BESIDE_THE_PACKAGE_FIELDS` covers the two text fields: no Core slot work | — |
| Signals | `ledger_sync._changed`, `schedule_trail` (no day or status change: nothing), `live._activity_changed`, `ssa/signals` (status not settling) | the ledger mark on commit; `plan.changed` | the same upsert after commit; the announcement asked of Django (31.4) |
| Answer | 540 | `get_activity` (a read) | — |

## 31.4 Decisions

1. **The writer role's two columns.** The edit needs `UPDATE
   (activity_purpose_text, expected_outcome)` on `activity`, which the
   writer role did not hold (it held the move's eleven columns). They are
   free text, not money, lifecycle, ownership or the SSA verdict, and
   `dbguard.protectedColumns` does not name them, so the guard is
   unchanged. Granted in `activities_roles.sql` (appended), applied
   additively to `edify_shadow_base` and `edify_gorn_test` only.
   *Flagged for the coordinator:* if a new UPDATE column on `activity` counts
   as a rule change, this is the one to approve.
2. **The live announcement.** An edit has no costs to follow, so 27.9's
   settling door (which announces) is never asked. A third small door,
   `POST /api/auth/internal/activity-changed` (beside the others in
   `gateway_relay.py`, behind the internal key, writing nothing), calls the
   existing `live.announce_activity` once Go's edit has committed, as the
   existing save's commit does.
3. **Not taken: a new focus.** `rejudge` rewrites the activity's
   `recommendation_source`, `ssa_alignment`, `source_ssa*`,
   `recommendation_reason`, `focus_intervention`, `purpose_intervention` and
   `ssa_recommendation_id`, releases planned recommendations (UPDATE and
   their audit rows) and links new ones. Taking it would grant those
   columns, a decision for the owner; it is handed on.

## 31.5 The edit, built and proved in shadow

| Piece | Where |
|---|---|
| Contract | `ActivityService.EditSchoolVisit` in `edify/activities/v1/activities.proto`: the drawer's fields as `optional string` (a field not posted is unset, as the audit row's `fields` needs), the reason; the edited activity (id, status, goal, outcome, the toast's words) or the refusal's words. `buf lint`, `buf format --diff --exit-code`, `buf breaking` against `origin/feature/edify-go-rn-migration` and against this branch's head pass; Go, web and app generated code regenerated with the coordinator's pinned generators (only the activities files changed). Nothing implements or calls the RPC |
| The edit | `internal/activities/edit.go` (`Service.Edit`, `EditRequestFromForm`): 31.3 in its order. Before the transaction: the hand-ons, the scope, the three refusals (with the view's failure row). One read-write transaction: the row's lock, unchanged since read, the UPDATE of what was posted. After commit: the ledger mark (credited types), the announcement, the `edit_activity` row with the leave-cover stamp |
| Announcement | `HTTPPricing.Announce` → `activity-changed` (31.4 §2) |
| The shadow's Go half | `cmd/shadow/goplay` plays a step opening `/my-plan/{id}/edit-drawer` through `Service.Edit` |

**The run** (copy A through the existing application, copy B through Go,
Django on 8196 over copy B; `agent14_shadow1.txt`), last lines exactly as
printed:

```
0 of 21 steps answered differently
goplay exit 0
366 tables, 22 changed by the runs
0 of 22 changed tables differ
shadow exit 0
verify_chain {'ok': True, 'brokenAt': None, 'checkedRows': 15973, 'fromSeq': None}
```

Steps 7–14 were Go's (five edits, three refusals), and Go's reschedule made
step 6; steps 15–20 were handed on (new day, focus, school, purpose, the
pair, the Core visit), step 21 refused at its drawer on both. Django on B
answered five `activity-changed` requests, one per Go edit. The first run
passed; nothing needed fixing.

## 31.6 The app's Edit save reaches Go (behind a switch, development only)

The app is unchanged: it reads `/my-plan/{id}/edit-drawer` with
`PageDrawerService.GetDrawer` and saves it with `SaveDrawer(path, values)`.
With `EDIFY_GO_SAVES=edit_visit` the gateway (`internal/screens/edit_save.go`)
asks the existing application for the form (`POST
/api/mobile/v1/drawer?form_only=1`; `DrawerFeedView` now gives a form for
the edit's save, `FORM_ONLY_SAVES`, and saves nothing); then as 30.8: a
form refusal is answered as is; a form Go does not take, a hand-on or an
acting seat is forwarded whole; a Go edit answers `{saved: true, message:
"Saved. Press Refresh to see it on the page. ×"}`; a Go refusal `{saved:
false, error: "Activity not saved: {words}"}`; a failure before the edit
`Unavailable`, nothing written. An edit is never made by both.

`config.GoSaves.EditVisit`, named `edit_visit`: off unless named, refused
in test and production, needing the existing application's address and
internal key. It has been on only in this proof's gateway (8097).

**The proof at the app's level** (`cmd/shadow/appplay` plays an Edit step as
the app does, `drawerLogic.ts`: every field's value as the drawer gives it,
the step's choices over them, only the fields shown sent): copy A through
gateway 8096 (switch off) over Django 8196 on `edify_shadow_a`, copy B
through gateway 8097 with `EDIFY_GO_SAVES=edit_visit` over Django 8197 on
`edify_shadow_b`. On B Django served 14 form-only requests and 5 forwarded
drawer saves (the move and the four hand-ons that reached a save); Go made
the other 10. Last lines exactly as printed (`agent14_app_shadow1.txt`):

```
0 of 21 steps answered differently
compare exit 0
366 tables, 19 changed by the runs
0 of 19 changed tables differ
shadow exit 0
verify_chain {'ok': True, 'brokenAt': None, 'checkedRows': 15965, 'fromSeq': None}
```

(The script's "forwarded drawer saves" line printed 0, as in 30.8: its
pattern does not match this server's log; the 5 are counted from the log.)

**Found in the existing app, reproduced, not fixed (both copies alike):**

1. **The app's Edit drawer blanks the expected outcome.** Its
   `expected_outcome` field arrives with an empty value (the goal's arrives
   filled), so saving the drawer from the app writes `''` over the visit's
   expected outcome unless the person retypes it: C, D and E ended with
   `expected_outcome = ''` on both copies. The web drawer keeps it. Go
   writes what the form posts, as the existing save does.
2. **The app's Edit drawer has no reason field** (the web's reason is an
   `x-if` template shown only when the day, school, project or purpose
   moves), so from the app a new day, school or purpose is always refused
   ("Give the reason …"): steps 15, 17 and 18 at the app level.

Both are the existing application's behaviour, for the owner to decide.

**Tests.** `internal/activities/edit_test.go` (the form taken only for
31.1's fields; the audit row's keys; each refusal and hand-on in the edit's
order; the hand-ons before any read; Python's strip);
`internal/screens/edit_save_test.go` (forwarded while off; Go takes the
edit with the form's fields and origin and forwards nothing; hand-on,
another drawer, a save elsewhere, a non-text form, a project field
forwarded; the refusal's words; a failure); `internal/config/go_saves_test.go`;
integration `TestTheActivitiesWriterRoleMakesTheEditsWrite`,
`TestTheGoEditIsOffByDefaultAndRefusedInProduction`, and
`TestGatewayRoleCanNeitherWriteNorReadSecrets` now also refusing a visit's
focus, purpose and SSA verdict; Django `test_gateway_relay` (the
announcement's door closed without the key and refusing a bad id).

## 31.7 Not done

Switching the edit off in Django in the same release (03 §3.7) and any
cutover wait for the owner; the switch is on nowhere but this proof's
processes. A new focus, day, school or purpose through Edit stays Django's.
Not reachable with the seed data, so covered by the code path and the
hand-on rule only: a visit changed between the read and the lock, an edit
posting neither text field, a person on leave cover (the stamp). The
form-only door for the edit has no Django test of its own (DB-backed); the
app-level run proves it. No replayed month on a sanitised restore.

**Settled by the coordinator, inside the owner's rules (2026-11-12).** The
writer role's `UPDATE (activity_purpose_text, expected_outcome)` on
`activity` stands: free-text columns the guard does not protect, the
minimum the edit needs, no rule changed. Focus changes stay handed on (their
SSA re-judging writes columns the role does not hold). The `activity-changed`
door only announces `plan.changed`, the pattern of the costs-to-follow relay.

**Merged and re-proved on the merged branch (2026-11-12)**, every save's
scenarios from fresh copies:

| Save | Level | Steps answered differently | Changed tables differing | verify_chain |
|---|---|---|---|---|
| Schedule | service | 0 of 15 | 0 of 20 | (not run by this script) |
| Schedule | app | 0 of 15 | 0 of 19 | ok, 15,962 rows |
| Reschedule | service | 0 of 19 | 0 of 22 | ok, 15,978 rows |
| Reschedule | app | 0 of 19 | 0 of 19 | ok, 15,976 rows |
| Cancel | service | 0 of 19 | 0 of 17 | ok, 15,972 rows |
| Cancel | app | 0 of 19 | 0 of 14 | ok, 15,970 rows |
| Edit | service | 0 of 21 | 0 of 22 | ok, 15,973 rows |
| Edit | app | 0 of 21 | 0 of 19 | ok, 15,965 rows |

Race, the integration suite, ruff, format, bandit, the relay tests and the
generated-code check pass.

**Found, to fix before the app ships (not a Go difference):** the app's Edit
drawer arrives with the expected outcome blank, so saving it writes `''` over
the stored outcome unless the person retypes it, and it has no reason field,
so the app cannot change a visit's day, school or purpose through Edit. The
web's drawer keeps both. The fix belongs to the drawer the app is given.
