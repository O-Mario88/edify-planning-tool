package plreview

import (
	"context"
	"fmt"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/audit"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
)

// ReviewRefusal is a business-rule refusal on PL approve/return.
type ReviewRefusal struct {
	Message   string
	Forbidden bool
}

func (r *ReviewRefusal) Error() string { return r.Message }

// ReviewResult is the outcome of a PL approve or return decision.
type ReviewResult struct {
	ActivityID string
	Status     string
	Reason     string
}

// ReviewService performs Programme Lead completion approvals and returns
// natively in Go via gateway_pl_review.* without calling Django.
type ReviewService struct {
	pool *pgxpool.Pool
	now  func() time.Time
}

// NewReviewService builds a ReviewService over pool.
func NewReviewService(pool *pgxpool.Pool, now func() time.Time) *ReviewService {
	if now == nil {
		now = time.Now
	}
	return &ReviewService{pool: pool, now: now}
}

// canReviewRole is who may decide at all: the page holds Admin, Impact
// Assessment and the lead, and can_review_activity then refuses Impact
// Assessment, which verifies partner work elsewhere.
func canReviewRole(role string) bool {
	return role == rules.LeadRole || role == rules.AdminRole
}

type reviewTarget struct {
	schoolID, activityType, responsibleStaffID, status string
}

func (s *ReviewService) checkReviewable(ctx context.Context, tx pgx.Tx, p auth.Principal, activityID string) (reviewTarget, error) {
	if !canReviewRole(p.ActiveRole) {
		return reviewTarget{}, &ReviewRefusal{
			Message:   "Access Denied: You do not supervise the owner of this activity.",
			Forbidden: true,
		}
	}
	review, err := Reviewable(ctx, tx, p, activityID, s.now())
	if err != nil {
		return reviewTarget{}, err
	}
	return reviewTarget{
		schoolID:           review.SchoolID,
		activityType:       review.ActivityType,
		responsibleStaffID: review.ResponsibleStaffID,
		status:             review.Status,
	}, nil
}

// Approve confirms a submitted completion as ia_verified (apps.pl_review.services.confirm).
func (s *ReviewService) Approve(ctx context.Context, p auth.Principal, activityID string) (ReviewResult, error) {
	if strings.TrimSpace(activityID) == "" {
		return ReviewResult{}, &ReviewRefusal{Message: "Activity is required."}
	}
	now := s.now().UTC()
	tx, err := s.pool.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite})
	if err != nil {
		return ReviewResult{}, fmt.Errorf("plreview: starting approve tx: %w", err)
	}
	defer func() { _ = tx.Rollback(ctx) }()

	target, err := s.checkReviewable(ctx, tx, p, activityID)
	if err != nil {
		return ReviewResult{}, err
	}
	var verdict string
	if err := tx.QueryRow(ctx, `SELECT gateway_pl_review.approve_completion($1, $2, $3)`,
		activityID, p.UserID, now).Scan(&verdict); err != nil {
		return ReviewResult{}, fmt.Errorf("plreview: approve_completion: %w", err)
	}
	switch verdict {
	case "":
	case "no_sfid":
		return ReviewResult{}, &ReviewRefusal{
			Message: "This completion has no Salesforce ID. Return it to the officer to enter the ID; it cannot be verified without one.",
		}
	case "changed":
		return ReviewResult{}, &ReviewRefusal{
			Message: "This completion is no longer waiting for Programme Lead review.",
		}
	default:
		return ReviewResult{}, fmt.Errorf("plreview: unexpected approve verdict %q", verdict)
	}
	if _, err := audit.Append(ctx, tx, audit.Entry{
		Action:      "pl_review_confirm",
		SubjectKind: audit.Text("Activity"),
		SubjectID:   audit.Text(activityID),
		ActorID:     audit.Text(p.UserID),
		ActorRole:   audit.Text(p.ActiveRole),
		Payload: map[string]any{
			"schoolId":           target.schoolID,
			"activityType":       target.activityType,
			"responsibleStaffId": target.responsibleStaffID,
			"status":             "ia_verified",
		},
	}, now); err != nil {
		return ReviewResult{}, fmt.Errorf("plreview: appending approve audit: %w", err)
	}
	if err := tx.Commit(ctx); err != nil {
		return ReviewResult{}, fmt.Errorf("plreview: committing approve: %w", err)
	}
	return ReviewResult{ActivityID: activityID, Status: "ia_verified"}, nil
}

// Return sends a submitted completion back to the officer with a required note
// (apps.pl_review.services.return_activity).
func (s *ReviewService) Return(ctx context.Context, p auth.Principal, activityID, reason string) (ReviewResult, error) {
	trimmed := strings.TrimSpace(reason)
	if trimmed == "" {
		return ReviewResult{}, &ReviewRefusal{
			Message: "Say what needs correcting before returning a completion.",
		}
	}
	if strings.TrimSpace(activityID) == "" {
		return ReviewResult{}, &ReviewRefusal{Message: "Activity is required."}
	}
	now := s.now().UTC()
	tx, err := s.pool.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite})
	if err != nil {
		return ReviewResult{}, fmt.Errorf("plreview: starting return tx: %w", err)
	}
	defer func() { _ = tx.Rollback(ctx) }()

	target, err := s.checkReviewable(ctx, tx, p, activityID)
	if err != nil {
		return ReviewResult{}, err
	}
	var verdict string
	if err := tx.QueryRow(ctx, `SELECT gateway_pl_review.return_completion($1, $2, $3, $4)`,
		activityID, p.UserID, trimmed, now).Scan(&verdict); err != nil {
		return ReviewResult{}, fmt.Errorf("plreview: return_completion: %w", err)
	}
	switch verdict {
	case "":
	case "no_reason":
		return ReviewResult{}, &ReviewRefusal{
			Message: "Say what needs correcting before returning a completion.",
		}
	case "changed":
		return ReviewResult{}, &ReviewRefusal{
			Message: "This completion is no longer waiting for Programme Lead review.",
		}
	default:
		return ReviewResult{}, fmt.Errorf("plreview: unexpected return verdict %q", verdict)
	}
	if _, err := audit.Append(ctx, tx, audit.Entry{
		Action:      "pl_review_return",
		SubjectKind: audit.Text("Activity"),
		SubjectID:   audit.Text(activityID),
		ActorID:     audit.Text(p.UserID),
		ActorRole:   audit.Text(p.ActiveRole),
		Reason:      audit.Text(trimmed),
		Payload: map[string]any{
			"schoolId":           target.schoolID,
			"activityType":       target.activityType,
			"responsibleStaffId": target.responsibleStaffID,
			"status":             "returned_by_pl",
		},
	}, now); err != nil {
		return ReviewResult{}, fmt.Errorf("plreview: appending return audit: %w", err)
	}
	if err := tx.Commit(ctx); err != nil {
		return ReviewResult{}, fmt.Errorf("plreview: committing return: %w", err)
	}
	return ReviewResult{ActivityID: activityID, Status: "returned_by_pl", Reason: trimmed}, nil
}
