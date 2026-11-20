package activities

import (
	"context"
	"errors"
	"net/url"
	"os"
	"path/filepath"
	"regexp"
	"slices"
	"testing"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
)

// A visit's ID is normalised as normalize_salesforce_id normalises it, and
// anything outside ASCII, which Python's upper() may read differently, is
// left to the existing application.
func TestTheSalesforceIDIsNormalisedAsTheExistingReservationDoes(t *testing.T) {
	for raw, want := range map[string]string{
		"sv-990001":        "SV-990001",
		" sve - abc123 ":   "SVE-ABC123",
		"sve-\tab\x00c123": "SVE-ABC123",
		"a0b1c2d3e4f5g6h":  "A0B1C2D3E4F5G6H",
		"SV-\x7f12\x1c3":   "SV-123",
		"ts-998877":        "TS-998877",
		"sv-12 3":          "",
		"straße-12345":     "",
	} {
		got, ok := normalizeSalesforceID(raw)
		if want == "" {
			if ok {
				t.Errorf("%q: normalised to %q, want it handed on", raw, got)
			}
			continue
		}
		if !ok || got != want {
			t.Errorf("%q: %q (%v), want %q", raw, got, ok, want)
		}
	}
}

// The forms a visit's ID may take are SV-…, SVE-… and the record's own
// 15- or 18-character ID; anything else is refused in the existing words,
// and a training's TS- ID is the view's own notice, handed on.
func TestAVisitsIDIsJudgedAsTheExistingCompletionJudgesIt(t *testing.T) {
	s := &Service{}
	for raw, want := range map[string]string{
		"SV-990001":          "",
		"sve-abc":            "",
		"A0B1C2D3E4F5G6H":    "",
		"A0B1C2D3E4F5G6HIJK": "",
		"":                   salesforceFormsRefusal,
		"SV-12":              salesforceFormsRefusal,
		"990001":             salesforceFormsRefusal,
		"A0B1C2D3E4F5G6HI":   salesforceFormsRefusal,
		"TS-998877":          "hand on",
	} {
		pl := &completionPlan{raw: raw}
		err := s.judgeSalesforceID(pl)
		var refusal *Refusal
		switch {
		case want == "" && err != nil:
			t.Errorf("%q: %v, want it accepted", raw, err)
		case want == "hand on" && !errors.Is(err, ErrHandOn):
			t.Errorf("%q: %v, want a hand-on", raw, err)
		case want != "" && want != "hand on" && (!errors.As(err, &refusal) || refusal.Message != want):
			t.Errorf("%q: %v, want %q", raw, err, want)
		}
	}
}

// The day done is today unless given, never a day in another form or after
// today (both the view's notice, handed on); a day other than the planned
// one moves the work and its money, and is handed on too.
func TestTheCompletedDayIsReadAsCompletionDayReadsIt(t *testing.T) {
	kampala, err := time.LoadLocation("Africa/Kampala")
	if err != nil {
		t.Fatal(err)
	}
	// 22:30 UTC on 19 November is already 20 November in Kampala.
	s := &Service{kampala: kampala, now: func() time.Time { return time.Date(2026, 11, 19, 22, 30, 0, 0, time.UTC) }}
	planned := time.Date(2026, 11, 20, 0, 0, 0, 0, time.UTC)
	for raw, handedOn := range map[string]bool{
		"": false, "2026-11-20": false, " 2026-11-20 ": false,
		"2026-11-21": true, "20 Nov 2026": true, "2026-02-30": true, "2026-11-19": true,
	} {
		pl := &completionPlan{a: completedVisit{plannedDate: planned}}
		err := s.readCompletionForm(pl, url.Values{"actual_delivery_date": {raw}, "salesforce_id": {"SV-990001"}})
		if handedOn != errors.Is(err, ErrHandOn) || (!handedOn && err != nil) {
			t.Errorf("%q: %v, want handed on: %v", raw, err, handedOn)
		}
	}
}

