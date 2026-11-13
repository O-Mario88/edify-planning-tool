package hrregister

import "testing"

// Python's own answers: [round(x, 1) for x in (0.25, 0.35, 0.45, 3.25, 3.35,
// 2.675, 3.75, 4.05)].
func TestScoresRoundAsPythonRoundsThem(t *testing.T) {
	for x, want := range map[float64]string{
		0.25: "0.2", 0.35: "0.3", 0.45: "0.5", 3.25: "3.2", 3.35: "3.4", 2.675: "2.7", 3.75: "3.8", 4.05: "4.0",
	} {
		if got := pyStr1(pyRound1(x)); got != want {
			t.Errorf("round(%v, 1) = %s, want %s", x, got, want)
		}
	}
}

func TestNoResultShowsUnderTheAnonymityFloor(t *testing.T) {
	few := make([]map[string]any, rules.PulseMinResponses-1)
	for i := range few {
		few[i] = map[string]any{"purpose": 5.0}
	}
	if r := results(few); r.shown || r.overall != nil || r.count != len(few) {
		t.Errorf("under the floor: %+v", r)
	}
	enough := append(few, map[string]any{"purpose": 0.0, "support": 3.0})
	r := results(enough)
	if !r.shown || r.overall == nil || pyStr1(*r.overall) != "4.0" {
		t.Errorf("at the floor: %+v", r)
	}
}
