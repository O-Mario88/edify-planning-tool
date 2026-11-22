# Architecture Verification — Final Release Candidate

**Audit Date:** 2026-11-22  
**Branch / Worktree:** `feature/edify-go-rn-migration` (`qa/c3-20261122`)  
**Production Database Contact:** ZERO (`127.0.0.1:5432/edify_gorn_test` isolated local database only, protected by `internal/dbguard`)

---

## 1. Verified Runtime Architecture

| Layer | Technology | Verified Responsibility | Ownership Status |
|---|---|---|---|
| **Operational Backend** | Go (`platform/backend`, **159 internal packages**) | Auth/MFA/sessions, server-side RBAC, country/team scoping, schools, clusters, planning, activities, visits, trainings, SSA operations, partner handovers, weekly advances, approvals, disbursements, loans, HR/PTO, escalations, decision log, bulk uploads, CSV/XLSX/PDF exports, scoped SSE + Redis Pub/Sub | **100% Go-Owned** (runs with `EDIFY_EXISTING_APP_URL=""` & `EDIFY_STRICT_READS=true`) |
| **Analytical Layer** | Python gRPC Worker (`platform/workers/analytics`) | Stateless descriptive/diagnostic/predictive analytics, SSA trends, coverage gaps, route efficiency, k-anonymized global reports | **100% Analytical / Non-Authoritative** (zero DB credentials; receives only Go-authorized payloads) |
| **Authoritative Data Store** | PostgreSQL 16.15 (`pg_trgm`) | Single authoritative operational ledger with `SECURITY DEFINER` least-privilege gateway functions and `dbguard` static/runtime write protection | **Verified Authoritative** |
| **Web Frontend** | Next.js 16 / React / TypeScript (`platform/web`) | **33 App Router pages** + **15 route handlers** (43 build routes), zero Django runtime dependency in standalone mode | **Verified Green (`55/55` Vitest files, `359` tests, `0` npm vulnerabilities)** |
| **Mobile Frontend** | React Native / Expo (`platform/mobile`) | Fieldwork, offline capture, Cluster Leader portal, Calendar, Smart Routes | **Verified Green (`35/35` Jest suites, `277` tests, `0` Django refs)** |
| **Caching & Multi-Replica Sync** | Pure-Go RESP2 Redis client (`internal/cache`, `internal/realtime`) | Distributed rate limiting, key-value cache, and multi-replica SSE Pub/Sub fan-out (`edify:realtime:events`) with in-memory fallback | **Verified (`TestMultiReplicaRedisPubSubFanoutAndIsolation` `-race` PASS)** |

## 2. Static & Runtime Safety Enforcement

* **`internal/dbguard` (`TestGatewaySourcesContainNoSchemaChanges`):** Enforced across all **159 Go packages** — prevents unauthorized DDL/DML against legacy Django-owned tables and ensures writes pass only through least-privilege `SECURITY DEFINER` SQL functions or allowlisted Go write packages (`internal/activities`, `internal/audit`, `internal/signin`, etc.).
* **Production Refusal Guard:** `config.Load` rejects `EDIFY_ENV=production` without explicit release approval (`ErrProductionNotApproved`) and rejects any production database host/URL in local or staging builds.
* **No Competing Operational Backend:** In pure-Go mode (`EDIFY_EXISTING_APP_URL=""`), all 12 `GoSaves` writers (`AllGoSaves()`), direct notifications, native pricing, exports, uploads, and SSA decision intelligence execute exclusively inside Go with zero Django HTTP calls.
