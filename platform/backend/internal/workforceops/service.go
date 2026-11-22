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
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/cuid"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/realtime"
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
	pool   *pgxpool.Pool
	now    func() time.Time
	broker *realtime.Broker
}

func NewService(pool *pgxpool.Pool) *Service {
	return &Service{pool: pool, now: time.Now}
}

// WithRealtime attaches the post-commit SSE broker for live workflow updates.
func (s *Service) WithRealtime(b *realtime.Broker) *Service {
	if s != nil {
		s.broker = b
	}
	return s
}

func countryOf(p auth.Principal) string {
	if p.Country != nil && strings.TrimSpace(p.Country.Code) != "" {
		return strings.ToUpper(strings.TrimSpace(p.Country.Code))
	}
	return "UG"
}

func (s *Service) publish(ev realtime.Event) {
	if s != nil && s.broker != nil {
		s.broker.Publish(ev)
	}
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
	if err == nil {
		s.publish(realtime.Event{
			Type:        "leave.decided",
			EntityType:  "leave",
			EntityID:    leaveID,
			CountryCode: countryOf(p),
			TargetRoles: []string{"Program Lead", "CountryDirector", "HumanResources", "Admin"},
			ActorUserID: p.UserID,
			Summary:     "Leave " + decision,
		})
	}
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
	if err == nil {
		s.publish(realtime.Event{
			Type:        "escalation.resolved",
			EntityType:  "leadership_escalation",
			EntityID:    escalationID,
			CountryCode: countryOf(p),
			TargetRoles: []string{"Program Lead", "CountryDirector", "RegionalVicePresident", "Admin"},
			ActorUserID: p.UserID,
			Summary:     "Escalation " + strings.TrimSpace(decision),
		})
	}
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

func isExternalOrNonStaffRole(role string) bool {
	switch role {
	case "", "ClusterLeader", "PartnerAdmin", "PartnerFieldOfficer", "MfiLoanOfficer", "MfiPartnerAdmin":
		return true
	default:
		return false
	}
}

// RaiseEscalation creates a leadership_escalation row natively in Go and
// appends a canonical SHA-256 audit row in the same transaction.
func (s *Service) RaiseEscalation(ctx context.Context, p auth.Principal, category, severity, subject, detail, requestedDecision, dueDate string) (string, error) {
	if p.UserID == "" || p.ActiveRole == "ClusterLeader" || p.ActiveRole == "MfiLoanOfficer" || p.ActiveRole == "MfiPartnerAdmin" {
		return "", ErrForbidden
	}
	subject = strings.TrimSpace(subject)
	detail = strings.TrimSpace(detail)
	if subject == "" || detail == "" {
		return "", fmt.Errorf("%w: subject and detail are required", ErrInvalidInput)
	}
	addressed := "PL"
	switch p.ActiveRole {
	case "Program Lead", "RegionalProgramLead":
		addressed = "CD"
	case "CountryDirector":
		addressed = "RVP"
	}
	var due *time.Time
	if raw := strings.TrimSpace(dueDate); raw != "" {
		parsed, err := time.Parse(time.DateOnly, raw)
		if err != nil {
			return "", fmt.Errorf("%w: due_date must be YYYY-MM-DD", ErrInvalidInput)
		}
		due = &parsed
	}
	countryID := "UG"
	if p.Country != nil && strings.TrimSpace(p.Country.Code) != "" {
		countryID = p.Country.Code
	}
	now := s.clock()
	id := cuid.New()
	var out string
	err := withRW(ctx, s.pool, func(tx pgx.Tx) error {
		if err := tx.QueryRow(ctx,
			`SELECT gateway_workforce_ops.raise_escalation($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)`,
			id, p.UserID, p.Name, countryID, addressed, category, severity, subject, detail, requestedDecision, due, now).Scan(&out); err != nil {
			return err
		}
		_, err := audit.Append(ctx, tx, audit.Entry{
			Action:      "escalation.raised",
			SubjectKind: audit.Text("leadership_escalation"),
			SubjectID:   audit.Text(out),
			ActorID:     audit.Text(p.UserID),
			ActorRole:   audit.Text(p.ActiveRole),
			Success:     true,
			Payload: map[string]any{
				"category":       strings.TrimSpace(category),
				"severity":       strings.TrimSpace(severity),
				"addressed_role": addressed,
				"subject":        subject,
			},
		}, now)
		return err
	})
	if err == nil {
		s.publish(realtime.Event{
			Type:        "escalation.raised",
			EntityType:  "leadership_escalation",
			EntityID:    out,
			CountryCode: countryID,
			TargetRoles: []string{"Program Lead", "CountryDirector", "RegionalVicePresident", "Admin"},
			ActorUserID: p.UserID,
			Summary:     subject,
		})
	}
	return out, err
}

// RequestLeave creates a pending leave request row natively in Go and appends
// a canonical SHA-256 audit row in the same transaction.
func (s *Service) RequestLeave(ctx context.Context, p auth.Principal, leaveType, startDate, endDate, reason, handover string) (string, error) {
	if p.UserID == "" || isExternalOrNonStaffRole(p.ActiveRole) {
		return "", ErrForbidden
	}
	leaveType = strings.TrimSpace(leaveType)
	if leaveType == "" {
		return "", fmt.Errorf("%w: leave_type is required", ErrInvalidInput)
	}
	startDate = strings.TrimSpace(startDate)
	endDate = strings.TrimSpace(endDate)
	sParsed, err := time.Parse(time.DateOnly, startDate)
	if err != nil {
		return "", fmt.Errorf("%w: start_date must be YYYY-MM-DD", ErrInvalidInput)
	}
	eParsed, err := time.Parse(time.DateOnly, endDate)
	if err != nil || eParsed.Before(sParsed) {
		return "", fmt.Errorf("%w: end_date must be on or after start_date", ErrInvalidInput)
	}
	days := int(eParsed.Sub(sParsed).Hours()/24) + 1
	if days > 365 {
		return "", fmt.Errorf("%w: leave duration cannot exceed 365 days", ErrInvalidInput)
	}
	now := s.clock()
	id := cuid.New()
	var out string
	err = withRW(ctx, s.pool, func(tx pgx.Tx) error {
		if err := tx.QueryRow(ctx,
			`SELECT gateway_workforce_ops.request_leave($1,$2,$3,$4,$5,$6,$7,$8,$9)`,
			id, p.UserID, leaveType, startDate, endDate, days, reason, handover, now).Scan(&out); err != nil {
			if strings.Contains(err.Error(), "workforceops: forbidden:") {
				return fmt.Errorf("%w: no staff profile found for this account", ErrForbidden)
			}
			return err
		}
		_, err := audit.Append(ctx, tx, audit.Entry{
			Action:      "leave.requested",
			SubjectKind: audit.Text("leave"),
			SubjectID:   audit.Text(out),
			ActorID:     audit.Text(p.UserID),
			ActorRole:   audit.Text(p.ActiveRole),
			Success:     true,
			Payload: map[string]any{
				"type":       strings.TrimSpace(leaveType),
				"start_date": startDate,
				"end_date":   endDate,
				"days":       days,
			},
		}, now)
		return err
	})
	if err == nil {
		s.publish(realtime.Event{
			Type:        "leave.requested",
			EntityType:  "leave",
			EntityID:    out,
			CountryCode: countryOf(p),
			TargetRoles: []string{"Program Lead", "CountryDirector", "HumanResources", "Admin"},
			ActorUserID: p.UserID,
			Summary:     fmt.Sprintf("%s (%d days)", leaveType, days),
		})
	}
	return out, err
}
