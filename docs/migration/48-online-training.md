# 48. The eighth save in Go: scheduling an online training (M6)

The cluster drawer has a third delivery mode (owner, 2026-10-09: "add
schedule for online training on the cluster training schedule … online
training fetches no cost it is free"): **Online Training**, opened as
`/planning/schedule-modal?cluster_id=…&action=online` and posting to
`/planning/schedule-action` like the Group Training of 38. It is the same
record (a `cluster_training` for the cluster and its ticked schools, the same
course, participants, invitations and ceiling count) delivered online, and so
free. This piece extends 38's Go save (`internal/activities`) to take it.

**Where it stands (2026-11-13, agent 36).** Mapped (48.1), measured (48.2),
built (48.3) and proved in shadow at the service level (48.4): every step
answers the same, every changed table is the same, the audit chain verifies.
It sits behind 38's switch `EDIFY_GO_SAVES=schedule_group_training` (off by
default, refused in test and production); nothing calls it yet (38.5 §5: the
app has no native cluster drawer). The writer role's additions (48.3) are
applied to this agent's shadow base and integration database only;
production needs the owner's approval at cutover like every role change.

## 48.1 What online changes on the path (this branch, cut from feature/edify-go-rn-migration at 79a030baa)

Everything in 38.3 holds; the differences, each where it is made:

| Step | Where | Online |
|---|---|---|
| Drawer | `schedule_modal_view` 1471–1476, `schedule_cluster_drawer.html` 3, 38–42, 119, 518–524, 542 | `action=online` is drawn as the training drawer titled "Schedule online training", with a hidden `delivery_mode=online`, no materials fields, the same Facilitated by field |
| Payload | `schedule_action_view` 2357–2363 | `programmeDeliveryMode "online"` for a `cluster_training` whose posted `delivery_mode` (stripped) is `online` |
| Cost preview | `_create` 3129–3135 (`asked_for_online`) | not asked: no rate can be missing, so "Enter the planned participant count …" is never said (a session with nobody per school saves at 0) |
| Row | `_create` 3395–3399 | `programme_delivery_mode = "online"` |
| Pricing | `_price_activity` 1174–1190 (`is_online_training`) | no day joined (no batch, no costs to follow); `apply_to_activity` with `precomputed_cost=ActivityCost()` **inside the save**: the period columns (`planned_date`, `week_start_date`, `week_end_date`, `fiscal_year`, `month`, `quarter`, `fy` from the planned day), `est_cost_cents 0`, `cost_missing` (false while a card is active), one current `activity_cost_snapshot` (operational cost 0, no lines, `calculation_inputs`/`warnings` of `calculate_dual`, reference figures when a reference card exists) and its `activity.cost.calculated` audit entry (actor the funding owner, no role) — **before** `activity.scheduled`. The weekly, monthly and advance syncs find no line and write nothing |
| Answer | 2476–2528 | the same toast: "Cluster activity scheduled. It is on your My Plan — keep planning." |
| Announce | the row's post_save (`live`) | `plan.changed` on commit; nothing settles later |

## 48.2 What one online training writes (measured, 2026-11-13)

