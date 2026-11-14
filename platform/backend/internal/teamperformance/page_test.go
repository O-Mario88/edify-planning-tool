package teamperformance

import (
	"reflect"
	"testing"
	"time"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
)

func TestFiguresAreWrittenAsThePageWritesThem(t *testing.T) {
	cases := []struct {
		name string
		got  string
		want string
	}{
		{"no figure is a dash", num(nil), "—"},
		{"a count is grouped", num(ptr(1234567)), "1,234,567"},
		{"zero is 0, never a dash", num(ptr(0)), "0"},
		{"a fraction keeps one place", num(ptr(356.44)), "356.4"},
		{"a share drops .0", pct(ptr(100)), "100%"},
		{"a share keeps its tenth", pct(ptr(99.9)), "99.9%"},
		{"a large share is grouped", pct(ptr(1234.5)), "1,234.5%"},
		{"a rise is signed", signed(ptr(700)), "+700"},
		{"a fall carries the minus sign", signed(ptr(-142)), "−142"},
		{"no change is 0", signed(ptr(0)), "0"},
		{"a rate is written as %g", fmtG(90), "90"},
		{"a fractional rate keeps its digits", fmtG(33.333333333), "33.3333"},
	}
	for _, c := range cases {
		if c.got != c.want {
			t.Errorf("%s: got %q, want %q", c.name, c.got, c.want)
		}
	}
}

func TestShareRoundsHalfToEvenOnTheBinaryValue(t *testing.T) {
	// round(100.0 * 1 / 8, 1) is 12.5; round(0.25, 1) is 0.2 in Python.
	if got := *share(ptr(1), ptr(8)); got != 12.5 {
		t.Errorf("1 of 8: %v", got)
	}
	if got := pyRound(0.25, 1); got != 0.2 {
		t.Errorf("round(0.25, 1): %v", got)
	}
	if share(ptr(3), ptr(0)) != nil || share(nil, ptr(3)) != nil {
		t.Error("no target or no figure has no share")
	}
}

func TestStatusFollowsTheWorkbooksRule(t *testing.T) {
	for _, c := range []struct {
		share   *float64
		running bool
		want    string
	}{
		{nil, true, ""},
		{ptr(100), false, "Achieved"},
		{ptr(100), true, "On Track"},
		{ptr(75), true, "Progressing"},
		{ptr(74.9), false, "Needs Attention"},
	} {
		if got := statusOf(c.share, c.running); got != c.want {
			t.Errorf("status(%v, %v) = %q, want %q", c.share, c.running, got, c.want)
		}
	}
}

func TestSpreadSharesATargetByLargestRemainder(t *testing.T) {
	weights := &counter{}
	for _, p := range []string{"Central", "Central", "Eastern", "Northern"} {
		weights.inc(p)
	}
	parts, order := spread(7, weights)
	if want := map[string]int{"Central": 3, "Eastern": 2, "Northern": 2}; !reflect.DeepEqual(parts, want) {
		t.Errorf("parts %v, want %v", parts, want)
	}
	if !reflect.DeepEqual(order, []string{"Central", "Eastern", "Northern"}) {
		t.Errorf("order %v", order)
	}
	// Equal remainders go to the place met first.
	even := &counter{}
	even.inc("Western")
	even.inc("Eastern")
	parts, _ = spread(1, even)
	if parts["Western"] != 1 || parts["Eastern"] != 0 {
		t.Errorf("a tie goes to the first place: %v", parts)
	}
	parts, order = spread(5, &counter{})
	if parts[rules.NotPlaced] != 5 || len(order) != 1 {
		t.Errorf("nothing to share by is not placed: %v", parts)
	}
}

func TestFamilyIsTheSchoolsATargetSpreadsBy(t *testing.T) {
	for key, want := range map[string]string{
		"core_recruitment":        "client",
		"ssa_core_baseline":       "client",
		"ssa_client":              "client",
		"ssa_core_followup":       "core",
		"core_visit_1":            "core",
		"client_visit_partner":    "client",
		"edtech_integration_core": "core",
		"teacher_pedagogy":        "client",
		"msc":                     "all",
		"dc_clubs":                "all",
	} {
		if got := familyOf(byKey[key]); got != want {
			t.Errorf("%s: %s, want %s", key, got, want)
		}
	}
}

