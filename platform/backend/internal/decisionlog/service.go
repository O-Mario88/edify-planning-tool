package decisionlog

import (
	"context"
	"fmt"
	"net/url"
	"time"

	"github.com/jackc/pgx/v5"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/closedschools"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pagegate"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// Path is the page this package answers.
const Path = "/decision-log"

// ErrNotAvailable is the page refused to the reader's role, which the
// existing feed answers as a page that is not there.
var ErrNotAvailable = pagegate.ErrNotAvailable

// Service builds the Decision Log.
type Service struct {
	db  schooldirectory.Querier
	now func() time.Time
}

// NewService wires the service to the database it reads.
func NewService(db schooldirectory.Querier, now func() time.Time) *Service {
	return &Service{db: db, now: now}
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
	switch member, err := PartnerTeamMember(ctx, s.db, p, rules.PartnerTeamMembers); {
	case err != nil:
		return nil, true, err
	case member == TeamMember:
		return nil, true, ErrNotAvailable
	case member == Undecided:
		return nil, false, nil
	}
	v := view{role: role, days: days(query.Get("days")), group: query.Get("group"), query: query}
	rows, err := s.decisions(ctx, p, role.Reach, v.days, v.group, query.Get("actor"))
	if err != nil {
		return nil, true, err
	}
	v.rows = rows
	return page(v), true, nil
}

// days is _int(query["days"], DEFAULT_DAYS): Python's int() of the value,
// held between one day and MAX_DAYS; anything else is the default.
func days(text string) int {
	n, ok := closedschools.PyInt(text)
	if text == "" || !ok {
		return rules.DefaultDays
	}
	return max(1, min(rules.MaxDays, n))
}

// actors is whose decisions a reader of the given reach reads, as the
// actor ids the rows are filtered on; nil is every actor.
func (s *Service) actors(ctx context.Context, p auth.Principal, reach Reach) ([]string, error) {
	switch reach {
	case reachGlobal:
		return nil, nil
	case reachCountry:
		// _country_filtered: the people whose live staff profile is in the
		// reader's country; the reader alone when no country is on file.
		var country string
		err := s.db.QueryRow(ctx, `
SELECT COALESCE(country, '') FROM staff_profile WHERE deleted_at IS NULL AND user_id = $1 ORDER BY id LIMIT 1`,
			p.UserID).Scan(&country)
		if err != nil && err != pgx.ErrNoRows {
			return nil, fmt.Errorf("decisionlog: reading the reader's country: %w", err)
		}
		if country == "" {
			return []string{p.UserID}, nil
		}
		rows, err := s.db.Query(ctx, `
SELECT user_id FROM staff_profile WHERE deleted_at IS NULL AND country = $1 AND user_id IS NOT NULL AND user_id <> ''`,
			country)
		if err != nil {
			return nil, fmt.Errorf("decisionlog: reading the country's people: %w", err)
		}
		ids, err := pgx.CollectRows(rows, pgx.RowTo[string])
		if err != nil {
			return nil, fmt.Errorf("decisionlog: reading the country's people: %w", err)
		}
		return append([]string{}, ids...), nil
	}
	return []string{p.UserID}, nil
}

// decisions are decision_log's rows: the decision actions (one group's, when
// a known group is asked for) of the lookback window, the reader's reach
// and, when one is asked for, one actor's; the latest first, up to the cap.
// They are read through gateway_read.decision_audit (decision_log_roles.sql),
// which shows the decision rows and only their subject keys: the gateway may
// not read the audit chain's payloads.
func (s *Service) decisions(ctx context.Context, p auth.Principal, reach Reach, lookback int, group, actor string) ([]decision, error) {
	actions := allActions()
	if only, ok := groupActions(group); ok {
		actions = only
	}
	args := []any{actions, s.now().Add(-time.Duration(lookback) * 24 * time.Hour)}
	where := "action = ANY($1) AND created_at >= $2"
	actors, err := s.actors(ctx, p, reach)
	if err != nil {
		return nil, err
	}
	if actors != nil {
		args = append(args, actors)
		where += fmt.Sprintf(" AND actor_id = ANY($%d)", len(args))
	}
	if actor != "" {
		args = append(args, actor)
		where += fmt.Sprintf(" AND actor_id = $%d", len(args))
	}
	rows, err := s.db.Query(ctx, fmt.Sprintf(`
SELECT action, actor_role, subject_id, reason, success, created_at, payload::text
FROM gateway_read.decision_audit WHERE %s ORDER BY created_at DESC LIMIT %d`, where, rules.RowLimit), args...)
	if err != nil {
		return nil, fmt.Errorf("decisionlog: reading the decisions: %w", err)
	}
	return pgx.CollectRows(rows, func(r pgx.CollectableRow) (decision, error) {
		var d decision
		var role, subject, reason, payload *string
		if err := r.Scan(&d.Action, &role, &subject, &reason, &d.Success, &d.At, &payload); err != nil {
			return d, err
		}
		d.ActorRole, d.SubjectID, d.Reason, d.Payload = deref(role), deref(subject), deref(reason), deref(payload)
		return d, nil
	})
}

func deref(s *string) string {
	if s == nil {
		return ""
	}
	return *s
}
