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

## 4. Authorized Mobile-First GPS Capture & Update System (Sections 1–12 Verified)

- **Direct Device Geolocation Capture (No Manual Coordinate Typing, No Photo EXIF, No Background Tracking):**
  - **Web (`LocationCard.tsx`, `GpsCaptureModal.tsx`) & Mobile (`LocationPanel.tsx`, `CaptureFlow.tsx`):** Conditionally display **`GPS Missing`** + **`Tap to Add GPS Coordinates`** when no coordinates exist, or **`GPS Recorded`** + stored coordinates/accuracy/date/source + **`Update GPS Coordinates`** when coordinates exist. Saving transitions **`Tap to Add GPS Coordinates` → `Update GPS Coordinates`** live without a full page reload.
  - **Additional Entry Points:** School Profile, School Directory expanded rows (`DirectoryList.tsx`), My Plan / School Visit cards (`FeedRecord.tsx`), and Smart Route Planner excluded missing-GPS school cards + map popups (`RoutePlanner.tsx`, triggering immediate route recalculation on save).
- **Transactional Go API (`POST /api/schools/{schoolId}/gps-location` & `/api/v1/schools/{schoolId}/gps-location`, `gps_http.go`):**
  - Validates authentication, role permissions (`GPSCaptureRoles`), school scope (`schoolByRef`), WGS84/country bounds, horizontal accuracy (`<= 20 m` optimal, `<= 50 m` rural tolerance, `> 50 m` held for review, `> 1000 m` rejected), freshness (`<= 120 s` for live captures), physical-presence confirmation, optimistic concurrency (`base_version` → HTTP `409 Conflict`), and `> 1 km` displacement safety hold (`pending_review`).
  - Persists transactionally under `pg_advisory_xact_lock` into `field_routes.location_capture`, `field_routes.school_location`, and `field_routes.location_change` (preserving full prior-coordinate audit history and never mutating historical `field_routes.route_stop` records).
  - Immediately invalidates both the road-routing cache (`Guarded.ClearCache()`) and the Country Map cache (`countryMapSvc.InvalidateMapCache()`), and publishes an SSE `school_location.updated` event.
- **Honest Offline Mode:** Offline captures queue locally and display an explicit **`Pending Sync`** badge (never `"Saved to Database"`), automatically synchronizing when connectivity returns.

### Live 12-Scenario Acceptance Verification (`edify_gorn_test` + Real Chromium Playwright + Live OSRM)

| # | Scenario | Result | Verified Evidence |
|---|----------|--------|-------------------|
| 1 | Missing-GPS school capture (`1008` Koome Islands Primary) | **PASS** | `GPS Missing` → `Tap to Add GPS Coordinates` → preview (`0.335120, 32.685240`, ±11 m) → `Save School Location` → PostgreSQL `field_routes.school_location` v1 → live switch to `Update GPS Coordinates` without reload |
| 2 | Existing-GPS school update + audit history | **PASS** | Updated v1 → v2 (`0.33545, 32.6856`); `field_routes.location_change` preserved `0.33512\|32.68524 -> 0.33545\|32.6856` |
| 3 | Smart Route Planner recalculation after GPS update | **PASS** | Route cache invalidated immediately; OSRM road distance recalculated `42,633 m -> 41,848 m` (`-785 m`) |
| 4 | GPS permission denied | **PASS** | Clear `Location Permission Denied` alert + `Retry GPS Capture`; zero coordinates written to DB |
| 5 | Poor GPS accuracy (`85 m` / `1500 m`) | **PASS** | `85 m` held as `pending_review` (`accuracy_poor`, stored v3 untouched); `1500 m` rejected HTTP `400` |
| 6 | Stale GPS reading (`10 min` old) | **PASS** | Rejected HTTP `400` (`GPS reading is stale (600 seconds old; max 120 seconds)`) |
| 7 | Unauthorized role / wrong school ID tampering | **PASS** | `ClusterLeader` rejected HTTP `403`; tampered school ID rejected HTTP `403` |
| 8 | Concurrent update (`base_version` mismatch) | **PASS** | Stale `base_version: 1` against v3 rejected HTTP `409 Conflict` (`version_conflict`, `current_version: 3`) |
| 9 | Offline capture (`Pending Sync` → online sync) | **PASS** | Visibly badged `Pending Sync` (never `"Saved to Database"`), then synced cleanly into PostgreSQL (`0.45123\|32.71234\|1`) |
| 10 | Cross-platform coordinate sync (Profile + Country Map + Route) | **PASS** | Country Map pins updated instantaneously `689 -> 691` with `1008` at `0.3418, 32.6856` |
| 11 | Historical route data integrity | **PASS** | MD5 hash of all `field_routes.route_stop` rows identical before & after all GPS captures/updates |
| 12 | Large move safeguard (`> 1 km`) & zero external map links | **PASS** | `~3.1 km` move held as `pending_review` (`large_move`); zero `google.com/maps`, `maps.apple.com`, or `waze.com` URLs |
