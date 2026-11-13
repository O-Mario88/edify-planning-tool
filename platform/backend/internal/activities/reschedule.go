package activities

// The second save Go owns: moving a scheduled school visit to another day
// from My Plan's Reschedule drawer (docs/migration/29), exactly 29.1's case.
// The rules are the view (apps/frontend/views/my_plan_views.py
// reschedule_activity_action) and the move (apps/activities/services.py
// reschedule, 5201–5435) for that case, in their order (29.3). The money the
// move meets is asked of the existing application before the transaction
// (MoveCheck) and settled by it after commit (Settle), as for the first save.

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"slices"
	"sort"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/audit"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/cuid"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// MoveRequest is the Reschedule drawer's fields (activities.proto
// RescheduleSchoolVisitRequest), as the view reads them.
type MoveRequest struct {
	ActivityID, Date, Reason string
}

// MoveAnswer is the moved visit and the toast the web shows.
type MoveAnswer struct {
	ActivityID, Status, PlannedDate, FY string
	RescheduleCount                     int
	Message                             string
}

// MoveVerdict is the existing application's answer for the money a move
// meets (gateway_relay.visit_move_check).
type MoveVerdict struct {
	Refusal    string `json:"refusal"`
	Stage      string `json:"stage"`
	TakesBack  bool   `json:"takesBack"`
	LeftFrozen bool   `json:"leftFrozen"`
	Pooled     bool   `json:"pooled"`
}

// MovePricing asks the existing application what a move's money meets.
type MovePricing interface {
	MoveCheck(ctx context.Context, activityID, date, reason string) (MoveVerdict, error)
}

// The statuses a move of 29.1's case starts from: a plan never begun.
var movableStatuses = []string{"scheduled", "rescheduled"}

// moved is the visit as read before the move.
type moved struct {
	id, activityType, status, purpose, schoolID, responsible, batchID string
	itemID, nameSnapshot                                              string
	scheduled                                                         time.Time
	plannedDate                                                       time.Time
	count                                                             int
}

// movePlan is everything decided before the transaction.
type movePlan struct {
	p                 auth.Principal
	a                 moved
	school            school
	item              *item
	home              staffHome
	ownerUID, reason  string
	posted            string
	scheduled, newDay time.Time
	fy, quarter       string
	month, week       int
	weeks             [][]string
	months            [][]any
	verdict           MoveVerdict
	origin            Origin
	now               time.Time
	newBatch          string
}

// Reschedule makes the move, or refuses it in the existing words, or hands
// it on (ErrHandOn). Nothing is written by a refusal or a hand-on.
func (s *Service) Reschedule(ctx context.Context, p auth.Principal, req MoveRequest, origin Origin) (MoveAnswer, error) {
	pl, err := s.prepareMove(ctx, p, req, origin)
	if err != nil {
		return MoveAnswer{}, err
	}
	rowID, err := s.writeMove(ctx, pl)
	if err != nil {
		return MoveAnswer{}, err
	}
	s.afterMove(ctx, pl, rowID)
	return MoveAnswer{
		ActivityID: pl.a.id, Status: "rescheduled", PlannedDate: pl.newDay.Format(time.DateOnly), FY: pl.fy,
		RescheduleCount: pl.a.count + 1, Message: rules.Move.SavedMessage,
	}, nil
}

