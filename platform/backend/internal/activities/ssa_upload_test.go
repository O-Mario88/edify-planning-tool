package activities

import (
	"errors"
	"net/url"
	"testing"
	"time"
)

func eightScores(value string) url.Values {
	form := url.Values{}
	for _, code := range rules.order {
		form.Set("score_"+code, value)
	}
	return form
}

func TestTheSSADrawerReadsItsEightScores(t *testing.T) {
	scores, refusal, err := visitScoresOf(eightScores(" 5.5 "))
	if err != nil || refusal != "" || len(scores) != 8 || scores[0].score != 5.5 || scores[0].intervention != rules.order[0] {
		t.Fatalf("got %v, %q, %v", scores, refusal, err)
	}
	if scores, refusal, err := visitScoresOf(url.Values{"notes": {"x"}}); err != nil || refusal != "" || scores != nil {
		t.Fatalf("no scores: %v, %q, %v", scores, refusal, err)
	}
	some := url.Values{"score_" + rules.order[0]: {"4"}}
	if _, refusal, _ := visitScoresOf(some); refusal != "Error: All 8 scores must be provided if manual entry is selected." {
		t.Fatalf("some: %q", refusal)
	}
	bad := eightScores("4")
	bad.Set("score_"+rules.order[2], "four")
	if _, refusal, _ := visitScoresOf(bad); refusal != "Error: Score must be numeric" {
		t.Fatalf("bad: %q", refusal)
	}
	odd := eightScores("4")
	odd.Set("score_"+rules.order[1], "nan")
	if _, _, err := visitScoresOf(odd); !errors.Is(err, ErrHandOn) {
		t.Fatalf("a float Go does not read the same way is handed on: %v", err)
	}
}

func TestAnSSAScoreIsBetweenZeroAndTen(t *testing.T) {
	if got := scoreRangeRefusal([]visitScore{{"leadership", 10}, {"enrolment", 0}}); got != "" {
		t.Fatalf("got %q", got)
	}
	if got := scoreRangeRefusal([]visitScore{{"leadership", 10.5}}); got != "Score for leadership must be between 0 and 10" {
		t.Fatalf("got %q", got)
	}
}

func TestAnSSAIsDatedAndAveragedAsTheExistingUpload(t *testing.T) {
	for month, want := range map[time.Month]string{time.October: "Q1", time.January: "Q2", time.June: "Q3", time.September: "Q4"} {
		if got := ssaQuarter(time.Date(2026, month, 3, 0, 0, 0, 0, time.UTC)); got != want {
			t.Fatalf("%s: got %s", month, got)
		}
	}
	tie := []visitScore{{"a", 5}, {"b", 5}, {"c", 5}, {"d", 5}, {"e", 5}, {"f", 5}, {"g", 6}, {"h", 6}}
	if got := ssaAverage(tie); got != 5.2 {
		t.Fatalf("round half to even: got %v", got)
	}
	if got := ssaAverage([]visitScore{{"a", 7}, {"b", 8}, {"c", 8}}); got != 7.7 {
		t.Fatalf("got %v", got)
	}
}

func TestTheSSAYearRulesSayTheirWords(t *testing.T) {
	if got, want := ssaSequenceRefusal("2027"), "Cannot upload SSA for the current FY (2027) — the previous FY (2026) SSA for this school exists but is not verified. Verify it first."; got != want {
		t.Fatalf("got %q", got)
	}
	if got, want := ssaDuplicateMessage("2027"), "SSA already exists for this school for FY2027. The record was not added."; got != want {
		t.Fatalf("got %q", got)
	}
}

func TestAVisitsSSAIsDatedByTheVisit(t *testing.T) {
	planned := time.Date(2026, 11, 18, 0, 0, 0, 0, time.UTC)
	delivered := time.Date(2026, 11, 19, 0, 0, 0, 0, time.UTC)
	started := time.Date(2026, 11, 19, 22, 30, 0, 0, time.UTC) // 01:30 on the 20th in Nairobi
	nairobi, _ := time.LoadLocation("Africa/Nairobi")
	if got := ssaVisitDay(&delivered, &started, planned, nairobi); !got.Equal(delivered) {
		t.Fatalf("delivered: got %v", got)
	}
	if got := ssaVisitDay(nil, &started, planned, nairobi); got.Format(time.DateOnly) != "2026-11-20" {
		t.Fatalf("started: got %v", got)
	}
	if got := ssaVisitDay(nil, nil, planned, nairobi); !got.Equal(planned) {
		t.Fatalf("planned: got %v", got)
	}
}
