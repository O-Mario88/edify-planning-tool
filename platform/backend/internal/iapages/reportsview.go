package iapages

import (
	"context"
	"fmt"
	"net/url"
	"slices"
	"time"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// annexKey is the live evidence annex's download (ia_impact_report_download).
const annexKey = "/ia/impact-report/download"

// reportsView is the dashboard's Impact reports view
// (partials/ia/reports_view.html over dashboard_reports_context) before any
// report is written: the project cohort filter, the register's tiles, the
// latest reports (none yet) and the live evidence annex. It hands on once a
// report is in the reader's reach, where no project is enrolled, and for a
// reader who may not export.
func (s *Service) reportsView(ctx context.Context, p auth.Principal, scope schooldirectory.Scope, query url.Values, now time.Time) ([]*screensv1.PageBlock, bool, error) {
	if scope.SummaryOnly || !slices.Contains(rules.ExportRoles, p.ActiveRole) {
		return nil, false, nil
	}
	args := []any{}
	reach, err := s.reportReach(ctx, p, &args)
	if err != nil {
		return nil, true, err
	}
	var reports int
	if err := s.db.QueryRow(ctx, "SELECT count(*) FROM impact_report r WHERE "+reach, args...).Scan(&reports); err != nil {
		return nil, true, fmt.Errorf("iapages: counting the reports: %w", err)
	}
	if reports > 0 {
		return nil, false, nil
	}
	schools, sargs := activeSchools(scope)
	project := query.Get("project")
	w, err := s.workspace(ctx, scope, schools, sargs, project, now)
	if err != nil {
		return nil, true, err
	}
	if len(w.projects) == 0 {
		return nil, false, nil
	}
	fy := schooldirectory.OperationalFY(now)
	tiles, err := s.reportTiles(ctx, reach, args, fy)
	if err != nil {
		return nil, true, err
	}
	filters := outcomeFilters(fy, nil, w)
	pf := filters[0].GetFilters()
	pf.Filters = pf.Filters[1:]
	pf.Hidden = map[string]string{"view": "reports"}
	links := []*screensv1.PageLink{}
	if p.ActiveRole == roleIA {
		links = append(links, &screensv1.PageLink{Text: "Start report", Href: ReportsPath + "new?project=" + project, Drawer: true})
	}
	links = append(links, &screensv1.PageLink{Text: "Open Impact Reports", Href: ReportsPath})
	latest := &screensv1.PageTable{Columns: columns("Report", "Period", "Version", "Author", "Status", ""),
		EmptyMessage: "No impact reports yet",
		Rows:         []*screensv1.PageRow{{Cells: []*screensv1.PageCell{cell("No impact reports yet Start a report: its evidence is frozen when you submit it for review.")}}}}
	years := &screensv1.DrawerField{Name: "fy", Kind: "select", Value: fy, Options: []*screensv1.DrawerOption{{Value: "", Label: "All recorded enrolments"}}}
	for _, y := range schooldirectory.FYOptions(now) {
		years.Options = append(years.Options, &screensv1.DrawerOption{Value: y, Label: "FY" + y})
	}
	field := func(f *screensv1.DrawerField) *screensv1.PageFormItem {
		return &screensv1.PageFormItem{Kind: &screensv1.PageFormItem_Field{Field: f}}
	}
	annex := &screensv1.PageForm{
		Title: "Live evidence annex (draft)",
		Text: "Today's project cohort evidence for a period — measured and missing evidence, assessment references and mapping versions — " +
			"with who generated it and a hash of its rows. It is not a report: a submitted report freezes its own annex.",
		Items: []*screensv1.PageFormItem{field(years), field(&screensv1.DrawerField{Name: "period_start", Kind: "date"}),
			field(&screensv1.DrawerField{Name: "period_end", Kind: "date"})},
		SubmitLabel: "Download annex (CSV)",
		Key:         annexKey,
	}
	return []*screensv1.PageBlock{
		filters[0],
		{Kind: &screensv1.PageBlock_Strip{Strip: &screensv1.PageStrip{Title: "Impact reports", Metrics: tiles}}},
		panelOf("Latest impact reports", linksItem(links...)),
		tableBlock(latest),
		{Kind: &screensv1.PageBlock_Form{Form: annex}},
	}, true, nil
}
