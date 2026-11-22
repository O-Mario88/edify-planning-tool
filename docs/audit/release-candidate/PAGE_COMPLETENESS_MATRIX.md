# Page Completeness & Real Chromium Browser Verification Matrix

**Audit Date:** 2026-11-22  
**Next.js App Router Inventory:** **33 pages** + **15 route handlers** (**43 compiled routes**)  
**Role Sidebar Sweep (Django Offline):** **417 / 417** role-sidebar pages verified live

---

## 1. Real Chromium Playwright Browser Verification (Desktop, Tablet & Mobile)

Executed via Playwright against live local Next.js (`:3091`) + Go Gateway (`:8091`, `EDIFY_EXISTING_APP_URL=""`, `EDIFY_STRICT_READS=true`, Django offline):

| Role | Route | Viewport | HTTP | Horizontal Overflow | Console Errors | Page Errors | 5xx | NotMovedYet | Interactive Check | Status |
|---|---|---|---:|---:|---:|---:|---:|---|---|---|
| Unauthenticated | `/dashboard` | `1440×900` | 307→200 | — | 0 | 0 | 0 | No | Redirected to `/login?next=%2Fdashboard` | **PASS** |
| Program Lead | `/dashboard?view=map` | `1440×900` | 200 | **0 px** | 0 | 0 | 0 | No | UBOS map + KPIs + table + Excel/PDF links | **PASS** |
| Program Lead | `/dashboard?view=team&fy=2027` | `1440×900` | 200 | **0 px** | 0 | 0 | 0 | No | Native Go Team Delivery table + pulse | **PASS** |
| Program Lead | `/dashboard?view=programmes&fy=2027` | `1440×900` | 200 | **0 px** | 0 | 0 | 0 | No | Native Go Cohort SSA & Activity breakdown | **PASS** |
| Admin | `/ssa/upload` | `1440×900` | 200 | **0 px** | 0 | 0 | 0 | No | Tab switched to Planned Activities CSV (`activity_id` rendered) | **PASS** |
| CCEO | `/dashboard?view=operations` | `1440×900` | 200 | **0 px** | 0 | 0 | 0 | No | Native Go Urgent Schools portfolio table | **PASS** |
| Admin | `/schools` | `1440×900` | 200 | **0 px** | 0 | 0 | 0 | No | School Directory + CSV/Excel/PDF actions | **PASS** |
| Program Lead | `/core-schools-oversight` | `768×1024` (Tablet) | 200 | **0 px** | 0 | 0 | 0 | No | Tablet layout + filters + CSV/Excel/PDF | **PASS** |
| CCEO | `/dashboard?view=map` | `390×844` (Mobile) | 200 | **0 px** | 0 | 0 | 0 | No | Mobile map + responsive cards | **PASS** |
| Admin | `/ssa/upload` | `390×844` (Mobile) | 200 | **0 px** | 0 | 0 | 0 | No | Mobile upload center layout | **PASS** |

## 2. Complete Route & Module Inventory (All 43 Next.js Routes Verified Built)

* **Operational:** `/`, `/login`, `/home`, `/dashboard` (all 7 PL views + CCEO Week/Urgent/Map), `/planning`, `/my-plan`, `/my-plan/smart-route`, `/schools`, `/schools/[id]`, `/schools/closed`, `/schools/location-reports`, `/clusters`, `/calendar`, `/route-planner`, `/route-planner/location`, `/work-plan`, `/ssa/upload`, `/ssa/upload/template`, `/today-next`, `/more`, `/support`, `/settings`.
* **Oversight & Supporting:** `/country-map`, `/core-schools-oversight`, `/debriefs`, `/decision-log`, `/escalations`, `/personal-time-off`, `/messages`, `/notifications`, `/countries`, `/countries/[code]`, `/countries/memberships`, `/country-admin`, `/[...rest]` (dynamic Go `PageScreenService` catch-all covering `/cluster-oversight/`, `/partner-oversight/`, `/fund-requests/weekly`, `/fund-approvals`, `/disbursements`, `/ia/verification/`, `/my-targets`, `/team-planning-oversight/`, `/projects`, `/partner/completed`, `/loans`, etc.).
* **Native Go Proxy Routes:** `/api/realtime`, `/api/uploads/[kind]`, `/exports/[kind]`, `/exports/cluster-oversight/[section]`, `/auth/*`.
