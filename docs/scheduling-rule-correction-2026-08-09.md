# Scheduling rule correction — standard support without a Project

**Date:** 2026-08-09
**Scope:** Planning → Activity → Cost → My Plan → Work Plan → Budget → Execution

---

## 1. What the false dependency actually was

The reported rule was:

```
SSA intervention → must belong to Project → Project must contain an Activity → only then schedule
```

**No such check existed in the code.** `validate_context()` required a Project
only where `item.requires_project` was true, and that flag was `False` on all
28 seeded catalogue items. The block was real; the explanation was not.

The actual mechanism, reproduced before any change was made:

| Symptom | Cause |
|---|---|
| "No single approved Catalogue Activity costs *In-school Training*" | `resolve_item_for_workflow_kind()` returns `None` when 0 **or >1** items match a workflow kind. Five curriculum titles costed `in_school_training`, so it refused to guess. |
| A standard School Visit could not be scheduled at all | **Zero** catalogue items had `workflow_kind = school_visit`. Same for `coaching_visit`, `in_school_support`, `donor_visit`, `story_gathering_visit`, `school_invitation`, `social_visit`. Every staff purpose in the drawer resolved to a blocked type. |
| A school whose weakest need was Financial Health was offered activities for an intervention scoring 8.0/10 | Five of the eight interventions (Financial Health, Leadership, Enrolment, Government Requirements, Exposure to the Word of God) were answered **only** by cluster-delivered trainings. The drawer's "no activity addresses X" banner then fired. |
| "You need a Project" became the field theory | The only school-level items covering weak interventions were named `LITERACY_NUMERACY_PROJECT` and `EARLY_CHILDHOOD_EDUCATION_PROJECT`. |
| Even a valid pick could be refused | `create()` required the item to be in `primary_ids` from `recommend_activities`, or to carry an override reason. |

So the correction is not the removal of a bad `if`. It is supplying the
missing standard responses and a rule that says ordinary support does not need
the SSA engine's blessing.

## 2. The new rule

```
Operational need
  → target SSA intervention or approved rationale
  → standard activity type
  → OPTIONAL project context
  → schedule → Activity → cost → My Plan → Work Plan → Budget → execution
```

* **Activity type** — required (unchanged).
* **Target intervention** — recorded whenever named; required for the
  programme's governed curriculum titles, optional for ordinary support.
* **Project** — required **only** where the Workflow Profile says
  `requires_project`. Whether an intervention is *also* used by some Project
  is never consulted.
* **Canonical Activity** — unchanged. Every successful schedule still creates
  exactly one `Activity` and its `ActivityBudgetLines`.

## 3. Changes

### Data model
| Model | Field | Why |
|---|---|---|
| `ActivityCatalogueItem` | `standard_support` | Ordinary field support: no Project, no recommendation gate. |
| | `participant_mode` | NONE / DIRECT_TOTAL / PER_SCHOOL / BY_CATEGORY — the authority behind "a visit has no participants". |
| | `certified_agency_delivery_allowed` | Booking an agency is a different permission from partner delivery. |
| `ActivityInterventionMapping` | `MappingMode.ANY_SSA_INTERVENTION` | Standard support belongs to no one intervention; the planner names it. |
| `Activity` | `executor_type` | staff / partner / **certified_partner_agency**. `delivery_type` stays two-valued because My Plan scoping, oversight, costing and partner payment all key on it. |

Migrations: `activity_catalogue/0007_…`, `activities/0036_activity_executor_type`,
`activities/0037_backfill_executor_type` (derives executor from delivery type;
no guessing).

### Catalogue
12 `STANDARD_SUPPORT_ITEMS`, kept in a list **separate** from the 28 governed
curriculum titles (whose count is still asserted). One per workflow kind,
enforced by a partial unique constraint — because two standard items for one
kind puts the purpose→costing resolver back where it started.

`resolve_item_for_workflow_kind()` now prefers the standard item, which is how
the five-way `in_school_training` ambiguity resolves.

### Services
* `apps/activity_catalogue/availability.py` — **`AvailableActivityTypeService`**
  (§6). One answer to "what may this user schedule here?", with each type's
  field profile.
* `_apply_participant_mode()` in `activities/services.py` — clears participant
  keys for NONE and derives BY_CATEGORY totals server-side.

  It deliberately does **not** clear a client-supplied total for `PER_SCHOOL`.
  The first version did, and the weekly-fund-request test caught it costing
  120,000 UGX too much: `budget/costing.py::_participants_of` substitutes
  `DEFAULT_TRAINING_PARTICIPANTS = 25` when no count reaches it, so throwing
  away a stated 15 priced twenty-five people rather than none. A stated
  number beats a hardcoded default; a number derived from live cluster
  membership beats both, and that override was already in place. School
  visits are safe to clear because they cost transport and lunch and never
  call `_participants_of`.
