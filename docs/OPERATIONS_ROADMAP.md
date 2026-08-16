# Operations Roadmap — from governed platform to operational autopilot

*Adopted 2026-08-14. Companion to [PLATFORM_GUIDE.md](PLATFORM_GUIDE.md)
(what exists today), [STAFF_TIME_STANDARD.md](STAFF_TIME_STANDARD.md) (the
measured ceiling this roadmap serves) and
[PRODUCT_PRINCIPLES.md](PRODUCT_PRINCIPLES.md) (Simple · Healthy · Focused).*

---

## Purpose

> Edify Planning & Monitoring automatically converts strategy, school
> needs, staff capacity, geography, approved budgets and verified results
> into the next best field actions — while keeping routine staff
> administration below 15 minutes per day.

The platform's operational foundation is unusually strong: governed status
machines, canonical services, strict separation of planned/actual/verified,
separation of duties enforced in the permission matrix, and a self-auditing
CI. **The missing piece is not more functionality — it is the automation
and orchestration layer that makes most existing functionality invisible
to staff.** Staff today manually translate targets into plans, plans into
schedules, schedules into budgets, and completed work into debriefs; the
components that could do that translation (capacity-aware phasing, route
intelligence, the calendar gate, catalogue-driven costing, the derived
To-Do queue) already exist but are not connected.

## Constitution — what no phase may weaken

These platform invariants are constitution-level. Automation exists to make
compliance with them effortless, never to route around them:

1. Nothing is fabricated — every number traces to a query; empty is empty.
2. Only IA-verified work earns achievement credit.
3. Partner-delivered work never becomes staff achievement.
4. One activity has one cost and one delivery channel.
5. Approved figures change only through documented amendments.
6. Planned, actual and verified values remain separate — and
   **machine-proposed** joins them as a fourth, distinct state (see
   Phase 4) that never counts as planned until a human accepts it.
7. Supervision is not ownership; scope is checked per record.
8. The server computes every business figure; the browser only displays.

And the division of labour is fixed: **automation calculates, prepares,
bundles and recommends; authorized humans confirm reality, approve, verify
and disburse.** AI assistance (transcription, summarisation,
classification, anomaly detection) is welcome at the edges and is never
the source of truth for attendance, expenditure, verification, approval,
school identity, achievement credit, disbursement, or locked-value
amendments.

## Decision register

| # | Decision | Status | Consequence |
|---|---|---|---|
| D1 | **Is the 50,000-school ambition multi-country expansion, or Uganda headroom?** | **OPEN — leadership decision required** | If multi-country: tenancy becomes a first-class workstream (per-country calendars, holidays, rate cards, school terms; `country_id` becomes structural, not a string; cross-country RVP rollups; data residency) and belongs *above* partitioning in Phase 6. If Uganda headroom: Phase 6 is load engineering only, and the 50k figure needs a stated justification. Everything in Phases 0–5 is identical under both answers. |
| D2 | 15-minute standard adopted with anti-surveillance constraints | **ADOPTED** — [STAFF_TIME_STANDARD.md](STAFF_TIME_STANDARD.md) | Every staff-facing roadmap item states its expected effect on the metric. |
| D3 | Architecture course: modular monolith + durable workers + outbox; **no microservice rewrite** | **ADOPTED** | The Django core remains the transaction and policy engine. |

## Phase sequence

The ordering logic: each phase has standalone value and makes the next
phase cheaper. The expensive ambitions (autopilot, 50k) come after the
things they depend on. Offline and integrations outrank the unified
workbench because field admin time is dominated by connectivity friction
and double-entry, not navigation; the event backbone precedes the
autopilot because its regeneration loops need durable workers.

### Phase 0 — Standards and decisions *(complete)*

- [STAFF_TIME_STANDARD.md](STAFF_TIME_STANDARD.md) adopted.
- This roadmap adopted; D1 posed to leadership.

### Phase 1 — Measure first, clean the ground *(built; baseline accruing)*

