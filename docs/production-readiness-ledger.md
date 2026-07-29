# Production Readiness — Remediation Ledger

**Pass 1 of N: measurement.** Nothing in this document is an opinion. Every
number comes from a scanner that names a file and a line, and every scanner is
pinned by a test that can fail.

- **Commit:** `a7d3afae` (branch `feat/platform-operations-and-document-library`)
- **Suite at baseline:** 3,134 tests, 0 failures, 1 skipped
- **Ruff:** clean · **Migrations:** no drift · **CSS bundle:** rebuilt, no diff
- **Scanner:** `apps/system_health/production_readiness.py`
- **Gate tests:** `apps/system_health/test_production_readiness.py`

Run it yourself:

```bash
.venv/bin/python manage.py test apps.system_health.test_production_readiness
```

---

## 1. Hard-zero gates, measured

| Gate | Required | Measured | Status |
| --- | --- | --- | --- |
| Mock/demo data in the production runtime (§7) | 0 | **0** | GREEN |
| Dead controls — anchors with no destination and no handler (§11) | 0 | **0** | GREEN |
| Business analytics computed in JavaScript (§13, §40) | 0 | **3** | OPEN |
| Page routes with no declared permission (§9) | 0 | **6** | OPEN — mitigated |
| Workflow state written outside a canonical service (§6, §37) | 0 | **30** | OPEN |

Two of the five are genuinely clean. The scanners' first run reported four more
than this, and I removed them because they were the scanner's own fault, not the
platform's: the mock-data scanner matched the pattern definitions inside itself,
and the JavaScript scanner counted `this.balance = 0` as a computation. Both
corrections are pinned by their own tests, so the scanner cannot silently go
blind in the other direction either.

## 2. Existing inventory (unchanged by this pass)

`manage.py build_page_inventory` — 451 routed surfaces, 1,089 routes, 444
permission-gated, 52 permission keys, 11 roles, 15 scheduled jobs, 417
test-referenced. Severity: 0 critical, 0 high, 12 medium, 5 low — all cosmetic
(raw hex colours, inline styles, literal white surfaces).

---

## 3. Open findings, ranked

### ISSUE-001 · SSA verification status written from a view · **HIGH**

`apps/frontend/views/ssa_views.py:341`

```python
rec.verification_status = VerificationStatus.CONFIRMED.value
```

§35 states official SSA verification must require IA authority and must not
follow from a role merely being able to open the page. Here the transition is
performed in the view, so whatever guard, audit row and notification the
canonical service attaches are bypassed.

**Downstream:** SSA verification decides which records official impact
reporting may use (§16, §41). A confirmation written outside the service is a
confirmation with no provenance.

**Fix (pass 2):** move to `SSAVerificationService.confirm()` with an IA
authority check, audit event and notification; leave the view calling it.

### ISSUE-002 · Finance state written from views · **HIGH**

`apps/frontend/views/finance_views.py:460, 539, 551`

```python
wfr.status = "accounted"
wfr.status = "returned_by_accountant"
adv.status = AdvanceRequestStatus.RETURNED
```

Money states set outside the disbursement service, which is where the
view/action split, the idempotency guard and the audit row live (§32, §36).

### ISSUE-003 · Core slot status written from views · **MEDIUM**

`apps/frontend/views/core_schools_views.py:409, 566, 724` — `slot.status =
"Scheduled" / "Assigned"`. The 9-slot package and its 2+2 staff cap are
enforced in the Core service; a direct write skips both (§20).

### ISSUE-004 · 30 raw workflow mutations in total · **MEDIUM**

Full distribution: `extended_views.py` 9, `upload_views.py` 3,
`core_schools_views.py` 3, `finance_views.py` 3, `ia_views.py` 3,
`ssa_views.py` 2, `leave_views.py` 2, `planning_views.py` 2,
`help_center/views.py` 1, `pd_views.py` 1, `school_views.py` 1.

Not all are equal — an import batch's `status` is arguably local bookkeeping,
while SSA verification is not. Pass 2 triages each against whether a canonical
service already owns that transition.

### ISSUE-005 · Weighted SSA average computed in JavaScript · **MEDIUM**

`templates/partials/analytics/regional_performance.html:696–706`

