package projectmonitoring

import (
	"slices"
	"testing"
	"time"
)

func at(v float64) *float64 { return &v }

func TestAFocusLineReadsAsTheDrawerWritesIt(t *testing.T) {
	day := time.Date(2026, 3, 1, 0, 0, 0, 0, time.UTC)
	cases := []struct {
		name string
		f    focus
		want string
	}{
		{"baseline, no follow-up", focus{Label: "Leadership", Baseline: at(3.9)}, "Leadership: 3.9 · no confirmed follow-up yet"},
		{"no baseline", focus{Label: "Leadership"}, "Leadership: – · no confirmed follow-up yet"},
		{"up", focus{Label: "Leadership", Baseline: at(3), Latest: at(4.5), LatestOn: &day}, "Leadership: 3.0 → 4.5 (+1.5)"},
		{"down", focus{Label: "Leadership", Baseline: at(5), Latest: at(4.5), LatestOn: &day}, "Leadership: 5.0 → 4.5 (-0.5)"},
		{"flat", focus{Label: "Leadership", Baseline: at(5), Latest: at(5), LatestOn: &day}, "Leadership: 5.0 → 5.0 (0.0)"},
		{"latest with no baseline", focus{Label: "Leadership", Latest: at(5), LatestOn: &day}, "Leadership: – → 5.0"},
	}
	for _, tc := range cases {
		if got := focusLine(tc.f); got != tc.want {
			t.Errorf("%s: got %q, want %q", tc.name, got, tc.want)
		}
	}
}

func TestASchoolWithNoWorkReadsAsAwaitingTheCoordinator(t *testing.T) {
	enrolled := time.Date(2026, 11, 9, 0, 0, 0, 0, time.UTC)
	row := schoolRow{
		e:            enrolment{SchoolName: "Goma", SchoolCode: "1699", District: "Mukono", StartDate: &enrolled},
		ProjectName:  "EdTech",
		AddedBy:      "—",
		Purpose:      "Support",
		Intervention: "Leadership",
		ImpactLabel:  "Awaiting delivery",
		Focus:        []focus{{Label: "Leadership", Baseline: at(3.9)}},
	}
	form := schoolFormOf(row, "EdTech", "Allan", false)
	if form.Subtitle != "EdTech · 1699 · Mukono" || form.Status != "Awaiting Project Coordinator Action" {
		t.Fatalf("head: %+v", form)
	}
	if form.AddedBy != "— · 9 Nov 2026" || form.Coordinator != "Allan" {
		t.Fatalf("who: %+v", form)
	}
	if form.AddedFor != "Added for Support · Leadership." {
		t.Fatalf("added for: %q", form.AddedFor)
	}
	if !slices.Equal(form.Focus, []string{"Leadership: 3.9 · no confirmed follow-up yet"}) || form.Controls {
		t.Fatalf("focus: %+v", form)
	}

	row.Purpose, row.Intervention = "", ""
	row.e.District = ""
	bare := schoolFormOf(row, "EdTech", "Allan", true)
	if bare.AddedFor != "" || bare.Subtitle != "EdTech · 1699" || !bare.Controls {
		t.Fatalf("bare: %+v", bare)
	}
	row.Purpose = "Support"
	if got := schoolFormOf(row, "EdTech", "Allan", true).AddedFor; got != "Added for Support." {
		t.Fatalf("purpose alone: %q", got)
	}
	row.Purpose, row.Intervention = "", "Leadership"
	if got := schoolFormOf(row, "EdTech", "Allan", true).AddedFor; got != "Added for Leadership." {
		t.Fatalf("intervention alone: %q", got)
	}
}
