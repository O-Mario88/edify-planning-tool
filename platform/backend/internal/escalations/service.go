package escalations

import (
	"context"
	"errors"
	"fmt"
	"math"
	"net/url"
	"time"

	"github.com/jackc/pgx/v5"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pagegate"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// Path is the page this package answers.
const Path = "/escalations"

// ErrNotAvailable is the page refused to the reader's role, which the
// existing feed answers as a page that is not there.
var ErrNotAvailable = pagegate.ErrNotAvailable

// Service builds the Escalations page.
type Service struct {
	db  schooldirectory.Querier
	now func() time.Time
}

// NewService wires the service to the database it reads.
func NewService(db schooldirectory.Querier, now func() time.Time) *Service {
	return &Service{db: db, now: now}
}

// escalation is one leadership_escalation row as the board serializes it.
type escalation struct {
	ID, RaisedBy, Category, Subject, Detail, Severity, Status string
	AddressedRole, Country                                    string
	RaisedByName, AssignedTo, RequestedDecision               *string
	Decision, DecisionNote                                    *string
	DueDate                                                   *time.Time
	CreatedAt                                                 time.Time
	ResolvedAt                                                *time.Time
	// Worked out for the reader.
	AgeDays           int
	Overdue, Mine     bool
	CanDecide, IsOpen bool
}

// reader is who is asking: their id, role and country.
type reader struct {
	id      string
	role    Role
	country string
}

// Build answers path for p with the page's query. served is false for a
// path this package does not answer.
func (s *Service) Build(ctx context.Context, p auth.Principal, path string, query url.Values) (*screensv1.GetPageResponse, bool, error) {
	if path != Path {
		return nil, false, nil
	}
	role, ok := rules.Roles[p.ActiveRole]
	if !ok || !role.Page {
		return nil, true, ErrNotAvailable
	}
	r := reader{id: p.UserID, role: role}
	var err error
	if r.country, err = s.countryOf(ctx, p.UserID); err != nil {
		return nil, true, err
	}
	rows, err := s.visible(ctx, r)
	if err != nil {
		return nil, true, err
	}
	b := board{rows: rows}
	if role.RaisesTo != "" && role.RaisesTo != rules.RegionalLevel {
		if b.raiseToID, b.raiseToName, err = s.supervisor(ctx, p.UserID, rules.RoleForAddressee[role.RaisesTo]); err != nil {
			return nil, true, err
		}
	}
	return page(role, b, query), true, nil
}

// countryOf is _country_of: the country on the reader's live staff profile,
// or none.
func (s *Service) countryOf(ctx context.Context, userID string) (string, error) {
	var country *string
	err := s.db.QueryRow(ctx, `
SELECT country FROM staff_profile WHERE user_id = $1 AND deleted_at IS NULL ORDER BY id LIMIT 1`, userID).Scan(&country)
	if errors.Is(err, pgx.ErrNoRows) || (err == nil && country == nil) {
		return "", nil
	}
	if err != nil {
		return "", fmt.Errorf("escalations: reading the reader's country: %w", err)
	}
	return *country, nil
}

// inbox is _addressed_to_me_q as a condition: named to the reader at the
// level they decide for, or addressed to that level with no one named (in
// the reader's country, below the RVP). Empty when they decide for none.
func inbox(r reader, args *[]any) string {
	level := r.role.DecidesFor
	if level == "" {
		return ""
	}
	arg := func(v any) string {
		*args = append(*args, v)
		return fmt.Sprintf("$%d", len(*args))
	}
	l := arg(level)
	byRole := "(addressed_role = " + l + " AND assigned_to_user_id IS NULL"
	if level != rules.RegionalLevel && r.country != "" {
		byRole += " AND country_id = " + arg(r.country)
	}
	return "((addressed_role = " + l + " AND assigned_to_user_id = " + arg(r.id) + ") OR " + byRole + "))"
}

// InboxClause is _addressed_to_me_q for another page (My Team): the
// condition on leadership_escalation naming what p decides, its arguments
// appended to args; "" when p decides for no level.
func InboxClause(ctx context.Context, db schooldirectory.Querier, p auth.Principal, args *[]any) (string, error) {
	r := reader{id: p.UserID, role: rules.Roles[p.ActiveRole]}
	if r.role.DecidesFor == "" {
		return "", nil
	}
	country, err := (&Service{db: db}).countryOf(ctx, p.UserID)
	if err != nil {
		return "", err
	}
	r.country = country
	return inbox(r, args), nil
}

// inInbox is the same condition for one row already read.
func inInbox(r reader, e escalation) bool {
	level := r.role.DecidesFor
	if level == "" || e.AddressedRole != level {
		return false
	}
	if e.AssignedTo != nil {
		return *e.AssignedTo == r.id
	}
	return level == rules.RegionalLevel || r.country == "" || e.Country == r.country
}

// visible is visible_to: what the reader raised, what is addressed to them
// and, for the Country Director, the country's Programme Lead items and
// what it sent up; everything for Admin. The newest first.
func (s *Service) visible(ctx context.Context, r reader) ([]escalation, error) {
	args := []any{}
	where := "TRUE"
	if !r.role.DecidesAll {
		args = append(args, r.id)
		where = "raised_by_user_id = $1"
		if q := inbox(r, &args); q != "" {
			where += " OR " + q
		}
		if r.role.ReadsCountryBoard {
			for _, level := range []string{rules.ProgrammeLeadLevel, rules.RegionalLevel} {
				args = append(args, level)
				part := fmt.Sprintf("addressed_role = $%d", len(args))
				if r.country != "" {
					args = append(args, r.country)
					part += fmt.Sprintf(" AND country_id = $%d", len(args))
				}
				where += " OR (" + part + ")"
			}
		}
	}
	rows, err := s.db.Query(ctx, `
SELECT id, raised_by_user_id, raised_by_name, addressed_role, assigned_to_user_id, country_id, category, subject,
  detail, requested_decision, severity, due_date, status, decision, decision_note, resolved_at, created_at
FROM leadership_escalation WHERE `+where+` ORDER BY created_at DESC`, args...)
	if err != nil {
		return nil, fmt.Errorf("escalations: reading the escalations: %w", err)
	}
	list, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (escalation, error) {
		var e escalation
		err := row.Scan(&e.ID, &e.RaisedBy, &e.RaisedByName, &e.AddressedRole, &e.AssignedTo, &e.Country, &e.Category,
			&e.Subject, &e.Detail, &e.RequestedDecision, &e.Severity, &e.DueDate, &e.Status, &e.Decision, &e.DecisionNote,
			&e.ResolvedAt, &e.CreatedAt)
		return e, err
	})
	if err != nil {
		return nil, fmt.Errorf("escalations: reading the escalations: %w", err)
	}
	now := s.now()
	for i := range list {
		e := &list[i]
		e.AgeDays = int(math.Floor(now.Sub(e.CreatedAt).Hours() / 24))
		e.IsOpen = e.Status != rules.Statuses.Resolved
		e.Overdue = e.Status == rules.Statuses.Open && e.AgeDays >= slaDays(e.Severity)
		e.Mine = e.RaisedBy == r.id
		e.CanDecide = r.role.DecidesAll || (inInbox(r, *e) && !e.Mine)
	}
	return list, nil
}

