# KPI simplification audit — 2026-08-20

This report implements the platform doctrine **Simple → Healthy → Focused** for
KPI tiles, metric strips and summary bands. The machine-readable, line-level
decision matrix is `docs/platform-kpi-inventory.json`; this document explains
the result and the remaining data-governance work without pretending that a
presentation migration fixes an unregistered metric definition.

## 1. Measured surface

| Surface | Live count | Evidence |
| --- | ---: | --- |
| Canonical registered metrics | 417 | `registered_metrics` |
| Hand-built KPI payloads still requiring registry review | **0** | `sites[kind=kpi-tile]` |
| Workflow breakdown/option rows (not headline KPIs) | 170 | `sites[kind=breakdown-row]` |
| Rendered KPI summaries | 65 | `template_sites` |
| Shared-component summaries | 65 | `source_pattern=shared-component` |
| Legacy adapter summaries | **0** | `source_pattern=legacy-adapter` |
| Registered Python payload groups | 38 | `payload_groups` |
| Metric items built by those groups | 219 | `source_items_in_registered_payloads` |
| Payload groups starting above six items | 14 | `payload_groups_over_six` |
| Payload groups repeating a decision category | 30 | `payload_groups_with_repeated_categories` |
| Duplicate hand-built label families | **0** | `duplicated_labels` |
| Unclassified rendered summaries | **0** | inventory summary |

Every detected registered list payload and rendered surface has a stable audit ID,
source file and line, recommendation, reason, priority and implementation
status. Every rendered summary also records its route, roles where the page
registry declares them, page purpose, primary action, previous presentation,
new prominent-KPI limit, mobile result and accessibility result.

## 2. Decision matrix result

The 417 canonical metrics classify as follows:

| Class | Count | Default decision |
| --- | ---: | --- |
| Primary decision KPI | 129 | Retain when it changes the next decision or action |
| Outcome KPI | 22 | Retain on dashboards/analytics; contextual elsewhere |
| Context KPI | 266 | Convert to a connected context summary |

The rendered hierarchy is now:

| Presentation | Surfaces | Rule |
| --- | ---: | --- |
| Legacy compact context summary | **0** | Removed; it bypassed the approved tile visual |
| Executive headline tray | 64 | Maximum six distinct values in product-authored order |
| Supporting analytics group | 1 | Secondary to the analytical question |

Executive payloads are consolidated before template iteration. Repeated metric
identities are removed and the remaining values retain the page's explicitly
authored narrative order. Category remains audit metadata rather than a hard
deletion rule because two scale, finance or progress measures may answer
different business questions. The resulting payload is capped at six (two
only when a surface explicitly requests compact density). Surplus values are
not hidden with CSS or moved into a drawer, carousel or disclosure. They remain
valid registry definitions for detailed analytical homes.

## 3. Page simplification result

The inventory covers 42 operational surfaces, 8 planning surfaces, 2 workflow
detail surfaces and 13 dashboard/analytics surfaces.

- Operational, planning and workflow surfaces use the same executive tray as
  dashboards, capped at six distinct decision-relevant values.
- Assigned-school and assigned-activity partner pages contain no KPI strip or
  legacy KPI grid; search, filters, counts and records remain the workflow.
- My Plan, planning, fund requests, fund approvals, disbursements, oversight,
  HR workspaces, partner oversight, school lists, clusters, team targets and
  document workflows now use the approved executive tile tray rather than a
  compact alternate presentation.
- True dashboards and analytics retain explicitly curated headline groups,
  capped at six metrics with no overflow row or hidden KPI drawer.
- All seventeen legacy adapter surfaces now use the shared component. Period
  selectors and target-progression controls were reclassified as navigation
  and timeline UI instead of being styled as KPIs. The Special Projects role
  dashboard moved from bespoke cards to one portfolio headline, while school
  and partner counts remain in their named detail tables.

For the complete page-by-page result, use `template_sites` in the generated
inventory. It is the authoritative page simplification report and includes the
exact route and source line for each decision.

## 4. Duplicate metric reconciliation

The 13 duplicate hand-built label families have been reconciled. Metrics with
different formulas or scopes now have different stable registry keys and
scope-qualified canonical labels; the legacy service label remains available
only as a temporary Python contract while callers migrate from label lookup to
`metric_key`. Shared KPI components display the canonical label.

For example, `Planned This Week` now resolves separately to the role command
centre and special-project personal-plan definitions, while the registry names
their service, formula expression, period and scope. No source dict is treated
as canonical merely because it contains a hand-stamped key.

