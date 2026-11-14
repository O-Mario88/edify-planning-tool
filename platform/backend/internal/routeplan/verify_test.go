package routeplan

import (
	"strings"
	"testing"
)

func TestCheckReport(t *testing.T) {
	kampala := &LatLng{0.3476, 32.5825}
	cases := []struct {
		name string
		in   ReportInput
		want string
	}{
		{"wrong with a typed point", ReportInput{Kind: "wrong", PointSource: "typed", Proposed: kampala, Note: "Pin is in the lake"}, ""},
		{"wrong with no point", ReportInput{Kind: "wrong", Note: "Pin is across the river"}, ""},
		{"missing needs a point", ReportInput{Kind: "missing", Note: "No pin"}, "Give the school's location"},
		{"device reading", ReportInput{Kind: "missing", PointSource: "device", Proposed: kampala, AccuracyM: 12, Note: "At the gate"}, ""},
		{"device too coarse", ReportInput{Kind: "missing", PointSource: "device", Proposed: kampala, AccuracyM: 900, Note: "At the gate"}, "only accurate to 900 m"},
		{"device with no accuracy", ReportInput{Kind: "missing", PointSource: "device", Proposed: kampala, Note: "At the gate"}, "did not say how accurate"},
		{"outside Uganda", ReportInput{Kind: "wrong", PointSource: "typed", Proposed: &LatLng{51.5, -0.12}, Note: "x"}, "not in Uganda"},
		{"zero point", ReportInput{Kind: "wrong", PointSource: "typed", Proposed: &LatLng{0, 0}, Note: "x"}, "not in Uganda"},
		{"typed with no point", ReportInput{Kind: "wrong", PointSource: "typed", Note: "x"}, "Give the school's location"},
		{"note required", ReportInput{Kind: "wrong", Note: "   "}, "Say what is wrong"},
		{"unknown kind", ReportInput{Kind: "moved", Note: "x"}, "wrong or missing"},
		{"unknown source", ReportInput{Kind: "wrong", PointSource: "map", Proposed: kampala, Note: "x"}, "could not be sent"},
		{"long note", ReportInput{Kind: "wrong", Note: strings.Repeat("a", noteMaxRunes+1)}, "under 1000"},
		{"long directions", ReportInput{Kind: "wrong", Note: "x", AccessNote: strings.Repeat("a", accessNoteMaxRunes+1)}, "under 300"},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			_, msg := CheckReport(c.in)
			if c.want == "" && msg != "" {
				t.Fatalf("refused: %q", msg)
			}
			if !strings.Contains(msg, c.want) {
				t.Fatalf("message %q, want it to say %q", msg, c.want)
			}
		})
	}
}

func TestCheckReportCleansWhatItKeeps(t *testing.T) {
	out, msg := CheckReport(ReportInput{Kind: "wrong", PointSource: "typed", Proposed: &LatLng{0.35, 32.6}, AccuracyM: 40, Note: "  moved  ", AccessNote: " by the church "})
	if msg != "" {
		t.Fatal(msg)
	}
	if out.Note != "moved" || out.AccessNote != "by the church" || out.AccuracyM != 0 {
		t.Fatalf("kept %+v", out)
	}
	out, _ = CheckReport(ReportInput{Kind: "wrong", Proposed: &LatLng{0.35, 32.6}, Note: "x"})
	if out.PointSource != "none" || out.Proposed != nil {
		t.Fatalf("a report with no source carried a point: %+v", out)
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

func TestReviewers(t *testing.T) {
	for _, role := range []string{"Program Lead", "CountryDirector", "Admin"} {
		if !MayReview(role) {
			t.Errorf("%s should review", role)
		}
	}
	for _, role := range []string{"CCEO", "ImpactAssessment", "Partner", ""} {
		if MayReview(role) {
			t.Errorf("%s should not review", role)
		}
	}
}

func TestNewIDIsAUUID(t *testing.T) {
	id, err := newID()
	if err != nil {
		t.Fatal(err)
	}
	if len(id) != 36 || id[14] != '4' || strings.Count(id, "-") != 4 {
		t.Fatalf("id %q", id)
	}
}
