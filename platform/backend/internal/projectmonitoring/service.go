package projectmonitoring

import (
	"context"
	"errors"
	"fmt"
	"net/url"
	"strconv"
	"strings"
	"time"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pagegate"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/planningpage"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schoolplanning"
)

// Path is the page this package answers.
const Path = "/projects/monitoring"

// ErrNotAvailable is the page refused to the reader's role, which the
// existing feed answers as a page that is not there.
var ErrNotAvailable = pagegate.ErrNotAvailable

// Service builds Project Monitoring.
type Service struct {
	db  schooldirectory.Querier
	now func() time.Time
}

// NewService wires the service to the database it reads.
func NewService(db schooldirectory.Querier, now func() time.Time) *Service {
	return &Service{db: db, now: now}
}

// Build answers path for p with the page's query. served is false for a
// path this package does not answer, and for a page holding what this piece
// does not build (see the package comment), which the existing application
// answers instead.
func (s *Service) Build(ctx context.Context, p auth.Principal, path string, query url.Values) (*screensv1.GetPageResponse, bool, error) {
	if path != Path {
		return nil, false, nil
	}
	doors, ok := rules.Doors[p.ActiveRole]
	if !ok || !doors.Page {
		return nil, true, ErrNotAvailable
	}
	page, err := s.build(ctx, p, doors, query)
	if errors.Is(err, errUnread) {
		return nil, false, nil
	}
	if err != nil {
		return nil, true, err
	}
	return page, true, nil
}

// view is what the template is given.
type view struct {
	l          lens
	doors      Doors
	fy, period string
	options    []string
	stage      string
	picks      map[string]string
	selected   string
	projects   []projectRow
	open       *projectRow
	workload   *screensv1.PageBlock
}

func (s *Service) build(ctx context.Context, p auth.Principal, doors Doors, query url.Values) (*screensv1.GetPageResponse, error) {
	now := s.now()
	options := schooldirectory.FYOptions(now)
	operational := schooldirectory.OperationalFY(now)
	v := view{doors: doors, fy: operational, options: options, picks: map[string]string{}}
	// _monitoring_fy: the year asked for, if the selector offers it.
	if asked := strings.TrimSpace(query.Get("fy")); in(options, asked) {
		v.fy = asked
	}
	if stage := strings.TrimSpace(query.Get("stage")); stage != "" {
		for _, f := range rules.StageFilters {
			if f[0] == stage {
				v.stage = stage
			}
		}
	}
	for _, f := range rules.RowFilters {
		if value := strings.TrimSpace(query.Get(f[0])); value != "" {
			v.picks[f[0]] = value
		}
	}
	v.l = lens{
		whole:    in(rules.WholeProjectRoles, p.ActiveRole),
		controls: p.ActiveRole == rules.CoordinatorRole,
		role:     p.ActiveRole,
		staffID:  p.StaffProfileID,
	}
	for _, id := range []string{p.UserID, p.StaffProfileID} {
		if id != "" {
			v.l.mine = append(v.l.mine, id)
		}
	}
	op, _ := strconv.Atoi(operational)
	years, err := schoolplanning.Horizon(ctx, s.db, v.fy, op, options, now)
	if err != nil {
		return nil, err
	}
	v.period = horizonLabel(years)
	if v.workload, err = planningpage.WorkloadLine(ctx, s.db, p, v.fy); err != nil {
		return nil, err
	}
	scope, err := schooldirectory.ResolveScope(ctx, s.db, p, now)
	if err != nil {
		return nil, err
	}
	projects, err := projectsFor(ctx, s.db, v.l, scope)
	if err != nil {
		return nil, err
	}
	ids := make([]string, len(projects))
	for i, pr := range projects {
		ids[i] = pr.ID
	}
	if busy, err := hasWork(ctx, s.db, ids, v.l.staffID); err != nil || busy {
		if err == nil {
			err = errUnread
		}
		return nil, err
	}
	if len(projects) > 0 {
		if v.projects, err = s.projectRows(ctx, v, projects, ids); err != nil {
			return nil, err
		}
	}
	return v.choose(strings.TrimSpace(query.Get("project")))
}

// choose picks the open tab (the project asked for, else the first) and
// refuses what this piece does not draw for it.
func (v view) choose(asked string) (*screensv1.GetPageResponse, error) {
	for i := range v.projects {
		if v.projects[i].p.ID == asked {
			v.open = &v.projects[i]
		}
	}
	if v.open == nil && len(v.projects) > 0 {
		v.open = &v.projects[0]
	}
	if v.open != nil {
		v.selected = v.open.p.ID
		// A measured cohort draws the impact grid; a table past one page
		// draws a pager. Neither is built here yet.
		if v.open.impact.Cohort > 0 || len(v.open.rows) > rules.PageSize {
			return nil, errUnread
		}
	}
	return page(v), nil
}

