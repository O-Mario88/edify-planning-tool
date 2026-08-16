# Edify Planning & Monitoring — Platform Guide

*The end-to-end reference for what the platform is, how it is built, and how
work flows through it. Written 2026-08-14 against the live codebase (509
routed surfaces, 914 routes, 11 roles, 70 permission keys, 5,000+ automated
tests). Companion documents: [PRODUCT_PRINCIPLES.md](PRODUCT_PRINCIPLES.md)
for the design doctrine, [platform-page-inventory.md](platform-page-inventory.md)
for the generated per-page catalogue, [runbooks.md](runbooks.md) for
operations, [OPERATIONS_ROADMAP.md](OPERATIONS_ROADMAP.md) for where the
platform is going, and [STAFF_TIME_STANDARD.md](STAFF_TIME_STANDARD.md)
for the measured 15-minute staff-time ceiling.*

---

## 1. What the platform is

Edify Planning & Monitoring runs Edify Uganda's school-support operation:
planning and budgeting field work across ~17,000 schools, executing and
verifying that work (visits, trainings, assessments), moving and accounting
for the money behind it, and rolling verified results up into targets,
performance and country strategy.

One principle governs every number on every page: **nothing is fabricated**.
Dashboards bind to real queries; empty states say honestly what would fill
them; planned figures are never displayed as achieved ones; and achievement
credit flows only from work that Impact Assessment has verified. The three
product tests every feature must pass — *Simple, Healthy, Focused* — are
defined in [PRODUCT_PRINCIPLES.md](PRODUCT_PRINCIPLES.md).

---

## 2. Technology and architecture

| Layer | Choice |
|---|---|
| Backend | Django 5 (Python 3.13), PostgreSQL 16, Redis (cache; degrades to per-process LocMemCache) |
| Frontend | Server-rendered Django templates + htmx (partial swaps) + Alpine.js (local interactivity) + Tailwind CSS (compiled to `static/css/main.css`) + per-page CSS under `static/css/pages/` |
| Charts | ApexCharts, initialised via Alpine `x-init` with destroy guards |
| API | A thin DRF layer under `/api/*` (296 routes) coexists with the primary HTMX page layer |
| Jobs | 18 scheduled jobs via a dedicated `runscheduler` service (see [scheduler-deployment.md](scheduler-deployment.md)) |
| PWA | `manifest.webmanifest` + service worker served by Django |
| Hosting | DigitalOcean App Platform (FRA region), DNS at GoDaddy; deploy healthcheck at `/api/health/build` |

### Code layout

Everything lives in `apps/` (~45 Django apps). The load-bearing ones:

- **`apps/core`** — cross-cutting law: `fy.py` (financial-year calendar),
  `scoping.py` (row-level access), `rbac.py` (role→permission matrix),
  `enums.py` (activity states, school types, SSA interventions and score
  bands, participant modes), `calendar_policy.py` (scheduling gate),
  `metrics/` (the KPI registry), `navigation.py` (pages, sidebar, icons,
  role visibility — the single registry every surface registers in).
- **`apps/accounts`** — users, staff profiles, supervision links, school
  assignments, leave, holidays, calendar blocks, support capacity.
- **`apps/schools` / `apps/geography` / `apps/clusters`** — the directory,
  Region→District→…→Village hierarchy, cluster assignment.
- **`apps/activity_catalogue`** — the governed catalogue of 40 activity
  types (stable codes, participant modes, evidence and costing profiles).
- **`apps/planning` / `apps/my_plan` / `apps/monthly_work_plan`** — annual
  and monthly planning, the My Plan execution surface.
- **`apps/activities` / `apps/evidence` / `apps/pl_review`** — the activity
  lifecycle, evidence requirements, PL review.
- **`apps/budget` / `apps/fund_requests` / `apps/partners`** — costing,
  the money chain, partner assignment and payment.
