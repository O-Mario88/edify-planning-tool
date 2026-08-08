# Final Platform Design Implementation Ledger — 2026-08-08

This is the live release ledger for the final Edify platform-wide design
implementation. It is paired with the exhaustive generated route/component
inventories:

- `docs/platform-page-inventory.json` — machine-readable route, role, template,
  state, permission, test and component evidence for every routed surface.
- `docs/platform-page-inventory.md` — human-readable catalogue of every routed
  surface, including routes that are not linked in the sidebar.
- `docs/MOBILE_UI_UX_PAGE_MATRIX_2026-08-08.md` — full-page mobile archetype and
  role matrix.

No page is Closed on the strength of this document alone. Closure requires the
generated inventory, automated gates, responsive browser evidence, accessibility
evidence and production verification to agree.

## Allowed status values

`Not Audited` · `Legacy Design Found` · `Shared Component Identified` ·
`Implementation In Progress` · `Desktop Complete` · `Tablet Complete` ·
`Mobile Complete` · `Accessibility Verified` · `Regression Tested` ·
`Production Deployed` · `Live Verified` · `Closed`

## Source-control baseline

| Field | Recorded value |
|---|---|
| Baseline branch | `origin/main` |
| Baseline commit | `cabd3c3bc6577e5a72e85d09e62bd417b838ef75` |
| Remote main | `cabd3c3bc6577e5a72e85d09e62bd417b838ef75` |
| Tree relationship | Release branch created from the recorded `origin/main` commit; pre-existing design work preserved |
| Release branch | `codex/platform-design-release-20260808` |
| Working tree | Substantial pre-existing design implementation preserved: modified and untracked files recorded by `git status --short` |
| Branch protection | Required: Django Lint & Test Suite, Security Scans, CodeQL Python, CodeQL JavaScript/TypeScript |
| Push policy | Pull request; no force push and no branch-protection bypass |

## Production baseline

| Field | Recorded value |
|---|---|
| Platform | DigitalOcean App Platform |
| App | `edify-planning-app` |
| Region | `blr` / BLR1 |
| Production URL | `https://edify-planning-app-gu9a6.ondigitalocean.app` |
| Active deployment | `01d07a02-2558-4521-a497-383e2440bf23` |
| Active source commit | `cabd3c3` from `main` |
| Deployment state | ACTIVE |
| Automatic deployment | Confirmed: pushes to GitHub `main` create App Platform deployments |

## Exhaustive inventory baseline

| Inventory dimension | Count | Status |
|---|---:|---|
| Routed product surfaces | 499 | Shared Component Identified |
| All registered routes | 901 | Shared Component Identified |
| API routes | 293 | Shared Component Identified |
| Full pages | 326 | Shared Component Identified |
| Partials and drawers | 157 | Shared Component Identified |
| Shared component templates | 316 | Shared Component Identified |
| Permission-gated surfaces | 489 | Regression Tested |
| Test-referenced surfaces | 463 | Regression Tested |
| Roles | 11 | Not Audited |

## Shared-system implementation ledger

