# 27. The first save in Go: scheduling a school visit (design)

Owner, 2026-11-12: the Next.js web foundation starts after the first save.
This is that save's design, measured with the shadow harness (26) before any
code. M5 (04): "schedule … Each write appends the same audit and timeline
rows as today."

## 27.1 What one visit save writes (measured)

`cceo@edify.org` saving Planning's Schedule drawer for one client school
(SSA Support, 25 November 2026), on a fresh copy, compared with the
untouched base:

| Table | Row | Written by |
|---|---|---|
| `activity` | one row, about 100 columns: the purpose's activity type (SSA Support is "School Visit + SSA Collection"), the catalogue item and version, the workflow profile's costing and evidence profiles, planned date, month, week, quarter and FY, delivery and executor, the planning source, the SSA verdict in `recommendation_source` (`apps.ssa.plan_alignment`), its day's batch | `activities.services._create` |
| `audit_log` | `activity.scheduled`, the planning payload, on the hash chain | the audit pipeline |
| `domain_event_log` | `activity.scheduled`, carrying the audit row's sequence | the audit pipeline |
| `target_ledger_dirty` | the owner and FY whose counts must be read again | the target ledger |
| `daily_visit_costs_to_follow` | the days to price again (`steps.days`: batch and owner), who asked, provenance | `daily_visit_batches.costs_follow` |

Everything else the earlier seven-step run showed (cost snapshots and lines,
fund request items, weekly request lines, transport and advance rows) is
the **pricing that follows**: `costs_follow` answers the save first and
prices the day's visits in a thread once it commits, or on the saver's next
request, or before any fund-request step (`settled_first`).

## 27.2 The split

1. **Go does the save:** every rule `_create` and the drawer's view ask for
   this save; the activity row; joining its day's batch (made if the day has
   none); the audit row on the same chain under the same advisory lock (as
   sign-in does, 08 §8.2); the domain event; the ledger mark; the costs to
   follow. It also asks what the pricing would refuse
   (`_assert_days_can_follow`: a day whose rates are missing, whose transport
   is paid, a member whose advance or weekly or monthly request has moved),
   read-only, with the same words, so a save the existing application
   refuses is refused.
2. **Money stays the existing application's until M12** (01 risk 7: money
   moves last, after a period of shadow comparison). Once its save commits,
   Go asks the existing application, server to server with the internal key
   (the pattern sign-in uses for security events), to settle the costs to
   follow it wrote. Only the queued work is passed; the pricing code is
   untouched.

## 27.3 Scope of the first piece

Go takes a visit only when every part of it is ported, and hands the rest to
the existing application unchanged (the gateway forwards the drawer's
request):

- **In:** a staff-delivered school visit (the purposes Training Follow Up,
  SSA Support, Donor Visit, Content/Story Collection, School Invitation,
  Social Visit), planned by its owner at a school in their own portfolio,
  from Planning's Schedule drawer, with no project, priority allocation,
  source activity or partner.
- **Handed on:** In-school Training (the training-and-visit pair), Core
  School visits (the package route), partner delivery and facilitation,
  visit requests to another owner, cluster work, reschedules and edits.

## 27.4 Contract, roles and proof

- **Contract:** `edify/activities/v1/activities.proto`,
  `ActivityService.ScheduleSchoolVisit`: the drawer's own fields (school,
  purpose, date, purpose text, expected outcome, SSA deviation reason), the
  answer (the activity's id and status, or the refusal's words), the
  blueprint's `activity.proto`.
- **Writer role:** `edify_activities_rw`, granted column by column only what
  27.1 lists (`INSERT` on those `activity` columns; `INSERT` on the audit and
  event logs, the ledger mark and the costs to follow; the batch's insert
  and the columns a join updates). No `DELETE`, no `UPDATE` of an audit row.
  The gateway stays read-only by default and opens a read-write transaction
  for the save only (08 §8.2); `TestGatewayRoleCanNeitherWriteNorReadSecrets`
  grows to refuse everything else.
