package escalations

import (
	"net/url"
	"testing"
	"time"
)

func ptr(s string) *string { return &s }

func TestTheExportedRolesAreThePagesOwn(t *testing.T) {
	for role, want := range map[string]Role{
		"CCEO":                          {Page: true, RaisesTo: "PL"},
		"ProjectCoordinator":            {Page: true, RaisesTo: "PL"},
		"Program Lead":                  {Page: true, RaisesTo: "CD", DecidesFor: "PL"},
		"CountryDirector":               {Page: true, RaisesTo: "RVP", DecidesFor: "CD", ReadsCountryBoard: true},
		"RegionalVicePresident":         {Page: true, DecidesFor: "RVP"},
		"Admin":                         {Page: true, RaisesTo: "RVP", DecidesAll: true},
		"ImpactAssessment":              {Page: true},
		"BusinessTransformationOfficer": {},
		"HumanResources":                {},
	} {
		if got := rules.Roles[role]; got != want {
			t.Errorf("%s: %+v, want %+v", role, got, want)
		}
	}
}

func TestTheHeaderSaysWhatTheReaderMayDo(t *testing.T) {
	for role, want := range map[string]string{
		"CCEO":                  "Decisions above your authority, routed to your Programme Lead",
		"Program Lead":          "Decisions your team has put in front of you, and the ones you have sent up to the Country Director",
		"RegionalVicePresident": "Decisions the Country Director has put in front of you",
		"Admin":                 "Decisions your team has put in front of you, and the ones you have sent up to the Regional Vice President",
		"ImpactAssessment":      "Decisions above your authority, routed to your None",
	} {
		if got := header(rules.Roles[role]).GetDescription(); got != want {
			t.Errorf("%s: %q, want %q", role, got, want)
		}
	}
}

func TestTheInboxIsNamedOrAddressedToTheLevelInTheCountry(t *testing.T) {
	pl := reader{id: "me", role: rules.Roles["Program Lead"], country: "Uganda"}
	rvp := reader{id: "me", role: rules.Roles["RegionalVicePresident"], country: "Uganda"}
	for _, c := range []struct {
		r    reader
		e    escalation
		want bool
	}{
		{pl, escalation{AddressedRole: "PL", AssignedTo: ptr("me"), Country: "Kenya"}, true},
		{pl, escalation{AddressedRole: "PL", AssignedTo: ptr("other")}, false},
		{pl, escalation{AddressedRole: "PL", Country: "Uganda"}, true},
		{pl, escalation{AddressedRole: "PL", Country: "Kenya"}, false},
		{reader{id: "me", role: pl.role}, escalation{AddressedRole: "PL", Country: "Kenya"}, true},
		{pl, escalation{AddressedRole: "CD", Country: "Uganda"}, false},
		{rvp, escalation{AddressedRole: "RVP", Country: "Kenya"}, true},
		{reader{id: "me", role: rules.Roles["CCEO"]}, escalation{AddressedRole: "PL"}, false},
	} {
		if got := inInbox(c.r, c.e); got != c.want {
			t.Errorf("%+v for %+v: %v, want %v", c.e, c.r, got, c.want)
		}
	}
}

func TestAStatusIsTheDecisionOrHowLongItHasWaited(t *testing.T) {
	for _, c := range []struct {
		e    escalation
		want string
	}{
		{escalation{Status: "resolved", Decision: ptr("delegated_back")}, "Delegated back to the raiser"},
		{escalation{Status: "resolved", Decision: ptr("escalated_further")}, "None"},
		{escalation{Status: "resolved"}, "None"},
		{escalation{Status: "open", Overdue: true}, "Overdue"},
		{escalation{Status: "acknowledged"}, "Acknowledged"},
		{escalation{Status: "something"}, "Open"},
	} {
		if got := status(c.e); got != c.want {
			t.Errorf("%+v: %q, want %q", c.e, got, c.want)
		}
	}
	if slaDays("urgent") != 7 || slaDays("critical") != 2 {
		t.Errorf("an unknown severity waits as a normal one does")
	}
}