func (s *Service) projectRows(ctx context.Context, v view, projects []project, ids []string) ([]projectRow, error) {
	l := v.l
	list, err := enrolments(ctx, s.db, l, ids)
	if err != nil {
		return nil, err
	}
	byProject := map[string][]enrolment{}
	schoolIDs, assigners := []string{}, []string{}
	codes := []string{}
	for _, pr := range projects {
		for _, c := range pr.targetList() {
			if c != "" && !in(codes, c) {
				codes = append(codes, c)
			}
		}
	}
	for _, e := range list {
		byProject[e.ProjectID] = append(byProject[e.ProjectID], e)
		if !in(schoolIDs, e.SchoolPK) {
			schoolIDs = append(schoolIDs, e.SchoolPK)
		}
		if e.AssignedBy != "" && !in(assigners, e.AssignedBy) {
			assigners = append(assigners, e.AssignedBy)
		}
		for _, c := range []string{e.Matched, e.SupportArea} {
			if isIntervention(c) && !in(codes, c) {
				codes = append(codes, c)
			}
		}
	}
	readings, err := focusReadings(ctx, s.db, codes, schoolIDs)
	if err != nil {
		return nil, err
	}
	names, err := peopleNames(ctx, s.db, assigners)
	if err != nil {
		return nil, err
	}
	totals, err := enrolledTotals(ctx, s.db, l, ids, schoolIDs)
	if err != nil {
		return nil, err
	}
	readsWhole := l.whole || l.controls
	mayWithdraw := l.controls || in(rules.WithdrawAnySchoolRoles, l.role) || !l.whole
	out := []projectRow{}
	for _, pr := range projects {
		mine := byProject[pr.ID]
		if !readsWhole && len(mine) == 0 {
			continue
		}
		row := projectRow{p: pr, mine: len(mine), schools: len(mine)}
		if n, ok := totals[pr.ID]; ok {
			row.schools = n
		}
		for _, e := range mine {
			r := schoolRowOf(e, pr, names, readings, l)
			if mayWithdraw {
				r.LeaveURL = "/projects/capacity/withdraw?enrolment=" + e.ID
			}
			if l.controls && in(rules.OpenStatuses, pr.Status) {
				r.ScheduleURL = "/planning/schedule-modal?school_id=" + url.QueryEscape(e.SchoolPK) + "&project_id=" + url.QueryEscape(pr.ID)
				r.PartnerURL = "/projects/planning/bulk-partner?assignments=" + url.QueryEscape(e.ID)
			}
			row.everyone = append(row.everyone, r)
			if r.matches(v.stage, v.picks) {
				row.rows = append(row.rows, r)
			}
		}
		cohort := mine
		if readsWhole {
			if cohort, err = allEnrolments(ctx, s.db, pr.ID); err != nil {
				return nil, err
			}
		}
		row.impact = projectImpact(cohort)
		out = append(out, row)
	}
	return out, nil
}

// enrolledTotals is _activity_totals' enrolled_total: each project's current
// enrolments, bounded by the reader's schools unless they read whole.
func enrolledTotals(ctx context.Context, q schooldirectory.Querier, l lens, ids, schoolIDs []string) (map[string]int, error) {
	out := map[string]int{}
	whole := l.whole || l.controls
	if !whole && len(schoolIDs) == 0 {
		return out, nil
	}
	sql := `
SELECT a.project_id, COUNT(a.id) FROM project_school_assignment a INNER JOIN school s ON a.school_id = s.id
WHERE s.deleted_at IS NULL AND s.operational_status = ANY($1) AND a.project_id = ANY($2)`
	args := []any{rules.OperatingStatuses, ids}
	if !whole {
		sql += ` AND a.school_id = ANY($3)`
		args = append(args, schoolIDs)
	}
	rows, err := q.Query(ctx, sql+` GROUP BY a.project_id`, args...)
	if err != nil {
		return nil, fmt.Errorf("projectmonitoring: counting the enrolments: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var id string
		var n int
		if err := rows.Scan(&id, &n); err != nil {
			return nil, fmt.Errorf("projectmonitoring: counting the enrolments: %w", err)
		}
		out[id] = n
	}
	return out, rows.Err()
}

// horizonLabel is fy_policy.horizon_label.
func horizonLabel(years []string) string {
	switch len(years) {
	case 0:
		return ""
	case 1:
		return "FY " + years[0]
	}
	low, high := years[0], years[0]
	for _, y := range years {
		if y < low {
			low = y
		}
		if y > high {
			high = y
		}
	}
	return "FY " + low + "–" + high
}
