package closedschools

import (
	"fmt"
	"net/url"
	"reflect"
	"strings"
	"testing"
	"time"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
)

func TestTheExportedDoorsAreThePagesOwn(t *testing.T) {
	for role, want := range map[string]Doors{
		"CCEO":                  {Page: true, Profiles: true},
		"Program Lead":          {Page: true, Profiles: true},
		"CountryDirector":       {Page: true, Impact: true, Profiles: true},
		"RegionalVicePresident": {Page: true, Impact: true},
		"Admin":                 {Page: true, Impact: true, Profiles: true},
		"ProjectCoordinator":    {},
	} {
		got := rules.Doors[role]
		if got.Page != want.Page || got.Impact != want.Impact {
			t.Errorf("%s: %+v, want page %v and impact %v", role, got, want.Page, want.Impact)
		}
	}
	if rules.PageSize != 50 || rules.MaxRows != 500 {
		t.Errorf("page size %d and cap %d", rules.PageSize, rules.MaxRows)
	}
}

func TestTruncateCharsIsDjangos(t *testing.T) {
	for _, c := range []struct {
		text   string
		length int
		want   string
	}{
		{"short", 24, "short"},
		{"central division church of uganda primary and more", 24, "central division church…"},
		{strings.Repeat("a", 24), 24, strings.Repeat("a", 24)},
		{strings.Repeat("a", 25), 24, strings.Repeat("a", 23) + "…"},
		// A combining mark is not a character of its own, and the text is composed.
		{"cafe\u0301 au lait", 5, "caf\u00e9…"},
		{"cafe\u0301", 4, "caf\u00e9"},
		{"x\u0301\u0302yz", 2, "x\u0301\u0302…"},
		{"anything", 0, ""},
		{"ab", 1, "…"},
	} {
		if got := truncateChars(c.text, c.length); got != c.want {
			t.Errorf("truncateChars(%q, %d) = %q, want %q", c.text, c.length, got, c.want)
		}
	}
}

func TestTheClearSearchButton(t *testing.T) {
	if h := header(""); len(h.GetActions()) != 0 {
		t.Fatalf("no search, yet %v", h.GetActions())
	}
	for _, c := range []struct{ q, label, key string }{
		{"zzz", "Clear search“zzz”", "clear_search_zzz"},
		{"central division church of uganda primary", "Clear search“central division church…”", "clear_search_central_division_church"},
		{"St.  Mary's", "Clear search“St. Mary's”", "clear_search_st_mary_s"},
		{"İstanbul café", "Clear search“İstanbul café”", "clear_search_i_stanbul_caf"},
		{"%", "Clear search“%”", "clear_search"},
	} {
		a := header(c.q).GetActions()[0]
		if a.GetLabel() != c.label || a.GetKey() != c.key || a.GetHref() != Path || !a.GetEnabled() || a.GetDrawer() || a.GetPrimary() {
			t.Errorf("q=%q: %v, want %q keyed %q", c.q, a, c.label, c.key)
		}
	}
}

func TestPythonsIntOfAPageNumber(t *testing.T) {
	for _, c := range []struct {
		text string
		n    int
		ok   bool
	}{
		{"2", 2, true}, {" 2 ", 2, true}, {"+3", 3, true}, {"-3", -3, true}, {"1_0", 10, true},
		{"abc", 0, false}, {"", 0, false}, {"2.0", 0, false}, {"_1", 0, false}, {"1__0", 0, false}, {"--1", 0, false},
	} {
		if n, ok := pyInt(c.text); n != c.n || ok != c.ok {
			t.Errorf("pyInt(%q) = %d, %v", c.text, n, ok)
		}
	}
	if n, ok := pyInt(strings.Repeat("9", 40)); !ok || n < 1<<40 {
		t.Errorf("a number too long to hold: %d, %v", n, ok)
	}
}

