# PostGIS & Geographic Map Audit

**Audit Date:** 2026-11-22  
**Endpoints Audited:** `GET /api/v1/country-map/data?fy=...`, `/country-map`, `/dashboard?view=map`

---

## 1. Geographic Hierarchy & Database Schema Audit

Verified PostgreSQL administrative hierarchy tables present in `edify_gorn_test`:
* `region` → `sub_region` → `district` → `county` → `sub_county` → `parish` → `village` → `school` (plus `school_geo_point`, `cluster_service_district`, `cluster_sub_county`, `staff_geography_assignment`, `geography_alias`).
* Multi-country hierarchy labels are configurable per country via `internal/countryconfig` (`UG` live; `KE`/`RW`/`ET` draft).

## 2. PostGIS Extension Status (Honest Finding)

* Local Homebrew PostgreSQL 16.15 (`edify_gorn_test`) currently has extensions `plpgsql (1.0)` and `pg_trgm (1.6)` installed; **PostGIS is NOT enabled on the local macOS PostgreSQL instance** (`school.latitude` / `school.longitude` double-precision columns + UBOS 135-district GeoJSON boundaries in `platform/web/public/geo/uganda_districts.geojson` power the current map).
* **Recommendation for 50,000+ Schools / Multi-Country Scale:** Enable `postgis` on the staging/production PostgreSQL cluster, add a `GEOGRAPHY(Point, 4326)` column + GiST spatial index on `school`, and store versioned country administrative polygon boundaries in PostgreSQL/PostGIS so Kenya, Rwanda, and Ethiopia boundaries serve directly from the database without static GeoJSON files.

## 3. Map Statistical & Missing-Coordinate Reconciliation (`edify_gorn_test`)

| Metric | PostgreSQL Independent Query | `GET /api/v1/country-map/data?fy=2027` | Variance |
|---|---|---|---|
| Total active schools | **700** | **700** | **0** |
| Schools with valid Uganda coordinates | **683** | **`with_coordinates_count = 683`** (`683` pins) | **0** |
| Schools missing/zero coordinates | **17** | **`missing_coordinates_count = 17`** | **0** |
| Coordinates invented for missing schools | 0 | **0** (excluded from pin plot, preserved in sub-region & district statistical totals) | **0** |
| Confirmed FY27 SSA avg & coverage | `5.91` (`306/700 = 44%`) | `5.91` (`306/700 = 44%`) | **0.00** |

## 4. Map Interactivity & Export Parity

* Verified live in Chromium across Desktop (`1440×900`) and Mobile (`390×844`): zoom/pan, sub-region choropleth filtering, district drill-down, search, cohort legend toggles, `0px` horizontal overflow, and multi-format exports (`Export Map Data` CSV + Go-backed `Excel (.xlsx)` and `PDF Report`).
