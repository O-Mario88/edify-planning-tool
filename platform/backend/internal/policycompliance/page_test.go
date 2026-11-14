package policycompliance

import "testing"

func TestReadingTimeIsWrittenAsTheReportWritesIt(t *testing.T) {
	for seconds, want := range map[int]string{0: "0s", -4: "0s", 45: "45s", 60: "1m 0s", 200: "3m 20s", 3599: "59m 59s", 3600: "1h 0m", 4000: "1h 6m"} {
		if got := humanise(seconds); got != want {
			t.Errorf("humanise(%d) = %q, want %q", seconds, got, want)
		}
	}
}

func TestViewerCompletionIsDerivedFromReadingNeverFromTheAnswer(t *testing.T) {
	for _, c := range []struct {
		a    ack
		want string
	}{
		{ack{Offline: true, Required: 120}, "completed_offline"},
		{ack{Active: 500}, "not_monitored"},
		{ack{Active: 120, Required: 120}, "completed"},
		{ack{Active: 0, Required: 120}, "not_read"},
		{ack{Active: 45, Required: 120, State: "agreed"}, "partial"},
	} {
		if got := completion(c.a); got != c.want {
			t.Errorf("%+v = %q, want %q", c.a, got, c.want)
		}
	}
}

func TestARegisteredCountCarriesThousandsSeparators(t *testing.T) {
	for n, want := range map[int]string{0: "0", 999: "999", 1000: "1,000", 1234567: "1,234,567"} {
		if got := thousands(n); got != want {
			t.Errorf("thousands(%d) = %q, want %q", n, got, want)
		}
	}
}

func TestAnUnknownFilterValueSelectsNoOption(t *testing.T) {
	bar := filterBar(filters{Document: "gone", State: "bogus"}, []option{{"p1", "Code"}}).GetFilters().GetFilters()
	if bar[0].GetValue() != "" || bar[1].GetValue() != "" {
		t.Fatalf("filters %v", bar)
	}
	bar = filterBar(filters{Document: "p1", State: "agreed"}, []option{{"p1", "Code"}}).GetFilters().GetFilters()
	if bar[0].GetValue() != "p1" || bar[1].GetValue() != "agreed" {
		t.Fatalf("filters %v", bar)
	}
}
