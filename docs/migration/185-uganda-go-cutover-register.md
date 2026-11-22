# 185 · Uganda Go Cutover — Dependency & Workflow Register (Post Phases A–D)

## 1. Verified Evidence Summary

| Item | Verified Value |
|---|---|
| **Branch** | `feature/edify-go-rn-migration` |
| **Base HEAD commit** | `3f62af8e1` (758 commits ahead / 2 commits behind `origin/main` `6c1a52d09`) |
| **Completed batches** | **Phase A (Batches 1–6)** + **Phase B (Batches 9–10)** + **Phase C (Batches 11–13)** + **Phase D (Batches 14–15)** |
| **Inventory totals** | `docs/platform-page-inventory.json`: **1,469 routes**, **955 pages**, **669 components**; `docs/platform-interaction-inventory.json`: **4,130 controls**; `docs/migration/179-stage-a/permissions-matrix.csv`: **232 role-gated routes** |
| **Go page & service coverage** | **219+ routes** natively answered by Go, plus **`/profile`** (5/5 parity, 0 diff), **`/my-plan`** for real CCEOs/PLs (wired to `planningmonitor.OwnReadiness` + `cluster_status.go` + table pagination), **`/help/context`** (`internal/helpcontext`), **acting-capacity page & navigation reads** (`internal/acting/policy.go` withheld-page enforcement + `internal/screens/page.go` seat resolution), and **17 `todos` builders** ported natively (eliminating officer/PL/CD/HR/Accountant guards). |
| **Switchable legacy saves (`EDIFY_GO_SAVES`)** | **11** switches (`schedule_visit`, `reschedule_visit`, `cancel_visit`, `edit_visit`, `schedule_training_pair`, `group_reschedule`, `group_cancel`, `schedule_group_training`, `schedule_cluster_meeting`, `complete_visit`, `pl_review`) — **all 11 now operate with `EDIFY_EXISTING_APP_URL=""`** (zero `?form_only=1` Django dependency). |
| **Configured flags by environment** | **Local dev / CI:** `EDIFY_GO_SAVES=""`, `EDIFY_STRICT_READS=false`. **Candidate Zero-Django Staging (`.do/uganda-go-staging.yaml`):** `EDIFY_ENV=staging`, `EDIFY_EXISTING_APP_URL=""`, `EDIFY_STRICT_READS=true`, all 11 `EDIFY_GO_SAVES` enabled. **Production:** **Unknown / Untouched** (hard-refused by `config.ErrProductionNotApproved`, `dbguard`, Next.js `environment.ts`, and mobile `environment.ts`). |
| **Standalone Python Analytics Worker** | `platform/workers/analytics` — **100% Django-independent**: 0 Django imports, refuses startup if `DATABASE_URL`/`PG*` set, **21/21 pytest passed**. |

---

## 2. Runtime & Build-Time Django Dependencies — Final State

### 2.1 Go → Django HTTP Relays (All 6 Replaced for Django-Absent Operation)

| # | Legacy Relay | Native Go Replacement (When `EDIFY_EXISTING_APP_URL=""`) | Status |
|---|---|---|---|
| 1 | `activities.NewHTTPPricing` | `activities.NewNativePricing` + `internal/costing/daypool` (835 vectors) + `notificationcenter.Writer` | **Replaced in Go** |
| 2 | `loans.NewLedgerClient` | `loans.NewNativeLedger` (`loans_ledger_roles.sql`, `gateway_loans_ledger.*` with `idempotency_key` dedupe) | **Replaced in Go** |
| 3 | `signin.NewHTTPRelay` | `signin.NewDirectRelay` (delivers security alerts via `notificationcenter.Writer`) | **Replaced in Go** |
| 4 | `accounts.NewHTTPRelay` | `accounts.NewDirectRelay` (delivers account lifecycle notices via `notificationcenter.Writer`) | **Replaced in Go** |
| 5 | `clusterlead.NewHTTPOnboarder` | `clusterlead.NewDirectOnboarder` (`cluster_onboard_roles.sql`, `gateway_cluster_onboard.ensure_leader_account`) | **Replaced in Go** |
| 6 | `clusterlead.NewHTTPNoticeSender` | `clusterlead.DirectNoticeSender` (`notification_roles.sql`, `notificationcenter.Writer`) | **Replaced in Go** |