// What the drawer posted is what the audit row records: the stripped ID as
// typed, the counts read as int() reads them, and the observation fields
// only when the drawer sent them (complete() leaves absent ones alone).
func TestTheCompletionPayloadIsTheExistingOne(t *testing.T) {
	s := &Service{kampala: time.UTC, now: func() time.Time { return time.Date(2026, 11, 20, 9, 0, 0, 0, time.UTC) }}
	pl := &completionPlan{a: completedVisit{plannedDate: time.Date(2026, 11, 20, 0, 0, 0, 0, time.UTC)}}
	form := url.Values{
		"actual_delivery_date": {"2026-11-20"}, "salesforce_id": {" sv-990001 "}, "teachers_attended": {"3"},
		"leaders_attended": {""}, "actual_outcome": {"  outcome "}, "follow_up_note": {""},
	}
	if err := s.readCompletionForm(pl, form); err != nil {
		t.Fatal(err)
	}
	if pl.raw != "sv-990001" || pl.normalized != "SV-990001" || pl.teachers != 3 || pl.leaders != 0 {
		t.Fatalf("read %q %q %d %d", pl.raw, pl.normalized, pl.teachers, pl.leaders)
	}
	if pl.outcome == nil || *pl.outcome != "outcome" || pl.observations != nil || pl.notes == nil || *pl.notes != "" {
		t.Fatalf("observations read as %v %v %v", pl.outcome, pl.observations, pl.notes)
	}
	if _, ok := pl.payload["actualObservations"]; ok {
		t.Error("an observation the drawer did not send is in the payload")
	}
	if pl.payload["salesforceId"] != "sv-990001" || pl.payload["trainingSalesforceId"] != "sv-990001" ||
		pl.payload["teachersAttended"] != 3 || pl.payload["ssaCollected"] != false {
		t.Errorf("payload %v", pl.payload)
	}
}

// A training's ID, an accountability, a register, a purpose given at
// completion and a count Python's int() would read differently all take the
// completion out of 183.1's case.
func TestTheCompletionHandsOnWhatItDoesNotMake(t *testing.T) {
	s := &Service{kampala: time.UTC, now: func() time.Time { return time.Date(2026, 11, 20, 9, 0, 0, 0, time.UTC) }}
	base := func() url.Values {
		return url.Values{"actual_delivery_date": {"2026-11-20"}, "salesforce_id": {"SV-990001"}}
	}
	for name, change := range map[string]func(url.Values){
		"a training's ID":     func(f url.Values) { f.Set("training_salesforce_id", "TS-1") },
		"an accountability":   func(f url.Values) { f.Set("netsuite_id", "NS-1") },
		"a register":          func(f url.Values) { f.Set("attended_school_ids", "s1") },
		"visiting schools":    func(f url.Values) { f.Set("visiting_register", "1") },
		"a purpose":           func(f url.Values) { f.Set("purpose_type", "ssa_support") },
		"a signed count":      func(f url.Values) { f.Set("teachers_attended", "-1") },
		"a spaced count":      func(f url.Values) { f.Set("leaders_attended", " 2") },
		"the school feedback": func(f url.Values) { f.Set("feedback_finding", "") },
	} {
		form := base()
		change(form)
		pl := &completionPlan{a: completedVisit{plannedDate: time.Date(2026, 11, 20, 0, 0, 0, 0, time.UTC)}}
		if err := s.readCompletionForm(pl, form); !errors.Is(err, ErrHandOn) {
			t.Errorf("%s: %v, want a hand-on", name, err)
		}
	}
}

// Anyone but an officer working in their own seat is handed on before any
// record is read: a lead's own work is approved as it lands, an acting
// appointment is another seat.
func TestTheCompletionIsHandedOnBeforeAnyRead(t *testing.T) {
	s, err := NewService(nil, nil, nil, nil)
	if err != nil {
		t.Fatal(err)
	}
	for name, p := range map[string]auth.Principal{
		"acting":           {Account: auth.Account{StaffProfileID: "s", ActiveRole: "CCEO", InActingAppointment: true}},
		"no staff profile": {Account: auth.Account{ActiveRole: "CCEO"}},
		"a lead":           {Account: auth.Account{StaffProfileID: "s", ActiveRole: "Program Lead"}},
		"an officer who leads": {Account: auth.Account{StaffProfileID: "s", ActiveRole: "CCEO",
			Roles: []string{"CCEO", "Program Lead"}}},
	} {
		pl, err := s.prepareCompletion(context.Background(), p, CompleteRequest{ActivityID: "a"}, Origin{})
		if !errors.Is(err, ErrHandOn) || pl != nil {
			t.Errorf("%s: %v, want a hand-on with no plan", name, err)
		}
	}
}

// The function that hands a visit in takes exactly the visit types the Go
// save takes: the SQL names them as a literal, so this holds the two together.
func TestTheHandInFunctionNamesTheCompletedVisitTypes(t *testing.T) {
	raw, err := os.ReadFile(filepath.FromSlash("../../../deploy/db/completion_roles.sql"))
	if err != nil {
		t.Fatal(err)
	}
	array := regexp.MustCompile(`(?s)activity_type = ANY \(ARRAY\[(.*?)\]::varchar\[\]\)`).FindSubmatch(raw)
	if array == nil {
		t.Fatal("the function's visit types were not found")
	}
	named := []string{}
	for _, m := range regexp.MustCompile(`'([a-z_]+)'`).FindAllSubmatch(array[1], -1) {
		named = append(named, string(m[1]))
	}
	want := slices.Clone(completedVisitTypes)
	slices.Sort(named)
	slices.Sort(want)
	if !slices.Equal(named, want) {
		t.Fatalf("the function takes %v; the Go save takes %v", named, want)
	}
}
