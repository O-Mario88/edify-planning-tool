package teamperformance

import (
	"context"
	"net/url"
	"slices"
	"strings"
	"time"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pagegate"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// Path is the page this package answers (apps.mobile_feed.views names
// team_performance among the pages the feed reads).
const Path = "/team-performance/"

// under is every other address of the page: the same without its slash and
// anything below it (the Country Targets editor among them), which the feed
// does not read.
const under = "/team-performance"

// ErrNotAvailable is the page refused to the reader.
var ErrNotAvailable = pagegate.ErrNotAvailable

// Service builds the Team Performance page.
type Service struct {
	db  schooldirectory.Querier
	now func() time.Time
}

// NewService wires the service to the database it reads.
func NewService(db schooldirectory.Querier, now func() time.Time) *Service {
	return &Service{db: db, now: now}
}

var nairobi = func() *time.Location {
	zone, err := time.LoadLocation("Africa/Nairobi")
	if err != nil {
		return time.FixedZone("EAT", 3*60*60)
	}
	return zone
}()

// localToday is timezone.localdate().
func localToday(now time.Time) day {
	t := now.In(nairobi)
	return dateOf(t.Year(), t.Month(), t.Day())
}

// Build answers path for p. served is false for a path that is not this
// page's, and for a role the page's own gate would turn away with its
// access-denied page rather than the feed's not-found.
func (s *Service) Build(ctx context.Context, p auth.Principal, path string, query url.Values) (*screensv1.GetPageResponse, bool, error) {
	if path != Path {
		if path == under || strings.HasPrefix(path, Path) {
			return nil, true, ErrNotAvailable
		}
		return nil, false, nil
	}
	d, ok := rules.Doors[p.ActiveRole]
	if !ok {
		return nil, false, nil
	}
	if !d.OpenURL {
		return nil, true, ErrNotAvailable
	}
	if !d.ViewPage {
		return nil, false, nil
	}
	get := func(key string) string {
		if slices.Contains(rules.NotPassed, key) {
			return ""
		}
		values := query[key]
		if len(values) == 0 {
			return ""
		}
		return values[len(values)-1]
	}
	now := s.now()
	today := localToday(now)
	per := resolvePeriod(get("fy"), get("month"), get("period"), get("quarter"), get("week"), today)
	tab := "summary"
	reads := ""
	for _, t := range rules.Tabs {
		if t[0] == get("tab") {
			tab = get("tab")
		}
	}
	for _, t := range rules.Tabs {
		if t[0] == tab {
			reads = t[2]
		}
	}
	r, err := buildReport(ctx, s.db, p, per)
	if err != nil {
		return nil, true, err
	}
	if tab == "summary" && get("charts") != "" {
		charts := r.sectionCharts(get("charts"), get("by"), get("in_region"), get("in_lead"))
		if charts == nil {
			return nil, true, ErrNotAvailable
		}
		return &screensv1.GetPageResponse{Header: &screensv1.PageHeader{}, Blocks: walk(chartsPart(charts), nil), WebPath: Path}, true, nil
	}
	years := slices.Clone(schooldirectory.FYOptions(now))
	slices.Sort(years)
	slices.Reverse(years)
	v := &pageView{get: get, tab: tab, reads: reads, per: per, years: years, r: r, setter: d.SetTargets}
	for _, key := range rules.Kept {
		if value := get(key); value != "" {
			v.kept = append(v.kept, [2]string{key, value})
		}
	}
	return &screensv1.GetPageResponse{Header: v.header(), Blocks: v.blocks(), WebPath: Path}, true, nil
}

// blocks is the page's index.html below its header, read as the feed reads it.
func (v *pageView) blocks() []*screensv1.PageBlock {
	r := v.r
	var scopes []scopeOption
	var opt scopeOption
	var dashOfficer *officer
	var dash struct {
		view, lead, leadLabel, sort, query string
	}
	switch v.tab {
	case "weekly":
		opt = r.scopeFor(v.get("scope"))
		scopes = r.scopes()
	case "dashboard":
		dash.view = "cceos"
		for _, dv := range rules.DashboardViews {
			if dv[0] == v.get("view") {
				dash.view = dv[0]
			}
		}
		if t := r.roster.team(v.get("lead")); t != nil && v.get("lead") != "" {
			dash.lead, dash.leadLabel = t.key, t.label
		}
		dash.sort = "name"
		for _, s := range rules.Sorts {
			if s[0] == v.get("sort") {
				dash.sort = s[0]
			}
		}
		dashOfficer = r.roster.officer(v.get("officer"))
		if dashOfficer == nil && len(r.roster.officers()) > 0 {
			dashOfficer = r.roster.officers()[0]
		}
		pairs := append([][2]string{}, v.kept...)
		for _, kv := range [][2]string{{"lead", dash.lead}, {"sort", dash.sort}, {"officer", officerID(dashOfficer)}} {
			if kv[1] != "" {
				pairs = append(pairs, kv)
			}
		}
		dash.query = query(pairs)
	}
	content := el("div", "", preBlock(v.filters(scopes, opt.key, dashOfficer)), preBlock(v.tabsBlock()))
	switch {
	case len(r.roster.officers()) == 0:
		content.Add(emptyState(noOfficers))
	case v.tab == "summary":
		content.Add(v.summaryTab())
	case v.tab == "weekly":
		content.Add(v.weeklyTab(opt))
	case v.tab == "milestones":
		content.Add(v.milestonesPart(false))
	case v.tab == "dashboard":
		content.Add(v.dashboardTab(dash.view, dash.lead, dash.leadLabel, dash.sort, dashOfficer, dash.query))
	case v.tab == "month":
		content.Add(v.monthTab())
	default:
		content.Add(v.coreTab())
	}
	return walk(el("main", "", content), nil)
}

func officerID(o *officer) string {
	if o == nil {
		return ""
	}
	return o.staffID
}
