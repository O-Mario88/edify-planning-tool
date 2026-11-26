package workplan

import "testing"

func TestThePlanSummaryUnitCostIsTheAverageRoundedHalfUpToTheCent(t *testing.T) {
	for _, c := range []struct {
		cost  int64
		count int
		want  float64
	}{{100, 3, 33.33}, {200, 3, 66.67}, {1, 8, 0.13}, {90000, 2, 45000}, {0, 0, 0}} {
		if got := unitCostValue(c.cost, c.count); got != c.want {
			t.Fatalf("%d over %d: %v, want %v", c.cost, c.count, got, c.want)
		}
	}
}
