// Package partnerworkspace is Partner Activities (/partners), the partner
// organisations' workspace, as the existing page draws it
// (apps.frontend.views.partner_views.partners_list_view, _partner_workspace
// and templates/pages/partners/index.html) and the app's feed reads it: each
// organisation's card with the work it holds, the six tiles, the scheduling
// breakdown and the reminder and upcoming lists. Staff who may open Partner
// Oversight are sent there, keeping the year and the partner.
//
// The cards are written as the template writes them and read by the shared
// walker (internal/feeddom), so the feed's grouping is the existing one: one
// panel for every card while no card holds work, a panel and a table per
// card once one does. The filters, tiles, tables and chart are drawn as their
// blocks directly.
//
// Passed on to the existing page: a search (q, which also reads assigned
// schools and regions), a CSV export, and a card with more rows than one
// table page.
//
// The doors, labels and statuses are exported to rules.json by `manage.py
// export_partners_rules`; apps/partners/test_partners_rules_export.py fails
// when the two differ.
package partnerworkspace

import (
	_ "embed"
	"encoding/json"
	"fmt"
	"slices"
	"strings"
	"time"
	"unicode"

	_ "time/tzdata" // the page's day is Kampala's wherever the gateway runs
)

// Path is the page Go answers.
const Path = "/partners"

//go:embed rules.json
var rulesJSON []byte

var rules = func() (r struct {
	PageRoles            []string            `json:"page_roles"`
	OversightRoles       []string            `json:"oversight_roles"`
	OwnOrganisationRoles []string            `json:"own_organisation_roles"`
	ProfileLinkRoles     map[string][]string `json:"profile_link_roles"`
	ActivityTypes        map[string]string   `json:"activity_types"`
	PurposeLabels        map[string]string   `json:"purpose_labels"`
	Interventions        map[string]string   `json:"interventions"`
	CapabilityGroups     map[string]string   `json:"capability_groups"`
	PartnerRoles         map[string]string   `json:"partner_roles"`
	KPILabels            map[string]string   `json:"kpi_labels"`
	NonFundableStatuses  []string            `json:"non_fundable_statuses"`
	CompletedWork        []string            `json:"completed_work_statuses"`
	CompleteStatuses     []string            `json:"complete_statuses"`
	ReleasedStatuses     []string            `json:"released_statuses"`
	PartnerRoleBridge    bool                `json:"partner_role_bridge"`
	PageSize             int                 `json:"page_size"`
}) {
	if err := json.Unmarshal(rulesJSON, &r); err != nil || len(r.PageRoles) == 0 || len(r.KPILabels) != 6 ||
		len(r.ReleasedStatuses) == 0 || len(r.NonFundableStatuses) == 0 || r.PageSize == 0 {
		panic(fmt.Sprintf("partnerworkspace: the embedded rules are unreadable: %v", err))
	}
	return r
}()

// zone is the application's TIME_ZONE: timezone.localdate() and the day a
// dated visit falls on.
var zone = func() *time.Location {
	z, err := time.LoadLocation("Africa/Kampala")
	if err != nil {
		panic("partnerworkspace: " + err.Error())
	}
	return z
}()

func mayOpen(kind, role string) bool { return slices.Contains(rules.ProfileLinkRoles[kind], role) }

// activityLabel is Activity.get_activity_type_display().
func activityLabel(code string) string {
	if label, ok := rules.ActivityTypes[code]; ok {
		return label
	}
	return code
}

// purposeLabel is apps.partners.purposes.visit_purpose_label.
func purposeLabel(code, fallback string) string {
	if label, ok := rules.PurposeLabels[code]; ok {
		return label
	}
	return fallback
}

// focusDisplay is Activity.get_focus_intervention_display(): the choice's
// label, or the stored code where it is no choice.
func focusDisplay(code string) string {
	if label, ok := rules.Interventions[code]; ok {
		return label
	}
	return code
}

// interventionLabel is partner_views._intervention_label: the label, or the
// code in title case; "" for none.
func interventionLabel(code string) string {
	if code == "" {
		return ""
	}
	if label, ok := rules.Interventions[code]; ok && label != "" {
		return label
	}
	return pyTitle(strings.ReplaceAll(code, "_", " "))
}

// pyTitle is str.title(): each run of letters starts with a capital and
// continues in lower case.
func pyTitle(s string) string {
	out := strings.Builder{}
	inWord := false
	for _, r := range s {
		switch {
		case !unicode.IsLetter(r):
			inWord = false
			out.WriteRune(r)
		case inWord:
			out.WriteRune(unicode.ToLower(r))
		default:
			inWord = true
			out.WriteRune(unicode.ToTitle(r))
		}
	}
	return out.String()
}

// intcomma is Django's |intcomma of an integer.
func intcomma(n int64) string {
	s := fmt.Sprint(n)
	sign := ""
	if strings.HasPrefix(s, "-") {
		sign, s = "-", s[1:]
	}
	for i := len(s) - 3; i > 0; i -= 3 {
		s = s[:i] + "," + s[i:]
	}
	return sign + s
}
