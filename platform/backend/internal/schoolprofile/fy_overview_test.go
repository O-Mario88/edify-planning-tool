package schoolprofile

import "testing"

func TestTheYearsActivityRateRoundsAsPythonRounds(t *testing.T) {
	cases := []struct {
		f    fyFigures
		want int
	}{
		{fyFigures{activities: 8, completed: 1}, 12},
		{fyFigures{activities: 8, completed: 3}, 38},
		{fyFigures{activities: 0, completed: 0}, 0},
		{fyFigures{activities: 264, completed: 260}, 98},
	}
	for _, tc := range cases {
		if got := tc.f.rate(); got != tc.want {
			t.Errorf("%d of %d: got %d, want %d", tc.f.completed, tc.f.activities, got, tc.want)
		}
	}
}
