package coreschools

import (
	"context"
	"fmt"
	"net/url"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schoolprofile"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/tablepager"
)

// The Graduated Champion Schools directory (core_schools_views.
// champions_list_view, pages/core_schools/champions.html): every operating
// champion school by name, with the year its Core service began and its
// latest SSA average.

const (
	ChampionsPath      = "/core-schools/champions"
	championsPageParam = "champions_page"
	championsPageSize  = 50
	championsEmpty     = "No schools have graduated to official Champion status yet."
	championsBadge     = "Graduate Champion"
)

// champion is one champion school's row.
type champion struct {
	code, name, district, region, onboardFY string
	latestAvg                               float64
}

// readChampions is the view's three reads in one: the operating champions
// by name, their Core profile's start year (looked up by School ID, else
// "Unknown") and their latest live SSA record's average (else 0.0).
func (s *Service) readChampions(ctx context.Context) ([]champion, error) {
	rows, err := s.db.Query(ctx, `
SELECT COALESCE(s.school_id, ''), s.name, COALESCE(d.name, 'Unknown'), COALESCE(r.name, 'Unknown'),
  COALESCE(csp.core_start_fy, 'Unknown'), COALESCE(latest.average_score, 0)
FROM school s
LEFT JOIN district d ON d.id = s.district_id
LEFT JOIN region r ON r.id = s.region_id
LEFT JOIN core_school_profile csp ON csp.school_id = s.school_id
LEFT JOIN LATERAL (
  SELECT sr.average_score FROM ssa_record sr
  WHERE sr.school_id = s.id AND sr.deleted_at IS NULL
  ORDER BY sr.date_of_ssa DESC LIMIT 1) latest ON true
WHERE s.deleted_at IS NULL AND s.operational_status IN ('active', 'reopened') AND s.school_type = 'champion'
ORDER BY s.name`)
	if err != nil {
		return nil, fmt.Errorf("coreschools: reading the champions: %w", err)
	}
	defer rows.Close()
	out := []champion{}
	for rows.Next() {
		var c champion
		if err := rows.Scan(&c.code, &c.name, &c.district, &c.region, &c.onboardFY, &c.latestAvg); err != nil {
			return nil, fmt.Errorf("coreschools: reading a champion: %w", err)
		}
		out = append(out, c)
	}
	return out, rows.Err()
}

// champions draws /core-schools/champions for a reader of Core Schools.
func (s *Service) champions(ctx context.Context, p auth.Principal, query url.Values) (*screensv1.GetPageResponse, error) {
	list, err := s.readChampions(ctx)
	if err != nil {
		return nil, err
	}
	header := &screensv1.PageHeader{BackLabel: "Back to Candidates Queue", BackHref: "/core-schools/champion-candidates",
		Title: "Graduated Champion Schools",
		Description: "Directory of schools that completed their core service package and achieved long-term " +
			"independent high-performance ratings.",
		Badges: []*screensv1.PageBadge{}, Actions: []*screensv1.PageAction{}}
	count := &screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{
		Title: fmt.Sprintf("Active Graduated Champions (%d)", len(list)), Badges: []*screensv1.PageBadge{}}}}
	t := &screensv1.PageTable{Columns: []*screensv1.PageColumn{{Label: "School ID"}, {Label: "School Name"}, {Label: "Region"},
		{Label: "District"}, {Label: "Core Start Fiscal Year"}, {Label: "Latest SSA Average"}, {Label: "Independent Status"}}}
	if len(list) == 0 {
		// The template's {% empty %} row, which the feed reads as a row.
		t.Rows = []*screensv1.PageRow{{Cells: []*screensv1.PageCell{{Text: championsEmpty}}}}
	}
	openSchools := schoolprofile.MayOpenSchools(p.ActiveRole)
	page := tablepager.Paginate(len(list), championsPageSize, query, championsPageParam)
	for _, c := range list[page.Start:page.End] {
		code, name := c.code, &screensv1.PageCell{Text: c.name}
		if code == "" {
			code = "—"
		} else if openSchools {
			name.Href = "/schools/" + c.code
		}
		t.Rows = append(t.Rows, &screensv1.PageRow{Cells: []*screensv1.PageCell{
			{Text: code}, name, {Text: c.region}, {Text: c.district}, {Text: c.onboardFY}, {Text: pyFloat(c.latestAvg)},
			{Text: championsBadge, Tone: "primary", Badge: true},
		}})
	}
	blocks := []*screensv1.PageBlock{count, {Kind: &screensv1.PageBlock_Table{Table: t}}}
	if pager := tablepager.Panel(len(list), championsPageSize, query, championsPageParam); pager != nil {
		blocks = append(blocks, pager)
	}
	return &screensv1.GetPageResponse{Header: header, Blocks: blocks, WebPath: ChampionsPath}, nil
}
