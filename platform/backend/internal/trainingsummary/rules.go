// Package trainingsummary is the Training Summary lens of Team Oversight
// (/team-planning-oversight/?view=trainings), built by Go: each training
// with a school committed to it in the year, its mode of delivery, the
// schools covered out of the Country Ceiling, the schools staff planned,
// those awaiting the partner's date, what remains, and each officer's
// schools against the ceiling their Programme Lead set
// (apps.frontend.views.oversight_views.team_planning_oversight_view,
// _training_summary_context, apps.planning.training_summary and
// apps.planning.training_ceilings), as the app's feed reads it
// (apps.mobile_feed).
//
// Its Summary, By staff and Schools tabs are Go's (the last two read
// training_ceilings.summary_for_staff and training_coverage.table); every
// other lens of the page and a page opened from a planning follow-up are
// still answered by the existing application.
//
// The vocabularies are the existing ones, exported to rules.json by
// `manage.py export_training_summary_rules`;
// apps/planning/test_training_summary_rules_export.py fails when they
// differ.
package trainingsummary

import (
	_ "embed"
	"encoding/json"
	"fmt"
	"regexp"
	"slices"
)

//go:embed rules.json
var rulesJSON []byte

// LensTab is one link of the oversight lens strip.
type LensTab struct {
	Label  string `json:"label"`
	Href   string `json:"href"`
	Active bool   `json:"active"`
}

// Doors is what a role reaches on the page.
type Doors struct {
	// Page is require_any_page_permission, FeedOpens the feed's can_open_url.
	Page      bool `json:"page"`
	FeedOpens bool `json:"feed_opens"`
	// Trainings is the lens itself (can_view_trainings).
	Trainings     bool `json:"trainings"`
	CountryReader bool `json:"country_reader"`
	// The strip above the lens, for a reader of the country and for a team.
	LensTabsCountry []LensTab `json:"lens_tabs_country"`
	LensTabsTeam    []LensTab `json:"lens_tabs_team"`
	// ReadsCountry: every officer in the country (training_summary.
	// may_read_country); SetsCountryCeiling: Admin and Impact Assessment.
	ReadsCountry       bool `json:"reads_country"`
	SetsCountryCeiling bool `json:"sets_country_ceiling"`
	// OpensStaffProfile is the staff_link tag's _may_open: a staff name
	// links to the person's profile.
	OpensStaffProfile bool `json:"opens_staff_profile"`
}

// Coverage are the By staff and Schools tabs' vocabularies
// (apps.planning.training_coverage and training_ceilings.SummaryRow).
type Coverage struct {
	RouteLabels               map[string]string `json:"route_labels"`
	StatusLabels              map[string]string `json:"status_labels"`
	StatusOrder               []string          `json:"status_order"`
	StatusTones               map[string]string `json:"status_tones"`
	ShowOptions               [][2]string       `json:"show_options"`
	Figures                   []string          `json:"figures"`
	CompletedStatuses         []string          `json:"completed_statuses"`
	UnderWayStatuses          []string          `json:"under_way_statuses"`
	TrainedTypes              []string          `json:"trained_types"`
	ExcludedDuplicateStatuses []string          `json:"excluded_duplicate_statuses"`
	OperatingStatuses         []string          `json:"operating_statuses"`
	TablePageSize             int               `json:"table_page_size"`
	SummaryFlagTones          map[string]string `json:"summary_flag_tones"`
}

// Rules are the lens's vocabularies.
type Rules struct {
	Doors map[string]Doors `json:"doors"`
	Tones struct {
		Cell    map[string]string `json:"cell"`
		Country map[string]string `json:"country"`
	} `json:"tones"`
	Coverage                    Coverage          `json:"coverage"`
	TrainingTypes               []string          `json:"training_types"`
	MeetingTypes                []string          `json:"meeting_types"`
	MeetingKindTraining         string            `json:"meeting_kind_training"`
	ReleasedStatuses            []string          `json:"released_statuses"`
	PlannedStates               []string          `json:"planned_states"`
	PartnerDeliveryType         string            `json:"partner_delivery_type"`
	DatedByPartner              string            `json:"dated_by_partner"`
	CertifiedPartnerAgency      string            `json:"certified_partner_agency"`
	UnscheduledHandoverStatuses []string          `json:"unscheduled_handover_statuses"`
	LiveProjectStatuses         []string          `json:"live_project_statuses"`
	CatalogueTrainingType       string            `json:"catalogue_training_type"`
	ModeGroup                   string            `json:"mode_group"`
	ModeInSchool                string            `json:"mode_in_school"`
	ModePartnerInSchool         string            `json:"mode_partner_in_school"`
	CatalogueModes              map[string]string `json:"catalogue_modes"`
	CountryReaderRoles          []string          `json:"country_reader_roles"`
	ProgramLeadRole             string            `json:"program_lead_role"`
	CCEORole                    string            `json:"cceo_role"`
	DefaultCountry              string            `json:"default_country"`
	QueryKeyPattern             string            `json:"query_key_pattern"`
	QueryKeysNotPassed          []string          `json:"query_keys_not_passed"`
	MaxQueryValue               int               `json:"max_query_value"`
}

var rules = mustLoad(rulesJSON)

var queryKey = regexp.MustCompile(rules.QueryKeyPattern)

func mustLoad(raw []byte) Rules {
	var r Rules
	if err := json.Unmarshal(raw, &r); err != nil {
		panic(fmt.Sprintf("trainingsummary: rules.json: %v", err))
	}
	if len(r.Doors) == 0 || len(r.TrainingTypes) == 0 || r.QueryKeyPattern == "" || r.MaxQueryValue == 0 ||
		r.Coverage.TablePageSize == 0 || len(r.Coverage.StatusOrder) == 0 || len(r.Coverage.ShowOptions) == 0 {
		panic("trainingsummary: rules.json is incomplete")
	}
	return r
}

func in(list []string, value string) bool { return slices.Contains(list, value) }
