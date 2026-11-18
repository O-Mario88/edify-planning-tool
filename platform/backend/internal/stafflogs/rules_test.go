package stafflogs

import "testing"

func TestAStatusIsWrittenAsStatusLabelWritesIt(t *testing.T) {
	cases := map[string]string{
		"awaiting_ia_verification": "Awaiting IA Verification",
		"follow_up_visit":          "Follow Up Visit",
		"submitted_to_pl":          "Submitted To PL",
		"IN-PROGRESS":              "In Progress",
		"netsuite_sync":            "NetSuite Sync",
		"":                         "",
	}
	for in, want := range cases {
		if got := statusLabel(in); got != want {
			t.Errorf("statusLabel(%q) = %q, want %q", in, got, want)
		}
	}
}
