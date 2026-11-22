# Smart Route Planner Architecture

**Project:** Edify Planning & Monitoring Platform  
**Date:** 2026-11-22  
**Status:** Implemented & Verified Locally (Isolated Test PostgreSQL `edify_gorn_test`)

---

## 1. System Overview

The Smart Route Planner has been upgraded from a straight-line fallback visualization into an enterprise, road-network-based field planning and 100% in-app navigation workspace owned by the canonical Go backend (`platform/backend/internal/routeplan/`).

```
[Web 3-Panel UI / Mobile App]
         │
         ├── Next.js BFF Proxy (/api/smart-route/* -> Go /api/v1/smart-route/*)
         ├── ConnectRPC (RoutePlannerService)
         └── Real-Time SSE (/api/v1/realtime/events)
         │
         ▼
[Go Gateway — internal/routeplan]
         ├── Multi-Stage Road Router (Google Routes API v2 | OSRM | Guarded Cache/Rate/Cap)
         ├── 5-Mode Smart Optimizer (balanced, fastest, shortest, max_schools, priority_schools)
         ├── SSA Priority Engine (read-only PostgreSQL query on confirmed ssa_record + school.school_type)
         ├── Road Condition Intelligence (field_routes.road_condition_report with verification workflow)
         └── Scheduling Calendar Rules (public_holiday + leave + Uganda FY2027 boundaries)
         │
         ▼
[PostgreSQL — Owned Schema `field_routes` (Migration 0007) + Read-Only `public.*`]
```

## 2. Canonical Entities & Storage (`field_routes` Migration 0007)

All operational route persistence lives in the Go-owned `field_routes` schema with row-level country isolation (`edify.read_countries` RLS policies) and append/version-only writes (zero `DELETE` statements, zero foreign keys into Django `public.*` tables, passing `internal/dbguard` and `internal/routeplan/schema` lint):

| Entity | Table | Purpose |
|---|---|---|
| **Route Plan** | `field_routes.route_plan` | Owner, planning day, country, FY, start/end coordinates, transport mode, optimization mode, route status, estimated road distance/duration, provider metadata, monotonic `route_version`. |
| **Route Stop** | `field_routes.route_stop` | Versioned stop sequence linked to authoritative `planned_activity_id` and `school_id`, arrival/departure estimates, visit duration, per-leg road metrics, and SSA priority band/score. |
| **Route Calculation** | `field_routes.route_calculation` | Audit log of every saved optimization calculation (provider, `input_hash`, alternatives count, fallback status, timestamp). |
| **Road Condition Report** | `field_routes.road_condition_report` | Staff-reported or official road hazards (`road_closed`, `road_flooded`, `bridge_damaged`, `under_construction`, `poor_condition`, `severe_congestion`, `road_reopened`) with source, verification status (`unverified`, `verified`, `expired`, `resolved`), impact level, expiry, and GiST spatial point index. |

## 3. Canonical Go Operational REST Endpoints

Mounted in `platform/backend/internal/server/server.go` via `routePlanSvc.RegisterHTTP(mux, authenticator, realtimeBroker)`:

- `GET  /api/v1/smart-route/day` — Hydrates the day's authoritative My Plan activities, saved route plan, road-based itinerary, SSA priority bands, active road-condition reports, scheduling calendar rules, and provider quota snapshot.
- `POST /api/v1/smart-route/optimize` — Runs the 5-mode road optimization engine with working hours, start/end locations, locked stops, visit durations, and road-condition proximity warnings.
- `POST /api/v1/smart-route/directions` — Computes 100% in-app turn-by-turn road directions, road-following polylines, ETAs, traffic status, and alternative routes.
- `POST /api/v1/smart-route/save` — Atomically persists `route_plan`, versioned `route_stop` (linked to `planned_activity_id`), `route_calculation`, and legacy `field_day`, publishing `route_plan.saved` via SSE. Never mutates `public.activity`.
- `POST /api/v1/smart-route/validate` — Cross-checks saved route stops against live My Plan activities, Sundays, public holidays, and approved leave to detect stale itineraries.
- `GET/POST /api/v1/smart-route/road-conditions` & `POST /api/v1/smart-route/road-conditions/{id}/verify` — Submits (always initially `unverified`) and supervisor-verifies/resolves road condition reports, publishing SSE notifications.
- `GET  /api/v1/scheduling/calendar-rules` — Serves country FY boundaries (Uganda FY2027 = `2026-10-01` to `2027-09-30`), `public_holiday` rows, and user's approved `leave` dates to the unified `EdifyDatePicker`.

## 4. Non-Negotiable Architectural Guarantees

1. **Zero Straight-Line Fake Routes:** `RouteMap.tsx` (web) and `routeMapHtml.ts` (mobile) render ONLY verified provider road geometry (`path_is_road === true`). When no road route exists, markers display with `"Road access requires verification"` and no fake straight-line route is drawn.
2. **Zero External Navigation Redirects:** Every external `google.com/maps`, `maps.apple.com`, and `waze.com` redirect has been removed from web and mobile. All "Get Directions" triggers open Edify's embedded in-app navigation experience.
3. **Single Source of Truth:** Planned activities stay authoritative in `public.activity`; Smart Route Planner never silently alters approved schedules.
