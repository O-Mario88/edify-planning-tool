package actionsweep

import "testing"

// parse_oversight_condition_key reads the record a key the oversight pages
// wrote names; any other key is not the sweep's to settle by record.
func TestParseKeyReadsOnlyTheOversightKeys(t *testing.T) {
	for key, want := range map[string][2]string{
		"oversight|activity_overdue|activity|a1":               {"activity", "a1"},
		"partner_oversight|assignment_returned|assignment|pa1": {"assignment", "pa1"},
		"planning_gap|planning_visit_gap|school|s1|2027":       {"", ""},
		"urgent|no_ssa|s1|2027":                                {"", ""},
	} {
		kind, id, _ := parseKey(key)
		if [2]string{kind, id} != want {
			t.Errorf("%q: %q %q, want %v", key, kind, id, want)
		}
	}
}

// ssa_score_band's labels at and around each floor.
func TestBandIsTheExistingScoreBand(t *testing.T) {
	for score, want := range map[float64]string{10: "Strong", 8: "Strong", 7.9: "Improving", 6: "Improving", 5.9: "Warning", 5: "Warning", 4.9: "Critical", 0: "Critical"} {
		if got := band(score); got != want {
			t.Errorf("%v: %q, want %q", score, got, want)
		}
	}
}
