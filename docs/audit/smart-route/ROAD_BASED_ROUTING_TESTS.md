# Road-Based Routing Verification Report

**Project:** Edify Planning & Monitoring Platform  
**Date:** 2026-11-22  
**Live Routing Provider Tested:** OSRM (`https://router.project-osrm.org`) + Google Routes API v2 (`httptest` multi-stage contract suite)

---

## 1. Critical Audit Finding & Resolution

- **Prior Defect Found:** `RouteMap.tsx` (web) and `routeMapHtml.ts` (mobile) previously connected school markers with a dashed straight line whenever road geometry was absent, and `LatLng` in Go `geo.go` lacked lowercase JSON tags (`json:"lat"`, `json:"lng"`), which caused MapLibre `Invalid LngLat object: (NaN, NaN)` errors on REST endpoints.
- **Fix Applied:**
  1. Removed straight-line route drawing from both `RouteMap.tsx` and `routeMapHtml.ts`. Only provider-returned road polylines (`path_is_road === true`) are rendered.
  2. Added lowercase JSON tags to `routeplan.LatLng` in `platform/backend/internal/routeplan/geo.go`.
  3. Upgraded `OSRM.RouteDetailed` and `Google.RouteDetailed` to return full road-following geometry, turn-by-turn road steps with road names, and alternative routes.

## 2. Acceptance Test A — Road Distance vs. Straight-Line Distance (Live Result)

Executed live against Go `:8091` + OSRM road network on real planned Mukono schools (`2026-11-17`):

| Metric | Measured Live Result |
|---|---|
| **Provider** | `osrm` (OpenStreetMap road network) |
| **Straight-Line Haversine Distance** | `5,762 m` (`5.76 km`) |
| **Actual Road Distance** | `9,801 m` (`9.80 km`) |
| **Road-to-Straight Ratio** | **`1.70×`** (follows actual road network, never straight line) |
| **Estimated Road Drive Time** | `1,300 s` (`21 min 40 sec`) |
| **Returned Road Polyline Points** | `60` simplified vertices (381 vertices for the full 4-school Mukono route) |
| **Turn-by-Turn Steps Returned** | `11` maneuvers on Leg 1 (e.g., `"Turn right onto Mbogo Road"`, `"Continue on Namugongo Road"`, `"Turn right at end of road onto Jinja Road"`) |
| **API Latency** | `12.2 ms` (cached) / `480.8 ms` (cold OSRM network call) |
| **DOM Attribute Verified** | `[data-block="route-map"]` → `data-path-is-road="true"` |

## 3. Additional Unit & Race-Detector Proofs

- `TestSmartRoute_RoadDistanceVsStraightLine` (`internal/routeplan/smart_optimize_test.go`): Verified `2.6×` road-to-straight detour across a simulated river barrier with `go test -race` PASS.
- `TestSmartRoute_TrafficClosuresAndMissingGPS`: Verified `None{}` provider returns `PathIsRoad: false` and `len(Path) == 0` (never fabricates a straight-line polyline).
- Visual Proof: Captured in `sr-desktop-3panel.png` and `sr-in-app-directions.png` showing the continuous blue road-following route winding along Mukono roads between Stops 1, 2, 3, and 4.
