# 38. The seventh save in Go: scheduling a cluster group training (M6, mapped)

M6 (04): cluster planning moves after the visit saves. Scheduling a Group
Training for a cluster is one decision that writes the session, an invitation
for each school ticked, and (at a cluster with Core schools) a training slot in
each invited Core school's package. This piece follows 27.8, 29.4, 30.4 and
32.4: the pricing's refusals asked of the read-only Django check before Go's
transaction, the costs to follow written by Go and settled by Django after
commit, an acting seat handed on, the writer role kept to exactly what the save
writes.

**Where it stands (2026-11-13).** Mapped (38.3) and measured (38.2) on this
agent's own shadow copies; a scope is proposed (38.4); the scenario for the
proof is written and played through the existing application on both copies,
which agree (38.6). **No Go save is built or committed.** The save writes a
table and columns the writer role `edify_activities_rw` cannot write, and takes
a row lock it cannot take (38.5). The brief for this piece says to stop there
and report rather than grant; the decisions are listed in 38.5. Nothing is
switched on anywhere: `EDIFY_GO_SAVES=schedule_group_training` does not exist
yet.

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

## 38.7 Not done

The Go save, its switch (`schedule_group_training`), the contract, the writer
role's additions, the app wiring and the service- and app-level proofs are not
built: they wait on 38.5's decisions. The schedule_visit and training_pair
scenarios were not re-run (no shared code changed besides `copies.sh`, whose
defaults are unchanged). Nothing was written to `edify_gorn_dev`; every save in
this piece was made on `edify_shadow_s22_a` / `_b`.
