package myplan

import (
	"testing"
	"time"
)

func TestDetailTitleIsTheTypeTitled(t *testing.T) {
	cases := map[string]string{
		"school_visit":                "School Visit",
		"school_visit_ssa_collection": "School Visit Ssa Collection",
		"donor_visit":                 "Donor Visit",
		"":                            "",
	}
	for kind, want := range cases {
		if got := detailTitle(kind); got != want {
			t.Errorf("detailTitle(%q) = %q, want %q", kind, got, want)
		}
	}
}

func TestPlannedDateIsDjangosDefaultFormat(t *testing.T) {
	april := time.Date(2026, 4, 3, 0, 0, 0, 0, time.UTC)
	nov := time.Date(2026, 11, 17, 0, 0, 0, 0, time.UTC)
	if got := plannedWords(&april); got != "April 3, 2026" {
		t.Errorf("april = %q", got)
	}
	if got := plannedWords(&nov); got != "Nov. 17, 2026" {
		t.Errorf("nov = %q", got)
	}
	if got := plannedWords(nil); got != "Unscheduled" {
		t.Errorf("none = %q", got)
	}
}

func TestJoinedIsTheBreakdownsList(t *testing.T) {
	if got := andJoined([]string{"transport"}); got != "transport" {
		t.Errorf("one = %q", got)
	}
	if got := andJoined([]string{"transport", "lunch"}); got != "transport and lunch" {
		t.Errorf("two = %q", got)
	}
	if got := andJoined([]string{"transport", "lunch", "dinner"}); got != "transport, lunch and dinner" {
		t.Errorf("three = %q", got)
	}
}

func TestBasisWordsReproduceTheAmount(t *testing.T) {
	if got := dayBasis(50000, 1, "per day"); got != "1 × UGX 50,000 per day" {
		t.Errorf("alone = %q", got)
	}
	if got := dayBasis(50000, 3, "per day"); got != "UGX 50,000 per day ÷ 3 activities" {
		t.Errorf("shared = %q", got)
	}
	if got := dayBasis(50000, 3, ""); got != "UGX 50,000 ÷ 3 activities" {
		t.Errorf("shared, no unit = %q", got)
	}
	if got := quantityBasis(1200, 500, "per page"); got != "1,200 × UGX 500 per page" {
		t.Errorf("quantity = %q", got)
	}
	if got := quantityBasis(2, 7000, ""); got != "2 × UGX 7,000" {
		t.Errorf("no unit = %q", got)
	}
}

func TestDayRateFindsTheFullRateBehindAShare(t *testing.T) {
	five := int64(50000)
	if got := dayRate(16667, 3, nil, []*int64{nil, &five}); got == nil || *got != 50000 {
		t.Errorf("shared = %v", got)
	}
	idx := int64(2)
	if got := dayRate(16667, 3, &idx, []*int64{&five}); got != nil {
		t.Errorf("the third share is 16,666, not 16,667: %v", *got)
	}
	if got := dayRate(1, 3, nil, []*int64{&five}); got != nil {
		t.Errorf("no rate gives 1: %v", *got)
	}
}

func TestFinanceStatusFollowsTheLineLifecycle(t *testing.T) {
	cases := []struct {
		name string
		in   lineMoney
		want string
	}{
		{"advance accounted with NetSuite", lineMoney{advance: "accounted", netsuite: "NS-1"}, "Cleared"},
		{"advance accounted without NetSuite", lineMoney{advance: "accounted"}, "NetSuite ID Required"},
		{"disbursed, verified", lineMoney{advance: "disbursed", status: "ia_verified"}, "Accountability Pending"},
		{"weekly pending", lineMoney{weekly: "pending_responsible_confirmation"}, "Included in Weekly Request"},
		{"weekly to the PL", lineMoney{weekly: "submitted_to_pl"}, "Submitted for Approval"},
		{"cancelled work", lineMoney{status: "cancelled", scheduled: true}, "Not Funded: Cancelled"},
		{"unscheduled", lineMoney{status: "planned"}, "Not Funded: Not Scheduled"},
		{"vendor transport", lineMoney{status: "planned", scheduled: true, vendorTransport: true}, "Transport Company: Awaiting Payment"},
		{"vendor transport paid", lineMoney{status: "planned", scheduled: true, vendorTransport: true, transportPaid: true}, "Paid to Transport Company"},
		{"hotel", lineMoney{status: "planned", scheduled: true, lineType: "accommodation", vendorPaid: true}, "Hotel Booked by Finance"},
		{"cost missing", lineMoney{status: "planned", scheduled: true, costMissing: true, amount: 5}, "Not Requested: Cost Setup Required"},
		{"no amount", lineMoney{status: "planned", scheduled: true}, "No Cost: Rate Not Set"},
		{"completed", lineMoney{status: "completed", scheduled: true, amount: 5}, "Evidence Submitted"},
		{"verified", lineMoney{status: "ia_verified", scheduled: true, amount: 5}, "IA Verified"},
		{"draft", lineMoney{status: "scheduled", scheduled: true, amount: 5}, "Draft Costed"},
	}
	for _, c := range cases {
		got, ok := financeStatus(c.in)
		if !ok || got != c.want {
			t.Errorf("%s: got %q (%v), want %q", c.name, got, ok, c.want)
		}
	}
	partner := []struct {
		in   lineMoney
		want string
	}{
		{lineMoney{status: "scheduled", scheduled: true, partner: true}, "Partner Invoice: Not Yet Paid"},
		{lineMoney{status: "scheduled", scheduled: true, partner: true, partnerAdvance: true}, "Partner Invoice: 50% Paid"},
		{lineMoney{status: "scheduled", scheduled: true, partner: true, partnerAdvance: true, partnerCleared: true}, "Paid on Partner Invoice"},
	}
	for _, c := range partner {
		if got, ok := financeStatus(c.in); !ok || got != c.want {
			t.Errorf("partner: got %q, want %q", got, c.want)
		}
	}
}