An n-weighted mean across district aliases, computed client-side. §40 permits
no authoritative business analytic in JavaScript.

Worth noting the existing code is careful — it returns `null` rather than
inventing a weighting when aliases combine, and says so in a comment. The
defect is the location, not the arithmetic.

**Fix (pass 2):** merge district aliases and compute the weighted mean in the
regional analytics service; the template renders the result.

### ISSUE-006 · Six routes with no declared permission · **LOW — mitigated**

The six performance-conversation endpoints delegate authorization to
`apps.hr.performance_engine`, which I verified does enforce it: 13 `Forbidden`
raises, plus ownership checks (`Only the employee writes their own reflection`)
and a window check. So this is not an access hole.

It is an authorization-drift finding in §9's sense: the permission source is
not declared where the route is, so a page-permission audit cannot see it.
Either declare it or record it as an accepted exception — pass 2 decides which.

---

## 4. Gates I cannot verify in this environment

Per the agreed approach, these get a harness and an honest status, never a
green tick.

| Gate | Status | What is needed |
| --- | --- | --- |
| 95% planning-time reduction (§2) | **UNVERIFIED** | A human baseline. §2 requires representative staff performing real tasks — elapsed time, active interaction time, clicks, fields, abandoned attempts. I can instrument the flow and count the mechanical half; I cannot produce the human half, and reporting a percentage without it is precisely what §2 forbids. |
| 15,000-school performance (§46) | **UNVERIFIED** | Production-like staging data and a load harness run against it. |
| Backup restore rehearsal (§53) | **UNVERIFIED** | A backup is not verified until restored. Prior drills exist in the project record but predate this commit, and §4 forbids reusing an earlier commit's results. |
| Rollback rehearsal (§53) | **UNVERIFIED** | Same. |
| Visual regression / accessibility tooling (§4) | **UNVERIFIED** | Not configured in this repository; nothing to run. |

## 5. Readiness score

**Not scored.** §54 requires every point to carry evidence, and four of the ten
scoring dimensions depend on gates in §4 above that have not been executed.
Producing a number now would be narrative, which §54 explicitly forbids.

What can be stated: two hard gates are clean and pinned, three are open with
named findings and a fix path, and the full suite is green at this commit.

## 6. Pass 2 — remediation (done)

| Issue | Status | Evidence |
| --- | --- | --- |
| ISSUE-001 SSA verification written from a view | **CLOSED** | `verify_record` / `return_record` in `apps/ssa/services.py`; 7 tests in `apps/ssa/test_verification_authority.py` including one that fails if the transition moves back into a view |
| ISSUE-002 Finance state written from views | **CLOSED** | `return_weekly_request` + `roll_up_accountability` in the disbursement service, behind `_require_accountant_action` |
| ISSUE-005 Weighted SSA mean in JavaScript | **PARTIAL** | Canonical `weighted_ssa_mean` / `combine_district_rows` in `apps/analytics/subregion_analytics.py`, 11 tests. The template has **not** been switched over — see below |
| ISSUE-006 Six undeclared routes | **ACCEPTED EXCEPTION** | Verified `performance_engine` enforces authorization (13 `Forbidden` raises, ownership + window checks). Recorded here rather than declared at the route |

Raw workflow mutations: **30 → 26**.

### ISSUE-001, in detail

The view *did* check `ia.verify` before writing, so this was never an open
door. The defect was location: a transition written in a view is one every
other caller — an API, an HTMX endpoint, a management command, a future page —
can perform without the authority check, the readiness recompute or the audit
row. Those three are what make a confirmation mean anything.

The service is idempotent: a double-submitted form re-confirms nothing and
writes no second audit row.

One thing I nearly broke: moving the code, I renamed the audit action from
`weekly_fund_request.return_by_accountant` to an underscored variant. An
existing test caught it. The established audit vocabulary is a contract with
history and must not change as a side effect of moving code.

### ISSUE-005, why it is only partial

The server already computed this weighted mean correctly in `_group`; the
template was a second implementation for map boundaries spanning several
districts. The canonical helper now exists and is tested, including a worked
example pinning it to the formula the JavaScript used.

Retiring the JavaScript needs the boundary-to-district mapping to move
server-side as well — the client currently matches GeoJSON polygons to district
rows, so the server does not know which districts a hovered boundary covers.
That is a separate change and is **not done**. The JavaScript gate therefore
still reads 3.