### 2.2 Scheduled Jobs (41/41 Registered in Standalone Go Scheduler)
- `platform/backend/internal/scheduler/catalog.go` registers **all 41** operational jobs from `apps/realtime/registry.py` (`LockKey` `400201..400241`) plus `cluster_action_followup` (`400101`) and `scheduler_heartbeat` (`400102`) inside `cmd/scheduler` under PostgreSQL session advisory locks (`PGLocker`) and `Africa/Kampala` fiscal year boundaries (`KampalaOperationalFY`).
- `platform/backend/Dockerfile` builds both `/gateway` and `/scheduler` into a minimal distroless image with zero Python/Django runtime.

### 2.3 Build-Time & Deployment Independence
- **Next.js web (`platform/web`):** `EDIFY_EXISTING_WEB_URL` is now optional (`environment.ts`); verified `tsc --noEmit`, `eslint --max-warnings 0 .`, **49/49 Vitest suites (338/338 tests)**, and `EDIFY_ENV=staging EDIFY_GATEWAY_URL=https://gateway-staging.example.com npm run build` (**34/34 routes compiled with zero Django**).
- **Expo/React Native (`platform/mobile`):** verified `tsc --noEmit` + **34/34 Jest suites (276/276 tests)**.
- **Go backend (`platform/backend`):** verified `gofmt`, `go vet -tags integration ./...`, full `go test ./...`, and `internal/costing/daypool` (835 vectors).
- **Candidate staging spec:** `.do/uganda-go-staging.yaml` deploys `gateway` + `scheduler` + `web` + `analytics` with zero Django process or `manage.py` command.
- **Backup & Restore:** `platform/deploy/db/rehearse-backup-restore.sh` verified custom `pg_dump` (data schemas) → fresh DB + `pg_trgm` → `pg_restore` → `apply-roles.sh` → row count reconciliation in **11s total** (`backup=1s restore=8s roles=2s`, `schools=700 activities=264`, 0 errors, zero Django).
- **Remaining migration note:** Reconciling `apps/accounts/migrations/0040_*` collision with `origin/main` applies only while Django remains deployed in parallel prior to retirement; once Uganda runs on Go-only staging/prod, inherited `public.*` schema changes move exclusively to SQL migrations.

---

## 3. Workflow Register (By Domain)