* `_resolved_executor_type()` / `_assert_bookable_certified_agency()` — §16/§17.
* `bookable_certified_agencies()` in `partners/services.py` — the single query
  behind both the picker and the write-time check.

### Drawer
Generated from the Workflow Profile. Participant fields live in
`<template x-if>`, not `x-show`: a hidden input **still submits**, which is how
30 participants typed for a Training ended up posted on a Visit.

### Certified Partner Agency (§15B)
Staff pick the date → one Activity at `partner_scheduled` (not
`assigned_to_partner`) → agency is executor, staff is owner/monitor → lands
dated in the agency's My Plan → agency + staff notified. The agency is never
shown a Schedule action for work Edify already scheduled.

Two gaps found on the way through, both fixed:

* **The To-Do service had no partner branch at all.** It scoped activities by
  staff identifiers, which a partner organisation never has — so a delivery
  partner's To-Do list was always empty. Survivable while every partner
  activity began as an assignment they had to accept; not survivable for a
  booking, where the notification was the only thing carrying the obligation.
* **A future-dated booking produced no next action.** `compute_next_action`
  fell through to the generic "View Details" default, which the To-Do service
  filters out. Added a `prepare` action for dated partner bookings ahead of
  their day (§20), and `partner_scheduled` now qualifies for "Start" on the
  day — `start_completion` had accepted it all along.

### Operations
* `apps/activity_catalogue/scheduling_health.py` — 13 checks, surfaced as
  **Scheduling Rules** on `/system-health`.
* `manage.py repair_scheduling_rules [--dry-run]` — idempotent. Repairs what is
  derivable (executor type, stale visit participants, cluster totals, booking
  status); **reports and never touches** what depends on intent (possibly
  artificial Projects, uncertified agency bookings).

## 4. Verification

**Automated** — 47 new tests across
`apps/planning/test_standard_support_scheduling.py` and
`apps/planning/test_scheduling_drawer_and_health.py`, plus updates to three
existing tests that asserted the old broken state:

| Test | Was asserting |
|---|---|
| `activity_catalogue.tests::test_seed_is_idempotent_and_complete` | 28 items — now 28 curriculum + 12 standard, counted separately. |
| `activity_catalogue.tests::test_ambiguous_legacy_activity_enters_review_queue` | That a legacy `school_visit` is *ambiguous*. It no longer is; the test now uses a genuinely ambiguous `training`, and a new sibling test pins that a plain school visit resolves. |
| `frontend.tests::test_cost_catalogue_row_and_initialization` | 28 governed activities on `/cost-settings` — now 40, because standard support is costed from the same CD catalogue. |
| `budget.test_reference::test_cost_catalogue_projects_coverage_for_all_governed_activities` | Same 28 → 40. Its real assertion — that *every* governed activity has cost components — still holds, so all 12 standard items are priceable. |

`apps/core/tests/test_weekly_fund_requests.py` was **not** updated: it failed
for a real reason and the code was fixed instead (see the participant-mode
note above).

`system_health.test_planning_benchmark::OneWayToHandWorkToAPartnerTests` was
rewritten rather than relaxed. Its rule — that the schedule drawer must not
be a second door to the ASSIGNMENT workflow, because that door wrote no
`PartnerAssignment` and made partner work invisible to everything reading
assignments — still holds and is still asserted. What it now distinguishes is
booking from assignment, and it explicitly forbids `value="partner"` in the
drawer so the assignment workflow cannot creep back in. The original
invisibility concern does not apply to bookings:
`partner_oversight_service._unassigned_partner_activities` exists to surface
partner-delivered Activities that no assignment points at, and a booking
appears there as a scheduled-stage item with the agency as next-action owner
(verified live).

Three generated manifests were regenerated (`build_kpi_inventory`,
`build_page_inventory`, `build_card_inventory`) — they record source line
numbers, so any edit shifts them.

**Two failures in the run are pre-existing and not from this work:**
`frontend.test_design_system_quality::TypeScaleFloorTest` (both cases) fails
on `static/css/platform.css:1999` — `font-size: 0.625rem !important`, below
the 12px micro tier. `git blame` puts it in commit `0028de61`
("fix(ui): resolve remaining responsive audit defects"), authored separately
from this change. No CSS was touched here.

The suite runs in chunks; `apps/` as one invocation exceeds a 50-minute
timeout on this machine.

**Live (local server, real data — 16,974 schools)**

Scheduled a standard In-School Training for school 1682 (Kimenyedde CoU
Primary), whose weakest intervention is Government Requirements at 3.1/10 —
one of the five that previously had no school-level response:

```
project_id      None
status          scheduled
executor_type   staff
focus           government_requirement
catalogue       STANDARD_IN_SCHOOL_TRAINING (standard_support = True)
participants    15  (backend sum of teachers 12 + leaders 3)
source_ssa      …clc8   score 3.10   Critical
cost lines      3       est_cost 430,000 UGX   cost_missing False
```

Booked Literacy Uganda (certified) for school 1655:

