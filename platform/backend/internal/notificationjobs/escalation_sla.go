package notificationjobs

// The escalation_sla_sweep job (apps.flags.escalation_service.sweep_overdue):
// every open leadership escalation past its severity's SLA is pushed again
// to whoever it is addressed to, and its raiser is told it is still waiting
// on that level. The notices go through the one notice writer, so a week's
// sweeps re-fire into the same open notice rather than adding to it.

import (
	"context"
	"fmt"
	"log/slog"
	"time"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/activities"
)

const (
	escalationOpen    = "leadership_escalation_open"
	escalationOverdue = "leadership_escalation_overdue"
)

// slaDays are SLA_DAYS, by severity; anything else takes normal's.
var slaDays = map[string]int{"critical": 2, "high": 4, "normal": 7}

// addresseeLabels are EscalationAddressee's labels; roleForAddressee is
// ROLE_FOR_ADDRESSEE.
var (
	addresseeLabels  = map[string]string{"PL": "Programme Lead", "CD": "Country Director", "RVP": "Regional Vice President"}
	roleForAddressee = map[string]string{"PL": "Program Lead", "CD": "CountryDirector", "RVP": "RegionalVicePresident"}
)

type escalation struct {
	id, status, severity, role, assigned, country, subject, detail, raiser, raiserName string
	created                                                                            time.Time
}

// firstRunes is a Python slice [:n] of a string.
func firstRunes(s string, n int) string {
	r := []rune(s)
	if len(r) > n {
		return string(r[:n])
	}
	return s
}

// SweepOverdueEscalations says how many escalations it pushed again.
func SweepOverdueEscalations(ctx context.Context, tx pgx.Tx, now time.Time, push activities.NoticePush) (int, error) {
	rows, err := tx.Query(ctx, `SELECT id, status, COALESCE(severity, ''), COALESCE(addressed_role, ''),
  COALESCE(assigned_to_user_id, ''), COALESCE(country_id, ''), subject, detail, COALESCE(raised_by_user_id, ''),
  COALESCE(raised_by_name, ''), created_at
FROM leadership_escalation WHERE status IS DISTINCT FROM 'resolved' ORDER BY created_at DESC`)
	if err != nil {
		return 0, fmt.Errorf("notificationjobs: reading the escalations: %w", err)
	}
	open, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (escalation, error) {
		var e escalation
		err := row.Scan(&e.id, &e.status, &e.severity, &e.role, &e.assigned, &e.country, &e.subject, &e.detail, &e.raiser,
			&e.raiserName, &e.created)
		return e, err
	})
	if err != nil {
		return 0, fmt.Errorf("notificationjobs: reading the escalations: %w", err)
	}
	pushed := 0
	for _, e := range open {
		limit, ok := slaDays[e.severity]
		if !ok {
			limit = slaDays["normal"]
		}
		age := int(now.Sub(e.created).Hours() / 24)
		if e.status != "open" || age < limit {
			continue
		}
		if err := tellAddressees(ctx, tx, push, now, e, fmt.Sprintf("Overdue escalation (%dd): %s", age, e.subject)); err != nil {
			return pushed, err
		}
		if e.raiser != "" {
			waiting := addresseeLabels[e.role]
			if waiting == "" {
				waiting = "decision-maker"
			}
			body := fmt.Sprintf("“%s” has passed its SLA without a decision from the %s.", e.subject, waiting)
			if err := escalationNotice(ctx, tx, push, now, e, escalationOverdue, "normal",
				fmt.Sprintf("Your escalation is overdue (%dd)", age), firstRunes(body, 300), []string{e.raiser}); err != nil {
				return pushed, err
			}
		}
		pushed++
	}
	return pushed, nil
}

// tellAddressees is _notify_addressees.
func tellAddressees(ctx context.Context, tx pgx.Tx, push activities.NoticePush, now time.Time, e escalation, title string) error {
	recipients, err := addresseeIDs(ctx, tx, e)
	if err != nil || len(recipients) == 0 {
		return err
	}
	priority := "high"
	if e.severity == "normal" {
		priority = "normal"
	}
	return escalationNotice(ctx, tx, push, now, e, escalationOpen, priority, title, firstRunes(e.detail, 300), recipients)
}

// addresseeIDs is _addressee_user_ids: the named person, or every active
// holder of the addressed role, in the escalation's country for a lead or a
// director when any holds it there.
func addresseeIDs(ctx context.Context, tx pgx.Tx, e escalation) ([]string, error) {
	if e.assigned != "" {
		return []string{e.assigned}, nil
	}
	role := roleForAddressee[e.role]
	if role == "" {
		return nil, nil
	}
	read := func(inCountry bool) ([]string, error) {
		query := `SELECT u.id FROM "user" u WHERE u.roles @> ARRAY[$1::varchar] AND u.status = 'active'`
		args := []any{role}
		if inCountry {
			query += ` AND EXISTS (SELECT 1 FROM staff_profile sp WHERE sp.user_id = u.id AND sp.country = $2)`
			args = append(args, e.country)
		}
		rows, err := tx.Query(ctx, query+` ORDER BY u.created_at DESC`, args...)
		if err != nil {
			return nil, fmt.Errorf("notificationjobs: reading the escalation's addressees: %w", err)
		}
		return pgx.CollectRows(rows, pgx.RowTo[string])
	}
	if e.role != "RVP" {
		local, err := read(true)
		if err != nil || len(local) > 0 {
			return local, err
		}
	}
	return read(false)
}

func escalationNotice(ctx context.Context, tx pgx.Tx, push activities.NoticePush, now time.Time, e escalation,
	event, priority, title, body string, recipients []string) error {
	to := make([]activities.NoticeTo, 0, len(recipients))
	for _, id := range recipients {
		to = append(to, activities.NoticeTo{UserID: id, Route: "/escalations", Label: "Open Escalation"})
	}
	if _, err := activities.NotifyInTx(ctx, tx, push, slog.Default(), now, e.id, activities.Notice{
		Title: title, Body: body, Event: event, Category: "leadership", ContextType: "escalation", Priority: priority,
	}, to); err != nil {
		return fmt.Errorf("notificationjobs: sending the escalation notice: %w", err)
	}
	return nil
}
