// Package myplan is My Plan (/my-plan), owned by Go (owner brief,
// 2026-11-11: "Activity planning and scheduling"): a person's own planned
// work, with the same period tabs, filters, strip, tables and empty states
// as the existing page (apps.frontend.views.my_plan_views.my_plan_view,
// apps.my_plan.services.get_frontend_context and the page's templates), as
// the app's feed reads it (apps.mobile_feed).
//
// It moves in pieces (docs/migration/25-my-plan.md). Piece 1 is the page as
// it opens for a member of staff who holds nothing yet: no work, schools,
// clusters, hand-overs or training ceilings, and no visit target. Everyone
// else's page (a planner's Planned and remaining, the rows, the partner's
// own My Plan) is still answered by the existing application.
//
// The vocabularies are the existing ones, exported to rules.json by
// `manage.py export_my_plan_rules`; apps/my_plan/test_my_plan_rules_export.py
// fails when they differ.
package myplan

import (
	_ "embed"
	"encoding/json"
	"fmt"
	"slices"
)

//go:embed rules.json
var rulesJSON []byte

// Door is whether a role may open the page.
type Door struct {
	Page bool `json:"page"`
}

// StripRules are the Plan progress strip's labels (the metric registry's)
// and the words its completed share shows when nothing was planned.
type StripRules struct {
	Keys      []string `json:"keys"`
	Labels    []string `json:"labels"`
	Drilldown string   `json:"drilldown"`
	NoData    string   `json:"no_data"`
}

// Rules are the page's exported vocabularies.
type Rules struct {
	Doors              map[string]Door `json:"doors"`
	Strip              StripRules      `json:"strip"`
	MonthOptions       [][2]any        `json:"month_options"`
	QuarterOptions     []string        `json:"quarter_options"`
	QuarterFirstMonth  map[string]int  `json:"quarter_first_month"`
	UnsetFilterValues  []string        `json:"unset_filter_values"`
	ExportPeriodKeys   []string        `json:"export_period_keys"`
	NotPassedQueryKeys []string        `json:"not_passed_query_keys"`
	ProgramLeadRole    string          `json:"program_lead_role"`
	CCEORole           string          `json:"cceo_role"`
	VisitTargets       map[string]int  `json:"visit_targets"`
	PartnerRoleBridge  bool            `json:"partner_role_bridge"`
	APIFormats         []string        `json:"api_formats"`
	Plan               PlanRules       `json:"plan"`
	Rows               RowRules        `json:"rows"`
	Readiness          ReadinessRules  `json:"readiness"`
	Tables             TableRules      `json:"tables"`
	PastDue            PastDueRules    `json:"past_due"`
	Week               WeekRules       `json:"week"`
	Detail             DetailRules     `json:"detail"`
	months             []monthOption
}

// DetailRules are what an activity's detail drawer reads
// (export_my_plan_rules.detail_drawer).
type DetailRules struct {
	RateUnits             map[string]string `json:"rate_units"`
	KeyLabels             map[string]string `json:"key_labels"`
	MixedTransportLabel   string            `json:"mixed_transport_label"`
	PeriodSuffix          string            `json:"period_suffix"`
	MissingLabels         map[string]string `json:"missing_labels"`
	FeeLineType           string            `json:"fee_line_type"`
	StaffFacilitatorLabel string            `json:"staff_facilitator_label"`
	NonFundableStatuses   []string          `json:"non_fundable_statuses"`
	UntickableStatuses    []string          `json:"untickable_statuses"`
	ReturnedStatuses      []string          `json:"returned_statuses"`
	SpentCostStatuses     []string          `json:"spent_cost_statuses"`
	StatusLabels          map[string]string `json:"status_labels"`
	TypeLabels            map[string]string `json:"type_labels"`
	AccommodationKeys     []string          `json:"accommodation_keys"`
	TrainingTypes         []string          `json:"training_types"`
	MeetingTypes          []string          `json:"meeting_types"`
	FacilitatorTypes      []string          `json:"facilitator_types"`
	TrainingMeetingKind   string            `json:"training_meeting_kind"`
	DeliveryLabels        map[string]string `json:"delivery_labels"`
}