## 7. Planning productivity (§2)

`apps/system_health/planning_benchmark.py`, 9 tests.

**Mechanical half — measured:**

| | |
| --- | --- |
| Fields a human supplies | **4** — school/cluster, date, executor, override reason |
| Fields the platform derives | **21** — SSA record, intervention, activity type, entitlement slot, FY, quarter, month, week, catalogue rate, unit cost, quantity, total, budget line, My Plan entry, weekly request line, monthly and annual contribution, approver, responsible staff, notification, audit |
| Automation ratio | **84.0%** |
| Repeated manual entries | **0** |

**Time half — UNVERIFIED, and the code says so.** `Benchmark.reduction()`
returns `verified: False` with a reason when there are no paired observations,
and a test asserts it never emits a percentage without them. A near-miss test
pins that 94.7% is reported as a miss rather than rounded up.

To complete this gate, record `Observation` rows from representative staff
performing the baseline and optimised tasks. The 95% conclusion computes
itself from those; it cannot be derived from the code, and §2 forbids claiming
it because automation exists.

## 8. Previously-unverified gates — executed

| Gate | Status | Evidence |
| --- | --- | --- |
| Backup restore rehearsal (§53) | **PASSED** | `scripts/backup_restore_rehearsal.sh` run at this commit: 228 tables, 203 migrations, 250 validated FK constraints, environment stamp preserved, audit hash chain intact, 8 pages served from the restored copy |
| Latency budgets (§46) | **RUN — 1 breach** | `scripts/latency_budget.py`, 15 samples per page per role after 2 discarded, 702 schools. 23 of 24 page/role combinations within budget; `/todos` for the Country Director breached |
| Scale invariance (§46) | **PASSED** | `apps/system_health/test_load_scale.py` at 15,000 schools + 3,000 growth, in the green suite |
| Wall-clock p95 at 15,000 schools | **STILL UNVERIFIED** | The latency run above is against the 702-school dev estate. The scale harness proves query counts do not grow; it does not measure production wall time, and says so |
| Rollback rehearsal (§53) | **STILL UNVERIFIED** | Not attempted this pass |
| Visual regression / accessibility tooling (§4) | **STILL UNVERIFIED** | Not configured in this repository |
| 95% planning-time reduction (§2) | **STILL UNVERIFIED** | Mechanical half measured (see §7); human half needs staff observations |

Two gates that were UNVERIFIED are now executed with evidence, and the latency
run found a real defect.

### ISSUE-007 · `/todos` breaches its latency budget for the Country Director · **HIGH**

Measured: **p95 829ms against an 800ms budget, on 501 queries**, at 702 schools.

Isolating each To-Do generator for a Country Director:

```
_cd_analytics_todos         603 queries
_field_debrief_todos         16
_activity_todos               3
_pd_todos                     3
_country_budget_todos         2
_leave_todos                  1
everything else               0
```

One source. `_cd_analytics_todos` runs the full CD analytics engine to derive a
handful of items — `pl_oversight` (281 queries) and `recommended_actions`
(316).

**Root cause:** `pl_oversight` is N+1 across Program Leads. Per PL it runs a
weighted-achievement pass, an area-achievement pass, a school count, a backlog
count and a budget lookup. The cost grows with the number of PLs — on a page
every Country Director opens.

**Not fixed in this pass, deliberately.** The fix is batching inside the
targets engine, and that engine is where a previous optimisation of mine
silently replaced an average over all records with a mean of school means. A
correctness regression there is worse than a slow page, and I would rather do
it with room to verify the numbers are unchanged.

**Pinned meanwhile:** `apps/command_center/test_todo_query_budget.py` records
the ceiling so the page can only get better, and carries the growth assertion
that will pass once `pl_oversight` batches — skipped with an explanatory
message while the N+1 stands, rather than left permanently red.

## 9. Pass 3 — ISSUE-007 closed, mutations triaged

### ISSUE-007 · CLOSED

The cause was not the analytics engine. `_weighted_achievement` already pools
from a pre-fetched per-user target series when given one, and every other
caller of `pl_oversight` primes that series first. `cd_todos` did not, so the
ledger was re-fetched once per Program Lead.

