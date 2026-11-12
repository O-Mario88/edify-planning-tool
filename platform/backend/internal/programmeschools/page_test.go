package programmeschools

import (
	"net/url"
	"reflect"
	"strings"
	"testing"
	"time"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/visitgate"
)

func f(v float64) *float64 { return &v }

func TestTheExportedDoorsAreThePagesOwn(t *testing.T) {
	for role, want := range map[string]Doors{
		"CCEO":               {Page: true, Schedule: true},
		"Program Lead":       {Page: true, Schedule: true},
		"CountryDirector":    {Page: true},
		"ImpactAssessment":   {Page: true},
		"Admin":              {Page: true},
		"ProjectCoordinator": {Schedule: true},
	} {
		if got := rules.Doors[role]; got != want {
			t.Errorf("%s: %+v, want %+v", role, got, want)
		}
	}
	if rules.Doors["RegionalVicePresident"].Page {
		t.Error("the RVP is not a reader of Programme Schools")
	}
	if got := typeValues(); !reflect.DeepEqual(got, []string{"core_trained", "core_graduate", "champion"}) {
		t.Errorf("the programme types: %v", got)
	}
}

func texts(r *screensv1.PageRow) []string {
	out := []string{}
	for _, c := range r.GetCells() {
		out = append(out, c.GetText())
	}
	return out
}

func TestARowOfTheList(t *testing.T) {
	day := time.Date(2026, time.December, 7, 0, 0, 0, 0, time.UTC)
	for _, c := range []struct {
		name   string
		school school
		doors  Doors
		want   []string
		tones  [3]string // SSA, visit plan, training
		action string
	}{
		{
			name: "a planner's Core Trained school with a visit dated and a session planned",
			school: school{Code: "1054", Name: "Kasawo  Primary", TypeLabel: "Core Trained", District: "Mukono", Owner: "Paul N.",
				SSAAverage: f(6.9), SSATone: "lime", VisitsUsed: 1, VisitsAllowed: 1, VisitLabel: "Scheduled for Visit", VisitTone: "info",
				NextVisit: &day, TrainingLabel: "Training Planned", TrainingPlanned: true},
			doors: Doors{Page: true, Schedule: true},
			want:  []string{"", "Kasawo Primary 1054", "Core Trained", "Mukono", "Paul N.", "6.9/10", "1/1 entitlement used", "Scheduled for Visit 7 Dec 2026", "Training Planned", "Schedule"},
			tones: [3]string{"lime", "info", "neutral"},
		},
		{
			name: "a reader's Champion with nothing recorded",
			school: school{Code: "1599", Name: "Goma Hill", TypeLabel: "Champion", VisitsAllowed: 1,
				VisitLabel: "No Visit Planned", VisitTone: "neutral", TrainingLabel: "No Training Required"},
			doors:  Doors{Page: true},
			want:   []string{"", "Goma Hill 1599", "Champion", "—", "Unassigned", "Not assessed", "0/1 1 left", "No Visit Planned", "No Training Required", "View"},
			tones:  [3]string{"", "neutral", "danger"},
			action: "/schools/1599",
		},
		{
			name: "a whole-number average, and more visits than the year allows",
			school: school{Code: "7", Name: "Lake", TypeLabel: "Core Graduate", SSAAverage: f(7), SSATone: "lime", VisitsUsed: 2, VisitsAllowed: 1,
				VisitLabel: "Visit Completed", VisitTone: "success", TrainingLabel: "No Training Planned"},
			doors:  Doors{Page: true},
			want:   []string{"", "Lake 7", "Core Graduate", "—", "Unassigned", "7/10", "2/1 entitlement used", "Visit Completed", "No Training Planned", "View"},
			tones:  [3]string{"lime", "success", "danger"},
			action: "/schools/7",
		},
	} {
		r := row(c.school, c.doors)
		if got := texts(r); !reflect.DeepEqual(got, c.want) {
			t.Errorf("%s:\n %q\nwant\n %q", c.name, got, c.want)
		}
		cells := r.GetCells()
		if got := [3]string{cells[5].GetTone(), cells[7].GetTone(), cells[8].GetTone()}; got != c.tones {
			t.Errorf("%s: tones %v, want %v", c.name, got, c.tones)
		}
		if cells[1].GetHref() != "/schools/"+c.school.Code || cells[9].GetHref() != c.action {
			t.Errorf("%s: the name opens %q and the action %q", c.name, cells[1].GetHref(), cells[9].GetHref())
		}
	}
}

func TestTheEntitlementFollowsTheSchoolsRule(t *testing.T) {
	r := visitgate.Rules{StaffVisitCap: 1}
	r.Core.Caps.StaffVisits = 2
	for _, c := range []struct {
		gate          visitgate.Gate
		used, allowed int
	}{
		{visitgate.Gate{Rule: "client", StaffVisits: 1}, 1, 1},
		{visitgate.Gate{Rule: "core", StaffVisits: 9, Split: visitgate.CoreSplit{StaffVisits: 1}}, 1, 2},
		{visitgate.Gate{Rule: "none", StaffVisits: 3}, 0, 0},
	} {
		if used, allowed := entitlement(c.gate, r); used != c.used || allowed != c.allowed {
			t.Errorf("%s: %d/%d, want %d/%d", c.gate.Rule, used, allowed, c.used, c.allowed)
		}
	}
}

