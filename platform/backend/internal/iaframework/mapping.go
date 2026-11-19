package iaframework

import (
	"context"
	"net/url"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/closedschools"
)

// MappingPath is the read-only Measurement Rules register
// (ssa_mapping_views.ssa_mapping_page, pages/hr/ssa_mapping.html): the
// rules_register rows for the ssa_mapping readers who do not work the
// rules on the framework (a framework reader is redirected there, which Go
// hands on), fifty a page, each with its History drawer.
const MappingPath = "/priorities/ssa-mapping"

const mappingPageParam = "rules_page"

func (s *Service) mappingPage(ctx context.Context, query url.Values) (*screensv1.GetPageResponse, bool, error) {
	rows, _, err := s.ruleRows(ctx)
	if err != nil {
		return nil, true, err
	}
	if len(rows) == 0 {
		// The register's empty state is the components/empty_state.html
		// card, which no register Go builds draws yet.
		return nil, false, nil
	}
	header := &screensv1.PageHeader{Eyebrow: "Measurement framework", Title: "Measurement Rules",
		Description: "Which SSA domain each school-facing, cluster or training activity is meant to move, and how that is judged. " +
			"Impact Assessment writes each rule and a second reviewer publishes it; only a published rule measures anything."}
	table := &screensv1.PageTable{}
	for _, c := range []string{"Programme", "Activity", "SSA domain", "Follow-up window", "Meaningful change", "Status", ""} {
		table.Columns = append(table.Columns, &screensv1.PageColumn{Label: c})
	}
	number, pages := closedschools.PageOf(query.Get(mappingPageParam), len(rows), rules.PageSize)
	for _, r := range rows[(number-1)*rules.PageSize : min(number*rules.PageSize, len(rows))] {
		table.Rows = append(table.Rows, &screensv1.PageRow{Cells: []*screensv1.PageCell{
			cell(r.programme), cell(r.name), cell(r.intervention), cell(r.window), cell(r.threshold), cell(r.state),
			actions([2]string{"History", MappingPath + "/" + r.itemID + "/history"}),
		}})
	}
	blocks := []*screensv1.PageBlock{panel("Measurement rules"), {Kind: &screensv1.PageBlock_Table{Table: table}}}
	if pages > 1 {
		blocks = append(blocks, closedschools.PagerPanel(mappingPageParam, number, pages, len(rows), rules.PageSize, query, nil))
	}
	return &screensv1.GetPageResponse{Header: header, Blocks: blocks, WebPath: MappingPath}, true, nil
}
