package activities

// The third save Go owns: calling off a scheduled school visit from My
// Plan's Cancel drawer (docs/migration/30), exactly 30.1's case. The rules
// are the view (apps/frontend/views/my_plan_views.py cancel_activity_action)
// and the cancel (apps/activities/services.py _cancel_or_defer) for that
// case, in their order (30.3). The money the cancel meets is asked of the
// existing application before the transaction (CancelCheck) and settled by
// it after commit (Settle); the visit's unmoved advances are withdrawn inside
// the transaction through gateway_money.withdraw_unmoved_advances, the
// narrow function the owner chose (30.4). The existing save's oddities are
// kept: a cancelled visit can be cancelled again, and a visit on a day whose
// week has left draft stays on that day.

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"slices"
	"sort"
	"strings"
	"time"
	"unicode/utf8"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/audit"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/cuid"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// The view's and the cancel's own words (my_plan_views.py 2846,
// services.py 6596), and the longest reason activity.last_reason holds.
const (
	cancelReasonRequired = "Give a reason this activity is being cancelled."
	cancelledAuditReason = "Activity cancelled"
	maxCancelReason      = 512
)

// The statuses a cancel of 30.1's case starts from: a plan never begun, or
// one already cancelled (the existing save cancels it again). Off-plan
// statuses write no timeline row when cancelled (schedule_trail.change_kind).
var (
	cancellableStatuses = []string{"scheduled", "rescheduled", "cancelled"}
	offPlanStatuses     = []string{"cancelled", "deferred"}
)

// CancelRequest is the Cancel drawer's fields (activities.proto
// CancelSchoolVisitRequest), as the view reads them.
type CancelRequest struct {
	ActivityID, Reason string
}

// CancelAnswer is the cancelled visit and the toast the web shows.
type CancelAnswer struct {
	ActivityID, Status, Reason, Message string
}

// CancelVerdict is the existing application's answer for the money a cancel
// meets and keeps (gateway_relay.visit_cancel_check).
type CancelVerdict struct {
	Found       bool       `json:"found"`
	Refusal     string     `json:"refusal"`
	FrozenWeeks bool       `json:"frozenWeeks"`
	Credited    bool       `json:"credited"`
	LeftFrozen  bool       `json:"leftFrozen"`
	PricedHere  bool       `json:"pricedHere"`
	Days        [][]string `json:"days"`
	Weeks       [][]string `json:"weeks"`
	Months      [][]any    `json:"months"`
}

// CancelPricing asks the existing application what a cancel's money meets.
type CancelPricing interface {
	CancelCheck(ctx context.Context, activityID, reason string) (CancelVerdict, error)
}

// cancelPlan is everything decided before the transaction.
type cancelPlan struct {
	p       auth.Principal
	a       moved
	reason  string
	verdict CancelVerdict
	origin  Origin
	now     time.Time
}

// Cancel calls the visit off, or refuses it in the existing words (with the
// view's failure row), or hands it on (ErrHandOn). A hand-on writes nothing.
func (s *Service) Cancel(ctx context.Context, p auth.Principal, req CancelRequest, origin Origin) (CancelAnswer, error) {
	pl, err := s.prepareCancel(ctx, p, req, origin)
	var refusal *Refusal
	if errors.As(err, &refusal) && pl != nil {
		s.auditCancel(ctx, pl, false, refusal.Message)
	}
	if err != nil {
		return CancelAnswer{}, err
	}
	rowID, err := s.writeCancel(ctx, pl)
	if errors.As(err, &refusal) {
		s.auditCancel(ctx, pl, false, refusal.Message)
	}
	if err != nil {
		return CancelAnswer{}, err
	}
	s.afterCancel(ctx, pl, rowID)
	return CancelAnswer{ActivityID: pl.a.id, Status: "cancelled", Reason: pl.reason, Message: rules.Move.SavedMessage}, nil
}

