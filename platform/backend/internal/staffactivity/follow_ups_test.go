package staffactivity

import (
	"testing"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
)

func keys(actions []StepAction) []string {
	out := make([]string, len(actions))
	for i, a := range actions {
		out[i] = a.Key
	}
	return out
}

func TestFollowUpStepsFollowTheExistingTable(t *testing.T) {
	lead := auth.Principal{UserID: "lead", ActiveRole: rules.Roles.ProgramLead}
	officer := auth.Principal{UserID: "officer", ActiveRole: rules.Roles.CCEO}
	director := auth.Principal{UserID: "cd", ActiveRole: rules.Roles.CountryDirector}
	manager := func(status string) *followUp {
		return &followUp{route: routeManager, status: status, createdBy: party{id: "lead"}, assignee: party{id: "officer"},
			subject: party{id: "officer"}}
	}
	viaLead := func(status string) *followUp {
		return &followUp{route: routeDirector, status: status, createdBy: party{id: "cd"}, assignee: party{id: "lead"},
			subject: party{id: "officer"}}
	}
	cases := []struct {
		name   string
		f      *followUp
		reader auth.Principal
		want   []string
	}{
		{"the lead who sent it", manager("sent"), lead, []string{"schedule_support", "wait_for_staff", "escalate", "resolve", "cancel"}},
		{"the officer it was sent to", manager("sent"), officer, []string{"acknowledge", "return"}},
		{"returned to the lead", manager("returned"), lead, []string{"resend", "resolve", "cancel"}},
		{"resolved, the lead closes", manager("resolved_by_manager"), lead, []string{"close"}},
		{"escalated: the lead may not acknowledge", manager("escalated"), lead, []string{"resolve", "cancel"}},
		{"escalated: the Director answers", manager("escalated"), director, []string{"acknowledge", "resolve"}},
		{"the Director's route: the lead manages", viaLead("sent"), lead,
			[]string{"acknowledge", "schedule_support", "wait_for_staff", "return", "resolve"}},
		{"the Director's route: the Director created it", viaLead("sent"), director, []string{"cancel"}},
		{"nobody's part", manager("sent"), auth.Principal{UserID: "x", ActiveRole: rules.Roles.CCEO}, nil},
	}
	for _, c := range cases {
		got := keys(c.f.actionsFor(c.reader))
		if len(got) != len(c.want) {
			t.Errorf("%s: %v, want %v", c.name, got, c.want)
			continue
		}
		for i := range got {
			if got[i] != c.want[i] {
				t.Errorf("%s: %v, want %v", c.name, got, c.want)
				break
			}
		}
	}
}

func TestFollowUpHistoryIsDatedAsPythonDatesIt(t *testing.T) {
	at := time.Date(2026, 11, 25, 7, 4, 5, 123456789, time.FixedZone("EAT", 3*3600))
	if got := pythonISO(at); got != "2026-11-25T04:04:05.123456+00:00" {
		t.Fatalf("pythonISO = %q", got)
	}
	if got := pythonISO(at.Truncate(time.Second)); got != "2026-11-25T04:04:05+00:00" {
		t.Fatalf("pythonISO whole second = %q", got)
	}
	lead := auth.Principal{UserID: "lead"}
	e := entry(&lead, "Grace", "sent", "  ", at)
	if e["by"] != "lead" || e["by_name"] != "Grace" || e["status"] != "sent" {
		t.Fatalf("entry = %v", e)
	}
	if platform := entry(nil, "", "resolved_by_activity", "Signed in.", at); platform["by"] != nil || platform["by_name"] != "Platform" {
		t.Fatalf("platform entry = %v", platform)
	}
}