// prepareMove is the view and `reschedule` up to its transaction (5251).
func (s *Service) prepareMove(ctx context.Context, p auth.Principal, req MoveRequest, origin Origin) (*movePlan, error) {
	now := s.now()
	today := dateOnly(now.In(s.kampala))
	if p.InActingAppointment || p.StaffProfileID == "" || in(rules.Doors.Requesters, p.ActiveRole) ||
		rules.CalendarBlocksRefuse {
		return nil, handOn("not the owner moving their own visit")
	}
	a, err := movedVisit(ctx, s.db, strings.TrimSpace(req.ActivityID))
	if err != nil {
		return nil, err
	}
	if a == nil || a.responsible != p.StaffProfileID || !in(movableStatuses, a.status) ||
		!in(inScopePurposes, a.purpose) || rules.Purposes.ActivityTypes[a.purpose] != a.activityType ||
		a.batchID == "" || a.nameSnapshot == "" {
		return nil, handOn("not a scheduled visit of the first save's kind, owned by the person")
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
	ownerUID, err := fundingOwner(ctx, s.db, a.responsible, p.UserID)
	if err != nil {
		return nil, err
	}
	if handOnWhy, err := moveNotices(ctx, s.db, a.id, ownerUID); err != nil || handOnWhy != "" {
		if err != nil {
			return nil, err
		}
		return nil, handOn(handOnWhy)
	}
	// assert_operating (5207).
	if sc.closed() {
		return nil, refuse("%s", rules.ClosedSchoolMessage)
	}
	// The view's fields (1295–1307) and _parse_date (5219).
	posted := strings.TrimSpace(req.Date)
	reason := strings.TrimSpace(req.Reason)
	if posted == "" {
		return nil, refuse("Invalid date: ")
	}
	if !isoDate.MatchString(posted) {
		return nil, handOn("a date in another form")
	}
	newDay, err := time.ParseInLocation(time.DateOnly, posted, s.kampala)
	if err != nil {
		return nil, refuse("Invalid date: %s", posted)
	}
	// assert_date_plannable (5222).
	if newDay.Before(today) {
		return nil, refuse("%s has passed. Schedule work from %s onwards.", longDate(newDay), longDate(today))
	}
	mover, ok := s.pricing.(MovePricing)
	if !ok {
		return nil, fmt.Errorf("activities: the pricing cannot check a move")
	}
	verdict, err := mover.MoveCheck(ctx, a.id, posted, reason)
	if err != nil {
		return nil, err
	}
	if verdict.TakesBack || verdict.LeftFrozen || !verdict.Pooled {
		return nil, handOn("the move's money has moved, or its day is not pooled")
	}
	weeks, months, err := lineBuckets(ctx, s.db, a.id)
	if err != nil {
		return nil, err
	}
	if len(weeks) > 1 || len(months) > 1 {
		return nil, handOn("the visit's lines sit in more than one week or month")
	}
	var it *item
	if a.itemID != "" {
		if it, err = itemByID(ctx, s.db, a.itemID); err != nil {
			return nil, err
		}
	}
	home, err := staffHomeOf(ctx, s.db, a.responsible)
	if err != nil {
		return nil, err
	}
	scheduledUTC := newDay.UTC()
	return &movePlan{
		p: p, a: *a, school: *sc, item: it, home: home, ownerUID: ownerUID, reason: reason, posted: posted,
		scheduled: newDay, newDay: newDay, fy: schooldirectory.OperationalFY(scheduledUTC),
		quarter: quarterOf(scheduledUTC), month: int(newDay.Month()), week: min(5, (newDay.Day()-1)/7+1),
		weeks: weeks, months: months, verdict: verdict, origin: origin, now: now,
	}, nil
}

func movedVisit(ctx context.Context, q Querier, id string) (*moved, error) {
	if id == "" {
		return nil, nil
	}
	var a moved
	var purpose, school, responsible, batch, itemID, name *string
	var planned, scheduled *time.Time
	var other bool
	err := q.QueryRow(ctx, `
SELECT a.id, a.activity_type, a.status, a.purpose_type, a.school_id, a.responsible_staff_id,
       a.daily_visit_batch_id, a.catalogue_item_id, a.activity_name_snapshot, a.scheduled_date, a.planned_date,
       a.reschedule_count,
       (a.cluster_id IS NOT NULL OR a.project_id IS NOT NULL OR a.assigned_partner_id IS NOT NULL
        OR a.delivery_type IS DISTINCT FROM 'staff' OR a.paired_school_visit_id IS NOT NULL
        OR a.end_date IS NOT NULL OR a.execution_started_at IS NOT NULL OR a.scheduled_date IS NULL
        OR EXISTS (SELECT 1 FROM activity o WHERE o.paired_school_visit_id = a.id))
FROM activity a WHERE a.id = $1 AND a.deleted_at IS NULL`, id).Scan(
		&a.id, &a.activityType, &a.status, &purpose, &school, &responsible, &batch, &itemID, &name,
		&scheduled, &planned, &a.count, &other)
	// An activity with no date (scheduled_date NULL) is not one a move or a
	// cancel of a scheduled visit takes: handed on, as `other` says.
	if errors.Is(err, pgx.ErrNoRows) || (err == nil && (other || school == nil || planned == nil || scheduled == nil)) {
		return nil, nil
	}
	if err != nil {
		return nil, fmt.Errorf("activities: reading the visit: %w", err)
	}
	a.purpose, a.schoolID, a.responsible = text(purpose), text(school), text(responsible)
	a.batchID, a.itemID, a.nameSnapshot = text(batch), text(itemID), text(name)
	a.plannedDate, a.scheduled = *planned, *scheduled
	return &a, nil
}

func text(s *string) string {
	if s == nil {
		return ""
	}
	return *s
}

// moveNotices says why the move is handed on when the existing save would
// write notices after commit (_resolve_overdue_reminder,
// _settle_day_off_notices): an open overdue reminder on the activity, an
// open day-off notice for its owner.
func moveNotices(ctx context.Context, q Querier, activityID, ownerUID string) (string, error) {
	var overdue, dayOff bool
	err := q.QueryRow(ctx, `
SELECT EXISTS (SELECT 1 FROM notification WHERE source_event_type = $1 AND context_type = 'activity'
                 AND context_id = $2 AND resolved_at IS NULL),
       EXISTS (SELECT 1 FROM notification WHERE recipient_id = $3 AND source_event_type = $4
                 AND resolved_at IS NULL)`,
		rules.Move.OverdueEvent, activityID, ownerUID, rules.Move.DayOffEvent).Scan(&overdue, &dayOff)
	if err != nil {
		return "", fmt.Errorf("activities: reading the visit's notices: %w", err)
	}
	switch {
	case overdue:
		return "an open overdue reminder", nil
	case dayOff:
		return "an open day-off notice", nil
	}
	return "", nil
}

// lineBuckets are the owner-weeks and owner-months the visit's cost lines
// sit in (sync_weekly/monthly_*_for_activity), as the costs row keeps them.
func lineBuckets(ctx context.Context, q Querier, activityID string) ([][]string, [][]any, error) {
	rows, err := q.Query(ctx, `SELECT DISTINCT responsible_user, week_start_date, fiscal_year, month
FROM activity_schedule_cost_line WHERE activity_id = $1`, activityID)
	if err != nil {
		return nil, nil, fmt.Errorf("activities: reading the visit's lines: %w", err)
	}
	defer rows.Close()
	weeks, months := [][]string{}, [][]any{}
	seenWeek, seenMonth := map[string]bool{}, map[string]bool{}
	for rows.Next() {
		var owner, fy *string
		var week *time.Time
		var month *int
		if err := rows.Scan(&owner, &week, &fy, &month); err != nil {
			return nil, nil, fmt.Errorf("activities: reading the visit's lines: %w", err)
		}
		if owner == nil || *owner == "" {
			continue
		}
		if week != nil {
			key := *owner + "|" + week.Format(time.DateOnly)
			if !seenWeek[key] {
				seenWeek[key] = true
				weeks = append(weeks, []string{*owner, week.Format(time.DateOnly)})
			}
		}
		if fy != nil && *fy != "" && month != nil && *month != 0 {
			key := fmt.Sprintf("%s|%s|%d", *owner, *fy, *month)
			if !seenMonth[key] {
				seenMonth[key] = true
				months = append(months, []any{*owner, *fy, *month})
			}
		}
	}
	return weeks, months, rows.Err()
}

// writeMove is the move's transaction (5251–5393, then _hand_over): the
// activity's lock, the duplicate test, the day it joins, the row, the
// timeline row and the costs to follow. It answers the costs row's id.
func (s *Service) writeMove(ctx context.Context, pl *movePlan) (int64, error) {
	tx, err := s.db.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite, IsoLevel: pgx.ReadCommitted})
	if err != nil {
		return 0, fmt.Errorf("activities: opening the move: %w", err)
	}
	defer func() { _ = tx.Rollback(ctx) }()
	if _, err := s.moveInTx(ctx, tx, pl); err != nil {
		return 0, err
	}
	rowID, err := keepMoveCosts(ctx, tx, pl)
	if err != nil {
		return 0, err
	}
	if err := tx.Commit(ctx); err != nil {
		return 0, fmt.Errorf("activities: committing the move: %w", err)
	}
	return rowID, nil
}