// supervisor is resolve_addressee's person: the reader's supervisor whose
// account holds the role the level is held by, the first link on file.
func (s *Service) supervisor(ctx context.Context, userID, role string) (string, string, error) {
	return supervisorOf(ctx, s.db, userID, role)
}

func supervisorOf(ctx context.Context, q schooldirectory.Querier, userID, role string) (string, string, error) {
	var id string
	var name *string
	err := q.QueryRow(ctx, `
SELECT sup.user_id, u.name
FROM staff_supervisor_assignment a
JOIN staff_profile se ON se.id = a.supervisee_id
JOIN staff_profile sup ON sup.id = a.supervisor_id
JOIN "user" u ON u.id = sup.user_id
WHERE se.user_id = $1 AND sup.deleted_at IS NULL AND (u.active_role = $2 OR u.roles @> ARRAY[$2]::varchar[])
ORDER BY a.id LIMIT 1`, userID, role).Scan(&id, &name)
	if errors.Is(err, pgx.ErrNoRows) {
		return "", "", nil
	}
	if err != nil {
		return "", "", fmt.Errorf("escalations: reading the reader's supervisor: %w", err)
	}
	if name == nil {
		return id, "", nil
	}
	return id, *name, nil
}

// AddresseeLabel is partner_oversight_actions.escalation_addressee_label:
// who the reader's Escalate reaches, in words — the named supervisor holding
// the addressee's role ("Name (Country Director)"), else the role; "" for a
// reader who cannot escalate.
func (s *Service) AddresseeLabel(ctx context.Context, userID, activeRole string) (string, error) {
	level := rules.Roles[activeRole].RaisesTo
	if level == "" {
		return "", nil
	}
	label := addresseeLabel(level)
	if level == rules.RegionalLevel {
		return label, nil
	}
	_, name, err := s.supervisor(ctx, userID, rules.RoleForAddressee[level])
	if err != nil || name == "" {
		return label, err
	}
	return name + " (" + label + ")", nil
}
