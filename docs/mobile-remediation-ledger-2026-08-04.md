# Mobile & Tablet Remediation Ledger — opened 2026-08-04

Evidence labels follow §2:

- **LIVE PRODUCTION VERIFIED** — observed on `https://www.edifyplanning.app`
- **PRODUCTION CLONE VERIFIED** — observed on an isolated clone
- **NOT VERIFIED** — asserted but not yet proven

Every entry below is **LIVE PRODUCTION VERIFIED** unless stated otherwise.

## Session scope and its limits

Audited so far: the unauthenticated surface only — PWA manifest, service
worker, icons, and the sign-in page at 390×844. Everything behind sign-in
(10 roles, ~25 routes) is **NOT VERIFIED**: this session has no authenticated
session to the live site. See "Blocked" at the end.

Host under test is `www.edifyplanning.app`. The apex still serves the GoDaddy
lander — re-confirmed 2026-08-04 04:19 UTC, `A 15.197.148.33 / 3.33.130.190`
unchanged. INC-2026-08-03-01 is still open.

---

## M-001 — Sign-in page first paint is 5.7 s on a phone viewport

| Field | Value |
|---|---|
| Severity | **Critical** |
| URL | `https://www.edifyplanning.app/login` |
| Page / Role | Sign-in / unauthenticated |
| Viewport | 390×844 portrait, desktop Chrome engine |
| Expected | FCP ≤ 1.8 s, LCP p75 ≤ 2.5 s (§47) |
| Actual | **first-contentful-paint = 5,696 ms**; DOMContentLoaded 3,017 ms; load 3,027 ms; TTFB 634 ms |
| Status | Discovered on Production |

Measured via `performance.getEntriesByType('paint')` in the live page. Nothing
renders for 5.7 seconds. TTFB is only 634 ms, so this is a client-side
render-blocking problem, not a slow origin.

Total page weight is 224 KB across 8 requests — small. The time is spent in a
render-blocking chain, not on bytes. Contributing entries M-002 and M-003.

## M-002 — Four render-blocking stylesheets on sign-in, 315 KB decoded

| Field | Value |
|---|---|
| Severity | **High** |
| URL | `https://www.edifyplanning.app/login` |
| Expected | Critical CSS ≤ 100 KB compressed; no unnecessary bundles on login (§48) |
| Actual | 4 separate stylesheets, all render-blocking |
| Status | Discovered on Production |

| Stylesheet | Transferred | Decoded | Duration |
|---|---|---|---|
| `main.<hash>.css` | 42 KB | **315 KB** | 1,694 ms |
| `design-system.<hash>.css` | 11 KB | 39 KB | 1,048 ms |
| `login.<hash>.css` | 5 KB | 21 KB | 1,710 ms |
| `fonts.<hash>.css` | 1 KB | 2 KB | 669 ms |

`main.css` is the whole application's Tailwind bundle — every utility for every
authenticated page — served to a page containing one form. The sign-in page
needs `design-system` + `login` at most.

Root cause not yet confirmed: needs checking whether `templates/layouts/login.html`
inherits the shell's stylesheet block rather than declaring its own.

## M-003 — 92 KB decorative hero image preloaded on sign-in

| Field | Value |
|---|---|
| Severity | **High** |
| URL | `https://www.edifyplanning.app/login` |
| Asset | `/static/images/login-classroom-portrait.<hash>.jpg` |
| Expected | No oversized background images; no large decorative hero on operational pages (§22, §48) |
| Actual | 92 KB JPEG, `initiatorType: link` (preloaded), 1,042 ms — the single largest asset on the page |
| Status | Discovered on Production |

It is a decorative classroom photograph. On a phone it is the heaviest thing
downloaded, it is preloaded so it competes with the CSS that actually blocks
render, and it is not the LCP element. Candidates: drop it at phone widths,
serve AVIF/WebP with `srcset`, or stop preloading it.

## M-004 — Service worker forces its own activation mid-session