// moveInTx is the move's writes inside a transaction it is given (5263–5393
// up to the costs): the activity's lock, the duplicate test, the day's
// refusal, the day joined, the row and the timeline row. stored says the
// existing save would have stored the row before a refusal (the day's is met
// after it), which a group's ledger marks follow (group.go).
func (s *Service) moveInTx(ctx context.Context, tx pgx.Tx, pl *movePlan) (stored bool, err error) {
	var status string
	var batch *string
	var scheduled time.Time
	var count int
	if err := tx.QueryRow(ctx, `SELECT status, daily_visit_batch_id, scheduled_date, reschedule_count
FROM activity WHERE id = $1 FOR UPDATE`, pl.a.id).Scan(&status, &batch, &scheduled, &count); err != nil {
		return false, fmt.Errorf("activities: locking the visit: %w", err)
	}
	if status != pl.a.status || text(batch) != pl.a.batchID || !scheduled.Equal(pl.a.scheduled) || count != pl.a.count {
		// Changed between the read and the lock: not what was decided on.
		return false, handOn("the visit changed before its lock")
	}
	if err := moveDuplicate(ctx, tx, pl); err != nil {
		return false, err
	}
	// The day's refusal is met once the visit leaves and joins
	// (_reprice_moved_activity, then _assert_days_can_follow).
	if pl.verdict.Refusal != "" {
		// The existing save has stored the row by then (5326, then 5379).
		return true, &Refusal{Message: pl.verdict.Refusal}
	}
	newBatch, err := s.joinMovedDay(ctx, tx, pl)
	if err != nil {
		return false, err
	}
	pl.newBatch = newBatch
	if _, err := tx.Exec(ctx, `UPDATE activity SET scheduled_date = $2, fy = $3, quarter = $4, planned_date = $5,
  planned_month = $6, planned_week = $7, reschedule_count = reschedule_count + 1, last_reason = $8,
  status = 'rescheduled', daily_visit_batch_id = $9, updated_at = $10 WHERE id = $1`,
		pl.a.id, pl.scheduled, pl.fy, pl.quarter, pl.newDay.Format(time.DateOnly), pl.month, pl.week,
		pl.reason, newBatch, pl.now); err != nil {
		return false, fmt.Errorf("activities: moving the visit: %w", err)
	}
	if !sameDay(pl.a.plannedDate, pl.newDay) {
		if _, err := tx.Exec(ctx, `INSERT INTO activity_schedule_change (id, kind, from_day, to_day, from_status,
  to_status, reason, changed_at, activity_id) VALUES ($1, 'rescheduled', $2, $3, $4, 'rescheduled', $5, $6, $7)`,
			cuid.New(), pl.a.plannedDate.Format(time.DateOnly), pl.newDay.Format(time.DateOnly), pl.a.status,
			truncateRunes(pl.reason, 512), pl.now, pl.a.id); err != nil {
			return false, fmt.Errorf("activities: writing the schedule trail: %w", err)
		}
	}
	return true, nil
}