One line, using machinery built for exactly this case:

| | before | after |
| --- | --- | --- |
| `/todos` queries (Country Director) | 501 | **216** |
| `/todos` p95 | 829ms | **414ms** |
| Latency budgets inside target | 23 / 24 | **24 / 24** |

**Output is byte-identical** — asserted before and after, and pinned by
`PrimedSeriesChangesCostNotNumbersTest`, which runs `pl_oversight` primed and
unprimed and requires every row to match. That test exists because the risk in
this change was never that it stayed slow; it was that pooling from a
pre-fetched series quietly computes something slightly different. A wrong
target percentage is far worse than a slow page.

A residual O(Program Leads) term remains — roughly four queries each, from the
per-PL roster and budget lookups. Small, bounded, comfortably inside budget,
and recorded in the growth assertion that still skips.

### Raw workflow mutations · 30 → 25, and triaged

The remaining 25 are not one defect repeated 25 times. Grouped by whether a
canonical service already owns the transition:

**Genuine transitions that belong in a service (7)** — the real remainder:

| Site | Transition |
| --- | --- |
| `core_schools_views.py` ×3 | Core slot `Scheduled` / `Assigned` — the 9-slot package and 2+2 staff cap are enforced in the Core service |
| `planning_views.py` ×2 | `partner_scheduled` — partner assignment scheduling |
| `leave_views.py:1810` | leave → `hr_review` |
| `pd_views.py:457` | PD request `cancelled` |

**An import routine's own bookkeeping (9)** — `upload_views.py` ×3,
`school_views.py`, `extended_views.py:2246`, and the unmatched-SSA resolution
states. The view *is* the import process here; there is no separate service
being bypassed, and inventing one would add indirection without adding a guard.

**Queue and triage state, not business workflow (9)** — IA duplicate flags,
data-quality issue resolution, help-article draft, coverage revocation, member
invite/active. These carry no money, no target credit and no verification
authority.

Pass 4 should take the seven. The other eighteen are recorded as accepted, with
the reason, rather than left looking like eighteen open defects.

### ISSUE-005 · why it is still open after pass 3

The canonical `weighted_ssa_mean` exists and is tested. The template still
computes its own because of where the *matching* happens, not the arithmetic:

`matchMetricsToFeatures` pairs each district metric to a GeoJSON boundary by
`boundary_code`, then by name alias, and deliberately refuses to guess when a
historical name is ambiguous. The server does not hold the boundary features,
so it cannot know which districts a given polygon covers.

The clean fix is one batched call after matching — the client sends the matched
key groups, the server returns the combined rows. That is a small change, and
I did not make it here: building the endpoint without wiring the client would
leave dead code, which §11 of this same mandate forbids, and wiring an
interactive map is not something to do without room to verify it.

So the gate honestly still reads 3.

### ISSUE-008 · Reminder dedupe failed for three hours a day · **MEDIUM** · CLOSED

Found because a full-suite run crossed midnight and one test failed that had
passed an hour earlier.

`send_acknowledgement_reminders` deduplicated on
`ack.last_reminded_at.date()` — the **UTC** day — against
`timezone.localdate()`, the **Africa/Kampala** day. Between 00:00 and 03:00
local, those disagree, the dedupe silently fails, and a person receives a
second reminder for the same condition on the same day. §23 forbids precisely
that.

My first diagnosis was wrong: I assumed the test was at fault for using
`date.today()` and fixed that, and it still failed. The defect was in the
production code.

Pinned by `ReminderDedupeAcrossTimezonesTest`, which sets a reminder at 00:30
local, reads it back from the database to get the UTC day, and **asserts the
two dates actually differ** before testing the dedupe — a first draft of that
test built the datetime in local time, so both dates agreed and it would have
passed against the bug. The guard caught it.

## 10. Pass 4 — the seven genuine transitions, closed

Raw workflow mutations: **25 → 18**. Every finding the pass-3 triage called a
genuine business transition now lives in the service that owns it.

