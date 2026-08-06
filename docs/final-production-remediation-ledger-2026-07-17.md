# Final Production Remediation Ledger — 2026-07-17

This is the live, evidence-backed ledger for the final whole-platform audit.
An item is never closed on a code change alone: it must also have the required
data repair, integration, role, responsive, performance, and System Health
evidence where those fields apply.

## Status vocabulary

`Discovered` → `Reproduced` → `Root Cause Confirmed` → `Fix In Progress` →
`Backend Fixed` → `Frontend Fixed` → `Data Repaired` → `Integration Verified`
→ `Performance Verified` → `Role Verified` → `Responsive Verified` →
`System Health Green` → `Closed`

## Active items

### F01 — Production encryption configuration gate

| Field | Evidence |
|---|---|
| Phase / feature | 1 — Production configuration and restricted-data protection |
| Affected apps / models / services | `config`, `apps.core.crypto`, `apps.security.services`; encrypted restricted fields now and future MFA / finance fields |
| Affected routes / pages / roles | Production boot; Security Health; every authenticated role |
| Severity | High |
| Reproduction / root cause | `config.settings.prod` requires a JWT secret and persistent evidence storage but accepts an absent or malformed `FIELD_ENCRYPTION_KEY`, although `apps.core.crypto` cannot encrypt/decrypt restricted data without a valid 32-byte key. |
| Upstream / downstream impact | Misconfiguration is detected only when a restricted field is first used; that creates an operational outage and risks plaintext fallback workarounds. |
| Financial / SSA / target / security impact | Security: high. Finance and SSA: indirect. |
| Backend / frontend repair | Implemented: production startup validates a 32-byte hex/base64 `FIELD_ENCRYPTION_KEY`; Security Health now rejects merely non-empty malformed values. No UI change. |
| Migration / historical repair | None; deployment secret must be provisioned before boot. |
| Verification required | Missing/malformed/valid-key regression tests (green); `manage.py check` (green); production boot smoke with deployment secrets remains required. |
| Performance / design / health | No request-path cost; Security Health reports configured state. |
| Status / closure evidence | Backend Fixed — `apps.core.tests.test_field_encryption` green. Deployment-secret boot rehearsal outstanding. |

### F02 — Canonical cluster membership

| Field | Evidence |
|---|---|
| Phase / feature | 2–3 — Scope, clustering and planning eligibility |
| Affected apps / models / services | `schools.School.cluster_id`, `clusters.SchoolClusterAssignment`, `ClusterSubCounty`; cluster, planning, project, partner and scope services |
| Affected routes / pages / roles | School Directory, Cluster workspace, Planning, Core Schools; Admin, CCEO, PL, CD, Partner, Project Coordinator |
| Severity | High |
| Reproduction / root cause | Read surfaces use both the denormalized `School.cluster_id` and the assignment join. Several view paths mutate the pointer directly. A stale join or pointer can make school counts, scope, planning eligibility and cluster attendance disagree. |
| Upstream / downstream impact | Cluster assignment, scope resolution, SSA recommendations, planning, Core visibility and analytics can diverge. |
| Financial / SSA / target / security impact | Financial/SSA/target: medium. Security: high where stale membership changes object scope. |
| Backend / frontend repair | Implemented: `School.cluster_id` is canonical; the join is a deterministic compatibility projection. A lock-backed assignment service is now the operational writer, direct drawer/bulk writes route through it, and Planning, IA, My Plan, activities, partner assignment and coverage read the canonical pointer. |
| Migration / historical repair | Added `clusters.0003_repair_canonical_school_cluster_membership`: valid pointer wins; valid historic join repairs an absent pointer; stale projections are rebuilt. System Health reports projection drift. |
| Verification required | Cluster setup/bulk-assignment regression suite (green); production migration and System Health zero-drift evidence remain required. |
| Performance / design / health | Indexed membership reads; no visual redesign except honest mismatch/error states. |
| Status / closure evidence | Backend + Frontend Fixed; Data Repair migration ready; 49 focused cluster/readiness/SSA/workflow tests green. Production migration and scoped role rehearsal outstanding. |

