# Database Reliability, Transactions, Idempotency & Recovery Report

**Audit Date:** 2026-11-22  
**Database Verified:** Isolated non-production `edify_gorn_test` (`127.0.0.1:5432`, PostgreSQL 16.15).  
**Production Database Impact:** **ZERO.**

---

## 1. Transactional & Safety Architecture Verified

| Safety Control | Implementation | Verification Evidence | Status |
|---|---|---|---|
| **Default Read-Only Sessions** | `cmd/gateway/main.go`: `default_transaction_read_only = "on"` on every pooled connection; writes MUST explicitly open `pgx.TxOptions{AccessMode: pgx.ReadWrite}` via `withRW` | Verified in source & live gateway startup | **Pass** |
| **Production-Protection Guard** | `internal/dbguard`: Verifies DSN host, database identity, non-superuser role (`edify_gateway`), and zero writable protected tables before accepting traffic | Observed in live gateway JSON logs (`database approved by the production-protection guard`) | **Pass** |
| **Least-Privilege DB Grants** | `edify_gateway` role enforced column/table read boundaries (caught `leadership_decisionnote` and `daily_debrief.created_at` during live export testing, ensuring exports only use approved views/tables like `audit_log`) | Verified live against PostgreSQL | **Pass** |
| **Atomic SHA-256 Audit Chain** | `audit.Append` executes inside the exact same PostgreSQL `ReadWrite` transaction as operational mutations (`financeops`, `workforceops`); rollback rolls back both mutation and audit entry | Verified in `financeops/service.go` & `workforceops/service.go` | **Pass** |
| **Financial Disbursement Idempotency** | `financeops.TransitionWeeklyRequest` requires non-empty `reference` idempotency key on `disburse` and returns `applied: false` without double-disbursing on retry | Verified in `financeops/service.go` & `financeops/service_test.go` | **Pass** |
| **Exact Integer Monetary Arithmetic** | `financeops.ReconcileVariance(disbursed, accounted, returned int64)` operates exclusively in integer UGX minor units; negative amounts refused | Verified in `TestReconcileVarianceExactIntegerUGX` & SQL audit (`UGX 0` variance on 280 advances) | **Pass** |
| **Outbox Delivery Durability** | School Loans (`school_loans.notification`, `loans.Worker`) and Cluster Actions (`cluster_leadership.cluster_action_notice`) persist delivery tasks inside the originating transaction | Verified in `internal/loans/` & `internal/integration/step4_scheduler_and_ops_test.go` | **Pass** |
| **SSE Reconnect Recovery** | `realtime.Broker` 512-event ring buffer replays missed events strictly after `Last-Event-ID` upon client reconnect | Verified in `TestBrokerLastEventIDReplay` | **Pass** |

---

## 2. Recovery Scenarios Pending Staging Infrastructure

- Controlled chaos/failover testing (PostgreSQL primary restart, Redis disconnect failover under load, mid-upload network drop against live S3/Spaces) is recommended on staging prior to production cutover. Note: `internal/cache` already implements graceful fallback to in-memory limiter if Redis is unavailable at startup.
