package projectcapacity

import (
	"context"
	"errors"
	"fmt"
	"slices"
	"strconv"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
)

const (
	focusClient = "client"
	focusCore   = "core"
)

// EnrolmentChoice is one project a school may be added to. A Block is why
// this person can add no school to it.
type EnrolmentChoice struct {
	Value, Label, Block string
}

// EnrolmentForm is what the Add to Project form offers.
type EnrolmentForm struct {
	Projects     []EnrolmentChoice
	Coordinators []Choice
}

// heldPlaces is a person's allocation on a project.
type heldPlaces struct{ maximum, assigned int }

// enrolmentLabel is the feed's project option: name, code and coordinator.
func enrolmentLabel(name, code, coordinator string) string {
	if code == "" {
		code = "No Code"
	}
	label := name + " (" + code + ")"
	if coordinator != "" {
		label += " · " + coordinator
	}
	return label
}

// capacityBlock is annotate_allocations' capacity_block.
func capacityBlock(projectName string, held *heldPlaces, managed, teamHeld bool) string {
	switch {
	case held != nil && held.maximum-held.assigned <= 0:
		return "You have reached your allocation of " + strconv.Itoa(held.maximum) + " schools for " + projectName +
			". No additional schools can be added unless the Project Coordinator increases your allocation."
	case held == nil && !teamHeld && managed:
		return "You have no school allocation for " + projectName + ". Ask its Project Coordinator to set one."
	}
	return ""
}

// consumingStaffID is capacity.consuming_staff_id: whose places this person's
// addition uses, "" for the roles allocations do not bind.
func consumingStaffID(p auth.Principal) string {
	if slices.Contains(rules.CapacityExemptRoles, p.ActiveRole) {
		return ""
	}
	return p.StaffProfileID
}

// excludedFocus is the school focus that does not admit this type of school.
func excludedFocus(schoolType string) string {
	if schoolType == focusCore {
		return focusClient
	}
	return focusCore
}

type enrolmentProject struct{ id, name, code, coordinator string }

// EnrolmentChoices is projects_open_for_enrolment with annotate_coordinator_names
// and annotate_allocations, and the Project Coordinators the form offers.
func (s *Service) EnrolmentChoices(ctx context.Context, p auth.Principal, schoolPK string) (EnrolmentForm, error) {
	var schoolType string
	var country *string
	err := s.db.QueryRow(ctx, `SELECT COALESCE(sc.school_type, ''), r.country FROM school sc LEFT JOIN region r ON r.id = sc.region_id
 WHERE sc.id = $1`, schoolPK).Scan(&schoolType, &country)
	if err != nil {
		return EnrolmentForm{}, fmt.Errorf("projectcapacity: reading the school: %w", err)
	}
	rows, err := s.db.Query(ctx, `
WITH coordinators AS (
  SELECT sp.id FROM staff_profile sp JOIN "user" u ON u.id = sp.user_id
   WHERE sp.deleted_at IS NULL AND u.roles @> ARRAY[$4]::varchar[])
SELECT pr.id, pr.name, COALESCE(pr.code, ''),
       COALESCE((SELECT u.name FROM staff_profile m LEFT JOIN "user" u ON u.id = m.user_id
                  WHERE m.id = pr.manager_staff_id AND m.deleted_at IS NULL), '')
  FROM project pr
 WHERE pr.deleted_at IS NULL AND pr.status = ANY($1)
   AND NOT EXISTS (SELECT 1 FROM project_school_assignment a WHERE a.project_id = pr.id AND a.school_id = $2)
   AND pr.school_focus IS DISTINCT FROM $3
   AND (pr.manager_staff_id IN (SELECT id FROM coordinators)
        OR EXISTS (SELECT 1 FROM project_staff_assignment sa
                    WHERE sa.project_id = pr.id AND sa.is_active AND sa.staff_id IN (SELECT id FROM coordinators)))
 ORDER BY pr.name`, rules.OpenStatuses, schoolPK, excludedFocus(schoolType), roleProjectCoordinator)
	if err != nil {
		return EnrolmentForm{}, fmt.Errorf("projectcapacity: reading the open projects: %w", err)
	}
	open, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (enrolmentProject, error) {
		var pr enrolmentProject
		err := row.Scan(&pr.id, &pr.name, &pr.code, &pr.coordinator)
		return pr, err
	})
	if err != nil {
		return EnrolmentForm{}, fmt.Errorf("projectcapacity: reading an open project: %w", err)
	}
	kept := make([]enrolmentProject, 0, len(open))
	for _, pr := range open {
		place, err := s.projectCountry(ctx, pr.id)
		if err != nil {
			return EnrolmentForm{}, err
		}
		if country != nil && *country != "" && place != "" && place != *country {
			continue
		}
		kept = append(kept, pr)
	}
	form := EnrolmentForm{Projects: make([]EnrolmentChoice, 0, len(kept))}
	places, err := s.placesFor(ctx, consumingStaffID(p), kept)
	if err != nil {
		return EnrolmentForm{}, err
	}
	for _, pr := range kept {
		form.Projects = append(form.Projects, EnrolmentChoice{
			Value: pr.id,
			Label: enrolmentLabel(pr.name, pr.code, pr.coordinator),
			Block: capacityBlock(pr.name, places.held[pr.id], places.managed[pr.id], places.team[pr.id]),
		})
	}
	form.Coordinators, err = s.projectCoordinators(ctx)
	return form, err
}

