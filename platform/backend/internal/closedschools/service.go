package closedschools

import (
	"context"
	"fmt"
	"net/url"
	"strconv"
	"time"

	"github.com/jackc/pgx/v5"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pagegate"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// Path is the page this package answers.
const Path = "/schools/closed"

// ErrNotAvailable is the page refused to the reader's role, which the
// existing feed answers as a page that is not there.
var ErrNotAvailable = pagegate.ErrNotAvailable

// Service builds the Closed Schools page.
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
	if !scope.CountryScope && !scope.RegionScope && !scope.SummaryOnly {
		if owners, err = bothIDSpaces(ctx, s.db, append([]string{p.UserID, p.StaffProfileID}, scope.SupervisedStaffIDs...)); err != nil {
			return nil, true, err
		}
	}
	v := view{doors: doors, summaryOnly: scope.SummaryOnly, q: strip(query.Get("q")), query: query}
	if v.figures, err = s.figures(ctx, scope, owners, v.q); err != nil {
		return nil, true, err
	}
	if !v.summaryOnly {
		if v.rows, err = s.rows(ctx, scope, owners, v.q); err != nil {
			return nil, true, err
		}
	}
	if doors.Impact {
		fy, _ := strconv.Atoi(schooldirectory.OperationalFY(now))
		if v.impact, err = s.impact(ctx, scope, fy); err != nil {
			return nil, true, err
		}
	}
	return page(v), true, nil
}