func sameDay(a, b time.Time) bool {
	return a.Year() == b.Year() && a.Month() == b.Month() && a.Day() == b.Day()
}

// moveDuplicate is assert_not_duplicate_client_visit for the new day
// (duplicate_visits.existing_same_day_visit, excluding the visit itself).
// The Core test is a no-op off Core schools.
func moveDuplicate(ctx context.Context, q Querier, pl *movePlan) error {
	if !in(rules.Gate.ClientRuleTypes, pl.school.Type) || pl.a.purpose == rules.Gate.CompanionPurpose {
		return nil
	}
	counts := pl.item != nil && pl.item.CountsTowardClientVisit
	if !counts && !in(rules.Gate.FollowUpVisitTypes, pl.a.activityType) {
		return nil
	}
	var same bool
	if err := q.QueryRow(ctx, `SELECT EXISTS (SELECT 1 FROM activity WHERE deleted_at IS NULL AND school_id = $1
  AND planned_date = $2 AND activity_type = $3 AND catalogue_item_id IS NOT DISTINCT FROM $4
  AND NOT (status = ANY($5)) AND NOT COALESCE(purpose_type = $6, false) AND id <> $7)`,
		pl.school.ID, pl.newDay.Format(time.DateOnly), pl.a.activityType, optString(pl.a.itemID),
		rules.DuplicateGoneStatuses, rules.Gate.CompanionPurpose, pl.a.id).Scan(&same); err != nil {
		return fmt.Errorf("activities: reading the school's visits that day: %w", err)
	}
	if same {
		return refuse("%s already has this visit on %s. Open that visit instead of planning a second one for the same day.",
			pl.school.Name, shortDate(pl.newDay))
	}
	return nil
}

