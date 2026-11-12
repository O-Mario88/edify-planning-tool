package decisionlog

import (
	"net/url"
	"testing"
	"time"
)

func TestTheExportedRolesAreThePagesOwn(t *testing.T) {
	for role, want := range map[string]struct {
		page  bool
		reach Reach
		strip bool
	}{
		"CCEO":                  {true, "own", false},
		"ProjectCoordinator":    {true, "own", false},
		"CountryDirector":       {true, reachCountry, false},
		"ImpactAssessment":      {true, reachCountry, true},
		"RegionalVicePresident": {true, reachGlobal, false},
		"Admin":                 {true, reachGlobal, false},
		"ClusterLeader":         {false, "own", false},
	} {
		got := rules.Roles[role]
		if got.Page != want.page || got.Reach != want.reach || (got.Strip != nil) != want.strip {
			t.Errorf("%s: %+v, want page %v, reach %s, strip %v", role, got, want.page, want.reach, want.strip)
		}
	}
	if rules.RowLimit != 200 || rules.PageSize != 50 || rules.DefaultDays != 30 || rules.MaxDays != 365 {
		t.Errorf("limit %d, page size %d, days %d..%d", rules.RowLimit, rules.PageSize, rules.DefaultDays, rules.MaxDays)
	}
}

func TestTheWindowIsReadAsPythonsIntAndHeldInRange(t *testing.T) {
	for text, want := range map[string]int{
		"": 30, "7": 7, " 90 ": 90, "9_0": 90, "0": 1, "-3": 1, "400": 365, "abc": 30, "4.5": 30,
		"99999999999999999999999": 365, "+12": 12, "_9": 30,
	} {
		if got := days(text); got != want {
			t.Errorf("days(%q) = %d, want %d", text, got, want)
		}
	}
}

func TestAPayloadIsReadAsPythonStrsIt(t *testing.T) {
	for raw, want := range map[string]string{
		`{"staffName": "Grace"}`:                            "Grace",
		`{"name": 5}`:                                       "5",
		`{"name": 100000000000000000000}`:                   "100000000000000000000",
		`{"name": 1.5}`:                                     "1.5",
		`{"name": 1234567.0}`:                               "1234567.0",
		`{"name": 0.0001}`:                                  "0.0001",
		`{"name": 0.00001}`:                                 "1e-05",
		`{"name": 1e16}`:                                    "1e+16",
		`{"name": 1.25e17}`:                                 "1.25e+17",
		`{"name": true}`:                                    "True",
		`{"name": ["a", "b's", "q\"t", null, false]}`:       `['a', "b's", 'q"t', None, False]`,
		`{"name": ["it's \"x\"", "back\\slash", "t\tn\n"]}`: `['it\'s "x"', 'back\\slash', 't\tn\n']`,
		`{"name": {"a": 1, "k": {"z": 2.0}}}`:               "{'a': 1, 'k': {'z': 2.0}}",
		`{"name": "", "subject": "next"}`:                   "next",
		`{"name": 0, "course": 0.0, "monthKey": "m"}`:       "m",
		`{"decision": "delegated_back"}`:                    "Delegated back",
		`{"decision": "ÉCOLE_Mixed"}`:                       "École mixed",
		`{"decision": 0}`:                                   "subject-1",
		`["not", "a", "dict"]`:                              "subject-1",
		`"text"`:                                            "subject-1",
		`{}`:                                                "subject-1",
	} {
		if got := detail(decision{Payload: raw, SubjectID: "subject-1"}); got != want {
			t.Errorf("detail(%s) = %q, want %q", raw, got, want)
		}
	}
	if got := detail(decision{}); got != "—" {
		t.Errorf("nothing at all: %q", got)
	}
}

func TestAnActionWithoutALabelIsMadeReadable(t *testing.T) {
	if got := label("plan_approve"); got != "Approved a monthly plan" {
		t.Errorf("a labelled action: %q", got)
	}
	if got := label("some_NEW_action"); got != "Some new action" {
		t.Errorf("an unlabelled action: %q", got)
	}
	if got := groupFor("unknown"); got != "Other" {
		t.Errorf("an action of no group: %q", got)
	}
}

func TestTheRowsFiltersAndTabsAreDrawnAsTheFeedReadsThem(t *testing.T) {
	at := time.Date(2026, 11, 9, 22, 11, 0, 0, time.UTC) // 01:11 on the 10th in Nairobi
	v := view{role: rules.Roles["CCEO"], days: 45, group: "Nope", query: url.Values{},
		rows: []decision{{Action: "plan_approve", ActorRole: "", Reason: "  two   spaces ", At: at, Payload: `{"name": " a  b "}`}}}
	p := page(v)
	f := p.GetBlocks()[2].GetFilters()
	if f.GetFilters()[0].GetValue() != "7" || f.GetHidden()["group"] != "Nope" {
		t.Errorf("a window not offered selects the first, the group travels hidden: %v", f)
	}
	for _, tab := range p.GetBlocks()[3].GetLinkTabs().GetTabs() {
		if tab.GetActive() {
			t.Errorf("an unknown group lights no tab, yet %v", tab)
		}
	}
	cells := p.GetBlocks()[4].GetTable().GetRows()[0].GetCells()
	if cells[0].GetText() != "10 Nov, 01:11" || cells[2].GetText() != "a b" || cells[3].GetText() != "—" || cells[4].GetText() != "two spaces" {
		t.Errorf("the row: %v", cells)
	}
	ia := page(view{role: rules.Roles["ImpactAssessment"], days: 30, query: url.Values{}})
	if ia.GetBlocks()[1].GetLinkTabs() == nil || ia.GetBlocks()[5].GetPanel().GetItems()[0].GetText() != "No decisions recorded in this period" {
		t.Errorf("Impact Assessment's page: %v", ia.GetBlocks())
	}
}

func TestOnlyTheFirstFiftyAreShownAndThePagerFollows(t *testing.T) {
	rows := make([]decision, 120)
	for i := range rows {
		rows[i] = decision{Action: "plan_approve", At: time.Unix(int64(1_800_000_000-i*60), 0)}
	}
	p := page(view{role: rules.Roles["Admin"], days: 30, query: url.Values{pageParam: {"3"}}, rows: rows})
	if got := len(p.GetBlocks()[4].GetTable().GetRows()); got != 20 {
		t.Errorf("the third page holds %d rows, want 20", got)
	}
	if got := p.GetBlocks()[5].GetPanel().GetItems()[0].GetText(); got != "Showing 101–120 of 120" {
		t.Errorf("the pager says %q", got)
	}
}
