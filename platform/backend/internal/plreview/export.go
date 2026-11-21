package plreview

import (
	"bytes"
	"context"
	"encoding/csv"
	"fmt"
	"strconv"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
)

// ExportCompletedVisitsCSV generates an authorized CSV export of completed and
// verified activities strictly scoped to the caller's role without touching
// Django.
//
// Scope rules:
//   - Admin / CountryDirector: all completed/verified visits in the request's
//     country (enforced by countryctx RLS).
//   - Program Lead: completed/verified visits of supervised officers + own.
//   - CCEO: own completed/verified visits only.
//   - Other roles: refused (Forbidden).
func (s *ReviewService) ExportCompletedVisitsCSV(ctx context.Context, p auth.Principal) ([]byte, int, error) {
	var (
		sql  string
		args []any
	)
	const cols = `
SELECT a.id, COALESCE(sc.school_id, ''), COALESCE(sc.name, ''), COALESCE(a.activity_type, ''),
       a.planned_date, a.actual_delivery_date, COALESCE(a.status, ''),
       COALESCE(a.salesforce_activity_id, ''),
       COALESCE(a.teachers_attended, 0), COALESCE(a.leaders_attended, 0), COALESCE(a.other_participants, 0)
FROM activity a
LEFT JOIN school sc ON sc.id = a.school_id
WHERE a.deleted_at IS NULL
  AND a.status IN ('submitted_to_pl', 'awaiting_ia_verification', 'ia_verified', 'completed', 'closed', 'accountant_confirmed')`

	switch p.ActiveRole {
	case "Admin", "CountryDirector":
		sql = cols + ` ORDER BY a.actual_delivery_date DESC NULLS LAST, a.id ASC LIMIT 1000`
	case "Program Lead":
		sql = cols + `
  AND (
    a.responsible_staff_id IN ($1, $2)
    OR a.responsible_staff_id IN (
      SELECT ssa.supervisee_id FROM staff_supervisor_assignment ssa WHERE ssa.supervisor_id IN ($1, $2)
      UNION
      SELECT sp.user_id FROM staff_supervisor_assignment ssa
      JOIN staff_profile sp ON sp.id = ssa.supervisee_id
      WHERE ssa.supervisor_id IN ($1, $2) AND sp.user_id IS NOT NULL
    )
  )
ORDER BY a.actual_delivery_date DESC NULLS LAST, a.id ASC LIMIT 1000`
		args = []any{p.StaffProfileID, p.UserID}
	case "CCEO":
		sql = cols + `
  AND a.responsible_staff_id IN ($1, $2)
ORDER BY a.actual_delivery_date DESC NULLS LAST, a.id ASC LIMIT 1000`
		args = []any{p.StaffProfileID, p.UserID}
	default:
		return nil, 0, &ReviewRefusal{
			Message:   "Your role may not export completed school visits.",
			Forbidden: true,
		}
	}

	rows, err := s.pool.Query(ctx, sql, args...)
	if err != nil {
		return nil, 0, fmt.Errorf("plreview: querying visits for export: %w", err)
	}
	defer rows.Close()

	var buf bytes.Buffer
	w := csv.NewWriter(&buf)
	if err := w.Write([]string{
		"Activity ID", "School ID", "School Name", "Activity Type",
		"Planned Date", "Delivery Date", "Status", "Salesforce ID",
		"Teachers Attended", "Leaders Attended", "Other Participants",
	}); err != nil {
		return nil, 0, err
	}
	count := 0
	for rows.Next() {
		var (
			id, schoolCode, schoolName, actType, status, sfID string
			planned, delivered                                *time.Time
			teachers, leaders, other                          int
		)
		if err := rows.Scan(&id, &schoolCode, &schoolName, &actType, &planned, &delivered, &status, &sfID, &teachers, &leaders, &other); err != nil {
			return nil, 0, fmt.Errorf("plreview: scanning export row: %w", err)
		}
		fmtDate := func(t *time.Time) string {
			if t == nil {
				return ""
			}
			return t.Format("2006-01-02")
		}
		if err := w.Write([]string{
			id, schoolCode, schoolName, actType,
			fmtDate(planned), fmtDate(delivered), status, sfID,
			strconv.Itoa(teachers), strconv.Itoa(leaders), strconv.Itoa(other),
		}); err != nil {
			return nil, 0, err
		}
		count++
	}
	if err := rows.Err(); err != nil {
		return nil, 0, err
	}
	w.Flush()
	if err := w.Error(); err != nil {
		return nil, 0, err
	}
	return buf.Bytes(), count, nil
}
