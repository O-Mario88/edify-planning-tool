// Package workforceops implements native Go operational writes for Batch 13:
// /profile self-service updates, leave approvals/escalations, leadership
// escalation decisions, and Knowledge Center feedback.
package workforceops

import (
	"context"
	"errors"
	"fmt"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/audit"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
)

func withRW(ctx context.Context, pool *pgxpool.Pool, fn func(pgx.Tx) error) error {
	tx, err := pool.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite})
	if err != nil {
		return err
	}
	defer func() { _ = tx.Rollback(ctx) }()
	if err := fn(tx); err != nil {
		return err
	}
	return tx.Commit(ctx)
}

var (
	ErrForbidden    = errors.New("workforceops: actor is not permitted")
	ErrInvalidInput = errors.New("workforceops: invalid input")
)

type Service struct {
	pool *pgxpool.Pool
	now  func() time.Time
}

func NewService(pool *pgxpool.Pool) *Service {
	return &Service{pool: pool, now: time.Now}
}

// WithClock overrides the clock used for audit timestamps (useful in tests).
func (s *Service) WithClock(fn func() time.Time) *Service {
	if s != nil && fn != nil {
		s.now = fn
	}
	return s
}

func (s *Service) clock() time.Time {
	if s != nil && s.now != nil {
		return s.now().UTC()
	}
	return time.Now().UTC()
}

func (s *Service) UpdateOwnProfile(ctx context.Context, p auth.Principal, name, phone string) error {
	if p.UserID == "" {
		return ErrForbidden
	}
	return withRW(ctx, s.pool, func(tx pgx.Tx) error {
		_, err := tx.Exec(ctx,
			`SELECT gateway_workforce_ops.update_own_profile($1,$2,$3)`,
			p.UserID, strings.TrimSpace(name), strings.TrimSpace(phone))
		return err
	})
}

func (s *Service) DecideLeave(ctx context.Context, p auth.Principal, leaveID, decision, note string) (string, error) {
	if p.ActiveRole != "Program Lead" && p.ActiveRole != "CountryDirector" && p.ActiveRole != "HumanResources" && p.ActiveRole != "Admin" {
		return "", ErrForbidden
	}
	if decision != "approved" && decision != "rejected" && decision != "hr_review" {
		return "", ErrInvalidInput
	}
	var out string
	err := withRW(ctx, s.pool, func(tx pgx.Tx) error {
		if err := tx.QueryRow(ctx,
			`SELECT gateway_workforce_ops.decide_leave($1,$2,$3,$4,$5)`,
			leaveID, decision, p.UserID, p.ActiveRole, strings.TrimSpace(note)).Scan(&out); err != nil {
			return err
		}
		_, err := audit.Append(ctx, tx, audit.Entry{
			Action:      "leave." + decision,
			SubjectKind: audit.Text("leave"),
			SubjectID:   audit.Text(leaveID),
			ActorID:     audit.Text(p.UserID),
			ActorRole:   audit.Text(p.ActiveRole),
			Success:     true,
			Payload: map[string]any{
				"new_status": out,
				"note":       strings.TrimSpace(note),
			},
		}, s.clock())
		return err
	})
	return out, err
}

func (s *Service) DecideEscalation(ctx context.Context, p auth.Principal, escalationID, decision, note string) (string, error) {
	if p.ActiveRole != "Program Lead" && p.ActiveRole != "CountryDirector" && p.ActiveRole != "RegionalVicePresident" && p.ActiveRole != "Admin" {
		return "", ErrForbidden
	}
	if strings.TrimSpace(decision) == "" {
		return "", ErrInvalidInput
	}
	var out string
	err := withRW(ctx, s.pool, func(tx pgx.Tx) error {
		if err := tx.QueryRow(ctx,
			`SELECT gateway_workforce_ops.decide_escalation($1,$2,$3,$4,$5)`,
			escalationID, strings.TrimSpace(decision), strings.TrimSpace(note), p.UserID, p.ActiveRole).Scan(&out); err != nil {
			return err
		}
		_, err := audit.Append(ctx, tx, audit.Entry{
			Action:      "escalation.resolved",
			SubjectKind: audit.Text("leadership_escalation"),
			SubjectID:   audit.Text(escalationID),
			ActorID:     audit.Text(p.UserID),
			ActorRole:   audit.Text(p.ActiveRole),
			Success:     true,
			Payload: map[string]any{
				"decision": strings.TrimSpace(decision),
				"note":     strings.TrimSpace(note),
			},
		}, s.clock())
		return err
	})
	return out, err
}

func (s *Service) RecordHelpFeedback(ctx context.Context, p auth.Principal, articleID string, helpful bool, feedbackType, comment, pageContext string) (string, error) {
	if p.UserID == "" || strings.TrimSpace(articleID) == "" {
		return "", ErrInvalidInput
	}
	var id string
	err := withRW(ctx, s.pool, func(tx pgx.Tx) error {
		return tx.QueryRow(ctx,
			`SELECT gateway_workforce_ops.record_help_feedback($1,$2,$3,$4,$5,$6,$7)`,
			articleID, p.UserID, p.ActiveRole, helpful, feedbackType, comment, pageContext).Scan(&id)
	})
	return id, err
}

// TransitionTeamAction applies a lifecycle transition to a team_action row
// (acknowledge, start, block, return, cancel, escalate, resolve) and appends
// a canonical SHA-256 audit row in the same transaction.
func (s *Service) TransitionTeamAction(ctx context.Context, p auth.Principal, actionID, transition, reason string) (string, error) {
	if p.UserID == "" || p.ActiveRole == "ClusterLeader" {
		return "", ErrForbidden
	}
	actionID = strings.TrimSpace(actionID)
	transition = strings.TrimSpace(transition)
	reason = strings.TrimSpace(reason)
	if actionID == "" || transition == "" {
		return "", ErrInvalidInput
	}
	now := s.clock()
	var state string
	err := withRW(ctx, s.pool, func(tx pgx.Tx) error {
		if err := tx.QueryRow(ctx,
			`SELECT gateway_workforce_ops.transition_team_action($1,$2,$3,$4,$5,$6)`,
			actionID, transition, p.UserID, p.ActiveRole, reason, now).Scan(&state); err != nil {
			msg := err.Error()
			switch {
			case strings.Contains(msg, "workforceops: forbidden:"):
				return fmt.Errorf("%w: %s", ErrForbidden, strings.TrimSpace(strings.SplitN(msg, "workforceops: forbidden:", 2)[1]))
			case strings.Contains(msg, "workforceops: invalid:"):
				return fmt.Errorf("%w: %s", ErrInvalidInput, strings.TrimSpace(strings.SplitN(msg, "workforceops: invalid:", 2)[1]))
			default:
				return err
			}
		}
		_, err := audit.Append(ctx, tx, audit.Entry{
			Action:      "team_action." + transition,
			SubjectKind: audit.Text("team_action"),
			SubjectID:   audit.Text(actionID),
			ActorID:     audit.Text(p.UserID),
			ActorRole:   audit.Text(p.ActiveRole),
			Success:     true,
			Payload: map[string]any{
				"transition": transition,
				"state":      state,
				"reason":     reason,
			},
		}, now)
		return err
	})
	return state, err
}
