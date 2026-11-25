// Package teamtargets is the Programme Lead's Team Targets
// (apps.targets.team_targets.PLTeamTargetsService, /team-targets and Team
// Oversight's targets lens). It reads; it never writes. A render the
// existing page would write during (risk notices, catch-up plans advanced)
// is handed on.
package teamtargets

import (
	"context"
	"errors"
	"fmt"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// ErrHandOn is a reading Go leaves to the existing application.
var ErrHandOn = errors.New("teamtargets: handed on")

// Member is one supervised person (a User with their staff record).
type Member struct {
	UserID, StaffID, Name, Title string
}

// supervisedUsers is supervised_users: a Regional Programme Lead's active
// CCEOs in reach, every active CCEO for the Country Director and Admin, and
// a Programme Lead's active supervisees (never themself), by name. A Lead
// working in an acting seat reads the seat's team, which Go does not yet:
// handed on.
func supervisedUsers(ctx context.Context, db schooldirectory.Querier, p auth.Principal, scope schooldirectory.Scope) ([]Member, error) {
	const cols = `SELECT u.id, COALESCE(sp.id, ''), COALESCE(u.name, ''), COALESCE(sp.title, '') FROM "user" u
		LEFT JOIN staff_profile sp ON sp.user_id = u.id AND sp.deleted_at IS NULL`
	switch p.ActiveRole {
	case "RegionalProgramLead":
		if len(scope.RegionIDs) == 0 {
			return []Member{}, nil
		}
		return readMembers(ctx, db, cols+` WHERE u.status = 'active' AND u.deleted_at IS NULL AND 'CCEO' = ANY(u.roles)
			AND (sp.id IN (SELECT a.staff_id FROM staff_school_assignment a JOIN school s ON s.id = a.school_id
			      WHERE s.deleted_at IS NULL AND s.operational_status = ANY($2) AND s.region_id = ANY($1))
			  OR sp.country IN (SELECT DISTINCT country FROM region WHERE id = ANY($1) AND country IS NOT NULL AND country <> ''))
			ORDER BY u.name, u.id`, scope.RegionIDs, operating)
	case "CountryDirector", "Admin":
		return readMembers(ctx, db, cols+` WHERE u.status = 'active' AND u.deleted_at IS NULL AND 'CCEO' = ANY(u.roles)
			ORDER BY u.name, u.id`)
	}
	if p.StaffProfileID == "" {
		return []Member{}, nil
	}
	if p.Acting != nil || p.InActingAppointment {
		return nil, ErrHandOn
	}
	return readMembers(ctx, db, cols+` WHERE u.status = 'active' AND u.deleted_at IS NULL AND sp.id IN (
		SELECT supervisee_id FROM staff_supervisor_assignment WHERE supervisor_id = $1 AND supervisee_id <> $1)
		ORDER BY u.name, u.id`, p.StaffProfileID)
}

// operating are lifecycle_models.OPERATING_STATUSES.
var operating = []string{"active", "reopened"}

func readMembers(ctx context.Context, db schooldirectory.Querier, sql string, args ...any) ([]Member, error) {
	rows, err := db.Query(ctx, sql, args...)
	if err != nil {
		return nil, fmt.Errorf("teamtargets: the team: %w", err)
	}
	defer rows.Close()
	out := []Member{}
	for rows.Next() {
		var m Member
		if err := rows.Scan(&m.UserID, &m.StaffID, &m.Name, &m.Title); err != nil {
			return nil, err
		}
		out = append(out, m)
	}
	return out, rows.Err()
}
