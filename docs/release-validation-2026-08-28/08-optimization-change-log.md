# Optimization change log

| ID | Area/files | Change | Before | After/test | Risk |
|---|---|---|---|---|---|
| OPT-001 | `apps/core_schools/champion_services.py` | Batch eligibility facts and bulk status updates | 23.538 s, >9,000 queries | 0.281 s, 5 queries; scale regression | Medium: complex eligibility equivalence |
| OPT-002 | closure/core-school/priority/account/admin templates and priority view | Server pagination | 10K–15K+ DOM on affected pages | Dedicated pages 1,335–2,555 DOM; pagination contracts | Low |
| OPT-003 | SSA form/view/URL/partial | HTMX school autocomplete | ~16,988-option datalist | 25-result cap; 176 ms page | Medium: scope correctness |
| OPT-004 | planning view/URL/partial | HTMX school autocomplete | Full school select | 25-result cap; 638 ms page | Medium: scope correctness |
| OPT-005 | budget/monthly-work-plan services, models, migrations, templates | Governed regional ceiling + operational allocation + reserve snapshots across all costs | Single-purpose/two-card ambiguity | Explicit 12,000/22,000 participant regression and envelope invariants | High: financial behavior, protected by focused/full suites |
| OPT-006 | navigation/page inventory/help services | Correct specialist visibility and help access | Unexpected exposure/403s | Permission/inventory tests and 14-role crawl | Medium |
| OPT-007 | seed command | Idempotent, scoped demo data; no global activity deletes | Non-idempotent and overly broad cleanup | Two identical successful runs | High if used incorrectly; environment stamp still guards production |
| OPT-008 | Playwright/package/CI | Cross-browser smoke, role crawl, freeze gates, CI service dependencies/artifacts | No suitable end-to-end release gate | 27 passed locally; workflow added | Low |

## Frontend build/inventory maintenance

Tailwind CSS was rebuilt after template changes. Card, KPI, page, and permission inventories were regenerated, and their checked-in/live consistency tests pass.