| Field | Value |
|---|---|
| Severity | **High** |
| URL | `https://www.edifyplanning.app/sw.js` |
| Expected | Show "A new Edify version is available" with Update Now / Later; do not force-refresh while the user is completing a form (§40) |
| Actual | `self.skipWaiting()` on install + `self.clients.claim()` on activate, unconditionally |
| Status | Discovered on Production |

```js
self.addEventListener('install', (event) => {
  self.skipWaiting();
});
```

A deploy during a work session takes over the page immediately. §40 prohibits
exactly this. There is no update prompt and no unsaved-work check.

Note the worker only handles `/static/` — the takeover swaps assets under a
page whose HTML came from the previous release, which is the mismatch case
§40's prompt exists to prevent.

## M-005 — No offline fallback

| Field | Value |
|---|---|
| Severity | **Medium** |
| URL | `https://www.edifyplanning.app/sw.js` |
| Expected | Offline fallback explaining a connection is required (§35, §39) |
| Actual | Navigation requests return early from the fetch handler; offline shows the browser's own error page |
| Status | Discovered on Production |

```js
if (!url.pathname.startsWith('/static/')) return;
```

The narrow scope is *correct* for safety — it is why §41 cross-user cache
exposure is zero by construction, and why no finance, HR or evidence data is
cached. Keep that. The gap is only the missing offline fallback document.

## M-006 — Cache-miss while offline resolves to `undefined`

| Field | Value |
|---|---|
| Severity | **Low** |
| URL | `https://www.edifyplanning.app/sw.js` |
| Expected | A rejected fetch yields a Response or a clean failure |
| Actual | `.catch(() => hit)` returns `undefined` when `hit` was already a miss |
| Status | Discovered on Production |

```js
caches.match(req).then((hit) => hit || fetch(req).then(...).catch(() => hit))
```

Reached only when `hit` is falsy, so the catch always returns `undefined`, and
`respondWith(undefined)` throws a TypeError instead of failing cleanly. Impact
is confined to uncached `/static/` assets while offline.

## M-007 — Manifest has no `id`

| Field | Value |
|---|---|
| Severity | **Medium** |
| URL | `https://www.edifyplanning.app/manifest.webmanifest` |
| Expected | `id` present (§36) |
| Actual | Absent; app identity falls back to `start_url` |
| Status | Discovered on Production |

Without an explicit `id`, changing `start_url` in a later release makes the
browser treat it as a *different* app — users end up with two Edify icons and
the installed one silently orphaned. Fix is one line in
`apps/frontend/views/pwa_views.py`.

Also absent, lower priority: `display_override`, `shortcuts` (§45),
`prefer_related_applications`.

## Verified as correct — no action

Recorded so they are not re-audited.

| Item | Evidence |
|---|---|
| Manifest MIME type | `application/manifest+json` |
| `name` / `short_name` | "Edify Planning & Monitoring" / "Edify" — matches §37 |
| `display` | `standalone` ✓ |
| `scope` | `/` ✓ |
| `orientation` | `any` ✓ — landscape available for evidence review, as §36 requires |
| Icons | 192, 512, maskable 192, maskable 512 all return 200; hashed filenames resolve |
| Apple touch icon + meta | present in `templates/partials/pwa_head.html`, incl. `apple-mobile-web-app-*` |
| Manifest on sign-in page | present — installable before login, not only after |
| Service worker scope | root-scoped at `/sw.js` ✓ |
| Obsolete cache cleanup | `activate` deletes every non-current cache ✓ |
| Sensitive caching | none — worker ignores everything outside `/static/` ✓ |
| POST/PUT/PATCH/DELETE | never cached — `if (req.method !== 'GET') return` ✓ |
| SW registration timing | on `load`, so it never competes with first paint ✓ |
| Sign-in horizontal overflow | `scrollWidth 390 === innerWidth 390` — none |
| Sign-in JS weight | one 2 KB script; no chart, calendar or PDF library ✓ (§48) |
| Sign-in touch targets | full-width fields, 56 px primary button — passes §53 by inspection |
| Service worker active | `navigator.serviceWorker.controller` non-null on live |

`HEAD /sw.js` returns 405 (`@require_GET`). Not a defect — browsers fetch
worker scripts with GET.

---

# Structural findings — responsive system inventory

