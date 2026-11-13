// Package partneroversight is Partner Monitoring (/partner-oversight/): one
// Partner at a time, the schools, clusters and activities handed to it, by
// team member, and where each stands, as the existing page draws it
// (apps.frontend.views.oversight_views.partner_oversight_view,
// apps.planning.partner_oversight_service, pages/oversight/
// partner_oversight.html with partials/oversight/partner_workspace.html) and
// the app's feed reads it (apps.mobile_feed).
//
// This first piece answers a field officer or a Programme Lead whose
// workspace holds no partner work: the page as it opens for them, with its
// filters, team-member tabs, headline tiles, empty state and (for a
// Programme Lead) the partnership register. A reader with any partner work in
// reach, or whom the page reads through the country or a region, is passed
// to the existing application (served=false).
//
// The vocabularies it is built from are the existing ones, exported to
// rules.json by `manage.py export_partner_oversight_rules`;
// apps/planning/test_partner_oversight_rules_export.py fails when the two
// differ.
package partneroversight

import (
	_ "embed"
	"encoding/json"
	"fmt"
)

//go:embed rules.json
var rulesJSON []byte

// Role is what a role is given on the page.
type Role struct {
	// Page opens Partner Monitoring at all.
	Page bool `json:"page"`
	// Lens is how the page reads partner work for the role: "team",
	// "country" or "region" (partner_oversight_service._resolve_scope).
	Lens string `json:"lens"`
	// OwnWorkOnly is a CCEO: their team is their own work alone.
	OwnWorkOnly bool `json:"own_work_only"`
	// CreatePartner offers Add Partner Organisation.
	CreatePartner bool `json:"create_partner"`
	// EngagementRegister shows the partnership register under the work.
	EngagementRegister bool `json:"engagement_register"`
	// RecordsEngagements may record one (the register's empty state says so).
	RecordsEngagements bool `json:"records_engagements"`
	// ReadsOwnEngagements reads only the engagements they recorded.
	ReadsOwnEngagements bool `json:"reads_own_engagements"`
	// ObservationsTile adds the Regional Lead observations tile.
	ObservationsTile bool `json:"observations_tile"`
}

// Tile is one headline tile as the feed reads it.
type Tile struct {
	Label  string `json:"label"`
	Value  string `json:"value"`
	Helper string `json:"helper"`
	Note   string `json:"note"`
	Tone   string `json:"tone"`
}

// Rules are the page's vocabularies.
type Rules struct {
	Roles                        map[string]Role      `json:"roles"`
	StatusFilterKeys             []string             `json:"status_filter_keys"`
	WorkTabs                     []string             `json:"work_tabs"`
	CoreWorkTab                  string               `json:"core_work_tab"`
	PlanningLeadRole             string               `json:"planning_lead_role"`
	PlanningCCEORole             string               `json:"planning_cceo_role"`
	RosterLeadRole               string               `json:"roster_lead_role"`
	PartnerDelivery              string               `json:"partner_delivery"`
	WithdrawalRequested          string               `json:"withdrawal_requested"`
	LeftPartnerStatuses          []string             `json:"left_partner_statuses"`
	ReturnedToStaff              string               `json:"returned_to_staff"`
	PartnerActionRecommendations []string             `json:"partner_action_recommendations"`
	EngagementMetricWords        map[string][2]string `json:"engagement_metric_words"`
	EngagementAutoloadParams     []string             `json:"engagement_autoload_params"`
	EngagementPageParam          string               `json:"engagement_page_param"`
	ZeroTiles                    []Tile               `json:"zero_tiles"`
	ZeroTilesWithTarget          []Tile               `json:"zero_tiles_with_target"`
	QueryKeysNotPassed           []string             `json:"query_keys_not_passed"`
}

var rules = mustLoad(rulesJSON)

func mustLoad(raw []byte) Rules {
	var r Rules
	if err := json.Unmarshal(raw, &r); err != nil {
		panic(fmt.Sprintf("partneroversight: rules.json: %v", err))
	}
	for _, key := range []string{"recorded", "partners_engaged", "follow_ups_due", "observations"} {
		if _, ok := r.EngagementMetricWords[key]; !ok {
			panic("partneroversight: rules.json lacks the engagement tile " + key)
		}
	}
	if len(r.ZeroTiles) == 0 || len(r.ZeroTiles) != len(r.ZeroTilesWithTarget) || len(r.WorkTabs) == 0 {
		panic("partneroversight: rules.json lacks the tiles or the work tabs")
	}
	return r
}