func TestDaySentenceSaysWhoSharesTheDay(t *testing.T) {
	day := time.Date(2026, 11, 2, 0, 0, 0, 0, time.UTC)
	alone := daySentence("Jane Doe", day, 1, []string{"transport", "lunch"})
	if alone != "This is the only activity Jane Doe has on Monday 2 November 2026, so it carries the day's transport and lunch in full. Another activity planned on the same day would share them." {
		t.Errorf("alone = %q", alone)
	}
	shared := daySentence("", day, 2, []string{"transport"})
	if shared != "The responsible officer has 2 activities on Monday 2 November 2026, so the day's transport is paid once and divided equally between them." {
		t.Errorf("shared = %q", shared)
	}
}

func TestFootnoteIsTheFirstNoteUnderTheTable(t *testing.T) {
	b := budgetBreakdown{source: "Rates from the X, version 1.", workedOut: "9 Nov 2026"}
	if got := b.footnote(); got != "Rates from the X, version 1. Worked out on 9 Nov 2026." {
		t.Errorf("source only = %q", got)
	}
	b.notes = []string{"This visit carries the in-school training done during it; the training itself is kept at UGX 0."}
	if got := b.footnote(); got != b.notes[0] {
		t.Errorf("a note first = %q", got)
	}
	b.missingNote = "Cost setup required: Lunch is not set, so this total is incomplete."
	if got := b.footnote(); got != b.missingNote {
		t.Errorf("missing first = %q", got)
	}
}

func TestCaptionIsTheDrawersFirstParagraph(t *testing.T) {
	plain := &detailActivity{}
	if got := caption(plain); got != "No purpose description text entered." {
		t.Errorf("plain = %q", got)
	}
	verdict := &detailActivity{ssaAlignment: "ssa_collection", verdictReason: "Collects the SSA.", purpose: "Visit"}
	if got := caption(verdict); got != "Collects the SSA." {
		t.Errorf("verdict = %q", got)
	}
	deviated := &detailActivity{ssaAlignment: "deviated", deviationReason: "Head teacher asked."}
	if got := caption(deviated); got != "Planner's reason: Head teacher asked." {
		t.Errorf("deviated = %q", got)
	}
}

func TestTrainingFactNamesTheCourseAndDelivery(t *testing.T) {
	named := &detailActivity{kind: "in_school_training", schoolID: "s", courseID: "c", courseName: "Biblical Integration"}
	if got := named.trainingFact(); got != "Biblical Integration (In-School Training)" {
		t.Errorf("named = %q", got)
	}
	unnamed := &detailActivity{kind: "cluster_training", clusterID: "c"}
	if got := unnamed.trainingFact(); got != "No training named yet (Group Training)" {
		t.Errorf("unnamed = %q", got)
	}
	meeting := &detailActivity{kind: "cluster_meeting", clusterID: "c"}
	if got := meeting.trainingFact(); got != "" {
		t.Errorf("a meeting that is not a training = %q", got)
	}
}

func TestDetailStatusReadsTodayInKampala(t *testing.T) {
	// 22:30 UTC on 24 November is already 25 November in Kampala.
	now := time.Date(2026, 11, 24, 22, 30, 0, 0, time.UTC)
	planned := time.Date(2026, 11, 25, 0, 0, 0, 0, time.UTC)
	a := &detailActivity{status: "scheduled", planned: &planned}
	if got := detailStatus(a, now); got != "Due Today" {
		t.Errorf("status = %q, want Due Today", got)
	}
}

func TestARowPricedWithoutAnAmountIsZero(t *testing.T) {
	members := []costLine{{id: "l1", key: "lunch_per_day", label: "Lunch", amount: 0, quantity: 1, unit: 0}}
	priced := map[string]any{"key": "lunch_per_day"}
	row, _, _, err := budgetRowOf("lunch_per_day", members, priced, map[rateKey]rateSetting{}, "", nil, map[string]string{"l1": "Draft Costed"})
	if err != nil {
		t.Fatalf("err = %v", err)
	}
	if row.amount != 0 || row.status != "Draft Costed" {
		t.Errorf("row = %+v", row)
	}
}
