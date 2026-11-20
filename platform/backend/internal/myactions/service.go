package myactions

import (
	"context"
	"fmt"
	"net/url"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/closedschools"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/decisionlog"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pagegate"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// Path is My Actions; SentPath is Actions Sent, the same rows read from the
// sender's end (actions_sent).
const (
	Path     = "/actions/mine"
	SentPath = "/actions/sent"
)

// side is one end of the rows: whose they are, whose name each row leads
// with, and the page's gates and words.
type side struct {
	path         string
	reader       string // the column that is the reader's: recipient_id or sender_id
	counterparty string // the column whose name the row shows
	sender       bool   // perspective == "sender"
	roles        map[string]Role
	team         decisionlog.PartnerTeam
	limit        int
	title, intro string
	empty        string
	column       string // the counterparty's column heading
}

var sides = map[string]side{
	Path: {path: Path, reader: "recipient_id", counterparty: "sender_id", roles: rules.Roles, team: rules.PartnerTeamMembers,
		limit: rules.RowLimit, title: "My Actions",
		intro:  "School issues assigned to you. These close automatically once the record shows the work is complete.",
		empty:  "Nothing has been assigned to you.",
		column: "Sent by"},
	SentPath: {path: SentPath, reader: "sender_id", counterparty: "recipient_id", sender: true, roles: rules.SentRoles,
		team: rules.SentPartnerTeamMembers, limit: rules.SentRowLimit, title: "Actions Sent",
		intro: "School issues you have assigned. Each one leaves the urgent list when it is sent and closes here when the " +
			"record shows the work is done.",
		empty:  "You have not sent any school actions yet.",
		column: "Assigned to"},
}

// ErrNotAvailable is the page refused to the reader's role, which the
// existing feed answers as a page that is not there.
var ErrNotAvailable = pagegate.ErrNotAvailable

// Service builds My Actions.
type Service struct {
	db  schooldirectory.Querier
	now func() time.Time
}

// NewService wires the service to the database it reads.
func NewService(db schooldirectory.Querier, now func() time.Time) *Service {
	return &Service{db: db, now: now}
}

// action is one team_action row with the names the row shows.
type action struct {
	SchoolPK, IssueType, RequestedAction, Route, State, ReturnedReason string
	CounterpartyID                                                     string
	DueDate                                                            *time.Time
	ResolvedBySystem                                                   bool
	// Read beside it.
	School, District, Counterparty string
	// SchoolCode is the live school's School ID, as the web's middleware
	// fills it in.
	SchoolCode string
}

// counts are _counts over everything handed to the reader.
type counts struct {
	Total, Open, Overdue, Resolved, AutoResolved int
}

// Build answers path for p with the page's query. served is false for a
// path this package does not answer.
func (s *Service) Build(ctx context.Context, p auth.Principal, path string, query url.Values) (*screensv1.GetPageResponse, bool, error) {
	sd, ok := sides[path]
	if !ok {
		return nil, false, nil
	}
	role, ok := sd.roles[p.ActiveRole]
	if !ok || !role.Page {
		return nil, true, ErrNotAvailable
	}
	// A partner's team member is refused the page (member_scope.page_withheld).
	switch member, err := decisionlog.PartnerTeamMember(ctx, s.db, p, sd.team); {
	case err != nil:
		return nil, true, err
	case member == decisionlog.TeamMember:
		return nil, true, ErrNotAvailable
	case member == decisionlog.Undecided:
		return nil, false, nil
	}
	tab := closedschools.StripSpace(query.Get("tab"))
	if tab == "" {
		tab = "open"
	}
	c, err := s.counts(ctx, sd, p.UserID)
	if err != nil {
		return nil, true, err
	}
	rows, err := s.actions(ctx, sd, p.UserID, tab)
	if err != nil {
		return nil, true, err
	}
	today := s.now().In(zone)
	return page(view{side: sd, role: role, counts: c, rows: rows, query: query,
		today: time.Date(today.Year(), today.Month(), today.Day(), 0, 0, 0, 0, time.UTC)}), true, nil
}

func (s *Service) counts(ctx context.Context, sd side, userID string) (counts, error) {
	var c counts
	err := s.db.QueryRow(ctx, `
SELECT COUNT(*),
  COUNT(*) FILTER (WHERE state = ANY($2) AND state <> $3),
  COUNT(*) FILTER (WHERE state = ANY($4)),
  COUNT(*) FILTER (WHERE state = $5),
  COUNT(*) FILTER (WHERE state = $5 AND resolved_by_system)
FROM team_action WHERE `+sd.reader+` = $1`,
		userID, rules.ActiveStates, rules.OverdueState, []string{rules.OverdueState, rules.EscalatedState}, rules.ResolvedState,
	).Scan(&c.Total, &c.Open, &c.Overdue, &c.Resolved, &c.AutoResolved)
	if err != nil {
		return c, fmt.Errorf("myactions: counting the actions: %w", err)
	}
	return c, nil
}

// tabFilter is _apply_tab: Open is the active work less the overdue, Overdue
// the overdue and escalated, Resolved the resolved; anything else is all.
func tabFilter(tab string, args *[]any) string {
	arg := func(v any) string {
		*args = append(*args, v)
		return fmt.Sprintf("$%d", len(*args))
	}
	switch tab {
	case "open":
		return " AND state = ANY(" + arg(rules.ActiveStates) + ") AND state <> " + arg(rules.OverdueState)
	case "overdue":
		return " AND state = ANY(" + arg([]string{rules.OverdueState, rules.EscalatedState}) + ")"
	case "resolved":
		return " AND state = " + arg(rules.ResolvedState)
	}
	return ""
}

// actions is actions_received's (or actions_sent's) rows: the tab's, soonest
// due first (no date last), the newest first among equals, up to the queue's
// limit; with the other party's names and the schools' names and districts.
func (s *Service) actions(ctx context.Context, sd side, userID, tab string) ([]action, error) {
	args := []any{userID}
	where := sd.reader + " = $1" + tabFilter(tab, &args)
	rows, err := s.db.Query(ctx, fmt.Sprintf(`
SELECT school_id, issue_type, requested_action, workflow_route, state, returned_reason, %s, due_date, resolved_by_system
FROM team_action WHERE %s ORDER BY due_date ASC, created_at DESC LIMIT %d`, sd.counterparty, where, sd.limit), args...)
	if err != nil {
		return nil, fmt.Errorf("myactions: reading the actions: %w", err)
	}
	list, err := pgx.CollectRows(rows, func(r pgx.CollectableRow) (action, error) {
		var a action
		err := r.Scan(&a.SchoolPK, &a.IssueType, &a.RequestedAction, &a.Route, &a.State, &a.ReturnedReason, &a.CounterpartyID,
			&a.DueDate, &a.ResolvedBySystem)
		return a, err
	})
	if err != nil || len(list) == 0 {
		if err != nil {
			err = fmt.Errorf("myactions: reading the actions: %w", err)
		}
		return list, err
	}
	senders, schools := []string{}, []string{}
	for _, a := range list {
		senders, schools = append(senders, a.CounterpartyID), append(schools, a.SchoolPK)
	}
	names, err := s.names(ctx, senders)
	if err != nil {
		return nil, err
	}
	places, err := s.schools(ctx, schools)
	if err != nil {
		return nil, err
	}
	for i := range list {
		a := &list[i]
		a.Counterparty = names[a.CounterpartyID]
		place := places[a.SchoolPK]
		a.School, a.District, a.SchoolCode = place[0], place[1], place[2]
	}
	return list, nil
}

// names are the people's names by id (every account, as User.objects reads
// them).
func (s *Service) names(ctx context.Context, ids []string) (map[string]string, error) {
	rows, err := s.db.Query(ctx, `SELECT id, COALESCE(name, '') FROM "user" WHERE id = ANY($1)`, ids)
	if err != nil {
		return nil, fmt.Errorf("myactions: reading the names: %w", err)
	}
	defer rows.Close()
	out := map[string]string{}
	for rows.Next() {
		var id, name string
		if err := rows.Scan(&id, &name); err != nil {
			return nil, err
		}
		out[id] = name
	}
	return out, rows.Err()
}

// schools are the live schools' names and districts, and every named
// school's School ID, by record id.
func (s *Service) schools(ctx context.Context, ids []string) (map[string][3]string, error) {
	rows, err := s.db.Query(ctx, `
SELECT s.id, COALESCE(s.name, ''), COALESCE(d.name, ''), COALESCE(s.school_id, ''), s.deleted_at IS NULL
FROM school s LEFT OUTER JOIN district d ON d.id = s.district_id
WHERE s.id = ANY($1)`, ids)
	if err != nil {
		return nil, fmt.Errorf("myactions: reading the schools: %w", err)
	}
	defer rows.Close()
	out := map[string][3]string{}
	for rows.Next() {
		var id, name, district, code string
		var live bool
		if err := rows.Scan(&id, &name, &district, &code, &live); err != nil {
			return nil, err
		}
		if !live {
			// The web names a deleted school by neither name nor ID.
			name, district, code = "", "", ""
		}
		out[id] = [3]string{name, district, code}
	}
	return out, rows.Err()
}

// pyTitle is str.title(): each run of letters with its first in capitals
// and the rest in lower case.
func pyTitle(s string) string {
	var b strings.Builder
	previousCased := false
	for _, r := range s {
		cased := strings.ToUpper(string(r)) != strings.ToLower(string(r))
		switch {
		case cased && !previousCased:
			b.WriteString(strings.ToTitle(string(r)))
		case cased:
			b.WriteString(strings.ToLower(string(r)))
		default:
			b.WriteRune(r)
		}
		previousCased = cased
	}
	return b.String()
}
