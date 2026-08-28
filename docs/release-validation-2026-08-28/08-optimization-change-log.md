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
| OPT-009 | `consistency.css`, `micro-ux.js`, workspace templates | Replace global `:has()` invalidation with explicit HTMX-aware relationship markers and split critical mutation regions | 92 ms `/analytics`, 43.6 ms `/schools`, 41.4 ms `/system-health` reported | Warm medians 1.37 ms, 1.43 ms, and 12.87 ms; all below one 16 ms frame | Medium: shared visual bridge, protected by source and browser gates |
| OPT-010 | school tabs/view and shared JS | Delegate tab behavior once and return only the school table for tab updates | 264→478 listeners and 15,366→21,344 nodes reported over 30 interactions | 277 listeners and 3,588 connected nodes remain unchanged from cycle 10 through cycle 50 | Low |
| OPT-011 | authored Tailwind classes and design-system lint | Replace unsupported numeric palette shades and enforce compiled/custom shade validity | 9 dead utility families, 35 verified template occurrences reported | No unsupported authored numeric colour utility remains; lint and CSS rebuild pass | Low |

## Frontend build/inventory maintenance

Tailwind CSS was rebuilt after template changes. Card, KPI, page, and permission inventories were regenerated, and their checked-in/live consistency tests pass.
