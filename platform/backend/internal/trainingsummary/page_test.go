package trainingsummary

import (
	"context"
	"net/url"
	"testing"
	"time"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
)

func ptr(n int) *int { return &n }

func texts(cells []*screensv1.PageCell) []string {
	out := []string{}
	for _, c := range cells {
		out = append(out, c.GetText()+"|"+c.GetHref()+"|"+c.GetTone())
	}
	return out
}

func equal(t *testing.T, got, want []string) {
	t.Helper()
	if len(got) != len(want) {
		t.Fatalf("got %d cells %q, want %d %q", len(got), got, len(want), want)
	}
	for i := range want {
		if got[i] != want[i] {
			t.Errorf("cell %d: got %q, want %q", i, got[i], want[i])
		}
	}
}

func TestIntcommaGroupsThousandsAsHumanizeDoes(t *testing.T) {
	for n, want := range map[int]string{0: "0", 7: "7", 999: "999", 1000: "1,000", 1234567: "1,234,567", -4500: "-4,500"} {
		if got := intcomma(n); got != want {
			t.Errorf("intcomma(%d) = %q, want %q", n, got, want)
		}
	}
}

func TestACellsStateAndToneFollowItsCeiling(t *testing.T) {
	for _, c := range []struct {
		cell        cell
		state, tone string
	}{
		{cell{schools: 3}, "unset", ""},
		{cell{schools: 3, limit: ptr(2)}, "above", "danger"},
		{cell{schools: 2, limit: ptr(2)}, "reached", "success"},
		{cell{schools: 1, limit: ptr(2)}, "below", "warning"},
	} {
		if got := c.cell.state(); got != c.state {
			t.Errorf("state = %q, want %q", got, c.state)
		}
		if got := rules.Tones.Cell[c.cell.state()]; got != c.tone {
			t.Errorf("tone of %s = %q, want %q", c.state, got, c.tone)
		}
	}
	if !(cell{}).blank() || (cell{limit: ptr(0)}).blank() {
		t.Error("only a cell with no ceiling and no school is blank")
	}
}

func TestACountryReaderOpensEveryFigureAndAdminSetsTheCeiling(t *testing.T) {
	s := summary{fy: "2027", countryLinks: true, maySetCountry: true}
	r := row{name: "Leadership", mode: "In-School Training", trainingID: "t1", countryCeiling: ptr(5), countryCeilingID: "cc1",
		planned: 7, staffPlanned: 4, partner: 3, partnerScheduled: 1,
		cells: []cell{{staffID: "s1"}, {staffID: "s2", schools: 2, limit: ptr(2)}, {staffID: "s3", limit: ptr(4), ceilingID: "c3"}}}
	link := "/team-planning-oversight/?view=trainings&tab=schools&fy=2027&training=t1&show="
	equal(t, texts(rowCells(s, r)), []string{
		"Leadership||", "In-School Training||",
		"7 / 5|" + link + "covered|danger",
		"4|" + link + "staff|",
		"2|" + link + "awaiting|warning",
		"0|" + link + "remaining|",
		"0||",
		"2 / 2|/training-summary/schools?staff=s2&training=t1&fy=2027|success",
		"0 / 4||warning",
	})
}

func TestAProgrammeLeadReadsTheCountryAndOpensTheirOfficersCeilings(t *testing.T) {
	s := summary{fy: "2026", maySet: true}
	r := row{name: "Leadership", trainingID: "t1", planned: 0, cells: []cell{{staffID: "s3", limit: ptr(4), ceilingID: "c3"}}}
	equal(t, texts(rowCells(s, r)), []string{
		"Leadership||", "||", "0 / Not set||", "0||", "0||", "—||",
		"0 / 4|/training-ceilings/c3/edit|warning",
	})
	r.countryCeiling, r.countryCeilingID, r.planned = ptr(1200), "cc", 1200
	if got := rowCells(s, r)[2]; got.GetText() != "1,200 / 1,200" || got.GetTone() != "success" || got.GetHref() != "" {
		t.Errorf("Total Covered at the ceiling = %q %q %q", got.GetText(), got.GetTone(), got.GetHref())
	}
	if got := rowCells(s, r)[5].GetText(); got != "0" {
		t.Errorf("Remaining at the ceiling = %q, want 0", got)
	}
}

func TestTheCountryCeilingCellOffersSetOnlyToWhoSetsIt(t *testing.T) {
	r := row{trainingID: "t1"}
	if text, href := countryCeiling(summary{fy: "2027", maySetCountry: true}, r); text != "Set" ||
		href != "/training-ceilings/country/set?training=t1&fy=2027" {
		t.Errorf("Admin with no ceiling: %q %q", text, href)
	}
	r.countryCeiling, r.countryCeilingID = ptr(30), "cc"
	if text, href := countryCeiling(summary{maySetCountry: true}, r); text != "30" || href != "/training-ceilings/country/cc/edit" {
		t.Errorf("Admin with a ceiling: %q %q", text, href)
	}
	if text, href := countryCeiling(summary{}, r); text != "30" || href != "" {
		t.Errorf("the Country Director reads it: %q %q", text, href)
	}
	// A reader of the country with no figure opens the ceiling from the cell.
	s := summary{fy: "2027", maySetCountry: true, countryLinks: true}
	if got := rowCells(s, row{trainingID: "t1"})[2]; got.GetText() != "0 / Set" ||
		got.GetHref() != "/training-ceilings/country/set?training=t1&fy=2027" {
		t.Errorf("no school yet: %q %q", got.GetText(), got.GetHref())
	}
}

