package costsettings

import (
	"net/url"
	"reflect"
	"testing"
)

func strp(s string) *string { return &s }

func TestTheCardAnswersARenamedKeyAndKeepsOnlyCanonicalAndLinkedRates(t *testing.T) {
	card := priceCard([]rate{
		{key: "primary_lunch_per_day", label: "Old lunch", unitCost: 9},
		{key: "primary_transport_per_day", label: "Transport", unitCost: 10},
		{key: "activity:x:snacks", label: "Snacks", unitCost: 3, itemID: strp("item1")},
	})
	if card.rates["lunch_per_day"] != 9 || card.rates["primary_transport_per_day"] != 10 || card.rates["activity:x:snacks"] != 3 {
		t.Fatalf("rates %v", card.rates)
	}
	if _, kept := card.rates["primary_lunch_per_day"]; kept {
		t.Fatal("the renamed key itself is priced")
	}
	keys := []string{}
	for _, r := range card.order {
		keys = append(keys, r.key)
	}
	// The renamed row answers last, after the rows read in the card's order.
	if want := []string{"primary_transport_per_day", "activity:x:snacks", "primary_lunch_per_day"}; !reflect.DeepEqual(keys, want) {
		t.Fatalf("order %v, want %v", keys, want)
	}
}

func TestCoverageListsALinkedCostAndHandsOnAnUnknownProfile(t *testing.T) {
	card := pricedCard{
		rates: map[string]int64{"primary_transport_per_day": 1, "lunch_per_day": 1, "activity:x:snacks": 5},
		order: []rate{{key: "activity:x:snacks", label: "Snacks", itemID: strp("item1")}},
	}
	rows, ok := coverageOf([]item{{
		id: "item1", name: "Visit", workflowKind: "school_visit", profile: "STAFF_SCHOOL_VISIT",
		activityType: "school_visit", delivery: "school_visit", hasPrimary: true,
	}}, card)
	if !ok || len(rows) != 1 {
		t.Fatalf("ok %v rows %v", ok, rows)
	}
	got := rows[0]
	if got.profile != "Staff School Visit" || got.intervention != "None" || !got.ready {
		t.Fatalf("row %+v", got)
	}
	if want := []string{"Transport Primary District", "Lunch", "Snacks"}; !reflect.DeepEqual(got.components, want) {
		t.Fatalf("components %v, want %v", got.components, want)
	}
	unready, _ := coverageOf([]item{{id: "i2", workflowKind: "school_visit", profile: "ONETEST"}}, pricedCard{rates: map[string]int64{"lunch_per_day": 1}})
	if unready[0].ready || unready[0].intervention != "Administrative / inherited" {
		t.Fatalf("an activity missing its transport: %+v", unready[0])
	}
	v := view{coverage: unready, card: catalogue{kind: "operational", fy: "2027", version: 1}, rates: []rate{{key: "lunch_per_day", label: "Lunch"}}, fy: "2027"}
	blocks, _ := v.blocks()
	last := blocks[len(blocks)-1].GetTable().GetRows()[0].GetCells()
	if last[5].GetText() != "Needs rate setup" {
		t.Fatalf("status %q", last[5].GetText())
	}
	if _, ok := coverageOf([]item{{id: "i", profile: "NO_SUCH_PROFILE"}}, card); ok {
		t.Fatal("an unknown profile was costed")
	}
}

func TestThePagerReadsAsTheFeedReadsIt(t *testing.T) {
	v := view{query: url.Values{"fy": {"2026"}, ratesPageParam: {"2"}}}
	items := v.pager(ratesPageParam, 2, 2, 56, 6).GetPanel().GetItems()
	if len(items) != 3 || items[0].GetText() != "Showing 51–56 of 56" || items[2].GetText() != "2" {
		t.Fatalf("items %v", items)
	}
	links := items[1].GetLinks().GetLinks()
	if len(links) != 2 || links[0].GetText() != "Prev" || links[0].GetCaption() != "‹" ||
		links[0].GetHref() != "?fy=2026&cost_items_page=1" || links[1].GetText() != "1" {
		t.Fatalf("links %v", links)
	}
	first := v.pager(ratesPageParam, 1, 2, 56, 50).GetPanel().GetItems()
	if len(first) != 3 || first[1].GetText() != "1" || len(first[2].GetLinks().GetLinks()) != 2 {
		t.Fatalf("page one %v", first)
	}
}

func TestTheTextHelpersAreTheTemplatesFilters(t *testing.T) {
	n := int64(1234567)
	if currency(&n) != "1,234,567" || currency(nil) != "0" {
		t.Fatal("currency")
	}
	if pyTitle("tot training") != "Tot Training" || pyTitle("submitted") != "Submitted" || pyTitle("a1b") != "A1B" {
		t.Fatalf("title %q %q", pyTitle("tot training"), pyTitle("a1b"))
	}
}

func TestEveryDoorIsOpenedOnlyByTheRolesThatMayOpenIt(t *testing.T) {
	if !mayOpen("CountryDirector", SettingsPath) || mayOpen("CountryDirector", IntelligencePath) {
		t.Fatal("the Country Director's doors")
	}
	if mayOpen("CCEO", SettingsPath) || mayOpen("CCEO", IntelligencePath) {
		t.Fatal("a CCEO opens a cost door")
	}
	if !rules.Roles["CountryDirector"].Manage || rules.Roles["Admin"].Manage {
		t.Fatal("who manages the rates")
	}
}