func TestMeasuresMatchTheWorkTheyCount(t *testing.T) {
	yes, no := true, false
	visit := facts{kind: "visit", core: &no, partner: true}
	training := facts{kind: "training", core: &yes, topic: "CC_SEL", online: true}
	meetingAsTraining := facts{kind: "training", core: &no, meeting: "training", activityType: "cluster_meeting_ssa_review"}
	leaders := facts{kind: "meeting", meeting: "cluster_leaders"}
	district := facts{kind: "event", topic: districtMeeting}
	alumni := facts{kind: "visit", core: &no, alumni: true}
	noSchool := facts{kind: "training", topic: "CC_SEL"}
	cases := []struct {
		key  string
		f    facts
		want bool
	}{
		{"client_visit_partner", visit, true},
		{"client_visit_staff", visit, false},
		{"client_visit_total", visit, true},
		{"cc_sel_core", training, true},
		{"cc_sel_client", training, false},
		{"core_online", training, true},
		{"client_online", training, false},
		{"online_sessions", training, true},
		{"ssa_review_client", meetingAsTraining, true},
		{"cluster_meetings", meetingAsTraining, true},
		{"client_trained", meetingAsTraining, true},
		{"cluster_leaders_meetings", leaders, true},
		{"cluster_leaders_meetings", district, true},
		{"district_meetings", district, true},
		{"alumni_data", alumni, true},
		{"alumni_data", visit, false},
		// Work at no school has no family: a Core or client row never takes it.
		{"cc_sel_core", noSchool, false},
		{"course_cc_sel", noSchool, false},
		{"online_schools", noSchool, false},
	}
	for _, c := range cases {
		m := byKey[c.key]
		if m == nil {
			if c.key == "course_cc_sel" {
				continue
			}
			t.Fatalf("no measure %s", c.key)
		}
		if got := matches(m, c.f); got != c.want {
			t.Errorf("%s on %+v: %v, want %v", c.key, c.f, got, c.want)
		}
	}
}

func TestPeriodReadsTheChosenWindow(t *testing.T) {
	today := dateOf(2026, time.November, 13)
	cases := []struct {
		name                       string
		fy, month, kind, q, week   string
		label, previous, monthName string
		months                     []int
		last                       int
	}{
		{"as it opens", "", "", "", "", "", "November 2026", "last month", "November 2026", []int{2}, 2},
		{"a week", "", "", "week", "", "2026-10-14", "Week of 12 Oct 2026", "last week", "November 2026", nil, 1},
		{"an ISO week", "", "", "week", "", "2026-W44", "Week of 26 Oct 2026", "last week", "November 2026", nil, 2},
		{"a quarter", "", "", "quarter", "3", "", "Q3 FY2027 (Apr–Jun 2027)", "last quarter", "November 2026", []int{7, 8, 9}, 9},
		{"the year", "", "", "year", "", "", "FY2027 (Oct 2026–Sep 2027)", "last year", "November 2026", []int{1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12}, 12},
		{"a past year opens on its last month", "2026", "", "", "", "", "September 2026", "last month", "September 2026", []int{12}, 12},
		{"a future year opens on its first", "2028", "", "", "", "", "October 2027", "last month", "October 2027", []int{1}, 1},
		{"a year that is not one", "1999", "13", "bad", "9", "nope", "November 2026", "last month", "November 2026", []int{2}, 2},
	}
	for _, c := range cases {
		p := resolvePeriod(c.fy, c.month, c.kind, c.q, c.week, today)
		if p.label() != c.label || p.previousLabel() != c.previous || p.monthLabel() != c.monthName {
			t.Errorf("%s: %q / %q / %q", c.name, p.label(), p.previousLabel(), p.monthLabel())
		}
		if !reflect.DeepEqual(p.months(), c.months) || p.lastMonth() != c.last {
			t.Errorf("%s: months %v last %d", c.name, p.months(), p.lastMonth())
		}
	}
	p := resolvePeriod("", "", "", "", "", today)
	if w := p.toDate(); !w.start.Equal(dateOf(2026, time.October, 1)) || !w.end.Equal(dateOf(2026, time.November, 14)) {
		t.Errorf("to date: %v", w)
	}
	if weeks := p.weekOptions(); weeks[0][0] != "2026-11-09" || weeks[len(weeks)-1][0] != "2026-09-28" {
		t.Errorf("weeks: %v", weeks)
	}
}

