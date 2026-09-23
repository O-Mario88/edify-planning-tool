# Edify frontend audit: the state before the responsive upgrade

A static read of the source, taken on 2026-09-23 at `e5a5cb9` before the
responsive system landed. It is the "current-state design audit" of the
responsive standard: where the CSS comes from, what each shared component
does about wrapping, the type scale, breakpoints, tables, the shell, the
tests that pinned the old behaviour, and the defects that followed from them.
The measured, page-by-page matrix — every argument-free page each seeded role
opens, at thirteen geometries, before and after — is
[responsive-audit-matrix.md](responsive-audit-matrix.md).

Counts come from static scans of `templates/**/*.html` and the hand-written
CSS (`static/css/**` excluding `vendor/`, `main.css` and `tokens.css`, plus
`assets/css/*`). Section 10 is the plan the change followed; where the
implementation departed from it, the matrix and the final report say so.

---

## 0. Headline findings

1. **Most of the target contract already exists but is split across layers, and several pieces work against each other.** Examples: table cells get `white-space: nowrap` everywhere, but `.edify-badge` explicitly sets `white-space: normal`. Tables are meant to scroll, but a JavaScript "fit by truncating" engine ellipsises them at 64rem and above. Drawers are *pinned by tests* to stay a floating centred card on phones.
2. **Some things only work after JavaScript runs.** `static/js/micro-ux.js` wraps *every* table in a scroll region and tags it `.edify-mobile-table--scroll`. 17 tables in 16 templates have no server-side scroll wrapper and depend on that JS.
3. **Many rules are scoped to `main` only, but `#drawer-container` sits outside `<main>`** (`templates/layouts/shell.html:449`). Tab nowrap, the `text-[12px]`→13px remap and the button min-heights in `platform.css` therefore do not reach drawers. The drawer templates alone carry 338 × `text-[12px]`.
4. **The cascade is heavily overridden.** 11 cascade-ordered stylesheets carry about 2,900 `!important` (consistency.css 1,015, platform.css 492, drawers.css 435, components.css 400). New shared rules must go in the *last* layer that owns the property, or they lose.
5. **There is a gap in the page-overflow tests.** The shell root is `h-full flex overflow-hidden` and `<main>` is `overflow-y-auto`, so page-wide overflow shows up as `main.scrollWidth > main.clientWidth`, not on `document.documentElement`. Most e2e overflow checks measure `documentElement` (details in section 7).

---

## 1. How CSS is built

### Pipeline (`package.json`)
```
"build:css": "tailwindcss -i assets/css/tailwind.source.css --minify -o static/css/main.css
           && tailwindcss -i assets/css/tokens.source.css --minify -o static/css/tokens.css
           && node scripts/build_indexed_css.cjs"
"watch:css": "node scripts/watch_css.cjs"   # watches assets/css, static/css, static/js, templates, apps
```
- The build uses Tailwind **v4.3.3** CLI, `@tailwindcss/oxide`, and `lightningcss` 1.32.0. **There is no `tailwind.config.js`.** The config is CSS-first:
  - `assets/css/tailwind.source.css`: `@import "tailwindcss" source(none)`, plus `@source "../../templates"` and `@source "../../apps"` (Python class strings count). It also imports `_theme.css` and **`../../static/css/custom.css`**, so custom.css ships *inside* main.css.
  - `assets/css/tokens.source.css`: Tailwind plus `_theme.css` only, giving about 6 KB for the sign-in layout.
  - `assets/css/_theme.css`: the single `@theme static {}` block. It holds `--font-sans`/`--font-mono`, the `--color-edify-*` aliases (these resolve to `var(--brand-*)` / `var(--edify-*)`), the extra `-150` shades, the **radius tokens** (`--radius-surface:12px`, `--radius-control:10px`, `--radius-overlay:16px`, `--radius-small:6px`, `--radius-pill`), and `--animate-fade-in`.
- `scripts/build_indexed_css.cjs` rewrites every `[class*="x"]` substring selector into `:is(.a,.b,…)`. The class list comes from CSS selectors, the Tailwind scanner over `templates`+`static/js`, template class attributes, JS `classList` calls, and badge/colour prefixes in Python. It covers exactly these 10 files (lines 14-25): `main.css, design-system.css, components.css, pages.css, platform.css, consistency.css, drawers.css, components/mobile-micro-ux.css, components/interactions.css, components/mobile-patterns.css`. Output goes to `static/build/css/<same path>` plus `selectors.json` (191 patterns). There are 562 `[class*=` selectors in the indexed sources.
  - **This matters for new work:** a new `[class*="…"]` selector in an indexed file only matches classes that exist when the build runs. The route audit e2e fails on "unindexed class patterns".

### Generated or source
| Generated (never hand-edit) | Source (edit these) |
|---|---|
| `static/css/main.css`, `static/css/tokens.css` | `assets/css/{tailwind.source,tokens.source,_theme}.css` |
| everything in `static/build/css/**` (incl. `selectors.json`) | `static/css/*.css`, `static/css/components/*.css`, `static/css/pages/*.css` |

