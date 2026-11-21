# 186 · Uganda Go Cutover — Release, Rollback Runbook & Batch Handoff

## 1. Candidate Scope & Guardrails

- **Branch:** `feature/edify-go-rn-migration` (based on `3f62af8e1`, with Phases A–D / Batches 1–15 implemented and verified locally).
- **Candidate zero-Django staging spec:** `.do/uganda-go-staging.yaml` (`gateway` + `scheduler` + `web` + `analytics`; zero Django service or `manage.py` commands; `EDIFY_STRICT_READS=true`, all 11 `EDIFY_GO_SAVES` enabled).
- **Hard environment guards (intact):**
  - `EDIFY_ENV=production` is hard-refused by `platform/backend/internal/config` (`ErrProductionNotApproved`), `platform/web/src/lib/environment.ts`, and `platform/mobile/src/config/environment.ts`.
  - `dbguard` blocks any production host/marker and enforces least-privilege non-superuser roles in staging (`default_transaction_read_only=on` on the pool; narrow `SECURITY DEFINER` Postgres functions for writes).
  - **No production shutdown, write, traffic shift, credential change, or data deletion is authorized by this runbook.** Production cutover requires explicit release-owner sign-off after staging rehearsal passes all gates below.

---

## 2. Pre-Flight & Candidate Build Commands (Clean Staging Environment)

### 2.1 Database Roles & Go-Owned Schema Migrations
```bash
# 1. Apply least-privilege gateway roles and SECURITY DEFINER write functions
EDIFY_ENV=staging \
EDIFY_ADMIN_DATABASE_URL="postgresql://<admin>@<staging-host>:25060/<db>?sslmode=require" \
  platform/deploy/db/apply-roles.sh

# 2. Apply Go-owned schema migrations (separate migration credential)
cd platform/backend
EDIFY_MIGRATE_DATABASE_URL="postgresql://<admin>@<staging-host>:25060/<db>?sslmode=require" \
  go run ./cmd/schemactl migrate --schema=country_registry --confirm-database=<db>
EDIFY_MIGRATE_DATABASE_URL="postgresql://<admin>@<staging-host>:25060/<db>?sslmode=require" \
  go run ./cmd/schemactl migrate --schema=school_loans --confirm-database=<db>
EDIFY_MIGRATE_DATABASE_URL="postgresql://<admin>@<staging-host>:25060/<db>?sslmode=require" \
  go run ./cmd/schemactl migrate --schema=field_routes --confirm-database=<db>
EDIFY_MIGRATE_DATABASE_URL="postgresql://<admin>@<staging-host>:25060/<db>?sslmode=require" \
  go run ./cmd/clusterctl migrate --confirm-database=<db>
```

### 2.2 Candidate Artifacts & Verification
```bash
# Go gateway + standalone Go scheduler + vulnerability check
cd platform/backend
go vet -tags integration ./...
go test -race -count=1 ./...
../.bin/govulncheck ./...
go build -trimpath -ldflags="-s -w" -o /tmp/edify-gateway ./cmd/gateway
go build -trimpath -ldflags="-s -w" -o /tmp/edify-scheduler ./cmd/scheduler

# Standalone Python analytics worker (verified 0 Django imports, refuses DB env vars)
cd ../workers/analytics
.venv/bin/python -m pytest -q

# React Native mobile & Next.js web
cd ../mobile && npm run typecheck && npm test
cd ../web && npm ci && npm run typecheck && npm run lint && npm test && npm run build
```

### 2.3 Django-Absent Acceptance Rehearsal & Backup/Restore (Isolated Database)
```bash
# 1. Full Django-absent integration & SLO rehearsal
cd platform/backend
EDIFY_TEST_ADMIN_DATABASE_URL=postgresql://localhost:5432/edify_gorn_test \
  go test -race -count=1 -tags integration ./internal/integration/ \
  -run 'TestSchoolVisitVerticalSliceWithoutDjango|TestNativeNotificationsAndLeaseSchedulerWithoutDjango|TestUgandaMultiCountryIsolation|TestUgandaCutoverPhaseCWithoutDjango|TestUgandaCutoverAcceptanceRehearsalAndSLO' -v

# 2. Django-absent PostgreSQL backup, restore (data schemas + pg_trgm), role re-apply, and row reconciliation
EDIFY_SOURCE_DB_URL=postgresql://localhost:5432/edify_gorn_test \
  platform/deploy/db/rehearse-backup-restore.sh
```
> [!NOTE]
> **Backup/Restore Operational Rule (verified 2026-11-21):** Dump the 5 data schemas (`public`, `cluster_leadership`, `school_loans`, `field_routes`, `country_registry`) excluding ephemeral `gateway_*` SECURITY DEFINER function schemas; pre-install `CREATE EXTENSION IF NOT EXISTS pg_trgm;` on the target DB; restore via `pg_restore --use-list` (excluding `SCHEMA - public`); then run `platform/deploy/db/apply-roles.sh`. Measured local rehearsal: **backup=1s, restore=8s, roles=2s, total=11s** (`schools=700`, `activities=264`, 0 errors).

---

## 3. Phased Rollout Order & Feature Flags

