# Platform UI design audit — 8 September 2026

## Verdict

The platform has a coherent typography foundation and compact data components, but it is not ready for final visual sign-off as a minimal, premium enterprise workspace. The highest-value work is to simplify page structure and surface treatment. Further global font shrinking would make the product harder to use without solving the main space problem.

This is a product-design assessment grounded in measurements and live inspection. It does not claim employment at any named design organization or a formal accessibility certification.

## Evidence and scope

- Inspected the live local Team Oversight and Analytics pages, including mobile and light/dark/Edify blue views. Earlier live checks in this task also covered the CCEO dashboard, finance dashboard, budget and Batch Payments.
- Measured 24 saved server-rendered page variants representing all 14 roles, at 390, 768 and 1440px widths in all three themes: 216 combinations. All measurement runs completed and none showed document-level horizontal overflow.
- The saved pages come from the isolated test-data route crawl. They use the current local styles, but they are not live populated records and do not cover every route, drawer, modal, state or permission combination. Absence of page overflow does not establish that every cell or label is unclipped.
- All 24 sampled pages resolved to the same Geist Sans font stack. Desktop heading samples were consistently H1 20px/700, H2 16px/600 and H3 15px/600.
- On the populated Team Oversight page at 1048×857, the first table header starts around 678px, the first data row around 710px, and ordinary rows measure 32px. The compact table is reached late because of the material above it.
- Mobile leaf-text samples from paragraphs, labels and table cells were predominantly 12px: 588 of 596 sampled elements. This is a sample distribution, not a count of every visible text element in the platform.
- Nine shared tab styles were separately tested across three sizes, themes and Chromium/Firefox/WebKit for the requested sharp internal joins and curved outer ends.
- Source inspection found 2,752 `!important` occurrences across 30 first-party CSS files (41,310 lines), excluding the generated main/tokens bundles and vendor directories. This is a maintenance warning, not a visual defect count.

Collection script: `e2e/ui-design-audit.spec.js`. Raw measurements: `test-results/ui-design-audit/*.json`. A passing collection test means measurements completed; it is not automatic design approval.

## Findings and recommendations

| Priority | Area | Finding | Recommendation |
|---|---|---|---|
| P1 | Page density | Team Oversight places a title card, description, period controls, KPI heading/strip/navigation, a separate filter/export row, team tabs, selected-team context and owner heading before the first row. | Consolidate into a compact title/actions row, one scope toolbar, KPI strip and team selector immediately above the data. Move explanatory copy to contextual help. Preserve scope labels where they prevent misreading. |
| P1 | Mobile usability | Team Oversight offers approximately one initial data row above the bottom navigation. Much primary text falls to 12px in the measured mobile sample. | Reduce header layers first. Use 14px for primary mobile task text; reserve 12px for supporting metadata. Provide a compact record summary or priority columns on phones, with details on demand. Keep financial comparisons available as tables. |
| P1 | Theme surfaces | Edify blue places a prominent photograph behind translucent working surfaces. Background detail competes with labels, borders and status colors. | Keep Edify blue as a color theme with an opaque blue canvas and solid surfaces. Reserve photography for sign-in or welcome content. Verify text/status contrast after the surface change. |
| P1 | Cards and elevation | Large softly shadowed introductions and multiple framed context blocks create more visual weight than the data. Analytics has several context layers before its analytical content. | Flatten routine page headers. Use one bordered surface per related data section; avoid nested cards. Reserve substantial elevation for dialogs, menus and overlays. Use restrained 12–16px card padding. |
| P1 | Style ownership | Recent tab defects came from several shared/positional/button rules overriding one another. Broad last-loaded overrides remain a source of regressions. | Give each component one owner stylesheet and a documented contract. Migrate generic overrides into component rules in small verified batches. Do not remove `!important` indiscriminately. |
| P2 | Table consistency | Team Oversight's 32px rows are already suitably dense. Different measured row heights include legitimate multiline and empty-state content. Its tables also repeat full headers and pagination for each person. | Standardize ordinary rows at 32–36px and headers at 32px, allow natural multiline height, use 12px horizontal cell padding and tabular right-aligned numeric columns. Consider collapsible person groups or a single grouped table to reduce repeated framing. |
| P2 | Buttons and inputs | The system has a 30–32px desktop core, with larger mobile controls and special-purpose variants. In Analytics, the square “More filters” control differs from neighboring rounded inputs, and “Customize” dominates the action hierarchy. | Define compact desktop controls at 32px, regular controls at 36px and a deliberate mobile interaction target around 44px. Apply the same control geometry to disclosure triggers. Use primary emphasis for the principal task; keep export/customization secondary. Validate target spacing rather than treating every smaller visual icon as a defect. |
| P2 | Tabs | Shared corner behavior is now corrected. Batch Payments still has a long full-width track with only two short tabs, whereas dashboard switches now fit their labels. | Define two intentional patterns: fit-content segmented view switches for a few modes, and scrollable section navigation for many destinations. Both use sharp internal joins and curved outer ends. Keep padding, selected-state treatment and focus behavior shared. |
| P2 | Typography | Font family and heading scale are consistent. Small text, uppercase eyebrows and dense explanatory copy still create noise. | Keep Geist Sans. Keep the current compact heading hierarchy. Use 400 body, 500 labels, 600 section headings and 700 page titles/KPIs. Reduce unnecessary uppercase and repeated captions. Do not introduce a second display font. |
| P2 | Product language | Examples include “Selected team” followed by the same team name and an explanatory sentence, engineering/provenance banners on operational screens, and status rendering such as “Ia Verified.” | Use concise task language, correct acronyms and consistent sentence case. Move implementation provenance to an explicit “Data details” disclosure. Keep operational freshness and scope visible where they affect interpretation. |
| P2 | Status hierarchy | Analytics repeats several red alert cards, while much other UI uses blue emphasis. Several signals compete at similar strength. | Prioritize one most urgent next action; use text labels and restrained semantic accents for the remainder. Distinguish normal zero, missing data and actual risk. Avoid using red simply because a count is zero. |