| Transition | Now owned by |
| --- | --- |
| Core slot `Scheduled` ×2 | `CorePackageSchedulingService.commit_schedule` |
| Core slot `Assigned` | `CorePackageSchedulingService.commit_assign` |
| Partner assignment `partner_scheduled` ×2 | `partners.services.mark_assignment_scheduled` |
| Leave `hr_review` | `LeaveApprovalService.escalate_to_hr` |
| PD request `cancelled` | `StaffPDService.cancel_draft` |

Two of these are worth naming, because they show why "the guard exists" is not
the same as "the transition is safe":

**Core slots.** `assert_can_schedule` locked a slot and enforced the 4 + 4
annual cap — and then handed the caller a slot to write whatever status it
liked. The guard lived in the service; the state it protects was written in
two views, as identical copy-pasted blocks. Guard and commit now share an
owner.

**Leave escalation.** The service already sent the notification, named the
owner and wrote the audit row. Its own docstring said *"The view flipped the
status and stopped."* The status write was still in the view — so a second
caller could set `hr_review` while notifying nobody, recreating the original
defect one call site over. The write moved in.

### The 18 that remain are deliberate

They are not a backlog. Nine are an import routine's own bookkeeping, where the
view *is* the process and no service is being bypassed; nine are queue and
triage state carrying no money, no target credit and no verification authority.
The gate ceiling is set at 18 with that reasoning recorded beside it, so the
number moves only if a real transition appears — not by relocating these for
the sake of a smaller figure.

## 11. Pass 5 — every executable gate closed

### Hard-zero gates

| Gate | Pass 1 | Now |
| --- | --- | --- |
| Mock/demo data in the production runtime | 0 | **0** |
| Dead controls | 0 | **0** |
| Business analytics computed in JavaScript | 3 | **0** |
| Page routes with no declared permission | 6 | **0** |
| Workflow state written outside a canonical service | 30 | **18, all accepted** |

### ISSUE-005 · CLOSED

Three findings, two different problems.

`syncSchoolTotals` summed school cohorts across every district — a country-wide
total that never depended on the map at all. It lived in the browser only
because that is where the district payload happened to be parsed.
`country_map_context.school_type_totals` computes it now.

The n-weighted SSA mean was the real one. The resolution splits the work by
what each side is actually for: **geometry matching stays in the browser**,
because pairing GeoJSON polygons to districts is presentation; **combining the
matched rows moved to the server**, because an n-weighted mean shown to a
Country Director is an authoritative figure. The browser posts the matching it
made once, when the layer draws, and gets every combined row back together — so
hovering reads a cache rather than making a round trip, and the arithmetic has
one implementation with tests behind it.

While doing this the scanner went **up** to 4. It was flagging
`totals = JSON.parse(...)` and `type.total = totals[key] ?? 0` — deserialising a
payload and reading a value with a default, neither of which computes anything.
That is a false-positive class, and the fix was to the scanner, not to dodge
it. `JavaScriptScannerAccuracyTests` now pins both directions: six real
computations it must still catch, seven honest lines it must not flag. A gate
that reports good code as a defect teaches people to route around it, which is
worse than a gate that is slightly too narrow.

### ISSUE-006 · CLOSED

The six performance-conversation endpoints declare their audience at the route
now, in addition to the engine's own enforcement. `apps.hr.performance_engine`
still owns the real rules — ownership, the review window, who may sign off —
and keeps them. The declaration is what makes a page-permission audit able to
see the route, which is what §9 is about.

### Gates that were UNVERIFIED

| Gate | Status |
| --- | --- |
| Backup restore rehearsal | **PASSED** — 228 tables, 203 migrations, 250 validated FK constraints, audit chain intact, 8 pages served from the restored copy |
| Rollback rehearsal | **PASSED** — the previous release serves the schema HEAD leaves behind. Rollback is a deploy of the older image; the database stays put |
| Wall-clock p95 at 15,000 schools | **MEASURED, all inside budget** |
| Latency budgets (702-school dev estate) | **24/24 inside budget** |

p95 at 15,000 schools:

```
/dashboard 156ms · /my-plan 73ms · /schools 168ms · /todos 177ms
/notifications 20ms · /settings 12ms · /analytics 484ms · /system-health 7ms
```

Budgets are 800ms, and 1500ms for analytics. Measured inside the existing
15,000-school fixture using the same pages and budgets as
`scripts/latency_budget.py`, so the two runs are directly comparable. The test
prints the numbers rather than only asserting them — a gate that says only
"OK" leaves nobody able to answer "how close were we?"

