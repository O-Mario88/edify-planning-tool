package routeplan

import (
	"slices"
	"strings"
	"testing"
	"time"
)

var (
	testNow  = time.Date(2026, 11, 14, 9, 0, 0, 0, time.UTC)
	kampala1 = LatLng{0.3476, 32.5825}
)

func gps(kind string, acc float64) CaptureInput {
	p := kampala1
	return CaptureInput{Target: "school", Kind: kind, Source: "device", Point: &p, AccuracyM: acc,
		CapturedAt: testNow.Add(-time.Minute), SampleCount: 5, SpreadM: 3, Reason: "Pin was wrong"}
}

func TestCheckCapture(t *testing.T) {
	far := LatLng{51.5, -0.12}
	cases := []struct {
		name string
		in   CaptureInput
		want string
	}{
		{"a first GPS location", gps("new", 8), ""},
		{"a correction by GPS", gps("correction", 8), ""},
		{"a correction needs a reason", func() CaptureInput { c := gps("correction", 8); c.Reason = " "; return c }(), "Say why"},
		{"a new location needs a point", CaptureInput{Kind: "new", Source: "none"}, "Give the school's location"},
		{"a correction may come without a point", CaptureInput{Kind: "correction", Source: "none", Reason: "Pin across the river"}, ""},
		{"outside Uganda", func() CaptureInput { c := gps("new", 8); c.Point = &far; return c }(), "not in Uganda"},
		{"no accuracy", gps("new", 0), "did not say how accurate"},
		{"too coarse", gps("new", 1500), "only accurate to 1500 m"},
		{"no capture time", func() CaptureInput { c := gps("new", 8); c.CapturedAt = time.Time{}; return c }(), "no time"},
		{"an unknown target", func() CaptureInput { c := gps("new", 8); c.Target = "gate"; return c }(), "could not be sent"},
		{"an unknown kind", func() CaptureInput { c := gps("move", 8); return c }(), "could not be sent"},
		{"a confirmation needs nothing", CaptureInput{Kind: "confirm"}, ""},
		{"long directions", func() CaptureInput { c := gps("new", 8); c.AccessNote = strings.Repeat("a", 301); return c }(), "under 300"},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			_, msg := CheckCapture(c.in, DefaultPolicy)
			if c.want == "" && msg != "" {
				t.Fatalf("refused: %q", msg)
			}
			if !strings.Contains(msg, c.want) {
				t.Fatalf("message %q, want %q", msg, c.want)
			}
		})
	}
}

func TestCheckCaptureCleansWhatItKeeps(t *testing.T) {
	typed := gps("new", 40)
	typed.Source = "typed"
	out, msg := CheckCapture(typed, DefaultPolicy)
	if msg != "" || out.AccuracyM != 0 || out.SampleCount != 0 || out.Target != "school" {
		t.Fatalf("typed kept device figures: %+v %q", out, msg)
	}
	out, _ = CheckCapture(CaptureInput{Kind: "confirm", Source: "device", Point: &kampala1, AccuracyM: 5}, DefaultPolicy)
	if out.Point != nil || out.Source != "none" {
		t.Fatalf("a confirmation kept a point: %+v", out)
	}
}

func TestDecide(t *testing.T) {
	none := SchoolState{}
	placed := SchoolState{Placed: true, At: LatLng{0.3480, 32.5830}, Version: 2}
	cases := []struct {
		name   string
		in     func() CaptureInput
		st     SchoolState
		role   string
		status string
		flags  []string
	}{
		{"a CCEO's first GPS location at 8 m is accepted", func() CaptureInput { return gps("new", 8) }, none, "CCEO", CaptureAccepted, nil},
		{"a PL's first location at 20 m is accepted", func() CaptureInput { return gps("new", 20) }, none, "Program Lead", CaptureAccepted, nil},
		{"35 m needs review", func() CaptureInput { return gps("new", 35) }, none, "CCEO", CapturePending, []string{"accuracy_fair"}},
		{"80 m needs review", func() CaptureInput { return gps("new", 80) }, none, "CCEO", CapturePending, []string{"accuracy_poor"}},
		{"readings that disagree", func() CaptureInput { c := gps("new", 8); c.SpreadM = 40; return c }, none, "CCEO", CapturePending, []string{"unstable"}},
		{"every correction is reviewed", func() CaptureInput { c := gps("correction", 5); c.BaseVersion = 2; return c }, placed, "Program Lead", CapturePending, []string{"correction"}},
		{"a new capture where a point appeared meanwhile", func() CaptureInput { return gps("new", 5) }, placed, "CCEO", CapturePending, []string{"correction", "version_conflict"}},
		{"captured against an older version", func() CaptureInput { c := gps("correction", 5); c.BaseVersion = 1; return c }, placed, "CCEO", CapturePending, []string{"correction", "version_conflict"}},
		{"another report is waiting", func() CaptureInput { return gps("new", 5) }, SchoolState{Pending: 1}, "CCEO", CapturePending, []string{"competing"}},
		{"an entrance is reviewed", func() CaptureInput { c := gps("new", 5); c.Target = "entrance"; return c }, none, "CCEO", CapturePending, []string{"entrance"}},
		{"a typed point is reviewed", func() CaptureInput { c := gps("new", 0); c.Source = "typed"; return c }, none, "CCEO", CapturePending, []string{"typed_point"}},
		{"a role that does not capture", func() CaptureInput { c := gps("new", 5); c.Source = "typed"; return c }, none, "CountryDirector", CapturePending, []string{"reporter_role", "typed_point"}},
		{"synced long after", func() CaptureInput { c := gps("new", 5); c.CapturedAt = testNow.Add(-40 * 24 * time.Hour); return c }, none, "CCEO", CapturePending, []string{"stale_capture"}},
		{"a clock running ahead", func() CaptureInput { c := gps("new", 5); c.CapturedAt = testNow.Add(time.Hour); return c }, none, "CCEO", CapturePending, []string{"clock_skew"}},
		{"far from its district", func() CaptureInput { return gps("new", 5) }, SchoolState{DistrictCentre: &LatLng{2.77, 32.30}}, "CCEO", CapturePending, []string{"far_from_district"}},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			d := Decide(c.in(), c.st, c.role, testNow, DefaultPolicy)
			if d.Status != c.status {
				t.Fatalf("status %s, want %s (flags %v)", d.Status, c.status, d.Flags)
			}
			if !slices.Equal(d.Flags, c.flags) {
				t.Fatalf("flags %v, want %v", d.Flags, c.flags)
			}
		})
	}
}