func TestTheTablesPage(t *testing.T) {
	for _, c := range []struct {
		requested     string
		total         int
		number, pages int
	}{
		{"", 0, 1, 1}, {"", 50, 1, 1}, {"", 51, 1, 2}, {"2", 51, 2, 2}, {"3", 51, 2, 2}, {"0", 120, 1, 3},
		{"-4", 120, 1, 3}, {"abc", 120, 1, 3}, {" 3 ", 120, 3, 3}, {strings.Repeat("9", 40), 500, 10, 10},
	} {
		if number, pages := pageOf(c.requested, c.total); number != c.number || pages != c.pages {
			t.Errorf("pageOf(%q, %d) = %d of %d, want %d of %d", c.requested, c.total, number, pages, c.number, c.pages)
		}
	}
}

func TestThePagerWindow(t *testing.T) {
	for _, c := range []struct {
		current, pages int
		want           []int
	}{
		{1, 1, []int{1}},
		{4, 7, []int{1, 2, 3, 4, 5, 6, 7}},
		{1, 10, []int{1, 2, 0, 10}},
		{2, 10, []int{1, 2, 3, 0, 10}},
		{3, 10, []int{1, 2, 3, 4, 0, 10}},
		{4, 10, []int{1, 0, 3, 4, 5, 0, 10}},
		{8, 10, []int{1, 0, 7, 8, 9, 10}},
		{9, 10, []int{1, 0, 8, 9, 10}},
		{10, 10, []int{1, 0, 9, 10}},
	} {
		if got := window(c.current, c.pages); !reflect.DeepEqual(got, c.want) {
			t.Errorf("window(%d, %d) = %v, want %v", c.current, c.pages, got, c.want)
		}
	}
}

func TestThePagersLinksCarryTheRestOfTheQuery(t *testing.T) {
	for _, c := range []struct {
		query url.Values
		want  string
	}{
		{url.Values{}, ""},
		{url.Values{"closed_page": {"3"}}, ""},
		{url.Values{"q": {"a b"}, "fy": {"2025"}, "closed_page": {"3"}}, "fy=2025&q=a+b&"},
		{url.Values{"q": {"St. Mary's & co/50%"}}, "q=St.+Mary%27s+%26+co%2F50%25&"},
		// The feed never passes these on to a page.
		{url.Values{"q": {"x"}, "export": {"1"}, "format": {"csv"}}, "q=x&"},
	} {
		if got := carried(c.query); got != c.want {
			t.Errorf("carried(%v) = %q, want %q", c.query, got, c.want)
		}
	}
}

func panelText(b *screensv1.PageBlock) string {
	parts := []string{}
	for _, item := range b.GetPanel().GetItems() {
		if links := item.GetLinks(); links != nil {
			for _, l := range links.GetLinks() {
				parts = append(parts, fmt.Sprintf("[%s%s %s]", l.GetText(), l.GetCaption(), l.GetHref()))
			}
			parts = append(parts, "/")
			continue
		}
		parts = append(parts, item.GetText())
	}
	return strings.Join(parts, " ")
}

func TestThePagerIsReadAsAPanel(t *testing.T) {
	first := panelText(pager(1, 10, 500, url.Values{}))
	if want := "Showing 1–50 of 500 1 [2 ?closed_page=2] / … [10 ?closed_page=10] [Next› ?closed_page=2] /"; first != want {
		t.Errorf("page 1:\n %s\nwant\n %s", first, want)
	}
	ninth := panelText(pager(9, 10, 500, url.Values{"q": {"primary"}}))
	if want := "Showing 401–450 of 500 [Prev‹ ?q=primary&closed_page=8] [1 ?q=primary&closed_page=1] / … [8 ?q=primary&closed_page=8] / 9 [10 ?q=primary&closed_page=10] [Next› ?q=primary&closed_page=10] /"; ninth != want {
		t.Errorf("page 9:\n %s\nwant\n %s", ninth, want)
	}
	last := panelText(pager(2, 2, 51, url.Values{}))
	if want := "Showing 51–51 of 51 [Prev‹ ?closed_page=1] [1 ?closed_page=1] / 2"; last != want {
		t.Errorf("the last page:\n %s\nwant\n %s", last, want)
	}
}