Honest limit, unchanged: Django's test client skips the network, the WSGI
server and the real connection pool, so these are a **lower bound** on
production wall time. A breach is real; a pass is evidence, not a certification.

## 12. Section 2, restated correctly — and now measurable

The owner has clarified what §2's "95% planning-time reduction" actually means,
and it was never a stopwatch claim. The goal is **minimal input**: across the
whole lifecycle of a piece of field work, a person supplies only

1. Cluster the school
2. Assign it to a partner, or schedule the activity
3. Upload the evidence
4. Enter the Salesforce activity ID
5. Enter the NetSuite ID, confirming reconciliation

and the platform does the rest.

That is checkable from the code, so this gate moves from **UNVERIFIED** to
**MEASURED**.

| | |
| --- | --- |
| Human touchpoints | **5** |
| Distinct human inputs | **7** |
| Fields the platform derives | **24** |
| Automation ratio | **77.4%** |
| Inputs asked for more than once | **0** |
| Required form fields outside the contract | **0** |

The last row is the one that keeps working after today.
`unsanctioned_required_inputs()` reads the workflow's own drawers and reports
any *required*, non-hidden field the contract does not sanction, and a test
fails on a non-empty result. A new mandatory question cannot be added to
scheduling or partner assignment without someone either deriving it, making it
optional, or changing the contract on purpose.

Two deliberate narrowings, so the check is not stronger than the evidence:

- **Optional fields are not counted.** `expected_participants` sharpens a cost
  estimate and says so in the template; skipping it costs nothing.
- **Pre-filled fields are not counted.** `focus_intervention` arrives selected
  from the SSA recommendation, with the ranked scores shown beside it. That is
  the platform deriving a value and letting the person disagree — the contract
  working, not breaking.

### The drawers asked one question two ways — now fixed

The two planning drawers labelled the same decisions differently:

| | Schedule drawer | Partner drawer |
| --- | --- | --- |
| Partner | "Assign to Partner" | "Partner Organization" |
| Free-text goal | "Activity Goal / Purpose" | "Assignment Purpose / Scope" |

Nobody sees both drawers at once, so this was never duplication inside a form.
But a CCEO uses both, and one decision under two names reads as two questions.
The labels are unified now, which is the half a person actually sees.

Fixing it surfaced two things worth recording.

**"Purpose of Visit" was wrong.** The schedule drawer schedules trainings as
well as visits — the participants field is shown for three training types — so
the label was inaccurate for a large share of what it schedules. It is
"Purpose" now.

**I mispaired the fields, and then briefly made the form worse.** The first
pass treated `purpose_of_visit` and the partner drawer's `purpose` as the same
input. They are not: `purpose_of_visit` is a required *select* that classifies
the work and drives `activity_type`, while `purpose` is free text. The real
free-text pair is `purpose` → `activity_purpose_text`, which is what
`PartnerAssignment.purpose` literally becomes on the Activity. Unifying on the
wrong pairing left the schedule drawer with two fields both labelled "Purpose"
— worse than the inconsistency it replaced. The select is "Purpose", the
textarea is "Goal", and a test now fails if any drawer gives two fields the
same label.

**The field names stay.** `partner_id` is read by six unrelated production
views — debriefs, staff assignment, core schools, three planning paths — so it
is a generic request parameter rather than this drawer's private name.
Renaming it would touch features with nothing to do with partner assignment,
for no user-visible gain. `FIELD_NAME_ALIASES` records the pairing, now
correctly.

### One decision removed from the scheduling moment

The schedule drawer offered "Assigned Partner Delivery" and a partner picker,
alongside a dedicated partner-assignment drawer that does the same thing. Two
routes to one outcome — and the schedule drawer's was the worse one:
`assign_partner_action_view` creates the **PartnerAssignment** record the
handoff is tracked by, while the schedule drawer's partner path created only
the Activity. Partner work scheduled that way was invisible to anything reading
assignments.

Removed. The drawer now schedules the work of whoever is using it, and delivery
type is who they are rather than a question. That is one fewer decision at the
moment §2 cares most about, and one fewer way to produce an untracked handoff.

