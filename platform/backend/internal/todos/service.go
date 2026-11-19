package todos

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
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
// passed on, whatever the builders it reaches. The Accountant's, HR's, the
// two lending roles' and the two partner roles' were compared with the
// existing queue over the demo seed (internal/home/testdata/golden.py); the
// lending and partner roles' builders pass every such reader on (their
// loan and partner work is not built in Go). The Regional Lead's CCE rows
// are not built (regionalEngagementGuard), and the Cluster Leader has no
// account in the seed to compare: both stay the existing application's.
// The RVP's were compared over a General Budget and an Annual Budget filed
// for them.
var PortedRoles = []string{"CCEO", leadRole, roleIA, adminRole, coordinatorRole, btRole,
	"Accountant", "HumanResources", "MfiLoanOfficer", "MfiPartnerAdmin", "PartnerAdmin", "PartnerFieldOfficer",
	rvpRole}

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
	// The desktop page differs from the phone's (its own header and the
	// parts marked mobile-home-hide), which Go does not build yet: a desktop
	// reading is the existing page's (pagegate.Desktop).
	if pagegate.Desktop(ctx) {
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
	q, served, err := s.readQueue(ctx, p)
	if !served || err != nil {
		return nil, served, err
	}
	return page(q), true, nil
}

// readQueue is get_todos for p: the reader's rows, sorted and counted.
// served is false for a reader whose queue needs what Go does not build.
func (s *Service) readQueue(ctx context.Context, p auth.Principal) (queue, bool, error) {
	now := s.now()
	local := now.In(zone)
	r := &reader{p: p, role: p.ActiveRole, now: now, fy: readerYear(now),
		today: time.Date(local.Year(), local.Month(), local.Day(), 0, 0, 0, 0, time.UTC)}
	for _, id := range []string{p.UserID, p.StaffProfileID} {
		if id != "" && !contains(r.owners, id) {
			r.owners = append(r.owners, id)
		}
	}
	scope, err := schooldirectory.ResolveScope(ctx, s.db, p, now)
	if err != nil {
		return queue{}, true, err
	}
	r.scope = scope
	rows, served, err := collect(ctx, s, r, rules.Roles[p.ActiveRole].Builders)
	if !served || err != nil {
		return queue{}, served, err
	}
	q, err := buildQueue(r.role, rows)
	if err != nil {
		return queue{}, true, err
	}
	return q, true, nil
}

// Row is one To-Do as Home's Priority actions read it (home_service._todo_row).
type Row struct {
	Title, Description, Category, Priority string
	StatusKey, StatusLabel, StatusTone     string
	DueLabel, DueTone                      string
	Linked, ActionLabel, ActionURL         string
}

// Queue is the reader's queue as Home reads it (get_cached_todos): the rows
// in the queue's order, and the same rows as group_identical's entries; the
// rows waiting on the reader, due today and critical; and how many rows it
// holds.
type Queue struct {
	Rows    []Row
	Entries []Entry
	Counts  map[string]int
	Total   int
}

// Entry is one of group_identical's entries: a row on its own, or the
// identical rows standing where the first of them stood.
type Entry struct {
	Rows  []Row
	Group bool
}

// ContextLine is todo_groups.context_line: a row's second line without the
// place when its title already names it.
func ContextLine(title, linked string) string { return contextLine(title, linked) }

// HomeQueue is the reader's queue for Home. served is false where the
// existing application answers the queue: a role Go has not ported, a
// builder it does not have, an acting appointment.
func (s *Service) HomeQueue(ctx context.Context, p auth.Principal) (Queue, bool, error) {
	role, ok := rules.Roles[p.ActiveRole]
	if !ok || !role.Page || !Served(p.ActiveRole) || p.InActingAppointment {
		return Queue{}, false, nil
	}
	q, served, err := s.readQueue(ctx, p)
	if !served || err != nil {
		return Queue{}, served, err
	}
	out := Queue{Rows: make([]Row, len(q.Rows)), Total: q.Total,
		Counts: map[string]int{"waiting_me": q.WaitingMe, "due_today": q.DueToday, "critical": q.Critical}}
	for i, t := range q.Rows {
		out.Rows[i] = rowOf(t)
	}
	for _, e := range groupIdentical(q.Rows) {
		rows := make([]Row, len(e.rows))
		for i, t := range e.rows {
			rows[i] = rowOf(t)
		}
		out.Entries = append(out.Entries, Entry{Rows: rows, Group: e.group})
	}
	return out, true, nil
}

func rowOf(t todo) Row {
	return Row{Title: t.Title, Description: t.Description, Category: t.Category, Priority: t.Priority,
		StatusKey: t.StatusKey, StatusLabel: t.StatusLabel, StatusTone: t.StatusTone,
		DueLabel: t.DueLabel, DueTone: t.DueTone, Linked: t.Linked, ActionLabel: t.ActionLabel, ActionURL: t.ActionURL}
}

// QueueCounts are Home's To-Do figures (home_service.build_home_todo_figures
// over get_cached_todos), from HomeQueue.
func (s *Service) QueueCounts(ctx context.Context, p auth.Principal) (counts map[string]int, total int, served bool, err error) {
	q, served, err := s.HomeQueue(ctx, p)
	return q.Counts, q.Total, served, err
}

// collect runs the reader's builders in order. A builder that needs what Go
// has not ported passes the reader on. So does one that fails: the existing
// queue skips a failing builder and still shows the page, which Go cannot
// copy row for row, so the existing application answers instead. A request
// that was cancelled or timed out is still an error.
func collect(ctx context.Context, s *Service, r *reader, names []string) ([]todo, bool, error) {
	var rows []todo
	for _, name := range names {
		got, err := Handled[name](ctx, s, r)
		switch {
		case errors.Is(err, errPassOn):
			return nil, false, nil
		case err != nil && ctx.Err() != nil:
			return nil, true, fmt.Errorf("todos: %s: %w", name, err)
		case err != nil:
			slog.WarnContext(ctx, "todos: a builder failed; the existing application answers", "builder", name, "error", err)
			return nil, false, nil
		}
		rows = append(rows, got...)
	}
	return rows, true, nil
}

// localDate is a moment's day in Kampala, at midnight UTC as the builders
// hold days. The existing builders sometimes take the UTC day instead, which
// is a day behind from 21:00 UTC; Go takes Kampala's (owner, 2026-11-13:
// "Can you fix those from the go side").
func localDate(t time.Time) time.Time {
	local := t.In(zone)
	return time.Date(local.Year(), local.Month(), local.Day(), 0, 0, 0, 0, time.UTC)
}

// readerYear is the operational year of Kampala's day. The existing queue
// reads get_operational_fy() on the UTC day, a year behind from 21:00 UTC on
// 30 September.
func readerYear(now time.Time) string {
	return schooldirectory.OperationalFY(localDate(now))
}