func schoolsOf(n int) []school {
	out := []school{}
	for i := range n {
		s := school{Code: "c", Name: "School", TypeLabel: "Champion", VisitsAllowed: 1}
		if i%4 == 0 {
			day := time.Date(2026, 12, 1, 0, 0, 0, 0, time.UTC)
			s.NextVisit = &day
		}
		s.TrainingPlanned = i%10 == 0
		out = append(out, s)
	}
	return out
}

func TestThePageAndItsFigures(t *testing.T) {
	years := []string{"2025", "2026", "2027", "2028"}
	districts := []option{{"d1", "Abim"}, {"d2", "Mukono"}}
	v := view{
		doors: Doors{Page: true}, query: url.Values{"programme_page": {"3"}, "school_type": {"champion"}}, years: years, districts: districts,
		f: filterState{schoolType: "champion", fy: "2027"}, byType: map[string]int{"champion": 1620}, total: 1620, rows: schoolsOf(120),
	}
	p := page(v)
	if len(p.GetBlocks()) != 5 || p.GetWebPath() != Path || len(p.GetHeader().GetActions()) != 0 {
		t.Fatalf("the page: %d blocks", len(p.GetBlocks()))
	}
	figures := p.GetBlocks()[0].GetStrip().GetMetrics()
	// The total is the whole filtered list's; the planned counts are of the
	// rows the page holds.
	if got := []string{figures[0].GetValue(), figures[1].GetValue(), figures[2].GetValue(), figures[3].GetValue()}; !reflect.DeepEqual(got, []string{"1,620", "30", "1,590", "12"}) {
		t.Errorf("the figures: %v", got)
	}
	if figures[1].GetNote() != "FY2027, from the Activity ledger" || figures[1].GetHelper() != "" {
		t.Errorf("the year's helper: %v", figures[1])
	}
	list := p.GetBlocks()[1].GetFilters().GetFilters()
	if list[0].GetValue() != "champion" || list[0].GetOptions()[3].GetLabel() != "Champion (1620)" || list[0].GetOptions()[1].GetLabel() != "Core Trained (0)" ||
		list[1].GetValue() != "" || len(list[1].GetOptions()) != 3 || list[2].GetValue() != "2027" || list[2].GetOptions()[0].GetLabel() != "FY2025" {
		t.Errorf("the filters: %v", list)
	}
	table := p.GetBlocks()[2].GetTable()
	if len(table.GetRows()) != 20 || table.GetColumns()[6].GetLabel() != "Visits FY2027" || !table.GetColumns()[9].GetNumeric() || table.GetColumns()[8].GetNumeric() {
		t.Errorf("the table: %d rows, %v", len(table.GetRows()), table.GetColumns())
	}
	pager := p.GetBlocks()[3].GetPanel().GetItems()
	if pager[0].GetText() != "Showing 101–120 of 120" || pager[1].GetLinks().GetLinks()[0].GetHref() != "?school_type=champion&programme_page=2" {
		t.Errorf("the pager: %v", pager)
	}
	if note := p.GetBlocks()[4].GetPanel().GetItems()[0].GetText(); !strings.HasPrefix(note, "Partner delivery is closed") {
		t.Errorf("the note: %q", note)
	}

	// A type that is not one of the three selects nothing in the filter, yet
	// the page still says its filters matched nothing.
	for _, c := range []struct {
		f    filterState
		want string
	}{
		{filterState{fy: "2027"}, "A school arrives here"},
		{filterState{fy: "2027", q: "zzz"}, "Clear the filters"},
		{filterState{fy: "2027", schoolType: "nonsense"}, "Clear the filters"},
		{filterState{fy: "2027", district: "d9"}, "Clear the filters"},
	} {
		p := page(view{doors: Doors{Page: true}, query: url.Values{}, years: years, districts: districts, f: c.f, byType: map[string]int{}})
		if len(p.GetBlocks()) != 3 || !strings.HasPrefix(p.GetBlocks()[2].GetEmpty(), c.want) {
			t.Errorf("%+v: %v", c.f, p.GetBlocks()[2])
		}
		if got := p.GetBlocks()[1].GetFilters().GetFilters()[0].GetValue(); got != "" {
			t.Errorf("%+v: the type filter shows %q", c.f, got)
		}
		if (len(p.GetHeader().GetActions()) == 1) != (c.f.q != "") {
			t.Errorf("%+v: Clear search: %v", c.f, p.GetHeader().GetActions())
		}
	}
}

func TestTheListsWhere(t *testing.T) {
	args := []any{}
	where := listed(schooldirectory.Scope{CountryScope: true}, filterState{schoolType: "client", fy: "2027"}, &args)
	if strings.Contains(where, "s.school_type = $") || len(args) != 2 {
		t.Errorf("a type outside the three filters nothing: %s (%d arguments)", where, len(args))
	}
	args = []any{}
	where = listed(schooldirectory.Scope{SchoolIDs: []string{"a"}}, filterState{schoolType: "champion", district: "d1", q: "50%"}, &args)
	for _, part := range []string{"s.school_type = ANY($1)", "s.operational_status = ANY($2)", "s.id = ANY($3)", "s.school_type = $4", "s.district_id = $5",
		"UPPER(s.name::text) LIKE UPPER($6) OR UPPER(s.school_id::text) LIKE UPPER($6)"} {
		if !strings.Contains(where, part) {
			t.Errorf("the list's WHERE lacks %q: %s", part, where)
		}
	}
	if len(args) != 6 || args[5] != `%50\%%` {
		t.Errorf("the arguments: %v", args)
	}
}
