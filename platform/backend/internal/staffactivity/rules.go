// Package staffactivity is the Staff Activity Log (/staff-activity): how the
// country's CCEOs and Programme Leads use the platform (sign-ins, active
// time, the parts they use, where they are now) and the meaningful work they
// complete, grouped by Programme Lead, with the summary strip, the filters
// and Team Insights, as the existing page draws it for the Country Director
// and the Admin (apps.frontend.views.staff_activity_views.staff_activity_view,
// apps.staff_activity.services.activity_log and
// templates/partials/staff_activity/) and the app's feed reads it
// (apps.mobile_feed). A Programme Lead is sent to their dashboard, as the
// page sends them; a role the page admits but whose log is nobody's is
// refused as the page refuses it.
//
// A reader whose figures need what the gateway may not read (the school a
// hand-over's audit row names in its payload), or that the page could not
// order exactly, is passed to the existing application (served=false).
//
// The vocabularies are the existing ones, exported to rules.json by
// `manage.py export_staff_activity_rules`;
// apps/staff_activity/test_staff_activity_rules_export.py fails when they
// differ.
package staffactivity

import (
	_ "embed"
	"encoding/json"
	"fmt"
	"time"
	_ "time/tzdata" // the page's days are Nairobi's wherever the gateway runs
)

//go:embed rules.json
var rulesJSON []byte

// Action is one meaningful action of registry.MEANINGFUL_ACTIONS.
type Action struct {
	Label     string `json:"label"`
	Module    string `json:"module"`
	School    bool   `json:"school"`
	Secondary bool   `json:"secondary"`
}

// StripSample is one summary strip and the feed's reading of it.
type StripSample struct {
	KPIs  map[string]any `json:"kpis"`
	Strip struct {
		Title   string `json:"title"`
		Metrics []struct {
			Label  string `json:"label"`
			Value  string `json:"value"`
			Helper string `json:"helper"`
			Note   string `json:"note"`
			Href   string `json:"href"`
			Tone   string `json:"tone"`
		} `json:"metrics"`
	} `json:"strip"`
}

// Rules are the page's vocabularies.
type Rules struct {
	Doors map[string]struct {
		Page bool `json:"page"`
	} `json:"doors"`
	Roles struct {
		ProgramLead     string `json:"program_lead"`
		CountryDirector string `json:"country_director"`
		Admin           string `json:"admin"`
		CCEO            string `json:"cceo"`
	} `json:"roles"`
	InternalRoles   []string `json:"internal_roles"`
	SupervisorRoles []string `json:"supervisor_roles"`
	LeaveApproved   string   `json:"leave_approved"`
	HolidayCountry  string   `json:"holiday_country"`
	Dashboard       struct {
		Role   string `json:"role"`
		Path   string `json:"path"`
		Param  string `json:"param"`
		Anchor string `json:"anchor"`
	} `json:"dashboard"`
	RoleFilterLabels [][2]string       `json:"role_filter_labels"`
	RoleTitles       map[string]string `json:"role_titles"`
	StatusOptions    [][2]string       `json:"status_options"`
	Periods          [][2]string       `json:"periods"`
	Thresholds       struct {
		FailedActionsSuggestion      int   `json:"failed_actions_suggestion"`
		ExcessiveTimeFactor          int64 `json:"excessive_time_factor"`
		ExcessiveTimeFloorSeconds    int64 `json:"excessive_time_floor_seconds"`
		LowEngagementMinExpectedDays int   `json:"low_engagement_min_expected_days"`
		IdleSeconds                  int64 `json:"idle_seconds"`
		OnlineSeconds                int64 `json:"online_seconds"`
		FinalBeatSeconds             int64 `json:"final_beat_seconds"`
		SessionCookieAge             int64 `json:"session_cookie_age"`
	} `json:"thresholds"`
	TimeZone             string            `json:"time_zone"`
	PageSize             int               `json:"page_size"`
	MeaningfulActions    map[string]Action `json:"meaningful_actions"`
	FailedRequestActions []string          `json:"failed_request_actions"`
	SchoolSubjects       []string          `json:"school_subjects"`
	ActivitySubjects     []string          `json:"activity_subjects"`
	PayloadSchoolKeys    []string          `json:"payload_school_keys"`
	FollowUpOpenStatuses []string          `json:"follow_up_open_statuses"`
	UntrackedPrefixes    []string          `json:"untracked_prefixes"`
	SectionRegistry      [][2]string       `json:"section_registry"`
	SectionPrefixes      [][2]string       `json:"section_prefixes"`
	Query                struct {
		KeyPattern string   `json:"key_pattern"`
		NotPassed  []string `json:"not_passed"`
		MaxValue   int      `json:"max_value"`
	} `json:"query"`
	StripSamples []StripSample `json:"strip_samples"`
}

var rules = mustLoad(rulesJSON)

// zone is settings.TIME_ZONE, the day every period is counted in.
var zone = mustZone(rules.TimeZone)

func mustLoad(raw []byte) Rules {
	var r Rules
	if err := json.Unmarshal(raw, &r); err != nil || len(r.Doors) == 0 || len(r.InternalRoles) == 0 ||
		len(r.MeaningfulActions) == 0 || len(r.StatusOptions) == 0 || len(r.Periods) == 0 ||
		r.PageSize <= 0 || r.TimeZone == "" || r.Thresholds.IdleSeconds <= 0 || r.Thresholds.SessionCookieAge <= 0 {
		panic(fmt.Sprintf("staffactivity: the embedded rules are unreadable: %v", err))
	}
	return r
}

func mustZone(name string) *time.Location {
	z, err := time.LoadLocation(name)
	if err != nil {
		panic(fmt.Sprintf("staffactivity: no time zone %q: %v", name, err))
	}
	return z
}

func label(pairs [][2]string, key string) (string, bool) {
	for _, p := range pairs {
		if p[0] == key {
			return p[1], true
		}
	}
	return "", false
}

// meaningfulKeys are the actions counted, and those that are not an echo.
func meaningfulKeys() (all, plain, school []string) {
	for k, d := range rules.MeaningfulActions {
		all = append(all, k)
		if !d.Secondary {
			plain = append(plain, k)
		}
		if d.School {
			school = append(school, k)
		}
	}
	return all, plain, school
}
