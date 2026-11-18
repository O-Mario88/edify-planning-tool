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

const (
	districtPrefix     = "/districts/"
	subRegionPrefix    = "/sub-regions/"
	countryProfilePath = "/country-profile"
)

// country draws /country-profile (profile_views.country_profile_view):
// every school of the reader's country, read by sub-region, district,
// staff and cluster. The decision review its Overview carries for a reader
// who holds it is still the existing application's.
func (sp *ScopePages) country(ctx context.Context, p auth.Principal, query url.Values) (*screensv1.GetPageResponse, bool, error) {
	d := rules.Doors[p.ActiveRole]
	if !d.CountryProfile {
		return nil, true, pagegate.ErrNotAvailable
	}
	for key := range query {
		if !scopeQueryKeys[key] {
			return nil, false, nil
		}
	}
	tab := query.Get("tab")
	if !contains(rules.Engine.Scope.SectionsOf["country"], tab) {
		tab = "overview"
	}
	if tab == "overview" && d.Decisions {
		return nil, false, nil
	}
	s := sp.s
	// training_ceilings.country_of: the reader's profile's country, else
	// the platform's.
	var country string
	err := s.db.QueryRow(ctx, `SELECT COALESCE(btrim(country), '') FROM staff_profile WHERE user_id = $1 ORDER BY id LIMIT 1`,
		p.UserID).Scan(&country)
	if err != nil && !errors.Is(err, pgx.ErrNoRows) {
		return nil, true, fmt.Errorf("schoolprofile: reading the reader's country: %w", err)
	}
	if country == "" {
		country = rules.Engine.Scope.DefaultCountry
	}
	// A school the upload could not place has no region: it is still the
	// country's.
	scope := scopeOf{kind: "country", key: country, name: country, covers: "Every school in the country",
		where: "(s.region_id IS NULL OR EXISTS (SELECT 1 FROM region r WHERE r.id = s.region_id AND r.country = $2))", args: []any{country}}
	page := scopePage{scope: scope, base: countryProfilePath, lead: "Edify Operations", title: country + " Profile"}
	page.facts = func(pr *scopeProfile) []*screensv1.PageFact {
		subRegions, districts := map[string]bool{}, map[string]bool{}
		for _, x := range pr.schools {
			if x.subRegion != "" {
				subRegions[x.subRegion] = true
			}
			if x.district != "" {
				districts[x.district] = true
			}
		}
		return []*screensv1.PageFact{
			{Label: "Type", Value: "Country"},
			{Label: "Sub-regions", Value: intcomma(len(subRegions))},
			{Label: "Districts", Value: intcomma(len(districts))},
			peopleFact("Programme Lead", pr.leads, d.OpenStaff, "/staff/"),
			{Label: "Staff Holding Schools", Value: intcomma(len(pr.staff))},
		}
	}
	return s.scopePage(ctx, p, page, query)
}

// subRegion draws /sub-regions/<id>: its districts, staff, clusters and
// schools.
func (sp *ScopePages) subRegion(ctx context.Context, p auth.Principal, id string, query url.Values) (*screensv1.GetPageResponse, bool, error) {
	if id == "" || strings.Contains(id, "/") {
		return nil, false, nil
	}
	if !rules.Doors[p.ActiveRole].OpenSubRegion {
		return nil, true, pagegate.ErrNotAvailable
	}
	for key := range query {
		if !scopeQueryKeys[key] {
			return nil, false, nil
		}
	}
	s := sp.s
	var name, regionName, country string
	var hasRegion bool
	err := s.db.QueryRow(ctx, `
SELECT sr.name, COALESCE(r.name, ''), COALESCE(r.country, ''), sr.region_id IS NOT NULL
FROM sub_region sr LEFT JOIN region r ON r.id = sr.region_id WHERE sr.id = $1`, id).Scan(&name, &regionName, &country, &hasRegion)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, true, ErrNotFound
	}
	if err != nil {
		return nil, true, fmt.Errorf("schoolprofile: reading the sub-region: %w", err)
	}
	// A school's sub-region is its district's; the school's own column
	// counts only where its district names none.
	scope := scopeOf{kind: "sub_region", key: id, name: name + " Sub-region", covers: "All schools in the sub-region",
		where: "(d.sub_region_id = $2 OR (d.sub_region_id IS NULL AND s.sub_region_id = $2))", args: []any{id}}
	page := scopePage{scope: scope, base: subRegionPrefix + id, back: [2]string{"Back to Country profile", "/country-profile?tab=sub_regions"}}
	if hasRegion {
		page.lead = regionName
	}
	page.facts = func(pr *scopeProfile) []*screensv1.PageFact {
		facts := []*screensv1.PageFact{{Label: "Type", Value: "Sub-region"}}
		if hasRegion {
			if regionName != "" {
				facts = append(facts, &screensv1.PageFact{Label: "Region", Value: regionName})
			}
			if country != "" {
				facts = append(facts, &screensv1.PageFact{Label: "Country", Value: country})
			}
		}
		districts := map[string]bool{}
		for _, x := range pr.schools {
			if x.district != "" {
				districts[x.district] = true
			}
		}
		open := rules.Doors[p.ActiveRole].OpenStaff
		return append(facts, &screensv1.PageFact{Label: "Districts", Value: intcomma(len(districts))},
			peopleFact("Programme Lead", pr.leads, open, "/staff/"), peopleFact("CCEO", pr.staff, open, "/staff/"))
	}
	return s.scopePage(ctx, p, page, query)
}