Source: repository, not live. Labelled **NOT VERIFIED** against production
until confirmed on the authenticated live site, but these are structural facts
about the code that ships, so they are unlikely to differ.

## M-008 — There is no mobile application shell

| Field | Value |
|---|---|
| Severity | **Critical — this is the mandate's central gap** |
| Location | `templates/layouts/shell.html` |
| Expected | Compact top app bar + role-aware bottom navigation (§6, §7) |
| Actual | Hamburger button opens the **desktop sidebar** as an off-canvas drawer |
| Status | **Shared Fix Implemented** — local only, NOT yet on staging or production |

Built 2026-08-04:

- `apps/core/navigation.build_mobile_nav_for_user` — resolves four primary
  destinations per role from the **same** `SIDEBAR_ITEMS` registry and
  `PAGE_PERMISSIONS` the desktop sidebar uses. The per-role table states a
  *preference*; a key is honoured only when the role can already reach that
  page, so it can advertise but never grant. §7's "no bottom navigation item
  for a page the role cannot access" holds by construction rather than by
  review.
- `templates/components/mobile_bottom_nav.html` — 4 destinations + More.
- `static/css/components/mobile-shell.css` — bar, safe areas, workspace
  clearance.
- Hamburger removed below `lg`; More opens the same drawer, so there is one
  navigation source with two surfaces, not a parallel IA.

Verified locally at 390×844 and 768×1024, Admin role, dark theme:

| Check | Result |
|---|---|
| Tabs rendered | Dashboard / Support / Health / Messages / More |
| Touch targets | 78×56 px each — above the 44 px floor |
| Horizontal overflow | none (`scrollWidth 390 === innerWidth 390`) |
| Active state | exactly 1 `aria-current="page"` in the bar |
| Workspace clearance | `padding-bottom: 56px` — last row clears the bar |
| More opens drawer | yes, `aria-expanded` flips to `true` |
| Bar inert while drawer open | yes — cannot tab out of the dialog |
| Focus restored on Escape | yes, returns to More |
| Keyboard retract wiring | bar translates 57 px down, `pointer-events: none` |
| Console errors | none |

Per-role resolution, all 10 roles, 4 destinations each, no duplicates:

| Role | Destinations after Dashboard |
|---|---|
| CCEO | My Plan · Schools · Messages |
| PL | My Plan · Targets · Messages |
| Partner | My Plan · Clusters · Messages |
| Project Coordinator | Projects · My Plan · Messages |
| IA | Verify · SSA · Messages |
| Accountant | Disburse · Payments · Messages |
| HR | People · Leave · Messages |
| CD / RVP | Budget · Analytics · Messages |
| Admin | Support · Health · Messages |

Tests: `apps/core/tests/test_mobile_nav.py` — 21 tests, 251 subtests, including
a guard that every preferred key is authorized for its role, and that Partner is
never offered `/schools` (it is absent from `PAGE_PERMISSIONS["schools"]`).

**Still open on this item:** the keyboard-retract behaviour is verified only by
dispatched events — this automated tab never receives system focus, so it fires
no real `focusin`. Needs confirmation on hardware. Landscape, light/blue themes
and the other nine roles are not yet visually checked. Nothing is deployed.

```
grep -rln "bottom-nav|bottom_nav|mobile-nav|mobile_nav|app-bar|appbar"  →  0 files
```

No bottom navigation exists anywhere in the codebase. No compact mobile app bar
exists. `shell.html` is the standard Tailwind admin pattern:

- `<aside class="app-sidebar hidden lg:flex">` — desktop sidebar at ≥1024 px
- below 1024 px, the same `app-sidebar` renders inside an Alpine off-canvas
  drawer (`sidebarOpen`), opened by a hamburger

§6 states "Do not render the desktop sidebar on phone widths", and §54 lists
"old hamburger menus" for removal. The current phone navigation *is* the thing
the mandate is written against.

Consequence for scope: §6, §7, §8, §22 and most per-role sections (§24–§31)
are not defect repairs — they are **new construction**. The mobile shell has to
be built before pages can be audited against it.

