# Responsive, accessibility, and performance report — 21 August 2026

## Responsive result

All 372 rendered surfaces inherit or declare the platform responsive contract. Nonvisual mutation endpoints are marked not applicable rather than falsely scored as pages.

| Area | Mobile | Tablet | Desktop / large desktop |
|---|---|---|---|
| Shell/navigation | safe-area-aware bottom navigation and full-screen search | sidebar/canvas transition | stable sidebar and topbar |
| Page headers | stack, wrap actions, no fixed lead basis | deliberate intermediate stack | lead/actions align in canonical band |
| KPI tray | two compact columns, no horizontal carousel | two/three columns by container | up to six equal cards |
| Tables | fit, horizontal scroll, or record-card transformation | protected key columns and scroll | full operational columns |
| Forms | 48px text controls, full-width actions where needed | grouped fields reflow | compact governed control height |
| Drawers/modals | full-screen or bounded sheet with safe-area padding | bounded sheet/dialog | centered dialog or governed side sheet |
| Charts/maps | resize contract and reduced dense labels | responsive plot region | complete legend/context |

Automated checks cover header stacking markers, adaptive table enhancement, drawer geometry, sticky actions, filter sheets, chart/map resize rules, wrapping, and page-level overflow guards. Orientation, hardware keyboard, and physical safe-area behavior remain part of the user-authorized browser/device evidence pass.

## Accessibility result

The code-controlled result is **WCAG 2.2 AA contract pass** with manual critical-workflow verification still required for final conformance language.

| Requirement | Result |
|---|---|
| Semantic landmarks and heading hierarchy | governed shell/header patterns; template tests pass |
| Labels and accessible names | shared form/search/navigation contracts; focused feature tests pass |
| Keyboard and focus | visible focus, modal/drawer focus contracts, no hover-only row actions |
| ARIA tabs and segmented controls | differentiated and source-tested |
| Dynamic state announcements | shared alert/status/live-region primitives catalogued |
| Duplicate/dangling IDs | component/card identity tests pass |
| Contrast | semantic token tests and agreement contrast tests pass |
| Touch targets | 44px platform target / 48px text controls enforced |
| Reduced motion | shared and component-specific media rules pass |
| Zoom/wrapping | fluid widths, wrapping, and no unconditional large fixed widths in templates |

No Critical or High accessibility finding remains in the inventory. Screen-reader sequence, zoom at 200/400%, hardware keyboard, and focus behavior for every critical workflow require the authenticated browser/device pass before a formal independent WCAG certification claim.

## Performance result

| Change | Effect |
|---|---|
| Ten template style blocks removed | CSS parses once from cacheable stylesheets rather than being repeated in HTML/HTMX swaps |
| Base CSS moved out of every full response | smaller repeated HTML and one governed cached foundation |
| Regional map CSS removed from HTMX partial | repeated map swaps no longer inject/reparse a style block |
| Help print and agreement CSS externalized | cacheable exports; no private palettes |
| Priority milestones use `content-visibility: auto` | off-screen layout/paint deferred without changing DOM order |
| Scoped feature styles retained | large admin/help/calendar/document styles are not added to unrelated pages |
| KPI cap | no hidden carousel or surplus metric DOM; maximum six desktop, two compact mobile |
| No business/query rewrite | data scope, arithmetic, permissions, and service ownership unchanged |

Chart instance counts and query shapes were not increased by this remediation. The change is presentation-only. The full application suite remains the guard for query/business regressions; layout-shift and real-device payload measurements belong to the final authenticated browser evidence pass.

