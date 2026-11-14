package closurequality

import (
	"net/url"
	"slices"
	"testing"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
)

func TestIntcommaGroupsThousands(t *testing.T) {
	for n, want := range map[int]string{0: "0", 999: "999", 1200: "1,200", 1234567: "1,234,567", -4500: "-4,500"} {
		if got := intcomma(n); got != want {
			t.Errorf("intcomma(%d) = %q, want %q", n, got, want)
		}
	}
}

func TestAClosureNamesEachOfItsQualityFlags(t *testing.T) {
	eff := time.Date(2026, 9, 15, 0, 0, 0, 0, time.UTC)
	c := closureRow{reason: "unconfirmed", dupStatus: rules.UnresolvedDup, effective: eff, createdDay: eff.AddDate(0, 0, 60), underReview: 2}
	want := []string{"Closed with its duplicate flag unresolved", "Closed without confirmation", "No enrolment recorded", "2 awaiting finance", "Recorded 60 days after closing"}
	if got := flags(c); !slices.Equal(got, want) {
		t.Errorf("flags = %v", got)
	}
	n := 40
	if got := flags(closureRow{reason: "financial", effective: eff, createdDay: eff.AddDate(0, 0, 30), enrolment: &n}); len(got) != 0 {
		t.Errorf("a clean closure has no flags: %v", got)
	}
}

func TestNoClosuresReadsTheEmptyMessageBetweenTheShellPanels(t *testing.T) {
	r := page(auth.Principal{}, "all", "2027", summary{}, nil, nil, nil, url.Values{})
	if len(r.Blocks) != 5 || r.Blocks[3].GetEmpty() == "" || r.Blocks[4].GetPanel().Items[0].GetText() != "All data is provisional and subject to verification." {
		t.Errorf("blocks: %v", r.Blocks)
	}
	if f := r.Blocks[2].GetFilters().Filters[0]; f.Value != "all" || f.Options[1].Label != "FY 2027" {
		t.Errorf("period: %v", f)
	}
}
