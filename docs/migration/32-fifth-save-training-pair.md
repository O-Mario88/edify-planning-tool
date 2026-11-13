# 32. The fifth save in Go: an In-school Training and its school visit

M5 (04): "schedule … Each write appends the same audit and timeline rows as
today." Scheduling an In-school Training is one decision that writes two
activities: the training and its companion school visit, the same day. The
visit carries the visit's cost and the training costs nothing (owner,
2026-09-28, "In-school training: visit carries cost"); In-school Training +
SSA Collection is the same pair, its visit collecting the school's SSA
(owner, 2026-10-20). This piece extends the first save (27) and follows its
decisions and 29.4's and 30.4's: the pricing's refusals asked of the
read-only Django check before Go's transaction, the costs to follow written
by Go and settled by Django after commit, an acting seat handed on, the
school's lock through `gateway_lock.lock_school`, and the writer role kept to
what the save writes.

**Where it stands (2026-11-13).** Mapped (32.3) and measured (32.2); the
contract, the writer role's additions, the Go save and the app's switch are
built; the shadow proofs at the service and the app level answer every step
the same and leave every changed table the same **but one**: the pair's
domain events, whose audit sequence the existing application drops (32.6, a
defect in the existing code, put to the coordinator). The first save's
scenarios, re-run on this code, pass at both levels. Nothing is switched on
outside this proof's own processes.

## 32.1 Scope

