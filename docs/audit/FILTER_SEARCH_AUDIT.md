# Global Search, Page Search & Filter Synchronization Audit

**Audit Date:** 2026-11-22

---

## 1. Search & Filter Surfaces Audited

| Surface | Implementation | Scope Enforcement | Filter Sync Verified | Status |
|---|---|---|---|---|
| TopBar Global Search | `TopBar.tsx` + `pageSearch.ts` → `/schools` or `/search` (`fieldpages/search.go`) | Server-side Go scope (`schooldirectory.ScopeFor`) | Preserves `search.keep` query parameters | **Pass** |
| School Directory Search & Filters | `schools/page.tsx` + `FilterBar.tsx` + `SchoolDirectoryScreenService` | Role-scoped (`CCEO` sees assigned/permitted schools; `Admin`/`CD` see country scope) | Syncs table rows, tab counts, pager, and filtered CSV export (`/exports/school_directory?...`) | **Pass** |
| Country Map / PL Map Search & Filters | `CountryMapView.tsx` + `GET /api/v1/country-map/data?fy=...` | Role-gated (`403` for disallowed roles) | FY selector re-queries Go API; search dropdown searches sub-regions, districts, and geo-located schools; legend filters sync pins & polygons live | **Pass** |
| Core School Oversight Filters | `CoreSchoolOversightView.tsx` + `coreoversight` | Role & country scoped | FY, district, core type, trajectory, champion readiness, and sort sync KPIs, donut, and table | **Pass** |
| Cluster Oversight Section Filters | `clusteroversight` (18 sections) | Role-gated per section | Carries `fy` and intervention/view filters through section tabs and CSV export links | **Pass** |
| Field Debrief & Decision Log Filters | `FieldDebriefView.tsx`, `DecisionLogView.tsx` | Role & country scoped | Period, risk/status, author, and clear-filters restore default views cleanly | **Pass** |

---

## 2. Live Search Scoping Verification

- Executed `SchoolDirectoryScreenService/GetSchoolDirectory` with `search: "Primary"` as both `CCEO` (`cceo@edify.org`) and `Admin` (`admin@edify.org`):
  - Both returned `HTTP 200` within `< 150ms` with valid scoped school rows.
  - Filtered CSV export (`school_directory`, `filters: { school_type: "core" }`) returned exactly `103` rows matching the live Core school count in PostgreSQL (`0` non-core leakage).