// joinMovedDay is day_to_join and reschedule_within_batch: the owner's day,
// locked, or a new one made with its defaults; the move's reason kept on it
// when it differs. The pricing is kept for after the save.
func (s *Service) joinMovedDay(ctx context.Context, tx pgx.Tx, pl *movePlan) (string, error) {
	var batchID, batchReason string
	err := tx.QueryRow(ctx, `SELECT id, COALESCE(reason, '') FROM daily_visit_batch WHERE responsible_user = $1
  AND visit_date = $2 ORDER BY created_at LIMIT 1 FOR UPDATE`, pl.ownerUID, pl.newDay.Format(time.DateOnly)).Scan(&batchID, &batchReason)
	if errors.Is(err, pgx.ErrNoRows) {
		districtType := "primary"
		if districtTypeFor(pl.home, pl.school.DistrictID, pl.school.DistrictName, pl.school.DistrictType) == "secondary" {
			districtType = "secondary"
		}
		batchID, batchReason = cuid.New(), ""
		if _, err := tx.Exec(ctx, `
INSERT INTO daily_visit_batch (id, created_at, updated_at, responsible_user, visit_date, district_type,
  rate_snapshot, daily_pool_amount, school_count, per_school_amount, workload_snapshot)
VALUES ($1, $2, $2, $3, $4, $5, '{}', 0, 0, 0, '{}')`,
			batchID, pl.now, pl.ownerUID, pl.newDay.Format(time.DateOnly), districtType); err != nil {
			return "", fmt.Errorf("activities: making the day: %w", err)
		}
	} else if err != nil {
		return "", fmt.Errorf("activities: locking the day: %w", err)
	}
	if pl.reason != "" && pl.reason != batchReason {
		if _, err := tx.Exec(ctx, `UPDATE daily_visit_batch SET reason = $2, updated_at = $3 WHERE id = $1`,
			batchID, pl.reason, pl.now); err != nil {
			return "", fmt.Errorf("activities: keeping the day's reason: %w", err)
		}
	}
	return batchID, nil
}