func TestTheRaiseFormNamesTheSupervisorOrTheWholeLevel(t *testing.T) {
	cceo := rules.Roles["CCEO"]
	named := raiseForm(cceo, board{raiseToID: "u1", raiseToName: "Grace  A."}, url.Values{"category": {" staffing "}}).GetForm()
	if named.GetTitle() != "Escalate to Grace A., your Programme Lead" || named.GetItems()[0].GetField().GetValue() != "staffing" {
		t.Errorf("a named supervisor: %q, category %q", named.GetTitle(), named.GetItems()[0].GetField().GetValue())
	}
	nobody := raiseForm(cceo, board{}, url.Values{"category": {"bogus"}, "detail": {"  two\nlines  "}}).GetForm()
	if nobody.GetTitle() != "Escalate to the Programme Lead" || nobody.GetItems()[0].GetField().GetValue() != "funding_gap" ||
		nobody.GetItems()[3].GetField().GetValue() != "two\nlines" || nobody.GetSubmitLabel() != "Send to Programme Lead" {
		t.Errorf("no supervisor on file: %v", nobody)
	}
	if want := " No supervisor is on file for you, so this goes to every Programme Lead in your country."; len(nobody.GetText()) < len(want) ||
		nobody.GetText()[len(nobody.GetText())-len(want)+1:] != want[1:] {
		t.Errorf("the line: %q", nobody.GetText())
	}
	if rvp := raiseForm(rules.Roles["Admin"], board{}, url.Values{}).GetForm(); rvp.GetTitle() != "Escalate to the Regional Vice President" ||
		rvp.GetItems()[1].GetField().GetValue() != "normal" {
		t.Errorf("to the RVP: %v", rvp)
	}
}

func TestAnOpenedRowReadsALabelAndItsFigureAsOneLine(t *testing.T) {
	created := time.Date(2026, 11, 3, 22, 30, 0, 0, time.UTC) // the 4th in Nairobi
	due := time.Date(2026, 11, 16, 0, 0, 0, 0, time.UTC)
	e := escalation{Detail: "5", RequestedDecision: ptr("Approve"), CreatedAt: created, DueDate: &due, Status: "resolved",
		Decision: ptr("approved"), AddressedRole: "PL"}
	items := opened(e)[0].GetPanel().GetItems()
	if rows := items[0].GetRows().GetRows(); len(rows) != 1 || rows[0].GetLabel() != "What is happening" || rows[0].GetValue() != "5" {
		t.Fatalf("the detail as a figure: %v", items)
	}
	want := []string{"Asking for: Approve", "— · raised 4 Nov 2026 · needed by 16 Nov 2026", "Programme Lead decision", "Approved", "None", "decided"}
	for i, w := range want {
		if got := items[i+1].GetText(); got != w {
			t.Errorf("line %d: %q, want %q", i+1, got, w)
		}
	}
}

func TestEveryListSharesOnePageParameter(t *testing.T) {
	rows := make([]escalation, 51)
	for i := range rows {
		rows[i] = escalation{Status: "open", IsOpen: true, CanDecide: true, Severity: "high"}
	}
	p := page(rules.Roles["RegionalVicePresident"], board{rows: rows}, url.Values{pageParam: {"9"}})
	if got := len(p.GetBlocks()[1].GetTable().GetRows()); got != 1 {
		t.Errorf("the last page holds %d rows", got)
	}
	if got := p.GetBlocks()[2].GetPanel().GetItems()[0].GetText(); got != "Showing 51–51 of 51" {
		t.Errorf("the pager: %q", got)
	}
	if cells := p.GetBlocks()[1].GetTable().GetRows()[0].GetCells(); cells[0].GetText() != "HIGH" || !cells[0].GetBadge() {
		t.Errorf("the severity pill: %v", cells[0])
	}
}
