package projectmonitoring

import (
	"context"
	"errors"
	"fmt"
	"strings"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

const noCoordinator = "Not assigned"

// ErrWorkNotBuilt is a school whose project has work, allocations or partner
// hand-overs. The page's own work lines are not built in Go yet, so the form
// says it is unavailable rather than showing a school as untouched.
var ErrWorkNotBuilt = errors.New("projectmonitoring: this project's work is not drawn in Go yet")

// SchoolForm is the row's View drawer (monitoring_school_drawer.html) for a
// school with nothing planned yet.
type SchoolForm struct {
	School, Subtitle, Status, AddedBy, Coordinator string
	AddedFor, Impact                               string
	Focus                                          []string
	Controls                                       bool
}

// focusLine is one Focus SSA line of the drawer.
func focusLine(f focus) string {
	line := f.Label + ": –"
	if f.Baseline != nil {
		line = f.Label + ": " + floatStr(*f.Baseline)
	}
	if f.Latest == nil {
		return line + " · no confirmed follow-up yet"
	}
	line += " → " + floatStr(*f.Latest)
	if change := f.change(); change != nil {
		sign := ""
		if *change > 0 {
			sign = "+"
		}
		line += " (" + sign + floatStr(*change) + ")"
	}
	return line
}

func schoolFormOf(r schoolRow, projectName, coordinator string, controls bool) SchoolForm {
	subtitle := projectName + " · " + r.e.SchoolCode
	if r.e.District != "" {
		subtitle += " · " + r.e.District
	}
	form := SchoolForm{
		School:      r.e.SchoolName,
		Subtitle:    subtitle,
		Status:      rules.RowStatusLabels["awaiting_coordinator"],
		AddedBy:     r.AddedBy + " · " + dayLabel(r.e.enrolledOn()),
		Coordinator: coordinator,
		Impact:      r.ImpactLabel,
		Controls:    controls,
	}
	parts := []string{}
	for _, part := range []string{r.Purpose, r.Intervention} {
		if part != "" {
			parts = append(parts, part)
		}
	}
	if len(parts) > 0 {
		form.AddedFor = "Added for " + strings.Join(parts, " · ") + "."
	}
	for _, f := range r.Focus {
		form.Focus = append(form.Focus, focusLine(f))
	}
	return form
}

// SchoolDrawer is monitoring.find_school_row through the page's own lens: nil
// when this reader's page would not show the school.
func (s *Service) SchoolDrawer(ctx context.Context, p auth.Principal, enrolmentID string) (*SchoolForm, error) {
	var projectID string
	err := s.db.QueryRow(ctx, `SELECT project_id FROM project_school_assignment WHERE id = $1`, enrolmentID).Scan(&projectID)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, nil
	}
	if err != nil {
		return nil, fmt.Errorf("projectmonitoring: reading the enrolment: %w", err)
	}
	now := s.now()
	scope, err := schooldirectory.ResolveScope(ctx, s.db, p, now)
	if err != nil {
		return nil, err
	}
	l := lensFor(p)
	readable, err := projectsFor(ctx, s.db, l, scope)
	if err != nil {
		return nil, err
	}
	var chosen []project
	for _, pr := range readable {
		if pr.ID == projectID {
			chosen = []project{pr}
		}
	}
	if len(chosen) == 0 {
		return nil, nil
	}
	busy, err := hasWork(ctx, s.db, []string{projectID}, l.staffID)
	if err != nil {
		return nil, err
	}
	if busy {
		return nil, ErrWorkNotBuilt
	}
	rows, err := s.projectRows(ctx, view{l: l, fy: schooldirectory.OperationalFY(now), picks: map[string]string{}}, chosen, []string{projectID})
	if err != nil {
		return nil, err
	}
	for _, row := range rows {
		for _, school := range row.everyone {
			if school.e.ID != enrolmentID {
				continue
			}
			coordinator, err := s.coordinatorName(ctx, projectID)
			if err != nil {
				return nil, err
			}
			form := schoolFormOf(school, row.p.Name, coordinator, l.controls)
			return &form, nil
		}
	}
	return nil, nil
}

// coordinatorName is _coordinator_names for one project.
func (s *Service) coordinatorName(ctx context.Context, projectID string) (string, error) {
	var name *string
	err := s.db.QueryRow(ctx, `
SELECT u.name FROM project pr JOIN staff_profile sp ON sp.id = pr.manager_staff_id AND sp.deleted_at IS NULL
  LEFT JOIN "user" u ON u.id = sp.user_id
 WHERE pr.id = $1`, projectID).Scan(&name)
	if errors.Is(err, pgx.ErrNoRows) {
		return noCoordinator, nil
	}
	if err != nil {
		return "", fmt.Errorf("projectmonitoring: reading the coordinator: %w", err)
	}
	if name == nil {
		return "", nil
	}
	return *name, nil
}
