package activities

import (
	"context"
	"errors"
	"fmt"
	"time"

	"github.com/jackc/pgx/v5"
)

// The stamps the audit pipeline adds to an actor's row
// (apps.audit.services.log).
//
// _acting_for: an actor covering a colleague on leave right now carries who
// they cover. audit_stamp_for: an actor working in an acting appointment
// carries the appointment; Go hands such a save on (Service.Schedule), as
// every Go module does for a person working in another's seat, so no Go
// save writes that stamp yet.

// coverageStamp is _read_acting_for(actor): nil, or the cover the actor
// holds now.
func coverageStamp(ctx context.Context, q Querier, actorUserID string, now time.Time) (map[string]any, error) {
	var staffID, userID, name, leaveID *string
	err := q.QueryRow(ctx, `
WITH me AS (SELECT id FROM staff_profile WHERE user_id = $1 AND deleted_at IS NULL ORDER BY created_at DESC LIMIT 1)
SELECT o.id, ou.id, ou.name, c.leave_request_id
FROM temporary_coverage_assignment c
JOIN me ON me.id = c.covering_staff_id
JOIN staff_profile o ON o.id = c.original_staff_id
JOIN "user" ou ON ou.id = o.user_id
WHERE c.start_datetime <= $2 AND c.end_datetime >= $2 AND c.status = 'active'
ORDER BY c.created_at DESC LIMIT 1`, actorUserID, now).Scan(&staffID, &userID, &name, &leaveID)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, nil
	}
	if err != nil {
		return nil, fmt.Errorf("activities: reading the actor's cover: %w", err)
	}
	return map[string]any{
		"acting_for": map[string]any{
			"staff_profile_id": deref(staffID), "user_id": deref(userID), "name": deref(name),
		},
		"reason":           "Leave Coverage",
		"leave_request_id": deref(leaveID),
	}, nil
}

func deref(s *string) any {
	if s == nil {
		return nil
	}
	return *s
}

// withStamps is the payload as log() leaves it: the cover merged in.
func withStamps(payload map[string]any, cover map[string]any) map[string]any {
	if cover == nil {
		return payload
	}
	out := make(map[string]any, len(payload)+len(cover))
	for k, v := range payload {
		out[k] = v
	}
	for k, v := range cover {
		out[k] = v
	}
	return out
}