### What `templates/base.html` loads, in cascade order (lines 74-115)
`css/fonts.css` → **build/**`main.css` → **build/**`design-system.css` → **build/**`components.css` → `css/components/sidebar.css` → `css/components/mobile-shell.css` → **build/**`components/mobile-patterns.css` → **build/**`pages.css` → **build/**`drawers.css` → `css/app.css` → `{% block platform_css %}` **build/**`platform.css` → `{% block feature_css %}` (per-page `css/pages/*.css`, admin/hcos/help-center) → `{% block consistency_css %}` **build/**`consistency.css` → **build/**`components/mobile-micro-ux.css` → `css/components/platform-status.css` → `css/form-refinement.css` → **build/**`components/interactions.css`.

Each link carries a hand-bumped `?v=` cache key. `apps/frontend/test_platform_table_system.py:120` requires **the `mobile-micro-ux.css` key to equal the `micro-ux.js` key**. `test_design_system_quality.py:566` pins `20260906float1` (on drawer-background.js).

**Orphan:** `static/css/components/record-views.css` is referenced by no template and is not in the indexed build, so it is dead CSS. It contains `white-space: normal !important` on record-table `thead` below 1024px.

### Rebuild
```
cd /home/user/edify-planning-tool
npm ci                # node_modules absent in this checkout
npm run build:css     # regenerates static/css/{main,tokens}.css + static/build/css/**
```
**CI gate** (`.github/workflows/ci.yml:155-174`, Node 24): `npm ci && npm run build:css && git diff --exit-code static/css/main.css static/css/tokens.css static/build/css`. Any edit to templates, apps class strings, static/js classList or source CSS therefore needs a rebuild and a commit of the output.

### Where the tokens live
- **`static/css/design-system.css`** (the single `:root` token layer, lines 15-548; theme blocks at `:root.light` 550, `:root.theme-blue` 569, `:root.theme-dark` 740).
  - Colours: brand palette at line 19, semantic ramps (`--edify-{success,warning,danger,info}{,-light,-border,-text}`) at 118, chart series at 185, surfaces at 221 (`--edify-bg`, `--edify-surface{,-muted,-raised}`, `--edify-border{,-strong}`, `--edify-text{,-muted,-subtle}`, `--edify-table-*` at 267-273), and `--brand-primary*`.
  - **Type** (lines 328-437): `--edify-text-{display 1.25rem, hero 1.5rem, heading 1rem, title .9375rem, body .8125rem, label .8125rem, floor/micro .75rem}-size`; component roles `--edify-text-{card-heading, card-title, tile-value, tile-label, tile-helper, table .8125rem, table-heading .75rem}-size`; weights, leading and tracking per tier; composed `--edify-font-{display,heading,title,body,label,micro}`.
  - **Table contract** (377-390): `--edify-table-cell-padding-{block .5rem, inline .75rem}`, `--edify-table-{header,body,identity}-weight`, `--edify-table-action-size: 2rem`.
  - **Spacing** (439-470): `--edify-space-{0..16}` on a 4px scale, aliases `xs..2xl`, `--edify-surface-padding*`, `--edify-kpi-padding` (clamp). **Almost nothing uses them:** only 7 `var(--edify-space-*)` padding/margin/gap declarations, against about 778 raw-px spacing declarations in source CSS.
  - Radius aliases `--edify-radius-{xs,sm,md,lg,xl,pill}` point to the `_theme.css` tokens (472-490). There are also shadow, motion and shell tokens, and `--edify-page-gutter: clamp(1rem, .7rem + 1.1vw, 1.75rem)` (547).
- **`static/css/platform.css:20-30`**: `--edify-page-max-size: 112rem`, `--edify-control-block-size: 2.5rem`, `--edify-action-button-{block-size 2.75rem, padding-inline, icon-size, radius}`, `--edify-panel-*`.
- **`static/css/components/mobile-micro-ux.css:415-424`** (≥64rem) resets `--edify-action-button-block-size: 2.5rem`. The same file (529-546, 712-727, 764-778) **re-declares the type tokens per breakpoint** (see section 3).
- **`static/css/drawers.css:7-11`**: `--drawer-width-{sm 420, md 580, lg 820, xl 1120, workspace 1600}px`; `:2114` `--edify-drawer-inset: clamp(1rem,4vh,3rem)`, `--edify-drawer-radius: 1.5rem`.
- **Legacy tokens in `static/css/custom.css:10-…`** (still compiled into main.css): `--text-tiny 11px`, `--text-caption 12px`, `--text-body 13.5px`, `--text-h-xs/sm/md 16/19/26px`, `--surface-*`, `--text-primary` and others. This is a second, stale scale.
- `--page-header-padding-{x,y}` are set to `0px` in all three themes (design-system.css:288, 661, 818; consistency.css:3201).

---

## 2. Shared component classes

"nowrap / min-height / shrink / font" describe the effective declarations found (file:line). Only the key rules are listed.

| Component | Where defined | nowrap | min-height | flex-shrink | font-size |
|---|---|---|---|---|---|
| `.btn`, `.edify-action-button` (48 template uses) | components.css:1096 | **yes** | pointer:coarse 44px (components.css:2619); `main` 2.5rem (platform.css:435); block-size = `--edify-action-button-block-size` via `.edify-shell :is(…)` at mobile-micro-ux.css:433 (≥64rem) and :623 (<64rem) | `flex-shrink:0` (components.css:1096), `flex:0 0 auto` (platform.css:466) | token (label). **But mobile-micro-ux.css:433/623 hard-codes `0.8125rem !important`**, and :738/:793 drop to micro at ≤36rem / ≤22.5rem |
| `.btn-premium-primary/-secondary` (32/12 uses) | shares platform.css:450/466 + mobile-micro-ux blocks | **no** (only when inside a table cell: platform.css:825) | yes (shared block-size) | `flex:0 0 auto` | 13px via the shared block |
| `.school-record-action` (36 uses) | platform.css:3452; consistency.css:4180 | **yes** | yes | yes | label token; micro at ≤33rem (platform.css:4104) and in `@container school-record (max-width:38rem)` (:4125) |
| `.edify-primary-solid` (135 padded controls) | consistency.css (colour only) + mobile-micro-ux sizing | **no** | yes (<64rem, via the generic `button` rule) | no | inherits |
| custom `button` in `.edify-workspace` | mobile-micro-ux.css:208 (<64rem min 2.75rem !important), :310 (coarse 3rem) | **no** global nowrap | yes | no | inherits |
| `components/button.html` (8 includes) | emits `btn btn-{variant} inline-flex h-8` | yes (via `.btn`) | h-8 | via `.btn` | via `.btn` |
| Tabs: `[role=tab]`, `.edify-tab-btn`, `[data-edify-tab]`, `.messages-inbox-tab`, `.pto-tabs>button`, `.edify-section-nav__link` and others | platform.css:~915-1011 (`main :where(…)`); pages.css:307; interactions.css:253-339 | **yes** (platform.css:933, pages.css:307), but **main-scoped only** | 2.375rem, then interactions.css:339 resets to 0 and the rail is 2rem; `.edify-shell [role=tab]` = action height ≥64rem | `flex:1 0 auto` (<48rem), `0 0 auto` ≥48rem | label token !important |
| Tab rails `[role=tablist]`, `.edify-tab-container` | platform.css:903 (`overflow-x:auto`), :5259 (≥64rem `flex-wrap:nowrap; overflow:hidden` plus the JS "More" overflow `.edify-rail-more`); pages.css:293 | n/a | 2.75rem / 2rem | n/a | n/a |
| `.edify-badge` (59 uses) | **components.css:19-35** | **NO: `white-space: normal; overflow-wrap: anywhere`** | none | none | `var(--edify-text-micro-size)` |
| `.status, .status-pill, .edify-status-badge, .badge` | platform.css:1198 (`main :where(…)`) | yes (main only) | 1.5rem | no | micro token |
| `components/badge.html` (16 includes) | Tailwind `whitespace-nowrap rounded-pill` | yes | none | none | `edify-text-caption` / `text-[12px]` |
| Tables (shared) | platform.css:663-700 (`main table th/td, .drawer-body table th/td`); consistency.css:2852-2885 "EVERY TABLE STAYS ON ONE LINE"; mobile-micro-ux.css:71-92 (`.edify-table-scroll-region`) | th: yes; td: platform.css:690 sets `text-wrap: pretty`, **overridden** by consistency.css:2865 `nowrap !important` (scope: main, .drawer-surface, dialog) | n/a | n/a | `--edify-text-table-size` / `--edify-text-table-heading-size` (!important) |
| `.edify-record-table` (110 tables in 80 files) | consistency.css:2762-2890; identity col `[data-record-title], tbody th[scope=row]` gets `inline-size:100%` (consistency.css:~2900) | yes | row-action size | n/a | tokens |
| Scroll wrappers | `.edify-table-scroll-region` (JS-applied, mobile-micro-ux.css:71); `main :where(.overflow-x-auto, .overflow-auto, [class*=table-wrap], [class*=table-scroll]):has(>table)` (platform.css:873, `container: edify-table`); `.edify-record-table-wrap` (mobile-shell.css:355, <1024px only) | | | | |
| Sticky identity column | **only** `main table .edify-frozen-cell` (platform.css:5060; 10 uses in 2 templates) plus page-specific ones (`.tt-member-row>td:first-child` pages.css:3431, `.period-matrix`, `.edify-report-matrix__table`, `.ia-master-table th` top-sticky) | | | | |
| Page header `.edify-page-header` (212 hand-rolled, 8 via `components/page_header.html`) | components.css:620 (flex, wrap, `gap`, padding via tokens that equal 0), :647 `__lead flex:1 1 20rem`, :758 `__controls flex-wrap:wrap`; consistency.css:1818; mobile-patterns.css:689/747 per-family padding | title: no (`main h1 {max-inline-size:30ch; text-wrap:balance}` platform.css:92) | n/a | n/a | `.edify-page-title` → `--edify-text-display-size` !important (consistency.css:446, 2305). 220 of 221 h1s carry `edify-page-title` (enforced by `scripts/normalize_page_titles.py --check`) |
| KPI strip: `components/context_metrics.html` (`kpi_strip.html` delegates; 81 including templates) | components.css:5307 `.context-metrics__sentence {flex; nowrap; overflow-x:auto}`, :5336 `__fact flex:1 0 auto`, :5384 value `clamp(20px,2cqi,24px)` | row nowrap | | | clamp |
| Legacy `.kpi-strip*` (168 rules) / `.edify-kpi*` (28 rules) | components.css, consistency.css, platform.css | Emitted by no template or JS (0 uses), **but pinned by tests** (`test_metric_labels_yield_columns_instead_of_wrapping`) | | | |
| Drawer `components/drawers/base_drawer.html` (84 extending templates; 9 hand-rolled `drawer-*`) | drawers.css (2,545 lines, 4+ re-declarations; the final block is at :2150-2300) | drawers.css has **zero** `white-space` rules | | | drawer title clamp at drawers.css:2357 |
| Pagination `components/table_pager.html` (197 including templates; 13 hand-rolled Prev/Next) | mobile-micro-ux.css:821-980 (`--edify-pagination-control-size` 1.875 → 2 → 1.75rem; ≤36rem stacks into a grid and hides the "Prev/Next" words) | labels are single words | yes | | caption token |
| Filters `.edify-filter-bar` (59), `.edify-filter-field` (16) | consistency.css:1000-1082 (flex, `flex-wrap:wrap !important`), :3992 (<64rem wrap); analytics-dashboard.css:947 (nowrap+scroll); mobile-micro-ux.css:337-370 (`#filters-form .school-filter-grid` grid 2/3/6 cols) | n/a | | | |
| `components/mobile_filter_sheet.html` | exists and is lint-tested (test_mobile_foundation), but **included by 0 templates** (2 pages hand-roll `data-mobile-filter-sheet`) | | | | |

---

## 3. Typography

### Tokens and responsive overrides
The base scale is at design-system.css:346-375. The body and label tiers are both **13px**, so the ladder is 12 / 13 / 15 / 16 / 20 / 24.
`test_core_and_component_type_steps_do_not_continuously_resize` forbids `clamp|calc|vw|cqi` inside the design-system TYPOGRAPHY block.
The stepped responsive tiers are declared instead in `components/mobile-micro-ux.css`:

| token | base | <64rem (:536) | ≤36rem (:719) | ≤22.5rem (:771) |
|---|---|---|---|---|
| display | 1.25rem | 1.25 | 1.125 | 1.0 |
| heading | 1.0 | 1.0 | .9375 | .875 |
| title | .9375 | .9375 | .875 | **.75** |
| body | .8125 | .8125 | **.875** | **.875** |
| label/table | .8125 | .8125 | .8125 | .8125 |
| tile-value | 1.25 | 1.125 | 1.0 | .9375 |

**Defect:** the hierarchy inverts at small widths. Body grows to 14px while title shrinks to 14px (≤36rem) and then to 12px (≤22.5rem), so a card title ends up smaller than body copy.

### font-size declarations in source CSS (1,339 in total)
`var()` 1,023 · raw rem/em 229 · raw px 43 · `clamp()` 41 · calc 2.
The files with the most raw values are `pages/ia-master.css` (68 rem), `drawers.css` (17), `analytics-dashboard.css` (17 rem + 2 px), `pages/team-target-distribution.css` (18, all raw), `custom.css` (18 px), `login.css` (15), and `help-center.css` (14).
The most common raw values are 1rem ×22, .875rem ×23, .75rem ×14, .6875rem ×9, .66/.68rem ×7 each, and 14px ×6.

**Sub-12px sizes (below the declared floor): 79 declarations.**
- `pages/ia-master.css` 43 (e.g. :114 .66rem, :196 .6rem, :283 .58rem)
- `pages/analytics-dashboard.css` 15 (:87 10px, :612 10px, :1265 .5625rem, :1243 .6875rem on header controls ≤48rem)
- `pages/team-target-distribution.css` 14 (.56-.72rem)
- `pages/oversight-workspace.css` 3
- `components/mobile-shell.css:292,306` (.6875 and .625rem)
- `components/interactions.css:984` (11px)
- `components/platform-status.css:105`

They survive because the lint globs `static/css/*.css` only, not subfolders (see section 7).

**Fluid (clamp) sizes:** 41 declarations, all feature-local. There is no fluid *token*. The only fluid tokens are `--edify-page-gutter`, `--edify-kpi-padding`, `--edify-panel-gap` (platform.css:28) and `--edify-drawer-inset`. Examples: components.css:1714/2006/4357/5384 (KPI values, `cqi`); drawers.css:337/959/1466/2357 (drawer titles); pages.css:1672/1888/2016/2067/2624; ia-master.css:123/144/221; help-center.css:67/156/363; login.css:192 `clamp(3rem,4vw,4.05rem)`; hcos-workspace.css:43 `clamp(2rem,4vw,3.5rem)`.

### Arbitrary Tailwind sizes in templates: 3,563 across 427 files
| utility | count | | utility | count |
|---|---|---|---|---|
| `text-[12px]` | **2,078** | | `text-[20px]` | 36 |
| `text-[13px]` | **619** | | `sm:text-[13px]` | 34 |
| `text-[14px]` | 395 | | `text-[22px]` | 21 |
| `text-[15px]` | 161 | | `text-[36px]` | 10 (empty-state icons) |
| `text-[18px]` | 113 | | `text-[32px]`/`[40px]`/`[44px]` | 5/2/1 |
| `text-[16px]` | 76 | | others | 7 |

Named sizes: `text-xs` 326, `text-sm` 324, `text-base` 23, `text-lg` 9, `text-xl` 7. The semantic utility `edify-text-caption` appears **3,799** times (components.css:7, label size, line-height 1rem !important).

**Remap bridge** (consistency.css:20-45): inside `main`, `.text-xs` and `text-[10-13.5px]` become the label token (!important), `text-[15px]` becomes body, and `[class*=badge|status|eyebrow|overline]` become micro. **This does not apply in drawers**, which sit outside `main`: their 338 × `text-[12px]` render at a literal 12px.

---

## 4. Breakpoints

- **328 `@media`** in source CSS, using **64 distinct width values** in mixed units.
- Grouped:
  - about 48rem (768px) band: 83
  - about 64rem (1024px) band: 64
  - 31-44rem: 37
  - ≤30rem: 17
  - 65-79rem: 18
  - ≥80rem: 18
  - 49-63rem: 9
- Most frequent exact values:

| query | count | | query | count |
|---|---|---|---|---|
| `min-width:64rem` | 26 | | `max-width:640px` | 7 |
| `max-width:48rem` | 23 | | `max-width:40rem` | 7 |
| `max-width:63.999rem` | 19 | | `max-width:36rem` | 7 |
| `min-width:48rem` | 17 | | `max-width:47.999rem` | 6 |
| `max-width:47.99rem` | 12 | | `max-width:47.9375rem` | 6 |
| `min-width:768px` | 7 | | `max-width:70rem` | 6 |

- There are also `1023.98px`, `767.98px`, `47.5rem`, `63.9375rem` and others, meaning four spellings of the same two breakpoints.
- `@media (pointer:coarse)` appears 15 times, plus 11 × `(max-width:48rem),(pointer:coarse)`.
- **Container queries:** 56 `@container` (platform.css 17, components.css 15, pages.css 10, analytics-dashboard 5, admin-dashboard 5) and 49 `container:` declarations. Named containers include `edify-workspace` (on `main`, platform.css:46), `edify-table` (every scroll wrapper, platform.css:876), `drawer`, `kpi-card`, `metric-tile` and `school-record`.
- Tailwind prefixes in templates: `sm:` 558, `lg:` 280, `md:` 69, `xl:` 52, `max-lg:` 3. There are no `@container` utilities.
- The shell switches at **`lg` (1024px)**: sidebar `hidden lg:flex`, bottom nav `lg:hidden`, and `micro-ux.js` `desktopShell = matchMedia('(min-width: 64rem)')`.

---

## 5. Tables

- **298 `<table>` elements in 208 templates.**
  - 1 is `sr-only`; 1 more uses `sp-visually-hidden`, which the JS exclusion list does not cover.
  - 69 carry `data-mobile-table="scroll"` and 1 carries `="fit"`.
  - 110 are `edify-record-table`, 46 `rpl-table`, 26 `edify-data-table`, and 11 `mp-table`.
- **280 tables have an overflow or scroll wrapper** as parent or grandparent in the markup: `overflow-x-auto` ×233, `data-table-scroll-region` ×60, `rpl-table-scroll` ×44, `edify-record-table-wrap` ×22.
- **17 tables in 16 files have none.** Several sit inside `overflow-hidden` cards and rely on `micro-ux.js` `makeScrollRegion()` (lines 495-514) to insert a wrapper at runtime:
  ```
  pages/ssa/upload_preview.html:92,122   pages/admin/audit_log.html:19     pages/cost_settings/index.html:93
  pages/districts/detail.html:49         pages/hr/conversation_document.html:36   pages/ssa/index.html:63
  partials/analytics/regional_performance.html:258   partials/budgets/budget_group_tables.html:7
  partials/core_schools/team_oversight.html:28       partials/cost_settings/edit_drawer.html:105
  partials/dashboards/admin/_planning_progress_body.html:26   partials/oversight/detail_drawer.html:105
  partials/oversight/partner_detail_drawer.html:118  partials/ssa/breakdown_table.html:4
  partials/ssa/performance_workspace.html:254 (sp-visually-hidden)   partials/targets/_period_matrix.html:23 (min-w-[860px])
  ```
- **nowrap in markup:** only 28 of 2,058 `<th>` and 127 of 2,147 `<td>` carry `whitespace-nowrap`. Nowrap comes from CSS instead: platform.css:673 (th), consistency.css:2852-2885 (all td/th and descendants, !important, in main/drawer/dialog), and mobile-micro-ux.css:86 (inside `.edify-table-scroll-region`).
- **Runtime behaviour** (`static/js/micro-ux.js`):
  - `enhanceTable` (558-586) adds a caption, `scope`, `data-edify-table-width` (standard ≤5 cols, wide 6-8, xwide >8), and wraps the table in a labelled `role=region tabindex=0` scroll region.
  - Below 64rem, `.edify-mobile-table--scroll[data-edify-table-width]` sets `min-inline-size: max(44|56|68rem,100%)` (mobile-micro-ux.css:165-175). **Even a 2-column table is forced to 704px wide on a phone**, so it scrolls when it didn't need to.
  - At 64rem and above, `fitTables()` (1091-1110) plus consistency.css:3836-3940 ("A TABLE WIDER THAN ITS REGION FITS BY TRUNCATING") apply `table-layout:fixed`, a computed `<colgroup>` and **ellipsis truncation**, not scrolling. The only opt-outs are `data-table-fit="scroll"` / `data-mobile-table="scroll"` / `.edify-record-table`; `data-table-fit` is used once.
- Also consistency.css:3560 (≥768px): `.edify-cell` gets `max-inline-size:24rem; ellipsis`. It is neutralised by the `max-inline-size:none !important` at :2865, so it is dead.
- **Shared table partials:** there is no generic table component. There are about 22 feature partials named `*table*.html` (e.g. `partials/schools/table.html`, `partials/actions/table.html`, `partials/planning/school_table.html`, `pages/escalations/_table.html`, `partials/oversight/_core_schools_table.html`), plus `components/table_pager.html`. The shared contract is the `edify-record-table` class family: identity cell `[data-record-title]` (159 uses in 105 files) or `tbody th[scope=row]` (93).
- **Sticky identity column:** there is no generic rule.
  - consistency.css:~2895 gives the record-table identity column `inline-size:100%`, and its own comment warns that a sticky column with that width "would ride over every data column". Making it sticky therefore also needs that width rule changed (e.g. `max-inline-size` or `inline-size:auto` while scrolling).
  - Tokens `--edify-frozen-surface{,-muted}` already exist for opaque sticky cells.
- `min-w-[…]` appears 229 times in templates, mostly on tables (`min-w-[1320px]` at `partials/targets/my_body.html:61`, `[1120px]` at `targets/team/workspace.html:131`, and others). That is fine inside a scroll region.

---

## 6. Mobile shell (`templates/layouts/shell.html`, 451 lines)

- Root (line ~30): `.edify-shell h-full flex overflow-hidden` (+`edify-shell-has-bottom-nav`), with a skip link.
- **Sidebar:** the mobile off-canvas is `lg:hidden fixed inset-0 z-40` with an `.app-sidebar max-w-xs` Alpine slide-in (lines 35-65). The desktop sidebar is `<aside class="app-sidebar hidden lg:flex">` (68-73), collapsible via `app-sidebar--collapsed`. Both include `components/sidebar.html`; its CSS is `css/components/sidebar.css` (not indexed).
- **Content column:** `flex-1 flex flex-col min-w-0 overflow-hidden` with `:inert="sidebarOpen"` (76-80).
- **Topbar:** `<header class="edify-topbar">` (83-~420) holds `__lead`, `__history`, search (collapses to an icon on phone/tablet), `__date` (`text-[12px]`), `__utilities`, notifications and `__account`. Mobile sizing is in mobile-shell.css:92-130 (≤47.5rem: `min-block-size: calc(3.25rem + env(safe-area-inset-top))`, gutter `max(var(--edify-page-gutter), env(safe-area-inset-left/right))`, 44px targets).
- **Main** (428-437): `<main id="main-content" class="edify-workspace flex-1 overflow-y-auto … bg-[var(--edify-bg)]" data-density="compact" data-mobile-system="micro-ux-v1">`. It is the scroll container, and `container: edify-workspace / inline-size` is set on it (platform.css:46).
- **Bottom nav:** `components/mobile_bottom_nav.html` has `edify-bottom-nav lg:hidden`, is fixed at the bottom with z 30, is a grid of equal cells, and hides for the software keyboard (`--hidden`). It sits inside the inert column. Clearance comes from `.edify-shell-has-bottom-nav .edify-workspace {padding-bottom: calc(56px + env(safe-area-inset-bottom))}` below 1024px (mobile-shell.css:334-337).
- **Safe-area insets:** `base.html:14` has `viewport-fit=cover`. `env(safe-area-inset-*)` appears in mobile-shell.css (13), mobile-patterns.css (4), platform-status.css (4), drawers.css (3), login.css (2), calendar-workspace.css (1), and `pages/ia/review_workspace.html` (2). The sidebar, bottom nav (bottom and inline), topbar (top, inline in landscape) and drawers are covered.
- **Width and gutters:**
  - `main > :where(div,section)[class*="px-"|"p-4"|"p-5"|"p-6"]` gets `inline-size:min(100%, 112rem); margin-inline:auto; padding-inline: var(--edify-page-gutter) !important` (platform.css:80-89).
  - `main > .edify-page-canvas` gets the same treatment plus `padding:1rem var(--edify-page-gutter)` (consistency.css:435-441).
  - The gutter is `clamp(1rem, .7rem+1.1vw, 1.75rem)`, i.e. 16px at 390px and 28px at 1440px.
  - `test_every_shell_page_has_a_gutter_contract_or_is_full_bleed` requires every page's root to carry `edify-page-canvas`, `edify-report-workspace` or `p-*`/`px-*`.
- **No `overflow-x: clip` anywhere** on html, body, main or the shell. Horizontal overflow inside main becomes a sideways-scrolling `main`, because `overflow-y:auto` forces overflow-x to auto.
- `data-mobile-family` (67 pages) selects per-family mobile layouts in mobile-patterns.css: performance 13, upload 7, directory 7, history 6, settings/oversight/analytics 5 each, and others.

---

## 7. Existing responsive tests

### Playwright (`playwright.config.js`)
There is a single worker. Projects: `seeded-accounts` setup, `chromium-desktop` / `firefox-desktop` / `webkit-desktop` (Desktop devices at 1280×720), `android-360` (**Galaxy S9+**, which Playwright's registry lists at 320×658), `iphone-390` (iPhone 13, 390×664), and `tablet-768` (iPad gen 7 overridden to 768×1024). The viewports come from Playwright's device registry and were not verified locally because node_modules is missing. CI's browser-suite runs Chromium and the route audit on each push; the full matrix runs separately.

Many specs replay HTML snapshots from `test-results/kpi-platform-crawl/` and `skip` when those are absent.

| spec | what it asserts (responsive-relevant) |
|---|---|
| `authenticated-route-audit` | For every role and every argument-free page: `documentElement.scrollWidth <= clientWidth+1` ("horizontal overflow"), **`.edify-badge` with `scrollWidth > clientWidth+2` fails ("overflowing status labels")**, no unindexed `[class*=]` patterns, ≤10k DOM nodes, every control named |
| `ui-design-audit` | Snapshot pages at **390 / 768 / 1440** × 3 themes: no `documentElement` sideways scroll, named controls, an h1/h2 exists |
| `calm-workspace` | `documentElement.scrollWidth <= innerWidth+2` at several widths; offline title is 20px |
| `project-layout` | **`main.scrollWidth - main.clientWidth <= 2`** (the only main-level check); first table above 620px at 1366; overfull tables keep action widths |
| `filter-containment` | fields ≥8px apart, no document overflow |
| `kpi-strips` | 320-1600px: visible metric counts per width, strip height ≤100, value ≤24px, no page overflow |
| `mobile-dashboard-tabs` | PL dashboard rail: `scrollWidth - clientWidth <= 1` for the rail and every tab (the tabs overflow into a **"More"** control, not a scroller) |
| `compact-drawers` | **At 390×844, 768×900, 1280, 1366 and 1920 the drawer must be centred (±2px), ≥8px from the top/left edges, height ≤ viewport−16, width ≤800 at ≥768, no inner horizontal scroll, submit visible** |
| `tab-corners`, `table-header-platform` (th colour `rgb(40,91,150)` at 1290), `table-column-plan` (1440), `plain-table-content`, `rectangle-platform` (1280/1366/1920), `display-density`, `workspace-polish`, `page-anomalies` (390 and 1366) | layout and theme detail |

**Gap:** only `project-layout` measures `main`. Every other overflow check reads `document.documentElement`, which the `overflow-hidden` shell root clips, so a page whose content pushes `main` sideways can pass them. Recommend adding a main-level check: `main.scrollWidth <= main.clientWidth + 1`.

### Python static lint (apps/frontend, 148 test files, SimpleTestCase)
Rules new work must respect:
- **Type** (`test_design_system_quality.py:1506-1686`):
  - No raw `font-size` below 12px, and **no raw `font-size` below 14px unless via a token**, in `static/css/*.css`. The glob is non-recursive and `design-system.css` is exempt from the 14px rule, so `components/` and `pages/` are unchecked.
  - Template `text-[Npx]` must sit on the ladder {12,13,14,15,16,18,20,22,28}, with a **ceiling of 60 off-ladder uses**; no `text-[<12px]`.
  - Chart `fontSize` ≥12px. No `var(--edify-text-micro-size)` in table th/td rules. Inline `font-size` ≥12px.
  - Exact token strings are pinned: `--edify-text-floor: 0.75rem`, `--edify-text-label-size: 0.8125rem`, `--edify-text-body-size: 0.8125rem`, `--edify-text-table-heading-size: 0.75rem`.
  - The TYPOGRAPHY block may not contain `clamp/calc/vw/cqi`.
  - `test_mobile_density_contract` pins `--edify-text-display-size: 1.125rem / 1rem / 1.25rem` and `[class~="text-[18px]"]`.
- **Tables:**
  - `test_tables_scroll_before_headers_or_words_are_crushed` requires `container: edify-table / inline-size`, `font-size: var(--edify-text-table-size) !important`, `.drawer-body table th {`, `text-wrap: nowrap`, `overflow-x: auto` and `word-break: normal` in platform.css, plus the "EVERY TABLE STAYS ON ONE LINE" block in consistency.css.
  - `TableColumnBudgetTest` requires `inline-size: max-content`, `max-inline-size: none !important`, `text-overflow: clip !important` and `white-space: nowrap !important` in consistency.css.
  - `test_platform_table_system` pins the JS strings ("Every visible table keeps single-line cells", `columnCount > 8 ? 'xwide'`) and the `max(44rem|56rem|68rem, 100%)` tiers.
  - `test_mobile_micro_ux` forbids table card modes.
- **Drawers:**
  - `test_popup_drawers_use_the_centered_dialog_contract` (docstring: "never … a full-height right-side drawer").
  - `test_drawers_use_the_centered_reference_modal_and_form_contract` (`max-height: calc(100dvh - 7rem) !important`).
  - `test_floating_drawer.py` pins, **in the last block of drawers.css**, `inset:0 !important`, `margin:auto !important`, `inline-size: calc(100% - (var(--edify-drawer-inset) * 2)) !important` and `max-block-size: calc(100dvh - …)`.
  - **A full-height mobile sheet directly contradicts these tests and `compact-drawers.spec.js`. The owner must sign off, and the tests must be changed alongside the CSS.**
- **Buttons, tabs and header:**
  - `test_one_action_button_height_at_every_width` (all declared sizes are `{"2.5rem"}`, in an `@media all` block).
  - `test_tab_design`: nine tests, including `no_template_paints_its_own_tab_strip` and `every_tab_surface_grows_from_its_complete_label`.
  - `test_page_hero_contract`: 11 tests (every page title sits in a shared header; the lead has a flex basis).
  - `test_shared_responsive_contract_covers_mobile_and_tablet` requires `@media (max-width: 63.9375rem)`, `(max-width: 47.5rem)`, `(max-width: 30rem)` and `min-block-size: 2.75rem` in platform.css. Consolidating breakpoints must keep these strings or update the test.
- **Tokens and markup:** no `rounded-[…]`, no `shadow-[…]`, no inline `border-radius`, no hard-coded `font-family`; `-150` shades only where declared; one `<main>` per page; every shell page has a gutter; `h-full` limited to an allowlist. `scripts/normalize_{legacy_primary_utilities,static_token_styles,page_titles}.py --check` must pass: no `bg/text/border-blue|indigo-*`, no static `style="background:var(--edify-surface)"`-style token declarations, and every h1 has `edify-page-title`.
- **Cache keys:** mobile-micro-ux.css and micro-ux.js `?v=` must match.
- **There is no global test banning `style="…"` or raw hex in templates.** Only `test_pl_cceo_performance_table.py:66` (one template) and `test_core_schools_layout.py:285` (core CSS `#fff`) check this.

---

## 8. Inline styles and raw hex

- **`style="…"`: 183 attributes in 86 templates**, plus 15 `:style=`.
  - 102 are dynamic (`{{ }}` widths or colours for bars and charts), 78 are static, and 3 set only custom properties.
  - The static ones are mostly `display:none` (32, Alpine FOUC guards), `background` (25) and `color` (20). **None set width, font-size or white-space.**
  - Top files: `partials/core_schools/performance_insights.html` 12; `partials/ia/operations.html`, `partials/core_schools/champion_review_drawer.html`, `pages/leave/leave_calendar.html` and `pages/debriefs/weekly_report.html` 7 each; `pages/projects/index.html` 6; `partials/projects/analytics_workspace.html`, `partials/planning/schedule_drawer.html`, `partials/finance/fund_workspace.html`, `partials/analytics/staff_partner_performance.html`, `pages/debriefs/submit.html` and `pages/closure/readiness_queue.html` 4 each.
- **Raw hex in templates: 25, in 3 files only:** `pages/offline.html` 15 (standalone, own `<style>`), `partials/pwa_launch.html` 9 (`<style>` mask gradients), `layouts/login.html` 1. There are no `bg-[#…]` arbitrary colours and no hex in `style=` attributes. **Templates are effectively clean.**
- Raw hex in source CSS: 1,189. The largest are custom.css 410, design-system.css 196 (the token definitions, which is expected), ia-master.css 150, login.css 93, consistency.css 64 and components.css 64.

---

## 9. Wrap-risk defects found statically

1. **`.edify-badge` wraps by design**: components.css:31-33 sets `white-space: normal; overflow-wrap: anywhere` (59 uses). ia-master.css:75 patches it for one header only. Switching it to nowrap needs `max-inline-size:100%` plus ellipsis, or the route-audit "overflowing status labels" check will start firing.
2. **Buttons without a nowrap-guaranteeing class.** Of about 1,461 button-like controls, about 635 padded ones carry none of `btn / edify-action-button / school-record-action / edify-tab-btn / whitespace-nowrap / truncate`. These include 135 `edify-primary-solid`, 27 `btn-premium-primary`, 12 `btn-premium-secondary` and 175 plain `inline-flex`. The top files are `partials/professional_development/request_form.html` 22, `partials/messages/conversation.html` 13, `pages/messages/new.html` 13, `partials/leave/impact_panel.html` 12 and `pages/schools/index.html` 12. **No global `button` nowrap rule exists.**
3. **`pages.css:552`** `.pl-dashboard-stack .pl-urgent-table .edify-action-button { white-space: normal }` is an explicit opt-in to wrapping. It is currently overridden by the table one-line rule, so it is dead but misleading.
4. **Tabs in drawers:** the tab nowrap and sizing rule (platform.css:915-960) is `main`-scoped. Drawer tabs (1 drawer template today) and `.status-pill`/`.badge` nowrap (platform.css:1198) do not apply in `#drawer-container`.
5. **Drawer typography drift:** the 338 × `text-[12px]` and 145 × `text-[13px]` in `*drawer*.html` bypass the `main`-scoped remap (consistency.css:20). The same utility is 13px on the page and 12px in the drawer.
6. **Unnecessary scrolling:** `data-edify-table-width="standard"` forces `min-inline-size: max(44rem,100%)` below 64rem, so narrow 2-5 column tables always scroll on a phone.
7. **Desktop truncation contradicts "scroll":** at 64rem and above, `micro-ux.js` fitTables plus consistency.css:3836-3940 ellipsise cells instead of scrolling. The docstring "No table content is folded or truncated" in `TableColumnBudgetTest` disagrees. **Decide before building.**
8. **17 tables without a server-side scroll wrapper** (section 5). A few sit in `overflow-hidden` cards (`pages/admin/audit_log.html:19`, `pages/districts/detail.html:49`), so before `micro-ux.js` runs (or after an HTMX swap, before re-enhancement) the table overflows or is clipped.
9. **`sp-visually-hidden`** (`partials/ssa/performance_workspace.html:254`) is not in the JS exclusion list, so an empty, focusable `role=region` wrapper is created around a hidden table.
10. **Dead CSS that contradicts the goal:** `components/record-views.css` (not loaded) has `white-space: normal !important` on record-table thead. It is harmless now, but delete it rather than revive it.
11. **Font sizes below the 12px floor** in `pages/*.css` and `components/*.css`: 79 declarations (section 3). The worst are `.58rem`/9.3px in ia-master.css:283 and team-target-distribution.css:35/53, `.5625rem`/9px in analytics-dashboard.css:1265, and 10px at analytics-dashboard.css:87/612.
12. **Inverted type ladder** at ≤36rem and ≤22.5rem (title ≤ body), from mobile-micro-ux.css:719-778.
13. **Headers at fixed large sizes on mobile:** page h1s are clean (220 of 221 use the token). Leftovers: `pages/system_health/index.html` has 14 × `<h3 class="text-[22px] font-extrabold">` (lines 48-295, 1085, 1118), `pages/admin/index.html:82-109` has 4 × `text-[22px]`, `partials/dashboards/cceo/week.html:24` and `pages/core_schools/detail.html:16` 22px, and `pages/documents/canonical_document.html:41,87,102,142` has 24-30px (standalone). Among CSS heroes, `login.css:192` (48-65px) and `hcos-workspace.css:43` (32-56px) scale with vw. The `text-[36-44px]` template hits are empty-state icons sized in `em`, so they are harmless.
14. **Button font is hard-coded:** mobile-micro-ux.css:433/623 set `font-size: 0.8125rem !important` on every action button, bypassing `--edify-text-label-size`. A token change will not reach buttons.
15. **Four spellings per breakpoint** (`63.999rem`, `63.9375rem`, `1023.98px`, `64rem` max) and six in the 768 band. Off-by-fraction gaps between `max-width:47.99rem` and `min-width:48rem` are safe, but `max-width:48rem` combined with `min-width:48rem` (23 and 17 uses) **overlap at exactly 768px**. That is the tablet-768 project's width.

---

## 10. Prioritised shared-CSS changes (most coverage, least per-page editing)

Put new rules in the **last layer that already owns the property**: mobile-micro-ux.css (loaded after consistency) or interactions.css. Scope them `:is(main, .drawer-surface, .edify-popup-dialog__surface, [role="dialog"])`, not `main`. Rebuild, bump `?v=` (keep the micro-ux css/js keys equal), and commit `static/build/css`.

1. **One-line controls, platform-wide (about 1,000 elements, zero template edits).** Add `white-space:nowrap; flex-shrink:0` to `:is(main, .drawer-surface, [role=dialog]) :is(button, [role=button], [role=tab], summary, a):is(.btn, .edify-action-button, [class*="btn-premium"], .school-record-action, .edify-primary-solid, .edify-tab-btn, [class*="rounded-control"], .edify-pagination__control, [role=tab])`. For badges, `.edify-badge, .status-pill, .edify-status-badge, .badge` get `white-space:nowrap; max-inline-size:100%; overflow:hidden; text-overflow:ellipsis`. **Delete** components.css:31-33 (`white-space:normal; overflow-wrap:anywhere`) and pages.css:552. The e2e check to keep green is the `.edify-badge` overflow check in the route audit.
2. **Extend the `main`-only rules to drawers.** The type remap (consistency.css:20-45), tab contract (platform.css:903-1011) and badge contract (platform.css:1198) should use the shared scope above. This removes the 12px/13px drift across the 84 drawer templates.
3. **Tables scroll, never shrink or wrap, below 64rem.** Replace the `44/56/68rem` width tiers with `min-inline-size:100%` plus `inline-size:max-content`, so small tables fit and wide ones scroll. The test strings in `test_platform_table_system` must be updated with it. Make `.edify-table-scroll-region` CSS-first: add the scroll wrapper rule to `:is(main, .drawer-surface) :is(.overflow-x-auto, [data-table-scroll-region], [class*=table-wrap], [class*=table-scroll], .edify-record-table-wrap)` at every width. Today, outside `main`, the substring rule at platform.css:873 is the only thing that makes wrappers scroll at desktop widths, and it does not reach `.drawer-surface`. Add server-side wrappers to the 17 tables in section 5 (a small, mechanical edit).
4. **Generic sticky identity column.** For `:is(.edify-table-scroll-region, [data-table-scroll-region], .overflow-x-auto) > table :is(thead th:first-child, tbody > tr > :first-child)`, and preferably targeting `[data-record-title], th[scope=row]`, apply `position:sticky; inset-inline-start:0; z-index:1; background: var(--edify-frozen-surface)`, with `thead` at z 2. Relax consistency.css `inline-size:100%` on the identity column while the region overflows (e.g. `max-inline-size: min(60vw, 20rem)` below 64rem). Reuse `.edify-frozen-cell`, which already has the right tokens.
5. **Decide on the desktop truncation mode** (micro-ux.js:588-1110, consistency.css:3836-3940). If the goal is "scroll, never truncate", default it off (inverting the check into an opt-in with `data-table-fit="truncate"`) and update `TableColumnBudgetTest`. This is one switch that changes about 280 tables.
6. **Drawer as a full-height sheet below 48rem.** Add one final block after drawers.css:2253-2275, using `inset: auto 0 0 0; inline-size:100%; max-block-size:100svh; block-size:100svh` (or `calc(100svh - env(safe-area-inset-top))`), radius on the top corners only, `padding-bottom: env(safe-area-inset-bottom)` on `.drawer-footer`, and sticky header and footer, which already exist. **This requires the owner's sign-off** and edits to `test_floating_drawer.py`, `test_design_system_contract.py:207` and `e2e/compact-drawers.spec.js` (the ±2px centring at 390).
7. **One type scale.**
   (a) Fix the inverted phone tiers in mobile-micro-ux.css:719-778 so that title ≥ body.
   (b) Route the button font through `var(--edify-text-label-size)` (mobile-micro-ux.css:433/623).
   (c) Add a remap for `text-[14px]`→body/title and `text-[16px]`/`text-[18px]`→heading/card-heading, using the same bridge pattern as consistency.css:20. That covers about 600 more utilities without touching templates; keep `[class~="text-[18px]"]`, which a test pins.
   (d) Extend the lint glob to `static/css/**/*.css` and fix the 79 sub-12px declarations in `pages/`, `components/` and `interactions.css`.
   (e) Retire the legacy `--text-*` tokens in custom.css.
8. **One breakpoint vocabulary.** Standardise on `48rem` and `64rem` (plus `36rem` and `80rem`), written as `max-width: 47.99rem` / `min-width: 48rem` and `max-width: 63.99rem` / `min-width: 64rem`, and remove the `max-width:48rem`/`min-width:48rem` overlap at 768px. Keep the three strings that `test_shared_responsive_contract_covers_mobile_and_tablet` pins, or update the test.
9. **Page-level overflow guard.** Add `main.edify-workspace { overflow-x: clip }` only after items 1-4 land. Otherwise it hides the defects it should expose. Add a `main.scrollWidth` assertion to `ui-design-audit` and the route audit, next to the `documentElement` check.
10. **Page header on phones.** 212 hand-rolled headers already share `.edify-page-header`. For phones, add a single rule in mobile-micro-ux.css below 48rem: `__controls {inline-size:100%; flex-wrap:nowrap; overflow-x:auto}` with `nowrap` children. Also migrate the 14 `text-[22px]` h3s in `system_health/index.html` and the 4 in `admin/index.html` to the heading token. This is the only per-page editing in the plan.
11. **Spacing.** Adopt `--edify-space-*` inside new shared rules only. The about 778 raw px spacing declarations and 3,461 fractional Tailwind spacing utilities are too numerous for this pass. Remap only the 3 page-edge rhythms, which the gutter and canvas rules already own.

Low-risk cleanups to include: delete `static/css/components/record-views.css` (unloaded), and dead `.kpi-strip*` / `.edify-kpi*` rules once their pinning tests are retired; add `.sp-visually-hidden` to the micro-ux.js exclusion list; wire `components/mobile_filter_sheet.html` or remove it.
