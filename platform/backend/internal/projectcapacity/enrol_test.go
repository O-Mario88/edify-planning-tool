package projectcapacity

import "testing"

// ssa_score_band's labels at its edges.
func TestABaselineIsBandedAsTheSSAIs(t *testing.T) {
	for score, want := range map[float64]string{10: "Strong", 8: "Strong", 7.9: "Improving", 6: "Improving", 5: "Warning", 4.9: "Critical"} {
		if got := ssaBand(score); got != want {
			t.Fatalf("%v = %s, want %s", score, got, want)
		}
	}
}

// ProjectStatus' label, and Active for no status.
func TestAPausedProjectSaysSo(t *testing.T) {
	if statusLabel("paused") != "Paused" || statusLabel("under_review") != "Under Review" || statusLabel("") != "Active" {
		t.Fatal("status labels")
	}
	if schoolTypeLabel("core_graduate") != "Core Graduate" || schoolTypeLabel("odd") != "odd" {
		t.Fatal("school type labels")
	}
}