// prepareCancel is the view and `_cancel_or_defer` up to its transaction
// (6600). A refusal comes back with the plan, for the view's failure row.
func (s *Service) prepareCancel(ctx context.Context, p auth.Principal, req CancelRequest, origin Origin) (*cancelPlan, error) {
	now := s.now()
	if p.InActingAppointment || p.StaffProfileID == "" || in(rules.Doors.Requesters, p.ActiveRole) {
		return nil, handOn("not the owner cancelling their own visit")
	}
	a, err := movedVisit(ctx, s.db, strings.TrimSpace(req.ActivityID))
	if err != nil {
		return nil, err
	}
	if a == nil || a.responsible != p.StaffProfileID || !in(cancellableStatuses, a.status) ||
		!in(inScopePurposes, a.purpose) || rules.Purposes.ActivityTypes[a.purpose] != a.activityType {
		return nil, handOn("not a visit of the first save's kind, owned by the person")
	}
	sc, err := schoolByIDOrCode(ctx, s.db, a.schoolID)
	if err != nil {
		return nil, err
	}
	if sc == nil || sc.ID != a.schoolID || in(rules.Gate.CoreRuleTypes, sc.Type) {
		return nil, handOn("a Core school, or no school")
	}
	scope, err := schooldirectory.ResolveScope(ctx, s.db, p, now)
	if err != nil {
		return nil, handOn("no scope: " + err.Error())
	}
	owner, err := schoolOwner(ctx, s.db, sc.ID)
	if err != nil {
		return nil, err
	}
	if !slices.Contains(scope.OwnSchoolIDs, sc.ID) || owner != p.StaffProfileID {
		return nil, handOn("outside the person's own portfolio")
	}
	pl := &cancelPlan{p: p, a: *a, reason: strings.TrimSpace(req.Reason), origin: origin, now: now}
	// The reason (6595), before any lock.
	if pl.reason == "" {
		return pl, refuse("%s", cancelReasonRequired)
	}
	if utf8.RuneCountInString(pl.reason) > maxCancelReason {
		return nil, handOn("a reason longer than the activity keeps")
	}
	ownerUID, err := fundingOwner(ctx, s.db, a.responsible, p.UserID)
	if err != nil {
		return nil, err
	}
	if why, err := moveNotices(ctx, s.db, a.id, ownerUID); err != nil || why != "" {
		if err != nil {
			return nil, err
		}
		return nil, handOn(why)
	}
	asker, ok := s.pricing.(CancelPricing)
	if !ok {
		return nil, fmt.Errorf("activities: the pricing cannot check a cancel")
	}
	verdict, err := asker.CancelCheck(ctx, a.id, pl.reason)
	if err != nil {
		return nil, err
	}
	if !verdict.Found || verdict.FrozenWeeks || verdict.Credited || verdict.PricedHere {
		return nil, handOn("the cancel's money writes after commit, or prices in the save")
	}
	pl.verdict = verdict
	// What pricing the day left would refuse (_assert_days_can_follow, met as
	// the block ends): the whole cancel is undone, and the view writes its row.
	if verdict.Refusal != "" {
		return pl, &Refusal{Message: verdict.Refusal}
	}
	return pl, nil
}

// writeCancel is the cancel's transaction (6600–6660, then _hand_over): the
// activity's lock, its row, the timeline row, the day it leaves, the
// advances withdrawn, and the costs to follow. It answers the costs row's id
// (0 when nothing is kept).
func (s *Service) writeCancel(ctx context.Context, pl *cancelPlan) (int64, error) {
	tx, err := s.db.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite, IsoLevel: pgx.ReadCommitted})
	if err != nil {
		return 0, fmt.Errorf("activities: opening the cancel: %w", err)
	}
	defer func() { _ = tx.Rollback(ctx) }()
	if err := s.cancelInTx(ctx, tx, pl); err != nil {
		return 0, err
	}
	rowID, err := keepCancelCosts(ctx, tx, pl)
	if err != nil {
		return 0, err
	}
	if err := tx.Commit(ctx); err != nil {
		return 0, fmt.Errorf("activities: committing the cancel: %w", err)
	}
	return rowID, nil
}

// cancelInTx is the cancel's writes inside a transaction it is given
// (6601–6658, up to the costs): the activity's lock, its row, the timeline
// row, the day it leaves and the advances withdrawn.
func (s *Service) cancelInTx(ctx context.Context, tx pgx.Tx, pl *cancelPlan) error {
	var status string
	var batch *string
	if err := tx.QueryRow(ctx, `SELECT status, daily_visit_batch_id FROM activity WHERE id = $1 FOR UPDATE`,
		pl.a.id).Scan(&status, &batch); err != nil {
		return fmt.Errorf("activities: locking the visit: %w", err)
	}
	if status != pl.a.status || text(batch) != pl.a.batchID {
		return handOn("the visit changed before its lock")
	}
	if _, err := tx.Exec(ctx, `UPDATE activity SET status = 'cancelled', last_reason = $2, updated_at = $3 WHERE id = $1`,
		pl.a.id, pl.reason, pl.now); err != nil {
		return fmt.Errorf("activities: cancelling the visit: %w", err)
	}
	if !in(offPlanStatuses, pl.a.status) {
		day := pl.a.plannedDate.Format(time.DateOnly)
		if _, err := tx.Exec(ctx, `INSERT INTO activity_schedule_change (id, kind, from_day, to_day, from_status,
  to_status, reason, changed_at, activity_id) VALUES ($1, 'cancelled', $2, $2, $3, 'cancelled', '', $4, $5)`,
			cuid.New(), day, pl.a.status, pl.now, pl.a.id); err != nil {
			return fmt.Errorf("activities: writing the schedule trail: %w", err)
		}
	}
	// remove_school: the day is left unless its week has left draft, when
	// the visit is kept on it (_detach_from_daily_visit_batch).
	if pl.a.batchID != "" && !pl.verdict.LeftFrozen {
		if _, err := tx.Exec(ctx, `UPDATE activity SET daily_visit_batch_id = NULL, updated_at = $2 WHERE id = $1`,
			pl.a.id, s.now()); err != nil {
			return fmt.Errorf("activities: leaving the day: %w", err)
		}
	}
	var withdrawn int
	if err := tx.QueryRow(ctx, `SELECT gateway_money.withdraw_unmoved_advances($1)`, pl.a.id).Scan(&withdrawn); err != nil {
		return fmt.Errorf("activities: withdrawing the advances: %w", err)
	}
	return nil
}

