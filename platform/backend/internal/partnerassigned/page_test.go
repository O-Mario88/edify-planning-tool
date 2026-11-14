package partnerassigned

import (
	"testing"
	"time"
)

func str(s string) *string { return &s }

func TestClusterOrGroupWorkIsAnActivityAndOneSchoolIsAVisit(t *testing.T) {
	if !isSchoolScoped(assignment{SchoolID: "s"}) || isSchoolScoped(assignment{SchoolID: "s", ClusterID: "c"}) ||
		isSchoolScoped(assignment{SchoolID: "s", Expected: "cluster_meeting"}) || isSchoolScoped(assignment{}) {
		t.Fatal("scope")
	}
}

func TestTheSubtypeAndPurposeFallBackAsThePageDoes(t *testing.T) {
	if got := subtype(assignment{Item: str("School Visit")}); got != "School Visit" {
		t.Errorf("item %q", got)
	}
	if got := subtype(assignment{Expected: "in_school_training"}); got != "In School Training" {
		t.Errorf("type %q", got)
	}
	if got := purpose(assignment{PurposeCode: "nothing", Purpose: "Free text"}); got != "Free text" {
		t.Errorf("free text %q", got)
	}
	if got := purpose(assignment{}); got != "—" {
		t.Errorf("none %q", got)
	}
}

func TestATeamMemberIsOfferedScheduleAlone(t *testing.T) {
	rows := []assignment{{ID: "a", SchoolID: "s", Item: str("X"), HasItem: true}}
	cells := page(SchoolsPath, true, false, rows, nil).GetBlocks()[0].GetTable().GetRows()[0].GetCells()
	if cells[len(cells)-1].GetText() != "Schedule" {
		t.Fatalf("team member decision %q", cells[len(cells)-1].GetText())
	}
}

func TestEvidenceReadsTheMissingWorkAndRecentUploads(t *testing.T) {
	at := time.Date(2026, 11, 14, 6, 41, 0, 0, time.UTC)
	r := evidencePage([]upload{{School: str("Kasawo  Primary"), At: at, Quarantined: true}, {At: at}},
		[]missing{{ID: "a1", Type: "school_visit", School: str("Katosi Primary")}, {ID: "a2", Type: "made_up"}})
	if got := r.Blocks[0].GetPanel().Items[0].GetText(); got != "2 completed activities missing evidence" {
		t.Errorf("count: %q", got)
	}
	items := r.Blocks[1].GetPanel().Items
	if len(items) != 4 || items[0].GetText() != "Katosi Primary · "+rules.ActivityTypes["school_visit"] || items[2].GetText() != "Activity · made_up" {
		t.Errorf("missing: %v", items)
	}
	if l := items[1].GetLinks().Links[0]; l.Text != "Upload Evidence" || l.Href != "/activities/a1/evidence" || !l.Drawer {
		t.Errorf("upload link: %v", l)
	}
	recent := r.Blocks[2].GetPanel()
	if recent.Title != "Recent Uploads" || len(recent.Items) != 6 || recent.Items[0].GetText() != "Kasawo Primary" ||
		recent.Items[1].GetText() != "14 Nov 2026 09:41" || recent.Items[2].GetText() != "Quarantined" || recent.Items[3].GetText() != "Activity" || recent.Items[5].GetText() != "Received" {
		t.Errorf("recent: %v", recent.Items)
	}
	one := evidencePage(nil, []missing{{ID: "a1", Type: "ssa"}})
	if got := one.Blocks[0].GetPanel().Items[0].GetText(); got != "1 completed activity missing evidence" {
		t.Errorf("one: %q", got)
	}
	if got := one.Blocks[2].GetPanel().Items[0].GetText(); got != "Evidence you upload for completed activities will appear here." {
		t.Errorf("no uploads: %q", got)
	}
}

func TestCompletedWorkWordsItsReviewAndPaymentForThePartner(t *testing.T) {
	cases := []struct {
		d     done
		paid  []payment
		stage string
		ia    string
		pay   string
	}{
		{done{status: "ia_verified"}, []payment{{kind: "advance"}, {kind: "clearance"}}, "", "Verified", "Paid"},
		{done{status: "ia_verified"}, nil, "awaiting_accountant", "Verified", "Awaiting Accountant"},
		{done{status: "closed"}, nil, "processing", "Verified", "Payment Processing"},
		{done{status: "ia_verified"}, []payment{{kind: "advance"}}, "", "Verified", "Advance Paid — Balance Pending"},
		{done{status: "accountant_confirmed"}, nil, "", "Verified", "Awaiting Payment"},
		{done{status: "returned_by_ia"}, nil, "", "Returned for Correction", "Not Yet Eligible"},
		{done{status: "completed"}, nil, "", "Under IA Review", "Not Yet Eligible"},
	}
	for _, c := range cases {
		if ia, _, pay, _ := paymentState(c.d, c.paid, c.stage); ia != c.ia || pay != c.pay {
			t.Errorf("%+v: %q %q", c, ia, pay)
		}
	}
	if ugx(1250000) != "1,250,000" || ugx(999) != "999" || ugx(-1000) != "-1,000" {
		t.Error("ugx")
	}
}
