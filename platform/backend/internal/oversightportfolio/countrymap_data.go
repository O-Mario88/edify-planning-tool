package oversightportfolio

import (
	"context"
	"encoding/json"
	"fmt"
	"math"
	"net/http"
	"slices"
	"strings"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// MapAuthenticator authenticates a Bearer Authorization header for HTTP endpoints.
type MapAuthenticator interface {
	Authenticate(ctx context.Context, header string) (auth.Principal, error)
}

// MapSchoolTotals holds the five canonical school cohort counts for the map KPIs and legend.
type MapSchoolTotals struct {
	Schools       int `json:"schools"`
	Clients       int `json:"clients"`
	Core          int `json:"core"`
	Champions     int `json:"champions"`
	CoreTrained   int `json:"core_trained"`
	CoreGraduates int `json:"core_graduates"`
}

// MapSubRegionRow is one sub-region row in the Performance by Sub-Region table and donut.
type MapSubRegionRow struct {
	Name                string  `json:"name"`
	Districts           int     `json:"districts"`
	Schools             int     `json:"schools"`
	Clients             int     `json:"clients"`
	Core                int     `json:"core"`
	Champions           int     `json:"champions"`
	CoreTrained         int     `json:"core_trained"`
	CoreGraduates       int     `json:"core_graduates"`
	ActivitiesPlanned   int     `json:"activities_planned"`
	ActivitiesCompleted int     `json:"activities_completed"`
	CoveredSchools      int     `json:"covered_schools"`
	CoveragePct         int     `json:"coverage_pct"`
	AvgSSA              float64 `json:"avg_ssa"`
}

// MapDistrictRow is one district entry for Top Districts, search, and choropleth tooltips.
type MapDistrictRow struct {
	ID            string `json:"id"`
	Name          string `json:"name"`
	SubRegion     string `json:"sub_region"`
	Schools       int    `json:"schools"`
	Clients       int    `json:"clients"`
	Core          int    `json:"core"`
	Champions     int    `json:"champions"`
	CoreTrained   int    `json:"core_trained"`
	CoreGraduates int    `json:"core_graduates"`
}

// MapSchoolPin is a geo-located operating school plotted on the country map.
type MapSchoolPin struct {
	ID         string  `json:"id"`
	SchoolID   string  `json:"school_id"`
	Name       string  `json:"name"`
	District   string  `json:"district"`
	SubRegion  string  `json:"sub_region"`
	SchoolType string  `json:"school_type"`
	Lat        float64 `json:"lat"`
	Lng        float64 `json:"lng"`
	Href       string  `json:"href"`
}

// MapDataResponse is the canonical country-wide dataset for the interactive Uganda map.
type MapDataResponse struct {
	FY             string            `json:"fy"`
	FYOptions      []string          `json:"fy_options"`
	ScopeLabel     string            `json:"scope_label"`
	CCEOs          int               `json:"cceos"`
	DistrictCount  int               `json:"district_count"`
	SubRegionCount int               `json:"sub_region_count"`
	Totals         MapSchoolTotals   `json:"totals"`
	SubRegions     []MapSubRegionRow `json:"sub_regions"`
	Districts      []MapDistrictRow  `json:"districts"`
	Pins           []MapSchoolPin    `json:"pins"`
}

var completedActivityStatuses = []string{
	"completed",
	"closed",
	"ia_verified",
	"accountant_confirmed",
	"evidence_accepted",
	"submitted_to_pl",
	"awaiting_ia_verification",
}

// CanReadMapData reports whether the caller's active role may read the
// country-wide interactive map dataset (Country Map roles plus Programme Lead
// and CCEO dashboard Map views).
func CanReadMapData(role string) bool {
	if role == rules.ProgramLeadRole || role == "CCEO" {
		return true
	}
	d := doorsFor(role)
	return d.MapPage && d.MapFeedOpens
}

// MapData computes the live country-wide map metrics directly from PostgreSQL
// for the requested fiscal year.
func (c *CountryMap) MapData(ctx context.Context, fy string) (*MapDataResponse, error) {
	now := c.s.now()
	options := schooldirectory.FYOptions(now)
	fy = strings.TrimSpace(fy)
	if fy == "" || !slices.Contains(options, fy) {
		fy = schooldirectory.OperationalFY(now)
	}

	resp := &MapDataResponse{
		FY:         fy,
		FYOptions:  options,
		ScopeLabel: "Country-wide system data",
		SubRegions: []MapSubRegionRow{},
		Districts:  []MapDistrictRow{},
		Pins:       []MapSchoolPin{},
	}

	if err := c.s.db.QueryRow(ctx, `
SELECT count(DISTINCT sp.id)
FROM staff_profile sp
JOIN "user" u ON u.id = sp.user_id
WHERE sp.deleted_at IS NULL AND u.is_active = true
  AND (u.active_role = 'CCEO' OR 'CCEO' = ANY(u.roles))`).Scan(&resp.CCEOs); err != nil {
		return nil, fmt.Errorf("oversightportfolio: counting active CCEOs: %w", err)
	}

	// Sub-region rollup with operating schools and FY activity coverage.
	srRows, err := c.s.db.Query(ctx, `
WITH active_schools AS (
  SELECT s.id, s.district_id, COALESCE(s.school_type, '') AS school_type, s.account_owner_id, s.cluster_id
  FROM school s
  WHERE s.deleted_at IS NULL AND s.operational_status = ANY($1)
),
fy_act AS (
  SELECT a.school_id,
         count(a.id) AS planned,
         count(a.id) FILTER (WHERE a.status = ANY($3)) AS completed
  FROM activity a
  WHERE a.deleted_at IS NULL AND a.fy = $2 AND NOT (a.status = ANY($4))
    AND a.school_id IS NOT NULL
  GROUP BY a.school_id
)
SELECT sr.name,
       count(DISTINCT d.id) AS districts,
       count(DISTINCT sc.id) AS schools,
       count(DISTINCT sc.id) FILTER (WHERE lower(sc.school_type) = 'client') AS clients,
       count(DISTINCT sc.id) FILTER (WHERE lower(sc.school_type) = 'core') AS core,
       count(DISTINCT sc.id) FILTER (WHERE lower(sc.school_type) = 'champion') AS champions,
       count(DISTINCT sc.id) FILTER (WHERE lower(sc.school_type) = 'core_trained') AS core_trained,
       count(DISTINCT sc.id) FILTER (WHERE lower(sc.school_type) = 'core_graduate') AS core_graduates,
       COALESCE(sum(fa.planned), 0)::int AS planned_act,
       COALESCE(sum(fa.completed), 0)::int AS completed_act,
       count(DISTINCT sc.id) FILTER (WHERE COALESCE(fa.planned, 0) > 0 OR sc.cluster_id IS NOT NULL) AS covered_schools
FROM sub_region sr
LEFT JOIN district d ON d.sub_region_id = sr.id
LEFT JOIN active_schools sc ON sc.district_id = d.id
LEFT JOIN fy_act fa ON fa.school_id = sc.id
GROUP BY sr.id, sr.name
ORDER BY schools DESC, districts DESC, sr.name ASC`,
		rules.OperatingStatuses, fy, completedActivityStatuses, rules.DeadStatuses)
	if err != nil {
		return nil, fmt.Errorf("oversightportfolio: reading sub-region rollup: %w", err)
	}
	defer srRows.Close()

	for srRows.Next() {
		var r MapSubRegionRow
		if err := srRows.Scan(
			&r.Name, &r.Districts, &r.Schools, &r.Clients, &r.Core,
			&r.Champions, &r.CoreTrained, &r.CoreGraduates,
			&r.ActivitiesPlanned, &r.ActivitiesCompleted, &r.CoveredSchools,
		); err != nil {
			return nil, fmt.Errorf("oversightportfolio: scanning sub-region row: %w", err)
		}
		if r.Schools > 0 {
			r.CoveragePct = int(math.Round(float64(r.CoveredSchools) * 100.0 / float64(r.Schools)))
			if r.CoveragePct > 100 {
				r.CoveragePct = 100
			}
		}
		resp.SubRegions = append(resp.SubRegions, r)
		resp.DistrictCount += r.Districts
		resp.Totals.Schools += r.Schools
		resp.Totals.Clients += r.Clients
		resp.Totals.Core += r.Core
		resp.Totals.Champions += r.Champions
		resp.Totals.CoreTrained += r.CoreTrained
		resp.Totals.CoreGraduates += r.CoreGraduates
	}
	if err := srRows.Err(); err != nil {
		return nil, err
	}
	resp.SubRegionCount = len(resp.SubRegions)

	// District rollup ordered by school count descending, then name ascending.
	dRows, err := c.s.db.Query(ctx, `
SELECT d.id, d.name, sr.name,
       count(s.id) AS schools,
       count(s.id) FILTER (WHERE lower(COALESCE(s.school_type, '')) = 'client') AS clients,
       count(s.id) FILTER (WHERE lower(COALESCE(s.school_type, '')) = 'core') AS core,
       count(s.id) FILTER (WHERE lower(COALESCE(s.school_type, '')) = 'champion') AS champions,
       count(s.id) FILTER (WHERE lower(COALESCE(s.school_type, '')) = 'core_trained') AS core_trained,
       count(s.id) FILTER (WHERE lower(COALESCE(s.school_type, '')) = 'core_graduate') AS core_graduates
FROM district d
JOIN sub_region sr ON sr.id = d.sub_region_id
LEFT JOIN school s ON s.district_id = d.id AND s.deleted_at IS NULL AND s.operational_status = ANY($1)
GROUP BY d.id, d.name, sr.name
ORDER BY schools DESC, d.name ASC`, rules.OperatingStatuses)
	if err != nil {
		return nil, fmt.Errorf("oversightportfolio: reading district rollup: %w", err)
	}
	defer dRows.Close()

	for dRows.Next() {
		var r MapDistrictRow
		if err := dRows.Scan(
			&r.ID, &r.Name, &r.SubRegion, &r.Schools,
			&r.Clients, &r.Core, &r.Champions, &r.CoreTrained, &r.CoreGraduates,
		); err != nil {
			return nil, fmt.Errorf("oversightportfolio: scanning district row: %w", err)
		}
		resp.Districts = append(resp.Districts, r)
	}
	if err := dRows.Err(); err != nil {
		return nil, err
	}

	// Geo-located operating school pins inside Uganda bounding box (excluding 0,0).
	pRows, err := c.s.db.Query(ctx, `
SELECT s.id, COALESCE(s.school_id, ''), s.name, COALESCE(d.name, ''), COALESCE(sr.name, ''),
       lower(COALESCE(s.school_type, 'client')), s.latitude, s.longitude
FROM school s
JOIN district d ON d.id = s.district_id
JOIN sub_region sr ON sr.id = d.sub_region_id
WHERE s.deleted_at IS NULL
  AND s.operational_status = ANY($1)
  AND s.latitude IS NOT NULL AND s.longitude IS NOT NULL
  AND NOT (s.latitude = 0 AND s.longitude = 0)
  AND s.latitude BETWEEN -1.6 AND 4.3
  AND s.longitude BETWEEN 29.4 AND 35.1
ORDER BY
  CASE lower(COALESCE(s.school_type, ''))
    WHEN 'champion' THEN 1
    WHEN 'core_graduate' THEN 2
    WHEN 'core_trained' THEN 3
    WHEN 'core' THEN 4
    ELSE 5
  END,
  s.name ASC
LIMIT 1500`, rules.OperatingStatuses)
	if err != nil {
		return nil, fmt.Errorf("oversightportfolio: reading school pins: %w", err)
	}
	defer pRows.Close()

	for pRows.Next() {
		var pin MapSchoolPin
		if err := pRows.Scan(
			&pin.ID, &pin.SchoolID, &pin.Name, &pin.District,
			&pin.SubRegion, &pin.SchoolType, &pin.Lat, &pin.Lng,
		); err != nil {
			return nil, fmt.Errorf("oversightportfolio: scanning school pin: %w", err)
		}
		pin.Href = "/schools/" + pin.ID
		resp.Pins = append(resp.Pins, pin)
	}
	if err := pRows.Err(); err != nil {
		return nil, err
	}

	return resp, nil
}

// RegisterMapHTTP mounts the read-only country map analytics JSON endpoint on mux.
func (c *CountryMap) RegisterMapHTTP(mux *http.ServeMux, auther MapAuthenticator) {
	mux.HandleFunc("GET /api/v1/country-map/data", func(w http.ResponseWriter, r *http.Request) {
		p, err := auther.Authenticate(r.Context(), r.Header.Get("Authorization"))
		if err != nil {
			w.Header().Set("Content-Type", "application/json")
			w.WriteHeader(http.StatusUnauthorized)
			_ = json.NewEncoder(w).Encode(map[string]string{"error": "Authentication required."})
			return
		}
		if !CanReadMapData(p.ActiveRole) {
			w.Header().Set("Content-Type", "application/json")
			w.WriteHeader(http.StatusForbidden)
			_ = json.NewEncoder(w).Encode(map[string]string{"error": "Map access is not permitted for your role."})
			return
		}
		data, err := c.MapData(r.Context(), r.URL.Query().Get("fy"))
		if err != nil {
			w.Header().Set("Content-Type", "application/json")
			w.WriteHeader(http.StatusInternalServerError)
			_ = json.NewEncoder(w).Encode(map[string]string{"error": "Could not load country map data."})
			return
		}
		w.Header().Set("Content-Type", "application/json")
		w.Header().Set("Cache-Control", "private, max-age=30")
		_ = json.NewEncoder(w).Encode(data)
	})
}