- **`apps/ssa`** — School Self-Assessment records and scoring.
- **`apps/core_schools`** — the Core programme (package slots, RVP baseline).
- **`apps/targets`** — the personal target ledger, Team Targets, FY calendar
  service with working-day capacity.
- **`apps/hr`** — performance agreements, strategic priorities, the Uganda
  Master Priority Plan cascade, leave services, recruitment/onboarding,
  professional development.
- **`apps/analytics` / `apps/leadership` / `apps/budget_intelligence`** —
  the analytics workspace, impact engine, decision engines.
- **`apps/command_center` / `apps/notifications` / `apps/messaging`** —
  the derived To-Do queue, workflow notifications, in-app messaging.
- **`apps/system_health`** — the platform's self-auditing gates (§15).

### Request flow

Pages render through `templates/layouts/shell.html` (sidebar, topbar,
mobile bottom nav). A page = a guarded view (`require_page_permission` +
a granular permission decorator) + an entry in `PAGE_PERMISSIONS`, `ICONS`
and `SIDEBAR_ITEMS` in `apps/core/navigation.py`. State changes go through
**canonical service functions**, never raw model writes — a system-health
scanner fails CI on any workflow-field write outside a service.

---

## 3. Roles and access

Eleven roles (`apps/core/rbac.py`), each mapped to permissions in one
in-code matrix (`ROLE_PERMISSIONS`) and to pages in `PAGE_PERMISSIONS`:

| Role | In short |
|---|---|
| **CCEO** | The field officer. Owns a direct portfolio of schools, plans and delivers visits/trainings/SSAs, submits evidence, carries personal targets. |
| **Program Lead (PL)** | Supervises CCEOs. Approves their plans and fund requests, reviews completions, distributes team targets, monitors Team Targets. |
| **Country Director (CD)** | Country leadership. Owns the Uganda master plan, the rate card and the country budget envelope; leads through analytics, not the operational directory. |
| **Impact Assessment (IA)** | The verification authority. Verifies activities and SSAs (`IA_VERIFY` is IA's alone), distributes Uganda annual targets to PLs, runs data quality. |
| **RVP** | Regional Vice President. Authors regional strategy, approves the country budget envelope and annual baseline, regional oversight. |
| **Accountant** | Disburses funds (`PAYMENT_ACT` is the Accountant's alone), reconciles accountability, closes activity finance. |
| **HR** | People systems: policies, leave administration, performance cycle validation, recruitment/onboarding. |
| **Project Coordinator** | Runs Special Projects through the same planning/activity/budget engine, scoped to their projects. |
| **Partner Admin / Partner Field Officer** | External delivery partners: see and complete only work assigned to their organisation. |
| **Admin** | Platform super-role — every permission **except** the three separation-of-duties authorities (IA verification, disbursement, field budget approval), which no super-role may hold. |

**Row-level scoping** is separate from permissions and lives in
`apps/core/scoping.py` (`UserScope`). A CCEO's *own* portfolio comes from
`StaffSchoolAssignment`; a PL additionally sees a *team* lens derived from
supervised CCEOs (`StaffSupervisorAssignment`) — own and team are
deliberately distinct ("supervision is not ownership"). Temporary coverage
assignments move access (and approval authority) to the covering person
while someone is on leave. `owner_ids()` is the single ownership check
(it returns both the user-id and staff-profile-id spaces, because activity
ownership columns historically hold either).

---

## 4. Core domain concepts

- **Financial year**: 1 October → 30 September, labelled by the year it
  *ends* (FY2027 = Oct 2026–Sep 2027). Q1 = Oct–Dec … Q4 = Jul–Sep;
  month-of-FY 1 = October. All period math flows through
  `apps/core/fy.py` and `apps/targets/fy_calendar.py` — the latter adds
  **working-day capacity**: weekdays minus public holidays minus the
  person's approved leave.
- **Schools**: `school_type` defines two families — Core-family
  (`core`, `champion`) and Client-family (`client`, `core_trained`).
  Operational status (active/reopened/closed) is a separate axis. Schools
  sit in the geography tree and may belong to one cluster.
- **Activity catalogue**: every plannable activity derives from one of 40
  governed catalogue items (stable codes like `STANDARD_SCHOOL_VISIT`,
  `LITERACY_NUMERACY_PROJECT`, `EDTECH_FOUNDATIONS`). The item is the
  workflow profile: it fixes the participant mode (none / direct total /
  per-school / by-category), the evidence profile and the costing profile.
  Activities snapshot their catalogue version at creation.
- **Projects**: Special Projects reuse the whole planning/activity/budget
  engine scoped by `ProjectStaffAssignment`; project eligibility for a
  school is an SSA judgement (weak in a target intervention).
- **Partners**: external organisations that deliver assigned work through
  their own portal flow; partner-delivered work is paid through
  `PartnerPaymentService` and **never earns staff achievement credit**.
- **SSA (School Self-Assessment)**: structured score data (never PDFs) on
  the canonical eight interventions — Christlike Behaviour, Exposure to
  the Word of God, Financial Health, Leadership, Government Requirements,
  Learning Environment, Teacher's Environment, Enrolment — each scored
  0–10 and banded by the single source of truth `ssa_score_band()`:
  Critical 0–4.9 / Warning 5–6.9 / Improving 7–7.9 / Strong 8–10.
  A record counts only when `verification_status = confirmed` (IA).

---

## 5. The field delivery workflow (the spine)

Everything else hangs off this chain. It is enforced by status machines
(23 activity states in `apps/core/enums.py`), not by convention.

```
Annual Work Plan (FY targets per school/cluster)
      │
      ▼
Planning & costing            one activity = one cost = one channel
      │                       (costing derives from the catalogue profile
      ▼                        and the CD-owned rate card)
Scheduling                    calendar-policy gate (REG-02): Sundays,
      │                       public holidays, blackouts, approved leave
      │                       and org events block; pending leave warns
      ▼
Execution                     staff-delivered, or assigned to a partner
      │                       (assigned_to_partner → partner_scheduled)
      ▼
Completion                    attendance recorded (teachers/leaders/other
      │                       ATTENDED — deliberately separate fields from
      ▼                       the planned ones), evidence uploaded
PL review                     submitted_to_pl → returned_by_pl | approved
      │
      ▼
IA verification               awaiting_ia_verification → ia_verified
      │                       (or returned — which also reverses any
      ▼                        milestone credit the activity had earned)
Finance close                 accountant confirmation, payment status,
      │                       Salesforce ID (required to close)
      ▼
closed                        the activity is a verified, paid fact
```

Key rules along the spine:

- **Participant mode has teeth.** A visit (`ParticipantMode.NONE`) cannot
  carry participant numbers — the service clears them so they can never
  reach costing. Per-school trainings derive the total from live cluster
  membership × per-school figure; a browser-computed total is never
  trusted. Where the Uganda master provides participants-per-school
  guidance for an activity, scheduling suggests it (a typed figure always
  wins).
- **Planned ≠ actual ≠ verified.** Planned participants and invited
  schools live in different fields from attended ones; only IA-verified
  attendance ever counts toward achievement.
- **Evidence** requirements come from the catalogue's evidence profile;
  completion is blocked until they are met (trainings additionally require
  non-zero attendance).
- **Returns are real.** A PL or IA return moves the activity back with a
  required reason, reverses strategic milestone credit, and (in the
  personal ledger) flips prior credit to `reversed` on the next rebuild.

---

## 6. The money workflow

Two chains, deliberately separate: the **field approval chain** and the
**country envelope**.

1. **Costing at plan time.** Every plannable activity gets one budget line
   from the catalogue costing profile × the CD-owned rate card
   (`COST_SETTINGS_MANAGE`). Money is plain UGX integers platform-wide
   (the Professional Development app is the one cents-based exception).
2. **Weekly fund requests (CCEO → PL).** Staff request funds for the
   coming week's fundable lines; the CCEO approves their own staff's
   requests and submits a consolidated request up to the PL
   (`BUDGET_APPROVE` is held by the field chain only — never CD/RVP/Admin).
   Escalated advances (non-CCEO owners) go to the CD
   (`FUND_REQUEST_APPROVE_ESCALATED`).
3. **Monthly country envelope (CD → RVP).** The CD consolidates PL monthly
   requests and submits the country envelope (`COUNTRY_BUDGET_SUBMIT`);
   the RVP approves it and locks the annual baseline
   (`COUNTRY_BUDGET_APPROVE`). Later baseline changes are amendments.
4. **Disbursement (Accountant).** The Accountant — and only the
   Accountant — marks funds disbursed (`PAYMENT_ACT`), records NetSuite
   references, and pays partners through the single
   `PartnerPaymentService` path.
5. **Accountability.** Spent funds are accounted for and cleared through
   the Program Lead; unaccounted balances block cleanly rather than
   silently. Activity finance closes with the accountant confirmation
   step of the activity lifecycle, and closure requires the Salesforce ID.

The separation of duties is structural: one account can never approve a
budget, disburse against it, and verify the work it paid for — Admin is
excluded from all three by the permission matrix itself.

---

## 7. Targets and performance

Three connected layers, one direction of flow: **verified work → credit →
targets → performance conversations**.

### 7.1 The personal ledger (My Targets)

`apps/targets/my_targets.py` maintains `TargetAchievementLedger`: one
deduplicated credit per source record (activity / SSA / MSC story),
credited to the month the work happened. Credits are `validated` only when
the source is IA-verified (activities also need their Salesforce ID);
otherwise `provisional`; returned/rejected sources become `reversed`.
A source credits **once, ever** (the uniqueness is deliberately
FY-agnostic). Partner-delivered work never enters a personal ledger.

Monthly targets come from the person's **agreed performance priorities**
(see 7.3), split across months; the page classifies each area against
working-day pace (Not Started / On Track / At Risk / Off Track / Complete /
Exceeded). `weighted_period_pct()` is *the* canonical weighted formula —
My Targets, Team Targets and CD analytics all call the same function, and
a randomized property-test suite pins their equivalence.

### 7.2 Team Targets and the CD view

`team_targets.py` aggregates supervised CCEOs for the PL (areas are the
union of each member's own agreed priorities), classifies the team
(On Track / Slightly Behind / High Risk / Critical), renders the team
calendar, blockers, validation and Salesforce-ID backlogs, and hosts the
**catch-up plan** flow: a PL proposes recovery activities for a behind
member; approval creates real planned activities through the normal
planning/costing funnel. CD analytics pools the same series country-wide.

### 7.3 Performance agreements and strategic priorities

`apps/hr` runs the annual performance cycle: strategic priorities are
authored at **regional** (RVP) and **country** (CD) level in one governed
cycle per FY; per-role rules translate each priority into how a role
carries it (execute / supervise / verify / finance / not-applicable) with
a metric from the canonical vocabulary. Publishing is gated (every
carrying role must name a real metric). Agreed commitments are frozen
copies — retiring strategy never rewrites a signed agreement; changes go
through `PriorityAmendment`.

### 7.4 The Uganda Master Priority Plan (the country target cascade)

The authoritative country plan and its one controlled distribution,
built on the milestone chain (`StrategicPriorityCycle → StrategicPriority
→ PriorityMilestone → MilestoneAllocation → MilestonePeriodTarget →
MilestoneActivityRule → MilestoneProgressCredit`):

```
Uganda Master Priority (74 milestones, 5 groups, CD-owned)
   ↓  CD confirms flagged source figures in-app, publishes & locks
IA → Program Lead annual allocations       (reconciled, then locked)
   ↓  PL distributes once among supervised CCEOs (reconciled, locked)
Approved allocations appear under My Priorities automatically
   ↓  quarterly spread approved (IA approves PL's; PL approves CCEO's)
Months phased by real capacity (working days − holidays − leave)
   ↓  staff schedule activities against the monthly target
Verified results update monthly / quarterly / annual achievement
```

The laws the engine (`apps/hr/target_distribution.py`) enforces:

- **Provenance**: country milestones are parented to their regional
  priority; every CCEO figure walks back to the Uganda total via the
  allocation `parent` link. Source ambiguities from the Priorities.docx
  (composite values, the "400%" visits question, FY-dated rows) are
  *flagged*, never silently normalized — publish refuses while any
  scoreable figure is unconfirmed.
- **Allocation methods** (per milestone): `field_cascade` (IA→PL→CCEO),
  `specialist` (project/team-owned), `country_owned` (CD/IA), and
  `non_scoreable` (preserved but excluded from scoring) — so accountants,
  HR and IA never receive school-delivery targets by default.
- **Reconciliation**: Σ PL = Uganda distributable; Σ CCEO = PL team
  target; Core and Client columns balance like the main column;
  Q1+Q2+Q3+Q4 = annual; months in a quarter = the quarter. Approval is
  blocked while a balance is missing or over-allocated.
- **One annual distribution**: one live allocation per holder per
  milestone; approval locks it (`locked_at`); later changes are
  `MilestoneAllocationAmendment` rows (annual **amendment** or quarterly
  **reforecast** — the reforecast keeps the annual total and cannot touch
  closed quarters) with actor, reason, previous and new values.
- **Rates never sum**: percentage commitments (SSA coverage 90%) cascade
  as *level* targets — every holder carries the rate against their own
  portfolio; achievement divides verified unique schools by the
  allocation's denominator, never units by a percentage.
- **Capacity-aware phasing**: recommendations and monthly phasing use the
  holder's real working days; a fully blocked month carries zero and its
  quarter absorbs it; if a target cannot fit the remaining capacity the
  platform raises a warning instead of reducing the commitment. Past
  months and verified achievements never move. **Approving leave
  automatically re-phases** the person's remaining months.
- **Four figures, kept separate**: assigned target / phased monthly
  target / planned output (rises when an activity is scheduled, returns
  to the gap when cancelled) / verified actual. Insufficient planning
  widens a reported gap; it never lowers the target.
- **Classification** (monthly, quarterly, annual): <80% Behind ·
  80–99% Near · =100% Achieved · 100–150% Exceeded · ≥150% Far exceeded;
  coverage-style percentages are capped at 100% and classified Achieved.

Surfaces: **`/target-distribution`** (IA distribution command + CD
confirmation/publication, database-backed recommendations from real
portfolios, reconciliation errors, amendment history) and
**`/target-distribution/team`** (the PL's supervised-team distribution,
quarterly approvals, per-member planned-output/verified/gap monitoring).
Seeded by `manage.py seed_uganda_master` (idempotent; drafts only —
a published master is never rewritten by a reseed).

---

## 8. Core Schools and the RVP programme

Core schools carry a defined annual support package (visit and training
slots) created through the same costed activity funnel; slot completion is
driven by verified activities. The RVP locks an annual baseline; changes
after the lock are amendments. Champion schools are Core-family;
`core_trained` graduates are Client-family. Completion gates (e.g. the §26
rule) prevent a Core year closing with undelivered package slots.

---

## 9. Scheduling intelligence

- **Calendar policy (REG-02)**: one gate (`SchedulingPolicyService`)
  answers "may this person work this date?" — Sundays always block,
  Saturdays never do; public holidays, blackout dates, org events and the
  person's approved leave block; pending leave warns; a 5-activity week
  warns. Create *and* reschedule both pass through it.
- **Route intelligence**: `DailyVisitRouteBatch` plans multi-school visit
  days using the location hierarchy (coordinates → structured → text),
  scores routes in bands, and justifies focus schools from SSA weakness.
- **Urgent attention / school action queue**: schools in trouble surface
  as `TeamAction` items in an unassigned queue with per-school+FY
  exclusion rules, feeding the PL's assignment flow.

---

## 10. People systems (HR)

- **Leave**: request → supervisor approval (hierarchy-checked, coverage
  aware) → balances recalculated → a `TemporaryCoverageAssignment` moves
  access to the covering colleague — and the person's future milestone
  months re-phase automatically. Public holidays and calendar blocks are
  admin-managed and feed every capacity calculation.
- **Professional Development**: per-role annual allocations (stored in
  cents in this app alone), request/accounting/return flow, HR dashboard
  and cron-less reminder command.
- **Daily Debrief**: a five-question end-of-day form auto-fed from My
  Plan (autosave, one per day) consolidating weekly into locked,
  versioned PDF reports for PL/CD/RVP/HR.
- **Field Debriefs**: structured field reports with role-scoped
  querysets (RVP sees critical-only; HR/IA global) feeding an
  intelligence summary shared by five dashboards.
- **Performance conversations**: the annual cycle (priority setting →
  quarterly snapshots → mid-year → year-end) documented in
  [PERFORMANCE_CONVERSATION_SPEC.md](PERFORMANCE_CONVERSATION_SPEC.md);
  weights must total 100; mandatory priorities cannot be dropped and
  their metrics are immutable per-person.
- **Recruitment & onboarding**: vacancy → application stages → hire →
  onboarding states, with staff setup flowing into the assignment model.

---

## 11. Analytics and intelligence

- **The Analytics workspace** (`/analytics`) merges the analysis surfaces
  behind one registry-driven section nav (links, never fake tabs):
  country/CD cockpit, team and staff performance, SSA movement,
  visit effectiveness (the canonical visit↔SSA engine), publishing, and
  more. All KPIs bind through the **metric registry**
  (`apps/core/metrics`): every registered tile carries its definition,
  numerator/denominator, date basis, period, scope and data state — and
  the KPI inventory ratchets unregistered tiles downward.
- **Impact analytics** (`/impact`): a pandas/scipy engine relating
  accepted spend to SSA movement with weak-baseline stratification and
  min-N honesty (it says "not enough data" rather than inventing a
  trend).
- **Decision engines**: the Leadership Decision Engine (staff capacity,
  recruitment gaps, partner performance, HR risk) and the Budget
  Intelligence engine *recommend and never auto-execute*; decisions are
  logged with notes.

---

## 12. Communications

- **Notifications** (`apps/notifications`): one emit point
  (`WorkflowNotificationService.trigger`) with idempotent re-firing (a
  repeat event updates the same notification, bumping a reminder count,
  never stacking), recipient resolution across both id spaces, and a
  central `NotificationLinkResolver` that routes each event type to the
  right surface *per role* (e.g. a `target_allocation.approved` sends a
  CCEO to My Targets and a PL to Team Target Distribution).
- **To-Do queue** (`apps/command_center/todo_service.py`): the user's
  work list is **derived live from workflow state** — ~22 producers, no
  stored to-dos, so items close themselves the moment the underlying
  state changes.
- **Messaging**: in-app conversations with fail-closed context access
  checks; real-time rail via SSE (async by requirement).

---

## 13. Platform integrity and governance

The platform audits itself in CI; these are tests, not conventions:

- **Audit chain** (`apps/audit`): hash-chained, serialized append-only
  log for every governed action (publish, approve, amend, disburse…).
- **RBAC + page inventory**: every routed frontend view must carry a
  permission guard (scanner-enforced); the generated page/KPI/card
  inventories are committed artifacts — CI fails if they drift from the
  live code (they record source line numbers deliberately).
- **UI quality gates**: no emojis (SVG icons only), no dead links or
  inert buttons, no uncompiled Tailwind utilities, no inline styles or
  raw hex (design tokens only), no client-side business arithmetic
  (server figures are the only figures), no mock/runtime placeholder
  data, tables paginated (page size 10), one search per page (the topbar
  binds page search via `topbar_search`), one shared page-header anatomy,
  filter selects on the canvas — plus the Django-template traps the
  suite pins (`{# #}` is single-line; `|default:` with a dotted argument
  is banned because it resolves eagerly).
- **Environment stamp guard**: the database is stamped
  local/staging/production and boot refuses mismatches (a dev dump can
  never serve production; a local shell can never point at the live DB).
- **Reliability**: liveness and readiness probes are split; the mailer is
  bounded; scheduled jobs take real locks (proven under race tests);
  15k-school load fixtures back the scale gates.

---

## 14. Operations

- **Seeds**: `manage.py seed` builds the demo environment (geography
  bootstrap via `/admin/`, demo accounts, super-admin from env);
  `seed_activity_catalogue`, `seed_fy2027_priorities` (regional strategy,
  also run by migration), `seed_uganda_master` (country master, draft),
  `seed_project_activity_rules`.
- **CI** (GitHub Actions): ruff check + format, migrations check, the
  full Django test suite (`--parallel 4`, ~5,000 tests), CSS build with
  a clean-diff check on `static/css/main.css`, pip-audit, bandit,
  npm audit, zizmor, Docker build + non-root + runtime import checks,
  trivy. Local `.env` relaxes the login throttle that CI enforces.
- **Deployment**: migrations run in the PRE_DEPLOY job (two instances
  would otherwise race); `/api/health/build` is the honest deploy check;
  the scheduler runs as its own service. See
  [runbooks.md](runbooks.md), [INFRA_SETUP.md](INFRA_SETUP.md) and
  [scheduler-deployment.md](scheduler-deployment.md).
- **Testing**: 377+ test files beside the code they pin (`test*.py`),
  plain `TestCase` with hand-built fixtures, `assertNumQueries` batching
  contracts, and randomized property tests where formulas must agree.

---

## 15. Appendix

### A. Where each role starts

| Role | Home surfaces |
|---|---|
| CCEO | Dashboard → My Plan → My Targets → Weekly Fund Request |
| PL | Team dashboard → Team Targets → Fund Approvals → Team Target Distribution |
| CD | Country analytics cockpit → Strategic Priorities → Target Distribution → Country Budget |
| IA | Verification queue → SSA → Target Distribution → Data quality |
| RVP | Regional analytics → Strategic Priorities → Country budget approval |
| Accountant | Fund Disbursement Dashboard → Advances → Accountability |
| HR | People dashboards → Performance cycle → Leave planner → Policies |
| Project Coordinator | Project planning → Project My Plan → Project analytics |
| Partner | Assigned work list → Completion + evidence |

### B. Glossary

| Term | Meaning |
|---|---|
| CCEO | The field officer role supporting a portfolio of schools |
| SSA | School Self-Assessment — structured 0–10 scores on 8 interventions |
| Core / Client | The two school families (core+champion / client+core_trained) |
| DC | Discipleship Community (a school-level programme) |
| FY | Financial year, Oct 1 → Sep 30, named for the ending year |
| MSC | Most Significant Change story (qualitative evidence, IA-reviewed) |
| PL | Program Lead (supervises CCEOs) |
| IA | Impact Assessment (the verification authority) |
| RVP | Regional Vice President |
| Rate card | CD-owned official cost settings used by activity costing |
| Catalogue item | Governed activity definition (workflow + evidence + costing profile) |
| Milestone allocation | One holder's share of a strategic/Uganda master target |
| Planned output | What scheduled activities are expected to deliver (never conflated with verified actuals) |

### C. Key invariants (the short list)

1. Nothing is fabricated — every number traces to a query; empty is empty.
2. Only IA-verified work earns achievement credit; partner work never
   credits staff.
3. One activity, one cost, one channel; money moves only through the
   Accountant.
4. Approved figures lock; change is an amendment with actor + reason +
   before/after.
5. Rates never sum; counts reconcile to zero at every cascade level.
6. Planned, actual and verified are different fields and never blur.
7. Supervision is not ownership; scope is checked per record.
8. The server computes every business figure; the browser only displays.
