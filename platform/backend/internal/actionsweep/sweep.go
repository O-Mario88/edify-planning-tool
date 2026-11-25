package actionsweep

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/activities"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/audit"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schoolprofile"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/visitgate"
)

// DB is what the sweep needs of the database: reads, and a transaction for
// each action's writes.
type DB interface {
	schooldirectory.Querier
	BeginTx(context.Context, pgx.TxOptions) (pgx.Tx, error)
}

// actionContext is the notices' context type.
const actionContext = "TeamAction"

func coreRules() visitgate.CoreRules { return schoolprofile.GateRules().Core }

// Sweep is _do_school_action_sweep: resolve_due_actions, then
// mark_overdue_actions, on now (today is the application's day). It answers
// the actions closed plus those flagged overdue; an action whose condition
// cannot be read again is logged and the rest go on.
func Sweep(ctx context.Context, db DB, push activities.NoticePush, now, today time.Time, logger *slog.Logger) (int, error) {
	if logger == nil {
		logger = slog.Default()
	}
	resolved, err := resolveDue(ctx, db, push, now, today, logger)
	if err != nil {
		return resolved, err
	}
	overdue, err := markOverdue(ctx, db, push, now, today)
	return resolved + overdue, err
}

func readActions(ctx context.Context, db schooldirectory.Querier, where string, args ...any) ([]action, error) {
	rows, err := db.Query(ctx, `SELECT id, COALESCE(condition_key, ''), COALESCE(issue_type, ''), COALESCE(school_id, ''), COALESCE(fy, ''),
  COALESCE(sender_id, ''), COALESCE(recipient_id, ''), COALESCE(requested_action, ''), COALESCE(workflow_route, ''), due_date
FROM team_action WHERE `+where, args...)
	if err != nil {
		return nil, fmt.Errorf("actionsweep: the actions: %w", err)
	}
	defer rows.Close()
	out := []action{}
	for rows.Next() {
		var a action
		if err := rows.Scan(&a.id, &a.key, &a.issue, &a.school, &a.fy, &a.sender, &a.recipient, &a.requested, &a.route, &a.due); err != nil {
			return nil, err
		}
		out = append(out, a)
	}
	return out, rows.Err()
}

// resolveDue is resolve_due_actions: each active action, oldest first,
// closed by the system once its condition has cleared, with the audit row
// and the sender told.
func resolveDue(ctx context.Context, db DB, push activities.NoticePush, now, today time.Time, logger *slog.Logger) (int, error) {
	active, err := readActions(ctx, db, `state = ANY($1) ORDER BY created_at, id`, rules.ActiveStates)
	if err != nil {
		return 0, err
	}
	resolved := 0
	for _, a := range active {
		holds, err := stillHolds(ctx, db, a, today, now)
		if err != nil {
			logger.ErrorContext(ctx, "actionsweep: could not evaluate the action", "action", a.id, "err", err)
			continue
		}
		if holds {
			continue
		}
		if err := inTx(ctx, db, func(tx pgx.Tx) error {
			if _, err := tx.Exec(ctx, `SELECT gateway_scheduler.resolve_team_action($1, $2, $3)`, a.id, rules.ResolvedState, now); err != nil {
				return fmt.Errorf("actionsweep: closing the action: %w", err)
			}
			if _, err := audit.Append(ctx, tx, audit.Entry{Action: "school_action.auto_resolved", SubjectKind: audit.Text(actionContext),
				SubjectID: audit.Text(a.id), Success: true,
				Payload: map[string]any{"condition_key": a.key, "issue_type": a.issue}}, now); err != nil {
				return fmt.Errorf("actionsweep: auditing the close: %w", err)
			}
			school, err := schoolName(ctx, tx, a.school)
			if err != nil {
				return err
			}
			return notify(ctx, tx, push, now, a.sender, a.id, "school_action_resolved", "Action resolved",
				a.requested+" at "+school+" is done — the record now confirms it.", "/actions/sent")
		}); err != nil {
			return resolved, err
		}
		resolved++
	}
	return resolved, nil
}