**1a. Interaction telemetry** *(built)*. Server-side interaction events
(resolved route pattern + timing only; no query strings, no payloads,
no IPs), sessionised nightly into per-person-day active minutes with the
§3a **planning vs execution-and-proof split**, reported as role-population
percentiles and a planning-share figure in System Health. Aggregate-only
by construction — the report layer cannot name an individual. Apps:
`apps/telemetry` (middleware, models, rollup job `interaction_rollup`).

**1b. Data-quality exception queues** *(built)*. `DataQualityIssue` gained
a durable `condition_key` identity: regeneration now reconciles in place
(preserving `assigned_to` — the old path deleted every open row on every
save), cleared conditions self-resolve with a timestamp. New detectors:
schools without usable coordinates (SchoolGeoPoint-aware); a trigram
duplicate proposer that populates the previously-empty
`SchoolDuplicateCandidate` queue and never overrides a human decision;
portfolio capacity overload sharing the assignment drawer's exact rule.
Nightly `data_quality_scan` job; queues surfaced in System Health with
owners and resolution links.

*Acceptance: a baseline active-minutes report by role exists with at least
14 days of data (accruing from deployment); each data-quality queue has an
owner role and its counts trend downward.*

### Phase 2 — The backbone *(core built; two items blocked, see register)*

- **Durable job queue + transactional outbox** *(built)* — `apps/outbox`:
  transactional enqueue with mandatory idempotency notes, SKIP LOCKED
  claims, deterministic exponential backoff, dead-letter queue with
  `manage.py outbox_requeue` replay, crash-claim recovery, a per-minute
  `outbox_drain` job, and a System Health block (depth, oldest-pending age,
  dead letters). Migrating existing heavy synchronous work (ledger
  rebuilds, period-target refreshes, notification fan-out) onto it is the
  remaining adoption work.
- **Object storage for evidence** — **BLOCKED on infrastructure** (B1 in
  the register): needs a provisioned object store (e.g. DO Spaces) with
  credentials before signed/resumable uploads can be real.
- **Salesforce and NetSuite integrations** *(framework built)* —
  `apps/integrations` on the outbox: sync ledger, converge-on-state
  handlers where a manually pasted reference always wins, enqueue seams at
  IA verification (SF) and advance disbursement (NetSuite), flags off by
  default. **The transport is BLOCKED on credentials** (B2): implementing
  `push_to_external` against the live APIs is the single seam that changes;
  enabled-but-unconfigured fails loudly into the DLQ, never silently.

*Acceptance: no user-facing request performs heavy work inline; a killed
worker loses nothing; SF/NetSuite IDs arrive by sync, not typing.*

### Phase 3 — Offline-first field operation *(server half built)*

The **day package** is live: `GET /my-plan/day-package` serialises the
caller's field day — route-grouped activities, school locations (geo-point
override aware), evidence checklists, prefilled participant plans, and the
sync-state vocabulary — own work only, partner rows excluded. **The client
half remains** (B3): service-worker caching of the package, the encrypted
local action queue with resumable replay, conflict detection and the
visible sync states. It builds on the endpoint as-is.

*Acceptance: a full five-visit day completes with airplane-mode gaps and
loses nothing; sync failures appear as exceptions, not silent loss.*

### Phase 4 — Operational autopilot, in slices *(guard + slice 1 built)*

The **machine-draft state is built** — `apps/autopilot`'s
ProposedPlan/ProposedActivity staging tables: a draft creates no Activity
row, consumes no budget, feeds no planned-output metric and raises no
To-Do until accepted (tested as a constitutional assertion). **Slice 1 is
built**: the weekly schedule recommendation — portfolio schools without
recent support, SSA-outstanding first, grouped into sub-county
route-coherent days that pass the same calendar gate as manual scheduling
(REG-02: holidays, blackouts, org events, approved leave). The decision is
*Accept Week* (routing every item through the canonical costed `create()`
funnel, per-item refusals surfaced) or *Dismiss*; regeneration supersedes,
never stacks; an accepted week is final.

Remaining slices, in order of time saved per effort:

2. **Fund-request preparation** — scheduled fundable lines bundled into
   the weekly request, envelope-checked, exceptions highlighted;
   authorization remains exactly where the field chain puts it today.
3. **Confirm-only daily debrief** — the five-question debrief upgrades to
   a prepared summary where staff confirm what was materially different.