### F03 — Planning-readiness vocabulary split

| Field | Evidence |
|---|---|
| Phase / feature | 3 — School data quality, SSA and planning readiness |
| Affected apps / models / services | `core.enums.PlanningReadiness`, `schools.School.recompute_quality_and_readiness`, SSA, planning, school, analytics and System Health services |
| Affected routes / pages / roles | School Directory, Data Quality, Planning, messages, command center; Admin, CCEO, PL, CD, IA, Partner |
| Severity | High |
| Reproduction / root cause | `School.recompute_quality_and_readiness()` writes `ready/limited/locked` when tests run and a different extended state machine in production; some views also persist undeclared legacy `blocked`/`limited` strings. |
| Upstream / downstream impact | The same school can have different planning eligibility, count, next action and UI badge in test versus production. |
| Financial / SSA / target / security impact | Financial/SSA/target: high through planning eligibility. Security: none direct. |
| Backend / frontend repair | Implemented: one environment-independent `School.recompute_quality_and_readiness()` state machine; legacy raw view writes removed; consumers use canonical readiness values and next actions distinguish cluster vs SSA work. |
| Migration / historical repair | Added `schools.0015_normalize_planning_readiness`, mapping legacy/unknown values from canonical cluster pointer and current-FY SSA facts. |
| Verification required | Cluster assignment, SSA upload, authenticated workflow and counters are green in the focused suite; production migration plus dashboard/API parity sweep remain required. |
| Performance / design / health | Indexed state remains; labels and pills use canonical choices; add readiness-vocabulary System Health check. |
| Status / closure evidence | Backend + Frontend Fixed; Data Repair migration ready; focused suite green. Full workflow/UI regression pending. |

### F04 — Domain-event and realtime delivery seam

| Field | Evidence |
|---|---|
| Phase / feature | 17 — Notifications, To-Dos, messages and realtime |
| Affected apps / models / services | `realtime.domain_events`, `realtime.bus`, `realtime.views`, `audit.DomainEventLog`, audit and notification services |
| Affected routes / pages / roles | `/api/realtime/stream`, notification rail, To-Dos and workflow pages; all roles |
| Severity | High |
| Reproduction / root cause | Repository search finds no workflow call to `domain_events.emit`; current workflow services write audit and notification effects independently, leaving `DomainEventLog` empty and SSE disconnected from real state changes. The in-process bus also cannot cross Daphne workers. |
| Upstream / downstream impact | Users can miss live next actions; event history cannot prove delivery; multi-worker realtime is inconsistent. |
| Financial / SSA / target / security impact | Financial/SSA/target: indirect but material to workflow timeliness. Security: medium (recipient isolation must remain explicit). |
| Backend / frontend repair | Implemented the non-recursive commit bridge: committed `AuditLog` rows create `DomainEventLog` rows and actor refresh events; direct workflow notifications dedupe recipients, audit their delivery command, and push only to recipients after commit. |
| Migration / historical repair | No backfill of historical live events; retain existing audit history. |
| Verification required | Event-log, rollback, notification recipient/dedupe and bus tests are green; SSE reconnect, queue-overflow and multi-worker/broker staging tests remain required. |
| Performance / design / health | Publish after commit; health reports broker/topology state and stale delivery. |
| Status / closure evidence | Backend Fixed — 8 event/notification tests green. Open for broker-backed multi-worker deployment validation. |

### F05 — Background scheduler deployment