func TestALargeMoveIsReviewedNeverRefused(t *testing.T) {
	c := gps("correction", 5)
	c.BaseVersion = 3
	d := Decide(c, SchoolState{Placed: true, At: LatLng{0.45, 32.70}, Version: 3}, "Program Lead", testNow, DefaultPolicy)
	if d.Status != CapturePending || !slices.Contains(d.Flags, "large_move") || d.DisplacementM == nil || *d.DisplacementM < 15000 {
		t.Fatalf("decision %+v", d)
	}
}

func TestAConfirmationMovesNothing(t *testing.T) {
	d := Decide(CaptureInput{Kind: "confirm", BaseVersion: 2}, SchoolState{Placed: true, Version: 2}, "CCEO", testNow, DefaultPolicy)
	if d.Status != CaptureNoted || len(d.Flags) != 0 {
		t.Fatalf("decision %+v", d)
	}
	d = Decide(CaptureInput{Kind: "confirm", BaseVersion: 1}, SchoolState{Placed: true, Version: 2}, "CCEO", testNow, DefaultPolicy)
	if !slices.Equal(d.Flags, []string{"version_conflict"}) {
		t.Fatalf("an answer about an old point: %+v", d)
	}
}

func TestReviewMessage(t *testing.T) {
	cases := []struct {
		name                                       string
		reviewer, reporter, status, decision, note string
		want                                       string
	}{
		{"approve", "pl", "cceo", "pending", "approve", "", ""},
		{"reject with a note", "pl", "cceo", "pending", "reject", "Pin is right", ""},
		{"reject needs a note", "pl", "cceo", "pending", "reject", " ", "Say why"},
		{"own report", "pl", "pl", "pending", "approve", "", "Someone else"},
		{"already decided", "pl", "cceo", "approved", "approve", "", "already been decided"},
		{"accepted at once", "pl", "cceo", "accepted", "reject", "x", "already been decided"},
		{"unknown decision", "pl", "cceo", "pending", "maybe", "", "approve or reject"},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			msg := ReviewMessage(c.reviewer, c.reporter, c.status, c.decision, c.note)
			if c.want == "" && msg != "" {
				t.Fatalf("refused: %q", msg)
			}
			if !strings.Contains(msg, c.want) {
				t.Fatalf("message %q, want %q", msg, c.want)
			}
		})
	}
}

func TestRoles(t *testing.T) {
	for _, role := range []string{"Program Lead", "CountryDirector", "Admin"} {
		if !MayReview(role) {
			t.Errorf("%s should review", role)
		}
	}
	for _, role := range []string{"CCEO", "ImpactAssessment", "PartnerAdmin", "ClusterLeader", ""} {
		if MayReview(role) {
			t.Errorf("%s should not review", role)
		}
	}
	for _, role := range []string{"CCEO", "Program Lead"} {
		if !MayCapture(role) {
			t.Errorf("%s should capture", role)
		}
	}
	for _, role := range []string{"PartnerAdmin", "PartnerFieldOfficer", "ClusterLeader", "Admin"} {
		if MayCapture(role) {
			t.Errorf("%s should not capture yet", role)
		}
	}
}

func TestIDs(t *testing.T) {
	id, err := newID()
	if err != nil || !uuidPattern.MatchString(id) {
		t.Fatalf("id %q %v", id, err)
	}
	if keyID("u1", "k") != keyID("u1", "k") || keyID("u1", "k") == keyID("u2", "k") || !uuidPattern.MatchString(keyID("u1", "k")) {
		t.Fatal("a report key does not map to one id per person")
	}
}