## Recommended compact design contract

These are proposed targets, not a claim that every component currently meets them.

| Element | Proposed standard |
|---|---|
| Font | Geist Sans throughout; system fallbacks retained |
| Page title | 20px / 700; 24px only for exceptional overview contexts |
| Section / card headings | 16px / 600 and 15px / 600 |
| Desktop table and control text | 13px; 12px for secondary metadata |
| Primary mobile task text | 14px; 16px editable text where needed for mobile behavior |
| KPI values | Preserve current 20–24px compact hierarchy |
| Desktop controls | 32px compact, 36px regular; consistent icon sizing and alignment |
| Mobile controls | Aim for 44px interaction targets or adequate separation; avoid global shrinkage |
| Table rows | 32–36px ordinary desktop rows; expand for meaningful multiline content |
| Spacing scale | 4, 8, 12, 16, 24px; use 8px inside controls, 12px within related groups, 16px between routine sections |
| Cards | 12–16px padding; subtle border; little or no shadow on static data surfaces |
| Page introductions | Title, short optional description and actions; no decorative hero container on routine work pages |
| Themes | White light surfaces, solid dark surfaces, solid blue surfaces; same geometry in all themes |
| Tables and amounts | Right-align numerical comparisons, tabular figures, exact amounts available alongside compact summaries |
| Tab corners | Sharp internal joins; curves only at the outer ends; single-tab controls curve on both sides |

## Team Oversight: concrete redesign direction

Current sequence: introduction card → period row → KPI heading/strip/navigation → filter/export row → team tabs → selected-team label/title/description → owner summary → table.

Proposed sequence:

1. **Team Oversight** with Export as a secondary action on the same row.
2. **FY / period / team / Filters** in one scope toolbar, wrapping deliberately on phones.
3. Compact KPI strip, with the current country scope stated once.
4. Team name and owner summary immediately above the table. Additional explanation lives in contextual help.

For this page, use a design target of bringing the first useful data row to roughly 400–450px from the top at 1048×857, compared with the observed ~710px. That would recover roughly 260–310px, equivalent to eight or nine current 32px rows. This is a proposed layout budget, not a measured result of an implemented redesign. On a phone, aim to expose at least two actionable records without scrolling the entire header stack.

Do not apply a universal “first table” threshold to analytical dashboards: their charts and prioritized decisions may be the primary content.

## Acceptance gates before final visual sign-off

1. Review populated Team Oversight, finance, planning and analytics screens after the structural pass; confirm that scope and primary actions remain clear while first-screen content increases.
2. Check long names, large amounts, empty/loading/error states, selected middle tabs, overflowing navigation, dialogs and drawers in each theme.
3. Verify keyboard focus and navigation, 200% zoom, text contrast, mobile target spacing and table scrolling. The current audit is not a substitute for those targeted accessibility checks.
4. Add a small maintained screenshot baseline using real shared components and representative populated pages. Include the complete stylesheet order and real HTMX updates, which previously exposed an issue that static rendering missed.
5. Review changes with users completing three representative tasks: identify at-risk work, inspect a funding request and find the next assigned activity. Observe errors and time to the first meaningful action, not merely the amount of content packed onto the screen.

## Suggested order of work

First: consolidate page headers/toolbars, remove photographic work-surface backgrounds and reduce card elevation. Second: settle mobile text/target density and shared button/table/tab variants. Third: simplify component ownership and lock down the visual regression baseline.

No application UI was changed as part of this audit. The output is the assessment, measurement harness and recommended implementation sequence.