// markOverdue is mark_overdue_actions: each action past its due date
// flagged overdue, the recipient and the sender told.
func markOverdue(ctx context.Context, db DB, push activities.NoticePush, now, today time.Time) (int, error) {
	late, err := readActions(ctx, db, `state = ANY($1) AND due_date < $2::date ORDER BY created_at, id`, rules.OverdueFromStates, today)
	if err != nil {
		return 0, err
	}
	count := 0
	for _, a := range late {
		if err := inTx(ctx, db, func(tx pgx.Tx) error {
			if _, err := tx.Exec(ctx, `SELECT gateway_scheduler.mark_team_action_overdue($1, $2, $3)`, a.id, rules.OverdueState, now); err != nil {
				return fmt.Errorf("actionsweep: flagging the action overdue: %w", err)
			}
			school, err := schoolName(ctx, tx, a.school)
			if err != nil {
				return err
			}
			due := ""
			if a.due != nil {
				due = a.due.Format("2 Jan")
			}
			if err := notify(ctx, tx, push, now, a.recipient, a.id, "school_action_overdue", "Action overdue",
				a.requested+" at "+school+" was due "+due+".", a.route); err != nil {
				return err
			}
			name, err := nameOf(ctx, tx, a.recipient)
			if err != nil {
				return err
			}
			return notify(ctx, tx, push, now, a.sender, a.id, "school_action_overdue_sender", "Action overdue",
				name+" has not completed "+strings.ToLower(a.requested)+" at "+school+".", "/actions/sent")
		}); err != nil {
			return count, err
		}
		count++
	}
	return count, nil
}

func inTx(ctx context.Context, db DB, run func(pgx.Tx) error) error {
	tx, err := db.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite})
	if err != nil {
		return err
	}
	defer func() { _ = tx.Rollback(ctx) }()
	if err := run(tx); err != nil {
		return err
	}
	return tx.Commit(ctx)
}

// notify is action_service._notify: the platform's own notice on the action
// (update_or_create by recipient, context and event); nobody to tell, no
// notice.
func notify(ctx context.Context, tx pgx.Tx, push activities.NoticePush, now time.Time, recipient, id, event, title, body, route string) error {
	if recipient == "" {
		return nil
	}
	_, _, err := activities.NotifyFromPerson(ctx, tx, push, now, activities.PersonNotice{Recipient: recipient, ContextType: actionContext,
		ContextID: id, Event: event, Fields: map[string]any{"title": title, "body": body, "category": "planning", "target_route": route,
			"priority": "high", "status": "unread", "source_event_id": id, "read_at": nil}})
	if err != nil && !errors.Is(err, activities.ErrPhoneCopy) {
		return err
	}
	return nil
}

// schoolName is _school_name.
func schoolName(ctx context.Context, q schooldirectory.Querier, id string) (string, error) {
	var name string
	err := q.QueryRow(ctx, `SELECT COALESCE(name, '') FROM school WHERE id = $1`, id).Scan(&name)
	if err != nil && !errors.Is(err, pgx.ErrNoRows) {
		return "", fmt.Errorf("actionsweep: the school's name: %w", err)
	}
	if name == "" {
		return "the school", nil
	}
	return name, nil
}

// nameOf is _name_of.
func nameOf(ctx context.Context, q schooldirectory.Querier, userID string) (string, error) {
	var name string
	err := q.QueryRow(ctx, `SELECT COALESCE(name, '') FROM "user" WHERE id = $1`, userID).Scan(&name)
	if err != nil && !errors.Is(err, pgx.ErrNoRows) {
		return "", fmt.Errorf("actionsweep: the recipient's name: %w", err)
	}
	if name == "" {
		return "a colleague", nil
	}
	return name, nil
}
