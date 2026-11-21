// Package workforceops implements native Go operational writes for Batch 13:
// /profile self-service updates, leave approvals/escalations, leadership
// escalation decisions, and Knowledge Center feedback.
package workforceops

import (
	"context"
	"errors"
	"strings"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"

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
}

func NewService(pool *pgxpool.Pool) *Service {
	return &Service{pool: pool}
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
		return tx.QueryRow(ctx,
			`SELECT gateway_workforce_ops.decide_leave($1,$2,$3,$4,$5)`,
			leaveID, decision, p.UserID, p.ActiveRole, strings.TrimSpace(note)).Scan(&out)
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
		return tx.QueryRow(ctx,
			`SELECT gateway_workforce_ops.decide_escalation($1,$2,$3,$4,$5)`,
			escalationID, strings.TrimSpace(decision), strings.TrimSpace(note), p.UserID, p.ActiveRole).Scan(&out)
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