| Workflow Domain | Entry Points | Role / Country | Source of Truth | Final Owner (Django-Absent) | Test Evidence | Status |
|---|---|---|---|---|---|---|
| **Identity & Navigation** | `/login`, `/auth/*`, `/settings`, `/profile`, `GetNavigation`, acting capacities | All roles; Uganda + multi-country | Postgres `"user"`, `refresh_token`, `acting_assignment` | **Go** (`signin`, `accounts`, `navigation`, `profilepage`, `acting`, `workforceops`) | `signin`, `accounts` (incl. self-reset block), `navigation` (incl. acting), `TestProfilePageMatchesTheExistingPage` (5/5, 0 diff), `acting/withheld_test.go` | **Go-native** |
| **School Visit Vertical Slice** | `/schools`, `/my-plan`, `/calendar`, `Schedule`, `Edit`, `Reschedule`, `Cancel`, `Complete`, `/pl/review-queue`, CSV export | CCEO, PL; Uganda (`countryctx` RLS) | Postgres `school`, `activity`, `activity_salesforce_reference`, `activity_completion_verification`, `audit_log` | **Go** (`activities`, `myplan` + `OwnReadiness`, `plreview`, `screens`) | `TestSchoolVisitVerticalSliceWithoutDjango` (Django absent, `/my-plan` 10 blocks, restart verified, 0 fallbacks) | **Go-native (Proven)** |
| **Field Evidence, SSA, IA & Partners (M7–M10)** | Evidence upload/download, SSA entry/CSV/confirm, IA verify/return, partner handovers/dating/return | CCEO, PL, IA, Partner, Admin | Postgres `evidence_record`, `ssa_record`, `ssa_score`, `partner_assignment`, `audit_log` | **Go** (`fieldops` + `field_ops_roles.sql`) | `fieldops` unit tests + `TestUgandaCutoverPhaseCWithoutDjango` (interrupted upload refused, idempotent upload, RBAC download, SSA entry+confirm) | **Go-native (Proven)** |
| **Finance & Lending (M12)** | Weekly fund requests, approvals, disbursements, receipts, accountability, monthly budgets, loan ledger | CCEO, PL, CD, Accountant, Lender, Admin | Postgres `weekly_fund_request`, `advance_request`, `monthly_work_plan_budget`, `bt_*`, `school_loans.*` | **Go** (`financeops` + `finance_roles.sql`, `loans.NativeLedger` + `loans_ledger_roles.sql`, `costing/daypool`) | `costing/daypool` (835 vectors), `financeops` unit tests, `TestUgandaCutoverPhaseCWithoutDjango` (duplicated disburse callback idempotent, exact UGX variance=0) | **Go-native (Proven)** |
| **Oversight, Workforce & Scheduling** | `/todos`, `/today`, `/leave/*`, `/escalations`, `/help/context`, 41 scheduled jobs | All roles | Postgres `leave`, `leadership_escalation`, `team_action`, `help_center_*` | **Go** (`todos` + 17 native builders, `helpcontext`, `workforceops`, `scheduler` 41 jobs) | `todos`, `scheduler` (41 jobs + Kampala FY rollover + advisory locks), `TestNativeNotificationsAndLeaseSchedulerWithoutDjango` | **Go-native** |
| **Communications, Exports & Multi-Country** | `/messages`, `/notifications`, async CSV exports, UG vs KE isolation | All roles, UG + synthetic KE | Postgres `message`, `notification`, `country_registry.*` | **Go** (`messaging`, `notificationcenter.Writer`, `exports.Manager`, `countryctx`) | `exports` unit tests (creation + download + cross-country auth), `TestUgandaMultiCountryIsolation`, `TestUgandaCutoverAcceptanceRehearsalAndSLO` | **Go-native (Proven)** |

---

## 4. Cutover Verdicts (Post Phases A–D)

| Verdict | Status | Date | Evidence |
|---|---|---|---|
| **Uganda technically independent in isolated rehearsal** | **PROVEN (Local Rehearsal)** | 2026-11-21 | Zero-Django integration suites, full Go/Web/Mobile/Analytics test suites, Django-absent Next.js staging build, 41-job advisory-lock Go scheduler, 11s local backup/restore rehearsal, and 50-concurrency local SLO probe (`p95=177.6ms <= 300ms`) all PASS. Deploy `.do/uganda-go-staging.yaml` to live DO staging to complete remote staging sign-off. |
| **Uganda authorized for production cutover** | **BLOCKED (Awaits Live Staging + Owner Sign-Off)** | 2026-11-21 | Requires deploying `.do/uganda-go-staging.yaml` to live staging, 500-user staging load test & EAS mobile build startup/sync measurements, finance month-end close sign-off, and explicit release-owner approval. Production guards remain intact. |
| **Django retired in production** | **BLOCKED** | 2026-11-21 | Awaits authorized production cutover and agreed post-cutover observation window. |
| **Kenya, Rwanda, Ethiopia ready for launch** | **BLOCKED (Production Rollout Pending)** | 2026-11-21 | Multi-country workspaces and cross-country isolation verified in Go with synthetic `KE` (`KES`), `RW` (`RWF`), and `ET` (`ETB`) fixtures across directory, messaging recipients, and CSV exports (`TestStep5MultiCountryAnalyticsGRPCAndSLOBenchmarks`); per-country production data import and launch remain separate decisions. |

---

## Step 1–6 Implementation Brief Completion Evidence (2026-11-21)

