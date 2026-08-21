# Ecosystem Integration Audit — 2026-08-21

Scope covered in this pass: activity provenance (§7), the SSA → recommendation
→ planning chain (§11/§12), the event-driven automation backbone (§33), and
data reconciliation (§36). Evidence is from the live codebase and the dev
database, not from the platform guide.

## Baseline

| Item | Value |
|---|---|
| Branch | `hr-priorities-frontend-integration-audits` (off `main` @ `80b514a6`) |
| Routed surfaces | 565 (1,023 routes; 202 full pages; 338 component templates) |
| Roles / permission keys | 14 / 97 |
| Live activities (dev) | 604 — 371 staff, 233 partner |
| Migration state | clean (`makemigrations --check` → no changes) |
| Scheduled jobs | 22, all `Africa/Kampala` |

---

## Finding 1 — Activity provenance exists as fields, not as a rule (Critical)

The mandate's §7 `primary_driver_type` / `primary_driver_id` pair **does not
exist**. Provenance is spread across roughly ten nullable `Activity` fields
plus three external link tables (`hr_activity_priority_link`,
`bt_activity_link`, `core_activity_slot.activity_id`), and **no creation path
requires any of them**.

`Activity.Meta.constraints` holds exactly two constraints, both about
`salesforce_activity_id`. There is no `clean()`. An activity with no SSA, no
allocation, no rationale and no planning source can be created and can draw
budget.

Measured on the 604 live activities:

| Provenance field | Populated |
|---|---|
| `source` | 604 (100%) — but every value is `manual_upload` |
| `recommendation_source` | 604 (100%) |
| `source_ssa` | 2 (0%) |
| `planning_source` | 4 (0%) |
| `priority_links` | 0 |
| `business_transformation_link` | 0 |
| `project_id`, `cluster_slot` | 0 |

The uniform `manual_upload` traces to `apps/core/management/commands/seed.py:824`,
which creates activities with zero provenance — a state no application path
produces. So this measurement characterises the **seed data**, not the live
creation funnel. It does mean the §48 question *"does every field activity have
a traceable strategic or school-needs reason?"* cannot be demonstrated
end-to-end on this dataset.

**Fixed this pass:** `_partner_schedule_from_assignment`
(`apps/activities/services.py`) never set `planning_source` or
`activity_context_type`, so every partner-scheduled activity was born already
failing the platform's own `activity_without_planning_source` health check
(`apps/activities/work_plan_health.py:90`). It now records
`planning_source="partner_assignment"` and the correct context type.

**Not fixed (needs an owner decision):** adding a `primary_driver` pair and a
DB constraint requiring one. That changes every creation path and would block
work that currently proceeds.

---

## Finding 2 — There is no SSA recommendation record (Critical)

SSA recommendations are **computed live on every request and never persisted**.
`apps/ssa/models.py` contains exactly two models, `SsaRecord` and `SsaScore`.
The engine (`apps/ssa/recommendation_engine.py`) returns plain dicts.

What survives is a provenance stamp on the *accepted outcome* —
`Activity.source_ssa`, `source_score`, `source_classification`,
`recommendation_reason` — and only for recommendations someone acted on.

Consequently the platform has **no status, owner, expiry, version, dedupe key
or supersession** for a recommendation, and no row at all for one that was
never accepted. Nothing can answer *"what did we recommend last month, and what
happened to it"* — which is §12.2's central leadership question.

The analytics half is strong: confirmed-SSA-only filtering is applied
consistently, weights are renormalised over measurable components, min-N
honesty is enforced, and `ActivityInterventionMapping` is a properly governed
mapping backed by two database constraints. The record-keeping half is absent.

The codebase already contains two working templates for exactly this shape —
`TeamAction` (`condition_key` + partial unique constraint + `supersedes_id`)
and `DailyDebrief.recommendation_status`. Neither was applied to the SSA chain.

Related, unfixed: `requires_current_ssa` is enforced merely as *a confirmed
record exists*, with no recency bound — a four-year-old SSA satisfies a flag
named "requires current". Tightening it would block field work, so it needs an
owner's definition of "current" first.

---

## Finding 3 — The event backbone carries 2 of 27 expected events (Critical)

A genuine transactional outbox exists and is well built: enqueue rides the
business transaction, `idempotency_key` is unique, claims use
`SELECT … FOR UPDATE SKIP LOCKED`, backoff is exponential, a dead-letter state
exists with an Admin notification, a health check and a replay command.

It carries six event types, four of which are disabled by default
(`SALESFORCE_SYNC_ENABLED` / `NETSUITE_SYNC_ENABLED` default to off). **In the
default configuration two event types ever reach the outbox.**

Every other workflow fact — allocation approved, funds disbursed, evidence
submitted, achievement credited or reversed, leave approved — travels through
`WorkflowNotificationService.trigger`, which writes `Notification` rows inline
with no retry, no dead-letter and no replay.

Also found: `VerificationRequirementStatus.OVERDUE` is read by two Command
Center queues but **never assigned anywhere** — those queues filter on a state
the system cannot enter.

**Fixed this pass, three contained bugs that made failures invisible:**

1. **Poison pills retried forever.** A worker killed mid-handler left its row
   `PROCESSING` with an expired claim; reclaiming it never incremented
   `attempts`, so `max_attempts` was never reached. Such an event never
   dead-lettered, never alerted an Admin and never appeared in the health
   check — invisible except as a backlog that would not drain. A crash-reclaim
   now counts as an attempt and retires the event when its budget is spent.
2. **A dead-letter notification could strand its own event.**
   `_notify_dead_letter` ran *inside* the finishing transaction; a database
   error inside it poisoned a transaction its own `except` could not
   un-poison, so the following `save()` raised and the event stayed
   `PROCESSING` to be re-run forever. It is now deferred to `on_commit`.
3. **Dead letters could be announced to nobody.** Recipients were resolved by
   `active_role="Admin"` — the role a person is *currently viewing as*. An
   Admin who had switched roles received nothing, and if all had switched the
   function returned silently. It now resolves by held `roles`, and logs an
   error when no Admin exists.

Three regression tests pin the reclaim accounting.

---

## Finding 4 — Reconciliation results (§36)

Run against live data:

| Check | Result |
|---|---|
| Team → employee allocation reconciliation | **balanced**, no errors |
| Activities with more than one milestone credit | 0 |
| Credits attached to partner-delivered activities | 0 (partner work correctly excluded) |
| Scheduled activities with no cost line | 0 |
| One authoritative cost per activity | holds — multiple lines sum to one total |

The achievement-ledger checks could not be exercised: the dev database holds
zero `MilestoneProgressCredit` rows.

---

## What remains open

Ranked by consequence, all requiring an owner decision rather than a patch:

1. A persisted SSA recommendation entity with status, owner, expiry and
   supersession (§11.2/§11.3) — the largest single gap.
2. `primary_driver_type` / `primary_driver_id` on `Activity`, plus a
   constraint requiring one (§7).
3. Moving the remaining 24 workflow events onto the durable outbox (§33).
4. Defining "current" for `requires_current_ssa`, then enforcing it.
5. A canonical school-priority engine — three surfaces currently rank
   differently, and one (`command_center`) presents alphabetical order as
   priority with a hardcoded blank "weakest" column.
6. Seeding frequency/cooldown eligibility rules: `validate_frequency` returns
   early when a catalogue item has no rule, and none of the 28 seeded items
   has one, so repeat-recommendation limits are unenforced out of the box.
