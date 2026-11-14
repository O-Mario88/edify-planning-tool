package oversightportfolio

import (
	"context"
	"errors"
	"net/url"
	"testing"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pagegate"
)

func row(id, name, officerID, officer, leadID, lead string, activities int) school {
	return school{id: id, code: id, name: name, officerID: officerID, officerName: officer,
		leadID: leadID, leadName: lead, activities: activities}
}

// The seed holds one lead with one officer, so the order of columns, the
// unassigned and no-lead headings and the dropping of emptied officers are
// proved here.
func TestGroupOrdersLeadsAndOfficersAsThePortfolioService(t *testing.T) {
	rows := []school{
		row("1", "A", rules.UnassignedKey, rules.UnassignedLabel, rules.NoLeadKey, rules.NoLeadLabel, 0),
		row("2", "B", "o2", "zed", "l2", "beth", 1),
		row("3", "C", "o1", "Amy", "l2", "beth", 0),
		row("4", "D", "o3", "Carl", "l1", "Adam", 2),
		row("5", "E", rules.UnassignedKey, rules.UnassignedLabel, "l2", "beth", 0),
	}
	leads := group(rows, "")
	got := []string{}
	for _, l := range leads {
		got = append(got, l.name)
		for _, o := range l.officers {
			got = append(got, "  "+o.name)
		}
	}
	want := []string{"Adam", "  Carl", "beth", "  Amy", "  zed", "  " + rules.UnassignedLabel, rules.NoLeadLabel, "  " + rules.UnassignedLabel}
	if len(got) != len(want) {
		t.Fatalf("group = %q, want %q", got, want)
	}
	for i := range want {
		if got[i] != want[i] {
			t.Fatalf("group = %q, want %q", got, want)
		}
	}

	// Asking for the planned schools drops the officers with none listed and
	// the leads left with no officer; the headings still count every school.
	planned := group(rows, "planned")
	if len(planned) != 2 || planned[0].name != "Adam" || planned[1].name != "beth" || len(planned[1].officers) != 1 {
		t.Fatalf("planned group = %+v", planned)
	}
	if o := planned[1].officers[0]; o.count() != 1 || len(o.visible) != 1 || planned[1].count() != 1 {
		t.Fatalf("beth's officer = %+v", o)
	}
	if n := len(group(rows, "unplanned")); n != 2 {
		t.Fatalf("unplanned leads = %d, want 2", n)
	}
}

func TestBuildFoldsTotalsBeforeTheLeadFilter(t *testing.T) {
	rows := []school{
		row("1", "A", "o1", "Amy", "l1", "Adam", 1),
		row("2", "B", "o2", "Bo", "l2", "Beth", 0),
		row("3", "C", "o2", "Bo", "l2", "Beth", 0),
	}
	p := build(rows, "l1", "")
	if p.totals.schools != 3 || p.totals.planned != 1 || p.totals.leads != 2 || p.totals.officers != 2 {
		t.Fatalf("totals = %+v", p.totals)
	}
	if len(p.options) != 2 || p.options[1].count != 2 || len(p.leads) != 1 {
		t.Fatalf("options %+v, leads %d", p.options, len(p.leads))
	}
	for _, all := range []string{"all", "All", ""} {
		if n := len(build(rows, all, "").leads); n != 2 {
			t.Fatalf("lead %q: %d leads, want 2", all, n)
		}
	}
}

func TestSharesRoundAsPython(t *testing.T) {
	cases := []struct {
		part, whole int
		share       int
		ratio       string
	}{
		{1, 8, 12, "12.5%"}, {3, 8, 38, "37.5%"}, {4, 699, 1, "0.6%"}, {2, 3, 67, "66.7%"},
		{1, 1, 100, "100%"}, {0, 5, 0, "0%"}, {1, 200, 0, "0.5%"},
	}
	for _, c := range cases {
		if got := *share(c.part, c.whole); got != c.share {
			t.Errorf("share(%d, %d) = %d, want %d", c.part, c.whole, got, c.share)
		}
		if got := ratio(c.part, c.whole); got != c.ratio {
			t.Errorf("ratio(%d, %d) = %q, want %q", c.part, c.whole, got, c.ratio)
		}
	}
	if share(0, 0) != nil || ratio(0, 0) != "" {
		t.Fatal("nothing to divide must be no share")
	}
}

func TestLeadCoverageTones(t *testing.T) {
	cases := []struct {
		planned, count int
		text, tone     string
	}{
		{4, 5, "80% planned", "success"}, {1, 2, "50% planned", "warning"}, {1, 3, "33% planned", "danger"},
	}
	for _, c := range cases {
		o := &officerGroup{}
		for i := 0; i < c.count; i++ {
			a := 0
			if i < c.planned {
				a = 1
			}
			o.schools = append(o.schools, school{activities: a})
		}
		items := leadBlock(&leadGroup{name: "L", officers: []*officerGroup{o}}).GetPanel().GetItems()
		last := items[len(items)-1]
		if last.GetText() != c.text || last.GetTone() != c.tone {
			t.Errorf("%d of %d: %q %q", c.planned, c.count, last.GetText(), last.GetTone())
		}
	}
}

