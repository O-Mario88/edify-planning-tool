package projectcapacity

import (
	"context"
	"fmt"
	"net/url"
	"slices"
	"sort"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/closedschools"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/myplan"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pagegate"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// Path is the page.
const Path = "/projects/capacity"

const roleProjectCoordinator = "ProjectCoordinator"

// Service answers the page from the existing database.
type Service struct {
	db  schooldirectory.Querier
	now func() time.Time
	// saves is Add to Project's save (enrol.go), set only when Go makes it.
	saves *enrolSaver
}

// NewService is the page over db.
func NewService(db schooldirectory.Querier, now func() time.Time) *Service {
	return &Service{db: db, now: now}
}

// project is one live project the reader directs.
type project struct{ ID, Name, Code, Status string }

// allocation is one staff member's allocation on the open project, with
// their year beside it (capacity.attach_visit_load).
type allocation struct {
	ID, StaffID, StaffName string
	Maximum, Assigned      int
	Planned, Ceiling       int
}

// Build answers /projects/capacity; every other path is not this page's.
func (s *Service) Build(ctx context.Context, p auth.Principal, path string, query url.Values) (*screensv1.GetPageResponse, bool, error) {
	if path != Path {
		return nil, false, nil
	}
	role, ok := rules.Roles[p.ActiveRole]
	if !ok || !role.Page {
		return nil, true, pagegate.ErrNotAvailable
	}
	now := s.now()
	scope, err := schooldirectory.ResolveScope(ctx, s.db, p, now)
	if err != nil {
		return nil, true, fmt.Errorf("projectcapacity: resolving the reader's scope: %w", err)
	}
	projects, err := s.directed(ctx, p, scope)
	if err != nil {
		return nil, true, err
	}
	selected := closedschools.StripSpace(query.Get("project"))
	if !slices.ContainsFunc(projects, func(pr project) bool { return pr.ID == selected }) {
		selected = ""
		if len(projects) > 0 {
			selected = projects[0].ID
		}
	}
	fy := schooldirectory.OperationalFY(now)
	var allocations []allocation
	if selected != "" {
		if allocations, err = s.allocations(ctx, selected, fy); err != nil {
			return nil, true, err
		}
	}
	return page(role, projects, selected, allocations, fy, query), true, nil
}

// directed is _directed_projects: the live projects in scoped_projects that
// projects_directed_by lets the reader change, by name. Admin and Impact
// Assessment direct every project they read; a Project Coordinator, the
// ones they run (scoped_projects again).
func (s *Service) directed(ctx context.Context, p auth.Principal, scope schooldirectory.Scope) ([]project, error) {
	clause, extra, reads := readableClause(p, scope, 2)
	if !reads {
		return nil, nil
	}
	args := append([]any{rules.LiveStatuses}, extra...)
	where := "p.deleted_at IS NULL AND p.status = ANY($1)" + clause
	rows, err := s.db.Query(ctx, `SELECT p.id, p.name, COALESCE(p.code, ''), p.status FROM project p WHERE `+where+` ORDER BY p.name`, args...)
	if err != nil {
		return nil, fmt.Errorf("projectcapacity: reading the projects: %w", err)
	}
	out, err := pgx.CollectRows(rows, func(r pgx.CollectableRow) (project, error) {
		var pr project
		err := r.Scan(&pr.ID, &pr.Name, &pr.Code, &pr.Status)
		return pr, err
	})
	if err != nil {
		return nil, fmt.Errorf("projectcapacity: reading the projects: %w", err)
	}
	return out, nil
}

// readableClause is scoped_projects for the roles that direct projects, as a
// condition on project p with its arguments numbered from next. Reads is
// false for a reader who directs nothing.
func readableClause(p auth.Principal, scope schooldirectory.Scope, next int) (string, []any, bool) {
	switch {
	case scope.CountryScope:
		if scope.Country == "" {
			return "", nil, true
		}
		// A country role reads the projects reaching its country by an
		// enrolled school or the person running them, and the unplaced.
		return fmt.Sprintf(` AND (EXISTS (SELECT 1 FROM project_school_assignment a JOIN school sc ON sc.id = a.school_id
    JOIN region r ON r.id = sc.region_id WHERE a.project_id = p.id AND r.country = $%[1]d)
  OR p.manager_staff_id IN (SELECT id FROM staff_profile WHERE country = $%[1]d AND deleted_at IS NULL)
  OR (NOT EXISTS (SELECT 1 FROM project_school_assignment a WHERE a.project_id = p.id)
      AND (p.manager_staff_id IS NULL OR p.manager_staff_id = '')))`, next), []any{scope.Country}, true
	case p.ActiveRole == roleProjectCoordinator:
		if scope.StaffID == "" {
			return "", nil, false
		}
		return fmt.Sprintf(` AND (p.manager_staff_id = $%[1]d OR EXISTS (
  SELECT 1 FROM project_staff_assignment sa WHERE sa.project_id = p.id AND sa.staff_id = $%[1]d AND sa.is_active))`, next),
			[]any{scope.StaffID}, true
	}
	// The page's other readers direct nothing (projects_directed_by).
	return "", nil, false
}

// allocations is allocations_by_project for one project, by name
// (case-folded), each with the schools its staff member holds on the
// project and their counted visits in fy against their role's ceiling.
func (s *Service) allocations(ctx context.Context, projectID, fy string) ([]allocation, error) {
	rows, err := s.db.Query(ctx, `
SELECT c.id, c.staff_id, u.name, c.max_schools,
  (SELECT count(*) FROM project_school_assignment a WHERE a.project_id = c.project_id AND a.assigned_staff_id = c.staff_id),
  sp.user_id, u.roles, COALESCE(u.active_role, '')
FROM project_staff_capacity c JOIN staff_profile sp ON sp.id = c.staff_id JOIN "user" u ON u.id = sp.user_id
WHERE c.project_id = $1`, projectID)
	if err != nil {
		return nil, fmt.Errorf("projectcapacity: reading the allocations: %w", err)
	}
	people := map[string][]string{}
	out, err := pgx.CollectRows(rows, func(r pgx.CollectableRow) (allocation, error) {
		var a allocation
		var userID string
		var roles []string
		var active string
		if err := r.Scan(&a.ID, &a.StaffID, &a.StaffName, &a.Maximum, &a.Assigned, &userID, &roles, &active); err != nil {
			return a, err
		}
		people[a.StaffID] = []string{a.StaffID, userID}
		a.Ceiling = myplan.VisitTarget(roles, active)
		return a, nil
	})
	if err != nil {
		return nil, fmt.Errorf("projectcapacity: reading the allocations: %w", err)
	}
	tallies, err := myplan.VisitTallies(ctx, s.db, people, fy)
	if err != nil {
		return nil, err
	}
	for i := range out {
		out[i].Planned = tallies[out[i].StaffID]
	}
	sort.SliceStable(out, func(i, j int) bool { return strings.ToLower(out[i].StaffName) < strings.ToLower(out[j].StaffName) })
	return out, nil
}
