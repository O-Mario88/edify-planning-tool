package iapages

import (
	"testing"
	"time"
)

func f64(v float64) *float64 { return &v }

func at(day int) *time.Time {
	t := time.Date(2026, time.November, day, 0, 0, 0, 0, time.UTC)
	return &t
}

// An enrolment's state reads as evidence_row reads it: a missing previous FY
// SSA first, then a measured change, a follow-up under review, and the
// follow-up window.
func TestAnEnrolmentsStateIsTheEvidenceRowsState(t *testing.T) {
	today := time.Date(2026, time.November, 17, 0, 0, 0, 0, time.UTC)
	measured := enrolment{baselineSet: true, baselineOK: true, baselineScore: f64(4.5), baselineAt: at(1),
		followUpSet: true, followUpOK: true, followUpScore: f64(7.25), followUpAt: at(10), classification: "improved",
		intervention: "leadership"}
	review := measured
	review.classification = "not_yet_measurable"
	sameDay := measured
	sameDay.followUpAt = at(1)
	outOfRange := measured
	outOfRange.baselineScore = f64(11)
	waiting := enrolment{baselineSet: true, baselineOK: true, baselineScore: f64(5), baselineAt: at(1)}
	overdue, due, upcoming := waiting, waiting, waiting
	overdue.due, due.due, upcoming.due = at(14), at(17), at(26)
	cases := []struct {
		name   string
		e      enrolment
		state  string
		status string
	}{
		{"measured", measured, "improved", "Improved"},
		{"under review", review, "evidence_review", "Evidence review"},
		{"a follow-up no later than the baseline", sameDay, "evidence_review", "Evidence review"},
		{"a baseline score out of range", outOfRange, "baseline_missing", "Previous FY SSA missing"},
		{"no follow-up date", waiting, "not_scheduled", "Current FY SSA missing"},
		{"overdue", overdue, "overdue", "Current FY SSA missing (overdue)"},
		{"due today", due, "due", "Current FY SSA missing (due today)"},
		{"to come", upcoming, "upcoming", "Current FY SSA missing (upcoming)"},
	}
	for _, c := range cases {
		r := c.e.row(today)
		if r.state != c.state || r.status != c.status {
			t.Errorf("%s: %q %q, want %q %q", c.name, r.state, r.status, c.state, c.status)
		}
	}
	if r := measured.row(today); r.delta == nil || *r.delta != 2.75 || r.intervention != "Leadership" {
		t.Errorf("the measured change: %+v", r)
	}
	if r := (enrolment{intervention: "made_up"}).row(today); r.intervention != "Not mapped" {
		t.Errorf("an unmapped domain: %q", r.intervention)
	}
}

// Shares and medians round as Python rounds: half to even.
func TestSharesAndMediansRoundAsPythonRounds(t *testing.T) {
	if got := *share(1, 8); got != 12 {
		t.Errorf("1 of 8: %d", got)
	}
	if got := *share(3, 8); got != 38 {
		t.Errorf("3 of 8: %d", got)
	}
	if share(1, 0) != nil {
		t.Error("a share of nothing is None")
	}
	if got := *medianOf([]float64{1, 2, 4, 7}); got != 3 {
		t.Errorf("an even list: %v", got)
	}
	if medianOf(nil) != nil {
		t.Error("a median of nothing is None")
	}
}

// A domain with fewer schools than the evidence floor shows its counts and
// withholds its change.
func TestADomainBelowTheFloorWithholdsItsChange(t *testing.T) {
	rows := []evidenceRow{{code: "leadership", schoolID: "a", state: "improved", delta: f64(1)}}
	for _, d := range cohortDomains(rows) {
		if d.name == "Leadership" && (!d.withheld || d.delta != nil || d.pairs != 1 || *d.improvedPct != 100) {
			t.Errorf("leadership: %+v", d)
		}
		if d.name != "Leadership" && (d.withheld || d.pairs != 0) {
			t.Errorf("%s: %+v", d.name, d)
		}
	}
}
