package ccelead

import (
	"testing"
	"time"
)

func day0(y int, m time.Month, d int) time.Time { return time.Date(y, m, d, 0, 0, 0, 0, time.UTC) }

func TestTheRhythmJudgesEachRuleAsTheRoleSetsIt(t *testing.T) {
	today := day0(2026, 11, 14)
	rows := evaluate([]held{
		{kind: "vp_cce_checkin", on: day0(2026, 11, 11)},
		{kind: "rvp_meeting", on: day0(2026, 9, 1)},
		{kind: "cd_annual_planning", on: day0(2026, 9, 15), country: "Uganda"},
	}, today, []leadInReach{{staffID: "pl", name: "Programme Lead"}}, []string{"Uganda", "Kenya"}, map[string]bool{"Kenya": true})
	states := map[string]string{}
	for _, r := range rows {
		states[r.label+"|"+r.subject] = r.state
	}
	for key, want := range map[string]string{
		"VP of CCE check-in|Region":                    "done",
		"Meeting with the RVP|Region":                  "overdue",
		"Coaching conversation|Programme Lead":         "due_soon",
		"Annual programming and budget input|Kenya":    "missed",
		"Annual programming and budget input|Uganda":   "open",
		"Country Director quarterly review|Uganda":     "open",
		"Cross-region Programme Lead convening|Region": "open",
	} {
		if states[key] != want {
			t.Errorf("%s: %q, want %q", key, states[key], want)
		}
	}
	if rows[0].state != "overdue" && rows[0].state != "missed" {
		t.Errorf("the worst is not first: %+v", rows[0])
	}
}

func TestAQuarterIsTheOperationalYearsQuarter(t *testing.T) {
	start, end := quarterRange(day0(2026, 11, 14))
	if !start.Equal(day0(2026, 10, 1)) || !end.Equal(day0(2027, 1, 1)) {
		t.Errorf("quarter %v–%v", start, end)
	}
	if opFY(day0(2026, 10, 1)) != 2027 || opFY(day0(2026, 9, 30)) != 2026 {
		t.Error("operational year")
	}
}
