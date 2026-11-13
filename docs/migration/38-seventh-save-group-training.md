# 38. The seventh save in Go: scheduling a cluster group training (M6, mapped)

M6 (04): cluster planning moves after the visit saves. Scheduling a Group
Training for a cluster is one decision that writes the session, an invitation
for each school ticked, and (at a cluster with Core schools) a training slot in
each invited Core school's package. This piece follows 27.8, 29.4, 30.4 and
32.4: the pricing's refusals asked of the read-only Django check before Go's
transaction, the costs to follow written by Go and settled by Django after
commit, an acting seat handed on, the writer role kept to exactly what the save
writes.

**Where it stands (2026-11-13, agent 24).** Mapped (38.3) and measured (38.2);
the coordinator decided 38.5's six questions (38.5, "Decided"); the writer
role's additions, the cluster lock, the Go save, its rules and its switch are
built (38.8); the service-level shadow proof answers every step the same and
leaves every changed table the same, the audit chain verifying (38.9). The
app does not reach the save (38.1): it is wired into `internal/screens`
behind `EDIFY_GO_SAVES=schedule_group_training`, off by default and refused
in test and production, for the app or the web to call later. The role and
lock are applied to this agent's shadow copies and integration database
only; production needs the owner's approval at cutover like every role
change.

## 38.1 Which drawer the Clusters page opens

