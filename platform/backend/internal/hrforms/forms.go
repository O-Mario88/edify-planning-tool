// Package hrforms is the HR programmes' forms (apps.frontend.views.
// hr_programme_views and the apps.hr services behind them) with Django
// absent: what each drawer offers and what each save checks and writes, in
// the services' words. The drawers themselves are drawn by internal/screens
// as the shared HR form drawer (partials/hr/form_drawer.html).
package hrforms

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/activities"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/audit"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/hrregister"
)

// Refusal is a service's BadRequest, Forbidden, ConflictError or NotFound:
// the words the reader is told.
type Refusal struct{ Message string }

func (r *Refusal) Error() string { return r.Message }

func refuse(words string) error { return &Refusal{Message: words} }

// ErrHandOn is a reader or a case Go leaves to the existing application.
var ErrHandOn = errors.New("hrforms: handed on")

// Choice is one option of a select.
type Choice struct{ Value, Label string }

// Forms is the HR programmes' forms over the gateway's pool.
type Forms struct {
	DB      *pgxpool.Pool
	Push    activities.NoticePush
	Live    activities.NoticePublisher
	Logger  *slog.Logger
	Now     func() time.Time
	Kampala *time.Location
}

func (f Forms) now() time.Time {
	if f.Now != nil {
		return f.Now()
	}
	return time.Now()
}

// today is the day in Kampala (the owner's rule: the local day).
func (f Forms) today() time.Time {
	loc := f.Kampala
	if loc == nil {
		loc = time.UTC
	}
	l := f.now().In(loc)
	return time.Date(l.Year(), l.Month(), l.Day(), 0, 0, 0, 0, time.UTC)
}

// hrRoles are the services' _HR_ROLES.
var hrRoles = []string{"HumanResources", "Admin"}

// HandsOn is whether Go leaves p's forms to the existing application: a
// reader working in an acting appointment (the stamp audit_stamp_for adds
// is not Go's yet).
func HandsOn(p auth.Principal) bool { return p.Acting != nil || p.InActingAppointment }

// assertHR is _assert_hr.
func assertHR(p auth.Principal) error {
	for _, r := range hrRoles {
		if p.ActiveRole == r {
			return nil
		}
	}
	return refuse("Only HR may record this.")
}

// PeopleOptions is _people_options: the live, still-employed People records
// in the reader's reach as "Name · Country", by name, the first 500.
func (f Forms) PeopleOptions(ctx context.Context, p auth.Principal) ([]Choice, error) {
	where, args, _, err := hrregister.PeopleReachProfiles(ctx, f.DB, p, nil)
	if err != nil {
		return nil, err
	}
	rows, err := f.DB.Query(ctx, `
SELECT sp.id, u.name, COALESCE(sp.country, '') FROM staff_profile sp JOIN "user" u ON u.id = sp.user_id
WHERE sp.deleted_at IS NULL AND u.deleted_at IS NULL AND sp.onboarding_state IS DISTINCT FROM 'exited' AND `+where+`
ORDER BY u.name, sp.id LIMIT 500`, args...)
	if err != nil {
		return nil, fmt.Errorf("hrforms: reading the people in reach: %w", err)
	}
	defer rows.Close()
	out := []Choice{}
	for rows.Next() {
		var id, name, country string
		if err := rows.Scan(&id, &name, &country); err != nil {
			return nil, fmt.Errorf("hrforms: reading the people in reach: %w", err)
		}
		label := name
		if country != "" {
			label = name + " · " + country
		}
		out = append(out, Choice{Value: id, Label: label})
	}
	return out, rows.Err()
}

// staff is a People record the reader reaches.
type staff struct{ id, userID, name, country string }

// staffInReach is _staff_in_reach: the live People record id names, if the
// reader reaches it (nil otherwise: the view's Http404).
func (f Forms) staffInReach(ctx context.Context, q pgx.Tx, p auth.Principal, id string) (*staff, error) {
	where, args, _, err := hrregister.PeopleReachProfiles(ctx, q, p, []any{id})
	if err != nil {
		return nil, err
	}
	var s staff
	var userID, country *string
	err = q.QueryRow(ctx, `
SELECT sp.id, sp.user_id, COALESCE(u.name, ''), sp.country FROM staff_profile sp LEFT JOIN "user" u ON u.id = sp.user_id
WHERE sp.deleted_at IS NULL AND sp.id = $1 AND `+where, args...).Scan(&s.id, &userID, &s.name, &country)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, nil
	}
	if err != nil {
		return nil, fmt.Errorf("hrforms: reading the employee: %w", err)
	}
	if userID != nil {
		s.userID = *userID
	}
	if country != nil {
		s.country = *country
	}
	return &s, nil
}

// write runs fn in one read-write transaction.
func (f Forms) write(ctx context.Context, fn func(pgx.Tx) error) error {
	tx, err := f.DB.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite})
	if err != nil {
		return fmt.Errorf("hrforms: opening the transaction: %w", err)
	}
	defer func() { _ = tx.Rollback(ctx) }()
	if err := fn(tx); err != nil {
		return err
	}
	if err := tx.Commit(ctx); err != nil {
		return fmt.Errorf("hrforms: committing: %w", err)
	}
	return nil
}

// auditRow is the services' _audit through apps.audit.services.log: the
// actor (with the cover they hold), the request's address, browser and
// correlation id.
func auditRow(ctx context.Context, tx pgx.Tx, action, kind, id string, p auth.Principal, payload map[string]any,
	o activities.Origin, now time.Time) error {
	cover, err := audit.CoverageStamp(ctx, tx, p.UserID, now)
	if err != nil {
		return err
	}
	role := p.ActiveRole
	if _, err := audit.Append(ctx, tx, audit.Entry{
		Action: action, SubjectKind: audit.Text(kind), SubjectID: audit.Text(id),
		ActorID: audit.Text(p.UserID), ActorRole: &role, Success: true, Payload: audit.WithStamps(payload, cover),
		IPAddress: audit.Text(o.IP), UserAgent: audit.Text(o.UserAgent), CorrelationID: audit.Text(o.CorrelationID),
	}, now); err != nil {
		return fmt.Errorf("hrforms: auditing %s: %w", action, err)
	}
	return nil
}

// day is _date: "" is no day; anything not YYYY-MM-DD is refused.
func day(raw string) (*time.Time, error) {
	raw = strings.TrimSpace(raw)
	if raw == "" {
		return nil, nil
	}
	t, err := time.Parse("2006-01-02", raw)
	if err != nil {
		return nil, refuse("Dates use the format YYYY-MM-DD.")
	}
	return &t, nil
}
