package adminpanel

import (
	"net/url"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/closedschools"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/tablepager"
)

// AccessMatrixPath is the Page & Feature Access Matrix
// (extended_views.admin_page_access_matrix_view over access_matrix_pages,
// pages/admin/page_access_matrix.html): every routed page by path, a column
// per role, fifty pages and fifty roles a page. Each cell is a grant icon,
// which the feed reads the same whether the role is granted or not.
const AccessMatrixPath = "/admin-panel/page-access-matrix"

const matrixPageSize = 50

func accessMatrix(query url.Values) *screensv1.GetPageResponse {
	m := rules.AccessMatrix
	roles := tablepager.Paginate(len(m.Roles), matrixPageSize, query, "roles_page")
	pages := tablepager.Paginate(len(m.Pages), matrixPageSize, query, "pages_page")
	t := &screensv1.PageTable{Columns: []*screensv1.PageColumn{{Label: "Page / Route Path"}}}
	shown := m.Roles[roles.Start:roles.End]
	for _, r := range shown {
		t.Columns = append(t.Columns, &screensv1.PageColumn{Label: r})
	}
	for _, p := range m.Pages[pages.Start:pages.End] {
		row := &screensv1.PageRow{Cells: []*screensv1.PageCell{{Text: closedschools.Collapse(p[0] + " " + p[1])}}}
		for range shown {
			row.Cells = append(row.Cells, &screensv1.PageCell{Tone: "primary", Badge: true})
		}
		t.Rows = append(t.Rows, row)
	}
	if len(m.Pages) == 0 {
		t.Rows = []*screensv1.PageRow{{Cells: []*screensv1.PageCell{{Text: "No pages or routes registered in matrix."}}}}
	}
	blocks := []*screensv1.PageBlock{{Kind: &screensv1.PageBlock_Table{Table: t}}}
	for _, panel := range []*screensv1.PageBlock{
		tablepager.Panel(len(m.Roles), matrixPageSize, query, "roles_page"),
		tablepager.Panel(len(m.Pages), matrixPageSize, query, "pages_page"),
	} {
		if panel != nil {
			blocks = append(blocks, panel)
		}
	}
	return page(header("Administration", "Page & Feature Access Matrix",
		"Overview of route clearance rules and active dashboards across role groups"), AccessMatrixPath, blocks...)
}