func TestAProjectTrainingIsReadFromItsProject(t *testing.T) {
	s := summary{fy: "2027", countryLinks: true}
	r := row{project: true, name: "EdTech Foundations (EdTech)", mode: "Online", trainingID: "t9", projectID: "p1", planned: 12,
		cells: []cell{{staffID: "s1", schools: 3, limit: ptr(5)}, {staffID: "s2"}, {staffID: "s3", limit: ptr(2)}}}
	equal(t, texts(rowCells(s, r)), []string{
		"EdTech Foundations (EdTech)||", "Online||",
		"12|/projects/monitoring?project=p1|", "—||", "—||", "—||",
		"3 / 5|/projects/monitoring?project=p1|warning", "0||", "0 / 2|/projects/monitoring?project=p1|warning",
	})
	if got := catalogueMode("cluster_training"); got != "Group Training" {
		t.Errorf("catalogueMode(cluster_training) = %q", got)
	}
	if got := catalogueMode("unknown_method"); got != "unknown_method" {
		t.Errorf("an unknown method reads as stored, got %q", got)
	}
}

func TestTheCardCountsItsFlagsAndSaysWhenItIsEmpty(t *testing.T) {
	s := summary{fy: "2027", staff: []profile{{id: "s1", name: "Ann"}, {id: "pl", name: "Lead  One"}}, leadIDs: []string{"pl"},
		rows: []row{{name: "A", cells: []cell{{schools: 3, limit: ptr(2)}, {schools: 1, limit: ptr(2)}}},
			{name: "B", cells: []cell{{schools: 2, limit: ptr(2)}, {}}}}}
	if got := subtitle(s); got != "1 above · 1 below · 1 at the number set · FY 2027" {
		t.Errorf("subtitle = %q", got)
	}
	table := tableBlock(s).GetTable()
	if got := table.GetColumns()[7].GetLabel(); got != "# Schools (Lead One · PL)" {
		t.Errorf("a Lead's column = %q", got)
	}
	if table.GetFootnote() != tableFootnote || len(table.GetRows()) != 2 {
		t.Error("a table with rows carries its note")
	}
	if got := tableBlock(summary{fy: "2027"}).GetTable(); got.GetEmptyMessage() != nobody || got.GetSubtitle() != "FY 2027" {
		t.Errorf("no staff: %q", got.GetEmptyMessage())
	}
	if got := tableBlock(summary{fy: "2027", staff: s.staff}).GetTable(); got.GetEmptyMessage() != nothingYet || got.GetFootnote() != "" {
		t.Errorf("no training: %q", got.GetEmptyMessage())
	}
}

func TestTheFeedsQueryIsWhatThePageReads(t *testing.T) {
	long := ""
	for range rules.MaxQueryValue + 1 {
		long += "x"
	}
	got := passed(url.Values{"view": {"x", "trainings"}, "Fy": {"2026"}, "export": {"csv"}, "fy": {long}, "tab": {"summary"}})
	if got.Get("view") != "trainings" || got.Has("Fy") || got.Has("export") || got.Has("fy") || got.Get("tab") != "summary" {
		t.Errorf("passed = %v", got)
	}
}

func TestHandoversAreReadInTheRunningAndLaterYears(t *testing.T) {
	now := time.Date(2026, 11, 13, 9, 0, 0, 0, time.UTC) // FY 2027
	for fy, want := range map[string]bool{"2026": false, "2027": true, "2028": true, "abc": false} {
		if got := handoversReadIn(fy, now); got != want {
			t.Errorf("handoversReadIn(%q) = %v, want %v", fy, got, want)
		}
	}
}

func TestTeamsAreEachLeadThenTheirOfficersThenTheRest(t *testing.T) {
	officers := []profile{{id: "a"}, {id: "l2"}, {id: "b"}, {id: "c"}, {id: "l1"}}
	leadOf := map[string]string{"a": "l1", "b": "l2", "c": "l1"}
	got := teamsInOrder(officers, leadOf, []string{"l1", "l2", "gone"})
	want := []string{"l1", "a", "c", "l2", "b"}
	for i, p := range got {
		if p.id != want[i] {
			t.Fatalf("order = %v, want %v", got, want)
		}
	}
}

func TestOnlyTheTrainingsLensIsGosAndOthersPassOn(t *testing.T) {
	s := NewService(nil, time.Now)
	lead := auth.Principal{Account: auth.Account{ActiveRole: rules.ProgramLeadRole}}
	cceo := auth.Principal{Account: auth.Account{ActiveRole: rules.CCEORole}}
	for _, c := range []struct {
		who    auth.Principal
		path   string
		query  url.Values
		served bool
	}{
		{lead, "/team-planning-oversight", url.Values{"view": {"trainings"}}, false},
		{lead, Path, url.Values{}, false},
		{lead, Path, url.Values{"view": {"portfolio"}}, false},
		{cceo, Path, url.Values{"view": {"trainings"}, "followup": {"f1"}}, true},
		{cceo, Path, url.Values{"view": {"trainings"}}, true},
	} {
		_, served, err := s.Build(context.Background(), c.who, c.path, c.query)
		if served != c.served {
			t.Errorf("%s %v: served = %v, want %v", c.path, c.query, served, c.served)
		}
		if c.served && err != ErrNotAvailable {
			t.Errorf("a CCEO is refused the page, got %v", err)
		}
	}
	for role, d := range rules.Doors {
		if d.Trainings && !(role == rules.ProgramLeadRole || d.ReadsCountry) {
			t.Errorf("%s holds the lens but the summary reads no one for it", role)
		}
	}
}
