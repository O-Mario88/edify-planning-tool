package presence

import (
	"encoding/json"
	"testing"
	"time"
)

// samples are the readings the existing functions gave for the exported
// requests and beats (export_presence_rules).
type samples struct {
	Footprints []struct {
		Method     string   `json:"method"`
		Path       string   `json:"path"`
		HTMX       bool     `json:"htmx"`
		CurrentURL string   `json:"current_url"`
		Footprint  []string `json:"footprint"`
	} `json:"footprint_samples"`
	Describes []struct {
		Page      string `json:"page"`
		Action    string `json:"action"`
		Section   string `json:"section"`
		WorkingOn string `json:"working_on"`
	} `json:"describe_samples"`
}

func loadSamples(t *testing.T) samples {
	t.Helper()
	var s samples
	if err := json.Unmarshal(rulesJSON, &s); err != nil {
		t.Fatal(err)
	}
	if len(s.Footprints) == 0 || len(s.Describes) == 0 {
		t.Fatal("rules.json carries no samples")
	}
	return s
}

func TestFootprintIsTheMiddlewaresReading(t *testing.T) {
	for _, c := range loadSamples(t).Footprints {
		page, action, ok := Footprint(Request{Method: c.Method, Path: c.Path, HTMX: c.HTMX, CurrentURL: c.CurrentURL})
		if want := c.Footprint != nil; ok != want {
			t.Errorf("%s %q: footprint %v, want %v", c.Method, c.Path, ok, want)
			continue
		}
		if ok && (page != c.Footprint[0] || action != c.Footprint[1]) {
			t.Errorf("%s %q: got (%q, %q), want %q", c.Method, c.Path, page, action, c.Footprint)
		}
	}
}

func TestDescribeIsPresenceLabels(t *testing.T) {
	for _, c := range loadSamples(t).Describes {
		section, working := Describe(c.Page, c.Action)
		if section != c.Section || working != c.WorkingOn {
			t.Errorf("%q %q: got (%q, %q), want (%q, %q)", c.Page, c.Action, section, working, c.Section, c.WorkingOn)
		}
	}
}

func TestTouchesWritesNeverBackgroundNeverABearersRead(t *testing.T) {
	cases := []struct {
		name string
		r    Request
		want bool
	}{
		{"a post", Request{Method: "POST", Path: "/today/snooze", HTMX: true}, true},
		{"a bearer's post", Request{Method: "POST", Path: "/api/mobile/v1/drawer", Bearer: true}, true},
		{"a bearer's read", Request{Method: "GET", Path: "/api/mobile/v1/page", Bearer: true}, false},
		{"a read with no method", Request{Path: "/api/mobile/v1/page", Bearer: true}, false},
		{"a head", Request{Method: "HEAD", Bearer: true}, false},
		{"a redraw read in the background", Request{Method: "GET", Path: "/today/panel", HTMX: true, Background: true}, false},
		{"a post in the background", Request{Method: "POST", Path: "/today/snooze", Background: true}, false},
	}
	for _, c := range cases {
		if got := Touches(c.r); got != c.want {
			t.Errorf("%s: %v, want %v", c.name, got, c.want)
		}
	}
}

func TestPlanGuardsOnTheBeatReadAndCreditsItsSlot(t *testing.T) {
	seen := time.Date(2026, 11, 13, 14, 0, 0, 123000, time.UTC)
	post := Request{Method: "POST", Path: "/today/unsnooze", HTMX: true}
	cases := []struct {
		name      string
		r         Request
		prev      previous
		guarded   bool
		section   string
		working   string
		footprint bool
		login     string
	}{
		{"a beat on a page is credited", post, previous{seen: &seen, path: "/dashboard", action: "GET /today/panel", login: "le1"},
			true, "Dashboard", "Viewing Dashboard", true, ""},
		{"no beat yet", post, previous{path: "/dashboard"}, false, "", "", true, ""},
		{"a beat with no page", post, previous{seen: &seen}, false, "", "", true, ""},
		{"an untracked page is no page", post, previous{seen: &seen, path: "/sw.js"}, false, "", "", true, ""},
		{"a bearer's person carries no beat", Request{Method: "POST", Path: "/api/mobile/v1/drawer", Bearer: true},
			previous{seen: &seen, path: "/dashboard"}, false, "", "", false, ""},
		{"the session's sign-in is cut to the column", Request{Method: "POST", Path: "/x", LoginID: "123456789012345678901234567890XYZ"},
			previous{}, false, "", "", true, "123456789012345678901234567890"},
	}
	for _, c := range cases {
		b := plan("u1", c.r, c.prev)
		if (b.Guard != nil) != c.guarded || b.Section != c.section || b.Working != c.working ||
			b.HasFootprint != c.footprint || b.LoginID != c.login {
			t.Errorf("%s: got %+v", c.name, b)
		}
		if c.guarded && (!b.Guard.Equal(seen) || b.PreviousLogin != "le1") {
			t.Errorf("%s: guard %v login %q", c.name, b.Guard, b.PreviousLogin)
		}
	}
}

func TestThresholdsAreTheExistingOnes(t *testing.T) {
	if rules.IdleSeconds != 300 || rules.FinalBeatSeconds != 30 || rules.OnlineWindowSeconds != 600 ||
		BackgroundHeader() != "X-Edify-Background" || rules.TimeZone == "" {
		t.Fatalf("rules: %+v", rules)
	}
}
