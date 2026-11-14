package extrawork

import (
	"context"
	"errors"
	"net/url"
	"testing"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
)

func points(s string) *string { return &s }

func TestTheSummaryLineCountsPointsOnceAndSaysWhenItShowsOnlySome(t *testing.T) {
	cases := []struct {
		name string
		s    summary
		mine int
		want string
	}{
		{"nothing scored", summary{open: 2, submitted: 1}, 3, "2 open · 1 awaiting review · 0 verified"},
		{"points that sum to nothing are not shown", summary{verified: 1, points: points("0.00")}, 1, "0 open · 0 awaiting review · 1 verified"},
		{"one point is singular", summary{verified: 1, points: points("1.00")}, 1, "0 open · 0 awaiting review · 1 verified · 1.00 performance point"},
		{"more are plural", summary{verified: 2, points: points("3.50"), overdue: 2}, 2, "0 open · 0 awaiting review · 2 verified · 3.50 performance points · 2 overdue"},
		{"past the count the template names", summary{open: 30}, rules.SummaryShows + 1, "30 open · 0 awaiting review · 0 verified · showing the 25 soonest of 26"},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			v := view{summary: c.s, mine: make([]assignment, c.mine)}
			if got := caption(v); got != c.want {
				t.Errorf("caption = %q, want %q", got, c.want)
			}
		})
	}
}

func TestEachStatusOffersItsOwnNextStep(t *testing.T) {
	cases := []struct {
		a    assignment
		want string
	}{
		{assignment{Status: "assigned"}, "Start"},
		{assignment{Status: "acknowledged"}, "Submit Result"},
		{assignment{Status: "in_progress"}, "Submit Result"},
		{assignment{Status: "returned"}, "Submit Result"},
		{assignment{Status: "verified", Points: points("2.50")}, "+2.50 pts"},
		{assignment{Status: "verified"}, "—"},
		{assignment{Status: "submitted"}, "—"},
		{assignment{Status: "cancelled"}, "—"},
	}
	for _, c := range cases {
		if got := action(c.a); got != c.want {
			t.Errorf("%s: %q, want %q", c.a.Status, got, c.want)
		}
	}
}

func TestOnlyOpenWorkDueBeforeTodayIsOverdue(t *testing.T) {
	today := time.Date(2026, 11, 13, 0, 0, 0, 0, time.UTC)
	v := view{today: today}
	for _, c := range []struct {
		status string
		due    time.Time
		want   bool
	}{
		{"assigned", today.AddDate(0, 0, -1), true},
		{"returned", today.AddDate(0, 0, -1), true},
		{"assigned", today, false},
		{"submitted", today.AddDate(0, 0, -9), false},
		{"verified", today.AddDate(0, 0, -9), false},
	} {
		if got := v.overdue(assignment{Status: c.status, Due: c.due}); got != c.want {
			t.Errorf("%s due %s: overdue %v, want %v", c.status, c.due.Format(time.DateOnly), got, c.want)
		}
	}
}

func TestAReturnedTaskCarriesItsReasonCutAsTheTemplateCutsIt(t *testing.T) {
	long := ""
	for len([]rune(long)) < 200 {
		long += "word "
	}
	row := view{}.mineRow(assignment{Title: "Fix it", Instruction: "Do it.", Status: "returned", ReturnReason: long})
	got := []rune(row.GetCells()[0].GetText())
	want := len([]rune("Fix it Do it. Returned: ")) + rules.Cuts.ReturnReason
	if len(got) > want || got[len(got)-1] != '…' {
		t.Errorf("the task cell %q is not cut at %d", string(got), rules.Cuts.ReturnReason)
	}
}

func TestRolesWithoutThePageAreRefusedBeforeAnythingIsRead(t *testing.T) {
	s := NewService(nil, time.Now) // no database: a refusal must not read one
	for role, r := range rules.Roles {
		if r.Page {
			continue
		}
		_, served, err := s.Build(context.Background(), auth.Principal{UserID: "u", ActiveRole: role}, Path, url.Values{})
		if !served || !errors.Is(err, ErrNotAvailable) {
			t.Errorf("%s: served %v, %v; want refused", role, served, err)
		}
	}
	if _, served, _ := s.Build(context.Background(), auth.Principal{ActiveRole: "CCEO"}, "/extra-work/assign-drawer", nil); served {
		t.Error("another path was answered")
	}
}

func TestOnlyTheDirectorAndProgrammeLeadsMayAssign(t *testing.T) {
	for role, r := range rules.Roles {
		want := role == "CountryDirector" || role == "Program Lead"
		if r.CanAssign != want {
			t.Errorf("%s may assign: %v", role, r.CanAssign)
		}
	}
	v := view{role: rules.Roles["Program Lead"], fy: "2026"}
	if got := page(v).GetHeader().GetActions(); len(got) != 1 || got[0].GetHref() != "/extra-work/assign-drawer?fy=2026" {
		t.Errorf("the Programme Lead's button: %v", got)
	}
	if got := page(view{role: rules.Roles["CCEO"]}).GetHeader().GetActions(); len(got) != 0 {
		t.Errorf("a CCEO is offered %v", got)
	}
}
