package activities

import (
	"context"
	"fmt"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
)

// ApplyBulkPlannedStatus updates a single planned activity's status and notes
// inside caller tx for the Bulk Upload Center, enforcing CCEO ownership scope
// and keeping all activity table writes strictly inside internal/activities.
func ApplyBulkPlannedStatus(
	ctx context.Context, tx pgx.Tx, p auth.Principal,
	activityID, targetStatus, notes string, now time.Time,
) (bool, error) {
	targetStatus = strings.ToLower(strings.TrimSpace(targetStatus))
	switch targetStatus {
	case "completed", "submitted_to_pl", "cancelled":
	default:
		return false, fmt.Errorf("activities: unsupported bulk status %q", targetStatus)
	}
	q := `UPDATE activity SET status = $1, updated_at = $2, completion_notes = CASE WHEN $3 <> '' THEN $3 ELSE completion_notes END WHERE id = $4 AND deleted_at IS NULL`
	args := []any{targetStatus, now.UTC(), strings.TrimSpace(notes), strings.TrimSpace(activityID)}
	if p.ActiveRole == "CCEO" && p.StaffProfileID != "" {
		args = append(args, p.StaffProfileID)
		q += ` AND responsible_staff_id = $5`
	}
	tag, err := tx.Exec(ctx, q, args...)
	if err != nil {
		return false, fmt.Errorf("activities: bulk update activity: %w", err)
	}
	return tag.RowsAffected() > 0, nil
}
