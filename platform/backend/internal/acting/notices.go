package acting

// The notices an appointment's change sends after its commit
// (apps.acting.services._notify_appointed, _notify_cancelled,
// _notify_rescheduled), sent by Go when the existing application is absent.

import (
	"context"
	"fmt"
	"log/slog"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/activities"
)

// Notices sends the acting notices through the one notice writer.
type Notices struct {
	DB     *pgxpool.Pool
	Push   activities.NoticePush
	Live   activities.NoticePublisher
	Logger *slog.Logger
	Now    func() time.Time
}

// noticeRow is _load's appointment with the names the notices say.
type noticeRow struct {
	Appointment
	seatUserID, cancelledByID string
}

// Notify is a Notifier: the appointment's notices for kind, never failing
// the change that is already saved.
func (n Notices) Notify(ctx context.Context, kind, appointmentID string) {
	if err := n.send(ctx, kind, appointmentID); err != nil && n.Logger != nil {
		n.Logger.WarnContext(ctx, "acting: the appointment's notices were not sent", "kind", kind, "appointment", appointmentID, "err", err)
	}
}

func (n Notices) send(ctx context.Context, kind, id string) error {
	var a noticeRow
	row := n.DB.QueryRow(ctx, appointmentSelect+` WHERE a.id = $1`, id)
	var err error
	if a.Appointment, err = scanAppointment(row); err != nil {
		return nil // _load found nothing: nothing is said
	}
	if err := n.DB.QueryRow(ctx, `SELECT COALESCE(sp.user_id, ''), COALESCE(a.cancelled_by_id, '')
FROM acting_assignment a JOIN staff_profile sp ON sp.id = a.seat_id WHERE a.id = $1`, id).Scan(&a.seatUserID, &a.cancelledByID); err != nil {
		return fmt.Errorf("acting: reading the appointment's seat: %w", err)
	}
	label, short := labelOf(a.Appointment), shortLabelOf(a.Appointment)
	period, effective := monthLabel(a.Start), effectiveLabel(a.Start, a.End)
	switch kind {
	case NoticeAppointed:
		if err := n.tell(ctx, a, "acting.appointed", "high",
			fmt.Sprintf("You have been appointed %s for %s.", short, period),
			fmt.Sprintf("%s appointed you %s for %s. Scope: %s. Effective %s. Your permanent role (%s) does not change.",
				a.AppointedByName, label, period, scopeLabel(a.Appointment), effective, a.AppointeeRole), a.AppointeeID); err != nil {
			return err
		}
		team, err := n.seatTeam(ctx, a)
		if err != nil || len(team) == 0 {
			return err
		}
		return n.tell(ctx, a, "acting.team_informed", "normal",
			fmt.Sprintf("%s is %s for %s.", a.AppointeeName, short, period),
			fmt.Sprintf("%s appointed %s %s for %s (%s). %s remains %s.", a.AppointedByName, a.AppointeeName, label, period,
				effective, a.AppointedByName, a.ByRole), team...)
	case NoticeCancelled:
		by := a.CancelledByName
		if by == "" {
			by = "A leader"
		}
		body := fmt.Sprintf("%s cancelled your %s appointment for %s. Your %s role is unchanged.", by, label, period, a.AppointeeRole)
		if a.CancelReason != "" {
			body += " Reason: " + a.CancelReason
		}
		to := []string{a.AppointeeID}
		if a.cancelledByID != a.seatUserID {
			to = append(to, a.seatUserID)
		}
		return n.tell(ctx, a, "acting.cancelled", "high",
			fmt.Sprintf("Your %s appointment for %s was cancelled.", short, period), body, to...)
	case NoticeRescheduled:
		return n.tell(ctx, a, "acting.rescheduled", "normal",
			fmt.Sprintf("Your %s appointment is now for %s.", short, period),
			fmt.Sprintf("%s moved your %s appointment to %s (%s).", a.AppointedByName, label, period, effective), a.AppointeeID)
	}
	return nil
}

func (n Notices) tell(ctx context.Context, a noticeRow, event, priority, title, body string, to ...string) error {
	var recipients []activities.NoticeTo
	for _, id := range to {
		if id != "" {
			recipients = append(recipients, activities.NoticeTo{UserID: id, Route: "/acting-leadership", Label: "Open Acting Leadership"})
		}
	}
	if len(recipients) == 0 {
		return nil
	}
	now := time.Now
	if n.Now != nil {
		now = n.Now
	}
	return activities.SendNotices(ctx, n.DB, n.Push, n.Live, n.Logger, now(), a.ID, "", activities.Origin{}, activities.Notice{
		Title: title, Body: body, Event: event, Category: "acting_leadership", ContextType: "ActingAssignment",
		Priority: priority,
	}, recipients)
}

// seatTeam is _seat_team_user_ids: the other people in the seat.
func (n Notices) seatTeam(ctx context.Context, a noticeRow) ([]string, error) {
	members := `sp.id IN (SELECT l.supervisee_id FROM staff_supervisor_assignment l WHERE l.supervisor_id = $1)`
	args := []any{a.SeatID}
	if a.ScopeType != ScopePLTeam {
		members = `(u.active_role = 'Program Lead' OR u.roles @> ARRAY['Program Lead']::varchar[]) AND sp.country = $1`
		args = []any{a.Country}
	}
	rows, err := n.DB.Query(ctx, `SELECT sp.user_id FROM staff_profile sp JOIN "user" u ON u.id = sp.user_id
WHERE `+members+` AND sp.deleted_at IS NULL AND u.is_active AND u.deleted_at IS NULL
  AND sp.user_id IS DISTINCT FROM $2 AND sp.user_id IS DISTINCT FROM $3`, append(args, a.AppointeeID, a.AppointedByID)...)
	if err != nil {
		return nil, fmt.Errorf("acting: reading the seat's team: %w", err)
	}
	defer rows.Close()
	var out []string
	for rows.Next() {
		var id string
		if err := rows.Scan(&id); err != nil {
			return nil, err
		}
		out = append(out, id)
	}
	return out, rows.Err()
}
