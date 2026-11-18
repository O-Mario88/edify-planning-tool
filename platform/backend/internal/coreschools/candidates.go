package coreschools

import (
	"context"
	"fmt"
	"net/url"
	"slices"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/coreoversight"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schoolprofile"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/tablepager"
)

// The Champion Candidate Queue (core_schools_views.champion_candidates_view,
// pages/core_schools/champion_candidates.html): every Core school the
// official rule finds eligible, as far as the reader's portfolio reaches,
// each with its Review drawer.

const (
	CandidatesPath      = "/core-schools/champion-candidates"
	candidatesPageParam = "candidates_page"
	candidatesEmpty     = "No core schools currently match all graduation requirements."
)

// settledStatuses are the stored statuses evaluate_all leaves as they are
// or would write again unchanged: any other eligible profile is moved to
// Potential Champion on the read, so that read is the existing
// application's.
var settledStatuses = []string{"Champion", "Approved Champion", "Potential Champion"}

// candidateSchool is the school behind a candidate.
type candidateSchool struct{ id, name, district string }

// readCandidateSchools is scan's School lookup: each School ID's live
// school, the last read where two share one, with its district.
func (s *Service) readCandidateSchools(ctx context.Context, codes []string) (map[string]candidateSchool, error) {
	rows, err := s.db.Query(ctx, `
SELECT s.school_id, s.id, s.name, COALESCE(d.name, 'Unknown')
FROM school s LEFT JOIN district d ON d.id = s.district_id
WHERE s.deleted_at IS NULL AND s.school_id = ANY($1)`, codes)
	if err != nil {
		return nil, fmt.Errorf("coreschools: reading the candidates' schools: %w", err)
	}
	defer rows.Close()
	out := map[string]candidateSchool{}
	for rows.Next() {
		var code string
		var sc candidateSchool
		if err := rows.Scan(&code, &sc.id, &sc.name, &sc.district); err != nil {
			return nil, fmt.Errorf("coreschools: reading a candidate's school: %w", err)
		}
		out[code] = sc
	}
	return out, rows.Err()
}

// candidates draws the queue for a reader of Core Schools.
func (s *Service) candidates(ctx context.Context, p auth.Principal, query url.Values) (*screensv1.GetPageResponse, error) {
	now := s.now()
	list, err := coreoversight.ChampionCandidates(ctx, s.db, schooldirectory.OperationalFY(now))
	if err != nil {
		return nil, err
	}
	codes := make([]string, len(list))
	for i, c := range list {
		if !slices.Contains(settledStatuses, c.Status) {
			return nil, fmt.Errorf("the candidate %q would be marked Potential Champion: %w", c.Code, errPassOn)
		}
		codes[i] = c.Code
	}
	schools, err := s.readCandidateSchools(ctx, codes)
	if err != nil {
		return nil, err
	}
	scope, err := schooldirectory.ResolveScope(ctx, s.db, p, now)
	if err != nil {
		return nil, err
	}
	// The sweep is the whole estate; the list follows the reader's scope.
	shown := []coreoversight.Candidate{}
	for _, c := range list {
		if scope.CountryScope || slices.Contains(scope.SchoolIDs, schools[c.Code].id) {
			shown = append(shown, c)
		}
	}
	return &screensv1.GetPageResponse{Header: candidatesHeader(),
		Blocks: candidateBlocks(shown, schools, query, schoolprofile.MayOpenSchools(p.ActiveRole)), WebPath: CandidatesPath}, nil
}

// candidatesHeader is the page's header; its link to the Graduated
// Champions sits outside what the feed reads as the header's actions.
func candidatesHeader() *screensv1.PageHeader {
	return &screensv1.PageHeader{Eyebrow: "Schools & Field", Title: "Champion Candidate Queue",
		Description: "Review core schools that have completed their support packages and met the performance " +
			"benchmarks for graduation.",
		Badges: []*screensv1.PageBadge{}, Actions: []*screensv1.PageAction{}}
}

// candidateBlocks is the count, the table (fifty a page) and its pager.
func candidateBlocks(shown []coreoversight.Candidate, schools map[string]candidateSchool, query url.Values, openSchools bool) []*screensv1.PageBlock {
	count := &screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{
		Title: fmt.Sprintf("Candidacy Proposals (%d)", len(shown)), Badges: []*screensv1.PageBadge{}}}}
	t := &screensv1.PageTable{Columns: []*screensv1.PageColumn{{Label: "School ID"}, {Label: "School Name"}, {Label: "District"},
		{Label: "SSA Avg"}, {Label: "Improvement Delta"}, {Label: "Package Completion"}, {Label: "Lowest Score"},
		{Label: "Champion Score"}, {Label: "Review Action", Numeric: true}}}
	if len(shown) == 0 {
		// The template's {% empty %} row, which the feed reads as a row.
		t.Rows = []*screensv1.PageRow{{Cells: []*screensv1.PageCell{{Text: candidatesEmpty}}}}
	}
	page := tablepager.Paginate(len(shown), championsPageSize, query, candidatesPageParam)
	for _, c := range shown[page.Start:page.End] {
		sc := schools[c.Code]
		code, name := c.Code, &screensv1.PageCell{Text: sc.name}
		if code == "" {
			code = "—"
		} else if openSchools {
			name.Href = "/schools/" + c.Code
		}
		delta := pyFloat(c.Delta)
		if c.Delta > 0 {
			delta = "▲ " + delta
		}
		t.Rows = append(t.Rows, &screensv1.PageRow{Cells: []*screensv1.PageCell{
			{Text: code}, name, {Text: sc.district}, {Text: pyFloat(c.LatestAvg)}, {Text: delta},
			{Text: fmt.Sprintf("%d / %d Slots", c.Completed, c.Total), Tone: "primary", Badge: true},
			{Text: pyFloat(c.LowestScore) + " (" + c.LowestIntervention + ")", Tone: "primary", Badge: true},
			{Text: pyFloat(c.Score), Tone: "primary", Badge: true},
			// The Review drawer opens over hx-get; the feed reads the label.
			{Text: "Review"},
		}})
	}
	blocks := []*screensv1.PageBlock{count, {Kind: &screensv1.PageBlock_Table{Table: t}}}
	if pager := tablepager.Panel(len(shown), championsPageSize, query, candidatesPageParam); pager != nil {
		blocks = append(blocks, pager)
	}
	return blocks
}
