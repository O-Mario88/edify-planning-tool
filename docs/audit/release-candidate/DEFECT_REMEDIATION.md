# Master Defect Remediation Register (All Audits Combined)

**Audit Date:** 2026-11-22  
**Total Code Defects Discovered:** **17** (`DEF-001`–`DEF-006`, `ECO-001`–`ECO-004`, `RC-001`–`RC-007`)  
**Resolved & Regression-Tested:** **17 / 17 (0 unresolved P0/P1 code defects)**

---

| ID | Severity | Original Behavior & Root Cause | Fix Implemented | Verified Outcome |
|---|---|---|---|---|
| `DEF-001` | P1 | Core School Oversight missed sub-regions when `school.sub_region_id IS NULL` | `COALESCE(s.sub_region_id, d.sub_region_id)` in `coreoversight/read.go` | `700/700` schools resolve sub-region (`0` unresolvable) |
| `DEF-002` | P0 | `financeops` allowed non-staff weekly submissions & unvalidated advance actions | Staff-only RBAC + strict action allowlist + `financeops/service_test.go` | `go test -race` PASS |
| `DEF-003` | P0 | `workforceops` allowed non-staff PTO & MFI escalations | Staff-only RBAC + MFI block + `workforceops/service_test.go` | `go test -race` PASS |
| `DEF-004` | P1 | Python analytics accepted non-finite scores & dropped zero-score cohorts | `math.isfinite`/`[0,10]` checks, symmetric weighting, clamping + `test_reconciliation.py` | `30/30` pytest PASS, `0.00` variance vs SQL |
| `DEF-005` | P1 | Country Map omitted confirmed FY SSA averages | Joined confirmed FY `ssa_record` in `countrymap_data.go` | FY27 `5.91` (`44%`), FY26 `4.96` (`100%`) match SQL |
| `DEF-006` | P2 | Dead `/clusters/oversight/` link in `countryMapData.ts` | Fixed to `/cluster-oversight/` | Verified 200 OK |
| `ECO-001` | P1 | Only 4 CSV export kinds existed; missing buttons & XLSX/PDF formats | Expanded to 11 kinds + pure-Go OOXML `.xlsx` & PDF 1.4 + restored buttons across 8 views | 100-export storm `0` errors, `P95 106.6 ms` |
| `ECO-002` | P1 | No real-time operational SSE synchronization | Built scoped `realtime.Broker` + Redis Pub/Sub bridge + `<RealtimeBridge />` + wired all 4 write services | Live commit-to-client **`37.84 ms`**; multi-replica `-race` PASS |
| `ECO-003` | P1 | DB pool default `8` saturated above 100 users | Raised pool default `8→32` (`cap 200`) + map 30s cache + dashboard batched SQL & 15s cache | 1,000-user wave `0` errors, `P95 491.8 ms`; 1,500 burst `0` errors |
| `ECO-004` | P1 | `httpmw` blocked SSE `Flush()` & 30s `WriteTimeout` dropped streams | Added `Flush()` to `statusRecorder` + `http.NewResponseController` deadline clear | `250/250` SSE streams connected in `281 ms` |
| `RC-001` | P1 | Bulk Upload SSA template used non-canonical intervention names instead of PostgreSQL `ssa_score.intervention` codes | Aligned `uploads/service.go` & `SsaUploadCenterView.tsx` to exact 8 canonical PostgreSQL codes | All 8 canonical headers verified live |
| `RC-002` | P1 | `screens/native_drawers.go` queried non-existent table `training_course` (returned 0 trainings) | Fixed to query authoritative `activity_catalogue_item WHERE status = 'active'` | **65 active catalogue trainings** loaded live |
| `RC-003` | P1 | Data race in `realtime/redis_pubsub_test.go` mock RESP2 server writer | Added per-connection `sync.Mutex` around `bufio.Writer` | **15/15 core packages pass `go test -race`** |
| `RC-004` | P1 | Missing explainable SSA Decision Intelligence API & Map missing-coordinate visibility | Built `internal/ssadecision` (`GET /api/v1/schools/{id}/ssa-recommendations`, 10 controlled tests) + `with_coordinates_count`/`missing_coordinates_count` on Map API | Live verified (`Nama Primary School` 8/8 interventions + unassessed school + `683`/`17` map split) |
| `RC-005` | P0 | `uploads/service.go` used `pool.Begin(ctx)` which inherited gateway read-only session default (`SQLSTATE 25006`) | Switched to `pool.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite})` + routed writes via `gateway_field_ops.enter_ssa` & `internal/activities` for `dbguard` compliance | Live SSA CSV upload committed (`verification_status='pending'`) + `dbguard` PASS across 159 packages |
| `RC-006` | P1 | `gateway_field_ops.enter_ssa` conflicted on `uniq_ssa_record_intervention` (`SQLSTATE 23505`) when upserting over Django CUID `ssa_score` rows | Fixed `ON CONFLICT (ssa_record_id, intervention) DO UPDATE` in `field_ops_roles.sql` + FY duplicate check in `uploads/service.go` | Live duplicate FY upload cleanly skipped without DB error |
| `RC-007` | P2 | 2 moderate transitive `@typescript-eslint` advisories in `platform/web` | Executed `npm audit fix` and verified `55/55` Vitest + `43/43` Next.js build | `npm audit` = **0 vulnerabilities** |