// keepCancelCosts is costs_follow._hand_over's row for a cancel: what the
// existing application says it would keep. No row when it keeps nothing.
func keepCancelCosts(ctx context.Context, tx pgx.Tx, pl *cancelPlan) (int64, error) {
	v := pl.verdict
	if len(v.Days) == 0 && len(v.Weeks) == 0 && len(v.Months) == 0 {
		return 0, nil
	}
	days, weeks, months := orEmpty(v.Days), orEmpty(v.Weeks), v.Months
	if months == nil {
		months = [][]any{}
	}
	steps, err := json.Marshal(map[string]any{
		"days": days, "together": false, "weeks": weeks, "months": months, "notes": []any{}, "change": nil,
	})
	if err != nil {
		return 0, err
	}
	owners := []string{}
	for _, d := range days {
		owners = append(owners, d[1])
	}
	for _, w := range weeks {
		owners = append(owners, w[0])
	}
	for _, m := range months {
		if owner, ok := m[0].(string); ok {
			owners = append(owners, owner)
		}
	}
	owners = slices.DeleteFunc(owners, func(o string) bool { return o == "" })
	sort.Strings(owners)
	owners = slices.Compact(owners)
	ownersJSON, _ := json.Marshal(owners)
	provenance, _ := json.Marshal(map[string]any{
		"ip": nilIfEmpty(pl.origin.IP), "agent": nilIfEmpty(pl.origin.UserAgent),
		"correlation": nilIfEmpty(pl.origin.CorrelationID), "acting": nil,
	})
	var id int64
	err = tx.QueryRow(ctx, `
INSERT INTO daily_visit_costs_to_follow (created_at, updated_at, owners, asked_by, asked_by_role, steps,
  provenance, attempts, held_reason)
VALUES ($1, $1, $2, $3, $4, $5, $6, 0, '') RETURNING id`,
		pl.now, ownersJSON, pl.p.UserID, pl.p.ActiveRole, steps, provenance).Scan(&id)
	if err != nil {
		return 0, fmt.Errorf("activities: keeping the costs to follow: %w", err)
	}
	return id, nil
}

func orEmpty(list [][]string) [][]string {
	if list == nil {
		return [][]string{}
	}
	return list
}

// afterCancel is what follows the commit, in the existing order: the
// ledger's mark (on commit), the view's cancel_activity row, then the
// pricing and the live announcement. None of it can undo the cancel.
func (s *Service) afterCancel(ctx context.Context, pl *cancelPlan, rowID int64) {
	if in(rules.LedgerCreditedTypes, pl.a.activityType) {
		if err := s.markOwnerYears(ctx, pl.a.responsible, pl.a.plannedDate); err != nil {
			s.logger.Warn("activities: the target ledger was not marked", "activity", pl.a.id, "err", err)
		}
	}
	s.auditCancel(ctx, pl, true, cancelledAuditReason)
	if rowID == 0 {
		return
	}
	if err := s.pricing.Settle(ctx, []int64{rowID}, pl.a.id); err != nil {
		s.logger.Warn("activities: the costs to follow were not settled; the sweep takes them",
			"activity", pl.a.id, "row", rowID, "err", err)
	}
}

// auditCancel is the view's `cancel_activity` row (my_plan_views 2827 for a
// refusal, 2839 for the cancel), with the stamps log() adds. A refusal
// carries no payload of its own.
func (s *Service) auditCancel(ctx context.Context, pl *cancelPlan, success bool, reason string) {
	if err := s.appendCancelRow(ctx, pl, success, reason); err != nil {
		s.logger.Warn("activities: the cancel audit row was not written", "activity", pl.a.id, "err", err)
	}
}

func (s *Service) appendCancelRow(ctx context.Context, pl *cancelPlan, success bool, reason string) error {
	role := pl.p.ActiveRole
	tx, err := s.db.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite})
	if err != nil {
		return err
	}
	defer func() { _ = tx.Rollback(ctx) }()
	cover, err := coverageStamp(ctx, tx, pl.p.UserID, s.now())
	if err != nil {
		return err
	}
	var payload any
	if success {
		payload = withStamps(map[string]any{"reason": pl.reason}, cover)
	} else if cover != nil {
		payload = withStamps(map[string]any{}, cover)
	}
	if _, err := audit.Append(ctx, tx, audit.Entry{
		Action: "cancel_activity", SubjectKind: audit.Text("Activity"), SubjectID: audit.Text(pl.a.id),
		ActorID: audit.Text(pl.p.UserID), ActorRole: &role, Success: success, Reason: audit.Text(reason),
		Payload: payload, IPAddress: nilIfEmpty(pl.origin.IP), UserAgent: nilIfEmpty(pl.origin.UserAgent),
		CorrelationID: nilIfEmpty(pl.origin.CorrelationID),
	}, s.now()); err != nil {
		return err
	}
	return tx.Commit(ctx)
}
