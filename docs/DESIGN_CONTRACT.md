# Edify Design Contract (v1 — premium overhaul)

Every page in this app follows this contract. It is enforced in review; a page
that violates it is not done. Stack: Django (all logic) + HTMX (fragments) +
Tailwind (layout) + Flowbite (components) + ApexCharts (charts) +
FullCalendar (planning calendars) + Alpine (UI state only).

## Page skeleton (in order)

1. `components/page_header.html` — title, one-line purpose, right-aligned actions
2. `components/filter_bar.html` — only if the page filters (GET or HTMX)
3. `components/role_scope_notice.html` — when the data slice isn't obvious
4. `components/kpi_strip.html` — top-level metrics, backend-driven (`kpi_strip_items`)
5. Primary insight area — **2-column** grid (`grid grid-cols-1 lg:grid-cols-2 gap-5`)
6. Supporting area — **max 3-column** grid (`grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4`)
7. Decision / Alert / Action row — `components/action_card.html`, 3-up max
8. Tables/detail — full width

## Hard layout rules

- **Never more than 3 content columns.** KPI Strip is the only exception (it is a strip).
- Major charts: 2-column. A chart never sits in a column narrower than 1/2 page.
- No `lg:grid-cols-4/5/6/7/8/10` for content cards. `lg:grid-cols-12` only as a
  split container whose children span ≥4 (i.e. ≤3 visual columns).
- Mobile: everything stacks to 1 column; tables scroll inside
  `overflow-x-auto`; the page body never scrolls horizontally.
- Cards: `card p-5` (or `p-4` for compact), title `text-[14px] font-semibold
  text-slate-800`, one clear purpose per card. No dead bottom whitespace — if a
  card is thin, merge it; if crowded, split it.

## Charts

- ApexCharts only, mounted via `components/chart_card.html` +
  `{{ options|json_script:"<chart_id>-config" }}`. The base.html initializer
  renders every `[data-apex-config]` mount (and after HTMX swaps).
- Chart options come from the **Django view** as a plain dict (series, labels,
  colors). No data computation in JS.
- Palette: emerald `#10b981`, blue `#3b82f6`, amber `#f59e0b`, rose `#f43f5e`,
  teal `#0ea5a4`, slate `#94a3b8`. Grid lines `#f1f5f9`.
- Always pass `has_data` so the card renders the shared empty state.

## Data honesty

- **Zero mock data.** Every number is a queryset aggregate or an honest empty
  state (`components/empty_state.html`, always with one CTA when actionable).
- No fake trends ("▲ 12% vs Apr"). Show a trend only if the view computes it.
- No dead buttons: every control acts (link, HTMX, submit) or is removed.

## Interactions

- HTMX for filters/tabs/pagination/drawers/form posts; responses are fully
  styled partials. Endpoints enforce the same role scoping as pages.
- Alpine only for open/close/tab/selection state.
- Forms open in drawers (existing `templates/components/drawers` /
  `static/css/drawers.css` patterns) with sticky footer + primary action.

## KPI Strip

- Replace ad-hoc KPI tile grids with `components/kpi_strip.html`
  (`kpi_strip_items` from the view: icon, label, value, helper, variant,
  optional trend). Top of page only.

## Role scoping

- Querysets scoped in the view (existing `resolve_user_scope` /
  `_scoped_schools` / `require_page_permission` machinery). Never hide by CSS.

## Utilities build

- Tailwind utilities are generated: after editing templates run
  `npm run css` (regenerates `static/css/utilities.css` from a template scan).
  Any standard Tailwind class is safe to use once the build runs.