- **Proof, in shadow (26):** the drawer scenario on copy A through the
  existing application, the same steps on copy B through Go, nothing
  differing and the same answer for every step: each in-scope purpose,
  a school with and without a batch that day, each refusal (a past date, a
  closed school, a school outside the portfolio, a day the pricing would
  refuse, the one-visit rule), then a replayed month of real scheduling on
  a sanitised restore (M5's exit). The audit chain is then verified by the
  existing `verify_chain(full=True)`.

## 27.5 Decided: one save at a time (owner, 2026-11-12)

The owner's answer: "Yes, one at a time". The reasoning it settled:


**One writer per table (03, 3.7) cannot hold save by save for `activity`.**
Dozens of saves write that table (schedule, edit, reschedule, cancel,
complete, verify, approve, pay). Moving them in one step would be one
release of all of M5 to M9. The practical path is the one sign-in took
(08 §8.4): one save at a time moves to Go, both systems writing the same
table under the same row locks and the same rules until the table's last
save has moved, each save switched off in Django in the same release that
switches it on in Go. Nothing is cut over without the owner's approval
either way; this asks which rule the cutovers follow.

## 27.6 The path, mapped (2026-11-12, before any port)

Read line by line for exactly 27.3's case: the owner, at a school in their
own portfolio, saving Planning's Schedule drawer for one of the six
purposes, staff delivery, no project, priority allocation, source activity
or partner. Lines are this branch's (354a1a64e). "Go" says what the port
must do; "hand on" means the case leaves 27.3 and the gateway forwards the
request unchanged.

**The view** (`apps/frontend/views/planning_views.py`,
`schedule_action_view`, 1986–2530):

| Step | Lines | What it does for this case | Go |
|---|---|---|---|
| Gate | 1987 | `RolePermissionService.can_open_schedule_drawer`; refused: 403 with `_no_scheduling_permission_message` (the Admin's own words) | same gate and words |
| Fields | 1993–2042 | reads the form; `split_training_purpose` (2030) only matters for In-school Training | contract fields only |
| Date | 2061–2072 | blank → "Pick the date this is planned for before scheduling it."; unparsable → "That scheduled date is not a valid calendar date." (400) | same words |
| Catalogue | 2161–2190 | `require_catalogue=yes` and no item: `resolve_item_for_workflow_kind(purpose_activity_type(purpose))`; none or several → "No single approved Catalogue Activity costs “{label}”. …" | resolve the one active item per workflow kind on the day |
| Purpose | 2197–2273 | `normalise_visit_purpose` (refusal words are the exception's); activity type from `PURPOSE_ACTIVITY_TYPES`; a pinned item of another purpose's kind is replaced (all six purposes are `INTERVENTION_FREE_PURPOSES` except Training Follow Up), clearing `recommendation_reason` | same |
| Payload | 2288–2316 | `ssaCollectionExpected` (yes, or SSA Support's type), `plannedMonth`, `plannedWeek = min(5, (day-1)//7+1)`, `requireSsaReason`, `ssaDeviationReason` | same |
| Owner | 2318–2338 | `get_visit_target_school_or_404` (`apps/core/permissions.py:1108`, by id or school code); `visit_owner_for` (3169: own portfolio → `resolve_monitoring_staff`); `approval_owner_for` (`apps/planning/visit_requests.py:74`): a request → hand on | own portfolio only; anything else hand on |
| Route | 2457–2475 | `schedule_school_visit` (`apps/planning/services.py:637`) → `schedule_as_core_visit` (`apps/core_schools/visit_routing.py:119`): None for donor/story/SSA support purposes and for a school with no core plan | a Core school (any `core_plan_for_visit`) → hand on |
| Answer | 2476–2528 | `_scheduled_into_own_plan`; toast "School visit scheduled. It is on your My Plan — keep planning." linking `/my-plan?fy=…&month=…&period=month`; `_ceiling_notice` (`staff_plan.ceiling_notice`, a warning only) | answer the activity id, status and the same message and notice |
| Refusal | 2529 | any exception → `error_fragment(e, 400)`: the exception's words | the same words in `refusal` |

**The create** (`apps/activities/services.py`, `create` 2170 →
`_create` 2203–3606, under `rate_cards_held`):

| Step | Lines | Reads / refuses | Go |
|---|---|---|---|
| Item | 2254 | `get_selectable_item(id, on_date)` | read |
| FY, quarter, period | 2338–2352 | `get_operational_fy(date)` (UTC rule), `get_quarter_for_date`, `_schedule_period` (3791) | `schooldirectory.OperationalFY` |
| Past date | 2359 | `fy_policy.assert_date_plannable`: "{d M Y} has passed. Schedule work from {today} onwards." (Kampala's day) | same |
| SSA flag | 2361–2373 | collection types or the drawer's flag | same |
| School | 2376–2385 | by `school_id` code, "School {id} not in directory"; `lifecycle_service.assert_operating` → `CLOSED_SCHOOL_MESSAGE`; district type | same |
| Participant mode | 2387–2401 | `_participant_mode_for` / `_apply_participant_mode` (1884/1902); `participant_guidance_for` when per-school | export the item's mode; per-school items are not in scope |
| Materials | 2433 | `_validated_materials` (2034): blanks | none posted |
| Scope | 2578 | `_assert_target_in_scope` (680): the owner's own school passes on the first test | own portfolio is the scope |
| Entitlement | 2597, again under the lock 3216 | `_assert_schedule_entitlement` (1322): `assert_outreach_activity_allowed` (champion schools: donor/story only), `rule_for(school_type)`; client rule: `client_visit_pool` → `assert_staff_may_schedule_visit` (the one-visit rule; SSA pool never closes); core rule → hand on | `internal/visitgate` already decides the same gate read-only for the Planning page; the refusal's words come from `visit_gate.refusal` |
| Facilitation | 2620–2650 | `_facilitating_partner_for`, `default_facilitator_id` (school work: none) | none for school work |
| Executor | 2651–2700 | `_resolved_executor_type` → staff; responsible = principal's staff profile; `district_type_for_staff` (`daily_visit_batches/districts.py:178`) | same |
| Calendar | 2744 | `SchedulingPolicyService.refusal`: empty while `CALENDAR_BLOCKS_REFUSE = False` (`apps/core/calendar_policy.py:57`) | export the switch; refuse only if it is on |
| Follow-up | 2830–2832 | Training Follow Up with no source: refused "Select the completed training this visit follows up." when `follow_up_requires_prior_training(fy)` | same policy read; with a source → hand on |
| SSA need | 2843–2846 | `plan_alignment.school_need(school)` | port (read) |
| Catalogue rules | 2960–2975 | `validate_context`, `validate_frequency` | port (read) |
| Recommendation | 2988, 3100–3123 | all six items are `standard_support` on development (checked): the "Standard field support." reason and the `standard_support` source dict; `recommend_activities` is never reached | same; a non-standard item → hand on |
| Online | 3125 | `asked_for_online`: no | — |
| **Pricing gate** | 3137–3165 | `costing_service.preview(...)` (795): a full price of the activity, read-only; blockers → "Cannot schedule — … Ask the Country Director to set the missing rate in the Cost Catalogue first." | **not ported: pricing** (27.7) |
| Status | 3167–3184 | `scheduled`; deviation reason ≤2000 | same |
| Transaction | 3207 | `School … select_for_update()` (3215); entitlement again (3216) | **the school row lock** (27.7) |
| Duplicate | 3296–3343 | identical activity same day → "An identical activity is already scheduled for this target on this date. …"; `assert_not_duplicate_client_visit` → "{school} already has this visit on {d b Y}. …"; `assert_not_duplicate_core_visit` | port (reads) |
| Source | 3344–3354 | `school_planning` / `school` | same |
| Row | 3369–3442 | `resolve_primary_driver` (2129); `Activity.objects.create(...)`, `salesforce_activity_type = sf_kind(type)` | one INSERT of the final row (below) |
| Snapshot | 3453–3466 | `apply_catalogue_snapshot` (`activity_catalogue/services.py:345`): item, version, name/type/method/evidence/costing/SF snapshots, reason, source, interventions; `latest_applicable_record(school)` and its score for the focus | folded into the INSERT |
| Verdict | 3519–3539 | `plan_alignment.stamp` (587): `recommendation_source.ssa`, `ssa_alignment`, `source_ssa*`, `recommendation_reason`; `link_recommendations` (only with a focus: Training Follow Up) UPDATEs `ssa_recommendation` to planned and appends `ssa.recommendation_planned` to the chain | folded into the INSERT; the link is its own UPDATE and audit row |
| **Day** | 3557–3561 | `costs_follow(principal)` around `_apply_schedule_cost_snapshot` → `_price_activity` (1142): `batch_poolable`; `attach_activity_to_batch` (`daily_visit_batches/services.py:603`): district type, `DailyVisitBatch … select_for_update()` by (owner, day), `_is_locked` ("This week's request has already been sent for approval. …"), `_rate_card` + `compute_daily_pool` (no rates → not pooled → `apply_to_activity` priced in the save), batch created with defaults if none, `activity.daily_visit_batch` saved, the day kept (`_price_when_the_save_ends`) | the join and the batch insert; the rate and lock reads are **pricing** (27.7) |
| Costs to follow | `costs_follow.py` 219–275 | `_assert_days_can_follow` (277): `_plan_day` for each kept day, `paid_transport_amounts`, `_money_under`, `_ask_money_guards`; then one `CostsToFollow` row (`steps.days = [[batch, owner]]`, weeks, months, notes, `asked_by`, role, `provenance` ip/agent/correlation/acting) and `_when_the_save_commits` (a thread prices it) | the row; the refusals are **pricing** (27.7); after commit Django settles it (27.2) |
| Ledger | `targets/ledger_sync.py` `_changed` on Activity save, `mark_when_committed` | `target_ledger_dirty` (owner, FY) upserted (`marked_at` on conflict) in its own statement once the save commits | the same upsert after commit |
| Model save | `activities/models.py:578` | `scheduled_date` normalised; `_link_training_intervention` (trainings only); `give_back_slots` and the Core slot sync find no slot for a non-Core school | — |
| Trail | `activities/schedule_trail.py:63` | a created row is only remembered: nothing written | — |
| Signals | `ssa/signals.py:20`, `projects/signals.py:53`, `business_transformation/signals.py:64` | none fire for a `scheduled` row with no project (`_link_planned_loan_verification_activity` matches the loan verification code only) | — |
| Live | `activities/live.py:116` | `plan.changed` to the realtime stream after the costs are in (Redis, no row) | not in shadow; the gateway must announce too before any cutover |
| Audit | 3566–3597, outside the atomic block | `audit.services.log` (`apps/audit/services.py:118`): `activity.scheduled`, the eleven-key payload plus the acting stamps (`_acting_for`, `audit_stamp_for`), the request's ip, agent and correlation; chain lock, seq, hash; `domain_event_log` projection | `internal/audit.Append` (it already writes both rows under `EDIFYAUD`); the acting stamps must be added |
| Tell | 3600 | `_notify_scheduled_owner`: the owner is the actor, so nobody is told | — |
| Hand-over | 3603 | `_ensure_partner_handover`: no partner, nothing | — |

**The row Go would insert** sets, besides its id and timestamps, the
columns `_create`, `apply_catalogue_snapshot`, `stamp` and the join leave
non-default, and every other NOT NULL column at its model default
(`evidence_status`, `ia_verification_status`, `payment_status`,
`reschedule_count`, `est_cost_cents` 0, `cost_missing`,
`attended_school_ids` `{}`, `environment`, `source`, the empty strings).
`est_cost_cents` and `cost_missing` are then the pricing's to set.

## 27.7 Where this piece stops, and what must be decided first

Built on this branch: the map above, the contract (27.4) and the writer
role (`platform/deploy/db/activities_roles.sql`), with the gateway-role test
and the staging check extended. **No save is ported or committed**: three
parts of the path are not a port of the save's own rules, and each needs a
decision before the save can be built.

1. **The pricing asks before the save.** Two of the save's refusals are
   pricing: `costing_service.preview`'s blockers (3137) and
   `_assert_days_can_follow` (`_plan_day`, paid transport, the finance
   guards), with `attach_activity_to_batch`'s rate card and week lock. Porting
   them ports the day planner and the finance guards, which 27.2 keeps in
   Django until M12. The alternative that keeps money in Django is a second
   internal, read-only Django endpoint ("would the pricing refuse this
   day?"), asked inside Go's transaction before commit. Either is a decision
   about where money's rules live.
2. **The school row lock.** `_create` holds `SELECT … FOR UPDATE` on the
   school (3215) so two saves cannot both pass the one-visit rule. Postgres
   needs an UPDATE right on some school column for that lock, and
   `dbguard.VerifyIdentity` refuses in staging any gateway role that can
   write any school column (`protectedTables`). The role file therefore
   does **not** grant it. Granting `UPDATE (updated_at) ON school` for the
   lock alone, and teaching the guard that one column, is a change to the
   production-protection rule.
3. **The acting stamps and the live announcement** are written by Django
   outside the save (`_acting_for` / `audit_stamp_for` on the audit payload;
   `plan.changed` on the realtime stream). Neither is in Go yet.

What is proved for the role, on `edify_gorn_test` (2026-11-12):
`TestTheActivitiesWriterRoleMakesTheVisitSavesWrites` makes every write of
27.1 as the gateway in one read-write transaction (rolled back): locking
and making the day, inserting the activity, reading the chain's tail and
appending to it, the domain event, the ledger upsert (which needs `SELECT`
on the three columns it names, found by this test) and the costs to follow,
and the recommendation update. `TestGatewayRoleCanNeitherWriteNorReadSecrets`
now also refuses changing an activity's status, price or day, a day's
figures, writing a cost line, removing days, costs to follow, ledger marks
or domain events, rescoring a recommendation, reading the costs'
provenance and locking a school. `dbguard.VerifyIdentity` refuses in
staging a role that can remove rows of the activity, day, costs-to-follow,
audit or event tables, or change an activity's lifecycle, price, owner,
school or day, a day's figures, or an audit row's seal or payload; the
gateway role passes it (`TestStagingIdentityCheckAcceptsOnlyTheReadOnlyRole`).
The role is applied to the test database by the suite's TestMain; it has
not been applied to the development database.

The shadow proof (27.4) has not been run for Go: there is no Go save to run.
