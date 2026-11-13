package activities

import (
	"encoding/json"
	"errors"
	"net/url"
	"testing"
	"time"
)

// docs/migration/48: the online Group Training's rules, before any read.

func onlineForm() url.Values {
	f := groupForm()
	f.Set("delivery_mode", "online")
	for _, material := range []string{"printing_pages", "photocopy_pages", "photocopy_copies"} {
		f.Del(material)
	}
	return f
}

func TestTheOnlineDrawerIsTakenAsAnOnlineGroupTraining(t *testing.T) {
	req, ok := GroupTrainingRequestFromForm(onlineForm())
	if !ok || !req.Online || req.ClusterID != "c1" || len(req.Invited) != 2 {
		t.Fatalf("the online drawer's form: %v %+v", ok, req)
	}
	if req, ok := GroupTrainingRequestFromForm(groupForm()); !ok || req.Online {
		t.Fatalf("the in-person drawer posts no delivery mode: %v %+v", ok, req)
	}
	handedOn := map[string]func(url.Values){
		"another mode":             func(f url.Values) { f.Set("delivery_mode", "hybrid") },
		"a blank mode":             func(f url.Values) { f.Set("delivery_mode", " ") },
		"two modes":                func(f url.Values) { f["delivery_mode"] = []string{"online", "online"} },
		"a partner facilitates it": func(f url.Values) { f.Set("facilitating_partner_id", "p1") },
	}
	for name, change := range handedOn {
		f := onlineForm()
		change(f)
		if _, ok := GroupTrainingRequestFromForm(f); ok {
			t.Errorf("%s: must be handed on", name)
		}
	}
}

func TestTheRevisionsPeriodsFollowThePlannedDay(t *testing.T) {
	day := func(s string) time.Time {
		d, err := time.Parse(time.DateOnly, s)
		if err != nil {
			t.Fatal(err)
		}
		return d
	}
	tests := []struct {
		planned, weekStart, weekEnd, quarter, fy string
		month                                    int
	}{
		{"2026-11-26", "2026-11-23", "2026-11-29", "Q1", "2027", 11}, // a Thursday
		{"2026-11-23", "2026-11-23", "2026-11-29", "Q1", "2027", 11}, // a Monday
		{"2026-11-29", "2026-11-23", "2026-11-29", "Q1", "2027", 11}, // a Sunday
		{"2026-10-01", "2026-09-28", "2026-10-04", "Q1", "2027", 10}, // the FY's first day
		{"2026-09-30", "2026-09-28", "2026-10-04", "Q4", "2026", 9},
		{"2027-01-01", "2026-12-28", "2027-01-03", "Q2", "2027", 1},
	}
	for _, tt := range tests {
		p := periodsOf(day(tt.planned))
		if p.weekStart.Format(time.DateOnly) != tt.weekStart || p.weekEnd.Format(time.DateOnly) != tt.weekEnd ||
			p.month != tt.month || p.quarter != tt.quarter || p.fy != tt.fy {
			t.Errorf("%s: %+v", tt.planned, p)
		}
	}
}

func freeRevision() *OnlineCost {
	id, version := "card", 1
	raw := func(s string) json.RawMessage { return json.RawMessage(s) }
	return &OnlineCost{
		OperationalCardID: &id, OperationalCardVersion: &version, ReferenceBreakdown: raw("[]"),
		OperationalBreakdown: raw("[]"), CalculationInputs: raw(`{"fy": "2027"}`), Warnings: raw("[]"),
		MissingConfiguration: raw("[]"),
	}
}

func TestGoWritesOnlyAFreeRevisionPricedAgainstACard(t *testing.T) {
	if !freeRevision().takeable() {
		t.Fatal("a free revision against a card is Go's")
	}
	var none *OnlineCost
	if none.takeable() {
		t.Error("no revision answered")
	}
	notTaken := map[string]func(*OnlineCost){
		"cost missing":             func(c *OnlineCost) { c.CostMissing = true },
		"a price":                  func(c *OnlineCost) { c.OperationalCost = 1 },
		"no operational card":      func(c *OnlineCost) { c.OperationalCardID = nil },
		"no card version":          func(c *OnlineCost) { c.OperationalCardVersion = nil },
		"no inputs":                func(c *OnlineCost) { c.CalculationInputs = nil },
		"null warnings":            func(c *OnlineCost) { c.Warnings = json.RawMessage("null") },
		"no missing configuration": func(c *OnlineCost) { c.MissingConfiguration = json.RawMessage("") },
	}
	for name, change := range notTaken {
		c := freeRevision()
		change(c)
		if c.takeable() {
			t.Errorf("%s: must be handed on", name)
		}
	}
}

func TestAnOnlineSessionTakesThePlannedDaysYearAndJoinsNoDay(t *testing.T) {
	planned, _ := time.Parse(time.DateOnly, "2026-10-01")
	row := activityRow{plannedDate: planned, fy: "2026", quarter: "Q4",
		group: &groupColumns{clusterID: "c1", online: true}}
	if err := takeOnline(&row, DayVerdict{Online: freeRevision()}); err != nil {
		t.Fatal(err)
	}
	if row.fy != "2027" || row.quarter != "Q1" {
		t.Errorf("the row's year: %s %s", row.fy, row.quarter)
	}
	for name, verdict := range map[string]DayVerdict{
		"pooled":    {Pooled: true, Online: freeRevision()},
		"a refusal": {Refusal: "no", Online: freeRevision()},
		"no answer": {},
	} {
		r := row
		if err := takeOnline(&r, verdict); !errors.Is(err, ErrHandOn) {
			t.Errorf("%s: %v", name, err)
		}
	}
	names := map[string]any{}
	for _, f := range append(row.groupFields(), row.onlineFields()...) {
		names[f.name] = f.value
	}
	if names["programme_delivery_mode"] != "online" || names["week_start_date"] != "2026-09-28" ||
		names["fiscal_year"] != "2027" || names["month"] != 10 {
		t.Errorf("the online columns: %v", names)
	}
	row.group.online = false
	for _, f := range append(row.groupFields(), row.onlineFields()...) {
		if f.name == "programme_delivery_mode" || f.name == "fiscal_year" {
			t.Errorf("an in-person session writes %s", f.name)
		}
	}
}