| System | Shared implementation | Current design state | Required change / evidence | Desktop | Tablet | Mobile | Light | Dark | Loading / Empty / Error | Interaction | Accessibility | Tests | Status | Production verification |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Design tokens | `static/css/design-system.css`, `platform.css`, `components.css` | Existing consolidation in working tree | Audit approved colors, Inter, 12/8/16px geometry, statuses, motion and hardcoded exceptions | Pending | Pending | Pending | Pending | Pending | N/A | Pending | Pending | Existing contract tests | Not Audited | Pending |
| Authenticated shell | `templates/layouts/shell.html`, `templates/base.html` | Existing shared shell | Verify unique contextual search, Messages → Notifications order, responsive shell and theme parity | Pending | Pending | Pending | Pending | Pending | Error boundary pending audit | Pending | Pending | Existing shell tests | Not Audited | Pending |
| Page Header | `.edify-page-header` shared CSS and template contract | Tonal header migration in working tree | Verify every major full page and HTMX replacement | Pending | Pending | Pending | Pending | Pending | N/A | Pending | Pending | Page-header contract tests | Not Audited | Pending |
| KPI Strip | `templates/components/kpi_strip.html` | Shared independent strip present | Verify no legacy/segmented duplicates and metric identity | Pending | Pending | Pending | Pending | Pending | Pending | Pending | Pending | KPI inventory/contract tests | Not Audited | Pending |
| Filters | `.edify-filter-bar`, filter drawer patterns | Page-canvas migration in working tree | Verify max 3 primary fields, arrow spacing, URL/back-forward, pagination reset | Pending | Pending | Pending | Pending | Pending | Pending | Pending | Pending | Filter contract tests | Not Audited | Pending |
| Cards | `.card`, shared surface tokens | Borderless/elevated migration in working tree | Verify 12px radius, single meaningful surface and row alignment | Pending | Pending | Pending | Pending | Pending | Pending | Pending | Pending | Card inventory/contract tests | Not Audited | Pending |
| Tables | Shared table primitives and mobile record cards | Mixed shared/page markup | Verify enterprise wrapper/states and mobile operational-card transformation | Pending | Pending | Pending | Pending | Pending | Pending | Pending | Pending | Table and mobile-family tests | Not Audited | Pending |
| Buttons | `.btn` variants and async feedback runtime | Shared variants present | Verify one dominant action, pending/disabled/result and dead endpoints | Pending | Pending | Pending | Pending | Pending | Pending | Pending | Pending | Interaction tests | Not Audited | Pending |
| Tabs | Shared section/tab navigation and `micro-ux.js` | Underline/color design in working tree | Verify real datasets/counts, URL state, keyboard and active reveal | Pending | Pending | Pending | Pending | Pending | Pending | Pending | Pending | Tab contract tests | Not Audited | Pending |
| Statuses | Central status registry and pill tokens | Existing registry requires audit | Verify canonical labels/colors/icons/sort order across domains | Pending | Pending | Pending | Pending | Pending | N/A | Pending | Pending | Status contract tests | Not Audited | Pending |
| Charts and maps | Page-scoped analytics assets | New analytics design; map intentionally retains approved original visual | Verify decision purpose, summaries, states, lazy loading and responsive layout | Pending | Pending | Pending | Pending | Pending | Pending | Pending | Pending | Analytics tests | Not Audited | Pending |
| Drawers and modals | Shared drawer/dialog templates | Shared pattern present | Verify focus trap/return, full-screen mobile, names and error recovery | Pending | Pending | Pending | Pending | Pending | Pending | Pending | Pending | Dialog contract tests | Not Audited | Pending |
| Mobile application shell | `mobile-shell.css`, `mobile-patterns.css`, `mobile-ux.js` | Five-phase migration in working tree | Verify role navigation, safe areas, 360–430px and no document overflow | N/A | Pending | Pending | Pending | Pending | Pending | Pending | Pending | Mobile foundation tests | Not Audited | Pending |
| PWA | Manifest, service worker and install assets | Existing implementation | Verify scope, icons, cache safety, upgrade and logout isolation | Pending | Pending | Pending | Pending | Pending | Offline/error pending | Pending | Pending | PWA tests | Not Audited | Pending |

## Page-family and role ledger

The exact route, role, template, partial, shared component, permission and test
records for each row are resolved in `docs/platform-page-inventory.json`. This
table owns implementation and release status across those exhaustive records.

