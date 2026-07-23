# Product Verification Evidence — 2026-07-23

Objective evidence captured against the complete-verification mandate. Baseline
commit: `38cada10` (main), working tree clean.

## Baseline gates (§4) — all GREEN

| Gate | Command | Result |
|---|---|---|
| System check | `manage.py check` | 0 issues |
| Migration drift | `makemigrations --check --dry-run` | No changes detected |
| Unapplied migrations | `migrate --plan` | None |
| Lint | `ruff check .` | All checks passed |
| Format | `ruff format --check .` | 847 files formatted, 0 diffs |
| **Full test suite** | `manage.py test --parallel 4` | **2038 tests, 0 failures, 0 errors (529s)** |

Three regressions from the new performance surfaces were found and fixed
(permission mapping, legacy primary utilities, inert buttons); the suite is
green after those fixes, confirmed by a second full run.

## Data & workflow integrity scans — all CLEAN

| Check | Mandate | Result |
|---|---|---|
| Duplicate Salesforce activity IDs | §29 | 0 |
| Duplicate School Salesforce account IDs | §29 | 0 |
| Duplicate Project–School assignments | §21 | 0 |
| Duplicate target credits (user+area+source+fy) | §31 | 0 (323 ledger rows) |
| Disbursement state consistency | §28 | 0 inconsistent |
| Dead sidebar routes | §11 | 0 (76/76 resolve) |
| Mock/fabricated production data | §14 | 0 (only a unique-id generator) |
| Sidebar page_keys without a permission | §8 | 0 |
| Orphaned school references (CorePlan / assignments) | §41 | 0 |

## UI/UX polish (§35) — 4 phases complete, verified light/dark/mobile

Role dashboards; operating pages (My Plan, Planning, Schools, Activities,
Evidence); finance (money formatting, refresh button, dead search chrome,
Fund Allocation reshaped to the country cost-plan); everything-else
(HR/PD/analytics/messages/calendar/system-health/leave). 29 design-system
guards pass.

## Honest boundary — gates that need infrastructure this environment lacks

These mandate gates cannot be truthfully closed from a headless dev session
and are NOT claimed as green:

- **§7 95% planning-time reduction** — requires timed tasks by representative
  real users against a manual baseline. Not measurable here.
- **§44 backup restore + rollback drills** — require production/staging DB infra.
- **Playwright / axe / visual-regression tool chains** (§36/§43/§54) — not
  installed in this environment.
- **§38 security penetration testing** (JWT refresh reuse, timing) — needs
  security tooling and a running deployment.
- **§42/§43 full 18-scenario E2E + 18-operation concurrency matrix with real
  role accounts** — partially covered by the 2038-test suite (which includes
  workflow, scope, and concurrency tests) but not the complete real-account matrix.

The code-controllable surface is green and proven. The remaining 100/100
certification gates are infrastructure- and real-user-dependent.
