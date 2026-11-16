// Package debriefs builds the Field Debrief Dashboard (/debriefs): the strip
// of the period's debriefs against the period before, the daily trend, the
// debriefs by activity type and by risk, the top challenges, the reader's
// action centre, the team and partner table under its tabs, the recent
// activity and peer solutions, and the highlights
// (apps.frontend.views.debrief_views.field_debrief_dashboard_view,
// apps.debriefs.dashboard_service.FieldDebriefDashboardService and
// FieldDebriefService.scoped_queryset, as the existing feed reads them).
//
// The existing feed shows every tab of the table with the rows of the tab
// asked for; Go draws the same.
//
// It reads; it never writes. It hands the page on for a partner reader (the
// partners a partner login acts as are not read here), a reader working in
// an acting appointment, a query it does not know, a range or page that is
// not plainly one, and more debriefs than one page of the table holds.
//
// The doors and words are exported to rules.json by `manage.py
// export_debriefs_rules`; apps/debriefs/test_debriefs_rules_export.py fails
// when the two differ.
package debriefs

import (
	_ "embed"
	"encoding/json"
	"fmt"
)

//go:embed rules.json
var rulesJSON []byte

var rules = func() (r struct {
	Pages              map[string]bool   `json:"pages"`
	PartnerRoles       []string          `json:"partner_roles"`
	ReviewableStatuses []string          `json:"reviewable_statuses"`
	Statuses           map[string]string `json:"statuses"`
	RiskLevels         [][2]string       `json:"risk_levels"`
	Completions        map[string]string `json:"completions"`
	Kinds              map[string]string `json:"kinds"`
	ChallengeTypes     map[string]string `json:"challenge_types"`
	ActivityTypes      map[string]string `json:"activity_types"`
	MetricLabels       []string          `json:"metric_labels"`
	PageSize           int               `json:"page_size"`
}) {
	if err := json.Unmarshal(rulesJSON, &r); err != nil {
		panic(fmt.Sprintf("debriefs: reading rules.json: %v", err))
	}
	if len(r.MetricLabels) != 8 || r.PageSize <= 0 {
		panic("debriefs: rules.json lacks the figures' labels or the page size")
	}
	return r
}()

// label is a choice's name, or the stored value when it is no choice.
func label(choices map[string]string, value string) string {
	if l, ok := choices[value]; ok {
		return l
	}
	return value
}

func riskLabel(level string) string {
	for _, pair := range rules.RiskLevels {
		if pair[0] == level {
			return pair[1]
		}
	}
	return level
}
