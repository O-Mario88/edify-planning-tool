package todos

import (
	"context"
	"fmt"
	"time"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// NextAction is compute_next_action's answer for one activity: the step's
// words, its kind ("view" when no owner step applies), where it opens and
// the line that says why.
type NextAction struct{ Text, Action, URL, Description string }

// NextActions is my_plan.services.compute_next_action for each of the
// activities, read as the To-Do builders read them (their school's SSA
// state and their cost lines' advances), for a page that lists work it does
// not own (Team Plans).
func NextActions(ctx context.Context, db schooldirectory.Querier, ids []string, today time.Time) (map[string]NextAction, error) {
	out := map[string]NextAction{}
	if len(ids) == 0 {
		return out, nil
	}
	rows, err := db.Query(ctx, `
SELECT a.id, a.status, COALESCE(a.delivery_type, ''), COALESCE(a.evidence_status, ''), a.planned_date,
  COALESCE(a.salesforce_activity_id, ''), a.activity_type, COALESCE(a.teachers_attended, 0), COALESCE(a.leaders_attended, 0),
  COALESCE(a.ia_verification_status, ''), COALESCE(a.payment_status, ''), a.school_id IS NOT NULL,
  COALESCE(s.current_fy_ssa_status, '')
FROM activity a LEFT OUTER JOIN school s ON s.id = a.school_id WHERE a.id = ANY($1)`, ids)
	if err != nil {
		return nil, fmt.Errorf("todos: reading the activities' next steps: %w", err)
	}
	list, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (activity, error) {
		var a activity
		var planned *time.Time
		err := row.Scan(&a.ID, &a.Status, &a.DeliveryType, &a.EvidenceStatus, &planned, &a.SalesforceID,
			&a.ActivityType, &a.Teachers, &a.Leaders, &a.IAVerification, &a.Payment, &a.HasSchool, &a.SchoolSSAStatus)
		if planned != nil {
			a.PlannedDate = dateOf(*planned)
		}
		return a, err
	})
	if err != nil {
		return nil, fmt.Errorf("todos: reading the activities' next steps: %w", err)
	}
	advances, err := (&Service{db: db}).advances(ctx, ids)
	if err != nil {
		return nil, fmt.Errorf("todos: reading the activities' advances: %w", err)
	}
	for _, a := range list {
		a.Advances = advances[a.ID]
		na := computeNextAction(a, today)
		out[a.ID] = NextAction{Text: na.Text, Action: na.Action, URL: na.URL, Description: na.Description}
	}
	return out, nil
}
