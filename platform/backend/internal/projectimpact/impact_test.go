package projectimpact

import (
	"testing"
	"time"
)

func day(y int, m time.Month, d int) time.Time { return time.Date(y, m, d, 0, 0, 0, 0, time.UTC) }

func intp(n int) *int { return &n }

func floatp(f float64) *float64 { return &f }

func TestChangeBetweenFollowsTheChangeRules(t *testing.T) {
	cases := []struct {
		name          string
		before, after float64
		direction     string
		threshold     *float64
		want          string
	}{
		{"any rise improves with no threshold", 4.2, 4.21, "improve", nil, improved},
		{"any fall declines with no threshold", 4.2, 4.1, "", nil, declined},
		{"no movement is no change", 5, 5, "improve", nil, noChange},
		{"below the threshold is no change", 4.4, 4.0, "improve", floatp(1), noChange},
		{"reaching the threshold improves", 4.0, 5.0, "improve", floatp(1), improved},
		{"a negative threshold reads as its size", 6.0, 4.9, "improve", floatp(-1), declined},
		{"holding strong is success", 2.9, 9.4, maintainDirection, nil, maintainedStrong},
		{"dropping out of strong is a decline", 7.6, 6.5, maintainDirection, nil, declined},
	}
	for _, c := range cases {
		if got := changeBetween(c.before, c.after, c.direction, c.threshold); got != c.want {
			t.Errorf("%s: changeBetween = %s, want %s", c.name, got, c.want)
		}
	}
}

func TestJudgeKeepsMissingEvidenceApartFromAClosedWindow(t *testing.T) {
	follow := &reading{score: 7}
	if got := judge(4, nil, "improve", "", nil, false); got != notYetMeasurable {
		t.Fatalf("closed window = %s", got)
	}
	if got := judge(4, nil, "improve", "", nil, true); got != insufficient {
		t.Fatalf("open window, no follow-up = %s", got)
	}
	if got := judge(4, follow, "improve", eligibilityOnly, nil, true); got != insufficient {
		t.Fatalf("eligibility only with a follow-up = %s", got)
	}
	if got := judge(4, follow, "improve", "", nil, true); got != improved {
		t.Fatalf("measured = %s", got)
	}
}

func TestFollowUpForTakesTheFirstReadingInsideTheWindow(t *testing.T) {
	readings := []reading{
		{recordID: "early", on: day(2026, 2, 10)},
		{recordID: "inside", on: day(2026, 4, 1)},
		{recordID: "later", on: day(2026, 6, 1)},
	}
	after := day(2026, 2, 1)
	if got := followUpFor(readings, after, intp(30), intp(100)); got == nil || got.recordID != "inside" {
		t.Fatalf("followUpFor = %+v", got)
	}
	if got := followUpFor(readings, after, intp(30), intp(40)); got != nil {
		t.Fatalf("a reading past the window was taken: %+v", got)
	}
	if got := followUpFor(readings, after, intp(0), nil); got == nil || got.recordID != "early" {
		t.Fatalf("a zero-day bound is no bound: %+v", got)
	}
}

func TestQualifyingIsTheLatestReadingOnOrBeforeTheStart(t *testing.T) {
	readings := []reading{{recordID: "a", on: day(2025, 10, 1)}, {recordID: "b", on: day(2026, 1, 15)}, {recordID: "c", on: day(2026, 3, 1)}}
	if got := qualifying(readings, day(2026, 1, 15)); got == nil || got.recordID != "b" {
		t.Fatalf("qualifying = %+v", got)
	}
	if got := qualifying(readings, day(2025, 9, 30)); got != nil {
		t.Fatalf("a reading after the start became a baseline: %+v", got)
	}
}

func TestScoreBandIsTheFourLabels(t *testing.T) {
	for score, want := range map[float64]string{10: "Strong", 8: "Strong", 7.99: "Improving", 6: "Improving", 5: "Warning", 4.99: "Critical"} {
		if got := scoreBand(score); got != want {
			t.Errorf("scoreBand(%v) = %s, want %s", score, got, want)
		}
	}
}
