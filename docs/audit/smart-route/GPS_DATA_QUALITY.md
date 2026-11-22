# School GPS Coordinate Data Quality & Governance

**Project:** Edify Planning & Monitoring Platform  
**Database Audited:** Isolated Local Test PostgreSQL `edify_gorn_test` (Production DB untouched)  
**Date:** 2026-11-22

---

## 1. Authoritative Coordinate Resolution Hierarchy

Every school coordinate used by the Smart Route Planner is retrieved strictly from PostgreSQL (`platform/backend/internal/routeplan/data.go`), following a strict precedence hierarchy that preserves original School Profile data:

1. **Verified School Entrance / Road Access Point** (`field_routes.school_location` where `target = 'entrance'`) — preferred target for road routing & turn-by-turn directions while preserving the school compound pin.
2. **Verified School Compound Location** (`field_routes.school_location` where `target = 'school'`, then `field_routes.verified_location`, then `school_geo_point`).
3. **Directory Recorded Coordinates** (`school.latitude`, `school.longitude`) — labeled `"recorded"` (unverified) until confirmed in the field.
4. **Missing or Out-of-Bounds Coordinates** (`NULL`, `(0, 0)`, swapped lat/lng, or outside Uganda bounds `[-1.6..4.4, 29.4..35.2]`) — marked `missing` or `invalid` and **never invented or replaced with district centroids**.

## 2. Local Test Database (`edify_gorn_test`) Coordinate Audit

- **Total Active Schools:** 700
- **Placed (Valid Uganda Coordinates):** 683 (97.6%)
- **Missing / Zero / Invalid Coordinates:** 17 (2.4%) — e.g., `Koome Islands Primary School` (ID `1008`, `NULL`), `Kyampisi UMEA Primary School` (ID `1009`), `Mpatta Church of Uganda Primary` (ID `1010`).
- **Spatial Indexing:** PostgreSQL GiST point indexes (`school_location_gist_point_idx`, `verified_location_gist_point_idx`, `road_condition_gist_point_idx`) plus country-scoped composite B-tree indexes (`0006_spatial_index.sql`, `0007_smart_route_intelligence.sql`) are active without requiring PostGIS superuser installation.

## 3. Missing GPS & Unroutable Access Honesty (Test E Verified)

Live test against `POST /api/v1/smart-route/optimize` including `Koome Islands Primary School` (`cmw9p7gwa005eb2ekhemc`, NULL coordinates):

```json
{
  "school_id": "cmw9p7gwa005eb2ekhemc",
  "school_code": "1008",
  "school_name": "Koome Islands Primary School",
  "district": "Mukono",
  "location_status": "missing",
  "reason_code": "missing_gps",
  "reason": "No GPS coordinates recorded in School Profile. Coordinates are never invented.",
  "priority": {
    "band": "high",
    "score": 82,
    "ssa_average": 5.1,
    "reason": "High-need verified SSA average (5.1/10 in 2026)"
  }
}
```

When a school has coordinates but the routing provider finds no drivable road connection, the optimizer excludes it with `reason_code: "road_access_unverified"` and message **`"Road access requires verification"`** — never drawing a fabricated straight line.

## 4. Authorized GPS Correction Workflow (Test F)

- Field staff submit GPS corrections or entrance captures via `ReportSchoolLocation` / `SubmitLocationCapture` (`platform/backend/internal/routeplan/verify.go`, `capture.go`), recording school ID, previous coordinates, proposed coordinates, source, accuracy, timestamp, and author.
- A different authorized reviewer (`MayReview`) approves or rejects pending reports via `/schools/location-reports` (`ReviewLocationReport`).
- Upon approval, `field_routes.school_location` increments `version` and records `field_routes.location_change`. Both the School Profile (`LocationCard.tsx`) and Smart Route Planner (`RoutePlanner.tsx` polling `ListLocationChanges`) synchronize automatically.
