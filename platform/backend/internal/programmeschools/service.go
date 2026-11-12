package programmeschools

import (
	"context"
	"fmt"
	"net/url"
	"time"

	"github.com/jackc/pgx/v5"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/closedschools"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pagegate"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schoolprofile"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/visitgate"
)

// Path is the page this package answers.
const Path = "/programme-schools"

// ErrNotAvailable is the page refused to the reader's role, which the
// existing feed answers as a page that is not there.
var ErrNotAvailable = pagegate.ErrNotAvailable

// Service builds the Programme Schools page.
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
	get := func(key string) string { return closedschools.StripSpace(query.Get(key)) }
	operational := schooldirectory.OperationalFY(now)
	v := view{
		doors: doors, query: query, years: schooldirectory.FYOptions(now),
		f: filterState{q: get("q"), schoolType: get("school_type"), district: get("district"), fy: get("fy")},
	}
	if !contains(v.years, v.f.fy) {
		v.f.fy = operational
	}
	if v.districts, err = s.districts(ctx); err != nil {
		return nil, true, err
	}
	args := []any{}
	where := listed(scope, v.f, &args)
	if v.byType, v.total, err = s.counts(ctx, where, args); err != nil {
		return nil, true, err
	}
	if v.total > 0 {
		if v.rows, err = s.rows(ctx, where, args, v.f.fy, operational); err != nil {
			return nil, true, err
		}
	}
	return page(v), true, nil
}

func contains(list []string, value string) bool {
	for _, item := range list {
		if item == value {
			return true
		}
	}
	return false
}

// listed is the page's schools as a WHERE over school s: live, of the three
// programme types, operating, the reader's (scoped_school_queryset), and
// the page's filters. A type that is not one of the three filters nothing.
func listed(scope schooldirectory.Scope, f filterState, args *[]any) string {
	arg := func(v any) string {
		*args = append(*args, v)
		return fmt.Sprintf("$%d", len(*args))
	}
	where := "s.deleted_at IS NULL AND s.school_type = ANY(" + arg(typeValues()) + ") AND s.operational_status = ANY(" + arg(rules.OperatingStatuses) + ")"
	where += " AND " + schooldirectory.AnalyticsReach(scope, args)
	if isProgrammeType(f.schoolType) {
		where += " AND s.school_type = " + arg(f.schoolType)
	}
	if f.district != "" {
		where += " AND s.district_id = " + arg(f.district)
	}
	if f.q != "" {
		like := arg(closedschools.LikeContains(f.q))
		where += fmt.Sprintf(" AND (UPPER(s.name::text) LIKE UPPER(%[1]s) OR UPPER(s.school_id::text) LIKE UPPER(%[1]s))", like)
	}
	return where
}

// counts are the filtered list by type, in the database, and their sum.
func (s *Service) counts(ctx context.Context, where string, args []any) (map[string]int, int, error) {
	rows, err := s.db.Query(ctx, `SELECT s.school_type, COUNT(s.id) FROM school s WHERE `+where+` GROUP BY s.school_type`, args...)
	if err != nil {
		return nil, 0, fmt.Errorf("programmeschools: counting the schools: %w", err)
	}
	defer rows.Close()
	byType, total := map[string]int{}, 0
	for rows.Next() {
		var kind string
		var n int
		if err := rows.Scan(&kind, &n); err != nil {
			return nil, 0, err
		}
		byType[kind] = n
		total += n
	}
	return byType, total, rows.Err()
}

// districts are every district by name, the District filter's choices.
func (s *Service) districts(ctx context.Context) ([]option, error) {
	rows, err := s.db.Query(ctx, `SELECT id, COALESCE(name, '') FROM district ORDER BY name ASC`)
	if err != nil {
		return nil, fmt.Errorf("programmeschools: reading the districts: %w", err)
	}
	return pgx.CollectRows(rows, func(r pgx.CollectableRow) (option, error) {
		var o option
		err := r.Scan(&o.value, &o.label)
		return o, err
	})
}

