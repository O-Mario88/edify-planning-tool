// Package calendarpage is the Calendar (/calendar), owned by Go (owner
// brief, 2026-11-11: "Activity planning and scheduling"): a month of the
// reader's own work, approved leave, holidays and organization events, a
// Programme Lead's CCEOs' and the Country Director's teams' calendars on
// tabs beside it, read only, exactly as the existing page
// (apps.frontend.views.extended_views.calendar_view and
// pages/calendar/index.html) is read by the app's feed (apps.mobile_feed).
//
// A partner's calendar (its Today table and delivery team) is still the
// existing application's.
//
// The vocabularies are the existing ones, exported to rules.json by
// `manage.py export_calendar_page_rules`;
// apps/activities/test_calendar_page_rules_export.py fails when they differ.
package calendarpage

import (
	_ "embed"
	"encoding/json"
	"fmt"
	"slices"
	"time"
)

//go:embed rules.json
var rulesJSON []byte

// LinkTab is one link of a workspace strip, as the feed reads it.
type LinkTab struct {
	Label  string `json:"label"`
	Href   string `json:"href"`
	Active bool   `json:"active"`
}

// Strip is the workspace strip above the page (partials/_section_nav.html).
type Strip struct {
	Label   string    `json:"label"`
	Scrolls bool      `json:"scrolls"`
	Tabs    []LinkTab `json:"tabs"`
}

// Role is what one role is given on the page, by the page's own gates.
type Role struct {
	Page     bool   `json:"page"`
	Leave    bool   `json:"leave"`
	MyPlan   bool   `json:"my_plan"`
	AddEvent bool   `json:"add_event"`
	Strip    *Strip `json:"strip"`
}

// HolidayRules are apps.core.public_holidays: the national calendar of each
// year as the existing code works it out, and what a recorded day changes.
type HolidayRules struct {
	NationalCountry   string              `json:"national_country"`
	Public            string              `json:"public"`
	National          map[string][][4]any `json:"national"`
	EidAlFitr         string              `json:"eid_al_fitr"`
	EidAlAdha         string              `json:"eid_al_adha"`
	FitrSpellings     []string            `json:"fitr_spellings"`
	AdhaSpellings     []string            `json:"adha_spellings"`
	EidReachDays      int                 `json:"eid_reach_days"`
	RecordedBlockType string              `json:"recorded_block_type"`
	national          map[int][]holiday
}

// Rules are the exported vocabularies.
type Rules struct {
	Roles                    map[string]Role     `json:"roles"`
	TimeZone                 string              `json:"time_zone"`
	Years                    [2]int              `json:"years"`
	ActivityTypes            [][2]string         `json:"activity_types"`
	StatusFamilies           map[string][]string `json:"status_families"`
	StatusOptions            [][2]string         `json:"status_options"`
	HiddenStatuses           []string            `json:"hidden_statuses"`
	OfficerCompletedStatuses []string            `json:"officer_completed_statuses"`
	EventKinds               []string            `json:"event_kinds"`
	WeekdayLabels            []string            `json:"weekday_labels"`
	AwaitingDelivery         []string            `json:"awaiting_delivery"`
	Untickable               []string            `json:"untickable"`
	ProgrammeEventType       string              `json:"programme_event_type"`
	AdminRole                string              `json:"admin_role"`
	LeadRole                 string              `json:"lead_role"`
	DirectorRole             string              `json:"director_role"`
	CoordinatorRole          string              `json:"coordinator_role"`
	PartnerRoles             []string            `json:"partner_roles"`
	OwnLabel                 string              `json:"own_label"`
	NoLeadKey                string              `json:"no_lead_key"`
	NoLeadLabel              string              `json:"no_lead_label"`
	PlanningLeadRole         string              `json:"planning_lead_role"`
	PlanningCCEORole         string              `json:"planning_cceo_role"`
	AllowCDOperational       bool                `json:"allow_cd_operational_planning"`
	PartnerRoleBridge        bool                `json:"partner_role_bridge"`
	Holidays                 HolidayRules        `json:"holidays"`
	NotPassedQueryKeys       []string            `json:"not_passed_query_keys"`
	APIFormats               []string            `json:"api_formats"`
}

var (
	rules    = mustRules()
	location = mustLocation(rules.TimeZone)
	// typeLabels is ActivityType's choices by value (get_activity_type_display).
	typeLabels = func() map[string]string {
		out := map[string]string{}
		for _, choice := range rules.ActivityTypes {
			out[choice[0]] = choice[1]
		}
		return out
	}()
)

func mustRules() Rules {
	var r Rules
	if err := json.Unmarshal(rulesJSON, &r); err != nil {
		panic(fmt.Sprintf("calendarpage: rules.json: %v", err))
	}
	r.Holidays.national = map[int][]holiday{}
	for year, days := range r.Holidays.National {
		var y int
		if _, err := fmt.Sscan(year, &y); err != nil {
			panic(fmt.Sprintf("calendarpage: rules.json: holiday year %q", year))
		}
		for _, d := range days {
			day, err := time.Parse(time.DateOnly, d[0].(string))
			if err != nil {
				panic(fmt.Sprintf("calendarpage: rules.json: holiday %v: %v", d, err))
			}
			r.Holidays.national[y] = append(r.Holidays.national[y], holiday{
				date: day, name: d[1].(string), public: d[2].(string) == r.Holidays.Public, expected: d[3].(bool),
			})
		}
	}
	return r
}

func mustLocation(name string) *time.Location {
	loc, err := time.LoadLocation(name)
	if err != nil {
		panic(fmt.Sprintf("calendarpage: the time zone %q: %v", name, err))
	}
	return loc
}

func in(list []string, value string) bool { return slices.Contains(list, value) }
