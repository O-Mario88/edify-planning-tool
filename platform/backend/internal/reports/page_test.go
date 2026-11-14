package reports

import (
	"testing"
	"time"
)

func TestFiguresRoundAsThePageDoes(t *testing.T) {
	if pyRound(92.5) != 92 || pyRound(93.5) != 94 || pyRound(79.2) != 79 {
		t.Errorf("round(): %d %d %d", pyRound(92.5), pyRound(93.5), pyRound(79.2))
	}
	if floatformat0(280.5) != "281" || fixed0(50.5) != "50" || fixed0(150) != "150" {
		t.Errorf("formats: %s %s", floatformat0(280.5), fixed0(50.5))
	}
	if status(70) != "On Track" || status(69) != "At Risk" || status(49) != "Off Track" {
		t.Error("thresholds")
	}
}

func TestThePeriodsDimWhatIsStillToCome(t *testing.T) {
	today := time.Date(2026, 11, 14, 0, 0, 0, 0, time.UTC)
	ps := periods(today, "2027", "2027")
	if len(ps) != 7 || ps[0].chevron != "Nov 2026" || ps[0].filter != "a.month = 11" || ps[0].dimmed {
		t.Fatalf("month: %+v", ps[0])
	}
	if ps[1].dimmed || !ps[2].dimmed || !ps[3].dimmed || !ps[4].dimmed || ps[6].dimmed || ps[6].chevron != "FY 2027" {
		t.Errorf("current year: %+v", ps)
	}
	past := periods(today, "2026", "2027")
	if !past[0].dimmed || past[2].dimmed || past[3].dimmed {
		t.Errorf("past year: %+v", past)
	}
}
