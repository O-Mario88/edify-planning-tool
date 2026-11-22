# Program Lead Dashboard & Interactive Map Validation

**Audit Date:** 2026-11-22  
**Routes Validated:** `/country-map` (Country Oversight) and `/dashboard?view=map` (Program Lead / CCEO Dashboard Map Tab)  
**Backend Source:** `GET /api/v1/country-map/data?fy=<fy>` (`platform/backend/internal/oversightportfolio/countrymap_data.go`)  
**Geographic Boundaries:** Official UBOS GeoJSON (`platform/web/public/geo/uganda_districts.geojson` — 135 district polygons across 10 sub-regions).

---

## 1. Geographic Hierarchy & Marker Reconciliation

| Validation Check | PostgreSQL Ground Truth | Map API / UI Value | Variance | Result |
|---|---:|---:|---:|---|
| UBOS Sub-Regions | `10` (`Acholi`, `Central`, `East Central`, `Elgon`, `Karamoja`, `Lango`, `South Western`, `Teso`, `West Nile`, `Western`) | `10` | `0` | **Pass** |
| Mapped Districts (`sub_region_id IS NOT NULL`) | `136` | `136` | `0` | **Pass** |
| Operating Schools in Mapped Districts | `700` | `700` | `0` | **Pass** |
| Cohort Breakdown (`Core` / `Client` / `Champion` / `Core Trained` / `Core Graduate`) | `103` / `558` / `39` / `0` / `0` | `103` / `558` / `39` / `0` / `0` | `0` | **Pass** |
| Schools with Verified Uganda GPS (`lat ∈ [-1.6, 4.3]`, `lng ∈ [29.4, 35.1]`, `≠ (0,0)`) | `683` | `683` markers plotted | `0` | **Pass** |
| Schools Missing GPS (`NULL`) or Null-Island `(0,0)` | `15` NULL + `2` at `(0,0)` = `17` | Explicitly excluded from map markers (never placed at invented coordinates) | `0` | **Pass** |
| FY 2027 Central Sub-Region Coverage & Avg SSA | `306 / 700 (44%)`, `avg_ssa = 5.91` | `306 / 700 (44%)`, `avg_ssa = 5.91` | `0` | **Pass (Fixed `DEF-005`)** |
| FY 2026 Central Sub-Region Coverage & Avg SSA | `700 / 700 (100%)`, `avg_ssa = 4.96`, `220` planned/completed activities | `700 / 700 (100%)`, `avg_ssa = 4.96`, `220` | `0` | **Pass (Fixed `DEF-005`)** |

---

## 2. Interactive Feature & Scope Verification

- **Scope Clarity:** Subtitle explicitly labels the dataset **`UBOS boundaries · sub-county detail on district zoom · Country-wide system data`**, preventing a Program Lead from confusing national reference counts with supervised team records.
- **Navigation & Deep Links:**
  - `/dashboard?view=map` preserves all 7 Program Lead tabs (`This Week`, active `Map`, `Priorities`, `Team`, `Coaching`, `Programmes`, `Collaboration`) while keeping non-map `/dashboard` views untouched.
  - `/country-map` links cleanly to `Country Portfolio`, `Schools & Coverage`, `Cluster Oversight` (`/cluster-oversight/?fy=...`, fixed via `DEF-006`), and `School Directory` (`/schools`).
- **Interactive Controls Tested Live (Playwright):**
  - Search autocomplete (`Mukono` → zooms to `Mukono (Central)` + displays `Reset` breadcrumb chip).
  - Floating `Map Layers` ↔ `Legend` panel toggles (District Boundaries, Sub-Region Labels, School Pins, Dim Empty Districts, clickable cohort filters, and sub-region checkboxes).
  - `Top 5 Districts (by Schools)` → `View All Districts →` inline expand / `Collapse to Top 5`.
  - `Quick Actions`: `View School Directory`, `Compare Sub-Regions` (activates comparison sorting bar), and `Export Map Data` (downloads UTF-8 CSV).
- **Responsive Layout:** `0px` horizontal overflow on Desktop (`1440×1320`, including bottom sub-region table `tableOverflow: 0`), Tablet (`768×1024`), and Mobile (`390×844`).
- **RBAC Enforcement:** `Accountant` and `PartnerFieldOfficer` receive `403 Forbidden` on `GET /api/v1/country-map/data` and refusal on both `/country-map` and `/dashboard?view=map`; unauthenticated requests receive `401 Unauthorized`.