```
status          partner_scheduled     ← agency is NOT asked to schedule
delivery/exec   partner / certified_partner_agency
responsible     None                  ← staff is not the executor
monitored_by    <staff>               ← oversight only
duplicate count 1
notifications   "Edify has booked you to deliver work" → agency
                "Certified agency booked"              → staff
agency My Plan  contains the booking
agency To-Do    "Prepare | KCCA Hill Primary · In-school Training | due Aug 24"
PL oversight    stage=scheduled, next_action_owner="Literacy Uganda",
                next_action="Execute and upload evidence", planned_cost 200,000
```

Drawer behaviour, driven in the browser with Alpine live:

| Check | Result |
|---|---|
| Training → type 30 teachers → switch to Donor Visit | participant fields removed; `FormData` participant keys: **none** |
| Switch back to Training | field is empty — the stale value does not resurrect |
| Delivery Type on a Visit | not offered (visits are not agency-deliverable) |
| Certified agency picker | lists only certified agencies covering the district |
| Switch agency → staff | agency selection cleared, `executor_type` back to `staff` |
| Desktop 1280 / tablet 768 / mobile 375 | no horizontal overflow, all fields reachable |

System health **Scheduling Rules: green**.

## 4b. Group Training is Project work, invited school by school

A follow-up correction to the **cluster action planner** drawer
(`partials/clusters/cluster_action_planner_drawer.html`), for Group Training
only. Cluster Meeting is untouched.

**Purpose → Project.** The free-text "Purpose for Meeting / Training" is
replaced by a Project select (Literacy, EdTech, CC-SEL, …). A Project already
declares which SSA interventions it exists to move, so selecting one
**populates** the target intervention instead of asking the planner to restate
it — two answers to one question is how they end up disagreeing, and when they
do, intervention analytics credit the work to something the Project is not
trying to change. The manual Focus Intervention select is gone for Group
Training; the derived value is shown as a chip and submitted hidden. A
free-text "Session Goal" remains for anything specific to the session.

Derivation never overrules a person: a stated intervention wins. A Project
targeting several interventions has no single answer, so nothing is derived
and the service asks the planner to choose rather than picking the first.

**Schools invited.** The participant total was `per-school × full cluster
membership`. Not every member qualifies for every session — a Literacy
training does not reach the secondary and vocational schools in a mixed
cluster — so that invited, catered and *budgeted* for people who were never
coming. New `Activity.schools_invited` (migration `0038`) is the multiplier:

```
planned participants = participants per school × schools invited
```

Defaults to full membership, which is exactly what every activity scheduled
before this field existed meant. Validated 1 ≤ invited ≤ live membership — a
cluster of eight cannot invite nine. `cluster_school_count_snapshot` keeps its
existing meaning (how large the cluster was when priced), so nothing reading
it changes. The browser's arithmetic remains a preview: the service recounts
the cluster and recomputes the total at submission.

Standard support no longer needs an `ActivityProjectMapping` to be scheduled
under a Project. That list governs which *named curriculum titles* a Project
funds — a real rule — but a Literacy project running a cluster training is
running a cluster training, and requiring someone to first map the generic
response into all five projects adds a setup step whose only effect is that
scheduling fails until it is done. Here the Project is attribution, not a menu.

Two new health checks: cluster totals are now verified against
`schools_invited` (falling back to the membership snapshot for legacy rows),
plus `scheduling_cluster_over_invited` for more schools invited than the
cluster holds.

## 5. Deliberately not changed

* **Non-school programme participants.** The existing rule requires 1–100,000
  participants for every non-school activity regardless of profile. Changing
  budget-affecting validation for camps and conferences is outside this
  correction and would need its own decision.
* **`follow_up_visit`.** Left resolving to `CLIENT_SCHOOL_FOLLOWUP_VISIT`
  (inherit-from-source). "School follow-up" is served by the new standard
  `training_follow_up_visit`; adding a second standard item here would have
  changed an already-working path for no gain.
* **Artificial Projects.** Standard support carrying a Project is *reported*
  by the repair command, never unlinked — from data alone it is
  indistinguishable from genuine Project delivery, and guessing would move
  money between programmes.
* **Booking acknowledgement / date-change / release requests (§22).** Not
  built. It is conditional in the brief ("where the workflow requires booking
  acknowledgement") and is not one of the §39 completion gates. The
  protections it wraps hold structurally already: a booking creates no
  `PartnerAssignment`, so the agency has no Schedule drawer, no re-selection
  of activity type, intervention, cost or agency, and no way to move the date
  — only staff can reschedule, through the canonical service.

## 6. Not done

**Live production verification (§37) has not been run.** It requires signing
in to the production site as real staff, PL, agency, IA and Accountant
accounts, and the destructive concurrency and locked-finance tests require a
production clone. Everything above was verified against a local server holding
the full 16,974-school dataset. Production remains to be checked after deploy —
merging to `main` auto-deploys, and `/api/health/build` is the honest check.