| Field | Evidence |
|---|---|
| Phase / feature | 17 / 19 — Scheduled jobs and operational resilience |
| Affected apps / models / services | `realtime.registry`, `realtime.jobs`, `runscheduler`, System Health |
| Affected routes / pages / roles | System Health and all scheduled workflow recipients |
| Severity | Deployment blocker when any scheduled job is required |
| Reproduction / root cause | The dedicated worker is intentionally not provisioned under the current deployment decision. Code correctly refuses to run an idle scheduler, but no job can execute until an authorised worker service exists. |
| Upstream / downstream impact | Digests, escalations, periodic rollups and reminders do not run. Immediate user-request actions continue to work. |
| Financial / SSA / target / security impact | Depends on enabled jobs; target/finance periodic reconciliation is at risk if relied on operationally. |
| Backend / frontend repair | No code workaround: provision exactly one authorised worker only when the deployment decision changes; keep immediate inbox delivery synchronous. |
| Migration / historical repair | Run safe job catch-up / reconciliation after worker activation. |
| Verification required | Scheduler health, lock, retry, manual rerun and staging restart drill. |
| Performance / design / health | Health must stay critical while required jobs are disabled. |
| Status / closure evidence | Open — external deployment authority required |

### F06 — Client annual entitlement

| Field | Evidence |
|---|---|
| Phase / feature | 5–6 — Client planning and activity creation |
| Affected apps / models / services | `activities.services.create`, `Activity`, Planning service |
| Affected routes / pages / roles | Planning, My Plan, partner scheduling; CCEO, PL, Partner |
| Severity | High rule, implementation verified |
| Reproduction / root cause | The supplied mandate confirms the rule: one client visit and one client training per FY. The earlier guard used the *current* FY instead of the scheduled activity FY, did not lock concurrent creators, and the school-level training type had no usable form path. |
| Upstream / downstream impact | Prevents duplicate cost, budget, target and support entitlement. |
| Financial / SSA / target / security impact | Financial/SSA/target: high. Security: none direct. |
| Backend / frontend repair | Implemented: entitlement checks now use the derived scheduled FY under a locked school row; client training is an explicit school-level activity with a participant input in the scheduling drawer; cancelled/rejected/deferred records release the slot. |
| Migration / historical repair | Scan legacy duplicate active client slots before production. |
| Verification required | Visit cancellation/reopen, training slot, next-FY slot and Core cap tests are green. Partner/reschedule race and historical duplicate scan remain required. |
| Performance / design / health | Add duplicate-active-slot System Health rule if not already present. |
| Status / closure evidence | Backend + Frontend Fixed — 4 entitlement tests green. Historical duplicate scan and multi-request concurrency soak remain pending. |

### F07 — Frontend design-system and responsive baseline

| Field | Evidence |
|---|---|
| Phase / feature | 18 — Frontend/back-end synchronization and design parity |
| Affected apps / models / services | `frontend`, `system_health.ui_quality`, `projects`; no business-model change |
| Affected routes / pages / roles | All routed pages (inventory: 374 user-facing route surfaces); Special Projects My Plan has a dedicated responsive repair; all roles |
| Severity | High usability risk, no direct data corruption |
| Reproduction / root cause | Static inventory found 7 design-system violations (tiny form text, unthemed surface and inline icon style) and the dedicated Special Projects My Plan sheet used 8–11px labels, table text, badges and action links. The original quality lint did not inspect that separate page stylesheet. |
| Upstream / downstream impact | Dense tables, filters and pills become unreadable at common laptop/tablet scales; a staff member can make a wrong workflow choice even when the backend is correct. |
| Financial / SSA / target / security impact | Financial/SSA/target: indirect operational risk. Security: none direct. |
| Backend / frontend repair | Implemented: corrected message/project drawer token and text violations; regenerated the platform route/page inventory; Special Projects My Plan now has a 12px working minimum for labels/tables/pills/actions, 36–40px compact action targets and retains its 1380/1050/760/420 breakpoints. |
| Migration / historical repair | None. CDN/static cache is invalidated by the page stylesheet version change. |
| Verification required | `system_health` UI-quality and page-inventory suites are green. Authenticated local-admin desktop browser inspection confirms the full Special Projects My Plan hierarchy, filters and computed 12px+ operational text; tablet/mobile, dark-mode and keyboard checks in staging remain required. |
| Performance / design / health | Page CSS is isolated and avoids a Tailwind rebuild; static quality checks remain exposed in System Health. |
| Status / closure evidence | Frontend Fixed — automated quality findings: 0. Responsive/design closure is pending staging visual evidence. |

