package ccelead

import (
	"testing"
	"time"
)

func onDay(s string) *time.Time {
	t, _ := time.Parse(time.DateOnly, s)
	return &t
}

func TestACoachingRecordReadsTheLeadsState(t *testing.T) {
	today := *onDay("2026-11-14")
	cases := []struct {
		name string
		x    coachingRecord
		want string
	}{
		{"draft", coachingRecord{}, "Not shared yet"},
		{"shared", coachingRecord{shared: onDay("2026-11-01")}, "Awaiting the officer"},
		{"acknowledged", coachingRecord{shared: onDay("2026-11-01"), acknowledged: onDay("2026-11-02")}, "Acknowledged"},
		{"due today", coachingRecord{acknowledged: onDay("2026-11-02"), due: onDay("2026-11-14")}, "Follow-up due"},
		{"due later", coachingRecord{due: onDay("2026-11-15")}, "Not shared yet"},
		{"closed", coachingRecord{due: onDay("2026-11-01"), done: onDay("2026-11-03")}, "Not shared yet"},
	}
	for _, c := range cases {
		if got := coachingState(c.x, today); got != c.want {
			t.Errorf("%s: %q, want %q", c.name, got, c.want)
		}
	}
	if stateWhere("follow_up", "$3") != " AND c.follow_up_due <= $3::date AND c.follow_up_done_at IS NULL" || stateWhere("odd", "") != "" {
		t.Error("state conditions")
	}
}

func TestAReaderNeverChoosesDrafts(t *testing.T) {
	reader := teamFilters(false, map[string]string{}, "", "", "draft")
	if len(reader) != 2 || reader[1].Value != "" || len(reader[1].Options) != 4 {
		t.Errorf("reader's state select: %v", reader)
	}
	lead := teamFilters(true, map[string]string{"s2": "Bea", "s1": "Ann"}, "s1", "", "draft")
	if len(lead) != 3 || lead[0].Options[1].Label != "Ann" || lead[2].Value != "draft" || len(lead[2].Options) != 5 {
		t.Errorf("lead's selects: %v", lead)
	}
}