The brief names `/clusters/schedule-training-drawer`
(`cluster_views.schedule_training_drawer_view` → `planner_drawer_view`,
`partials/clusters/cluster_action_planner_drawer.html`, posting to
`/clusters/schedule-activity`). That is the **retired** second drawer: no
template opens it (owner, 2026-09-17, "use the same cluster meeting planning
drawer … everywhere there is cluster planning";
`apps/frontend/test_one_cluster_drawer.py` asserts it). Every live entry point
— the Clusters page's buttons and each card's Actions menu (Django's templates
and Go's `internal/clusterpage/page.go` 37 and 234), a cluster profile, a
Planning row — opens **`/planning/schedule-modal?cluster_id=…&action=training`**
(`planning_views.schedule_modal_view` 1409, cluster branch 1430–1590,
`partials/planning/schedule_cluster_drawer.html`), whose form posts to
**`/planning/schedule-action`** (`schedule_action_view` 1986). This map is of
the live drawer. Both views end in the same `activities.services.create`, and
the measured rows (38.2) are the same shape through either.

**The app does not save this drawer today.** The app opens the cluster's
"Schedule Group Training" through the generic drawer feed (`PageScreen.tsx`
`openLink`: a `/planning/schedule-modal` link with no `school_id` is not a
planning drawer). `apps/mobile_feed/views.py` `DRAWER_VIEWS` does not name
`planning_schedule_modal` and `DRAWER_SAVES` does not name
`planning_schedule_action`, so the feed answers 404 and the app opens the page
on the web (`WebDrawer` `onUnavailable` → `webPageFor` → `/my-plan?cluster_id=…`).
There is no app path for Go to take over yet (38.5 §5).

## 38.2 What one group training writes (measured, 2026-11-13)

`cceo@edify.org`, Cluster C (six client schools, three of them
Partner-supported and so unticked by default), Leadership, 26 November 2026,
2 teachers and 1 leader per school, on a fresh copy, with the settling thread
held (`_when_the_save_commits` stubbed, as 30.2) to read the save's own rows
(`agent22_m3`):

| Table | Rows | Written by |
|---|---|---|
| `activity` | one: `activity_type cluster_training`, `cluster_id`, no school, `planning_source cluster_planning`, `activity_context_type cluster`, the course as the catalogue item (`activity_name_snapshot` its name, `costing_profile_snapshot CLUSTER_TRAINING`, `evidence_profile_snapshot TRAINING_ATTENDANCE`, `salesforce_activity_type training`), `focus/purpose_intervention` the course's fixed one, `teachers/leaders/other_per_school`, `participants_per_school` 3, `cluster_school_count_snapshot` 6, `schools_invited` 3, `expected_participants` 9 (3 × 3, recomputed), the purpose text and outcome, its **day's batch** (a cluster training is pooled into the officer's day like a visit), `recommendation_source` from the **cluster recommendation engine** (`engine apps.ssa.recommendation_engine`, `sourceSsaIds` of every member, `verificationState`, and the cluster SSA verdict under `ssa` with `focusSource "course"` and the invited schools' `cluster` block), `ssa_alignment` | `_create` 3371, `apply_catalogue_snapshot` 3453, `plan_alignment.stamp` 3521 |
| `cluster_activity_attendance` | one per ticked school: `invited true`, the per-school teachers/leaders/other, `recorded_by` the actor's user id; a serial id | `set_invited_schools` (`cluster_attendance.py` 110) |
| `daily_visit_batch` | the day made with its defaults when the officer has none (else joined) | `attach_activity_to_batch` |
| `daily_visit_costs_to_follow` | one: `steps.days = [[batch, owner]]`, `together false` | `costs_follow` |
| `audit_log`, `domain_event_log` | `activity.scheduled`, the eleven-key payload with `cluster_id` set and `school_id` null | `_create` 3568 |
| `target_ledger_dirty` | (owner, FY) on commit | `ledger_sync` |
| `core_activity_slot` | **at a cluster with Core schools only**: each invited Core school's next training slot in its package for the session's FY takes the session (`activity_id`, `owner staff`, `assigned_staff_id`, status, `scheduled_for`) | `Activity.save` → `cluster_credit.credit_cluster_session` (models.py 605–612), again from `set_invited_schools` |

Then the pricing that follows (Django's, settled after commit): the session's
cost snapshot and lines (venue, meals, facilitation, the day's travel share),
the day's figures, the week's and month's requests, advance and fund-request
rows. Measured at Cluster A (seven members, three Core, five ticked; pricing
allowed to follow; `agent22_m4`): `366 tables, 15 changed by the runs`, among
them `core_activity_slot` (2 rows changed) and `cluster_activity_attendance`
(5 rows).

## 38.3 The path, line by line (this branch, a5a168f3b)

**The view** (`apps/frontend/views/planning_views.py`, `schedule_action_view`):

| Step | Lines | What it does for a group training |
|---|---|---|
| Gate | 1987 | `_may_open_schedule_drawer`; refused: 403 with `_no_scheduling_permission_message` |
| Fields | 1993–2042 | `activity_type cluster_training`, `cluster_id`, the course in `catalogue_item_id`, the per-school categories, materials, `activity_goal`, `expected_outcome`, `executor_type`/`delivery_type` (staff), `facilitating_partner_id` (blank = Staff) |
| Date | 2061–2072 | blank / unparsable: 27.6's words (400) |
| Course | 2078–2104 | no course → "Select the Training to deliver."; `validate_priority_training_selection(…, CLUSTER)`: not a governed cluster course → "Select a training from the governed Training Catalogue."; `_training_focus`: the course's fixed intervention wins, a posted one is read only for a course linked to none |
| No item | 2276–2287 | not reached (the course is the item) |
| Payload | 2355–2378 | `clusterId`; online delivery → `programmeDeliveryMode online`; `responsibleStaffId` only for a PL, Admin or IA |
| Invited | 2396–2415 | ticked ids → `invitedSchoolIds`, `schoolsInvited`; the checklist shown and nothing ticked → "Tick the schools this training is for." |
| Facilitator | 2441–2449 | `facilitating_partner_id` always posted by this drawer: blank is Staff; a partner is a facilitator, **not an assignment** (owner, 2026-09-29) |
| Route | 2474–2475 | `planning.services.schedule_cluster_activity` (1124: kind and cluster checked, `requireCatalogue`) → `activities.services.create` |
| Answer | 2476–2528 | "Cluster activity scheduled. It is on your My Plan — keep planning." with the My Plan link and `_ceiling_notice`; filed against somebody else: "… scheduled onto {name}'s My Plan, because …" |
| Refusal | 2529 | `error_fragment(e, 400)`: the exception's words |

**The create** (`apps/activities/services.py`, `create` 2170 → `_create`):

| Step | Lines | Reads / refuses for this case |
|---|---|---|
| Item | 2254 | `get_selectable_item(course, day)`; `workflow_kind cluster_training` |
| Course focus | 2295–2318 | the course is the scheduled training; `intervention_for` fixes the focus, `focus_source "course"` |
| FY, period, past date | 2338–2359 | 27.6's (UTC FY, Kampala's day) |
| Participant mode | 2393–2410 | `_participant_mode_for` / `_apply_participant_mode` |
| Participants | 2423–2459 | `_validated_per_school_categories` (each a whole number; words at 1989–2033), `active_school_count` (none → "This cluster has no active schools, …"), `_validated_schools_invited` (≥1, ≤ members), `expectedParticipants = per school × invited` |
| Materials | 2461 | `_validated_materials` (blank → none; whole, non-negative, ≤ 1,000,000) |
| Scope | 2578 | `_assert_target_in_scope`: visit-only roles refused cluster work (`refuse_cluster`); country scheduling roles pass; else the cluster in the person's **direct** portfolio; a supervisor → `OVERSIGHT_ONLY_MESSAGE`; else "Activity target outside your scope." |
| Entitlement | 2597 | `_assert_schedule_entitlement` with no school: nothing for a group training |
| Facilitation | 2620–2650 | `_facilitating_partner_for` / `_requested_facilitator` (a named partner, checked active); a drawer that never asked → `clusters.facilitation.default_facilitator_id` (the cluster's standing facilitator, owner 2026-10-02) |
| District type | 2708–2725 | the cluster's district, primary or secondary for the officer (`district_type_for_staff`) |
| Calendar | 2744 | 27.6's (off while `CALENDAR_BLOCKS_REFUSE = False`) |
| SSA need | 2847 | `plan_alignment.cluster_need(cluster, invited)` (plan_alignment.py 258) |
| Catalogue rules | 2960–2975 | `validate_context(cluster=…)`, `validate_frequency(cluster=…)` |
| Recommendation | 3041–3100 | **every active course is governance-gated** (`standard_support` false for all 21 on development): `recommend_cluster_activities` (activity_catalogue/services.py 946–1184) ranks each member's need with the school engine and merges them; the matching row's reason ("6 Cluster member School(s) have verified Leadership need.") and its school contexts' SSA ids are recorded |
| Pricing gate | 3137–3165 | `costing_service.preview` blockers; missing participants → "Enter the planned participant count in the activity drawer before scheduling." |
| Lock | 3207, 3232 | `Cluster … select_for_update()` (the cluster row) |
| Ceiling, no names | 3234–3254 | `assert_schools_named` (only when nothing is invited) |
| Duplicate | 3297–3315 | identical session that day for the cluster → "An identical activity is already scheduled for this target on this date. …"; the client and Core same-day tests take no school here |
| Row | 3371–3442 | `cluster_id`, the participant and materials columns, `planning_source cluster_planning` |
| Snapshot | 3453 | `apply_catalogue_snapshot` |
| Invitations | 3509–3516 | `set_invited_schools`: members only (else "Only schools in this cluster can be invited …"), **no Champion school** ("Champion schools receive no cluster training or meeting, …"), `reserve_for_session` under the officer's **training ceiling** (a school counts once per training, owner 2026-10-08; a no-op with no ceiling: development has none), one row per school, then `credit_cluster_session` |
| Verdict | 3521 | `plan_alignment.stamp` (the cluster block) |
| Day | 3557–3561 | `costs_follow` around `_apply_schedule_cost_snapshot` → `_price_activity` → `attach_activity_to_batch` (a cluster training is `batch_poolable`) |
| Core slots | models.py 605–612 | `credit_cluster_session`: invited Core schools' training slots, on the staff half while it has room (`package_split`); a package made if none (`ensure_core_plan`) |
| Audit, tell, hand-over | 3568, 3600–3605 | `activity.scheduled`; nobody told (the owner is the actor); `_ensure_partner_handover` does nothing (no assigned partner); a facilitator is told (`_tell_facilitating_partner`) |

Owner rules met on the path, all on the existing side and kept by any port: a
partner facilitating is not an assignment (step L of the scenario: staff
delivery, the partner as `facilitating_partner_id`, no `partner_assignment`
row); a training ceiling counts schools, a school once per training
(`reserve_for_session`); a group training is training coverage and is "Group
Scheduled", never "Scheduled" (read by the pages, nothing the save writes).

## 38.4 Proposed scope (not built)

- **In:** the owner's own staff Group Training from the live drawer, at a
  cluster in their direct portfolio whose ticked schools include **no Core
  school** (so no package slot moves), for a governed course, Facilitated by
  Staff, in person, with no project, priority allocation or ceiling set for the
  officer and course this year, a day the pricing pools.
- **Handed on, unchanged:** a cluster session inviting a Core school (38.5 §3),
  a partner facilitating (the fee and the facilitator's notice) or a cluster's
  standing facilitator, online delivery, partner and agency delivery, cluster
  meetings, project work, a ceiling set, a person in an acting seat or an
  asking role, a PL/Admin/IA naming another person.

## 38.5 What stops the save: decisions needed

1. **Writer-role rights (stop condition).** Go cannot write this save as
   `edify_activities_rw` today. It would need, at least:
   `INSERT (cluster_id, expected_participants, participants_per_school,
   cluster_school_count_snapshot, schools_invited, teachers_per_school,
   leaders_per_school, other_per_school, printing_pages, photocopy_pages,
   photocopy_copies) ON activity`; `INSERT (activity_id, school_id, invited,
   attended, is_guest, teachers, leaders, other, recorded_by, created_at,
   updated_at) ON cluster_activity_attendance` with `USAGE` on its id
   sequence; and the reads of the cluster, its members' partner support, the
   cluster recommendation engine's tables and the ceiling's counts. None is
   granted (the brief: stop and report). `activity.cluster_id` is already in
   `dbguard.protectedColumns` (insert, never change), so an INSERT right fits
   the guard as it stands.
2. **The cluster row lock.** `_create` holds `SELECT … FOR UPDATE` on the
   cluster (3232) so two saves cannot both pass the duplicate test. As for the
   school (27.8 §2), Postgres takes a row lock only for a role with an UPDATE
   right on the table; the pattern would be a second narrow function,
   `gateway_lock.lock_cluster(id)`, owned by a NOLOGIN role holding
   `UPDATE (updated_at)` on `cluster` only. A new database object: the owner's
   approval for production, as `lock_school`'s.
3. **Core package slots.** At a cluster with Core schools the save itself moves
   `core_activity_slot` rows (and may make a `core_plan`). Proposed: hand those
   sessions on (no right needed; Clusters C, I, K and L of the seed have no Core
   school, so the scope is reachable). Porting the credit means UPDATE rights on
   the slot's lifecycle columns, which the guard does not allow today.
4. **The invitations' order is random in the existing application.**
   `set_invited_schools` inserts in the order of a Python `set`
   (`_clean_ids`, cluster_attendance.py 315), which differs between processes
   (string hashing is randomised), so the serial `cluster_activity_attendance.id`
   is given to schools in a different order on each run. Measured (38.6): two
   runs of the existing application differ in that table and nothing else; with
   `PYTHONHASHSEED=0` on both they are identical. Go cannot match a random
   order. Either the comparison reads that table's ids as noise and matches its
   rows on (activity, school), or Django inserts in a fixed order (a change to
   the existing application: the owner's call, as 32.8's was).
5. **The app's path.** The app has no native group-training save to route
   through Go (38.1). Wiring it needs the feed to open the cluster drawer and
   save it (`DRAWER_VIEWS` / `DRAWER_SAVES` or a cluster kind beside
   `PlanningDrawerFeedView`), which changes what the app does (a native drawer
   in place of the web page): not behaviour-neutral, so a decision first.
6. **Size.** Every active course is governance-gated, so the port includes the
   cluster recommendation engine (`recommend_cluster_activities` and the
   school engine it merges) and `plan_alignment.cluster_need`, read-only but
   large, beside the save itself.

### Decided (the coordinator, 2026-11-13; production still needs the owner's approval at cutover)

1. **Writer role:** granted in `platform/deploy/db/activities_roles.sql`
   (appended) exactly what the save inserts and reads: `INSERT` of the
   session's cluster, participant and materials columns on `activity`;
   `INSERT` on `cluster_activity_attendance` and `USAGE` on its id sequence;
   `SELECT` of `cluster (id, deleted_at, responsible_staff_id, district_id)`,
   `school.cluster_status`, `activity_catalogue_item.cluster_delivery_allowed`
   and `activity (cluster_id, fy, focus_intervention, created_at)` (the
   recommendation engine's conflict and follow-up reads and the duplicate
   guard). No `UPDATE` of anything new; `dbguard` now also names the
   session's head-count columns and the invitation's session, school,
   invited, attended and guest columns as insert-never-change, and the
   invitation table as never removed.
2. **Cluster lock:** `gateway_lock.lock_cluster(id)` beside `lock_school`,
   owned by the NOLOGIN `edify_cluster_lock_owner` (`UPDATE (updated_at)` on
   `cluster` only; its `CREATE` on the lock schema is revoked once the
   function is made); the gateway has `EXECUTE` and nothing else.
3. **Core schools:** a session inviting a Core school is handed on (checked
   before and inside the transaction): its package slots stay Django's.
4. **Invitation order:** Django unchanged. `cmd/shadow` reads
   `cluster_activity_attendance.id` as `<new>` and compares the table's rows
   by what they say (the session, the school, the counts):
   `serialIDs` in `cmd/shadow/main.go`,
   `TestInvitationsAreComparedBySessionAndSchoolNotTheirSerialID`.
5. **App path:** no app wiring. The save is proved at the service level and
   wired into `internal/screens` (`WithGroupTrainingSave`,
   `ScheduleGroupTrainingInGo`) behind `schedule_group_training`, off by
   default; nothing calls it yet.
6. **Recommendation and need:** `recommend_cluster_activities` and
   `plan_alignment.cluster_need` ported read-only (`cluster_need.go`), their
   vocabularies exported (`rules.json` `group_training`, drift test
   `apps/activities/test_schedule_visit_rules_export.py`), unit tests for
   what the seed cannot reach.

## 38.6 Built on this branch

| Piece | Where |
|---|---|
| Copies by name | `cmd/shadow/copies.sh` reads `EDIFY_SHADOW_BASE`, `EDIFY_SHADOW_A`, `EDIFY_SHADOW_B` (defaults unchanged, each still refused unless named `edify_shadow_*`; on `fresh` the base and both copies are checked before anything is dropped), so several people prove saves side by side. Checked: with `EDIFY_SHADOW_B=edify_gorn_dev`, `copies.sh fresh` prints `refused: edify_gorn_dev is not a shadow copy`, exits 2 and leaves copy A in place |
| The scenario | `cmd/shadow/scenarios/group_training.json` (13 steps, `[shadow-gt]`, `cceo@edify.org` unless named): Leadership at C making a day (A); Budgeting at I joining it (B); A again (refused, identical); the submitted week (refused, "This week's request has already been sent for approval. …"); a past date; no training; no school ticked; nobody per school (refused, "Enter the planned participant count …"); an orientation (no intervention, saved); a profile posted as the training (refused, "Select a training from the governed Training Catalogue."); a cluster with Core schools (saved; for Go a hand-on); a partner facilitating (saved; a hand-on); `cceo1@edify.org` opening cceo's cluster (refused at the drawer, "Access Denied: …") |

**The harness against itself** (no Go: the existing application plays the
scenario on `edify_shadow_s22_a` and again on `edify_shadow_s22_b`; a
fresh pair from `edify_shadow_s22_base`, made from `edify_gorn_dev` with the
roles applied and the week of 30 November's request set to `submitted`, as the
other saves' base). Last lines exactly as printed, first run
(`agent22_self1.txt`):

```
0 of 13 steps answered differently
366 tables, 18 changed by the runs
  cluster_activity_attendance              DIFFERS: 8 rows only in a, 8 only in b
1 of 18 changed tables differ
exit status 1
shadow exit 1
verify_chain {'ok': True, 'brokenAt': None, 'checkedRows': 15978, 'fromSeq': None}
```

Every differing row is an invitation whose serial id names another school of
the same session (38.5 §4). With `PYTHONHASHSEED=0` for both runs, and step L
moved off the submitted week (`agent22_self2.txt`):

```
13 steps on edify_shadow_s22_a: 5 answered ok, 8 refused
13 steps on edify_shadow_s22_b: 5 answered ok, 8 refused
0 of 13 steps answered differently
366 tables, 18 changed by the runs
0 of 18 changed tables differ
shadow exit 0
verify_chain {'ok': True, 'brokenAt': None, 'checkedRows': 15983, 'fromSeq': None}
```

## 38.7 Agent 22's stopping point (superseded)

Agent 22 stopped at 38.5's decisions with nothing granted; agent 24 built the
save on this branch after the coordinator decided them (38.8–38.11).

## 38.8 Built

| Piece | Where |
|---|---|
| Rules | `rules.json` `group_training` (the activity type, the per-school mode, the Champion types, the operating statuses, the active and completed support statuses, the admin catalogue type, the ranked, follow-up and ungated mapping modes, the country, visit-only and summary roles), exported by `export_schedule_visit_rules` (`group_training()`), drift test `apps/activities/test_schedule_visit_rules_export.py`. Words of the view, the service and `set_invited_schools` are literals in `group_training.go`, each with where it is said |
| The save | `internal/activities/group_training.go`: `GroupTrainingRequestFromForm` (only the drawer's own fields; a partner facilitating, no "Facilitated by" field, online delivery, a responsible person, a named focus, a project, partner delivery, a meeting or a school are handed on), `Service.ScheduleGroupTraining`: 38.3 in its order (the gate, the date, the course offered for a cluster today, the ticks, the course on the day, the past date, per school by category, the active member count and the invited count, the materials, the scope, the SSA need, `validate_context`, the governed recommendation, the cost preview and the day asked of the relay, the ceiling); one transaction: `gateway_lock.lock_cluster`, the ceiling again, the duplicate guard, the invitations' refusals (Champion, members only) and the Core hand-on, the day's refusal, the day joined, the row, one invitation per school, the invited schools' open recommendations planned to the session, the costs to follow; after commit the ledger's mark, `activity.scheduled` (`cluster_id` set, `school_id` null), Django settles the day. Hand-ons besides 38.4's: no participants stated per school (the catalogue's guidance or the preview decide it), a number Python's `int()` and Go would read apart (a sign, a leading zero, a decimal), a school ticked twice, a cluster the person is not responsible for, a standard-support or not per-school course |
| Need and recommendation | `internal/activities/cluster_need.go`: `clusterNeedFrom` (cluster_need: Python's `sum`, half-even rounding, the 5.5 line, out-of-date records set aside, source SSAs sorted, first 50), `assessCluster` / `clusterReason` (the cluster verdict and sentence), `recommendForCluster` / `rankForCluster` (recommend_cluster_activities: members by `school_id`, each ranked by the school engine already ported for the visit save, fixed and multiple-allowed mappings by (rank, priority, intervention), follow-up items at rank+20 on the cluster's last completed session's target, merged by stable code, sorted by (rank, −schools, conflict, name, code), the first three recommended) |
| The day check | `apps/daily_visit_batches/gateway_relay.py` (behaviour-neutral for every existing caller): `PROBE_FIELDS` gains the session's cluster, head-count and materials columns, and a probe with a cluster and no school asks the cost preview with the cluster's district for the officer, the derived head count and the materials (`_cluster_preview_inputs`), as `_create` asks it. A school's probe asks exactly what it asked before |
| Writer role and lock | `activities_roles.sql`, appended (38.5 "Decided" §1–2). Applied additively to `edify_shadow_s22_base` and `edify_gorn_a22_test` only |
| Guard | `dbguard`: `cluster_activity_attendance` never removable; the head-count and invitation columns insert-never-change; the schema-statement lint allows the activities package's invitation insert |
| The switch | `config.GoSaves.ScheduleGroupTraining`, named `schedule_group_training`: off unless named, refused in test and production, needing the existing application's address and internal key; `server.go` gives the screens service the save when it is on (`WithGroupTrainingSave`); `screens.ScheduleGroupTrainingInGo(form)` answers in the existing feed's words (`outcomeOf`), or is not served. Nothing calls it (38.1) |
| The shadow | `cmd/shadow/goplay` plays a posted cluster form through `ScheduleGroupTraining`; `cmd/shadow` reads the invitations' serial id as `<new>` (38.5 "Decided" §4). The proof's Djangos ran with a settings module that only sets `ADMIN_OPS_SLO_MS = 600000` on both copies (38.9) |

No new contract was added: nothing outside the gateway calls the save yet;
the RPC belongs with the app path (38.5 §5).

## 38.9 Proof in shadow (service level)

Copy A through the existing application, copy B through Go with Django on
8284 over copy B for the relay and the settling (`agent24_shadow_run.sh`,
fresh copies from `edify_shadow_s22_base` with the grants of 38.8 applied).
Nine of the thirteen steps were Go's (A, B, the identical session, the
submitted week, the past date, no training, no school ticked, the
orientation, the profile posted as the training); four were handed on
(nobody per school, the cluster with Core schools, the partner facilitating,
`cceo1@edify.org` refused at the drawer). Last lines exactly as printed
(`agent24_run_group_training.txt`):

```
13 steps on edify_shadow_s22_a: 5 answered ok, 8 refused
0 of 13 steps answered differently
goplay exit 0
366 tables, 18 changed by the runs
0 of 18 changed tables differ
shadow exit 0
verify_chain {'ok': True, 'brokenAt': None, 'checkedRows': 15983, 'fromSeq': None}
```

`activity` (5 rows written on each), `cluster_activity_attendance` (17),
`audit_log` (17), `domain_event_log` (17), `daily_visit_batch` (2), the
costs, cost lines, fund-request, advance and ledger tables are the same.

The first run (`agent24_shadow1.txt`) answered every step the same and left
every save table the same, but differed in `admin_system_incident`,
`notification`, `audit_log` and, through the audit sequence, in
`domain_event_log`: the existing application's slow-request detector
(`apps.admin_ops.detection`, 3,000 ms) opened SLO incidents on whichever
copy's requests happened to be slow (8–10 s each on a machine shared with
other agents' test suites). The re-run sets the threshold far out on both
copies' Djangos, a setting of the proof only.

**The earlier saves, re-run on this branch** (they share the row writer,
now cluster-aware, and the probe): schedule_visit
(`agent24_run_schedule_visit.txt`): `15 steps on edify_shadow_s22_a: 10
answered ok, 5 refused`, `0 of 15 steps answered differently`, `366 tables, 20
changed by the runs`, `0 of 20 changed tables differ`, `shadow exit 0`,
`verify_chain {'ok': True, 'brokenAt': None, 'checkedRows': 15991, 'fromSeq':
None}`; training_pair (`agent24_run_training_pair.txt`): `18 steps on
edify_shadow_s22_a: 10 answered ok, 8 refused`, `0 of 18 steps answered
differently`, `366 tables, 20 changed by the runs`, `0 of 20 changed tables
differ`, `shadow exit 0`, `verify_chain {'ok': True, 'brokenAt': None,
'checkedRows': 16005, 'fromSeq': None}`. The app-level runs were not re-run:
the app path does not reach this save, and the app-level harness is
unchanged.

## 38.10 Tests

`internal/activities/group_training_test.go` (the form Go takes and every
hand-on; participants and materials as the service reads them; the cluster
need, verdict and sentence; the recommendation's merge, order, follow-up and
no-row cases; a cluster row's columns and probe, and a visit's unchanged);
`internal/screens/group_training_save_test.go` (served only with the switch,
a hand-on forwarded, a refusal in the existing words);
`internal/config/go_saves_test.go` `TestTheGroupTrainingSaveIsOffUnlessNamed`;
`cmd/shadow` `TestInvitationsAreComparedBySessionAndSchoolNotTheirSerialID`;
integration `TestTheWriterRoleMakesTheGroupTrainingsWritesAndNoMore`,
`TestTheClusterLockBlocksAnotherSessionsLock`,
`TestTheGoGroupTrainingIsOffByDefaultAndRefusedInProduction`, and
`TestGatewayRoleCanNeitherWriteNorReadSecrets` extended (no invitation
changed or removed, no session re-clustered or recounted, no cluster
written), with the visit's, pair's and staging-identity tests passing on
`edify_gorn_a22_test`; Django `ClusterPreviewInputsTest`. `gofmt`, `go vet
./...`, `go test -race ./...`, ruff, format, bandit and the drift test pass.

## 38.11 Not done

The app path (38.5 §5) and a contract for it; switching the Django save off
in the same release (03 §3.7) and any cutover wait for the owner. Not
reachable with the seed data, so covered by the code path, the hand-on rules
and unit tests only: a training ceiling, a Champion school ticked, a school
ticked from another cluster, a follow-up course, a course mapped several
ways, an out-of-date or missing member SSA, open recommendations at the
invited schools, a cost-preview refusal other than the participants'.
Nothing was written to `edify_gorn_dev`; every save was made on
`edify_shadow_s22_a` / `_b`.
