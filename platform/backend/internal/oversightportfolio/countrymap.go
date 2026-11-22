package oversightportfolio

import (
	"context"
	"fmt"
	"net/url"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/myplan"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pagegate"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// The Country Map (/country-map/: oversight_views.country_map_view,
// pages/oversight/country_map.html): the map of the country, which the
// browser draws from the shared analytics (Python), and under it the country
// portfolio the Planning Oversight lens draws. The feed reads the map's card
// as its fixed words, the one line of totals and an empty sub-region table
// the browser fills; Go writes the same and counts the totals as
// subregion_performance does.
const (
	CountryMapPath  = "/country-map/"
	mapTitle        = "Country Map"
	mapEyebrow      = "Country Oversight"
	mapDescription  = "Where the country's delivery, backlog and money sit, and every school in the country portfolio under the Programme Lead and CCEO who hold it."
	mapCardTitle    = "Performance by Sub-Region ⓘ"
	mapCardSubtitle = "UBOS boundaries · sub-county detail on district zoom · Country-wide system data"
	aboutFigures    = "Planned counts every school visit, cluster meeting or cluster training planned for the financial year, including the ones already delivered; achieved counts those completed, shown as achieved/planned. Assigned to partner counts activities handed to a partner. Cluster sessions count in the district and sub-county the cluster is filed under."
)

// The words of the map card the browser fills in (regional_performance.html).
var mapCardWords = []string{
	"Loading district boundaries…", "The map could not load.", "Try again", "Sub-county detail unavailable Retry",
	"▲ Strongest", "▼ Weakest", "Too few confirmed assessments to rank interventions.", "Schools",
}

// The sub-region table's columns; its rows are the browser's.
var distributionColumns = []struct {
	label   string
	numeric bool
}{
	{"Sub-region", false}, {"Schools", true}, {"Clusters", true}, {"Visits planned", true}, {"Visits achieved", true},
	{"Meetings planned", true}, {"Meetings achieved", true}, {"Trainings planned", true}, {"Trainings achieved", true}, {"Partner", true},
}

// CountryMap builds /country-map/ and serves the cached country map data API.
type CountryMap struct {
	s     *Service
	cache *mapDataCache
}

// NewCountryMap is the Country Map over the portfolio service.
func NewCountryMap(s *Service) *CountryMap { return &CountryMap{s: s, cache: newMapDataCache()} }

// mapTotals is subregion_performance's totals line: the districts filed under
// a sub-region, the sub-regions they name, and the operating schools in them.
func mapTotals(ctx context.Context, db schooldirectory.Querier) (districts, subregions, schools int, err error) {
	err = db.QueryRow(ctx, `
SELECT (SELECT count(*) FROM district d WHERE d.sub_region_id IS NOT NULL),
  (SELECT count(DISTINCT sr.name) FROM district d JOIN sub_region sr ON sr.id = d.sub_region_id),
  (SELECT count(*) FROM school s JOIN district d ON d.id = s.district_id
     WHERE d.sub_region_id IS NOT NULL AND s.deleted_at IS NULL AND s.operational_status = ANY($1))`,
		rules.OperatingStatuses).Scan(&districts, &subregions, &schools)
	if err != nil {
		err = fmt.Errorf("oversightportfolio: counting the map's totals: %w", err)
	}
	return districts, subregions, schools, err
}

func panelOf(title, subtitle string, items ...*screensv1.PagePanelItem) *screensv1.PageBlock {
	return block(&screensv1.PagePanel{Title: title, Subtitle: subtitle, Items: items})
}

// mapBlocks is the map card as the feed reads it.
func mapBlocks(districts, subregions, schools int) []*screensv1.PageBlock {
	words := make([]*screensv1.PagePanelItem, 0, len(mapCardWords))
	for _, w := range mapCardWords {
		words = append(words, text(w))
	}
	columns := make([]*screensv1.PageColumn, 0, len(distributionColumns))
	empty := make([]*screensv1.PageCell, 0, len(distributionColumns))
	for _, c := range distributionColumns {
		columns = append(columns, &screensv1.PageColumn{Label: c.label, Numeric: c.numeric})
		empty = append(empty, &screensv1.PageCell{})
	}
	return []*screensv1.PageBlock{
		panelOf(mapCardTitle, mapCardSubtitle),
		panelOf("", "", words...),
		panelOf("", "", text("Distribution by Sub-Region"),
			text(fmt.Sprintf("%d districts · %d sub-regions · %d schools", districts, subregions, schools))),
		block(&screensv1.PageTable{Columns: columns, Rows: []*screensv1.PageRow{{Cells: empty}}}),
		panelOf("", "", &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Heading{Heading: "About these figures"}}, text(aboutFigures)),
	}
}

// Build answers /country-map/ for a reader the page opens for; the feed
// refuses the others. The portfolio under the map is drawn only when it
// holds a school (has_portfolio).
func (c *CountryMap) Build(ctx context.Context, p auth.Principal, path string, query url.Values) (*screensv1.GetPageResponse, bool, error) {
	if path != CountryMapPath {
		return nil, false, nil
	}
	if myplan.FeedRefusesFormat(query) {
		return nil, true, pagegate.ErrNotAvailable
	}
	query, ok := passed(query)
	if !ok {
		return nil, false, nil
	}
	doors, known := rules.Doors[p.ActiveRole]
	if !known {
		return nil, false, nil
	}
	if !doors.MapFeedOpens || !doors.MapPage {
		return nil, true, pagegate.ErrNotAvailable
	}
	now := c.s.now()
	fy := pyStrip(query, "fy")
	if fy == "" {
		fy = schooldirectory.OperationalFY(now)
	}
	if !periodReadable(query, fy) {
		return nil, false, nil
	}
	v, years, err := c.s.read(ctx, p, doorsFor(p.ActiveRole), fy, query, now)
	if err != nil {
		return nil, true, err
	}
	v.base, v.country = CountryMapPath, true
	districts, subregions, schools, err := mapTotals(ctx, c.s.db)
	if err != nil {
		return nil, true, err
	}
	blocks := mapBlocks(districts, subregions, schools)
	if v.totals().schools > 0 {
		blocks = append(blocks, &screensv1.PageBlock{Kind: &screensv1.PageBlock_Section{Section: "Country portfolio"}},
			stripBlock(v), filtersBlock(v, years))
		if len(v.p.leads) == 0 {
			blocks = append(blocks, &screensv1.PageBlock{Kind: &screensv1.PageBlock_Empty{Empty: emptyMessage}})
		}
		for _, l := range v.p.leads {
			blocks = append(blocks, leadBlock(l))
			for _, o := range l.officers {
				blocks = append(blocks, officerBlocks(o, v.query)...)
			}
		}
	}
	return &screensv1.GetPageResponse{
		Header:  &screensv1.PageHeader{Eyebrow: mapEyebrow, Title: mapTitle, Description: mapDescription},
		Blocks:  blocks,
		WebPath: CountryMapPath,
	}, true, nil
}

// MapCard is the country map card (partials/analytics/regional_performance.html)
// as the feed reads it, for another page that draws it (the IA dashboard's
// Map view).
func MapCard(ctx context.Context, db schooldirectory.Querier) ([]*screensv1.PageBlock, error) {
	districts, subregions, schools, err := mapTotals(ctx, db)
	if err != nil {
		return nil, err
	}
	return mapBlocks(districts, subregions, schools), nil
}
