package plreview

// The hand_in_entered_work job (apps.pl_review.handed_in.hand_in_entered_work
// with apply): staff work a Programme Lead verifies that holds its Salesforce
// ID but was never handed in goes to the lead as Submit sends it, and a
// lead's own is approved as it is handed in (approve_on_hand_in). Each piece
// of work commits on its own, as the existing job does.

import (
	"context"
	"errors"
	"fmt"
	"slices"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/activities"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/cuid"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

const autoApproveReason = "A Programme Lead's own work is approved when it is handed in."

// notHandedInStatuses are NOT_HANDED_IN_STATUSES.
var notHandedInStatuses = []string{"scheduled", "rescheduled", "in_progress", "completion_started",
	"evidence_uploaded", "evidence_accepted", "salesforce_id_required", "completed"}

var leadReviewableStatuses = []string{statusSubmittedToPL, statusAwaitingIA}

// handInCandidate is one row of _candidates.
type handInCandidate struct{ id, status string }

// HandInEnteredWork says how many pieces of work it handed in, as the
// existing job counts them. Work whose save would also move a Core package
// in a way Go does not yet write is left and named in the error.
func (s *ReviewService) HandInEnteredWork(ctx context.Context, kampala *time.Location) (int, error) {
	candidates, err := s.handInCandidates(ctx)
	if err != nil {
		return 0, err
	}
	done := 0
	var handedOn []string
	for _, c := range candidates {
		lead, err := programmeLeadOwner(ctx, s.pool, c.id)
		if err != nil {
			return done, err
		}
		if slices.Contains(leadReviewableStatuses, c.status) && lead == "" {
			continue // a CCEO's, already with the lead
		}
		final := statusSubmittedToPL
		if lead != "" {
			final = statusVerified
		}
		left, err := activities.SlotMirrorHandedOn(ctx, s.pool, c.id, final)
		if err != nil {
			return done, err
		}
		if left {
			handedOn = append(handedOn, c.id)
			continue
		}
		done++
		status, err := s.handIn(ctx, c, kampala)
		if err != nil {
			return done, err
		}
		if lead != "" && slices.Contains(leadReviewableStatuses, status) {
			if err := s.approveOnHandIn(ctx, c.id, lead, kampala); err != nil {
				return done, err
			}
		}
	}
	if len(handedOn) > 0 {
		return done, fmt.Errorf("plreview: %d piece(s) of work left for the existing application, whose package side Go does not write: %s",
			len(handedOn), strings.Join(handedOn, ", "))
	}
	return done, nil
}

// handInCandidates is _candidates(): lead-verified staff work holding its
// Salesforce ID, not awaiting its In-school Training, not handed in or with
// the lead, by planned day.
func (s *ReviewService) handInCandidates(ctx context.Context) ([]handInCandidate, error) {
	rows, err := s.pool.Query(ctx, `
WITH lead_verified AS (
  SELECT sp.id, sp.user_id FROM staff_profile sp LEFT JOIN "user" u ON u.id = sp.user_id WHERE `+leadVerifiedStaff+`)
SELECT a.id, a.status FROM activity a
WHERE a.deleted_at IS NULL AND a.delivery_type IS DISTINCT FROM 'partner'
  AND (a.responsible_staff_id IN (SELECT id FROM lead_verified) OR a.responsible_staff_id IN (SELECT user_id FROM lead_verified))
  AND COALESCE(a.salesforce_activity_id, '') <> ''
  AND NOT (COALESCE(a.purpose_type, '') IN ('in_school_training', 'in_school_training_ssa')
           AND a.activity_type IS DISTINCT FROM 'in_school_training'
           AND NOT EXISTS (SELECT 1 FROM activity t WHERE t.paired_school_visit_id = a.id))
  AND (a.status = ANY($3) OR a.status = ANY($4))
ORDER BY a.planned_date, a.id`, rules.LeadVerifiedRoles, rules.LeadRole, notHandedInStatuses, leadReviewableStatuses)
	if err != nil {
		return nil, fmt.Errorf("plreview: reading the work to hand in: %w", err)
	}
	return pgx.CollectRows(rows, func(row pgx.CollectableRow) (handInCandidate, error) {
		var c handInCandidate
		err := row.Scan(&c.id, &c.status)
		return c, err
	})
}

// programmeLeadOwner is programme_lead_owner: the lead's user id when this is
// a Programme Lead's own staff work, read from the role the owner holds.
func programmeLeadOwner(ctx context.Context, q schooldirectory.Querier, activityID string) (string, error) {
	var lead string
	err := q.QueryRow(ctx, `SELECT COALESCE((SELECT sp.user_id FROM staff_profile sp JOIN "user" u ON u.id = sp.user_id
  WHERE (sp.id = a.responsible_staff_id OR sp.user_id = a.responsible_staff_id) AND sp.deleted_at IS NULL
    AND u.roles @> ARRAY[$2::varchar] LIMIT 1), '')
FROM activity a WHERE a.id = $1 AND COALESCE(a.responsible_staff_id, '') <> '' AND a.delivery_type IS DISTINCT FROM 'partner'`,
		activityID, rules.LeadRole).Scan(&lead)
	if errors.Is(err, pgx.ErrNoRows) {
		return "", nil
	}
	if err != nil {
		return "", fmt.Errorf("plreview: reading whether the work is a lead's own: %w", err)
	}
	return lead, nil
}

// handIn is _hand_in and the save around it: the work's status, its
// completion record, its package slots and its ledger mark. It says the
// work's status afterwards.
func (s *ReviewService) handIn(ctx context.Context, c handInCandidate, kampala *time.Location) (string, error) {
	if slices.Contains(leadReviewableStatuses, c.status) {
		return c.status, nil
	}
	now := s.now().UTC().Truncate(time.Microsecond)
	status := c.status
	err := s.inTransaction(ctx, func(tx pgx.Tx) error {
		var moved bool
		if err := tx.QueryRow(ctx, `SELECT gateway_pl_review.hand_in_entered($1, $2, $3)`, c.id, cuid.New(), now).
			Scan(&moved); err != nil {
			return fmt.Errorf("plreview: handing the work in: %w", err)
		}
		if !moved {
			return nil
		}
		status = statusSubmittedToPL
		return afterWorkSaved(ctx, tx, c.id, nil, kampala, now)
	})
	return status, err
}

// afterWorkSaved is what Activity.save does beside the row for this work:
// the package slots it fills and the owner's ledger mark, with any marks the
// save's own steps found.
func afterWorkSaved(ctx context.Context, tx pgx.Tx, activityID string, marks []ledgerMark, kampala *time.Location, now time.Time) error {
	if err := activities.MirrorSlots(ctx, tx, activityID, kampala, now); err != nil {
		return err
	}
	review, _, err := readReview(ctx, tx, activityID)
	if err != nil {
		return err
	}
	if mark, ok := workMark(review); ok {
		marks = append(slices.Clone(marks), mark)
	}
	for _, mark := range marks {
		if _, err := tx.Exec(ctx, `SELECT gateway_pl_review.mark_ledger($1, $2, $3)`, mark.owner, mark.fy, now); err != nil {
			return fmt.Errorf("plreview: marking the ledger: %w", err)
		}
	}
	return nil
}

// approveOnHandIn is approve_on_hand_in: the lead's own work approved by the
// writer the lead's Verified uses, audited, nobody told.
func (s *ReviewService) approveOnHandIn(ctx context.Context, activityID, lead string, kampala *time.Location) error {
	now := s.now().UTC().Truncate(time.Microsecond)
	var progress progressPlan
	approved := false
	err := s.inTransaction(ctx, func(tx pgx.Tx) error {
		target, _, err := readReview(ctx, tx, activityID)
		if err != nil {
			return err
		}
		if progress, err = planProgress(ctx, tx, target); err != nil {
			return err
		}
		var verdict string
		if err := tx.QueryRow(ctx, `SELECT gateway_pl_review.approve_completion($1, $2, $3)`, activityID, lead, now).
			Scan(&verdict); err != nil {
			return fmt.Errorf("plreview: approve_completion: %w", err)
		}
		switch verdict {
		case "":
		case "changed":
			return nil
		case "no_sfid":
			return fmt.Errorf("plreview: %s: %s", activityID, noSalesforceID)
		default:
			return fmt.Errorf("plreview: unexpected approve verdict %q", verdict)
		}
		approved = true
		if err := settleRecommendations(ctx, tx, target, now); err != nil {
			return err
		}
		if err := linkLoanVisit(ctx, tx, activityID, now); err != nil {
			return err
		}
		ssaMarks, err := confirmVisitSSA(ctx, tx, target, lead, now)
		if err != nil {
			return err
		}
		if err := closeNotice(ctx, tx, eventAwaitingLead, "Activity", activityID, now); err != nil {
			return err
		}
		if target.Status == statusAwaitingIA {
			if err := closeNotice(ctx, tx, eventAwaitingIA, "activity", activityID, now); err != nil {
				return err
			}
		}
		if err := afterWorkSaved(ctx, tx, activityID, ssaMarks, kampala, now); err != nil {
			return err
		}
		if err := raiseEvents(ctx, tx, reviewEvents(target, statusVerified, now, s.salesforceSync), now); err != nil {
			return err
		}
		by := auth.Principal{UserID: lead, ActiveRole: rules.LeadRole}
		return appendAudit(ctx, tx, decisionAudit(ctx, by, "pl_review_auto_approve", target, statusVerified, autoApproveReason), now)
	})
	if err != nil || !approved {
		return err
	}
	if err := s.recordProgress(ctx, activityID, progress, now); err != nil {
		s.logger.ErrorContext(ctx, "plreview: the milestone credit was not recorded", "activity", activityID, "err", err)
	}
	return nil
}

// workMark is ledger_sync's mark for a save of this work: its owner and its
// planned day's year, when a target area counts its type.
func workMark(r Review) (ledgerMark, bool) {
	if r.ResponsibleStaffID == "" || r.Planned == nil || !slices.Contains(rules.LedgerCreditedTypes, r.ActivityType) {
		return ledgerMark{}, false
	}
	day := r.Planned.UTC()
	return ledgerMark{
		owner: r.ResponsibleStaffID,
		fy:    schooldirectory.OperationalFY(time.Date(day.Year(), day.Month(), day.Day(), 0, 0, 0, 0, time.UTC)),
	}, true
}
