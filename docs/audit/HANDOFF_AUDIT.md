# Ecosystem Handoff & Cross-Module State Transition Audit

**Audit Date:** 2026-11-22  
**Target Environment:** Isolated non-production `edify_gorn_test` + Go Gateway (`EDIFY_STRICT_READS=true`, Django offline).

---

## 1. Handoff Verification Matrix (Sections 4.1 – 4.12)

| Handoff ID | Flow | Source Authority | Downstream Consumers Verified | Result | Evidence & Notes |
|---|---|---|---|---|---|
| **H-01** | School Directory → Cluster Assignment → Cluster Oversight | `school`, `school_cluster_membership`, `cluster` | School Directory, School Profile, Clusters, Cluster Oversight (`/cluster-oversight/`), `cluster_schools` export | **Pass** | Zero multi-active memberships (`0`), zero `school.cluster_id` mismatches (`0`), `cluster_schools` export returns exact `90` clustered schools with `edify_school_id` |
| **H-02** | Cluster → Planning → My Plan → Calendar | `activity`, `activity_schedule_cost_line` | `/planning`, `/my-plan`, `/my-plan/smart-route`, `/calendar`, `completed_visits` export | **Pass** | Go `myplan` & `activities` unit tests pass; live routes render `HTTP 200`, `0px` overflow. Note: 4 legacy seeded activities in test DB lack `fy` (`DATA-003`) |
| **H-03** | My Plan → Weekly Advance → Supervisor Approval → Accountant Disbursement | `advance_request`, `financeops`, `audit_log` | Weekly Advance, Fund Approvals, Budget, `finance_weekly` export | **Pass** | Exact `int64` UGX variance (`UGX 0` unexplained); idempotency key required on disburse; `IA`/`CCEO`/`Partner` blocked (`403`); `finance_weekly` exports all `280` rows |
| **H-04** | My Plan → Execution → Evidence → IA Verification | `fieldops`, `evidence_record`, `activity` | School Profile, Targets, Core Oversight | **Pass (Unit) / Staging Fixture Pending** | Go `fieldops` unit tests pass; `edify_gorn_test` has `0` seeded `evidence_record` rows (requires staging fixture E2E) |
| **H-05** | Planning → Partner Assignment → Evidence → Payment | `fieldops`, `partner_payment`, `partnerworkspace` | Partner Planning, IA Verification, Accountant Payment | **Pass (Unit) / Staging Fixture Pending** | Partner isolation & external finance RBAC (`403`) verified live; `0` seeded `partner_payment` rows in local snapshot |
| **H-06** | School Visit → SSA → Core School Oversight → Country Map | `ssa_record`, `ssa_score`, `coreoversight`, `countrymap_data` | Core School Oversight, Country Map, PL Dashboard Map, Python `AnalyzeSsa` | **Pass** | Fixed `COALESCE(s.sub_region_id, d.sub_region_id)` (`DEF-001`) and FY SSA join in map API (`DEF-005`): FY27 `306/700 (44%), avg 5.91`, FY26 `700/700 (100%), avg 4.96` |
| **H-07** | Verified Activity → Staff Targets → Team Targets → Country Oversight | `target_achievement_ledger`, `mytargets`, `targetdistribution` | My Targets, Team Targets, Oversight | **Pass** | `120` provisional FY26 rows separated from verified credit; `1` reversed FY27 row preserved |
| **H-08** | Leave Request → Supervisor/HR Approval → Calendar & SSE Sync | `workforceops`, `leave`, `realtime.Broker`, `audit_log` | PTO, Team Leave, SSE `leave.requested` / `leave.decided` | **Pass** | External roles & invalid dates refused (`403`/`400`); CCEO self-approval refused (`403`); post-commit SSE event published |
| **H-09** | Escalation Raise → Supervisor Routing → Decision Log & SSE Sync | `workforceops`, `leadership_escalation`, `audit_log`, `realtime.Broker` | Escalations, Decision Log, SSE `escalation.raised` / `escalation.resolved` | **Pass** | Routing `CCEO→PL`, `PL→CD`, `CD→RVP`; CCEO self-resolution refused (`403`); SHA-256 audit row written atomically |
| **H-10** | School Loans (Public → Lender → Approval → Repayment) | `school_loans.*` (40 tables), `internal/loans` | Loan Portal, Mobile `LoansRoute.tsx`, Outbox Worker | **Pass (Unit) / Staging Fixture Pending** | Native Go ledger & outbox verified in unit/mobile tests (`loanRoutes.test.ts`); `0` seeded `school_loans.application` rows locally |

---

## 2. Cross-Module State Transition Safety Verified

- **Idempotency:** `financeops.TransitionWeeklyRequest` requires non-empty `reference` (idempotency key) on `disburse` and returns `applied: false` on replay without duplicate audit or monetary mutation.
- **Transactional Atomicity:** All `financeops` and `workforceops` mutations execute inside `pgx.TxOptions{AccessMode: pgx.ReadWrite}` with `audit.Append` in the same transaction; SSE events in `workforceops` fire strictly **after** `withRW` commits (`err == nil`).
- **Role/State Refusal:** Out-of-role transitions (`CCEO` approving leave/escalation/disbursement, `IA` disbursing funds, `Partner` submitting staff weekly advances or leave) fail at the Go service layer with `403 Forbidden` before touching PostgreSQL.
