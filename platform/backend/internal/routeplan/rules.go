// Package routeplan is the Smart Route Planner (owner, 2026-11-14): a field
// day's schools placed by the School Directory's own coordinates, the
// straight-line and road distances between them, a visiting order that keeps
// fixed appointments and the working day, and the eligible schools near the
// route.
//
// It only reads. A recommended school is a suggestion: putting it on the plan
// is the existing Schedule visit drawer's save, as every official change is.
//
// The working day, visit length, planning speed and statuses are the
// existing route engine's, exported to rules.json by
// `manage.py export_route_rules`; apps/routes/test_route_rules_export.py
// fails when the two differ.
package routeplan

import (
	_ "embed"
	"encoding/json"
	"fmt"
	"slices"
)

//go:embed rules.json
var rulesJSON []byte

// Rules is the exported rule set.
var Rules = func() (r struct {
	Day struct {
		Start            string `json:"start"`
		WorkMinutes      int    `json:"work_minutes"`
		LunchMinutes     int    `json:"lunch_minutes"`
		AvailableMinutes int    `json:"available_minutes"`
		VisitMinutes     int    `json:"visit_minutes"`
		BufferMinutes    int    `json:"buffer_minutes"`
	} `json:"day"`
	NearbyRadiusKm     float64           `json:"nearby_radius_km"`
	PlanningSpeedKmh   float64           `json:"planning_speed_kmh"`
	VisitTypes         []string          `json:"visit_types"`
	CompletedStatuses  []string          `json:"completed_statuses"`
	NotLiveStatuses    []string          `json:"not_live_statuses"`
	ClosedStatuses     []string          `json:"closed_statuses"`
	SchoolTypes        map[string]string `json:"school_types"`
	PlannerRoles       []string          `json:"planner_roles"`
	SchoolProfileRoles []string          `json:"school_profile_roles"`
}) {
	if err := json.Unmarshal(rulesJSON, &r); err != nil || r.Day.WorkMinutes == 0 || r.PlanningSpeedKmh == 0 {
		panic(fmt.Sprintf("routeplan: the embedded rules are unreadable: %v", err))
	}
	return r
}()

// MayPlan is whether the role opens the planner (My Plan's door).
func MayPlan(role string) bool { return slices.Contains(Rules.PlannerRoles, role) }

// MayOpenProfile is whether the role opens a school's profile.
func MayOpenProfile(role string) bool { return slices.Contains(Rules.SchoolProfileRoles, role) }