| Stage | Cohort | Flags | Gate to Advance |
|---|---|---|---|
| **Stage 0: Shadow Reads** | Internal QA + 1 Uganda team | `EDIFY_STRICT_READS=false`, `EDIFY_GO_SAVES=""` | 0 parity regressions; fallback log baseline recorded (`screens: django fallback attempt`) |
| **Stage 1: Strict Reads** | Staging Uganda cohort | `EDIFY_STRICT_READS=true`, `EDIFY_GO_SAVES=""` | 0 blocked read attempts across core role journeys; p95 latency ≤ 300 ms |
| **Stage 2: Rehearsed Writes (M4/M8/M9)** | Pilot Uganda PL + CCEOs | `EDIFY_GO_SAVES=schedule_visit,reschedule_visit,cancel_visit,edit_visit,complete_visit,pl_review` | 0 shadow diffs, 0 duplicate Salesforce refs/verifications, audit chain intact (`verify_chain`) |
| **Stage 3: Standalone Scheduler & Notifications (M11)** | Staging | Run `cmd/scheduler` alongside `cmd/gateway` with `EDIFY_EXISTING_APP_URL=""` | Single-executor advisory locks verified on failover; 0 duplicate notices |
| **Stage 4: Remaining Workflows & Finance Close (M7/M10/M12)** | Staging → Full Uganda | Remaining writes + Go costing (`costing-day-pool`) + 41 scheduled jobs migrated | Full finance month-end close reconciled to the cent; 0 attempted Django calls |

---

## 4. Monitoring Thresholds & Mandatory Rollback Triggers

**Stop expansion immediately if ANY trigger fires:**
1. Any unexplained financial/amount discrepancy between Go and reconciled ledger totals.
2. Any lost or inaccessible evidence record or broken attachment reference.
3. Any cross-country data leak (Uganda user seeing synthetic KE/RW/ET rows or exports).
4. Any duplicate write (duplicate `activity_salesforce_reference`, duplicate advance/disbursement, or duplicate notification for the same `source_event_id`).
5. Any attempted Django fallback call (`screens: django fallback attempt`) in a migrated Django-absent cohort.
6. Error rate > 1% on migrated RPCs or API p95 > 300 ms sustained over 15 minutes.

### Zero-Data-Loss Rollback Procedure (Never Discard Accepted User Work)
1. **Pause intake:** Set `EDIFY_GO_SAVES` to remove only the affected save flag (or disable the affected route at the gateway/load balancer) while keeping Go reads live.
2. **Drain in-flight work:** Allow graceful shutdown (`SIGTERM`, 15 s grace window; `cmd/gateway` and `cmd/scheduler` wait on `sync.WaitGroup` for active transactions and workers to commit/exit).
3. **Reconcile records created during Go ownership:**
   - Every Go write uses the exact same `public.*` table schema, CUID format, and `audit_log` hash chain as Django — **no database restore that discards accepted work is used**.
   - Verify `activity_salesforce_reference`, `activity_completion_verification`, `audit_log` chain integrity, and `notification` rows written during the Go window before re-opening the Django writer for that cohort.
4. **Resume:** Only re-enable a single authoritative writer per operation and cohort. Never run dual active writers for the same operation.

---

## 5. Performance & Availability Targets (Infographic Gate)

| Target | Threshold | Measurement Status |
|---|---|---|
| API p95 latency | ≤ 300 ms | **Local 50-concurrency Django-absent probe: p50=102.3ms, p95=177.6ms, max=182.1ms (PASS)**; 500-user remote staging load run pending deployment of `.do/uganda-go-staging.yaml` |
| Map pins (≤ 500 schools) | ≤ 2 s | **Pending live staging load run** |
| Route planner (≤ 10 stops) | ≤ 5 s | **Pending live staging load run** |
| Concurrent active users | ≥ 500 | **Pending live staging load run** |
| Mobile startup | ≤ 3 s | **Pending EAS release build** |
| Offline sync after reconnect | < 30 s | **Pending EAS release build** |
| Backup & Restore (isolated DB) | Clean restore + role re-apply | **Verified locally (2026-11-21): total 11s (backup=1s, restore=8s, apply-roles=2s, 0 errors)** |
| Availability | 99.9% | **Requires agreed operational observation window in staging/prod** |

---

## 6. Updated Cutover Verdicts (Post Phases A–D / Batches 1–15)

| Verdict | Status | Date | Evidence |
|---|---|---|---|
| **Uganda technically independent in local rehearsal** | **PROVEN (Ready for Live Staging Deploy)** | 2026-11-21 | All 6 internal HTTP relays replaced natively in Go (`NativePricing` + `costing/daypool` 835 vectors, `NativeLedger`, `DirectRelay` for signin/accounts, `DirectOnboarder`, `DirectNoticeSender`); all 11 `EDIFY_GO_SAVES` work with `EDIFY_EXISTING_APP_URL=""`; `/my-plan` renders natively for real CCEOs/PLs; `/help/context` & acting-capacity reads ported; M7–M12 field/SSA/IA/partner/finance/workforce/export writers proven with idempotent callbacks & RBAC; 41/41 APScheduler jobs registered in `cmd/scheduler` under `PGLocker`; Next.js staging build passes without `EDIFY_EXISTING_WEB_URL` (34/34 routes, 338/338 Vitest); Expo mobile 276/276 Jest; Python analytics 21/21 pytest; backup/restore 11s. Candidate spec ready at `.do/uganda-go-staging.yaml`. |
| **Uganda authorized for production cutover** | **BLOCKED (Awaits Live Staging + Owner Sign-Off)** | 2026-11-21 | Awaits deploying `.do/uganda-go-staging.yaml` to live staging, 500-user load/EAS verification, finance close sign-off, and explicit release-owner approval. |
| **Django retired in production** | **BLOCKED** | 2026-11-21 | Awaits authorized production cutover and post-cutover observation window. |
| **Kenya, Rwanda, Ethiopia ready for launch** | **BLOCKED** | 2026-11-21 | Synthetic `KE` isolation verified in Go; per-country data import, config, and workflow acceptance not yet executed. |
