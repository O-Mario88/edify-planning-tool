package planningpage

import (
	"net/url"
	"slices"
	"strings"
	"testing"
	"time"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schoolplanning"
)

func TestThePagerWindowIsTheExistingOne(t *testing.T) {
	cases := []struct {
		page, total int
		want        []int
	}{
		{1, 0, []int{}},
		{1, 5, []int{1, 2, 3, 4, 5}},
		{1, 7, []int{1, 2, 3, 4, 5, 6, 7}},
		{1, 10, []int{1, 2, 0, 10}},
		{5, 10, []int{1, 0, 4, 5, 6, 0, 10}},
		{9, 10, []int{1, 0, 8, 9, 10}},
		{10, 10, []int{1, 0, 9, 10}},
		{3, 10, []int{1, 2, 3, 4, 0, 10}},
	}
	for _, c := range cases {
		if got := window(c.page, c.total); !slices.Equal(got, c.want) {
			t.Errorf("page %d of %d: %v, want %v", c.page, c.total, got, c.want)
		}
	}
}

func TestTheQuarterTurnsWithTheFiscalYear(t *testing.T) {
	for month, want := range map[time.Month]string{time.October: "Q1", time.December: "Q1", time.January: "Q2",
		time.March: "Q2", time.April: "Q3", time.June: "Q3", time.July: "Q4", time.September: "Q4"} {
		if got := quarterOf(time.Date(2026, month, 15, 0, 0, 0, 0, time.UTC)); got != want {
			t.Errorf("%s: %s, want %s", month, got, want)
		}
	}
}

func TestFiltersAreReadAsTheViewReadsThem(t *testing.T) {
	now := time.Date(2026, 11, 12, 9, 0, 0, 0, time.UTC)
	f, ok := readFilters(url.Values{}, "2027", true, now)
	if !ok || f.fy != "2027" || f.quarter != "Q1" || f.district != "All" || f.tab != "client" ||
		f.group != "owner" || f.support != "all" || f.page != 1 || f.perPage != 15 {
		t.Errorf("defaults for a country reader: %+v", f)
	}
	if f, _ := readFilters(url.Values{}, "2027", false, now); f.group != "name" {
		t.Errorf("an officer's default grouping: %s", f.group)
	}
	if f, _ := readFilters(url.Values{"group": {"anything"}, "support": {"bogus"}}, "2027", true, now); f.group != "name" || f.support != "all" {
		t.Errorf("an unknown grouping or support filter: %+v", f)
	}
	if _, ok := readFilters(url.Values{"page": {"two"}}, "2027", false, now); ok {
		t.Error("a page that is not a number is the existing view's failure, not an answer")
	}
	if f, _ := readFilters(url.Values{"fy": {""}}, "2027", false, now); f.fy != "" || f.dataFY != "2027" {
		t.Errorf("an empty year is shown as given and read as the operational one: %+v", f)
	}
}

func TestAGroupHeadingCountsItsSchools(t *testing.T) {
	if got := groupRow("Program Lead 1 · Paul N.", 1).GetCells()[0].GetText(); got != "Program Lead 1 · Paul N. 1 school" {
		t.Error(got)
	}
	if got := groupRow(groupLabel(nil), 75).GetCells()[0].GetText(); got != "Unassigned 75 schools" {
		t.Error(got)
	}
	if got := groupLabel(&owner{name: "Paul N."}); got != "No Program Lead · Paul N." {
		t.Error(got)
	}
}

func TestTabsLinkToTheFormAsItStands(t *testing.T) {
	f := filterState{tab: "client"}
	filters := []*screensv1.PageFilter{{Name: "fy", Value: "2027"}, {Name: "quarter", Value: "Q1"}, {Name: "district", Value: "All"},
		{Name: "staff", Value: "a b&c"}, {Name: "empty", Value: ""}}
	got := tabs(f, filters).GetLinkTabs().GetTabs()
	if got[1].GetHref() != "?tab=core&fy=2027&quarter=Q1&district=All&staff=a+b%26c" || !got[0].GetActive() || got[1].GetActive() {
		t.Errorf("tabs %v", got)
	}
}

func TestFactsTakeTheirHoldersColour(t *testing.T) {
	for classes, want := range map[string]string{"school-record-row__ssa is-danger": "alert", "is-warning": "caution",
		"is-success": "good", "is-lime": "", "is-positive": "good", "is-attention": "caution", "": ""} {
		if got := factTone(classes); got != want {
			t.Errorf("%q: %q, want %q", classes, got, want)
		}
	}
}