func texts(r *screensv1.PageRow) []string {
	out := []string{}
	for _, c := range r.GetCells() {
		out = append(out, c.GetText())
	}
	return out
}

func TestARowOfTheArchive(t *testing.T) {
	n := func(v int64) *int64 { return &v }
	day := time.Date(2026, time.September, 5, 0, 0, 0, 0, time.UTC)
	// The cut counts the text as stored, before its spaces are run together.
	long := "The   proprietor closed the school after two terms without enough learners to pay the teachers, and sold the land."
	for _, c := range []struct {
		name          string
		closure       closure
		doors         Doors
		want          []string
		profile, view string
	}{
		{
			name: "a full row",
			closure: closure{SchoolID: "sch1", SchoolCode: "1078", SchoolName: "Central  Primary", District: "Mukono", Owner: " Paul   N. ",
				Effective: day, Type: "temporary", ReasonCategory: "low_enrolment", Reason: long, Enrollment: n(12345)},
			doors:   Doors{Page: true, Profiles: true},
			want:    []string{"1078", "Central Primary 1078", "Mukono", "Paul N.", "5 Sep 2026", "Temporarily closed", "Low enrolment The proprietor closed the school after two terms without enough learners to pay the tea…", "12,345", "View"},
			profile: "/schools/sch1", view: "/schools/1078",
		},
		{
			name: "nothing recorded, and words the lists do not hold",
			closure: closure{SchoolID: "sch 2", SchoolCode: "S/2", SchoolName: "Hill", Effective: day.AddDate(0, 3, 20),
				Type: "sabbatical", ReasonCategory: "mystery", Enrollment: n(0)},
			doors:   Doors{Page: true, Profiles: true},
			want:    []string{"S/2", "Hill S/2", "—", "—", "25 Dec 2026", "sabbatical", "mystery", "Not recorded", "View"},
			profile: "/schools/sch%202", view: "/schools/S/2",
		},
		{
			name:    "a reader who may not open profiles is given the name as text",
			closure: closure{SchoolID: "sch3", SchoolCode: "3", SchoolName: "Lake", Effective: day, Type: "permanent", ReasonCategory: "other", Reason: "short"},
			doors:   Doors{Page: true},
			want:    []string{"3", "Lake 3", "—", "—", "5 Sep 2026", "Permanently closed", "Other short", "Not recorded", "View"},
			view:    "/schools/3",
		},
		{
			name:    "a school with no name has nothing to link",
			closure: closure{SchoolID: "sch4", SchoolCode: "4", Effective: day, Type: "permanent", ReasonCategory: "other"},
			doors:   Doors{Page: true, Profiles: true},
			want:    []string{"4", "4", "—", "—", "5 Sep 2026", "Permanently closed", "Other", "Not recorded", "View"},
			view:    "/schools/4",
		},
	} {
		r := row(c.closure, c.doors)
		if got := texts(r); !reflect.DeepEqual(got, c.want) {
			t.Errorf("%s:\n %q\nwant\n %q", c.name, got, c.want)
		}
		if got := r.GetCells()[1].GetHref(); got != c.profile {
			t.Errorf("%s: the name links to %q, want %q", c.name, got, c.profile)
		}
		if got := r.GetCells()[8].GetHref(); got != c.view {
			t.Errorf("%s: View opens %q, want %q", c.name, got, c.view)
		}
	}
}

func rowsOf(n int) []closure {
	out := []closure{}
	for i := range n {
		out = append(out, closure{SchoolID: fmt.Sprint("s", i), SchoolCode: fmt.Sprint(i), SchoolName: fmt.Sprint("School ", i),
			Effective: time.Date(2026, 1, 1, 0, 0, 0, 0, time.UTC).AddDate(0, 0, -i)})
	}
	return out
}