4. **Automatic accountability preparation** — expected vs actual, receipts
   required, recoverable balance, prepared from recorded facts.
5. **Annual plan draft generation** — last; needs the above plus Phase
   1b's clean directory.

*Acceptance: ≥90% of activity fields prefilled; weekly plans and fund
requests system-prepared; every automatic action idempotent, auditable and
attributable; every failed automation a visible exception.*

### Phase 5 — The Today workbench *(v1 built)*

**`/today` is live** for CCEO, Program Lead and Project Coordinator: Your
Next Activity · Your Route (the day package, geography-grouped) · Waiting
for Your Confirmation and Exceptions (the derived To-Do queue, split) ·
Your Proposed Week (prepare / accept / dismiss, the autopilot's slice 1) ·
Day Completion (debrief state). Composed entirely from canonical services;
honest empty states throughout; sits above Dashboard in the sidebar for
the roles it serves. It grows richer as autopilot slices 2–4 land — fund
preparation and the confirm-only debrief surface here when built.

*Acceptance: the Staff Time Standard's metric meets 95% ≤ 15 minutes for
field roles; routine days touch one surface.*

### Phase 6 — Scale and enterprise hardening *(shape depends on D1)*

- Load model = schools × activities × evidence × transitions × credits ×
  audit — tested at the D1 scale with realistic volumes and peak
  concurrency, not school rows alone.
- Partitioning (FY/date) for the large transactional tables; read models
  and a separated analytical store when leadership analytics measurably
  compete with field submissions; the metric registry stays the semantic
  source of truth.
- Reliability operating model: SLOs (availability, response, sync success,
  job delay, integration lag), end-to-end observability (structured logs,
  metrics, traces, correlation IDs), quarterly restore drills, documented
  RPO/RTO, zero-downtime expand-and-contract migrations, progressive
  rollout with rollback.
- Enterprise identity: SSO, device/session management, joiner-mover-leaver
  automation, access reviews, secrets rotation, security-event monitoring,
  learner-data minimisation and retention policy. (MFA and lockout policy
  already exist; this completes them.)
- If D1 = multi-country: tenancy workstream first (calendars, rate cards,
  holidays, terms, rollups, residency per country).

## Alignment audit log

Every workflow and integration is periodically audited against this
document's purpose, the constitution and the Staff Time Standard. Findings
are fixed with a pinned test or recorded here — never silently absorbed.

**2026-08-15 — full seams audit (complete).** Ten seams audited against
this document; twelve findings fixed with regression tests, five recorded.

Fixed (beyond items 1–3 below): **(4)** the live IA verification workspace
(`ActivityCertificationService`) wrote no milestone credit and no SF sync —
only the DRF path did, so every Uganda allocation's actuals stayed at zero
in production; credit + sync + reversal now fire on certify, return AND
closure-invalidation (pinned: a workspace-certified activity moves a
period target's actuals). **(5)** the autopilot passed the School PK where
the funnel expects the business code — every accepted item was refused;
fixed, the acceptance test is now strict (zero refusals, real costed
activities), and the generator applies the client one-visit-per-FY
entitlement up front. **(6)** telemetry's route classification covered 19%
of surfaces and its §3a "Assign" hook matched nothing — amended against
the real URL map; the day-package prefetch is exempted as background sync.
**(7)** /today was absent from mobile nav (the field device!) — now first
for CCEO/PL/PC; a shadowed duplicate `/today` route removed. **(8)** the
day package missed legacy rows with only a scheduled_date — My Plan's own
fallback applied. **(9)** the NetSuite seam sat on the one disburse path
the UI never uses — enqueued on the weekly and period channels' advance
flips. **(10)** the integration ledger was write-only and its FAILED rows
rolled back with the exception recording them — dead write removed, a
System Health reader added. **(11)** a human-resolved-but-persisting
quality condition respawned as an anonymous row — reconcile now REOPENS
the prior row with its assignee. **(12)** quarterly-spread approvals,
outbox dead letters and autopilot refusals were silent — the holder is
notified on spread approval, Admins on dead letters (routed to System
Health), and acceptance results persist on the plan's rationale. Plus: a
weekly `autopilot_weekly_proposals` job now prepares drafts automatically —
preparation no longer costs the staff member even the click.

Recorded, not yet fixed: **(R1)** the duplicate-review UI reads
`duplicate_risk` issues, not `SchoolDuplicateCandidate` pairs, and never
marks candidates resolved — the queue can only grow until it is pointed at
the pairs and routed through `services.resolve_duplicate`. **(R2)** the
Data Quality Center lacks worklists for `no_coordinates`,
`missing_school_type`, `missing_sub_county`. **(R3)** My Plan's API
(`get`) and page (`get_frontend_context`) disagree about supervisee
visibility — an open product decision. **(R4)** six declared activity
statuses have no writer, including `accountant_confirmed`, which is a
milestone QUALIFYING_STATE the platform cannot currently reach (ties to
the open Accountant-workflow policy question). **(R5)** Partner Field
Officers keep `partner/today` rather than joining `/today` — a deliberate
scope decision to revisit with Phase 5's partner pass.

Original three findings, each with a regression test:

1. *Today ↔ To-Do queue vocabulary* — the workbench read `url`/`subtitle`
   keys the queue never emits (real keys: `action_url`, `description`;
   priorities critical/high/medium/low; `blocked` is a `status_key`).
   Every item silently fell back to the dashboard link, violating "every
   red number leads to an actionable queue". Fixed in
   `apps/frontend/views/today_views.py` + template; pinned by a test that
   drives a real planned activity into a linked row.
2. *Exception split* keyed on a nonexistent "overdue" priority and a
   missing boolean — now uses the queue's own vocabulary
   (`priority == critical` or `status_key == blocked`).
3. *SSA upload hard-deleted cleared `no_ssa` rows*, destroying assignee
   and resolution history in the durable queue — now resolves with a
   timestamp (`apps/ssa/upload_service.py`), consistent with the Phase 1b
   reconcile-never-delete law.

## Blocked-item register

Work that code alone cannot finish. Each item names what unblocks it.

| # | Item | Blocked on | Ready when |
|---|---|---|---|
| B1 | Evidence object storage (signed, resumable uploads) | Infrastructure provisioning + credentials (e.g. DO Spaces) | Ops provisions the bucket; then the storage backend, upload endpoints and retention rules are code. |
| B2 | Live Salesforce / NetSuite transports | API credentials, org endpoints, an integration owner | Implement `apps.integrations.services.push_to_external` per system, then flip `SALESFORCE_SYNC_ENABLED` / `NETSUITE_SYNC_ENABLED`. Everything around the transport (ledger, handlers, seams, DLQ semantics) is built and tested. |
| B3 | Offline client (service-worker day cache, local action queue, sync states) | Frontend build effort on the existing PWA shell | The day-package endpoint is live; the client consumes it as-is. |
| B4 | Phase 6 scale/tenancy shape | **Decision D1** (multi-country vs Uganda headroom) | Leadership answers D1. |
| B5 | SSO, device management, security monitoring | Identity-provider selection + org rollout | MFA and lockout already exist; these complete them when an IdP is chosen. |

## Explicit non-goals

- No microservice rewrite (D3).
- No analytics warehouse before it is measurably needed.
- No per-person interaction-time surfaces, ever (Staff Time Standard §5).
- No AI as a source of truth for any constitutional value.
- No dropdown that loads the full school directory — scoped search only.

## Acceptance criteria for the programme as a whole

**Staff efficiency**: ≥95% of routine field days ≤15 active minutes; ≥90%
of activity fields prefilled; nothing entered twice; a routine visit's
administration ≈60–90 seconds; weekly plans, fund requests and debriefs
system-prepared; manual attention concentrated on exceptions.

**Automation safety**: 100% of financial authorization, IA verification
and locked-value changes attributable to authorized humans; every
automatic action idempotent and auditable; every failure a visible
exception; no recommendation ever presented as a verified fact.

**Scale and reliability** (post-D1): realistic-volume load tests pass at
the target scale with margin; large reports never block submissions;
uploads resume; search stays scoped and fast; achievement and financial
maths reconcile under concurrency; SLOs defined and met; restore, offline
recovery and integration-failure drills all pass; no data loss through
deploys or worker failure.