func TestSchoolRowWritesTheTemplatesWords(t *testing.T) {
	day := time.Date(2026, 10, 5, 0, 0, 0, 0, time.UTC)
	cases := []struct {
		s    school
		want []string
	}{
		{school{name: "A", district: "", clusterID: ""}, []string{"—", "A", "—", "No cluster", "Nothing planned", "0", "0", "—", "UGX 0"}},
		{school{code: "12", name: "B", districtID: "d", district: "Mukono", clusterID: "c", clusterName: "", activities: 3, visits: 2, trainings: 1, firstDate: &day, budget: 1234567},
			[]string{"", "B", "Mukono", "—", "3 planned", "2", "1", "5 Oct 2026", "UGX 1,234,567"}},
	}
	for _, c := range cases {
		cells := schoolRow(c.s).GetCells()
		for i, w := range c.want {
			if cells[i].GetText() != w {
				t.Errorf("%s cell %d = %q, want %q", c.s.name, i, cells[i].GetText(), w)
			}
		}
		if cells[1].GetHref() != "/schools/"+c.s.code {
			t.Errorf("school link %q", cells[1].GetHref())
		}
	}
}

func TestOfficerPageParam(t *testing.T) {
	for key, want := range map[string]string{
		"cmw9p7bwp00t19mekheun": "portfolio_cmw9p7bwp00t19mekheun_page",
		rules.UnassignedKey:     "portfolio_unassigned_page",
		"__":                    "portfolio_officer_page",
		"a-b":                   "portfolio_a_b_page",
	} {
		if got := (officerGroup{key: key}).pageParam(); got != want {
			t.Errorf("pageParam(%q) = %q, want %q", key, got, want)
		}
	}
}

func TestEmptyPortfolio(t *testing.T) {
	v := view{fy: "2027", p: build(nil, "", "")}
	resp := page(v, []string{"2026", "2027"})
	blocks := resp.GetBlocks()
	if got := blocks[len(blocks)-1].GetEmpty(); got != emptyMessage {
		t.Fatalf("last block = %v", blocks[len(blocks)-1])
	}
	metrics := blocks[0].GetStrip().GetMetrics()
	if metrics[1].GetValue() != "No schools in scope" || metrics[0].GetHelper() != "0 leads · 0 officers" {
		t.Fatalf("strip = %v", metrics)
	}
	if resp.GetHeader().GetDescription() != teamDescription {
		t.Fatalf("description = %q", resp.GetHeader().GetDescription())
	}
}

// The doors and the questions handed on are answered before the database
// is read, so a service with no database proves them.
func TestBuildDoors(t *testing.T) {
	s := NewService(nil, time.Now)
	cases := []struct {
		name   string
		role   string
		path   string
		query  url.Values
		served bool
		err    error
	}{
		{"another path", "Admin", "/team-planning-oversight", url.Values{"view": {"portfolio"}}, false, nil},
		{"another lens", "Admin", Path, url.Values{"view": {"coverage"}}, false, nil},
		{"the Team Plan", "Admin", Path, url.Values{}, false, nil},
		{"a refused reader", "CCEO", Path, url.Values{"view": {"portfolio"}}, true, pagegate.ErrNotAvailable},
		{"no renderer", "Admin", Path, url.Values{"view": {"portfolio"}, "format": {"xml"}}, true, pagegate.ErrNotAvailable},
		{"the Accountant falls back to the Team Plan", "Accountant", Path, url.Values{"view": {"portfolio"}}, false, nil},
		{"an unknown role", "Nobody", Path, url.Values{"view": {"portfolio"}}, false, nil},
		{"a planning follow-up", "Admin", Path, url.Values{"view": {"portfolio"}, "followup": {"x"}}, false, nil},
		{"a list of ids", "Admin", Path, url.Values{"view": {"portfolio"}, "ids": {"a,b"}}, false, nil},
		{"a year the page cannot read", "Admin", Path, url.Values{"view": {"portfolio"}, "fy": {"abc"}}, false, nil},
		{"a month int() refuses", "Admin", Path, url.Values{"view": {"portfolio"}, "month": {"²"}}, false, nil},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			_, served, err := s.Build(context.Background(), auth.Principal{ActiveRole: c.role}, c.path, c.query)
			if served != c.served || !errors.Is(err, c.err) && err != c.err {
				t.Fatalf("served %v err %v, want %v %v", served, err, c.served, c.err)
			}
		})
	}
}

func TestEveryRoleThePortfolioOpensForOpensThePage(t *testing.T) {
	for role, d := range rules.Doors {
		if d.Portfolio && (!d.Page || !d.FeedOpens) {
			t.Errorf("%s: the lens opens but the page does not", role)
		}
	}
}