### F08 — My Plan and unmatched-SSA lifecycle bypasses

| Field | Evidence |
|---|---|
| Phase / feature | 4, 6, 10–14 — SSA, activity execution, evidence, review and target handoff |
| Affected apps / models / services | `frontend.views.my_plan_views`, `frontend.views.extended_views`, `activities.services`, `ssa.services`; `Activity`, `SsaRecord`, `SsaScore`, evidence and completion-verification records |
| Affected routes / pages / roles | My Plan drawers/actions, SSA unmatched queue, IA queue; CCEO, PL, IA, Partner, Admin |
| Severity | Critical workflow and analytics integrity |
| Reproduction / root cause | Several form actions wrote Activity status, attendance completion and SSA rows directly from views. This skipped canonical scope, evidence, Salesforce ID, attendance, partner acceptance, current-FY SSA, score/provenance, readiness and target gates. |
| Upstream / downstream impact | Users could reach review/finance/analytics with missing evidence or invalid SSA, and unmatched SSA resolution could create an apparently ready school without a valid canonical record. |
| Financial / SSA / target / security impact | Financial/SSA/target: high. Security: scope was inconsistently enforced by the bypass paths. |
| Backend / frontend repair | Implemented canonical `start_completion`, `record_attendance` and `submit_for_review` routing from My Plan; evidence/SSA drawers call canonical evidence/SSA services; unmatched-row match/create now calls `ssa.upload` inside an atomic school-onboarding transaction. Invalid source rows show an error and do not create an orphan school. |
| Migration / historical repair | Run the existing data-repair/System Health scan before production to locate legacy Activity/SSA inconsistencies; historical unmatched rows with obsolete indicator names require an approved mapping, not an inferred conversion. |
| Verification required | My Plan, partner/read-only, SSA validation and unmatched-SSA lifecycle suites pass; role-level IA/accountant rehearsal and historical repair report remain required. |
| Performance / design / health | Uses existing indexed canonical services and one transaction per resolution; no UI-only completion state remains. |
| Status / closure evidence | Backend + Frontend Fixed; Integration Verified locally. Historical data and staging role verification remain open. |

### F09 — Partner monitor identity and contextual messaging

| Field | Evidence |
|---|---|
| Phase / feature | 2, 6, 17 — scope, partner scheduling, My Plan and internal messaging |
| Affected apps / models / services | `PartnerAssignment.assigning_staff_id`, `Activity.monitored_by_staff_id`, planning/core/cluster services and messaging suggestions |
| Affected routes / pages / roles | Planning partner assignment, Partner schedule/reschedule, My Plan, contextual Message compose; CCEO, PL, Project Coordinator, Partner, Admin |
| Severity | High scope/operational correctness |
| Reproduction / root cause | Some planning drawers stored a raw `User.id`, while core scheduling expected `StaffProfile.id`. A partner scheduling a deferred assignment therefore created an Activity without its monitor; My Plan and message recipients could not reliably resolve the accountable staff member. |
| Upstream / downstream impact | Partner work can disappear from the monitoring queue and the internal message system can omit the responsible staff recipient. |
| Financial / SSA / target / security impact | Financial/SSA/target: medium through missed oversight. Security: high where an inconsistent id makes scope results unreliable. |
| Backend / frontend repair | Implemented canonical StaffProfile-first writer with documented User fallback; delayed `partner_schedule` resolves and persists the monitor; availability, My Plan display and message suggestions resolve both canonical and legacy identity shapes. |
| Migration / historical repair | Added `partners.0007_normalize_partner_assignment_staff_identity` to convert linked historic User ids. Admins without StaffProfiles retain their valid User-id fallback. |
| Verification required | Frontend partner assignment/scheduling regression and contextual messaging recipient tests pass. Apply migration and run scoped Partner/PL rehearsal in staging. |
| Performance / design / health | One indexed profile lookup on legacy activation; normal writes are canonical. |
| Status / closure evidence | Backend + Frontend Fixed; Data Repair migration ready. Staging migration and role evidence required. |