func TestARowNamesWhatTheSchoolLacks(t *testing.T) {
	s := school{ID: "s1", Code: "1650", Name: "Central  Primary", Type: "client", ClusterID: "c1", ClusterName: "Cluster missing",
		ownerName: "Unassigned", badges: &schoolplanning.Badges{}}
	r := row(s, Doors{Schedule: true}, true, "2027")
	cells := r.GetCells()
	if cells[1].GetText() != "Central Primary" || cells[1].GetHref() != "" || cells[2].GetText() != "Cluster missing" || cells[2].GetHref() != "" {
		t.Errorf("name and cluster: %v %v", cells[1], cells[2])
	}
	if cells[3].GetText() != "Not Planned" || cells[6].GetText() != "Staff" {
		t.Errorf("badges and responsible: %v", cells)
	}
	if actions := cells[7].GetActions(); len(actions) != 1 || actions[0].GetLabel() != "Schedule" {
		t.Errorf("a school the visit rule keeps from partners offers Schedule alone: %v", actions)
	}
	facts := map[string][3]string{}
	for _, f := range r.GetDetails() {
		facts[f.GetLabel()] = [3]string{f.GetValue(), f.GetHref(), f.GetTone()}
	}
	for label, want := range map[string][3]string{
		"District": {"—", "", ""}, "Enrollment": {"—", "", ""}, "Phone": {"No phone", "", ""}, "Staff Name": {"Unassigned", "", ""},
		"SSA": {"Not assessed", "", ""}, "Visit": {"0", "", "caution"}, "Next Activity": {"—", "", ""},
	} {
		if facts[label] != want {
			t.Errorf("%s: %v, want %v", label, facts[label], want)
		}
	}
	if r.GetDetailsHref() != "" {
		t.Errorf("no profile, district or owner to open: %q", r.GetDetailsHref())
	}
	s.DistrictID, s.OwnerID = "d1", "o1"
	if got := row(s, Doors{}, false, "2027").GetDetailsHref(); got != "/districts/d1" {
		t.Errorf("a reader who may not open profiles opens the district: %q", got)
	}
}

func TestAnEmptyListSaysWhyWholeAndKeepsItsPager(t *testing.T) {
	f := filterState{page: 1, perPage: 20}
	blocks := emptyBlocks(f, false, "Showing 0–0 of 0 schools", nil)
	items := blocks[0].GetPanel().GetItems()
	if len(items) != 2 || items[0].GetText() != "No schools have been clustered yet." ||
		items[1].GetText() != "Planning works on clustered schools. Every school is still in the School Directory — add them to a cluster and they appear here." ||
		items[1].GetTextLinks()[0].GetHref() != "/schools" {
		t.Errorf("nothing clustered: %v", items)
	}
	pager := blocks[1].GetPager()
	if pager.GetSummary() != "Showing 0–0 of 0 schools" || pager.GetSize().GetValue() != "20" || len(pager.GetSize().GetOptions()) != 3 {
		t.Errorf("pager: %v", pager)
	}
	blocks = emptyBlocks(filterState{page: 2, perPage: 30}, true, "Showing 0–0 of 0 schools", []*screensv1.PagePagerPage{{Label: "Prev", Href: "/planning?page=1"}})
	if blocks[0].GetPanel().GetItems()[0].GetText() != "No planning records match your filters." || blocks[1].GetPager().GetPages()[0].GetLabel() != "Prev" {
		t.Errorf("filters matched nothing on page 2: %v", blocks)
	}
	if got := blocks[1].GetPager().GetSize().GetValue(); got != "15" {
		t.Errorf("a size the chooser lacks selects its first: %q", got)
	}
}

func TestTheWorkloadLineSharesTheYearOut(t *testing.T) {
	base := ownWorkload{fy: "2027", ceiling: 560, coreStaffVisits: 2, corePartnerVisits: 2}
	for _, c := range []struct {
		name       string
		w          ownWorkload
		text, tone string
	}{
		{"nothing held", base, "Your FY2027 visits: 0 of 560 planned. Core 0 of 0 · Client 0 of 0.", "info"},
		{"one beyond", func() ownWorkload {
			w := base
			w.coreSchools, w.clientSchools, w.corePlanned, w.clientPlanned = 100, 361, 2, 5
			return w
		}(),
			"Your FY2027 visits: 7 of 560 planned. Core 2 of 200 · Client 5 of 360. 1 of your Client schools is beyond your 560 and is the Partner's to visit: assign it to a Partner. The Partner also takes two visits and two trainings at each of your Core schools.", "info"},
		{"core only, over", func() ownWorkload {
			w := base
			w.ceiling, w.coreSchools, w.clientSchools, w.corePlanned = 280, 150, 3, 290
			return w
		}(),
			"Your FY2027 visits: 290 of 280 planned. Core 290 of 300 · Client 0 of 0. 3 of your Client schools are beyond your 280 and are the Partner's to visit: assign them to a Partner. The Partner also takes two visits and two trainings at each of your Core schools. Your Core schools alone take your whole 280 (20 over), so every other school you hold is the Partner's. You are 10 past your 280. Nothing was refused; the visits past it are the Partner's share.", "warning"},
		{"core exactly fills it", func() ownWorkload { w := base; w.ceiling, w.coreSchools = 280, 140; return w }(),
			"Your FY2027 visits: 0 of 280 planned. Core 0 of 280 · Client 0 of 0. The Partner also takes two visits and two trainings at each of your Core schools. Your Core schools alone take your whole 280, so every other school you hold is the Partner's.", "warning"},
	} {
		if got := c.w.text(); got != c.text {
			t.Errorf("%s:\n got %q\nwant %q", c.name, got, c.text)
		}
		if got := c.w.tone(); got != c.tone {
			t.Errorf("%s: tone %q, want %q", c.name, got, c.tone)
		}
		if !strings.HasPrefix(c.w.text(), c.w.lead()) {
			t.Errorf("%s: the lead opens the line", c.name)
		}
	}
}

func TestTheBarOffersOnlyTheDrawersTheRoleMayOpen(t *testing.T) {
	if selection(Doors{}) != nil {
		t.Error("a role with neither drawer has no bar")
	}
	if got := selection(Doors{AssignPartner: true}).GetActions(); len(got) != 1 || got[0].GetLabel() != "Assign to partner" {
		t.Errorf("%v", got)
	}
}