| Page family | Representative routes | Roles | Templates / partials | Required design focus | Desktop | Tablet | Mobile | Light | Dark | Loading | Empty | Error | Interaction | Accessibility | Tests | Status | Production verification |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Role dashboards | `/dashboard`, `/dashboard/*` | All authenticated roles | `pages/dashboards/*`, `partials/dashboards/*` | Header, task hierarchy, KPI strip, role scope, responsive home | Pending | Pending | Pending | Pending | Pending | Pending | Pending | Pending | Pending | Pending | Existing role tests | Not Audited | Pending |
| School Directory and profiles | `/schools`, `/schools/<id>` | Admin, CCEO, PL, CD, RVP, IA, Accountant, PC | `pages/schools/*`, `partials/schools/*` | Filters, dense rows, checkbox order, row/name interactions, lifecycle | Pending | Pending | Pending | Pending | Pending | Pending | Pending | Pending | Pending | Pending | Existing + new directory tests | Not Audited | Pending |
| Clusters and cluster profiles | `/clusters`, `/clusters/<id>` | Admin, CCEO, PL, CD, RVP, IA, PC | `pages/clusters/*`, `partials/clusters/*` | Eligibility, ownership, dense rows and actions | Pending | Pending | Pending | Pending | Pending | Pending | Pending | Pending | Pending | Pending | Existing cluster tests | Not Audited | Pending |
| Planning and My Plan | `/planning`, `/my-plan`, `/work-plan/*` | CCEO, PL, PC, leadership | Planning/My Plan pages and partials | Canonical filters, cards, activities, costs, state handoff | Pending | Pending | Pending | Pending | Pending | Pending | Pending | Pending | Pending | Pending | Existing planning tests | Not Audited | Pending |
| Team/Country/Partner Oversight | `/team-planning-oversight`, `/country-planning-oversight`, `/partner-oversight` | PL, CD, RVP, IA, Accountant, Admin | `pages/oversight/*`, `partials/oversight/*` | PL/CCEO/partner grouping, periods, read-only authority, totals | Pending | Pending | Pending | Pending | Pending | Pending | Pending | Pending | Pending | Pending | 140 focused tests | Regression Tested | Pending |
| Analytics and reports | `/analytics`, `/analytics/*`, `/reports` | Authorized roles | `pages/analytics/*`, `partials/analytics/*` | Decision hierarchy, original map visual, charts, tables and filters | Pending | Pending | Pending | Pending | Pending | Pending | Pending | Pending | Pending | Pending | Analytics suites | Regression Tested | Pending |
| Calendar and scheduling | `/calendar`, scheduling drawers | Staff roles | `pages/calendar/*`, `partials/calendar/*` | Mobile calendar, event tabs, schedule feedback and conflict clarity | Pending | Pending | Pending | Pending | Pending | Pending | Pending | Pending | Pending | Pending | Calendar tests | Not Audited | Pending |
| IA verification | `/ia/*`, `/ssa/*`, evidence review routes | IA, Admin, leadership read scopes | `pages/ia/*`, `pages/ssa/*`, IA partials | Command center hierarchy, queue, review, evidence, data quality | Pending | Pending | Pending | Pending | Pending | Pending | Pending | Pending | Pending | Pending | IA and SSA suites | Not Audited | Pending |
| Finance and budget | `/accounts/*`, `/fund-requests/*`, `/country-budget`, `/work-plan/*` | Accountant, PL, CD, RVP, Admin | Accounts/finance pages and partials | Money hierarchy, approvals, audit, tables and safe actions | Pending | Pending | Pending | Pending | Pending | Pending | Pending | Pending | Pending | Pending | Finance suites | Not Audited | Pending |
| Partner workspaces | `/partner/*`, `/partners` | Partner, PL, Admin, leadership | Partner pages and partials | Today-first mobile flow, scheduling, evidence, partner management | Pending | Pending | Pending | Pending | Pending | Pending | Pending | Pending | Pending | Pending | Partner suites | Not Audited | Pending |
| Targets and performance | `/targets`, `/hr/performance-*`, priority routes | Staff, PL, HR, leadership | Targets/HR pages and partials | Hierarchy, progress, conversations, role clarity | Pending | Pending | Pending | Pending | Pending | Pending | Pending | Pending | Pending | Pending | Targets/HR suites | Not Audited | Pending |
| People, leave and PD | `/staff`, `/leave/*`, `/professional-development` | HR, staff, leadership | Staff/leave/PD pages and partials | Directory density, availability, approvals and mobile actions | Pending | Pending | Pending | Pending | Pending | Pending | Pending | Pending | Pending | Pending | HR/leave/PD tests | Not Audited | Pending |
| Messages, notifications and to-dos | `/messages`, `/notifications`, `/todos`, `/actions/*` | All authenticated roles | Messaging/action pages and partials | Badge parity, unique search, mobile full-screen flow, action feedback | Pending | Pending | Pending | Pending | Pending | Pending | Pending | Pending | Pending | Pending | Messaging/action suites | Not Audited | Pending |
| Documents and evidence | `/documents/*`, `/evidence/*` | Permission-scoped roles | Documents/evidence pages and partials | Upload, viewer, review, security and loading/error states | Pending | Pending | Pending | Pending | Pending | Pending | Pending | Pending | Pending | Pending | Document/evidence suites | Not Audited | Pending |
| Closure and lifecycle | `/activities/closure/*`, closed-school routes | Scoped staff and leadership | Closure pages/partials | Controlled lifecycle, impact disclosure and historical access | Pending | Pending | Pending | Pending | Pending | Pending | Pending | Pending | Pending | Pending | Closure suites | Not Audited | Pending |
| Admin and system operations | `/admin-panel/*`, `/admin-ops/*`, `/system-health`, audit routes | Admin | Admin/system/audit pages | Dense operational clarity, permissions, destructive-action safety | Pending | Pending | Pending | Pending | Pending | Pending | Pending | Pending | Pending | Pending | Admin/system tests | Not Audited | Pending |
| Settings and Help | `/settings/*`, `/help/*` | Role-scoped | Settings/help layouts and pages | Forms, search locality, documentation hierarchy and mobile shell | Pending | Pending | Pending | Pending | Pending | Pending | Pending | Pending | Pending | Pending | Settings/help tests | Not Audited | Pending |

