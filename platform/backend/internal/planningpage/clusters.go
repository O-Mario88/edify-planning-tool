package planningpage

import (
	"context"
	"fmt"

	"github.com/jackc/pgx/v5"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/clusterpage"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// clustersTab is the Clusters tab: the reader's clusters (a supervisor's
// team's too) by name, as the Clusters page's cards, with the tab's own
// filters: not yet scheduled this year, the search and the district.
func (s *Service) clustersTab(ctx context.Context, p auth.Principal, scope schooldirectory.Scope, f filterState) ([]*screensv1.PageBlock, error) {
	supervisor := scope.Role == "Program Lead" || len(scope.SupervisedStaffIDs) > 0
	b := &sqlb{}
	scoped, err := clusterpage.ScopedClusters(ctx, s.db, scope, !supervisor, b.arg)
	if err != nil {
		return nil, err
	}
	where := "c.deleted_at IS NULL AND " + scoped
	if f.readiness == "not_scheduled" {
		where += fmt.Sprintf(` AND c.id NOT IN (SELECT a.cluster_id FROM activity a WHERE a.deleted_at IS NULL AND a.fy = %s
  AND a.activity_type IN ('cluster_meeting', 'cluster_training') AND a.cluster_id IS NOT NULL AND a.status <> 'cancelled')`, b.arg(f.dataFY))
	}
	if f.q != "" {
		where += " AND UPPER(c.name::text) LIKE UPPER(" + b.arg(likeContains(f.q)) + ")"
	}
	if set(f.district) {
		where += " AND c.district_id = " + b.arg(f.district)
	}
	total, err := count(ctx, s.db, "the tab's clusters", "SELECT count(*) FROM cluster c WHERE "+where, b.args...)
	if err != nil {
		return nil, err
	}
	ids := []string{}
	if err := each(ctx, s.db, "the tab's page", fmt.Sprintf("SELECT c.id FROM cluster c WHERE %s ORDER BY c.name LIMIT %d OFFSET %d",
		where, f.perPage, (f.page-1)*f.perPage), func(rows pgx.Rows) error {
		var id string
		if err := rows.Scan(&id); err != nil {
			return err
		}
		ids = append(ids, id)
		return nil
	}, b.args...); err != nil {
		return nil, err
	}
	records, err := clusterpage.PlanningRecords(ctx, s.db, p, scope, ids, f.dataFY)
	if err != nil {
		return nil, err
	}
	pages := (total + f.perPage - 1) / f.perPage
	summary, pageLinks := pager(f, total, pages, "clusters")
	if len(records) == 0 {
		return []*screensv1.PageBlock{emptyMessagePanel("No clusters ready to be scheduled.", summary, pageLinks)}, nil
	}
	out := []*screensv1.PageBlock{}
	for _, r := range records {
		out = append(out, &screensv1.PageBlock{Kind: &screensv1.PageBlock_Record{Record: r}})
	}
	return append(out, &screensv1.PageBlock{Kind: &screensv1.PageBlock_Pager{Pager: &screensv1.PagePager{Summary: summary, Pages: pageLinks}}}), nil
}
