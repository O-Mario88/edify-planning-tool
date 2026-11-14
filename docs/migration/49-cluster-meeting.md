# 49. The eighth save in Go: scheduling a cluster meeting (M6)

M6 (04): cluster planning. A cluster meeting is planned from the same
drawer as a Group Training (38.1: `/planning/schedule-modal?cluster_id=…&action=meeting`,
`partials/planning/schedule_cluster_drawer.html`, posting to
`/planning/schedule-action`), and it goes down the same path: the view's
cluster branch, `activities.services._create` for a cluster, then
`cluster_attendance.set_invited_schools`. This piece extends 38's save
rather than writing a second one: the same transaction, lock, invitations,
day check and costs to follow, with the meeting's own item, kind, focus and
one more audit row.

**Where it stands (2026-11-13, agent 37).** Built and proved at the service
level in shadow (49.4): every step answered the same, every changed table the
same, the audit chain verifying. No new grant, role, view or lock was needed
(49.3). Wired into `internal/screens` behind
`EDIFY_GO_SAVES=schedule_cluster_meeting`, off by default and refused in test
and production; nothing calls it yet, for the same reason as the Group
Training (38.1, 38.5 §5: the app's drawer feed does not open the cluster
drawer).

## 49.1 What a meeting is, and how it differs from a Group Training