## Required test matrix

| Gate | Local status | CI status | Production status |
|---|---|---|---|
| Django system checks and deploy checks | Passed: 0 issues | Pending | Pending |
| Migration drift and migration plan | Passed: no drift, no planned migration | Pending | Pending |
| Ruff lint and formatting | Passed: 1,272 files formatted | Pending | N/A |
| Django/pytest suites | Django passed: 4,700 tests; pytest coverage measured 88%. Three xdist-only serialization/argv artifacts reran serially: 3 passed, 5 subtests passed | Pending | N/A |
| Permission and scope suites | Passed within full Django suite | Pending | Live smoke pending |
| JavaScript build/syntax | No separate JS test runner configured; production CSS build reproducible | Pending | Asset load pending |
| Static collection and asset manifest | Passed: 369 copied, 1,719 post-processed locally | Pending | Hash pending |
| Security and dependency scans | Passed: Bandit, pip-audit, npm audit, zizmor, Trivy High/Critical=0 | Pending | Headers/health pending |
| Accessibility | Contract suites passed; browser semantic review passed on representative families | Pending | Pending |
| Responsive/visual regression | 18 page families × 8 widths = 144 checks; 0 overflow/font/header/radius/search failures | Pending | Pending |
| PWA/manifest/service worker | Manifest, required icons, root scope and uncacheable service worker passed locally | Pending | Pending |

## Rollback triggers

- Any required GitHub check fails.
- Any migration fails or introduces unexpected destructive operations.
- Production deployment does not build the exact merged `main` commit.
- Login, navigation, primary role workflow, static assets or health checks fail.
- Production error rate, latency or instance health materially regresses.
- Cross-role scope, evidence, finance, HR or authenticated cache isolation fails.
- A critical/high accessibility or responsive issue is introduced.

## Current release status

`Regression Tested` — local release gates are green. CI, merge, deployment and
production verification remain open and must not be inferred from this status.