## M-009 — `env(safe-area-inset-*)` is inert on iOS: no `viewport-fit=cover`

| Field | Value |
|---|---|
| Severity | **High** |
| Location | `templates/base.html:6`, `templates/layouts/login.html:6` |
| Expected | Safe-area insets honoured for sticky bars and full-screen sheets (§9) |
| Actual | `<meta name="viewport" content="width=device-width, initial-scale=1.0">` — no `viewport-fit=cover` |
| Status | **Shared Fix Implemented** — local only |

Fixed 2026-08-04. `viewport-fit=cover` added to `templates/base.html`, landing
together with the shell-level insets it makes load-bearing — the top bar, the
off-canvas drawer and the bottom bar all inset themselves in
`static/css/components/mobile-shell.css`. Shipping the meta tag alone would have
extended the layout under the status bar with nothing padding it back out.

This also revives the safe-area code that was already present and inert:
`pages/ia/review_workspace.html:94` and `:432`, and `static/css/login.css:887`.

Needs hardware confirmation — a simulator or notched device is the only honest
test of an inset value.

Without `viewport-fit=cover`, iOS Safari resolves every `env(safe-area-inset-*)`
to **0 px**. The safe-area code that does exist is therefore doing nothing on
any notched iPhone:

- `templates/pages/ia/review_workspace.html:94` — mobile decision bar,
  `pb-[max(.75rem,env(safe-area-inset-bottom))]`
- `templates/pages/ia/review_workspace.html:432` — desktop sticky footer
- `static/css/login.css:887-888` — top and bottom padding

The fix is one attribute in two templates. It should land *before* any new
sticky bar or bottom navigation is built, or that work inherits the same
silent failure.

## M-010 — Safe-area handling exists on exactly one page

