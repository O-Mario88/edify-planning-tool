package todos

import (
	"context"
	"errors"
	"fmt"
	"net/url"
	"time"

	_ "time/tzdata" // the page's day is Nairobi's wherever the gateway runs

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pagegate"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// Path is the page this package answers.
const Path = "/todos"

// ErrNotAvailable is the page refused to the reader's role, which the
// existing feed answers as a page that is not there.
var ErrNotAvailable = pagegate.ErrNotAvailable

// zone is settings.TIME_ZONE: date.today() and timezone.localdate() are its
// day.
var zone = mustZone("Africa/Nairobi")

func mustZone(name string) *time.Location {
	z, err := time.LoadLocation(name)
	if err != nil {
		panic("todos: " + err.Error())
	}
	return z
}

// Service builds the To-Do page.
type Service struct {
	db  schooldirectory.Querier
	now func() time.Time
}

// NewService wires the service to the database it reads.
func NewService(db schooldirectory.Querier, now func() time.Time) *Service {
	return &Service{db: db, now: now}
}

// reader is everything a builder is given.
type reader struct {
	p     auth.Principal
	role  string
	scope schooldirectory.Scope
	// today is the local day, at midnight UTC; now the moment.
	today, now time.Time
	// fy is get_operational_fy() (read in UTC).
	fy string
	// owners are the reader's two ids (_owner_ids and scoping.owner_ids:
	// the account and the staff profile).
	owners []string
}

// errPassOn is a builder's answer when the reader has records it does not
// build yet: the existing application builds the page instead.
var errPassOn = errors.New("todos: passed to the existing application")

// Handled is every builder of the queue Go has, by the queue's own name for
// it (rules.Builders): each returns the rows it adds, or errPassOn.
var Handled = map[string]func(ctx context.Context, s *Service, r *reader) ([]todo, error){}

// PortedRoles are the roles whose queue Go builds; every other role is
// passed on, whatever the builders it reaches.
var PortedRoles = []string{"CCEO"}

// Served is whether Go answers a role at all: Go has built the role's queue
// and has every builder the role reaches.
func Served(role string) bool {
	r, ok := rules.Roles[role]
	if !ok || !contains(PortedRoles, role) {
		return false
	}
	for _, name := range r.Builders {
		if _, ok := Handled[name]; !ok {
			return false
		}
	}
	return true
}

// Build answers path for p. served is false for a path this package does
// not answer and for a reader whose queue needs a builder Go does not have.
func (s *Service) Build(ctx context.Context, p auth.Principal, path string, _ url.Values) (*screensv1.GetPageResponse, bool, error) {
	if path != Path {
		return nil, false, nil
	}
	role, ok := rules.Roles[p.ActiveRole]
	if !ok {
		return nil, false, nil
	}
	if !role.Page {
		return nil, true, ErrNotAvailable
	}
	if !Served(p.ActiveRole) {
		return nil, false, nil
	}
	now := s.now()
	local := now.In(zone)
	r := &reader{p: p, role: p.ActiveRole, now: now, fy: schooldirectory.OperationalFY(now),
		today: time.Date(local.Year(), local.Month(), local.Day(), 0, 0, 0, 0, time.UTC)}
	for _, id := range []string{p.UserID, p.StaffProfileID} {
		if id != "" && !contains(r.owners, id) {
			r.owners = append(r.owners, id)
		}
	}
	scope, err := schooldirectory.ResolveScope(ctx, s.db, p, now)
	if err != nil {
		return nil, true, err
	}
	r.scope = scope
	var rows []todo
	for _, name := range role.Builders {
		got, err := Handled[name](ctx, s, r)
		switch {
		case errors.Is(err, errPassOn):
			return nil, false, nil
		case err != nil:
			return nil, true, fmt.Errorf("todos: %s: %w", name, err)
		}
		rows = append(rows, got...)
	}
	q, err := buildQueue(r.role, rows)
	if err != nil {
		return nil, true, err
	}
	return page(q), true, nil
}
