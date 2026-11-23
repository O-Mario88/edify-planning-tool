package routeplan

import "testing"

func TestLocationSourceNamesWhereTheRecordCameFrom(t *testing.T) {
	cases := []struct {
		name     string
		capture  string
		reviewed bool
		placed   bool
		want     string
	}{
		{name: "a device reading", capture: "device", placed: true, want: "Device GPS (Field)"},
		{name: "a typed point", capture: "typed", placed: true, want: "Entered by hand"},
		{name: "a capture outranks an older report", capture: "device", reviewed: true, placed: true, want: "Device GPS (Field)"},
		{name: "an approved report", reviewed: true, placed: true, want: "Approved location report"},
		{name: "only the directory's point", placed: true, want: "School Directory"},
		{name: "no location at all", want: ""},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			if got := locationSource(tc.capture, tc.reviewed, tc.placed); got != tc.want {
				t.Fatalf("locationSource(%q, %v, %v) = %q, want %q", tc.capture, tc.reviewed, tc.placed, got, tc.want)
			}
		})
	}
}
