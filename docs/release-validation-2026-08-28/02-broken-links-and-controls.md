# Broken link and control report

## Findings corrected

| ID | Finding | Severity | Resolution | Regression evidence |
|---|---|---|---|---|
| CTRL-001 | `/mfi-portal` was advertised to Admin even though the service correctly denied Admin. | Medium | Marked the page role-exclusive and corrected page-inventory role expansion. | Page inventory and permission matrix tests; authenticated role crawl. |
| CTRL-002 | Business Transformation and both MFI roles received 403 on canonical help onboarding/context pages. | Medium | Added the specialist roles to canonical help access and reconciled existing canonical content without overwriting editor content. | `apps.help_center.tests`; specialist browser role crawl. |
| CTRL-003 | `/ssa/manual/` embedded the complete school catalogue in a datalist. | High performance | Replaced it with scoped HTMX search, minimum two characters, maximum 25 results. | `apps.frontend.test_manual_entry`; freeze browser gate. |
| CTRL-004 | `/planning/schedule` embedded the full school catalogue in a select. | High performance | Added scoped HTMX school lookup and a bounded result partial. | `apps.frontend.test_schedule_school_lookup`; freeze browser gate. |
| CTRL-005 | Several large operational/admin pages rendered unbounded row sets. | High performance | Added server pagination to closure, core-school health, strategic priorities, blocked accounts, and page-access matrix surfaces. | Pagination contract tests and authenticated browser crawl. |

## Current automated result

- Broken internal links observed by the final argument-free browser crawl: 0.
- Unexpected 4xx/5xx responses in that crawl: 0.
- Visible enabled controls without an accessible name: 0 under the crawler’s accessible-name calculation.
- Unexpected console errors/page errors: 0.
- Horizontal-overflow failures in the final crawl: 0.

## Important limitation

No list of “all controls passed” is asserted. Controls were inventoried and their containing pages were rendered; most mutation controls were not clicked through every workflow state. Therefore dead controls that appear only in uncreated states or require parameterized records remain possible and are an explicit release blocker.

