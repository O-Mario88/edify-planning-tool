package acting

// The acting_lifecycle job (apps.acting.lifecycle.sweep): an appointment's
// reminder three days ahead of its first day, its start and its end, each
// stamped once on the row, the start and end audited, and the appointee told.
// Access never waits on this: an appointment is in effect on its dates.

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"time"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/activities"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/audit"
)

// reminderDays is REMINDER_DAYS.
const reminderDays = 3

// lifecycleStep is one of the sweep's three passes.
type lifecycleStep struct {
	due   string // which standing appointments are due, $1 the day
	stamp string // the column the step sets once
	write func(ctx context.Context, tx pgx.Tx, a Appointment, now time.Time, push activities.NoticePush) error
}

// Sweep is lifecycle.sweep for the day on (Kampala's calendar day); it says
// how many transitions it recorded.
func Sweep(ctx context.Context, tx pgx.Tx, on, now time.Time, push activities.NoticePush) (int, error) {
	day := on.Format(time.DateOnly)
	steps := []lifecycleStep{
		{due: `start_date > $1::date AND start_date <= $1::date + ` + fmt.Sprint(reminderDays) + ` AND reminded_at IS NULL`,
			stamp: "reminded_at", write: remind},
		{due: `start_date <= $1::date AND end_date >= $1::date AND activated_at IS NULL`, stamp: "activated_at", write: activate},
		{due: `end_date < $1::date AND expired_at IS NULL`, stamp: "expired_at", write: expire},
	}
	done := 0
	for _, step := range steps {
		n, err := runStep(ctx, tx, step, day, now, push)
		done += n
		if err != nil {
			return done, err
		}
	}
	return done, nil
}

func runStep(ctx context.Context, tx pgx.Tx, step lifecycleStep, day string, now time.Time, push activities.NoticePush) (int, error) {
	rows, err := tx.Query(ctx, `SELECT id FROM acting_assignment WHERE cancelled_at IS NULL AND `+step.due+`
ORDER BY start_date DESC, created_at DESC`, day)
	if err != nil {
		return 0, fmt.Errorf("acting: reading the appointments due a %s: %w", step.stamp, err)
	}
	ids, err := pgx.CollectRows(rows, pgx.RowTo[string])
	if err != nil {
		return 0, err
	}
	done := 0
	for _, id := range ids {
		a, err := scanAppointment(tx.QueryRow(ctx, appointmentSelect+` WHERE a.id = $1 AND a.cancelled_at IS NULL
  AND a.`+step.stamp+` IS NULL FOR UPDATE OF a`, id))
		if errors.Is(err, pgx.ErrNoRows) {
			continue
		}
		if err != nil {
			return done, fmt.Errorf("acting: reading the appointment due a %s: %w", step.stamp, err)
		}
		if _, err := tx.Exec(ctx, `UPDATE acting_assignment SET `+step.stamp+` = $2, updated_at = $2 WHERE id = $1`,
			id, now); err != nil {
			return done, fmt.Errorf("acting: stamping %s: %w", step.stamp, err)
		}
		if err := step.write(ctx, tx, a, now, push); err != nil {
			return done, err
		}
		done++
	}
	return done, nil
}

func shortLabelOf(a Appointment) string {
	if entry, ok := ByKey(a.RoleKey); ok {
		return entry.ShortLabel
	}
	return a.RoleKey
}

// dayLabel is strftime('%B') with the day: "November 30".
func dayLabel(t time.Time) string { return fmt.Sprintf("%s %d", t.Format("January"), t.Day()) }

func tellAppointee(ctx context.Context, tx pgx.Tx, a Appointment, now time.Time, push activities.NoticePush,
	event, title, body string) error {
	_, err := activities.NotifyInTx(ctx, tx, push, slog.Default(), now, a.ID, activities.Notice{
		Title: title, Body: body, Event: event, Category: "acting_leadership", ContextType: "ActingAssignment",
		Priority: "normal",
	}, []activities.NoticeTo{{UserID: a.AppointeeID, Route: "/acting-leadership", Label: "Open Acting Leadership"}})
	if err != nil {
		return fmt.Errorf("acting: telling the appointee (%s): %w", event, err)
	}
	return nil
}

func lifecycleAudit(ctx context.Context, tx pgx.Tx, action string, a Appointment, now time.Time) error {
	if _, err := audit.Append(ctx, tx, audit.Entry{
		Action: action, SubjectKind: audit.Text("ActingAssignment"), SubjectID: audit.Text(a.ID), Success: true,
		Payload: describe(a),
	}, now); err != nil {
		return fmt.Errorf("acting: auditing %s: %w", action, err)
	}
	return nil
}

func remind(ctx context.Context, tx pgx.Tx, a Appointment, now time.Time, push activities.NoticePush) error {
	return tellAppointee(ctx, tx, a, now, push, "acting.reminder",
		fmt.Sprintf("Your %s assignment begins %s.", shortLabelOf(a), dayLabel(a.Start)),
		fmt.Sprintf("You are %s for %s (%s), appointed by %s. Scope: %s. It starts by itself on the first day.",
			labelOf(a), monthLabel(a.Start), effectiveLabel(a.Start, a.End), a.AppointedByName, scopeLabel(a)))
}

func activate(ctx context.Context, tx pgx.Tx, a Appointment, now time.Time, push activities.NoticePush) error {
	if err := lifecycleAudit(ctx, tx, "acting_assignment.activated", a, now); err != nil {
		return err
	}
	return tellAppointee(ctx, tx, a, now, push, "acting.started",
		fmt.Sprintf("You are %s for %s.", shortLabelOf(a), monthLabel(a.Start)),
		fmt.Sprintf("Your %s appointment is in effect until %s. Scope: %s. Switch between %s and your %s role from the account menu.",
			labelOf(a), dayLabel(a.End), scopeLabel(a), shortLabelOf(a), a.AppointeeRole))
}

func expire(ctx context.Context, tx pgx.Tx, a Appointment, now time.Time, push activities.NoticePush) error {
	if err := syncHint(ctx, tx, a.AppointeeID); err != nil {
		return err
	}
	if err := lifecycleAudit(ctx, tx, "acting_assignment.expired", a, now); err != nil {
		return err
	}
	return tellAppointee(ctx, tx, a, now, push, "acting.ended",
		fmt.Sprintf("Your %s appointment for %s has ended.", shortLabelOf(a), monthLabel(a.Start)),
		fmt.Sprintf("Your %s access ended on %s. You continue as %s.", labelOf(a), dayLabel(a.End), a.AppointeeRole))
}