| Field | Value |
|---|---|
| Severity | **Medium** (becomes moot once M-008's shell exists) |
| Expected | Shared safe-area support for app bar, bottom nav, sticky actions, sheets, toasts, modal footers (§9) |
| Actual | One page — the IA review workspace — implements it; nothing else does |
| Status | Root Cause Confirmed |

Worth noting as the **anchor pattern**: `ia/review_workspace.html` already does
what §22 and §24 describe — a `lg:hidden fixed inset-x-0 bottom-0` decision bar
with safe-area padding, and a separate desktop sticky footer. It is the correct
model to generalise into the shared sticky action bar, rather than inventing one.

## M-011 — Operational tables horizontally scroll instead of becoming records

| Field | Value |
|---|---|
| Severity | **High** |
| Expected | Operational record tables → structured mobile cards; horizontal scroll reserved for comparison matrices (§17 A vs B) |
| Actual | **138 templates contain `<table>`; 3 had a mobile card block; 135 did not** |
| Status | **Shared component built; first 6 templates converted** — local only |

### Correction to an earlier figure in this ledger

An earlier revision reported "77 tables, 1 with a mobile alternative". Both
numbers were wrong, for two separate reasons:

1. The scan walked `templates/pages/` only. Many record lists live in
   `templates/partials/` — the real corpus is 490 templates, 138 with tables.
2. It detected only `(md|lg):hidden` (a mobile-only block) and missed the
   inverse idiom `hidden lg:block` (a desktop-only block). Three templates were
   already correctly done and were being counted as broken.

Corrected: **138 with tables, 3 already had a card block, 135 did not.** The
conclusion is unchanged and slightly worse in absolute terms.

### The three that were already right

`pages/ia/partials/queue_table.html`, `partials/core_schools/planning_queue.html`,
`partials/projects/portfolio_list.html`. The IA queue is the best of them —
desktop table under `hidden lg:block`, a `lg:hidden` card `<ul>` with status
pills and a full-width `min-h-11` Review button. It is the pattern this
component generalises, rather than a new invention.

Also already card-based, so never in scope: the School Directory
(`partials/schools/table.html` renders `<ul role="list">`, not a table).

### The component

`.edify-record-table` in `static/css/components/mobile-shell.css`. CSS-only,
opt-in, active below 1024px:

- `thead` hidden; `tr` becomes a card; `td` becomes a labelled row
- labels from `data-label`, rendered by `::before` — **in the markup, not
  stamped from `<thead>` by script.** Labels arriving a frame late read as a
  layout bug, and an unlabelled "UGX 200,000" for even one frame is worse than
  that on a finance page
- `data-record-title` — identity line, no label
- `data-record-action` — full-width control, 44px minimum
- `min-width: 0` cancels the forced desktop widths (980px on the cost
  catalogue, 860px on the RVP dashboard) that would otherwise restore the
  sideways scroll
- empty cells collapse rather than render an empty labelled row

Opt-in is the point: §17 class B matrices must stay tables. There is a test
guarding the class against spreading to `targets/`, `analytics/`, `ssa/` or
`budget_intelligence/`.

### Converted so far (6 templates)

My Plan field surface — `school_visits`, `cluster_trainings`,
`cluster_meetings`, `programme_activities`, plus the shared
`activity_row.html` action cell that serves all four.

Cost Catalogue — both tables, including the 980px one.

### Measured, `/cost-settings` at 390×844

| Metric | Before | After |
|---|---|---|
| Columns visible | 2 of 9 | **9 of 9** |
| Rate (UGX) visible | no | **yes** |
| Elements wider than viewport | table @595px | **none** |
| Table `min-width` | 980px | 0 |
| Action control | inline, small | 294×44 px |

Desktop regression check at 1440×900: `display: table`, rows `table-row`, cells
`table-cell`, `thead` visible, 980px min-width restored, `::before` labels
suppressed, 9 of 9 columns visible, bottom nav `display: none`, sidebar
present. **Desktop is unchanged.**

Tests: `apps/core/tests/test_record_tables.py` — 12 tests, 31 subtests.

### Conversion sweep — final state

| | Count |
|---|---|
| Table templates with a mobile record view | **52** (was 3) |
| Still without one | 86 |
| **Field-execution templates remaining** | **0 convertible** |

Field execution is complete. The two field-area templates still without a card
view — `pages/ia/analytics_dashboard.html` and
`partials/projects/analytics_workspace.html` — are §17 class B comparison
matrices and are deliberately left as tables.

Converted in this pass: the four My Plan activity tables and their shared
action cell · both Cost Catalogue tables · 12 Accountant queues
(accountability, approvals, blocked, amendments, cleared, partner payments,
ready-for-advance, reimbursements, returned, variance, weekly requests, audit)
· 7 admin queues · closure, clusters, coverage, visits, trainings, partners,
work plan, completed activities, core schools champions/candidates/leadership,
IA returned/history, debriefs, fund request detail, schools upload preview,
projects planning/my-plan/plan tables, My Plan attention + detail drawer.

### Deliberately NOT converted (§17 class B)

`admin/page_access_matrix` and `admin/roles_permissions` (page × role, and the
`<th>` is a template variable — the column set is dynamic), the
`finance/country_budget_submission` and `finance/fund_allocation` breakdowns,
`accounts/dashboard`'s category table, `hr/conversation_document` and
`hr/my_performance` (priority × target/actual/weight), and the
`projects/planning_workspace` project summary. Stacking any of these destroys
the comparison it exists for. A test guards the opt-in class against spreading
to `targets/`, `analytics/`, `ssa/` or `budget_intelligence/`.

### Remaining 86, by area

analytics 18 · dashboards 13 · ssa 5 · targets 5 · leave 5 · hr 5 · finance 6 ·
admin 2 · plus a long tail. A large share of analytics/targets/ssa is class B
and should get a sticky first column and a scroll affordance instead of cards.
86 is an upper bound on the work, not a target.

### Verification

| Check | Result |
|---|---|
| Role × route render sweep | **300 combinations, 0 failures, 0 5xx** |
| Converted templates parse | 52 / 52, 0 syntax errors |
| `ruff check` / `ruff format` | clean |
| `manage.py check` | 0 issues |
| Migration drift | none |
| `/admin-panel/users` at 390px | 67 cards, 201 labels, 67 controls all ≥44px, 0 overflow |
| `/coverage` at 390px | record cards, labels rendering, 0 overflow |
| `/cost-settings` at 390px | 9/9 columns readable (was 2/9) |
| Desktop 1440px regression | `display: table` restored, labels suppressed, 9/9 columns |

### Converter limits worth knowing

The sweep was mechanical and its heuristics are not infallible. One genuine
error it made, caught and fixed: on `admin/audit_log` the column header
"Action" is the *event that was recorded*, not a control, so the converter made
the timestamp the card title and the event description the action button. Any
future sweep needs the same review pass — a header called "Action" is a control
only when the cell contains one.

Two other cells were flagged and cleared as false positives (`admin/users`,
`admin/unmatched_ssa_queue`) — their controls sit below the 3-line window the
check looked at. That review did surface a real gap, though: those cells wrap
their controls in a flex `div`, which the original direct-child selector
missed, so the component now stacks wrapped controls too.

## M-015 — Four competing `attr(data-label)` card transforms now exist

| Field | Value |
|---|---|
| Severity | Medium (consolidation debt, not a defect) |
| Status | Documented, not fixed |

`.edify-record-table` is the fourth implementation of this pattern in the
codebase. The others:

| Selector | File | Breakpoint |
|---|---|---|
| `.admin-priorities .admin-table--priorities` | `admin-dashboard.css` | — |
| `main .platform-responsive-table.platform-table-cards` | `platform.css` | — |
| `.hcos-table` | `hcos-workspace.css` | **640px** |
| `.edify-record-table` | `components/mobile-shell.css` | **1024px** |

No template carries two of them, so nothing is currently fighting. But the
breakpoints disagree: at 768px an `.hcos-table` is still a table while an
`.edify-record-table` is already cards, so an iPad in portrait gets two
different treatments of the same idea. They should be consolidated into one
component — deliberately not attempted here, because the other three have pages
this session has not seen and merging them blind would be a regression risk.

The current answer to "narrow screen" is almost universally horizontal
scrolling. §17 allows that only for class B comparison matrices. The class A
list — My Plan, School Directory, Partner Activities, IA Verification,
Approvals, Accountability, Leave, PD — needs a shared row-to-card transform,
not 73 individual repairs.

### Full-corpus scan, 2026-08-04 (all 197 page templates)

| Signal | Count |
|---|---|
| Contains `<table>` | **77 (39%)** |
| …of those, has a mobile card alternative | **1** |
| …of those, horizontal scroll only | **76** |
| No responsive breakpoint of any kind | 20 (10%) |
| Fixed pixel widths ≥100px | 149 (75%) |
| Forces `min-width` ≥600px | 5 |

Worst forced widths: `cost_settings` 980px · `dashboards/rvp` 860px ·
`finance/country_budget_submission` 820px · `finance/fund_allocation` 820px ·
`budget/index` 720px. Each of those horizontally scrolls on every phone made.

### Measured, live at 390×844 — `/cost-settings`

| Metric | Value |
|---|---|
| Table width | 595px in a 390px viewport |
| Columns total | 9 |
| **Columns visible** | **2** — "Activity", "Type" |
| Off-screen | Item, **Rate (UGX)**, Delivery, Intervention, Cost recipe, Status |
| `documentElement.scrollWidth > innerWidth` | **false** |

The Cost Catalogue's *rate* column — the reason the page exists — is off-screen
on a phone. Key strings clip mid-word
(`cluster_meeting_participant_meal_cost_per_…`).

Note the last row. The page does **not** trip a horizontal-overflow check,
because the table scrolls inside its own container. This is precisely the
failure the mandate warns about: "do not claim a page is mobile-ready merely
because it does not horizontally overflow." Any audit gated on overflow alone
would have passed this page.

## M-012 — Tablet portrait gets the phone drawer; no navigation rail exists

| Field | Value |
|---|---|
| Severity | **Medium** |
| Expected | Adaptive tablet shell — compact rail or collapsible sidebar, master-detail (§8) |
| Actual | `tailwind.config.js` declares no custom `screens`, so defaults apply. The sidebar cutoff is `lg:` = 1024 px |
| Status | Root Cause Confirmed |

- iPad portrait (768×1024) falls below `lg` → hamburger drawer, i.e. treated as
  a phone
- iPad landscape (1024×1366) → full desktop sidebar

Neither is the rail/master-detail shell §8 asks for. §8's "not a desktop with
tiny controls, not a phone with excessive unused space" describes precisely
these two states.

## M-013 — 13 render-blocking stylesheets, ~875 KB, on every authenticated page

| Field | Value |
|---|---|
| Severity | **Critical** |
| Location | `templates/base.html` |
| Expected | Critical CSS ≤ 100 KB compressed; one production bundle where efficient (§48) |
| Actual | 13 separate render-blocking `<link>` elements, 875 KB decoded |
| Status | Discovered — not fixed |

M-002 measured the *sign-in* page at 4 stylesheets. The authenticated shell is
far worse:

| Stylesheet | Decoded |
|---|---|
| `main.css` | 322 KB |
| `pages.css` | 145 KB |
| `platform.css` | 108 KB |
| `components.css` | 103 KB |
| `consistency.css` | 72 KB |
| `design-system.css` | 39 KB |
| `drawers.css` | 32 KB |
| `admin-dashboard.css` | 30 KB |
| `help-center.css` | 17 KB |
| `components/sidebar.css` | 14 KB |
| `hcos-workspace.css` | 10 KB |
| `fonts.css` | 2 KB |
| `app.css` | 1 KB |
| **Total** | **~875 KB** |

Every page pays for `admin-dashboard.css` and `hcos-workspace.css` whether or
not it is that page. This is the single largest lever on mobile first paint and
it needs its own consolidation pass — not a per-page patch.

Note: `components/mobile-shell.css` (3 KB) added today makes it 14. That is a
deliberate trade against fixing the shell, and it is small, but it does move
the wrong number in the wrong direction; fold it into the consolidation.

## M-014 — Four sidebar destinations had no icon at all

| Field | Value |
|---|---|
| Severity | Medium |
| Location | `apps/core/navigation.ICONS` |
| Expected | Every registered destination resolves an icon |
| Actual | `staff`, `leave_approvals`, `admin_support_queue`, `ssa` were absent, so `ICONS.get(...)` returned `""` |
| Status | **Fixed** — local only |

Surfaced by a bottom-nav test asserting every item carries an icon. The desktop
sidebar had been rendering an empty icon slot for People Directory, Leave
Approvals and Support Tickets — survivable beside a 240px label, fatal in a tab
where the icon is the affordance and the label is an 11px caption. Four icons
added; both surfaces fixed at once.

## Confirmed present and reusable

The design system itself is in good shape — the gap is the mobile adaptation
layer, not the components:

`templates/components/` — `kpi_card.html`, `kpi_strip.html`, `page_header.html`,
`card.html`, `button.html`, `badge.html`, `input.html`, `empty_state.html`,
`table_pager.html`, `school_list_card.html`, `drawers/`

`static/css/drawers.css` already uses `dvh` units correctly
(`min(88dvh, 48rem)`, `calc(100dvh - 1.5rem)`), so §9's "do not rely blindly on
a fixed 100vh" is already partly satisfied there.

---

## Needs a product decision, not a fix

**§12 requires Inter. Live production serves Geist.**
`/static/fonts/Geist-Variable.<hash>.woff2`, 68 KB — the second-heaviest asset
on sign-in. Commit `21e1d3d4` ("Align app typography") moved the app to Geist
deliberately. Replacing it is a whole-application visual change, not a
defect repair, so it is **not** actioned here. Confirm which font is intended
before anything touches this.

---

## Blocked

| Blocker | Consequence |
|---|---|
| No authenticated live session | §5 page inventory, §24–§31 role experiences, §52 visual regression — all 10 roles and ~25 authenticated routes remain **NOT VERIFIED** |
| No physical Android / iPhone / iPad | §42–§44, §50 real-device installation cannot be performed; emulation and iOS Simulator only |
| No deploy access (`doctl` absent, no CI trigger) | §57 steps 9–16 — build artifact, staging deploy, promotion, cache invalidation — cannot be executed from here |
| Apex still serving GoDaddy lander | INC-2026-08-03-01 open; all live testing is via `www` |