// Build draws /districts/<id> (extended_views.district_detail_view) and
// /sub-regions/<id> (profile_views.sub_region_profile_view).
func (sp *ScopePages) Build(ctx context.Context, p auth.Principal, path string, query url.Values) (*screensv1.GetPageResponse, bool, error) {
	if strings.HasPrefix(path, subRegionPrefix) {
		return sp.subRegion(ctx, p, strings.TrimPrefix(path, subRegionPrefix), query)
	}
	if path == countryProfilePath {
		return sp.country(ctx, p, query)
	}
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
// scopeTabsInGo are the sections Go draws; the rest are still the existing
// application's.
var scopeTabsInGo = map[string]bool{"overview": true, "ssa": true, "sub_counties": true, "staff": true, "districts": true, "sub_regions": true, "schools": true, "projects": true, "clusters": true}

// tablePageSize is the shared table pager's page (TABLE_PAGE_SIZE).
const tablePageSize = 50

var scopeQueryKeys = map[string]bool{"tab": true, "fy": true, "period": true, "show": true, "what": true, "parts_page": true, "schools_page": true, "sub_county": true, "projects_page": true, "clusters_page": true}

// scopePage is one kind of profile page: its scope, its address, its back
// link, the line before its scope line and its own header facts.
type scopePage struct {
	scope scopeOf
	base  string
	back  [2]string
	lead  string
	// title is the page's title where it is not the scope's name.
	title string
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
	if !scopeTabsInGo[tab] || query.Get("what") != "" {
		return nil, false, nil
	}
	l := lens{tab: tab, fy: fy, period: period, running: running, window: periodWindow(fy, period), base: page.base, query: query}
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
	title := page.scope.name
	if page.title != "" {
		title = page.title
	}
	header := &screensv1.PageHeader{BackLabel: page.back[0], BackHref: page.back[1], Title: title,
		Description: pr.scopeLine(page.lead, l)}
	facts := append(page.facts(pr), &screensv1.PageFact{Label: "Fiscal Year", Value: fyLabel(fy)})
	filters := scopeFilters(l)
	if tab == "schools" {
		// The Schools tab's Show list, and the sub-county a part's row opened.
		show := query.Get("show")
		if _, ok := rules.Engine.Scope.ShowLabels[show]; !ok {
			show = "all"
		}
		options := []*screensv1.PageFilterOption{}
		for _, key := range rules.Engine.Scope.ShowOrder {
			options = append(options, &screensv1.PageFilterOption{Value: key, Label: rules.Engine.Scope.ShowLabels[key]})
		}
		f := filters.GetFilters()
		f.Filters = append(f.Filters, &screensv1.PageFilter{Name: "show", Label: "Show", Value: show, Options: options})
		if sub := query.Get("sub_county"); sub != "" {
			f.Hidden["sub_county"] = sub
		}
	}
	blocks := []*screensv1.PageBlock{
		{Kind: &screensv1.PageBlock_Facts{Facts: &screensv1.PageFacts{Facts: facts}}},
		filters,
	}
	switch tab {
	case "overview":
		blocks = append(blocks, pr.overview(l)...)
		parts := map[string][]part{}
		for _, level := range rules.Engine.Scope.LevelsOf[page.scope.kind] {
			if level == "schools" || level == "clusters" {
				continue
			}
			rows, _, err := s.groups(ctx, pr, level, pr.planned)
			if err != nil {
				return nil, true, err
			}
			parts[level] = rows
		}
		tables := pr.tables(l, pr.book, pr.focus, rules.Doors[p.ActiveRole].Profile, parts)
		if tables == nil {
			return nil, false, nil
		}
		blocks = append(blocks, tables...)
	case "ssa":
		atTarget := 0
		for _, x := range pr.schools {
			if c := pr.scores[x.id].current; c != nil && *c >= rules.Engine.SSATarget {
				atTarget++
			}
		}
		progress, err := s.progressByYear(ctx, idsOf(pr.schools))
		if err != nil {
			return nil, true, err
		}
		blocks = append(blocks, ssaSection(pr.cmp, pr.overall, atTarget, l, progress)...)
	case "schools":
		show := query.Get("show")
		if _, ok := rules.Engine.Scope.ShowLabels[show]; !ok {
			show = "all"
		}
		blocks = append(blocks, pr.schoolsBlocks(l, show, query.Get("sub_county"), rules.Doors[p.ActiveRole])...)
	case "clusters":
		if s.clusterCards == nil {
			return nil, false, nil
		}
		lines, err := s.clusterLines(ctx, pr, fy, kampalaDay(now).Format("2006-01-02"))
		if err != nil {
			return nil, true, err
		}
		blocks = append(blocks, pr.clustersBlocks(l, lines, rules.Doors[p.ActiveRole], s.clusterCards.AlertAfter())...)
	case "projects":
		projects, err := s.scopeProjects(ctx, pr, l)
		if err != nil {
			return nil, true, err
		}
		blocks = append(blocks, projectsBlocks(l, projects, rules.Doors[p.ActiveRole].OpenProjects)...)
	case "sub_counties", "staff", "districts", "sub_regions":
		rows, unplaced, err := s.groups(ctx, pr, tab, pr.planned)
		if err != nil {
			return nil, true, err
		}
		blocks = append(blocks, pr.partsBlocks(l, tab, rows, unplaced, tab != "staff" || rules.Doors[p.ActiveRole].OpenStaff)...)
	}
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