- **In:** the owner's own staff In-school Training (purpose
  `in_school_training`, or `in_school_training_ssa`) from Planning's Schedule
  drawer (`/planning/schedule-modal?school_id=…` posting to
  `/planning/schedule-action`) and the app's `SavePlanningDrawer(…,
  "schedule", …)`, at a school in their own portfolio that is not a Core
  school, for a Training Catalogue course whose one active, primary mapping
  is **fixed** to one of the eight SSA interventions or **administrative**
  (an orientation: none), with "Facilitated by" left at Staff, and no
  project, priority allocation, source activity, cluster, posted focus or SSA
  flag. A **universal** course (SSA Training) is in: it is on top of the
  school's entitlement.
- **Handed on, unchanged:** a partner facilitating (the facilitation fee and
  reprice), partner delivery and Certified Partner Agency, Core package
  trainings (V and T slots), group, cluster and online trainings, a course
  mapped to "any SSA intervention" or to several, a course whose workflow
  kind is another purpose's (the view would replace it), a course with a
  **training ceiling** set for the officer this year (`reserve` counts the
  officer's covered schools: not ported), a person in an acting seat or an
  asking role, a school outside the person's own portfolio or owned by
  someone else, a profile that is not standard support, a day that does not
  pool the visit. Nothing here writes a notice after commit (the owner is the
  actor; `_notify_scheduled_owner` tells nobody).

## 32.2 What one pair writes (measured, 2026-11-13)

`cmd/shadow/scenarios/training_pair.json` through the existing application
on a fresh copy, and its first two steps again with the settling thread held
(`_when_the_save_commits` stubbed, as 30.2) to read the save's own rows:

| Table | Row | Written by |
|---|---|---|
| `activity` (training) | `activity_type in_school_training`, `purpose_type in_school_training`, the **In-School Training** profile's catalogue item, version and snapshots, `activity_name_snapshot` = the course's name, `training_course_id` = the course, `focus/purpose_intervention` = the course's (none for an orientation), `ssa_collection_expected false`, **no day** (`daily_visit_batch_id` NULL: `skip_cost_snapshot`), `recommendation_source` = standard support plus `trainingCourseId/Name/Code`, `trainingCategory`, `ssaIndicator`, and the SSA verdict with `focusSource "course"`; then `paired_school_visit_id` = the visit | `_create` (2289–2340, 3471–3488), then the pair (785–786) |
| `activity` (visit) | `activity_type school_visit`, `purpose_type in_school_training_delivery_visit`, the **School Visit** profile, goal "School visit accompanying {course}", outcome the posted one or "Complete the school visit and {course} training.", the course's intervention, `ssa_collection_expected` for the SSA purpose, its day's batch; then `ssa_alignment` and `recommendation_source.ssa` replaced by the training's, with `pairedWithActivityId` | `_create`, then the pair (787–797) |
| `audit_log`, `domain_event_log` | `activity.scheduled` for the training, then for the visit (the eleven-key payload, `focus_intervention ""` for none) | `_create` 3566–3597, inside the pair's transaction |
| `daily_visit_costs_to_follow` | one row: the visit's day (`steps.days = [[batch, owner]]`) | the visit's `costs_follow` |
| `target_ledger_dirty` | (owner, FY) once on commit: both rows share it | `ledger_sync` |
| `ssa_recommendation` | the school's open recommendations for the course's intervention, planned to the **training** (none on the scenario's schools) | `link_recommendations` |

Then the pricing that follows (Django's, settled after commit): the visit's
cost snapshot and lines, the day's figures and route batch, the week's and
month's requests, transport and advance rows. The training is never priced
(`UNCOSTED_PAIR_TRAINING`). No training-ceiling, priority, slot or notice row
is written for 32.1's case.

Measured run (`agent16_m_a.json`): `14 steps on edify_shadow_a: 8 answered
ok, 6 refused`; against the untouched copy 20 tables changed, among them
`core_activity_slot` and `document_acknowledgement` from the handed-on Core
and other-officer steps.

## 32.3 The path, line by line (this branch, 8b790bc42)

**The view** (`apps/frontend/views/planning_views.py`, `schedule_action_view`):

| Step | Lines | What it does for this case | Go |
|---|---|---|---|
| Gate | 1987 | as 27.6 | the same gate and words |
| Purpose | 2025–2032 | `split_training_purpose`: `in_school_training_ssa` → `in_school_training`, the visit collecting (staff delivery only) | `IsPairPurpose`; collects for the SSA purpose |
| Date | 2061–2072 | blank / invalid: 27.6's words | the same |
| Course | 2142–2160 | no `catalogue_item_id` → "Select the Training to deliver."; `validate_in_school_training_course_selection` (today): not an effective, staff-deliverable course → "Select a training from the governed Training Catalogue."; `_training_focus` | `offeredCourse(today)`; the same words |
| Pin | 2197–2273 | the course's kind is another purpose's → replaced (and then refused by the pair) | handed on (`course.conflicts`) |
| School | 2318–2338 | as 27.6 | `ownSchool` (27's, moved into a helper unchanged) |
| Route | 2462–2468 | `schedule_in_school_training_pair(payload)`; `ssaCollectionExpected` for the SSA purpose | `schedulePair` |
| Answer | 2469–2528 | "In-school training and school visit[ with SSA collection] scheduled. It is on your My Plan — keep planning.", the My Plan link, the ceiling notice | the same words (literals there and in `pair.go`) |

**The pair** (`apps/planning/services.py` 661–811, `@transaction.atomic`):

| Step | Lines | Reads / refuses | Go |
|---|---|---|---|
| Course | 689–706 | blank → refused; `validate_…(on_date=day)`; `get_selectable_item` | `offeredCourse(day)`, same words (a course effective that day is selectable) |
| Profiles | 707–719 | `resolve_item_for_workflow_kind(in_school_training / school_visit, day)`; none → "The standard In-school Training and School Visit profiles must both be active before this work can be scheduled." | `resolveForKind`, same words |
| Training | 735–750 | `create(…, training_course=course, skip_cost_snapshot=True)` | `pairTraining` (below) |
| Visit | 754–784 | `create(…)` with the companion purpose, the School Visit profile, the default words, `ssa_default_focus=False`, no facilitator or priority keys | `pairVisit` (below) |
| Join | 785–797 | the training names the visit; the visit takes the training's verdict | inserted joined (32.4 §2) |
| Facilitator | 798–803 | reprice for a partner facilitator | handed on |

**`_create` for the training** differs from 27.6 at: the course's fixed
intervention (`intervention_for`, 2313) and `resolve_activity_intervention`
(2322–2340), focus source "course"; the entitlement with the course
(`never_refused`: a universal course is not refused after the Champion
rule); the course's mapping modes for the verdict (2924–2932); no cost
preview, day or costs (`skip_cost_snapshot`, 3134, 3555); under the school's
lock `reserve_for_activity` (3270), a no-op with no ceiling row; the course's
identity on the row (3471–3488). `_link_training_intervention` (models 507)
changes nothing (the focus is set, or the course fixes none). The duplicate
tests are 27.6's: the identical test refuses a second In-school Training at
the school that day; the client same-day test skips trainings and the
companion visit.

**`_create` for the visit** is 27.6's for a School Visit, with the companion
purpose: no pool counts it (`client_visit_pool`), its cost preview and day
are the first save's relay (`visit-day-check`, met after the training's
locked tests, as the existing order meets them), its costs to follow are the
pair's one row.

## 32.4 Decisions

Covered by 27.8, 29.4 and 30.4 and kept: the relay before the transaction,
the costs settled by Django, the acting seat handed on, the school lock. Two
choices made here, neither a rule change:

1. **No new UPDATE right.** The existing save inserts the training and then
   UPDATEs `paired_school_visit_id`, and UPDATEs the visit's verdict.
   `dbguard.protectedColumns` names `activity.paired_school_visit_id`
   (insert, never change). Go computes both rows before the transaction and
   inserts the visit first and the training naming it, which leaves the same
   rows; the writer role gains `INSERT (training_course_id,
   paired_school_visit_id)` and nothing to UPDATE.
2. **Training ceilings are handed on.** A ceiling set for the officer and
   course this year means `reserve` counts the officer's covered schools
   across staff, group and partner routes (training_ceilings.py); Go hands
   such a pair on (checked before and again inside the transaction) rather
   than port that count. The dev data has no ceiling.

## 32.5 Built

| Piece | Where |
|---|---|
| Contract | `edify/activities/v1/activities.proto`: `ScheduleSchoolVisitRequest` documents the two pair purposes and the course in `catalogue_item_id`; `ScheduledActivity.paired_school_visit_id = 10`. `buf lint`, `buf format --diff --exit-code`, `buf breaking` against this branch's head and `origin/feature/edify-go-rn-migration` pass; Go (`backend/gen`), web (`web/src/gen`) and app (`mobile/src/gen`) code regenerated with the pinned generators, only the activities files changed |
| Writer role | `activities_roles.sql`, appended: `SELECT (staff_delivery_allowed, universal_training, training_category, ssa_indicator_label)` of a catalogue item, `SELECT (intervention)` of a mapping, `SELECT (staff_id, training_id, fy)` of `training_ceiling`, `INSERT (training_course_id, paired_school_visit_id)` of `activity`. Applied additively to `edify_shadow_base` and `edify_gorn_test` only |
| Rules | `rules.json` `pair` (the two purposes, the profiles' kinds, the training shapes, the mapping modes), exported by `export_schedule_visit_rules`, drift test `apps/activities/test_schedule_visit_rules_export.py` |
| The save | `internal/activities/pair.go`: `Service.Schedule` routes the two purposes to `schedulePair`; 32.3 in its order; one transaction: the school's lock, the training's entitlement, ceiling and duplicate tests, the visit's preview refusal, entitlement and duplicate tests, the day's refusal, the day joined, the recommendations planned to the training, both rows, the costs to follow; after commit the ledger's mark, the training's then the visit's `activity.scheduled` rows (the leave-cover stamp), then Django settles the visit's day |
| The switch | `config.GoSaves.ScheduleTrainingPair`, named `schedule_training_pair`: off unless named, refused in test and production, needing the existing application's address and internal key. The screens' Schedule save asks Go only when the switch for that purpose is on (`switchedOn`): `schedule_visit` never moves a pair and `schedule_training_pair` never moves a visit. A non-blank "Facilitated by" in the form is handed on by `RequestFromForm` |
| The shadow | `cmd/shadow/goplay` needed nothing new (`RequestFromForm` + `Schedule`); `cmd/shadow/appplay` sends the training picker's values as the app does (`planningLogic.scheduleValues`: the course, the facilitator, the course's reason) |

## 32.6 Proof in shadow

**The scenario** (`cmd/shadow/scenarios/training_pair.json`, 18 steps,
`[shadow-t]`, `cceo@edify.org`): a Leadership training joining a day already
made (A); the SSA purpose with an outcome (B); a donor visit through the
first save making a day (C) and an orientation (no intervention) beside it
(D); a second training at A's school (refused, the one-visit rule: "…has had
its staff support visit (a Training Follow Up or an In-school Training) for
FY2027 (1/1)."); SSA Training on top of it (F, universal, saved); A again
(refused); a past date; no course; a Champion school; the submitted week
(refused, "This week's request has already been sent for approval. …"); SSA
Training first at a fresh school making its day (O), then Leadership the same
day (refused, the identical-activity test), then Leadership the next week
with the SSA purpose (Q, saved: the universal training is not counted); a
profile id posted as the course (refused, "Select a training from the
governed Training Catalogue."); then the hand-ons: a partner facilitating, a
Core school, and `cceo1@edify.org` at another officer's school.

**Service level** (copy A through the existing application, copy B through
Go with Django on 8196 over copy B; `agent16_shadow1.txt`), last lines
exactly as printed:

```
18 steps on edify_shadow_a: 10 answered ok, 8 refused
0 of 18 steps answered differently
goplay exit 0
366 tables, 20 changed by the runs
  domain_event_log                         DIFFERS: 17 rows only in a, 17 only in b