func TestThePageInItsFourShapes(t *testing.T) {
	doors := Doors{Page: true, Profiles: true}
	// One page of rows: the strip and the table, no pager.
	p := page(view{doors: doors, query: url.Values{}, figures: figures{Closed: 3, Active: 1699, EnrollmentRemoved: 52126048}, rows: rowsOf(3)})
	if len(p.GetBlocks()) != 2 || len(p.GetBlocks()[1].GetTable().GetRows()) != 3 || p.GetWebPath() != Path {
		t.Fatalf("three closures: %v", p)
	}
	strip := p.GetBlocks()[0].GetStrip()
	if strip.GetTitle() != "Performance overview" || strip.GetMetrics()[1].GetValue() != "1,699" || strip.GetMetrics()[2].GetValue() != "52,126,048" ||
		strip.GetMetrics()[2].GetNote() != "Learners, at the moment each school closed" || strip.GetMetrics()[2].GetHelper() != "" {
		t.Fatalf("the strip: %v", strip)
	}
	// More than a page: the page asked for, and the pager under the table.
	p = page(view{doors: doors, query: url.Values{"closed_page": {"3"}}, rows: rowsOf(120)})
	if len(p.GetBlocks()) != 3 || len(p.GetBlocks()[1].GetTable().GetRows()) != 20 ||
		p.GetBlocks()[1].GetTable().GetRows()[0].GetCells()[1].GetText() != "School 100 100" ||
		p.GetBlocks()[1].GetTable().GetFootnote() != "" || p.GetBlocks()[1].GetTable().GetPager() != nil ||
		p.GetBlocks()[2].GetPanel().GetItems()[0].GetText() != "Showing 101–120 of 120" {
		t.Fatalf("the third page of 120: %v", p.GetBlocks()[1:])
	}
	// The year's impact, for its readers: a second strip, the money shortened.
	p = page(view{doors: doors, query: url.Values{}, impact: &impact{Districts: 1, Schools: 1043, Activities: 63, Partners: 42, Budget: "124162500", FY: fyLabel(2027)}})
	second := p.GetBlocks()[1].GetStrip()
	if second.GetTitle() != "Closure Impact" || second.GetMetrics()[0].GetHelper() != "1,043 schools" ||
		second.GetMetrics()[0].GetNote() != "1,043 schools closed in FY 2026/27" || second.GetMetrics()[1].GetValue() != "UGX 124.16M" {
		t.Fatalf("the impact strip: %v", second)
	}
	// Nothing to list: which sentence says so.
	for _, c := range []struct {
		v    view
		want string
	}{
		{view{}, "When a school stops operating"},
		{view{q: "zzz"}, "No closed school name contains that text."},
		{view{summaryOnly: true, q: "zzz", rows: rowsOf(4)}, "Your role reads the archive's figures"},
	} {
		c.v.query = url.Values{}
		p := page(c.v)
		last := p.GetBlocks()[len(p.GetBlocks())-1]
		if !strings.HasPrefix(last.GetEmpty(), c.want) || len(p.GetBlocks()) != 2 {
			t.Errorf("q=%q summary=%v: %v", c.v.q, c.v.summaryOnly, p.GetBlocks())
		}
	}
}

func TestTheYearsLabelAndTheSearchPattern(t *testing.T) {
	if got := fyLabel(2027); got != "FY 2026/27" {
		t.Errorf("fyLabel(2027) = %q", got)
	}
	if got := fyLabel(2100); got != "FY 2099/00" {
		t.Errorf("fyLabel(2100) = %q", got)
	}
	if got := likeContains(`50%_a\b`); got != `%50\%\_a\\b%` {
		t.Errorf("likeContains = %q", got)
	}
	if got := collapse(" a\x1cb \u00a0 c\n"); got != "a b c" {
		t.Errorf("collapse = %q", got)
	}
}

// A School ID cell reads as the web's middleware fills it in: the school's
// ID, or "ID unavailable" for a school without one.
func TestSchoolCodeIsTheWebsFilledInID(t *testing.T) {
	if got := SchoolCode("1599"); got != "1599" {
		t.Fatalf("SchoolCode(1599) = %q", got)
	}
	if got := SchoolCode(""); got != "ID unavailable" {
		t.Fatalf("SchoolCode(\"\") = %q", got)
	}
}