// bothIDSpaces is oversight_service._both_id_spaces: the ids given, the
// users of the live staff profiles among them, and the live staff profiles
// of the users among them. A closure's owner is filed under either.
func bothIDSpaces(ctx context.Context, q schooldirectory.Querier, given []string) ([]string, error) {
	ids := []string{}
	add := func(id string) {
		if id != "" && !in(ids, id) {
			ids = append(ids, id)
		}
	}
	for _, id := range given {
		add(id)
	}
	if len(ids) == 0 {
		return nil, nil
	}
	rows, err := q.Query(ctx, `
SELECT id, COALESCE(user_id, '') FROM staff_profile
WHERE deleted_at IS NULL AND (id = ANY($1) OR user_id = ANY($1))`, ids)
	if err != nil {
		return nil, fmt.Errorf("closedschools: reading the owner ids: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var profileID, userID string
		if err := rows.Scan(&profileID, &userID); err != nil {
			return nil, err
		}
		add(profileID)
		add(userID)
	}
	return ids, rows.Err()
}

// likeContains is Django's icontains pattern: the value escaped and wrapped.
func likeContains(value string) string {
	out := []rune{'%'}
	for _, r := range value {
		if r == '\\' || r == '%' || r == '_' {
			out = append(out, '\\')
		}
		out = append(out, r)
	}
	return string(append(out, '%'))
}

// inReach is the schools the reader's analytics reach
// (scoped_school_queryset), as a condition on a closure's school_id.
func inReach(scope schooldirectory.Scope, args *[]any) string {
	return "c.school_id IN (SELECT s.id FROM school s WHERE " + schooldirectory.AnalyticsReach(scope, args) + ")"
}

// archive is the view's closures as a WHERE over school_closure c and its
// school sch: still closed, the reader's (_closed_archive_scope: the schools
// their analytics reach and, for an officer or a lead, any closure recorded
// against them or their officers as the school's owner), and the search on
// the school's name.
func archive(scope schooldirectory.Scope, owners []string, q string, args *[]any) string {
	arg := func(v any) string {
		*args = append(*args, v)
		return fmt.Sprintf("$%d", len(*args))
	}
	mine := inReach(scope, args)
	if len(owners) > 0 {
		mine = "(" + mine + " OR c.owner_at_closure = ANY(" + arg(owners) + "))"
	}
	where := mine + " AND c.reopened_at IS NULL"
	if q != "" {
		where += " AND UPPER(sch.name::text) LIKE UPPER(" + arg(likeContains(q)) + ")"
	}
	return where
}

// figures are the page's three: the matching closures and the learners they
// removed, and the reader's schools still operating.
func (s *Service) figures(ctx context.Context, scope schooldirectory.Scope, owners []string, q string) (figures, error) {
	var f figures
	args := []any{}
	where := archive(scope, owners, q, &args)
	if err := s.db.QueryRow(ctx, `
SELECT COUNT(c.id), COALESCE(SUM(c.enrollment_at_closure), 0)
FROM school_closure c INNER JOIN school sch ON c.school_id = sch.id
WHERE `+where, args...).Scan(&f.Closed, &f.EnrollmentRemoved); err != nil {
		return f, fmt.Errorf("closedschools: counting the closures: %w", err)
	}
	args = []any{}
	reach := schooldirectory.AnalyticsReach(scope, &args)
	args = append(args, rules.OperatingStatuses)
	if err := s.db.QueryRow(ctx, fmt.Sprintf(`
SELECT COUNT(*) FROM school s WHERE %s AND s.operational_status = ANY($%d)`, reach, len(args)), args...).Scan(&f.Active); err != nil {
		return f, fmt.Errorf("closedschools: counting the active schools: %w", err)
	}
	return f, nil
}

// rows are the archive's closures, the latest effective date first, up to
// the page's cap.
func (s *Service) rows(ctx context.Context, scope schooldirectory.Scope, owners []string, q string) ([]closure, error) {
	args := []any{}
	where := archive(scope, owners, q, &args)
	rows, err := s.db.Query(ctx, fmt.Sprintf(`
SELECT sch.id, sch.school_id, sch.name, COALESCE(d.name, ''), c.owner_name_at_closure, c.effective_date,
  c.closure_type, c.reason_category, c.reason, c.enrollment_at_closure
FROM school_closure c INNER JOIN school sch ON c.school_id = sch.id
LEFT OUTER JOIN district d ON sch.district_id = d.id
WHERE %s ORDER BY c.effective_date DESC LIMIT %d`, where, rules.MaxRows), args...)
	if err != nil {
		return nil, fmt.Errorf("closedschools: reading the closures: %w", err)
	}
	return pgx.CollectRows(rows, func(r pgx.CollectableRow) (closure, error) {
		var c closure
		err := r.Scan(&c.SchoolID, &c.SchoolCode, &c.SchoolName, &c.District, &c.Owner, &c.Effective,
			&c.Type, &c.ReasonCategory, &c.Reason, &c.Enrollment)
		return c, err
	})
}

// impact is closure_analytics.country_summary over the operational year:
// the closures of the schools the reader's analytics reach that took effect
// in it and have not been reopened.
func (s *Service) impact(ctx context.Context, scope schooldirectory.Scope, fy int) (*impact, error) {
	i := &impact{FY: fyLabel(fy)}
	args := []any{}
	where := inReach(scope, &args)
	args = append(args, time.Date(fy-1, time.October, 1, 0, 0, 0, 0, time.UTC), time.Date(fy, time.October, 1, 0, 0, 0, 0, time.UTC))
	err := s.db.QueryRow(ctx, fmt.Sprintf(`
SELECT COUNT(c.id), COALESCE(SUM(c.activities_cancelled), 0), COALESCE(SUM(c.budget_released), 0)::text,
  COALESCE(SUM(c.partner_assignments_withdrawn), 0), COUNT(DISTINCT sch.district_id)
FROM school_closure c INNER JOIN school sch ON c.school_id = sch.id
WHERE %s AND c.effective_date >= $%d::date AND c.effective_date < $%d::date AND c.reopened_at IS NULL`,
		where, len(args)-1, len(args)), args...).Scan(&i.Schools, &i.Activities, &i.Budget, &i.Partners, &i.Districts)
	if err != nil {
		return nil, fmt.Errorf("closedschools: reading the closure impact: %w", err)
	}
	return i, nil
}
