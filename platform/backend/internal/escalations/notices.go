package escalations

// The escalation channel's notices (_notify_addressees and the trigger it
// goes through), shared by the raise and the scheduler's SLA sweep.

import (
	"context"
	"fmt"
	"log/slog"
	"time"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/activities"
)

// OpenEvent is ESCALATION_OPEN.
const OpenEvent = "leadership_escalation_open"

// Addressed is one escalation as its addressees' notice reads it.
type Addressed struct {
	ID, Severity, Level, Assigned, Country, Detail string
}

// TellAddressees is _notify_addressees: whoever the escalation is addressed
// to is told under title, high priority unless it is a normal one.
func TellAddressees(ctx context.Context, tx pgx.Tx, push activities.NoticePush, now time.Time, e Addressed, title string) error {
	recipients, err := AddresseeIDs(ctx, tx, e)
	if err != nil || len(recipients) == 0 {
		return err
	}
	priority := "high"
	if e.Severity == "normal" {
		priority = "normal"
	}
	return Notify(ctx, tx, push, now, e.ID, OpenEvent, priority, title, cut(e.Detail, 300), recipients)
}

// AddresseeIDs is _addressee_user_ids: the named person, or every active
// holder of the addressed role, in the escalation's country for a lead or a
// director when any holds it there.
func AddresseeIDs(ctx context.Context, tx pgx.Tx, e Addressed) ([]string, error) {
	if e.Assigned != "" {
		return []string{e.Assigned}, nil
	}
	role := rules.RoleForAddressee[e.Level]
	if role == "" {
		return nil, nil
	}
	read := func(inCountry bool) ([]string, error) {
		query := `SELECT u.id FROM "user" u WHERE u.roles @> ARRAY[$1::varchar] AND u.status = 'active'`
		args := []any{role}
		if inCountry {
			query += ` AND EXISTS (SELECT 1 FROM staff_profile sp WHERE sp.user_id = u.id AND sp.country = $2)`
			args = append(args, e.Country)
		}
		rows, err := tx.Query(ctx, query+` ORDER BY u.created_at DESC`, args...)
		if err != nil {
			return nil, fmt.Errorf("escalations: reading the escalation's addressees: %w", err)
		}
		return pgx.CollectRows(rows, pgx.RowTo[string])
	}
	if e.Level != rules.RegionalLevel {
		local, err := read(true)
		if err != nil || len(local) > 0 {
			return local, err
		}
	}
	return read(false)
}

// Notify is the trigger for one escalation's notice: each recipient opens
// the Escalations page.
func Notify(ctx context.Context, tx pgx.Tx, push activities.NoticePush, now time.Time, escalationID, event, priority, title, body string,
	recipients []string) error {
	to := make([]activities.NoticeTo, 0, len(recipients))
	for _, id := range recipients {
		to = append(to, activities.NoticeTo{UserID: id, Route: "/escalations", Label: "Open Escalation"})
	}
	if _, err := activities.NotifyInTx(ctx, tx, push, slog.Default(), now, escalationID, activities.Notice{
		Title: title, Body: body, Event: event, Category: "leadership", ContextType: "escalation", Priority: priority,
	}, to); err != nil {
		return fmt.Errorf("escalations: sending the escalation notice: %w", err)
	}
	return nil
}

// tellRaised is raise_escalation's _notify_addressees for the escalation
// just written in tx, in a savepoint of its own: a notice must never block
// the escalation.
func tellRaised(ctx context.Context, tx pgx.Tx, push activities.NoticePush, now time.Time, r Raised, e Addressed, raiserName, subject string) {
	inner, err := tx.Begin(ctx)
	if err != nil {
		return
	}
	err = TellAddressees(ctx, inner, push, now, e, fmt.Sprintf("Escalation from %s: %s", first(raiserName, "a colleague"), subject))
	if err == nil {
		err = inner.Commit(ctx)
	}
	if err != nil {
		_ = inner.Rollback(ctx)
		slog.Default().WarnContext(ctx, "escalations: the escalation's addressees were not told", "escalation", r.ID, "err", err)
	}
}