func TestTargetsComeFromThePlanThenTheEligibleSchools(t *testing.T) {
	book := &targetBook{byCode: map[string]*milestone{}, country: map[string]countryTarget{},
		team: map[[2]string]*allocation{}, staff: map[[2]string]*allocation{}, teamsOf: map[string][]*allocation{},
		staffOf: map[string][]*allocation{}, phasing: map[string]*months{}}
	book.byCode["CLIENT_VISIT_COVERAGE"] = &milestone{code: "CLIENT_VISIT_COVERAGE", measurement: "percentage", value: ptr(90)}
	book.byCode["SEL_TRAINING"] = &milestone{code: "SEL_TRAINING", measurement: "count", value: ptr(100), core: ptr(40), client: ptr(60)}
	a := &allocation{id: "a1", kind: "employee", employee: "s1", allocated: ptr(10), core: ptr(4), client: ptr(6)}
	b := &allocation{id: "a2", kind: "employee", employee: "s2", allocated: ptr(20), core: nil, client: ptr(12)}
	book.staff[[2]string{"SEL_TRAINING", "s1"}] = a
	book.staff[[2]string{"SEL_TRAINING", "s2"}] = b
	book.staffOf["SEL_TRAINING"] = []*allocation{a, b}
	ph := &months{}
	ph.set(1, 5)
	ph.set(2, 5)
	book.phasing["a1"] = ph

	eligible := 401
	got := book.targetOf(byKey["client_visit_total"], countryScope(), &eligible)
	if got.annual == nil || *got.annual != 361 || got.source != "90% of eligible schools (country milestone)" {
		t.Errorf("rate target: %+v", got)
	}
	got = book.targetOf(byKey["cc_sel_core"], countryScope(), nil)
	if *got.annual != 40 || got.source != "Country milestone" || got.months == nil || *got.month(1) != 2 {
		t.Errorf("country Core slice: %+v %v", got, got.months)
	}
	got = book.targetOf(byKey["cc_sel_client"], regionScope("pl", map[string]bool{"s1": true, "s2": true}), nil)
	if *got.annual != 18 || got.source != "Allocation" || *got.through(2) != 6 {
		t.Errorf("officers' client slices added up: %+v", got)
	}
	got = book.targetOf(byKey["cc_sel_core"], officerScope("s2"), nil)
	if got.annual != nil || got.source != "Not set" {
		t.Errorf("a slice with no figure is not set: %+v", got)
	}
	// A coverage row with no milestone takes its eligible schools.
	got = book.targetOf(byKey["core_visit_1"], officerScope("s1"), &eligible)
	if *got.annual != 401 || got.source != "Eligible schools" {
		t.Errorf("eligible: %+v", got)
	}
	// IA or Admin's country target wins over the plan.
	book.country["cc_sel_core"] = countryTarget{annual: 55, source: "Country target (Admin)"}
	if got = book.targetOf(byKey["cc_sel_core"], countryScope(), nil); *got.annual != 55 || got.months != nil {
		t.Errorf("country target: %+v", got)
	}
	if h := book.holders("SEL_TRAINING"); !reflect.DeepEqual(h, []string{"s1", "s2"}) {
		t.Errorf("holders %v", h)
	}
}

func TestOrderedMonthsKeepTheStoredOrder(t *testing.T) {
	m, err := orderedMonths(`{"1": "10.00", "2": "2.50", "10": "1.00"}`)
	if err != nil || !reflect.DeepEqual(m.order, []int{1, 2, 10}) || m.by[2] != 2.5 {
		t.Fatalf("%v %v", m, err)
	}
	if m, _ := orderedMonths(`{}`); m != nil {
		t.Error("an empty split is no split")
	}
}

func TestAChartIsReadFromItsBarsTitles(t *testing.T) {
	bs := bars([]bar{
		{label: "Program Lead 1", target: nil, achieved: ptr(3)},
		{label: "Program Lead 2", target: ptr(1200), achieved: ptr(0)},
	})
	holder := el("div", "", targetChart(bs, "Programme Lead")...).attr("data-tp-chart", "lead")
	chart := chartOf(holder)
	if chart == nil || !reflect.DeepEqual(chart.Categories, []string{"Program Lead 1", "Program Lead 2"}) {
		t.Fatalf("%v", chart)
	}
	// The first bar's target is a dash, so Achieved is met first.
	if chart.Series[0].Name != "Achieved" || chart.Series[1].Name != "Target" ||
		!reflect.DeepEqual(chart.Series[1].Values, []float64{0, 1200}) {
		t.Errorf("series %v", chart.Series)
	}
	if chartOf(el("div", "", targetChart(nil, "District")...)) != nil {
		t.Error("a chart with no bars is no chart")
	}
}

