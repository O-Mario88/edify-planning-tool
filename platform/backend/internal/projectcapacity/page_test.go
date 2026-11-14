package projectcapacity

import (
	"net/url"
	"testing"
)

func TestAnAllocationReadsFullNearOrAvailableAndBlockedOnAProjectTakingNoSchools(t *testing.T) {
	for _, c := range []struct {
		max, assigned int
		blocked       bool
		want          string
	}{
		{5, 5, false, "Full"}, {5, 6, false, "Full"}, {5, 4, false, "Near capacity"}, {10, 7, false, "Available"},
		{10, 8, false, "Near capacity"}, {3, 2, false, "Available"}, {5, 5, true, "Blocked"},
	} {
		if got := status(allocation{Maximum: c.max, Assigned: c.assigned}, c.blocked); got != c.want {
			t.Errorf("%d of %d (blocked %v) = %q, want %q", c.assigned, c.max, c.blocked, got, c.want)
		}
	}
}

func TestUtilizationIsRoundedToOnePlaceWithoutATrailingZero(t *testing.T) {
	for _, c := range []struct {
		max, assigned int
		want          string
	}{{3, 1, "33.3%"}, {3, 2, "66.7%"}, {5, 4, "80%"}, {5, 0, "0%"}, {8, 1, "12.5%"}, {5, 7, "140%"}} {
		if got := utilization(allocation{Maximum: c.max, Assigned: c.assigned}); got != c.want {
			t.Errorf("%d of %d = %q, want %q", c.assigned, c.max, got, c.want)
		}
	}
}

func TestVisitsAreReadAgainstTheRolesCeilingAndPastItInTheDangerTone(t *testing.T) {
	if c := visits(allocation{Planned: 4}); c.GetText() != "4" || c.GetTone() != "" {
		t.Errorf("no ceiling: %v", c)
	}
	if c := visits(allocation{Planned: 13, Ceiling: 560}); c.GetText() != "13 / 560" || c.GetTone() != "" {
		t.Errorf("under: %v", c)
	}
	if c := visits(allocation{Planned: 283, Ceiling: 280}); c.GetText() != "283 / 280 3 over" || c.GetTone() != "danger" {
		t.Errorf("over: %v", c)
	}
}

func TestTheHeaderOffersSetStaffCapacityOnlyWithAProject(t *testing.T) {
	if got := header(nil, "").GetActions(); len(got) != 0 {
		t.Fatalf("no projects, actions %v", got)
	}
	got := header([]project{{ID: "p1"}}, "p1").GetActions()
	if len(got) != 1 || got[0].GetHref() != "/projects/capacity/set?project=p1" || !got[0].GetDrawer() || got[0].GetPrimary() {
		t.Fatalf("actions %v", got)
	}
}

func TestNoProjectIsOneEmptyLineAndOneProjectHasNoTabs(t *testing.T) {
	empty := page(Role{}, nil, "", nil, "2027", url.Values{}).GetBlocks()
	if len(empty) != 1 || empty[0].GetEmpty() != emptyNote {
		t.Fatalf("no projects: %v", empty)
	}
	one := page(Role{}, []project{{ID: "p1", Name: "A", Code: "SP-A"}}, "p1", nil, "2027", url.Values{}).GetBlocks()
	if len(one) != 2 || one[1].GetPanel().GetTitle() != "A SP-A" {
		t.Fatalf("one project: %v", one)
	}
}
