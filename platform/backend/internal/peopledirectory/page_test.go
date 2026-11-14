package peopledirectory

import (
	"slices"
	"testing"
)

func TestThePageAskedForFollowsDjangosPaginator(t *testing.T) {
	cases := []struct {
		asked     string
		total     int
		want, all int
	}{
		{"", 57, 1, 2}, {"2", 57, 2, 2}, {"9", 57, 2, 2}, {"0", 57, 2, 2}, {"x", 57, 1, 2}, {" 2 ", 57, 2, 2}, {"", 0, 1, 1},
	}
	for _, c := range cases {
		if n, p := pageOf(c.asked, c.total, 50); n != c.want || p != c.all {
			t.Errorf("pageOf(%q, %d) = %d of %d", c.asked, c.total, n, p)
		}
	}
	if got := elided(6, 10); !slices.Equal(got, []int{1, 0, 5, 6, 7, 0, 10}) {
		t.Errorf("elided: %v", got)
	}
}

func TestARowReadsItsRolePlaceAndOnboarding(t *testing.T) {
	x := person{role: "Program Lead", district: "Mukono", country: "Uganda", hasProfile: true, onboarding: "pending", reportsTo: []string{"Zoe", "Abel"}}
	if got := place(x); got != "Programme Lead Mukono · Uganda · reports to Abel, Zoe" {
		t.Errorf("place: %q", got)
	}
	if place(person{role: "Odd"}) != "Odd No place recorded" || onboarding(x) != "Pending" || onboarding(person{}) != "no_profile" {
		t.Error("fallbacks")
	}
	if initials("ab cd") != "AB" || initials("") != "??" || initials("é") != "É" {
		t.Error("initials")
	}
}
