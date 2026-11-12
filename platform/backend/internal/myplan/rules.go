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
	months             []monthOption
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