func TestAPanelPairsALabelWithItsFigure(t *testing.T) {
	card := el("div", "tp-cards", el("article", "",
		el("header", "", el("h3", "", "Alex M."), span("tp-badge", "—")),
		para("", "Portfolio: ", el("strong", "", "0"), " schools"),
		el("div", "tp-stat", span("", "Visits"), el("strong", "", "0"), el("small", "", "Core: 0")),
		el("footer", "", span("", "Enrollment: ", el("strong", "", "—")))))
	p := readPanel(card)
	if p.Title != "Alex M." {
		t.Fatalf("title %q", p.Title)
	}
	// As the feed reads the same HTML (page_blocks.read): the footer's
	// "Enrollment: " runs around its bold figure, so it is one sentence and
	// "Core: 0" is left without a figure to pair with.
	got := []string{}
	for _, item := range p.Items {
		if r := item.GetRows(); r != nil {
			for _, row := range r.Rows {
				got = append(got, row.Label+"="+row.Value)
			}
		} else {
			got = append(got, item.GetText())
		}
	}
	if !reflect.DeepEqual(got, []string{"Portfolio: 0 schools", "Visits=0", "Core: 0", "Enrollment: —"}) {
		t.Errorf("items %v", got)
	}
}

func TestASentenceKeepsItsLeadItsLinksAndItsBlocks(t *testing.T) {
	// page_blocks._sentences on
	// <div data-tone="caution"><strong>Note</strong> see <a href="/x">the list</a>.<p>Apart</p>tail</div>
	n := el("div", "", el("strong", "", "Note"), " see ", el("a", "", "the list").attr("href", "/x"), ".",
		para("", "Apart"), "tail").attr("data-tone", "caution")
	items := panelItems(n, map[*node]bool{}, nil)
	if len(items) != 3 {
		t.Fatalf("%d items", len(items))
	}
	first := items[0]
	if first.GetText() != "Note see the list." || first.Lead != "Note" || first.Tone != "caution" ||
		len(first.TextLinks) != 1 || first.TextLinks[0].Href != "/x" || first.TextLinks[0].Text != "the list" {
		t.Errorf("first %+v", first)
	}
	if items[1].GetText() != "Apart" || items[1].Tone != "" || items[2].GetText() != "tail" || items[2].Tone != "caution" {
		t.Errorf("rest %+v %+v", items[1], items[2])
	}
	if _, ok := plainText(first); ok {
		t.Error("a sentence with a lead is never paired")
	}
}

func TestTheWalkReadsAnEmptyChartCardAsItsParts(t *testing.T) {
	a := &area{key: "msc", label: "MSC Stories", m: byKey["msc"], achieved: ptr(0),
		charts: []areaChart{{level: "district", label: "District"}}}
	got := walk(chartsPart([]*area{a}), nil)
	kinds := []string{}
	for _, b := range got {
		switch b.Kind.(type) {
		case *screensv1.PageBlock_Panel:
			kinds = append(kinds, "panel")
		case *screensv1.PageBlock_Section:
			kinds = append(kinds, "section")
		case *screensv1.PageBlock_Table:
			kinds = append(kinds, "table")
		default:
			kinds = append(kinds, "other")
		}
	}
	if !reflect.DeepEqual(kinds, []string{"panel", "section", "table"}) {
		t.Errorf("blocks %v", kinds)
	}
	if got[0].GetPanel().GetItems()[0].GetText() != "0 of — · stories" {
		t.Errorf("meta %v", got[0].GetPanel())
	}
}

func TestPlaceOfASessionIsWhereMostSchoolsItReachedAre(t *testing.T) {
	l := newLedger("2027")
	l.schools["s"] = &school{pk: "s", region: "Central"}
	for _, r := range []string{"Western", "Eastern", "Eastern", "Western"} {
		l.reached("act", &school{region: r})
	}
	if got := l.placeOf("act", "region"); got != "Eastern" {
		t.Errorf("a tie goes to the first name: %s", got)
	}
	if got := l.placeOf("s", "region"); got != "Central" {
		t.Errorf("a school is where it is: %s", got)
	}
	if got := l.placeOf("none", "region"); got != "" {
		t.Errorf("work at no school is nowhere: %q", got)
	}
}

func TestTheRulesHoldEveryDoor(t *testing.T) {
	if d := rules.Doors["CCEO"]; !d.OpenURL || !d.ViewPage || d.Reach != reachOwn {
		t.Errorf("CCEO: %+v", d)
	}
	if d := rules.Doors["Program Lead"]; d.Reach != reachTeam {
		t.Errorf("Programme Lead: %+v", d)
	}
	if d := rules.Doors["ProjectCoordinator"]; d.OpenURL {
		t.Errorf("Project Coordinator: %+v", d)
	}
	if !rules.Doors["ImpactAssessment"].SetTargets || rules.Doors["CountryDirector"].SetTargets {
		t.Error("only IA and Admin set country targets")
	}
}
