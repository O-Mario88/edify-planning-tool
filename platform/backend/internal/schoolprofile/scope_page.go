package schoolprofile

import (
	"context"
	"errors"
	"fmt"
	"math"
	"net/url"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pagegate"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// ScopePages are the profiles of many schools in Go
// (frontend.views.profile_views over apps.analytics.profile_intelligence,
// pages/profiles/profile.html): a District's first. Every tab but the
// Overview, a figure's records (what=) and the other kinds of profile are
// still the existing application's.
type ScopePages struct{ s *Service }

// NewScopePages builds the profiles of many schools.
func NewScopePages(db Querier, now func() time.Time) *ScopePages {
	return &ScopePages{s: NewService(db, now)}
}

const districtPrefix = "/districts/"

// Build draws /districts/<id> (extended_views.district_detail_view).
func (sp *ScopePages) Build(ctx context.Context, p auth.Principal, path string, query url.Values) (*screensv1.GetPageResponse, bool, error) {
	if !strings.HasPrefix(path, districtPrefix) {
		return nil, false, nil
	}
	id := strings.TrimPrefix(path, districtPrefix)
	if id == "" || strings.Contains(id, "/") {
		return nil, false, nil
	}
	if !rules.Doors[p.ActiveRole].OpenDistrict {
		return nil, true, pagegate.ErrNotAvailable
	}
	for key := range query {
		if !scopeQueryKeys[key] {
			return nil, false, nil
		}
	}
	s := sp.s
	var name, regionName, subRegionID, subRegionName string
	err := s.db.QueryRow(ctx, `
SELECT d.name, COALESCE(r.name, ''), COALESCE(d.sub_region_id, ''), COALESCE(sr.name, '')
FROM district d LEFT JOIN region r ON r.id = d.region_id LEFT JOIN sub_region sr ON sr.id = d.sub_region_id
WHERE d.id = $1`, id).Scan(&name, &regionName, &subRegionID, &subRegionName)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, true, ErrNotFound
	}
	if err != nil {
		return nil, true, fmt.Errorf("schoolprofile: reading the district: %w", err)
	}
	scope := scopeOf{kind: "district", key: id, name: name + " District", covers: "All schools in the district",
		where: "s.district_id = $2", args: []any{id}}
	page := scopePage{scope: scope, base: districtPrefix + id, back: [2]string{"Back to Districts", "/districts"}, lead: regionName}
	page.facts = func(pr *scopeProfile) []*screensv1.PageFact {
		facts := []*screensv1.PageFact{{Label: "Type", Value: "District"}}
		if subRegionID != "" && subRegionName != "" {
			facts = append(facts, &screensv1.PageFact{Label: "Sub-region", Value: subRegionName, Href: "/sub-regions/" + subRegionID})
		}
		open := rules.Doors[p.ActiveRole].OpenStaff
		return append(facts, peopleFact("Programme Lead", pr.leads, open, "/staff/"), peopleFact("CCEO", pr.staff, open, "/staff/"))
	}
	return s.scopePage(ctx, p, page, query)
}

// scopeQueryKeys are the keys a profile's own links carry; anything else
// is still the existing application's.
var scopeQueryKeys = map[string]bool{"tab": true, "fy": true, "period": true, "show": true, "what": true}

// scopePage is one kind of profile page: its scope, its address, its back
// link, the line before its scope line and its own header facts.
type scopePage struct {
	scope scopeOf
	base  string
	back  [2]string
	lead  string
	facts func(*scopeProfile) []*screensv1.PageFact
}

// scopePage draws a profile page (profile_context and profile.html).
func (s *Service) scopePage(ctx context.Context, p auth.Principal, page scopePage, query url.Values) (*screensv1.GetPageResponse, bool, error) {
	now := s.now()
	running := schooldirectory.OperationalFY(now)
	fy := query.Get("fy")
	known := false
	for _, year := range fyChoices(running) {
		known = known || year == fy
	}
	if !known {
		fy = running
	}
	period := query.Get("period")
	if !knownPeriod(period) {
		period = ""
	}
	sections := rules.Engine.Scope.SectionsOf[page.scope.kind]
	tab := query.Get("tab")
	if !contains(sections, tab) {
		tab = sections[0]
	}
	if tab != "overview" || query.Get("what") != "" {
		return nil, false, nil
	}
	l := lens{tab: tab, fy: fy, period: period, running: running, window: periodWindow(fy, period), base: page.base}
	reader, err := schooldirectory.ResolveScope(ctx, s.db, p, now)
	if err != nil {
		return nil, true, err
	}
	pr, err := s.readScopeProfile(ctx, btReader{p: p, scope: reader, doors: rules.Doors[p.ActiveRole]}, page.scope, l, now)
	if err != nil {
		return nil, true, err
	}
	labels := map[string]string{}
	for _, pair := range rules.Engine.Scope.Sections {
		labels[pair[0]] = pair[1]
	}
	tabs := []*screensv1.PageTab{}
	for _, key := range sections {
		tabs = append(tabs, &screensv1.PageTab{Key: key, Label: labels[key], Active: key == tab})
	}
	header := &screensv1.PageHeader{BackLabel: page.back[0], BackHref: page.back[1], Title: page.scope.name,
		Description: pr.scopeLine(page.lead, l)}
	facts := append(page.facts(pr), &screensv1.PageFact{Label: "Fiscal Year", Value: fyLabel(fy)})
	blocks := []*screensv1.PageBlock{
		{Kind: &screensv1.PageBlock_Facts{Facts: &screensv1.PageFacts{Facts: facts}}},
		scopeFilters(l),
	}
	blocks = append(blocks, pr.overview(l)...)
	tables := pr.tables(l, pr.book, pr.focus, rules.Doors[p.ActiveRole].Profile)
	if tables == nil {
		return nil, false, nil
	}
	blocks = append(blocks, tables...)
	return &screensv1.GetPageResponse{Header: header, Tabs: tabs, Blocks: blocks, WebPath: page.base}, true, nil
}

// scopeFilters is partials/profiles/_filters.html: the year and the period.
func scopeFilters(l lens) *screensv1.PageBlock {
	fyOptions := []*screensv1.PageFilterOption{}
	for _, year := range fyChoices(l.running) {
		fyOptions = append(fyOptions, &screensv1.PageFilterOption{Value: year, Label: fyLabel(year)})
	}
	periods := []*screensv1.PageFilterOption{}
	for _, o := range periodOptions() {
		periods = append(periods, &screensv1.PageFilterOption{Value: o[0], Label: o[1]})
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Filters{Filters: &screensv1.PageFilters{
		Filters: []*screensv1.PageFilter{
			{Name: "fy", Label: "Fiscal year", Value: l.fy, Options: fyOptions},
			{Name: "period", Label: "Period", Value: l.period, Options: periods},
		},
		Hidden: map[string]string{"tab": l.tab},
	}}}
}

func contains(list []string, v string) bool {
	for _, x := range list {
		if x == v {
			return true
		}
	}
	return false
}

// pyRoundHalfEven is Python's round(x) for a whole number.
func pyRoundHalfEven(x float64) int { return int(math.RoundToEven(x)) }