- **Step 1 (Financially correct school-visit workflow through shipped gateway):** `platform/deploy/db/costing_settle_roles.sql` (`edify_costing_owner`, `gateway_costing`) + upgraded `internal/activities/native_pricing.go` wired directly into `internal/costing/daypool` and `internal/costing` against live operational rate cards (`cost_catalogue`, `cost_setting`). Proven end-to-end through `server.New` RPCs (`SavePlanningDrawer`, `SaveDrawer`) in `TestGatewaySchoolVisitFinancialCorrectnessWithoutDjango` with exact integer UGX pool conservation, reschedule old+new day re-settlement, locked weekly fund request refusal, cancellation, idempotent `HandedIn` notification, unrelated PL denial, supervising PL approval, durable `plan.changed` domain events, and `FallbackTracker.Total() == 0`.
- **Step 2 (Full business effects of legacy relays, lending ledger, and live session revocation):** `platform/deploy/db/relay_ops_roles.sql` (`gateway_relay_ops`), updated `cluster_onboard_roles.sql` (staff email conflict check, `pending_invited`, `user_invitation` SHA-256 token hash, `audit_log`), hardened `loans_ledger_roles.sql` (concurrent `ON CONFLICT DO NOTHING` idempotency + NOT NULL parity), `signin.DirectRelay` (`admin_system_incident` + dedupe + Admin alert), `accounts.DirectRelay` (`account_deleted` partner login release + `roles_changed` day-pool re-pricing). Proven in `TestStep2RelaysLedgerAndLiveRevocationWithoutDjango`, including immediate restriction of an already-open bearer token when DB role is revoked.
- **Step 3 (User-facing Next.js web handoffs removed):**
  - `/support`: replaced Django redirect with native Go `/api/v1/support/tickets` (`support_roles.sql`, `internal/support/service.go`, `platform/web/src/app/(app)/support/page.tsx`).
  - `/messages`: replaced Django handoff with native Go read-thread (auto mark-read), reply, compose, star, archive (`messaging_roles.sql`, `internal/messaging/http.go`, `platform/web/src/app/(app)/messages/page.tsx`, `lib/messagesInbox.ts`).
  - `/notifications`: replaced Django `DeliverySettings` handoff with native Go `POST /api/v1/notifications/preferences` (`notification_roles.sql`, `internal/notificationcenter/preferences.go`, `DeliverySettings.tsx`) and native in-app deep links (`NotificationList.tsx`).
  - Bulk Selection (`SelectionBar.tsx`): replaced Django redirect for activity bulk reschedule/cancel with native Go two-step **Preview (0 writes, explains excluded rows) → Confirm (idempotent, double-click safe)** (`internal/activities/bulk_http.go`, `bulk/activities/actions.ts`, `SelectionBar.tsx`).
  - Verified in `TestStep3SupportMessagesNotificationsAndBulkWithoutDjango` + Next.js `tsc`, `eslint --max-warnings 0`, 49/49 Vitest suites (338/338 tests), and Django-absent staging `next build` (34/34 routes).
- **Step 4 (Real 41-job Go scheduler & operational recovery):** `platform/deploy/db/scheduler_jobs_roles.sql` (`gateway_scheduler`) + real operational logic in `internal/scheduler/catalog.go` + machine-readable 41-job disposition register `docs/migration/188-uganda-cutover-disposition.json`. Proven with 2 independent replicas, controlled clock, simulated crash advisory-lock recovery, poison-record quarantine (5 failures -> `held_at` set, non-blocking), and ground-truth `scheduled_job_execution` records in `TestStep4SchedulerControlledClockTwoReplicasCrashAndQuarantine`. Backup + restore + `apply-roles.sh` verified cleanly in 16s (`rehearse-backup-restore.sh`).
- **Step 5 (Multi-country workspaces, standalone Python analytics gRPC, SLO benchmarks):** Proven in `TestStep5MultiCountryAnalyticsGRPCAndSLOBenchmarks` — UG + synthetic KE/RW/ET isolation, live Go → standalone Python analytics gRPC (`SummarizePortfolio`, zero Django, zero DB env vars), and 40-concurrent Django-absent SchoolDirectory benchmark (`p50=294.5ms, p95=299.1ms, max=299.1ms`, within `p95 <= 300ms` and `pin <= 2s`).
