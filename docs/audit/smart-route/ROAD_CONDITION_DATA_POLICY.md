# Road Condition, Traffic & Closure Data Policy

**Project:** Edify Planning & Monitoring Platform  
**Date:** 2026-11-22

---

## 1. Truthfulness & Source Attribution Rules

Edify's Smart Route Planner distinguishes strictly between four information trust states and **never fabricates traffic congestion or displays "Road Open" merely because no closure report exists**:

| Information State | UI & API Labeling | Routing Engine Treatment |
|---|---|---|
| **Provider-confirmed traffic** | `normal`, `slow`, `traffic_jam` (Google Routes v2 `TRAFFIC_ON_POLYLINE` + `staticDuration` vs `duration`) | Applied directly in Google Stage 2 ETA & displayed with explicit delay badge. |
| **Verified road condition** | `verification_status: "verified"` (supervisor-reviewed staff report or official notice) | Matched within `radius_m` of route polyline, displayed as high-visibility amber/red hazard pin & warning banner with distance and alternative-route prompt. |
| **Unverified staff report** | `verification_status: "unverified"` (all newly submitted field staff reports start here) | Displayed explicitly as `"Unverified staff report — treat with caution"`, never represented as an official closure or provider-blocked road. |
| **Unavailable information** | `traffic_state: "unavailable"` (e.g., OSRM or unconfigured Google key) | Explicitly labeled `"Traffic unavailable"` / `"Live traffic unavailable"`. Never mocked. |

## 2. Supported Staff Road-Condition Categories

Implemented in `field_routes.road_condition_report` (migration `0007_smart_route_intelligence.sql`) and `RoutePlanner.tsx` modal:
- `road_closed`, `road_flooded`, `bridge_damaged`, `under_construction`, `poor_condition`, `severe_congestion`, `road_reopened`.
- Every report stores: `road_name`, `lat`, `lng`, `radius_m` (`100`–`25,000 m`), `category`, `source`, `verification_status`, `impact_level` (`advisory` | `delay` | `impassable`), `notes`, `reported_by`, `reported_by_name`, `reported_at`, `expires_at` (auto-excluded once expired), `reviewed_by`, `reviewed_at`, `country_code` (RLS enforced).

## 3. Live Acceptance Test D Proof

1. `cceo@edify.org` submitted `POST /api/v1/smart-route/road-conditions` (`"QA Test Mukono Bridge Closure"`, `category: "road_closed"`, `impact_level: "impassable"`):
   - HTTP `201 Created`, `report_id: f2cd3844-33ff-47f7-9017-214ac080887f`, initial `verification_status: "unverified"`.
2. `admin@edify.org` verified via `POST /api/v1/smart-route/road-conditions/{id}/verify` (`status: "verified"`):
   - HTTP `200 OK`, `verification_status: "verified"`, SSE event `road_condition.verified` published.
3. Subsequent `POST /api/v1/smart-route/optimize` matched the closure directly on the road polyline:
   - `matched_on_route: true`
   - `applicability_note: "Verified report within 0.0 km of route — check alternative routes."`
   - Disclosed provider limitation transparently: provider cannot automatically block staff-reported segments; users are warned and prompted to compare alternatives.
4. Resolved via `status: "resolved"` post-test so QA test data does not pollute active warnings.