Three online saves (`[shadow-ot]` A, B, D of the scenario) on a fresh copy
through the existing application, against the untouched twin
(`agent36_m2_cmp.txt`): `366 tables, 7 changed by the runs`: `activity` (3),
`activity_cost_snapshot` (3), `audit_log` (6: cost.calculated then scheduled,
per save), `domain_event_log` (6), `cluster_activity_attendance` (9),
`target_ledger_dirty` (1), `user` (the runner's sign-in). No batch, cost
line, advance, weekly or monthly request, costs-to-follow row or notice.

## 48.3 Built

| Piece | Where |
|---|---|
| The form | `GroupTrainingRequestFromForm` takes `delivery_mode`: exactly one value `online` is an online training; any other value, or two, is handed on; absent is in person (unchanged) |
| The revision's figures | `apps/daily_visit_batches/gateway_relay.py` (behaviour-neutral for every existing caller): `PROBE_FIELDS` gains `programme_delivery_mode`; a probe of an online training asks no preview and joins no day and answers `online`, `_online_cost`: `calculate_dual` over `_profiled_input(_costing_input(activity, data))` with what `_create` holds in `data` (the head count, the materials with a blank as 0), and the snapshot's and audit entry's figures as `apply_to_activities` writes them. Read only, inside the probe's rolled-back transaction |
| The save | `internal/activities/online_training.go` and small edits in `group_training.go`, `write.go`, `relay.go`: the day check's `online` answer is taken only when free, against a card, nothing missing and every figure given (`takeable`), else handed on; the row takes the planned day's quarter and FY (the ceiling is still counted in `_create`'s year) and its periods (`periodsOf`); in the transaction no day is joined and no costs are kept; after the invitations and recommendations Go writes the snapshot and `activity.cost.calculated` (with the actor's cover, under the chain lock, inside the save); after commit the ledger's mark, `activity.scheduled`, and `activity-changed` (docs/migration/31) for the announcement |
| Writer role | `activities_roles.sql`, appended: `INSERT (programme_delivery_mode, week_start_date, week_end_date, month, fiscal_year) ON activity`; `INSERT` of the snapshot's columns on `activity_cost_snapshot`. No UPDATE or DELETE. Applied additively to `edify_shadow_s25_base` and `edify_gorn_a25_test` only |
| Guard | `dbguard`: `activity_cost_snapshot` never removable; `activity.programme_delivery_mode` and the snapshot's costs, money, current flag, activity and inputs columns insert-never-change; the schema-statement lint allows the activities package's snapshot insert |
| Scenario | `cmd/shadow/scenarios/online_training.json` (15 steps, `[shadow-ot]`, `cceo@edify.org` unless named): online at C and at I on 26 Nov (no day), the same online training again (identical), online in the week whose request is awaiting confirmation (saved: nothing priced), a past date, no training, no school ticked, nobody per school (Django saves at 0; Go hands on), an online orientation, a profile posted as the training, online at a cluster with Core schools (hand-on), a partner facilitating online (hand-on), `cceo1@edify.org` at cceo's cluster (refused at the drawer), in person at C where the online one is (identical), in person at D making the day the online ones did not |

## 48.4 Proof in shadow (service level)

Copy A through the existing application, copy B through Go with Django on
8225 over copy B for the day check, the announcement and the hand-ons
(`agent36_shadow_run.sh`, fresh copies of `edify_shadow_s25_base`: made from
`edify_gorn_dev` by `copies.sh base`, its dumped `gateway_*` schemas dropped
and the roles applied with `apply-roles.sh` to that base only, so the
SECURITY DEFINER objects are owned as the role files say; then 48.3's grants).
Both Djangos ran with `ADMIN_OPS_SLO_MS = 600000` (38.9). Eleven steps were
Go's, four handed on (nobody per school, Core schools, a partner
facilitating, cceo1 refused at the drawer). Last lines exactly as printed
(`agent36_run2.txt`):

```
15 steps on edify_shadow_s25_a: 8 answered ok, 7 refused
0 of 15 steps answered differently
goplay exit 0
366 tables, 17 changed by the runs
0 of 17 changed tables differ
shadow exit 0
verify_chain {'ok': True, 'brokenAt': None, 'checkedRows': 19403, 'fromSeq': None}
```

`activity_cost_snapshot` (9 rows written on each), `activity` (8),
`audit_log` (20), `domain_event_log` (20), `cluster_activity_attendance`
(29) and the in-person day's batch, lines, advances and requests are the
same. The first run (`agent36_run1.txt`) also matched, but only because Go
handed every online save on ("the day does not pool the session"): the
in-person pooling hand-on still ran for online; fixed before run 2.

**The earlier saves re-run on this branch** (they share the row writer, the
probe and the group save): group_training (`agent36_run_group_training.txt`):
`13 steps on edify_shadow_s25_a: 6 answered ok, 7 refused`, `0 of 13 steps
answered differently`, `366 tables, 17 changed by the runs`, `0 of 17 changed
tables differ`, `shadow exit 0`, `verify_chain {'ok': True, 'brokenAt': None,
'checkedRows': 19402, 'fromSeq': None}`; schedule_visit
(`agent36_run_schedule_visit.txt`): `15 steps on edify_shadow_s25_a: 11
answered ok, 4 refused`, `0 of 15 steps answered differently`, `366 tables,
19 changed by the runs`, `0 of 19 changed tables differ`, `shadow exit 0`,
`verify_chain {'ok': True, 'brokenAt': None, 'checkedRows': 19410, 'fromSeq':
None}`.

## 48.5 Tests

`internal/activities/online_training_test.go` (the online form and its
hand-ons; the periods of a week, a Sunday, the FY's edges; which revisions Go
writes; the row's year and columns, and an in-person row's unchanged);
`group_training_test.go` (an unknown delivery mode handed on, in place of
"online delivery"); integration `TestTheWriterRoleMakesTheOnlineTrainingsWritesAndNoMore`
and `TestGatewayRoleCanNeitherWriteNorReadSecrets` extended (no revision
repriced, superseded or removed; no session's delivery changed), with 38's
writer, lock and switch tests passing on `edify_gorn_a25_test`; Django
`OnlineCostTest` (`apps/daily_visit_batches/test_gateway_relay.py`).
`gofmt`, `go vet ./...`, `go test -race ./...`, ruff, format and bandit pass.

## 48.6 Not done

- The app path and a contract (38.5 §5, unchanged); switching the Django save
  off and any cutover wait for the owner.
- Handed on, by choice: an online session with nobody stated per school
  (Django saves it at 0 people; 38 hands it on and so does this), and every
  hand-on of 38.4 (Core schools, a partner facilitating, ceilings …).
- Not reachable with the seed data, so covered by the code path and unit
  tests only: a reference (regional) rate card (the revision's reference
  figures come from the relay unchanged), no active operational card (handed
  on: `cost_missing`), an online session on 1 October (the row's FY moves to
  the planned day's), an actor covering a colleague (the cover stamp on the
  revision's audit entry).
- Its own switch name: the online training rides 38's
  `schedule_group_training`, since it is the same save; a separate name is a
  one-line change if the owner wants them apart.

Nothing was written to `edify_gorn_dev`; every save was made on
`edify_shadow_s25_a` / `_b`.
