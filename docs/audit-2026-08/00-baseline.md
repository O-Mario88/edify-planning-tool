# End-to-End Audit — Baseline (frozen 2026-08-16)

## Audited version

| Item | Value |
| --- | --- |
| Repository | github.com/O-Mario88/edify-planning-tool |
| Branch | main |
| Commit | 5ef10c98 (functional baseline 6c2c263d + formatter/CVE repair) |
| Migrations on disk | 249 files · 282 applied rows in django_migrations |
| Python / Django | 3.13.12 / 5.2.16 |
| PostgreSQL | 16.13 (Homebrew, aarch64) |
| Environment | Local development (env-stamped `local`); production is DigitalOcean fra, NOT touched by this audit |
| Cache | Redis configured; local fallback LocMemCache when redis is down |
| Integration flags | SALESFORCE_SYNC_ENABLED=off, NETSUITE_SYNC_ENABLED=off (default) |
| Test suite at baseline | 5,195 tests — OK (2 skipped, 1 expected failure), local CI-parity run 2026-08-16 |
| Audit start | 2026-08-16 |

## Documented figures vs. live code (mandate §1)

| Claim (PLATFORM_GUIDE.md) | Live at baseline | Verdict |
| --- | --- | --- |
| 509 routed surfaces | **532** (build_page_inventory) | STALE — guide predates Business Transformation |
| 914 routes | **952** (URL resolver walk) | STALE |
| 11 roles | **14** (EdifyRole: +BusinessTransformationOfficer, MfiPartnerAdmin, MfiLoanOfficer) | STALE |
| 70 permission keys | **85** (Permission enum) | STALE |
| >5,000 automated tests | 5,195 | Consistent |
| Registered metrics | 81 (METRIC_REGISTRY) | Not claimed in guide; recorded here |

→ Finding AUD-001 (Medium, documentation): PLATFORM_GUIDE.md must be regenerated before
acceptance gate 20 ("platform documentation matches the audited system") can pass.

## Findings already established during baseline freeze

- **AUD-002 (High, CI controls):** CI failed at `ruff format --check` for the last 8
  pushes (~2m40s each), so the automated suite **has not run on GitHub for weeks** —
  the same silent-red mode the 2026-07-25 pipeline audit fixed once before. Repaired
  in 5ef10c98 (65 files reformatted, gates re-run locally). Residual risk: no ratchet
  prevents recurrence; recommend a pre-push hook or making the formatter check a
  separate always-first job with an alert.
- **AUD-003 (High, dependency security):** Scheduled Trivy scan failing on runtime
  image setuptools 70.3.0 — CVE-2025-47273 (path traversal, HIGH), fixed ≥78.1.1.
  Patched in 5ef10c98 (in-place upgrade in the runtime stage). Verification: next
  scheduled scan run must go green.
- CodeQL on the baseline commit: **pass**.

## Source-of-truth hierarchy used (mandate §4.2)

1. docs/PLATFORM_GUIDE.md (2026-08-15 — known stale on BT, see AUD-001)
2. docs/OPERATIONS_ROADMAP.md + docs/STAFF_TIME_STANDARD.md (adopted 2026-08-15)
3. Generated inventories (page/KPI/card — CI-enforced to match live code)
4. apps/core/rbac.py role/permission matrix (canonical, seeded to RolePermission)
5. Live code + migrations at 5ef10c98
6. The 2026-08-16 audit mandate (this document's parent instruction), including its
   Business Transformation requirements (§22), treated as approved requirements.

## Method constraints (honesty register)

Performed here: static review, dynamic service-level probes on an isolated DB clone,
independent SQL reconciliation, scale measurement on generated data, instrumented
browser walkthroughs, security probes via test client, CI/scan verification.

NOT performable in this environment (require staging/humans/devices — carried as
open audit obligations): observed real-user time studies; real-device offline/PWA
field trials; live Salesforce/NetSuite/MFI credentialed integration tests (flags
off, transports unimplemented by design — B2); production restore drill on the
DigitalOcean side; multi-instance load soak.