// projectPlaces is a person's allocations on these projects.
type projectPlaces struct {
	held          map[string]*heldPlaces
	managed, team map[string]bool
}

func (s *Service) placesFor(ctx context.Context, staffID string, projects []enrolmentProject) (projectPlaces, error) {
	places := projectPlaces{held: map[string]*heldPlaces{}, managed: map[string]bool{}, team: map[string]bool{}}
	if staffID == "" || len(projects) == 0 {
		return places, nil
	}
	ids := make([]string, len(projects))
	for i, pr := range projects {
		ids[i] = pr.id
	}
	rows, err := s.db.Query(ctx, `
SELECT c.project_id, c.staff_id = $2, c.max_schools,
       (SELECT count(*) FROM project_school_assignment a WHERE a.project_id = c.project_id AND a.assigned_staff_id = c.staff_id),
       c.staff_id IN (SELECT supervisee_id FROM staff_supervisor_assignment WHERE supervisor_id = $2)
  FROM project_staff_capacity c WHERE c.project_id = ANY($1)`, ids, staffID)
	if err != nil {
		return places, fmt.Errorf("projectcapacity: reading the allocations: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var projectID string
		var mine, inTeam bool
		var maximum, assigned int
		if err := rows.Scan(&projectID, &mine, &maximum, &assigned, &inTeam); err != nil {
			return places, fmt.Errorf("projectcapacity: reading an allocation: %w", err)
		}
		places.managed[projectID] = true
		if mine {
			places.held[projectID] = &heldPlaces{maximum: maximum, assigned: assigned}
		}
		if inTeam {
			places.team[projectID] = true
		}
	}
	if err := rows.Err(); err != nil {
		return places, fmt.Errorf("projectcapacity: reading the allocations: %w", err)
	}
	return places, nil
}

// projectCoordinators is the form's coordinator list: every live staff record
// holding the Project Coordinator role, by its name or else its id.
func (s *Service) projectCoordinators(ctx context.Context) ([]Choice, error) {
	rows, err := s.db.Query(ctx, `
SELECT sp.id, COALESCE(u.name, sp.id) FROM staff_profile sp JOIN "user" u ON u.id = sp.user_id
 WHERE sp.deleted_at IS NULL AND u.roles @> ARRAY[$1]::varchar[] ORDER BY sp.created_at, sp.id`, roleProjectCoordinator)
	if err != nil {
		return nil, fmt.Errorf("projectcapacity: reading the coordinators: %w", err)
	}
	coordinators, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (Choice, error) {
		var c Choice
		err := row.Scan(&c.Value, &c.Label)
		return c, err
	})
	if err != nil && !errors.Is(err, pgx.ErrNoRows) {
		return nil, fmt.Errorf("projectcapacity: reading a coordinator: %w", err)
	}
	return coordinators, nil
}
