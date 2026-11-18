package schoolprofile

import (
	"context"
	"fmt"
	"net/url"
	"strings"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pagegate"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/tablepager"
)

// The Districts directory (extended_views.districts_list_view,
// pages/districts/index.html): every district by name, its region, its
// schools and their mean SSA this operational year, each opening its
// profile, fifty a page.

const (
	districtsPath      = "/districts"
	districtsPageParam = "districts_page"
)

// directoryDistrict is one district's row.
type directoryDistrict struct {
	id, name, region string
	schools          int
	avgSSA           *float64
}

// likeContains is Django's icontains argument: the text with its LIKE
// wildcards escaped, inside wildcards.
func likeContains(text string) string {
	escaped := strings.NewReplacer(`\`, `\\`, `%`, `\%`, `_`, `\_`).Replace(text)
	return "%" + escaped + "%"
}

// readDirectory is the view's one query: every district with its live
// schools and the mean SSA of their live records in the year.
func (s *Service) readDirectory(ctx context.Context, fy, search string) ([]directoryDistrict, error) {
	args := []any{fy}
	where := ""
	if search != "" {
		args = append(args, likeContains(search))
		where = "WHERE UPPER(d.name::text) LIKE UPPER($2)"
	}
	rows, err := s.db.Query(ctx, `
SELECT d.id, d.name, COALESCE(r.name, '—'),
  count(DISTINCT sc.id) FILTER (WHERE sc.deleted_at IS NULL),
  avg(sr.average_score) FILTER (WHERE sr.fy = $1 AND sr.deleted_at IS NULL AND sc.deleted_at IS NULL)
FROM district d
LEFT JOIN region r ON r.id = d.region_id
LEFT JOIN school sc ON sc.district_id = d.id
LEFT JOIN ssa_record sr ON sr.school_id = sc.id
`+where+`
GROUP BY d.id, d.name, r.name
ORDER BY d.name`, args...)
	if err != nil {
		return nil, fmt.Errorf("schoolprofile: reading the districts: %w", err)
	}
	defer rows.Close()
	out := []directoryDistrict{}
	for rows.Next() {
		var d directoryDistrict
		var avg *float64
		if err := rows.Scan(&d.id, &d.name, &d.region, &d.schools, &avg); err != nil {
			return nil, fmt.Errorf("schoolprofile: reading a district: %w", err)
		}
		// round(avg, 2) if avg else None: a mean of nought shows as none.
		if avg != nil && *avg != 0 {
			rounded := pyRound(*avg, 2)
			d.avgSSA = &rounded
		}
		out = append(out, d)
	}
	return out, rows.Err()
}

// directory draws /districts for a reader who may open a district.
func (sp *ScopePages) directory(ctx context.Context, p auth.Principal, query url.Values) (*screensv1.GetPageResponse, bool, error) {
	d := rules.Doors[p.ActiveRole]
	if !d.OpenDistrict {
		return nil, true, pagegate.ErrNotAvailable
	}
	fy := schooldirectory.OperationalFY(sp.s.now())
	districts, err := sp.s.readDirectory(ctx, fy, strings.TrimSpace(query.Get("q")))
	if err != nil {
		return nil, true, err
	}
	header := &screensv1.PageHeader{Eyebrow: "Schools & Field", Title: "Districts", Description: "Edify Operations · Districts",
		Badges: []*screensv1.PageBadge{}, Actions: []*screensv1.PageAction{}}
	// The widest profile, offered to the roles that read the whole country.
	if d.CountryProfile {
		header.Actions = append(header.Actions, &screensv1.PageAction{Key: "country_profile", Label: "Country Profile",
			Enabled: true, Href: countryProfilePath})
	}
	return &screensv1.GetPageResponse{Header: header, Blocks: directoryBlocks(districts, query), WebPath: districtsPath}, true, nil
}

// directoryBlocks is the districts' table and its pager, or the empty card.
func directoryBlocks(districts []directoryDistrict, query url.Values) []*screensv1.PageBlock {
	if len(districts) == 0 {
		return []*screensv1.PageBlock{{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{Badges: []*screensv1.PageBadge{},
			Items: []*screensv1.PagePanelItem{{Kind: &screensv1.PagePanelItem_Text{Text: "No districts found"}}}}}}}
	}
	t := &screensv1.PageTable{Columns: []*screensv1.PageColumn{{Label: "District"}, {Label: "Region"}, {Label: "Schools"},
		{Label: "Avg SSA"}, {Label: ""}}}
	page := tablepager.Paginate(len(districts), tablePageSize, query, districtsPageParam)
	for _, row := range districts[page.Start:page.End] {
		ssa := "—"
		if row.avgSSA != nil {
			ssa = pyFloat(*row.avgSSA) + "/10"
		}
		t.Rows = append(t.Rows, &screensv1.PageRow{Cells: []*screensv1.PageCell{
			{Text: row.name}, {Text: row.region}, {Text: itoa(row.schools)}, {Text: ssa},
			{Text: "View →", Href: districtPrefix + row.id},
		}})
	}
	blocks := []*screensv1.PageBlock{{Kind: &screensv1.PageBlock_Table{Table: t}}}
	if pager := tablepager.Panel(len(districts), tablePageSize, query, districtsPageParam); pager != nil {
		blocks = append(blocks, pager)
	}
	return blocks
}
