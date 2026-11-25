package btcases

import (
	"testing"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pydecimal"
)

func TestAddMonthsClampsToTheMonthsLastDay(t *testing.T) {
	d := func(y int, m time.Month, day int) time.Time { return time.Date(y, m, day, 0, 0, 0, 0, time.UTC) }
	cases := []struct {
		from   time.Time
		months int
		want   time.Time
	}{
		{d(2026, 1, 31), 1, d(2026, 2, 28)},
		{d(2026, 11, 30), 3, d(2027, 2, 28)},
		{d(2024, 1, 31), 1, d(2024, 2, 29)},
		{d(2026, 12, 15), 12, d(2027, 12, 15)},
	}
	for _, c := range cases {
		if got := addMonths(c.from, c.months); !got.Equal(c.want) {
			t.Errorf("addMonths(%s, %d) = %s, want %s", c.from.Format(time.DateOnly), c.months, got.Format(time.DateOnly),
				c.want.Format(time.DateOnly))
		}
	}
}

// The expected strings are Python's f"{Decimal(x):,.0f}".
func TestGroupedPrintsAsPythonFormats(t *testing.T) {
	for in, want := range map[string]string{"1234567.5": "1,234,568", "2.5": "2", "0": "0", "-1500.5": "-1,500", "999.49": "999"} {
		if got := grouped(pydecimal.MustParse(in)); got != want {
			t.Errorf("grouped(%s) = %s, want %s", in, got, want)
		}
	}
}
