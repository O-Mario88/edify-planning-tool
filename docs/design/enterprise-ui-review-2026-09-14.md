# Platform UI improvement and independent review

Status: shared improvements implemented; independent acceptance is pending. This is not a certification of the whole product or a claim of WCAG conformance.

## Scope and evidence boundaries

The current platform inventory lists 803 routed surfaces, 15 roles, 255 full pages and 444 component templates. Some routes are aliases, fragments, redirects or nonvisual actions. The companion CSV preserves every inventory row so reviewers can explicitly mark a surface reviewed, not applicable, blocked or failed. Route placeholders require a role-appropriate test record. Source-contract results and automated quality scores in older inventories must not be treated as completed human reviews.

Changes here are in the shared shell and enhancement layer, so they apply wherever that layer is loaded. Record-card enhancement covers compatible `edify-record-table` tables (100 template occurrences after the oversight migration), including work plan details. It intentionally excludes merged headers, grouped/colspan rows, footers and comparison opt-outs; those retain their table structure. Existing bespoke school-directory cards remain intact. This does not mean every table or role workflow has been individually inspected.

## Improvements delivered

- Request-owned pending states survive unrelated HTMX swaps. Repeated terminal events cannot finish another request's progress. The actual submitter is used when available; original child nodes, widths and ARIA states are restored. Keyboard repeats are rejected while the same control is pending.
- Network, server and timeout failures have a visible dismissible alert. Recovery wording does not promise that an uncertain mutation was rolled back. Session-expiry and capacity responses retain their dedicated recovery paths.
- Idle loading indicators are hidden from the accessibility tree without moving adjacent controls.
- Paging one table preserves other table positions and repeated multi-select filter values.
- Compatible main-workspace record lists offer Cards/Table on phones. Original cells, links and controls remain the same DOM nodes. Card fields wrap, actions have 44-pixel minimum heights, hidden rows remain hidden, and desktop keeps a table. HTMX cleanup removes generated controls; tbody replacement re-enhances records.
- Narrow headers retain reachable primary controls. Help and Report a problem move into the account menu. This fixes the outer workspace being scrolled sideways when focusing an off-screen theme/account control.
- Shared mobile role homes expose a level-one page heading. HR and regional leadership exceptions precede general metrics.
- Regional/country oversight owner groups expand and collapse; paging a group keeps it open. Their school records now include operational School IDs. The regional delegation form wraps on phones so its action remains reachable.
- All new visual styles use the platform's semantic theme colours. Existing blue/dark divider and contrast regression tests remain in force.

## Validation completed

- `npm run test:ui-state`: 6 behavioural tests passed (concurrent requests, duplicate completion, restored DOM identity/ARIA, input submitters, uncertain failures, dedicated session/capacity recovery).
- Targeted Django suite: 182 tests and 862 subtests passed. Includes theme contrast, shared components, interaction/loading contracts, mobile foundations, role homes, workflows, responsive tables, pagination and directory interactions. One existing Django CheckConstraint deprecation warning remains.
- Additional checks: 28 oversight/access tests and 14 subtests passed; five school-identity tests and 684 subtests passed, including template compilation.
- Generated indexed CSS rebuilt successfully.
- Live local browser checks: IA returned activities in light, blue and night themes; 320/390-pixel mobile card layouts; Cards/Table switching; desktop table restoration and hidden mobile labels at 1440 pixels; narrow header controls and account help access; HR mobile heading, attention-first order and idle indicator visibility; school directory retained its own card layout; Regional Programme Lead mobile dashboard and oversight groups were inspected, including School IDs, 320-pixel layout, keyboard accordion expansion, hidden collapsed content and full wrapped field values.
- During live checking, conflicting legacy table display/height rules, visible desktop mobile-labels, and off-screen header focus were reproduced and corrected. These demonstrate why source checks alone are insufficient.

These checks do not establish production performance, screen-reader interoperability, all-role workflow correctness, or user satisfaction. No messages have been sent to outside reviewers, and no human approval has been recorded.

## Acceptance criteria for independent reviewers

Review representative populated, empty, loading, validation-error, network-error and permission-limited states in every role, then record exceptions against the full route register.

| Area | Acceptance criterion |
| --- | --- |
| Components | Tables, filters, tabs, forms and actions follow shared patterns; departures have a documented task reason. |
| Hierarchy | The user's next decision and primary action are obvious; scope and reporting period remain visible and accurate. |
| Responsive layout | At 320, 390, 768 and 1440 pixels, no page-wide horizontal displacement or inaccessible controls. Dense comparisons may have a labelled scroll region; operational records have a usable compact presentation. |
| Accessibility | Complete a workflow with keyboard only; test visible focus, focus return, screen-reader names/headings/errors, 200% text resizing and 400% zoom. Measure actual text/control contrast in all three themes. |
| States | Loading acknowledges the correct action; errors explain recovery and retain available entries; empty states explain what to do next; success reflects a confirmed server result. |
| Data and permission integrity | UI changes do not broaden access, change financial decisions, hide required information, or misrepresent missing values as zero. |
| Performance | Measure real user LCP, INP and CLS and slow-network workflows in the release environment. Record device/network/sample size; do not substitute local request time or a static contract score. |
| User validation | Staff complete realistic tasks without coaching. Record completion, mistakes, time, confusing labels and confidence; obtain explicit acceptance after fixing blocking findings. |

## Role workflow sampling

- CCEO: find an assigned school, read its ID, plan a visit, review evidence and schedule state.
- Programme lead / regional programme lead: inspect district groups, urgent schools, team work plans and a supervised action.
- IA: select an allowed school, inspect SSA evidence, review a returned item and prepare an impact report.
- HR Director: identify the next people decision, filter reach, inspect staffing and a review workflow using authorised test data.
- Country Director / RVP: inspect priorities, approvals and programme outcomes in their scope.
- Accountant: inspect an advance and accountability record; use a sandbox for consequential actions.
- Coordinator / partner roles: inspect assigned delivery and evidence workflows.
- MFI roles: inspect authorised lending records and evidence without executing real transactions.
- Administrator / business transformation: inspect configuration, quality and support workflows.

Independent UX, accessibility and frontend reviewers should fill the CSV with their names, findings and final decision. Real staff acceptance and production performance measurement remain required before declaring the entire platform enterprise-ready.

## Second check — 14 September

Found and fixed two additional lifecycle defects: a request cancelled by a later event listener could leave its control busy, and a tbody refresh reset the user's Table/Cards selection. Added behavioural regressions for cancellation, selection preservation, duplicate-label prevention and generated-control cleanup. All nine JavaScript tests pass; the focused theme, table, status and pagination Django checks pass (15 tests). JavaScript syntax and diff whitespace checks pass.

Live regional oversight recheck at 320 pixels: page width 320, main left offset zero, delegation control height 44 and right edge 298, keyboard accordion expansion successful, all six fields of the sampled first record had no horizontal clipping, and Table selection restored native table display. The viewport override was reset. This is a focused recheck, not independent acceptance of all routes.
