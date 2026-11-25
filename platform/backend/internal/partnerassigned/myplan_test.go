package partnerassigned

import (
	"slices"
	"testing"
	"time"
)

func day(s string) *time.Time {
	t, err := time.Parse("2006-01-02", s)
	if err != nil {
		panic(err)
	}
	return &t
}

// partner_plan_context: returned work needs attention with only Correct,
// started work is in progress, today's is due, a passed day unstarted needs
// attention, this week's (to Sunday) and later's are planned; every row not
// returned can be cancelled and shows no return reason.
func TestBucketFilesEachRowWhereThePlanDoes(t *testing.T) {
	today, weekEnd := *day("2026-11-25"), *day("2026-11-29")
	cases := []struct {
		name    string
		r       planRow
		want    int
		actions []string
	}{
		{"returned by the PL", planRow{status: "returned_by_pl", note: "Fix it"}, sectionAttend, []string{"correct"}},
		{"started", planRow{status: "in_progress", note: "stale"}, sectionProgress, []string{"continue", "complete", "reschedule", "cancel"}},
		{"due today", planRow{status: "partner_scheduled", planned: day("2026-11-25")}, sectionToday, []string{"start", "complete", "reschedule", "cancel"}},
		{"its day passed", planRow{status: "scheduled", planned: day("2026-11-20")}, sectionAttend, []string{"start", "complete", "reschedule", "cancel"}},
		{"this Sunday", planRow{status: "partner_scheduled", planned: day("2026-11-29")}, sectionWeek, []string{"start", "complete", "reschedule", "cancel"}},
		{"next week", planRow{status: "partner_scheduled", planned: day("2026-11-30")}, sectionLater, []string{"start", "complete", "reschedule", "cancel"}},
		{"not dated", planRow{status: "assigned_to_partner"}, sectionLater, []string{"start", "complete", "reschedule", "cancel"}},
	}
	for _, tc := range cases {
		r := tc.r
		if got := bucket(&r, today, weekEnd); got != tc.want || !slices.Equal(r.actions, tc.actions) {
			t.Errorf("%s: section %d %v, want %d %v", tc.name, got, r.actions, tc.want, tc.actions)
		}
		if r.status != "returned_by_pl" && r.note != "" {
			t.Errorf("%s: return reason %q kept", tc.name, r.note)
		}
	}
}

// The feed draws the menu's links and drawers, not its posted forms.
func TestMenuLeavesOutThePostedForms(t *testing.T) {
	r := planRow{id: "a1", actions: []string{"start", "complete", "reschedule", "cancel", "team"}, contact: "Grace A."}
	labels := []string{}
	for _, a := range r.menu() {
		labels = append(labels, a.GetKey()+":"+a.GetLabel())
	}
	if want := []string{"menu:Reschedule", "menu:Change team member", "danger:Cancel"}; !slices.Equal(labels, want) {
		t.Errorf("menu = %v, want %v", labels, want)
	}
}

func TestEvidenceSummaryCountsTheKindsRequired(t *testing.T) {
	visit := planRow{activityType: "school_visit", kinds: map[string]bool{"photo": true}}
	if got := visit.evidenceSummary(); got != "0/1 evidence items" {
		t.Errorf("visit = %q", got)
	}
	visit.kinds["visit_form"] = true
	if got := visit.evidenceSummary(); got != "1/1 evidence items" {
		t.Errorf("visit with its form = %q", got)
	}
	none := planRow{activityType: "school_visit", profile: "ADMIN_NONE", kinds: map[string]bool{}}
	if got := none.evidenceSummary(); got != "No evidence yet" {
		t.Errorf("no evidence asked = %q", got)
	}
}