### F10 — Date/DateTime boundary consistency for SSA analytics

| Field | Evidence |
|---|---|
| Phase / feature | 4, 14, 16 — SSA, targets, activity impact and dashboards |
| Affected apps / models / services | `ssa.services`, `targets.my_targets`, `targets.team_targets`, `activities.services`; `SsaRecord.date_of_ssa` |
| Affected routes / pages / roles | Country Director dashboard, My Targets, Team Targets, activity impact; CD, PL, CCEO, IA |
| Severity | High analytics correctness / deployment reliability |
| Reproduction / root cause | SSA service and several dashboard/target queries accepted date-only inputs or compared a timestamp field to a DateField boundary. Django silently coerced the boundary to a naïve midnight datetime; under warning-as-error this made the CD dashboard return 500. |
| Upstream / downstream impact | FY target credit, SSA drilldowns, impact attribution and leadership dashboards can be incorrect at boundaries or fail in hardened environments. |
| Financial / SSA / target / security impact | SSA/target: high. Financial: indirect. Security: none direct. |
| Backend / frontend repair | `ssa._parse_date` normalizes all date-only inputs to timezone-aware values. Timestamped SSA queries now use canonical aware FY/month ranges; activity-impact comparisons use one explicit local-day boundary. |
| Migration / historical repair | Existing PostgreSQL timestamps are timezone-aware; no schema migration. Confirm imported legacy values during staging health/reconciliation. |
| Verification required | Repaired UI/workflow suite passes with `PYTHONWARNINGS=error::RuntimeWarning`, including the Country Director dashboard. Full analytics regression remains required. |
| Performance / design / health | Range predicates remain index-friendly. No visual regression expected. |
| Status / closure evidence | Backend Fixed and local Integration Verified; full analytics/staging parity remains open. |

### F11 — Effective fiscal-year cost catalogue on visit-batch reschedule

| Field | Evidence |
|---|---|
| Phase / feature | 6–8 — Scheduling, rescheduling and automatic costing |
| Affected apps / models / services | `daily_visit_batches.services`, `CostCatalogue`, `DailyVisitBatch`, `ActivityScheduleCostLine` |
| Affected routes / pages / roles | My Plan reschedule and daily visit scheduling; CCEO, PL, CD and Admin |
| Severity | High financial reconciliation risk |
| Reproduction / root cause | Daily visit batch creation selected a catalogue by its activity FY, but remove/reschedule/recalculation selected the globally latest active catalogue. Moving a visit across the September/October boundary could therefore price a FY 2027 activity from a FY 2026 rate card. |
| Upstream / downstream impact | Rate provenance, daily pool, activity cost lines, weekly requests and country budget periods could disagree after reschedule. |
| Financial / SSA / target / security impact | Financial: high. SSA/target: indirect. Security: none direct. |
| Backend / frontend repair | Implemented one batch-date resolver using the scheduled date's operational FY for removal, reschedule and fallback recalculation. Existing UI continues to show the backend-stamped catalogue and cost lines. |
| Migration / historical repair | No schema migration. Before release, reconcile any active batch whose `cost_catalogue.fy` differs from its `visit_date` FY and use the approved budget-amendment path where the source period is locked. |
| Verification required | Strict cross-FY reschedule test is green; deployment staging needs an October boundary reschedule with a distinct rate card and weekly/monthly reconciliation. |
| Performance / design / health | Single indexed catalogue lookup; no visible design change. Add/retain a System Health mismatch check for batch-date vs catalogue FY. |
| Status / closure evidence | Backend Fixed; local integration verified. Historical reconciliation and staging finance evidence remain open. |