1 of 20 changed tables differ
exit status 1
shadow exit 1
verify_chain {'ok': True, 'brokenAt': None, 'checkedRows': 15976, 'fromSeq': None}
```

Fifteen steps were Go's (six pairs saved, the first save's visit, eight
refusals), three handed on. `activity` (20 rows written on each),
`audit_log` (39), `daily_visit_batch` (5), the costs, fund-request, advance,
transport, route and ledger tables are the same.

**App level** (`agent16_app_shadow.sh`: copy A through gateway 8096 with the
switch off over Django 8196 on `edify_shadow_a`; copy B through gateway 8097
with `EDIFY_GO_SAVES=schedule_training_pair` over Django 8197 on
`edify_shadow_b`; `agent16_app_shadow2.txt`): `0 of 18 steps answered
differently`, `compare exit 0`, `366 tables, 19 changed by the runs`, then,
exactly as printed:

```
  domain_event_log                         DIFFERS: 13 rows only in a, 13 only in b
1 of 19 changed tables differ
exit status 1
shadow exit 1
verify_chain {'ok': True, 'brokenAt': None, 'checkedRows': 15976, 'fromSeq': None}
form-only requests on B: 18
forwarded drawer saves on B: 4
```

On B Go made 14 (six pairs, eight refusals); 4 saves were forwarded (the
donor visit, whose switch was off, and the three hand-ons); Django answered 8
`visit-day-check` and 6 settling requests for Go (the log's 8
`costs-to-follow` lines include the script's two readiness probes). The
first app-level run (`agent16_app_shadow1.txt`) also differed in the last
handed-on step's pricing rows: the window closed at the app's last answer,
before Django's settling thread had written them; the script now closes it
once both servers have stopped.

**The one difference: the existing application drops the pair's audit
sequence from its domain events.** On both runs every differing row is an
`activity.scheduled` (or the settling's `activity.cost.calculated`) event
whose `payload.auditSeq` is `null` on the existing application's side and
the row's sequence on Go's; with `auditSeq` removed the events of the service
run are identical (`agent16_ev_a.txt` / `agent16_ev_b.txt`, 39 rows each,
differing only in the new activity ids `cmd/shadow` reads as `<new>`). The
audit rows themselves are the same and the chain verifies on both copies.
Cause, read and confirmed: `schedule_in_school_training_pair` is decorated
`@transaction.atomic`, and a decorator is **one** `Atomic` instance for the
life of the process (`_recreate_cm()` returns itself, checked in a shell).
`audit.services._seal_after_commit` marks the outermost atomic block with
`_edify_audit_seal = True` and registers the seal only when the mark is
absent, so after a process's first pair no seal runs at the pair's commit:
its audit rows are written unsealed, `_ProjectOnCommit` reads `seq` NULL and
publishes `auditSeq: null`, and the rows are sealed later by someone else's
commit or the scheduled seal. The first pair each process makes keeps its
sequence (on copy A the runner's first pair has 15938/15939; on B the
handed-on steps 16–18, each played by a fresh process, keep theirs). Go writes the sequence the seal gives, as the projection is designed
to. **Decision needed** (32.8).

**The first save, re-run on this code** (it shares `prepare`, now
`ownSchool`, and the activity insert, now two columns longer): service level
`0 of 15 steps answered differently`, `366 tables, 20 changed by the runs`,
`0 of 20 changed tables differ`, `verify_chain {'ok': True, 'brokenAt': None,
'checkedRows': 15962, 'fromSeq': None}`; app level with
`EDIFY_GO_SAVES=schedule_visit`: `0 of 15 steps answered differently`,
`366 tables, 19 changed by the runs`, `0 of 19 changed tables differ`,
`verify_chain` the same over 15,962 rows, 15 form-only requests and 3
forwarded saves on B (`agent16_first_service.txt`, `agent16_first_app.txt`).

**Not reachable with the seed data**, so covered by the code path, the
hand-on rule and unit tests only: a training ceiling, a course mapped to
"any SSA intervention" or several, a course of another purpose's kind, an
inactive profile, a cost-preview refusal on the visit, a closed school, open
recommendations for the course's intervention at the school.

## 32.7 Tests

`internal/activities/pair_test.go` (which courses Go takes and the
intervention each carries; a course the view would replace; the two
purposes and no other, and none of the six; a universal course on top of the
entitlement but not of the Champion rule, asking nothing; the hand-ons and
the pair's own refusals before any read); `internal/screens/pair_save_test.go`
(each switch moves only its own save; a partner facilitating is forwarded;
never made by both); `internal/config/go_saves_test.go` (the new name);
integration `TestTheWriterRoleMakesThePairsWritesAndCannotRejoinThem` (the
reads and the two joined inserts as the gateway; UPDATE of the pair, the
course or a ceiling refused 42501) and
`TestTheGoTrainingPairIsOffByDefaultAndRefusedInProduction`;
`TestTheVisitSaveRefusesAndHandsOnInTheExistingWords` now expects an
In-school Training with no course to be refused in the view's words (it was
a hand-on before this save); `TestGatewayRoleCanNeitherWriteNorReadSecrets`,
`TestStagingIdentityCheckAcceptsOnlyTheReadOnlyRole`,
`TestTheActivitiesWriterRoleMakesTheVisitSavesWrites`,
`TestTheGoVisitSaveIsOffByDefaultAndRefusedInProduction` pass. `gofmt`,
`go vet ./...`, `go test -race ./...`, ruff, format, bandit and the rules
drift test pass.

## 32.8 Decision needed, and not done

**Decision (for the coordinator, then the owner): the pair's domain events.**
The existing application publishes `auditSeq: null` for an In-school
Training pair's events after each worker process's first pair (32.6), a
defect of the shared seal flag on a decorator's `Atomic`. Either (a) Go
keeps writing the sequence and the defect is fixed in Django (for instance
the seal mark kept per transaction rather than on the reused `Atomic`) —
a Django behaviour change, outside this piece — or (b) Go reproduces
`null` for the pair's events, which matches a warmed worker but not a
process's first pair. Until then the shadow proof stands at one table
differing in that one field. Nothing else was found that needs a rule or
right beyond 27.8, 29.4 and 30.4.

**Not done.** Switching the pair off in Django in the same release (03 §3.7)
and any cutover wait for the owner; the switch is on nowhere but this proof's
processes. The web (Next.js) does not call this path. No replayed month on a
sanitised restore. The handed-on cases (32.1) stay Django's.