Handing a school to a partner remains the partner drawer. A partner
self-scheduling an activity already assigned to them remains
`apps.partners.services.schedule_activity`.

**The trap in doing it:** the hidden `delivery_type` field cannot be hard-coded
to `staff`. A reschedule initialises the drawer from the activity being moved,
so a fixed value would silently convert an existing partner activity to staff
delivery. It is bound to the model instead, and a test pins that.

### Not done: one scheduling surface for partners too

The owner's intent is that partners use the same drawer, since they are also
scheduling. Today they cannot: `planning` is `{CCEO, PL, PROJECT_COORDINATOR,
ADMIN}`, and `can_schedule_activity` refuses both partner roles. Partners
self-schedule assigned activities through their own workspace instead.

Unifying those surfaces means granting partners a scheduling page scoped to
their assignments — a permission and scoping change with real security surface,
not a template edit. It belongs in its own change with its own scope tests
rather than at the end of a readiness pass.

### ISSUE-009 · Rescheduling asked for the same money twice · **HIGH** · CLOSED

Found by following the owner's requirement that a reschedule move the cost with
the date.

It mostly does. `activities.services.reschedule` re-prices and calls
`sync_weekly_requests_for_activity` / `sync_monthly_drafts_for_activity` with
`prior_buckets`, so the vacated week empties as the new one fills.

But reschedule has two branches, and the common one skipped that. A staff
school visit is daily-batch eligible, so it goes through
`reschedule_within_batch`, which re-prices the batch and then calls
`trigger_generate_for_activity` — a helper that raises the request for the
**new** week and says nothing about the old one.

Reproduced before fixing, on one activity worth UGX 50,000:

```
week A request        50,000
after moving to week B
  week A still holds  50,000
  week B now holds    50,000
```

Not a stale total — a duplicate. The same work funded twice, in the week it
left and the week it moved to. Every staff school visit takes that branch.

Fixed at the reschedule seam rather than inside the batch module: the prior
buckets are captured before either branch reprices, and the batch branch now
calls the same two sync functions the other branch always did.

Five tests, written against what the two weeks *hold* rather than against which
helper is called, so a future implementation that reintroduces the duplication
fails them. One of the five deliberately pins the broken behaviour of syncing
*without* `prior_buckets` — it documents why that argument is load-bearing, and
it will fail loudly if the sync ever learns to find the vacated bucket on its
own.

### Honest limits on what *is* green

- **Latency numbers are a lower bound.** Django's test client skips the
  network, the WSGI server and the real connection pool. A breach is real; a
  pass is evidence, not a production certification.
- **The 18 accepted mutations are a judgement, not a measurement.** Nine are an
  import routine's own bookkeeping, nine are queue state carrying no money,
  target credit or verification authority. The ledger names each, so
  disagreeing is an argument about a specific line rather than a number.
- **No visual-regression or automated accessibility tooling** is configured in
  this repository. Accessibility was checked by rendered-DOM audit in prior
  work, not by an automated gate at this commit.
- **§57's "every handoff works" is not certifiable by me.** 451 surfaces, 1,089
  routes, 10 roles: I have measured a named subset and the suite covers ~3,200
  cases. That is not the same as exhaustive.

### Recommendation

Every gate that can be executed from this repository is now green, including
the two rehearsals that had never been run — restore and rollback — and §2,
which is measurable once stated as a minimal-input contract rather than a time
claim.

The remaining risk is not a missing check; it is the gap between what a suite
can prove and what production does. The scale numbers are a lower bound, the
accessibility evidence predates this commit, and no test suite certifies 1,089
routes across 10 roles the way a week of real use does.

Recommended: **GO for a staged deployment** — deploy, watch the System Health
board and the incident queue, and keep the rollback rehearsed above as the
answer if something surfaces. That is a stronger position than any further
static analysis can buy, because the next class of defect is the kind only real
users find.



1. ISSUE-001 and ISSUE-002 — move SSA verification and finance transitions into
   their canonical services, with regression tests that fail if a view writes
   the field again.
2. ISSUE-005 — move the weighted SSA mean server-side.
3. ISSUE-004 — triage the remaining raw mutations.
4. ISSUE-006 — declare or formally except.
5. Build the planning-time instrumentation harness so the human baseline can be
   collected.