### F12 — Required target-reference data resilience

| Field | Evidence |
|---|---|
| Phase / feature | 14 / 16 — Target achievement and leadership analytics |
| Affected apps / models / services | `targets.TargetArea`, `targets.my_targets`, `targets.team_targets`, `TargetAchievementLedger` |
| Affected routes / pages / roles | My Targets, Team Targets, target exports and leadership target rollups; CCEO, PL, CD, RVP and Admin |
| Severity | High analytics availability / completeness |
| Reproduction / root cause | The five official `TargetArea` rows were seeded only by a one-time migration. A restored, flushed or historically edited database could have no rows, causing key omissions in monthly target series and empty/incomplete dashboards. |
| Upstream / downstream impact | Annual fallback targets, weighted progress, team rollups, exports and To-Do risk signals could disappear or fail despite valid source work. |
| Financial / SSA / target / security impact | Target: high. SSA: indirect. Financial/security: none direct. |
| Backend / frontend repair | Implemented an idempotent reference-data guard that restores only missing official rows without overwriting existing administrator configuration. My Targets and Team Targets now consume that common active-area source. |
| Migration / historical repair | No schema migration. Deployment health scan must confirm exactly the five official areas and approved active/weight configuration. |
| Verification required | Annual fallback, five-area integrity, target ledger, team scope and impact suites run under warning-as-error locally; staging needs target/export parity against production data. |
| Performance / design / health | One small indexed configuration read; no client-side calculation or UI redesign. |
| Status / closure evidence | Backend Fixed and local integration verified; production reference-data health evidence remains open. |

### F13 — Local System Health data-repair backlog

| Field | Evidence |
|---|---|
| Phase / feature | 3–20 — data integrity, workflows and release operations |
| Affected apps / models / services | Schools/clusters, partner assignments/activities, evidence storage, projects, daily visit batches, geography, accountability and client entitlements; `system_health.services.report` |
| Affected routes / pages / roles | System Health and all dependent operational pages; Admin, CD, PL, CCEO, Partner, IA and Accountant |
| Severity | Deployment blocker until the production snapshot is clean or each exception is approved and remediated |
| Reproduction / root cause | Read-only local System Health snapshot on 2026-07-17 is not clean: 685 unclustered schools (including 100 Core), 100 partner rows without a linked partner-visible work item/monitor, 25 project schools without a project activity this FY, 84 scheduled staff visits without a Daily Visit Batch, 135 unclassified districts, 2 duplicate active client entitlement slots, plus isolated evidence, participant, NetSuite and setup findings. Local data is a development dataset (`isProduction=false`, dev seed enabled), so it is evidence of repair logic to execute—not proof that the production dataset has the same counts. |
| Upstream / downstream impact | Unrepaired production equivalents can block planning, hide partner work, invalidate staffing/route costs, corrupt entitlements, or make finance/closure queues incomplete. |
| Financial / SSA / target / security impact | Financial/SSA/target: high. Security: scope/visibility risk for partner monitoring. |
| Backend / frontend repair | Health checks and safe repair command exist. Do not infer cluster, geography, partner user, project-activity, evidence-file, NetSuite or duplicate-entitlement resolutions from incomplete data; each requires the authoritative owner or an approved repair rule. |
| Migration / historical repair | Run the scripted migration/data repair sequence against a restored production copy first. Export each remaining row with owner and resolution, repair in an approved transaction, and re-run System Health until `workflowIssues.clean=true`. |
| Verification required | Clean production-copy System Health, reconciliation report, partner visibility check, cost/batch integrity, entitlement conflict resolution and evidence-storage validation. |
| Performance / design / health | System Health correctly exposes the backlog; it is not green. |
| Status / closure evidence | Reproduced locally; production data audit and approved repairs are required. |
