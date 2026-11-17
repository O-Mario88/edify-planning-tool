package coreschools

import (
	"errors"
	"slices"
	"testing"
)

// A page number reads as Django's paginator reads it: blank is the first
// page, a number past the end is the last, and a word that is not a number is
// the first, unless it is one the paginator would read differently.
func TestThePageNumberIsReadAsThePaginatorReadsIt(t *testing.T) {
	cases := []struct {
		raw  string
		want int
	}{
		{"", 1}, {"2", 2}, {"9", 3}, {"0", 3}, {"007", 3}, {"abc", 1}, {"last", 1},
	}
	for _, c := range cases {
		got, err := pageNumber(c.raw, 3)
		if err != nil || got != c.want {
			t.Errorf("%q: %d, %v; want %d", c.raw, got, err, c.want)
		}
	}
	for _, raw := range []string{" 2", "+2", "-1", "1_0", "٢"} {
		if _, err := pageNumber(raw, 3); !errors.Is(err, errPassOn) {
			t.Errorf("%q: %v, want a hand-on", raw, err)
		}
	}
}

// The pager shows every page up to four, then the ends around the current
// page with a gap (0) between.
func TestThePagerElidesAsTheExistingPagerDoes(t *testing.T) {
	cases := []struct {
		number, pages int
		want          []int
	}{
		{1, 1, []int{1}},
		{2, 4, []int{1, 2, 3, 4}},
		{1, 10, []int{1, 2, 0, 10}},
		{5, 10, []int{1, 0, 4, 5, 6, 0, 10}},
		{9, 10, []int{1, 0, 8, 9, 10}},
		{7, 10, []int{1, 0, 6, 7, 8, 9, 10}},
	}
	for _, c := range cases {
		if got := elided(c.number, c.pages); !slices.Equal(got, c.want) {
			t.Errorf("page %d of %d: %v, want %v", c.number, c.pages, got, c.want)
		}
	}
}

// The queue's one control reads as the next step it leads to.
func TestTheNextActionReadsAsItsStep(t *testing.T) {
	cases := map[string]string{
		"Requires Cluster":    "Cluster required",
		"Assessment Required": "Upload Assessment",
		"Package planned":     "Package planned",
		"Graduation Review":   "Review SSA",
		"Core Assessment":     "Review SSA",
		"V2 Visit":            "Schedule Visit (V2)",
		"T3 Training":         "Schedule Training (T3)",
	}
	for next, want := range cases {
		if got := nextAction(next); got != want {
			t.Errorf("%q: %q, want %q", next, got, want)
		}
	}
}