// PastDueRules are what Home's "What needs you now" lists by
// (export_my_plan_rules.past_due).
type PastDueRules struct {
	TerminalStatuses []string `json:"terminal_statuses"`
	VisitTypes       []string `json:"visit_types"`
	TrainingTypes    []string `json:"training_types"`
	MeetingTypes     []string `json:"meeting_types"`
	ReturnedStatuses []string `json:"returned_statuses"`
	PageSize         int      `json:"page_size"`
}

// WeekRules are what a field officer's This Week lists by
// (export_my_plan_rules.week).
type WeekRules struct {
	ReleasedStatuses     []string    `json:"released_statuses"`
	WithIAStatuses       []string    `json:"with_ia_statuses"`
	AwaitingLeadStatuses []string    `json:"awaiting_lead_statuses"`
	NotSubmittedStatuses []string    `json:"not_submitted_statuses"`
	SFMissingStatuses    []string    `json:"sf_missing_statuses"`
	StartedStatuses      []string    `json:"started_statuses"`
	ReturnedStatuses     []string    `json:"returned_statuses"`
	OwnAwaitingLabel     string      `json:"own_awaiting_label"`
	Tables               [][2]string `json:"tables"`
	ShowFilters          []string    `json:"show_filters"`
	WeekReach            int         `json:"week_reach"`
	RowsPerPage          int         `json:"rows_per_page"`
}

// TableRules are what My Plan's own tables draw a row of finished work by
// (export_my_plan_rules.plan_tables).
type TableRules struct {
	AwaitingDelivery             []string          `json:"awaiting_delivery"`
	NeverOverdue                 []string          `json:"never_overdue"`
	Untickable                   []string          `json:"untickable"`
	WorkedStatuses               []string          `json:"worked_statuses"`
	HandedInStatuses             []string          `json:"handed_in_statuses"`
	SubmitNeedsParticipantsTypes []string          `json:"submit_needs_participants_types"`
	FacilitatorTypes             []string          `json:"facilitator_types"`
	FacilitatorEditableStatuses  []string          `json:"facilitator_editable_statuses"`
	MeetingKindLabels            map[string]string `json:"meeting_kind_labels"`
	OutreachTypes                []string          `json:"outreach_types"`
	OutreachPurposes             []string          `json:"outreach_purposes"`
	VisitShapeTypes              []string          `json:"visit_shape_types"`
	OpenHandoverStatuses         []string          `json:"open_handover_statuses"`
	MoneyAwaitingStatuses        []string          `json:"money_awaiting_statuses"`
	ProgrammeSchoolLabels        map[string]string `json:"programme_school_labels"`
	// The attention cards: compute_next_action's lists, the loop's urgency
	// sections, the Finance card's payment states and who sent work back.
	DatedAndOpen                  []string          `json:"dated_and_open"`
	SSAUploadTypes                []string          `json:"ssa_upload_types"`
	WaitingOnMeActions            []string          `json:"waiting_on_me_actions"`
	FinancePendingPaymentStatuses []string          `json:"finance_pending_payment_statuses"`
	ReturnedBy                    map[string]string `json:"returned_by"`
}

// monthOption is one of the Month filter's choices.
type monthOption struct {
	value int
	label string
}

var rules = mustRules()

func mustRules() Rules {
	var r Rules
	if err := json.Unmarshal(rulesJSON, &r); err != nil {
		panic(fmt.Sprintf("myplan: rules.json: %v", err))
	}
	for _, pair := range r.MonthOptions {
		value, ok := pair[0].(float64)
		label, isText := pair[1].(string)
		if !ok || !isText {
			panic("myplan: rules.json: a month option is not [number, label]")
		}
		r.months = append(r.months, monthOption{value: int(value), label: label})
	}
	if len(r.Strip.Keys) != len(r.Strip.Labels) || len(r.Strip.Labels) != stripFigures {
		panic("myplan: rules.json: the strip is not the page's eight figures")
	}
	return r
}

func in(list []string, value string) bool { return slices.Contains(list, value) }