// keepMoveCosts is costs_follow._hand_over's row for a move: the day left
// and the day joined, the lines' week and month, the note the move writes on
// its new lines, and the change it is.
func keepMoveCosts(ctx context.Context, tx pgx.Tx, pl *movePlan) (int64, error) {
	days := [][]string{}
	if pl.a.batchID != pl.newBatch {
		days = append(days, []string{pl.a.batchID, pl.ownerUID})
	}
	days = append(days, []string{pl.newBatch, pl.ownerUID})
	notes := []any{}
	if !pl.a.scheduled.Equal(pl.scheduled) {
		notes = append(notes, map[string]any{
			"kind": "reschedule_note", "activity": pl.a.id, "old": pyISO(pl.a.scheduled.UTC()),
			"new": pyISO(pl.scheduled), "reason": pl.reason,
		})
	}
	steps, err := json.Marshal(map[string]any{
		"days": days, "together": false, "weeks": pl.weeks, "months": pl.months, "notes": notes,
		"change": pl.a.nameSnapshot + " at " + pl.school.Name,
	})
	if err != nil {
		return 0, err
	}
	owners := []string{pl.ownerUID}
	for _, w := range pl.weeks {
		owners = append(owners, w[0])
	}
	for _, m := range pl.months {
		owners = append(owners, m[0].(string))
	}
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

// pyISO is Python's datetime.isoformat() for a whole or fractional second.
func pyISO(t time.Time) string {
	layout := "2006-01-02T15:04:05"
	if t.Nanosecond() != 0 {
		layout += ".000000"
	}
	return t.Format(layout + "-07:00")
}

// afterMove is what follows the commit, in the existing order: the ledger's
// marks (on commit), the view's reschedule_activity row, then the pricing
// and the live announcement. None of it can undo the move.
func (s *Service) afterMove(ctx context.Context, pl *movePlan, rowID int64) {
	if in(rules.LedgerCreditedTypes, pl.a.activityType) {
		if err := s.markOwnerYears(ctx, pl.a.responsible, pl.a.plannedDate, pl.newDay); err != nil {
			s.logger.Warn("activities: the target ledger was not marked", "activity", pl.a.id, "err", err)
		}
	}
	if err := s.auditMoved(ctx, pl); err != nil {
		s.logger.Warn("activities: the reschedule audit row was not written", "activity", pl.a.id, "err", err)
	}
	if err := s.pricing.Settle(ctx, []int64{rowID}, pl.a.id); err != nil {
		s.logger.Warn("activities: the costs to follow were not settled; the sweep takes them",
			"activity", pl.a.id, "row", rowID, "err", err)
	}
}

// markOwnerYears is ledger_sync's marks on commit: the owner for the year of
// the day left and of the day joined, distinct and sorted, in one statement
// (_write_marks' bulk upsert), so the ledger's ids advance as Django's do.
func (s *Service) markOwnerYears(ctx context.Context, owner string, days ...time.Time) error {
	fys := []string{}
	for _, day := range days {
		fys = append(fys, schooldirectory.OperationalFY(time.Date(day.Year(), day.Month(), day.Day(), 0, 0, 0, 0, time.UTC)))
	}
	sort.Strings(fys)
	fys = slices.Compact(fys)
	tx, err := s.db.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite})
	if err != nil {
		return err
	}
	defer func() { _ = tx.Rollback(ctx) }()
	if _, err := tx.Exec(ctx, `INSERT INTO target_ledger_dirty (owner_id, fy, marked_at)
SELECT $1, fy, $3 FROM unnest($2::varchar[]) WITH ORDINALITY AS t(fy, n) ORDER BY n
ON CONFLICT (owner_id, fy) DO UPDATE SET marked_at = EXCLUDED.marked_at`, owner, fys, s.now()); err != nil {
		return err
	}
	return tx.Commit(ctx)
}

// auditMoved is the view's `reschedule_activity` row (my_plan_views 1317),
// with the stamps log() adds.
func (s *Service) auditMoved(ctx context.Context, pl *movePlan) error {
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
	if _, err := audit.Append(ctx, tx, audit.Entry{
		Action: "reschedule_activity", SubjectKind: audit.Text("Activity"), SubjectID: audit.Text(pl.a.id),
		ActorID: audit.Text(pl.p.UserID), ActorRole: &role, Success: true,
		Payload:   withStamps(map[string]any{"new_date": pl.posted, "reason": pl.reason}, cover),
		IPAddress: nilIfEmpty(pl.origin.IP), UserAgent: nilIfEmpty(pl.origin.UserAgent),
		CorrelationID: nilIfEmpty(pl.origin.CorrelationID),
	}, s.now()); err != nil {
		return err
	}
	return tx.Commit(ctx)
}