## 5. Role information map

| Role | Headline information | Context or queue information |
| --- | --- | --- |
| CCEO | Work requiring action now; material planning risk | Due work, waiting states and plan progress |
| Program Lead | Approvals, returns and team exceptions | Team capacity and planning context |
| Country Director | Country exceptions, verified outcomes and budget risk | District and team comparisons |
| Impact Assessment | Verification and data-quality exceptions | Queue counts, age and Salesforce state |
| Accountant | Payment/accountability blockers | Requested, approved, disbursed and accounted context |
| Partner | No generic KPI grid on assigned-work pages | Assignment counts, execution, evidence and payment status |
| Business Transformation | Repayment, verification and verified impact | Salesforce, MFI and compliance exceptions |
| RVP | Country comparisons and strategic risk | Supporting regional analysis |
| HR | People actions, coverage and wellbeing risk | Workforce and cycle context |

## 6. Shared components

### Retained

- `components/kpi_strip.html` for registered executive and analytical metrics.

### Added

- `professional_kpis`: a server-side template boundary that creates the final
  identity-deduplicated headline payload (maximum six).
- `kpi-strip--executive`: one rounded tray containing calm, individually
  bounded cards with an icon, trend, canonical label, value and helper.

### Consolidation status

All 65 rendered KPI surfaces use the shared component; 64 use its executive
presentation and one is an explicitly supporting analytics group. No template
contains the legacy `edify-kpi-strip`, the mobile-only metric clone, or a direct
consumer of `components/kpi_card.html`; a repository-wide regression test
keeps those three bypass paths closed. A fourth gate prohibits the removed
`variant="context"` path.

## 7. Performance and data integrity

- No browser-side business arithmetic was added.
- No metric query, service, period, scope or verification rule changed.
- Every presentation consumes the same server facts, so this pass adds no
  database queries and no chart instances.
- Additional headline values are absent from the rendered HTML. Services may
  still compute them for their detailed tables, exports or analytics; removing
  those proven-shared queries is a separate measured performance change.
- Empty registered values render an explicit data state; a measured zero stays
  a zero, and preformatted server values are not recalculated in the browser.

Query removal remains **0**. Canonicalization binds existing server results to
metadata without adding or duplicating database queries; query consolidation
requires a separate measured performance pass.

## 8. Validation

- Django system check: pass.
- Exhaustive rendered-markup crawl: 559 argument-free routes × 14 roles =
  7,826 role/route responses. Every HTML page and HTMX fragment rejects legacy
  KPI class families, non-executive strips, cards outside the approved tray,
  incomplete tile anatomy and trays above six cards.
- Full template gate: all 565 templates compile and none renders a competing
  KPI class family or direct KPI-card markup.
- Registry, generated-inventory, shared-strip, design-system, Reports, My
  Targets and Business Transformation gates pass.
- Authenticated role responses enforce the six-card platform maximum. The
  lending-specific hierarchy is tighter: four on the BT dashboard and two on
  the operational loan register.
- Ruff lint and formatting checks pass across the repository; the duplicate
  view definitions previously recorded in `extended_views.py` are removed.
- Inventory drift: generated manifest matches live source.
- Complete Django suite: 5,506 tests pass; 2 intentional skips and 1 expected
  failure are recorded by the runner.
- Responsive contract: executive trays become one column on phones; no
  horizontal KPI carousel is used.
- Rendered visual check: six equal cards in one desktop row; two responsive
  columns and no horizontal overflow at 390 px.
- Accessibility contract: native headings and lists, focus-visible links, text
  labels and non-colour state text; there is no overflow control to
  discover or operate.
- The exhaustive authenticated route/DOM crawl is the release gate for every
  role and page. Interactive screenshots remain supplementary visual evidence;
  no authentication shortcut or fake-data preview was introduced.

## 9. Canonical-metric completion

The original scan found 268 metric-shaped dicts. Non-KPI select options, chart
bands and workflow breakdown rows were correctly reclassified rather than
being falsely registered as KPIs. Every remaining runtime metric now has a
stable key, owner service, preserved formula expression, source-model
declaration, value type, period, date basis, role and filter scope, data-state
contract, canonical label, and either a drill-down or an explicit reason none
exists.

The live registry now contains 417 definitions. Its 38 registered payload
groups contribute 219 source items, while the hand-built KPI ratchet, duplicate
label-family ratchet, legacy-surface count and unclassified-surface count are
all zero.