| | Group Training (38) | Cluster meeting (this piece) |
|---|---|---|
| `activity_type` | `cluster_training` | `cluster_meeting` (the drawer's hidden field, 121) |
| Item | the course posted as `catalogue_item_id`, governed | none posted: the view resolves `resolve_item_for_workflow_kind("cluster_meeting")` (2276–2287), on development the one **standard-support** item `STANDARD_CLUSTER_MEETING` ("Cluster Meeting", `any_ssa_intervention`, per school); none → "No single approved Activity Catalogue item costs this cluster activity. Ask the Country Director to configure it." |
| Kind | — | `meeting_kind` (owner, 2026-10-06): `training`, `only_meeting`, `cluster_leaders`; another value → "Choose the meeting type: Training, Only Meeting or Cluster Leaders Meeting." (view 2112, `_create` 2284); the column is written |
| Purpose | `focus_intervention` (the view's default) | `operational_admin` (the drawer's hidden field, 127) |
| Focus | the course's fixed intervention, `focusSource "course"` | the planner's `focus_intervention` (`focusSource "planner"`), else `plan_alignment.default_focus` over the invited schools' need: the weakest priority, `focusSource "ssa_default"` (2928–2958) |
| Recommendation | `recommend_cluster_activities` (governed) | standard support (3100–3123): "Standard field support targeting {Focus}." (or "Standard field support."), `engine standard_support`, `sourceSsaId null`, `verificationState none`, `context cluster` |
| No school ticked | refused: "Tick the schools this training is for." | the whole cluster (only a training is refused, 2405) |
| Ceiling | the officer's training ceiling for the course | none (only a Training meeting has a course) |
| After the save | `activity.scheduled` | `activity.scheduled`, then `activity.cluster_meeting_added_to_my_plan` (`_notify_scheduled_owner`, 3631–3646: owner, `monitoredBy`, partner, fy, `plannedDate`, `myPlanWeek`); nobody is told (the owner is the actor) |
| Answer | "Cluster activity scheduled. It is on your My Plan — keep planning." | the same |

Everything else is 38.3's path unchanged: the gate, the date, the
participants per school by category, the active members and invited count,
the materials, the scope (a cluster the person is responsible for), the
cluster need, `validate_context`, the cost preview and the day asked of the
relay, the cluster lock, the duplicate guard, `set_invited_schools`'
refusals (Champion, members only), a Core school invited (its package slot:
`CLUSTER_SESSION_TYPES` includes the meeting types, so `credit_cluster_session`
moves it) handed on, the day joined, one invitation per school, the open
recommendations, the costs to follow, the ledger mark, Django settling the
day.

## 49.2 Scope

- **Go's:** the owner's own staff meeting of kind `only_meeting` or
  `cluster_leaders`, with or without a focus the planner names (one of the
  eight SSA interventions), at a cluster they are responsible for, the item
  the standard per-school Cluster Meeting, the schools ticked by name and none
  of them Core, per school by category, Facilitated by Staff, on a day the
  pricing pools.
- **Handed on, unchanged:** a Training meeting (a course and its ceiling), no
  meeting type, no school ticked (the whole cluster), a partner facilitating
  or no "Facilitated by" field (the cluster's standing facilitator), a Core
  school ticked, a governed or not per-school meeting item, a focus that is not
  an SSA intervention, another purpose type, a responsible person named, a
  priority, a school, an acting seat or an asking, country, visit-only or
  summary role, and every hand-on of 38.8.

## 49.3 Built

| Piece | Where |
|---|---|
| Rules | `rules.json` `cluster_meeting` (the activity type, the meeting types, the meeting kinds, the training kind), exported by `export_schedule_visit_rules` (`cluster_meeting()`), drift test `apps/activities/test_schedule_visit_rules_export.py`. The view's and `_notify_scheduled_owner`'s words are literals in `cluster_meeting.go`, each with where it is said |
| The save | `internal/activities/cluster_meeting.go`: `ClusterMeetingRequestFromForm` (the meeting drawer's own fields only; the shared ones read by the Group Training's reader, so its hand-ons hold), `Service.ScheduleClusterMeeting` / `prepareMeeting` (the gate, the date, the kind, the ticks, the item resolved on today, the cluster), then 38's `createGroup` and `writeGroup` |
| Shared with 38 | `group_training.go`: `createGroup` takes a `session` (type, purpose, a training's course or a meeting's kind, focus and item); `sessionItemTaken` (a training's governed course, a meeting's standard item), `sessionFocus` (the course's, the planner's, or the SSA default); the ceiling read only for a course. `write.go`: the row's `meeting_kind`; `afterCommit` appends the meeting's audit row after `activity.scheduled` (`auditMeetingAdded`, a no-op for other types) |
| Writer role | nothing new: `meeting_kind` was already in the `activity` INSERT grant (`activities_roles.sql` 68), the item read is the visit save's, the rest is 38's |
| The switch | `config.GoSaves.ScheduleClusterMeeting`, named `schedule_cluster_meeting` (its own, not the Group Training's); `server.go` gives the screens service the save when it is on (`WithClusterMeetingSave`); `screens.ScheduleClusterMeetingInGo(form)` (`cluster_meeting_save.go`) answers in the feed's words or is not served. Nothing calls it |
| The shadow | `cmd/shadow/goplay` plays a posted meeting form through `ScheduleClusterMeeting`; the scenario `cmd/shadow/scenarios/cluster_meeting.json` |

No contract was added: nothing outside the gateway calls the save yet; the
RPC belongs with the app path (38.5 §5).

## 49.4 Proof in shadow (service level)

Copies `edify_shadow_s19_a` / `_b` made fresh from `edify_shadow_s19_base`
(`edify_gorn_dev` by `pg_dump`, the roles applied with `apply-roles.sh` after
the dump's schema owners were set to the development database's, and the week
of 30 November's request for `cceo@edify.org` set to `submitted`, as the other
saves' bases). Copy A through the existing application, copy B through Go with
a Django on 8219 over copy B for the day check and the settling; both copies'
Djangos with the SLO threshold set far out (38.9).

The scenario (16 steps, `[shadow-cm]`, `cceo@edify.org` unless named): A an
Only Meeting at C making a day (no focus: the SSA default); B a Cluster
Leaders Meeting at I joining it, Leadership named (off the cluster's
priorities); C A again (refused, identical); D the submitted week (refused);
E a past date; F no date; G an unknown meeting type; H nobody per school; I a
Champion school ticked at F (each refused); J a meeting at L with Financial
Health and a deviation reason; K a Training meeting at K (saved; for Go a
hand-on); L a cluster with Core schools (saved; a hand-on); M a partner
facilitating (saved; a hand-on); N nobody ticked at L (the whole cluster:
saved; a hand-on); O `cceo1@edify.org` opening cceo's cluster (refused at the
drawer); P one school ticked at F with materials.

The existing application against itself first (no Go,
`PYTHONHASHSEED=0`, `agent37_self.txt`): `0 of 20 changed tables differ`.
Then the proof (`agent37_shadow_run.sh`, `agent37_run1.txt`), last lines
exactly as printed:

```
16 steps on edify_shadow_s19_a: 8 answered ok, 8 refused
0 of 16 steps answered differently
goplay exit 0
366 tables, 20 changed by the runs
0 of 20 changed tables differ
shadow exit 0
verify_chain {'ok': True, 'brokenAt': None, 'checkedRows': 19517, 'fromSeq': None}
```

Eleven steps were Go's (A, B, C, D, E, F, G, H, I, J, P: four saves, seven
refusals); five were handed on (K, L, M, N, O). `activity` (10 rows written on
each), `cluster_activity_attendance` (21), `audit_log` (37, with eight
`activity.cluster_meeting_added_to_my_plan` rows on each copy),
`domain_event_log` (37), `daily_visit_batch` (4), the cost snapshot, cost
lines, advance, fund-request, weekly request, transport and ledger tables are
the same.

**The earlier saves, re-run on this branch** (they share `createGroup`,
`writeGroup` and the row writer), same copies and harness:

- group_training (`agent37_run_group_training.txt`): `13 steps on
  edify_shadow_s19_a: 5 answered ok, 8 refused`, `0 of 13 steps answered
  differently`, `goplay exit 0`, `366 tables, 17 changed by the runs`, `0 of
  17 changed tables differ`, `shadow exit 0`, `verify_chain {'ok': True,
  'brokenAt': None, 'checkedRows': 19497, 'fromSeq': None}`
- schedule_visit (`agent37_run_schedule_visit.txt`): `15 steps on
  edify_shadow_s19_a: 10 answered ok, 5 refused`, `0 of 15 steps answered
  differently`, `goplay exit 0`, `366 tables, 19 changed by the runs`, `0 of
  19 changed tables differ`, `shadow exit 0`, `verify_chain {'ok': True,
  'brokenAt': None, 'checkedRows': 19505, 'fromSeq': None}`
- training_pair (`agent37_run_training_pair.txt`): `18 steps on
  edify_shadow_s19_a: 10 answered ok, 8 refused`, `0 of 18 steps answered
  differently`, `goplay exit 0`, `366 tables, 19 changed by the runs`, `0 of
  19 changed tables differ`, `shadow exit 0`, `verify_chain {'ok': True,
  'brokenAt': None, 'checkedRows': 19519, 'fromSeq': None}`

## 49.5 Tests

`internal/activities/cluster_meeting_test.go` (the form Go takes and every
hand-on; the kind, focus and purpose as the view reads them; the planner's
focus, the SSA default and none; which items Go takes for a meeting and a
training); `internal/screens/cluster_meeting_save_test.go` (served only with
the switch, a Group Training's form not taken, a hand-on forwarded, a refusal
in the existing words); `internal/config/go_saves_test.go`
`TestTheClusterMeetingSaveIsOffUnlessNamed`; integration
`TestTheWriterRoleMakesTheClusterMeetingsWritesAndNoMore` (the meeting with
its kind and an invitation inserted, its kind, cluster and type not
changeable) and `TestTheGoClusterMeetingIsOffByDefaultAndRefusedInProduction`,
with 38's integration tests and `TestGatewayRoleCanNeitherWriteNorReadSecrets`
passing on `edify_gorn_a19_test`. `gofmt`, `go vet ./...`, `go test -race
./...`, ruff, format, bandit and the drift test pass.

## 49.6 Not done

The app path (38.5 §5) and a contract for it; a Training meeting (its course,
ceiling and the course stamped beside the meeting's item, `_create`
3466–3497) stays Django's; switching the Django save off and any cutover wait
for the owner. Not reachable with the seed data, so covered by the hand-on
rules and unit tests only: a governed or several standard meeting items, a
meeting item that is not per school, a cluster whose invited schools have no
assessed SSA (no default focus), open recommendations at the invited schools.
Nothing was written to `edify_gorn_dev`; every save was made on
`edify_shadow_s19_a` / `_b`.

## 49.7 Merged with the online Group Training (doc 48)

Both saves reworked 38's group save. After the merge, `groupPlan` holds
`courseID` (blank for a meeting: no ceiling is read) and 48's `ceilingFY`
(the year `_create` counts the ceiling in, which an online session's row
later leaves for its planned day's year). `createGroup` takes 49's `session`
and keeps 48's online branch (no preview, no day, the UGX 0 revision). The
merge also let `delivery_mode` into the meeting drawer's own fields, because
they are built from the Group Training's. That would have sent an online
meeting down the online training path. `delivery_mode` is now left out of
`meetingFormFields`, so an online meeting is handed on. The unit test's
"online delivery" case failed before this fix and passes after it.

Re-proved at the service level on `edify_shadow_s22_a` / `_b`, made fresh
from a base remade with the fixed `copies.sh base` and `apply-roles.sh`
applied to that base only. Django ran on 8284 for copy B. Every run printed
`goplay exit 0`, `shadow exit 0` and `verify_chain` ok:

| Scenario | Steps | Answered differently | Changed tables differ | Go's steps | Handed on |
|---|---|---|---|---|---|
| cluster_meeting | 16 | 0 | 0 of 20 | 11 | 5 |
| online_training | 15 | 0 | 0 of 17 | 11 | 4 |
| group_training | 13 | 0 | 0 of 17 | 9 | 4 |
| schedule_visit | 15 | 0 | 0 of 19 | 12 | 3 |
| training_pair | 18 | 0 | 0 of 19 | 15 | 3 |

The first group_training run showed 1 of 17 tables differing: `user`, in
`online_since` only. Presence restarts a sitting when `last_seen_at` is older
than `ONLINE_WINDOW` (`apps/accounts/presence.py`). Copy A's first request
landed inside the window from the base's dump, and copy B's handed-on step
landed after it. The difference came from the clock, not from the save. The
re-run printed 0 of 17.
