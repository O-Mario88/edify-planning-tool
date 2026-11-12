package clusterpage

import (
	"context"
	"errors"
	"fmt"
	"net/url"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// Path is the page this package answers.
const Path = "/clusters"

// ErrNotAvailable is the page refused to the reader's role, which the
// existing feed answers as a page that is not there.
var ErrNotAvailable = errors.New("clusterpage: the page is not available to this reader")

// Service builds the Clusters page.
type Service struct {
	db  schooldirectory.Querier
	now func() time.Time
}

// NewService wires the service to the database it reads.
func NewService(db schooldirectory.Querier, now func() time.Time) *Service {
	return &Service{db: db, now: now}
}

// Build answers path for p with the page's query. served is false for a
// path this package does not answer.
func (s *Service) Build(ctx context.Context, p auth.Principal, path string, query url.Values) (*screensv1.GetPageResponse, bool, error) {
	if path != Path {
		return nil, false, nil
	}
	doors, ok := rules.Doors[p.ActiveRole]
	if !ok || !doors.Page {
		return nil, true, ErrNotAvailable
	}
	now := s.now()
	scope, err := schooldirectory.ResolveScope(ctx, s.db, p, now)
	if err != nil {
		return nil, true, err
	}
	owners := []string(nil)
	if !scope.CountryScope && !scope.SummaryOnly {
		if owners, err = ownerIDs(ctx, s.db, scope); err != nil {
			return nil, true, err
		}
	}
	years := schooldirectory.FYOptions(now)
	get := func(key string) string { return strings.TrimSpace(query.Get(key)) }
	f := filterState{
		q: get("q"), fy: get("fy"), quarter: get("quarter"), district: get("district"),
		subCounty: get("sub_county"), staff: get("staff"), ssaStatus: get("ssa_status"),
		risk: get("cluster_risk"), activity: get("activity_status"),
	}
	if !in(years, f.fy) {
		f.fy = schooldirectory.OperationalFY(now)
	}

	clusters, err := s.clusters(ctx, scope, owners, f)
	if err != nil {
		return nil, true, err
	}
	if err := covered(ctx, s.db, clusters); err != nil {
		return nil, true, err
	}
	all, err := cards(ctx, s.db, clusters, f.fy)
	if err != nil {
		return nil, true, err
	}
	listed := keep(all, f)

	districts, subCounties, staff, err := s.options(ctx, scope, owners)
	if err != nil {
		return nil, true, err
	}
	blocks := []*screensv1.PageBlock{
		filters(f, years, districts, subCounties, staff),
		stripBlock(listed),
	}
	number, pages := pageOf(query.Get("page"), len(listed))
	if len(listed) == 0 {
		blocks = append(blocks, empty(doors))
	}
	for _, c := range listed[min((number-1)*pageSize, len(listed)):min(number*pageSize, len(listed))] {
		blocks = append(blocks, &screensv1.PageBlock{Kind: &screensv1.PageBlock_Record{Record: record(c, doors, f.fy)}})
	}
	if pages > 1 {
		blocks = append(blocks, pager(number, pages, len(listed)))
	}
	return &screensv1.GetPageResponse{Header: header(doors), Blocks: blocks, WebPath: Path}, true, nil
}

// keep is get_dashboard_data's filters on the figures: SSA complete or
// incomplete, the risk, and meetings open or held.
func keep(all []card, f filterState) []card {
	out := []card{}
	for _, c := range all {
		switch {
		case f.ssaStatus == "done" && c.plan.WithSSA != c.schools,
			f.ssaStatus == "not_done" && c.plan.WithSSA >= c.schools,
			f.risk != "" && c.risk() != f.risk,
			f.activity == "pending" && c.plan.MeetingsOpen <= 0,
			f.activity == "completed" && c.plan.MeetingsDone <= 0:
			continue
		}
		out = append(out, c)
	}
	return out
}

// base is the page's clusters before its filters: active, not deleted, and
// the reader's (cluster_queryset(scope, direct_only=True)).
func base(b *sqlb, scope schooldirectory.Scope, owners []string) string {
	return "c.deleted_at IS NULL AND c.status = 'active' AND " + b.inScope(scope, owners)
}

// clusters is the filtered list in the model's order (by name).
func (s *Service) clusters(ctx context.Context, scope schooldirectory.Scope, owners []string, f filterState) ([]cluster, error) {
	b := &sqlb{}
	where := base(b, scope, owners)
	if f.q != "" {
		p := b.arg(likeContains(f.q))
		where += fmt.Sprintf(" AND (UPPER(c.name::text) LIKE UPPER(%[1]s) OR UPPER(d.name::text) LIKE UPPER(%[1]s))", p)
	}
	if f.district != "" {
		where += " AND c.district_id = " + b.arg(f.district)
	}
	if f.subCounty != "" {
		where += " AND c.sub_county_id = " + b.arg(f.subCounty)
	}
	if f.staff != "" {
		staff := b.arg(f.staff)
		where += fmt.Sprintf(` AND (c.responsible_staff_id = %[1]s OR c.id IN (
  SELECT s.cluster_id FROM school s WHERE s.deleted_at IS NULL AND s.operational_status = ANY(%[2]s)
    AND s.account_owner_id = %[1]s AND s.cluster_id IS NOT NULL AND s.cluster_id <> ''))`, staff, b.arg(rules.OperatingStatuses))
	}
	out := []cluster{}
	err := each(ctx, s.db, "the clusters", `
SELECT c.id, COALESCE(c.name, ''), d.name, CASE WHEN sc.id IS NULL THEN NULL ELSE COALESCE(sc.name, '') END,
  COALESCE(c.sub_county_name, ''), COALESCE(c.cluster_leader_name, ''), COALESCE(c.cluster_leader_phone, ''),
  COALESCE(c.facilitating_partner_id, '')
FROM cluster c
LEFT JOIN district d ON d.id = c.district_id
LEFT JOIN sub_county sc ON sc.id = c.sub_county_id
WHERE `+where+` ORDER BY c.name`, func(rows pgx.Rows) error {
		var c cluster
		var district *string
		if err := rows.Scan(&c.ID, &c.Name, &district, &c.SubCounty, &c.SubCountyName, &c.LeaderName, &c.LeaderPhone, &c.FacilitatingPartnerID); err != nil {
			return err
		}
		if district != nil {
			c.District = district
		}
		out = append(out, c)
		return nil
	}, b.args...)
	return out, err
}

// options are the District and Sub-county choices of the page's own
// clusters, and every live staff profile, by name.
func (s *Service) options(ctx context.Context, scope schooldirectory.Scope, owners []string) (districts, subCounties, staff []option, err error) {
	read := func(what, sql string, args ...any) ([]option, error) {
		out := []option{}
		err := each(ctx, s.db, what, sql, func(rows pgx.Rows) error {
			var id string
			var name *string
			if err := rows.Scan(&id, &name); err != nil {
				return err
			}
			label := "None"
			if name != nil {
				label = *name
			}
			out = append(out, option{id, label})
			return nil
		}, args...)
		return out, err
	}
	b := &sqlb{}
	where := base(b, scope, owners)
	if districts, err = read("the district options", `
SELECT d.id, d.name FROM district d WHERE d.id IN (SELECT c.district_id FROM cluster c WHERE `+where+`) ORDER BY d.name`, b.args...); err != nil {
		return
	}
	if subCounties, err = read("the sub-county options", `
SELECT sc.id, sc.name FROM sub_county sc WHERE sc.id IN (
  SELECT c.sub_county_id FROM cluster c WHERE c.sub_county_id IS NOT NULL AND `+where+`) ORDER BY sc.name`, b.args...); err != nil {
		return
	}
	staff, err = read("the staff options", `
SELECT sp.id, u.name FROM staff_profile sp LEFT JOIN "user" u ON u.id = sp.user_id
WHERE sp.deleted_at IS NULL ORDER BY u.name`)
	return
}
