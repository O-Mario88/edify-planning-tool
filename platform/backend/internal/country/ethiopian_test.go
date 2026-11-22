package country

import (
	"testing"
	"time"
)

func TestEthiopianCalendarConversions(t *testing.T) {
	cases := []struct {
		greg string
		want EthiopianDate
	}{
		// Ethiopian New Year 2019 EC (non-leap previous year)
		{"2026-09-11", EthiopianDate{Year: 2019, Month: 1, Day: 1}},
		// Current migration date: 22 Nov 2026 = Hidar 13, 2019 EC
		{"2026-11-22", EthiopianDate{Year: 2019, Month: 3, Day: 13}},
		// Ethiopian leap day: Pagume 6, 2015 EC = 11 Sep 2023
		{"2023-09-11", EthiopianDate{Year: 2015, Month: 13, Day: 6}},
		// Ethiopian New Year 2016 EC (after leap year) = 12 Sep 2023
		{"2023-09-12", EthiopianDate{Year: 2016, Month: 1, Day: 1}},
	}
	for _, tc := range cases {
		g, _ := time.Parse(time.DateOnly, tc.greg)
		got := ToEthiopian(g)
		if got != tc.want {
			t.Errorf("ToEthiopian(%s) = %+v, want %+v", tc.greg, got, tc.want)
		}
		back := got.ToGregorian()
		if back.Format(time.DateOnly) != tc.greg {
			t.Errorf("ToGregorian(%+v) = %s, want %s", got, back.Format(time.DateOnly), tc.greg)
		}
	}

	g, _ := time.Parse(time.DateOnly, "2026-11-22")
	if s := FormatInCalendar(g, "ethiopian", "en"); s != "Hidar 13, 2019 EC" {
		t.Fatalf("en format: got %q", s)
	}
	if s := FormatInCalendar(g, "ethiopian", "am"); s != "ኅዳር 13, 2019 ዓ.ም" {
		t.Fatalf("am format: got %q", s)
	}
}
