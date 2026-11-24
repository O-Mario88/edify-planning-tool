package screens

import (
	"testing"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/activities"
)

func TestFacilitatorDrawerIsTheTemplatesWords(t *testing.T) {
	d := facilitatorDrawer(activities.FacilitatorFacts{
		Subtitle: "Cluster Meeting · Cluster A · 12 Apr 2026", Current: "Staff", Noun: "meeting",
		Partners: []activities.FacilitatorPartner{{ID: "p1", Name: "Build Africa"}},
	})
	if d.GetTitle() != "Facilitated by" || d.GetSubmitLabel() != "Save" || d.GetCancelLabel() != "Cancel" || !d.GetCanSubmit() {
		t.Fatalf("drawer = %+v", d)
	}
	if got := d.GetItems()[0].GetText(); got != "Now facilitated by Staff. Staff still run the meeting and complete it; a partner facilitator is told the date and invoices the facilitation fee." {
		t.Errorf("text = %q", got)
	}
	f := d.GetItems()[1].GetField()
	if f.GetName() != "facilitating_partner_id" || f.GetKind() != "select" || len(f.GetOptions()) != 2 || f.GetOptions()[0].GetLabel() != "Staff" {
		t.Errorf("field = %+v", f)
	}
	if f.GetHelp() != "A partner facilitating this meeting is not assigned the school. Assign the school to a partner separately for follow-ups and other support." {
		t.Errorf("help = %q", f.GetHelp())
	}
}

func TestFacilitatorPathIsTheActivitys(t *testing.T) {
	for path, want := range map[string]bool{
		"/activities/abc123/facilitator":  true,
		"/activities/abc123/facilitator/": true,
		"/clusters/abc123/facilitator":    false,
		"/activities/abc/facilitator/x":   false,
	} {
		if got := activityFacilitatorPath.MatchString(path); got != want {
			t.Errorf("%s: %v", path, got)
		}
	}
}