// rows are the list's schools by name, up to the page's limit, each with its
// owner's name, SSA average, visit entitlement, visit status and training
// coverage for the year.
func (s *Service) rows(ctx context.Context, where string, args []any, fy, operational string) ([]school, error) {
	found, err := s.db.Query(ctx, fmt.Sprintf(`
SELECT s.id, COALESCE(s.school_id, ''), COALESCE(s.name, ''), s.school_type, COALESCE(d.name, ''),
  COALESCE(s.account_owner_id, ''), COALESCE(s.cluster_id, '')
FROM school s LEFT OUTER JOIN district d ON s.district_id = d.id
WHERE %s ORDER BY s.name ASC LIMIT %d`, where, rules.MaxRows), args...)
	if err != nil {
		return nil, fmt.Errorf("programmeschools: reading the schools: %w", err)
	}
	list, err := pgx.CollectRows(found, func(r pgx.CollectableRow) (school, error) {
		var sc school
		err := r.Scan(&sc.ID, &sc.Code, &sc.Name, &sc.Type, &sc.District, &sc.OwnerID, &sc.ClusterID)
		return sc, err
	})
	if err != nil {
		return nil, fmt.Errorf("programmeschools: reading the schools: %w", err)
	}
	ids, refs, ownerIDs := []string{}, []schooldirectory.SchoolRef{}, []string{}
	for _, sc := range list {
		ids = append(ids, sc.ID)
		refs = append(refs, schooldirectory.SchoolRef{ID: sc.ID, SchoolType: sc.Type, ClusterID: sc.ClusterID})
		if sc.OwnerID != "" && !contains(ownerIDs, sc.OwnerID) {
			ownerIDs = append(ownerIDs, sc.OwnerID)
		}
	}
	statuses, err := schooldirectory.VisitStatusesOf(ctx, s.db, ids, fy)
	if err != nil {
		return nil, err
	}
	coverage, err := schooldirectory.CoveragesOf(ctx, s.db, refs, fy)
	if err != nil {
		return nil, err
	}
	averages, err := schooldirectory.LatestSSAAverages(ctx, s.db, ids)
	if err != nil {
		return nil, err
	}
	owners, err := s.ownerNames(ctx, ownerIDs)
	if err != nil {
		return nil, err
	}
	gate := schoolprofile.GateRules()
	for i := range list {
		sc := &list[i]
		sc.TypeLabel = typeLabel(sc.Type)
		sc.Owner = owners[sc.OwnerID]
		if average, ok := averages[sc.ID]; ok {
			sc.SSAAverage = &average
			_, sc.SSATone = schooldirectory.SSABand(average)
		}
		g, err := visitgate.Of(ctx, s.db, gate, visitgate.School{ID: sc.ID, Code: sc.Code, Name: sc.Name, Type: sc.Type}, fy, operational)
		if err != nil {
			return nil, err
		}
		sc.VisitsUsed, sc.VisitsAllowed = entitlement(g, gate)
		status := statuses[sc.ID]
		sc.VisitLabel, sc.VisitTone, sc.NextVisit = status.Label, status.Tone, status.Next
		sc.TrainingLabel, sc.TrainingPlanned = coverage[sc.ID].Label, coverage[sc.ID].Planned
	}
	return list, nil
}

// entitlement is the gate's staff_visits of its staff_cap: the year's one
// staff support visit on the client rule, which all three programme types
// are on; a Core package's staff visits of its cap; nothing counted or
// allowed where no rule applies.
func entitlement(g visitgate.Gate, r visitgate.Rules) (used, allowed int) {
	switch g.Rule {
	case "client":
		return g.StaffVisits, r.StaffVisitCap
	case "core":
		return g.Split.StaffVisits, r.Core.Caps.StaffVisits
	}
	return 0, 0
}

// typeLabel is get_school_type_display for a programme type.
func typeLabel(value string) string {
	for _, t := range rules.SchoolTypes {
		if t[0] == value {
			return t[1]
		}
	}
	return value
}

// ownerNames is programme_schools._owner_names: an owner is filed under a
// staff profile id or a user id, so the live staff profiles are asked first
// and the live users for the ids left.
func (s *Service) ownerNames(ctx context.Context, ids []string) (map[string]string, error) {
	names := map[string]string{}
	if len(ids) == 0 {
		return names, nil
	}
	read := func(what, sql string, args ...any) error {
		rows, err := s.db.Query(ctx, sql, args...)
		if err != nil {
			return fmt.Errorf("programmeschools: reading %s: %w", what, err)
		}
		defer rows.Close()
		for rows.Next() {
			var id, name string
			if err := rows.Scan(&id, &name); err != nil {
				return err
			}
			names[id] = name
		}
		return rows.Err()
	}
	if err := read("the owners", `
SELECT sp.id, COALESCE(u.name, '') FROM staff_profile sp INNER JOIN "user" u ON u.id = sp.user_id
WHERE sp.deleted_at IS NULL AND sp.id = ANY($1)`, ids); err != nil {
		return nil, err
	}
	missing := []string{}
	for _, id := range ids {
		if _, ok := names[id]; !ok {
			missing = append(missing, id)
		}
	}
	if len(missing) > 0 {
		if err := read("the owners' accounts", `SELECT id, COALESCE(name, '') FROM "user" WHERE deleted_at IS NULL AND id = ANY($1)`, missing); err != nil {
			return nil, err
		}
	}
	return names, nil
}
