package activities

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"log/slog"
	"slices"
	"sort"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/audit"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/costing"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/costing/daypool"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/cuid"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/notificationcenter"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// rebuildableWeeklyStatuses matches apps/fund_requests/weekly_service.py REBUILDABLE_WEEKLY_STATUSES.
var rebuildableWeeklyStatuses = []string{
	"pending_responsible_confirmation",
	"returned_by_pl",
	"returned_by_cd",
	"returned_by_accountant",
}

// nonFundableStatuses matches apps/core/activity_types.py NON_FUNDABLE_ACTIVITY_STATUSES.
var nonFundableStatuses = []string{
	"cancelled",
	"rejected",
	"deferred",
	"awaiting_owner_approval",
}

// plannedDayStatuses matches apps/daily_visit_batches/services.py _PLANNED_DAY_STATUSES.
var plannedDayStatuses = []string{
	"planned",
	"scheduled",
	"rescheduled",
}

// dailyKeyLabels matches apps/daily_visit_batches/pricing.py KEY_LABELS.
var dailyKeyLabels = map[string]string{
	"primary_transport_per_day":          "Transport Primary District",
	"secondary_transport_per_day":        "Transport Secondary District",
	"lunch_per_day":                      "Lunch",
	"secondary_accommodation_per_night":  "Accommodation",
	"management_accommodation_per_night": "Accommodation",
	"secondary_overnight_dinner_per_day": "Dinner",
	"secondary_breakfast_per_day":        "Breakfast",
}

// NativePricing replaces HTTPPricing when Django is absent: it runs the
// exported day-pool and activity-recipe rules (internal/costing/daypool and
// internal/costing) directly against PostgreSQL rate cards, settles affected
// days atomically via gateway_costing, records durable plan.changed events,
// and delivers idempotent completion notifications through notificationcenter.Writer.
type NativePricing struct {
	pool   *pgxpool.Pool
	writer *notificationcenter.Writer
	now    func() time.Time
	push   NoticePush
	live   NoticePublisher
}

// WithNotices sets how the settlement's workflow notices reach a phone and
// open pages.
func (n *NativePricing) WithNotices(push NoticePush, live NoticePublisher) *NativePricing {
	n.push, n.live = push, live
	return n
}

func (n *NativePricing) notices() workflowNotices {
	return workflowNotices{db: n.pool, push: n.push, live: n.live, logger: slog.Default()}
}

// NewNativePricing constructs a Django-independent Pricing/MovePricing/CancelPricing/
// GroupPricing/Announcer/HandedInNotifier implementation.
func NewNativePricing(pool *pgxpool.Pool, writer *notificationcenter.Writer) *NativePricing {
	return &NativePricing{pool: pool, writer: writer, now: time.Now}
}

type rateCard struct {
	ID             string
	Version        int
	Currency       string
	RequiredTarget int
	Rates          map[string]int64
}

type staffCostProfile struct {
	UserID            string
	StaffProfileID    string
	Roles             []string
	ActiveRole        string
	PrimaryDistrictID string
	PrimaryDistrict   string
}

func (n *NativePricing) clock() time.Time {
	if n.now != nil {
		return n.now().UTC()
	}
	return time.Now().UTC()
}

func (n *NativePricing) loadRateCard(ctx context.Context, fy, kind string) (*rateCard, error) {
	if kind == "" {
		kind = "operational"
	}
	var card rateCard
	var target *int
	err := n.pool.QueryRow(ctx, `
SELECT id, version, COALESCE(currency, 'UGX'), required_school_visits_per_day
  FROM cost_catalogue
 WHERE is_active = true AND kind = $1 AND ($2 = '' OR fy = $2)
 ORDER BY CASE WHEN fy = $2 THEN 0 ELSE 1 END, version DESC
 LIMIT 1`, kind, fy).Scan(&card.ID, &card.Version, &card.Currency, &target)
	if errors.Is(err, pgx.ErrNoRows) && fy != "" {
		err = n.pool.QueryRow(ctx, `
SELECT id, version, COALESCE(currency, 'UGX'), required_school_visits_per_day
  FROM cost_catalogue
 WHERE is_active = true AND kind = $1
 ORDER BY version DESC
 LIMIT 1`, kind).Scan(&card.ID, &card.Version, &card.Currency, &target)
	}
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, nil
	}
	if err != nil {
		return nil, fmt.Errorf("activities: loading %s rate card: %w", kind, err)
	}
	card.RequiredTarget = 5
	if target != nil && *target > 0 {
		card.RequiredTarget = *target
	}
	card.Rates = map[string]int64{}
	rows, err := n.pool.Query(ctx, `SELECT key, unit_cost FROM cost_setting WHERE catalogue_id = $1`, card.ID)
	if err != nil {
		return nil, fmt.Errorf("activities: loading rate card settings: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var key string
		var unit int64
		if scanErr := rows.Scan(&key, &unit); scanErr != nil {
			return nil, scanErr
		}
		card.Rates[key] = unit
	}
	return &card, rows.Err()
}

func (n *NativePricing) loadStaffProfile(ctx context.Context, staffOrUserID string) (staffCostProfile, error) {
	var prof staffCostProfile
	if strings.TrimSpace(staffOrUserID) == "" {
		return prof, nil
	}
	err := n.pool.QueryRow(ctx, `
SELECT COALESCE(u.id, ''), COALESCE(sp.id, ''), COALESCE(u.roles, ARRAY[]::varchar[]),
       COALESCE(u.active_role, ''), COALESCE(sp.primary_district_id, ''), COALESCE(d.name, '')
  FROM staff_profile sp
  LEFT JOIN "user" u ON u.id = sp.user_id
  LEFT JOIN district d ON d.id = sp.primary_district_id
 WHERE sp.id = $1 OR sp.user_id = $1
 ORDER BY CASE WHEN sp.user_id = $1 THEN 0 ELSE 1 END, sp.created_at ASC
 LIMIT 1`, staffOrUserID).Scan(
		&prof.UserID, &prof.StaffProfileID, &prof.Roles, &prof.ActiveRole,
		&prof.PrimaryDistrictID, &prof.PrimaryDistrict,
	)
	if errors.Is(err, pgx.ErrNoRows) {
		err = n.pool.QueryRow(ctx, `
SELECT id, COALESCE(roles, ARRAY[]::varchar[]), COALESCE(active_role, '')
  FROM "user" WHERE id = $1`, staffOrUserID).Scan(&prof.UserID, &prof.Roles, &prof.ActiveRole)
		if errors.Is(err, pgx.ErrNoRows) {
			return prof, nil
		}
	}
	if err != nil {
		return prof, fmt.Errorf("activities: reading staff cost profile: %w", err)
	}
	return prof, nil
}

func (n *NativePricing) isWeekLocked(ctx context.Context, ownerID string, day time.Time) (bool, error) {
	if ownerID == "" {
		return false, nil
	}
	var locked bool
	err := n.pool.QueryRow(ctx, `
SELECT EXISTS (
  SELECT 1 FROM weekly_fund_request
   WHERE responsible_user = $1
     AND week_start_date <= $2::date
     AND week_end_date >= $2::date
     AND NOT (status = ANY($3))
)`, ownerID, day.Format(time.DateOnly), rebuildableWeeklyStatuses).Scan(&locked)
	if err != nil {
		return false, fmt.Errorf("activities: checking weekly fund request lock: %w", err)
	}
	return locked, nil
}

func (n *NativePricing) resolveDistrictType(prof staffCostProfile, districtID, districtName string) string {
	target := strings.TrimSpace(districtName)
	if target == "" {
		target = strings.TrimSpace(districtID)
	}
	if target == "" {
		return daypool.PrimaryDay
	}
	primary := strings.TrimSpace(prof.PrimaryDistrict)
	if primary == "" {
		primary = strings.TrimSpace(prof.PrimaryDistrictID)
	}
	if prof.PrimaryDistrictID != "" && districtID != "" && prof.PrimaryDistrictID == districtID {
		return daypool.PrimaryDay
	}
	role := prof.ActiveRole
	if daypool.HoldsFieldRole(prof.Roles, prof.ActiveRole) {
		role = "CCEO"
	}
	dt, err := daypool.ResolveDistrictType(role, primary, target)
	if err != nil {
		// Fall back to HQ/primary when a field profile has no primary district configured in synthetic seeds.
		if primary == "" {
			return daypool.PrimaryDay
		}
		return daypool.HQDistrictType(target)
	}
	return dt
}

func dayLineLabel(key, mark string) string {
	if mark == daypool.MixedDay && key == "secondary_transport_per_day" {
		return "Transport Mixed District"
	}
	if label, ok := dailyKeyLabels[key]; ok {
		return label
	}
	return costing.RateLabel(key)
}

func stringFromAny(v any) string {
	switch x := v.(type) {
	case string:
		return x
	case *string:
		if x != nil {
			return *x
		}
	}
	return ""
}

func intFromAny(v any) int {
	switch x := v.(type) {
	case int:
		return x
	case int64:
		return int(x)
	case float64:
		return int(x)
	}
	return 0
}

// DayCheck evaluates rate-card availability, district/accommodation day-pool
// eligibility, online training zero-cost revision, and week/payment locks
// directly against PostgreSQL (matching gateway_relay.visit_day_check).
func (n *NativePricing) DayCheck(ctx context.Context, activity map[string]any) (DayVerdict, error) {
	if n.pool == nil {
		return DayVerdict{Pooled: true}, nil
	}
	fy := stringFromAny(activity["fy"])
	plannedStr := stringFromAny(activity["planned_date"])
	responsible := stringFromAny(activity["responsible_staff_id"])
	schoolID := stringFromAny(activity["school_id"])
	clusterID := stringFromAny(activity["cluster_id"])
	deliveryMode := stringFromAny(activity["programme_delivery_mode"])

	// Online group training: free, outside every day pool (docs/migration/48).
	if deliveryMode == onlineDelivery {
		card, err := n.loadRateCard(ctx, fy, "operational")
		if err != nil {
			return DayVerdict{}, err
		}
		refCard, _ := n.loadRateCard(ctx, fy, "reference")
		prof, _ := n.loadStaffProfile(ctx, responsible)
		calcBy := prof.UserID
		if calcBy == "" {
			calcBy = responsible
		}
		oc := &OnlineCost{
			OperationalCost:      0,
			OperationalBreakdown: json.RawMessage(`[]`),
			ReferenceBreakdown:   json.RawMessage(`[]`),
			CalculationInputs:    json.RawMessage(`{"programmeDeliveryMode":"online"}`),
			Warnings:             json.RawMessage(`[]`),
			MissingConfiguration: json.RawMessage(`[]`),
			CostMissing:          card == nil,
			CalculatedBy:         &calcBy,
		}
		if card != nil {
			id := card.ID
			ver := card.Version
			oc.OperationalCardID = &id
			oc.OperationalCardVersion = &ver
		}
		if refCard != nil {
			id := refCard.ID
			ver := refCard.Version
			oc.ReferenceCardID = &id
			oc.ReferenceCardVersion = &ver
		}
		return DayVerdict{Pooled: false, Online: oc}, nil
	}

	prof, err := n.loadStaffProfile(ctx, responsible)
	if err != nil {
		return DayVerdict{}, err
	}
	ownerUID := prof.UserID
	if ownerUID == "" {
		ownerUID = responsible
	}

	var districtID, districtName string
	if schoolID != "" {
		_ = n.pool.QueryRow(ctx, `
SELECT COALESCE(s.district_id, ''), COALESCE(d.name, '')
  FROM school s LEFT JOIN district d ON d.id = s.district_id
 WHERE s.id = $1`, schoolID).Scan(&districtID, &districtName)
	} else if clusterID != "" {
		_ = n.pool.QueryRow(ctx, `
SELECT COALESCE(c.district_id, ''), COALESCE(d.name, '')
  FROM cluster c LEFT JOIN district d ON d.id = c.district_id
 WHERE c.id = $1`, clusterID).Scan(&districtID, &districtName)
	}

	dt := n.resolveDistrictType(prof, districtID, districtName)
	accommKey := daypool.AccommodationKeyForUser(prof.Roles, prof.ActiveRole)

	// Load rate card and verify all required daily pool rates exist.
	card, err := n.loadRateCard(ctx, fy, "operational")
	if err != nil {
		return DayVerdict{}, err
	}
	rates := map[string]int64{}
	if card != nil {
		rates = card.Rates
	}
	if _, err := daypool.ComputeDailyPool(rates, dt, accommKey, false); err != nil {
		return DayVerdict{Refusal: err.Error(), Stage: "preview", Pooled: false}, nil
	}

	// Check week lock & paid activities on that day.
	if plannedDay, parseErr := time.Parse(time.DateOnly, plannedStr); parseErr == nil {
		locked, err := n.isWeekLocked(ctx, ownerUID, plannedDay)
		if err != nil {
			return DayVerdict{}, err
		}
		if locked {
			return DayVerdict{
				Refusal: "This week's request has already been sent for approval. Have it returned before changing the planned activities and daily cost shares.",
				Stage:   "day",
				Pooled:  true,
			}, nil
		}
		var hasPaid bool
		_ = n.pool.QueryRow(ctx, `
SELECT EXISTS (
  SELECT 1
    FROM daily_visit_batch b
    JOIN activity a ON a.daily_visit_batch_id = b.id
   WHERE b.responsible_user = $1
     AND b.visit_date = $2::date
     AND a.deleted_at IS NULL
     AND NOT (a.status = ANY($3))
     AND a.payment_status IN ('disbursed', 'paid')
)`, ownerUID, plannedStr, nonFundableStatuses).Scan(&hasPaid)
		if hasPaid {
			return DayVerdict{
				Refusal: "This day already has disbursed or paid work and cannot change its shared cost pool.",
				Stage:   "day",
				Pooled:  true,
			}, nil
		}
		refusal, err := n.dayRefusal(ctx, ownerUID, false, plannedDay, "", "")
		if err != nil {
			return DayVerdict{}, err
		}
		if refusal != "" {
			return DayVerdict{Refusal: refusal, Stage: "day", Pooled: true}, nil
		}
	}

	return DayVerdict{Pooled: true}, nil
}

type costsFollowSteps struct {
	Days     [][]string   `json:"days"`
	Together bool         `json:"together"`
	Weeks    [][]string   `json:"weeks"`
	Months   [][]any      `json:"months"`
	Notes    []followNote `json:"notes"`
	Change   *string      `json:"change"`
}

// Settle computes and persists the day-pool cost split for every affected batch
// listed in the daily_visit_costs_to_follow rows, updates daily_visit_batch,
// activity.est_cost_cents, activity_cost_snapshot, activity_schedule_cost_line,
// audit_log, domain_event_log, and neighbouring return-day batches, then marks
// each costs-to-follow row complete (or records failure/quarantine for retry).
func (n *NativePricing) Settle(ctx context.Context, rows []int64, activityID string) error {
	if n.pool == nil || len(rows) == 0 {
		return nil
	}

	type followRow struct {
		id        int64
		stepsRaw  []byte
		askedBy   string
		askedRole string
	}
	var pending []followRow
	qRows, err := n.pool.Query(ctx,
		`SELECT id, steps, asked_by, asked_by_role FROM gateway_costing.read_costs_to_follow($1)`, rows)
	if err != nil {
		return fmt.Errorf("activities: reading costs_to_follow rows: %w", err)
	}
	for qRows.Next() {
		var r followRow
		if scanErr := qRows.Scan(&r.id, &r.stepsRaw, &r.askedBy, &r.askedRole); scanErr != nil {
			qRows.Close()
			return scanErr
		}
		pending = append(pending, r)
	}
	qRows.Close()
	if err := qRows.Err(); err != nil {
		return err
	}

	var firstErr error
	for _, r := range pending {
		var steps costsFollowSteps
		if err := json.Unmarshal(r.stepsRaw, &steps); err != nil {
			_ = n.recordFollowFailure(ctx, r.id, "invalid steps json: "+err.Error())
			if firstErr == nil {
				firstErr = err
			}
			continue
		}
		// Deduplicate batch IDs in deterministic sorted order to prevent deadlocks under concurrency.
		ownerByBatch := map[string]string{}
		var batchIDs []string
		for _, pair := range steps.Days {
			if len(pair) < 1 || strings.TrimSpace(pair[0]) == "" {
				continue
			}
			bID := strings.TrimSpace(pair[0])
			owner := ""
			if len(pair) >= 2 {
				owner = strings.TrimSpace(pair[1])
			}
			if _, seen := ownerByBatch[bID]; !seen {
				batchIDs = append(batchIDs, bID)
			}
			ownerByBatch[bID] = owner
		}
		sort.Strings(batchIDs)

		money := newDayMoney()
		money.askedBy, money.askedRole = r.askedBy, r.askedRole
		rowErr := money.addSteps(steps)
		for _, batchID := range batchIDs {
			if rowErr != nil {
				break
			}
			rowErr = n.settleBatch(ctx, batchID, ownerByBatch[batchID], r.askedBy, r.askedRole, true, money)
		}
		if rowErr == nil {
			rowErr = n.completeFollowRow(ctx, r.id, money)
			if rowErr == nil {
				n.tellMonthly(ctx, money)
			}
		}
		if rowErr != nil {
			_ = n.recordFollowFailure(ctx, r.id, rowErr.Error())
			if firstErr == nil {
				firstErr = rowErr
			}
		}
	}

	if activityID != "" {
		_ = n.Announce(ctx, activityID)
	}
	return firstErr
}

// SettleUnsettled drains unsettled, non-quarantined daily_visit_costs_to_follow
// rows (used by the scheduler's cost_reprice_sweep job).
func (n *NativePricing) SettleUnsettled(ctx context.Context, limit int) (int, error) {
	if n.pool == nil {
		return 0, nil
	}
	qRows, err := n.pool.Query(ctx, `SELECT id FROM gateway_costing.read_unsettled_costs($1)`, limit)
	if err != nil {
		return 0, fmt.Errorf("activities: listing unsettled costs_to_follow: %w", err)
	}
	var ids []int64
	for qRows.Next() {
		var id int64
		if scanErr := qRows.Scan(&id); scanErr != nil {
			qRows.Close()
			return 0, scanErr
		}
		ids = append(ids, id)
	}
	qRows.Close()
	if err := qRows.Err(); err != nil {
		return 0, err
	}
	if len(ids) == 0 {
		return 0, nil
	}
	err = n.Settle(ctx, ids, "")
	return len(ids), err
}

// completeFollowRow rebuilds the row's weekly requests and monthly drafts and
// closes it in one transaction: a failure leaves the row to be tried again,
// and trying it again ends in the same figures.
func (n *NativePricing) completeFollowRow(ctx context.Context, rowID int64, money *dayMoney) error {
	tx, err := n.pool.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite})
	if err != nil {
		return err
	}
	defer func() { _ = tx.Rollback(ctx) }()
	if err := refileDayMoney(ctx, tx, money, n.clock()); err != nil {
		return err
	}
	var ok bool
	if err := tx.QueryRow(ctx, `SELECT gateway_costing.complete_costs_to_follow($1)`, rowID).Scan(&ok); err != nil {
		return err
	}
	return tx.Commit(ctx)
}

func (n *NativePricing) recordFollowFailure(ctx context.Context, rowID int64, reason string) error {
	tx, err := n.pool.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite})
	if err != nil {
		return err
	}
	defer func() { _ = tx.Rollback(ctx) }()
	var attempts int
	if err := tx.QueryRow(ctx, `SELECT gateway_costing.fail_costs_to_follow($1, $2, $3)`,
		rowID, reason, n.clock()).Scan(&attempts); err != nil {
		return err
	}
	return tx.Commit(ctx)
}

type batchMember struct {
	id                   string
	activityType         string
	deliveryType         string
	costingProfile       string
	schoolID             string
	clusterID            string
	districtID           string
	districtName         string
	expectedParticipants *int
	printingPages        int
	photocopyPages       int
	photocopyCopies      int
	status               string
	paymentStatus        string
}

func (n *NativePricing) settleBatch(
	ctx context.Context,
	batchID, ownerOverride, actorID, actorRole string,
	settleNeighbours bool,
	money *dayMoney,
) error {
	now := n.clock()
	tx, err := n.pool.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite, IsoLevel: pgx.ReadCommitted})
	if err != nil {
		return fmt.Errorf("activities: begin settle tx for batch %s: %w", batchID, err)
	}
	defer func() { _ = tx.Rollback(ctx) }()

	// Lock the batch row to serialize concurrent edits on the same day.
	var responsibleUser, prevDistrictType string
	var visitDate time.Time
	var prevSchoolCount int
	err = tx.QueryRow(ctx, `
SELECT responsible_user, visit_date, district_type, school_count
  FROM daily_visit_batch
 WHERE id = $1
   FOR UPDATE`, batchID).Scan(&responsibleUser, &visitDate, &prevDistrictType, &prevSchoolCount)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil
	}
	if err != nil {
		return fmt.Errorf("activities: locking batch %s: %w", batchID, err)
	}
	ownerUID := responsibleUser
	if ownerUID == "" {
		ownerUID = ownerOverride
	}

	// Do not mutate a batch whose week has left rebuildable statuses.
	locked, err := n.isWeekLocked(ctx, ownerUID, visitDate)
	if err != nil {
		return err
	}
	if locked {
		return fmt.Errorf("batch %s week is locked (non-rebuildable weekly fund request)", batchID)
	}

	// Read all active non-cancelled/non-deferred activities on this day, deterministically ordered by id.
	mRows, err := tx.Query(ctx, `
SELECT a.id, a.activity_type, COALESCE(a.delivery_type, 'staff'),
       COALESCE(a.costing_profile_snapshot, ''),
       COALESCE(a.school_id, ''), COALESCE(a.cluster_id, ''),
       COALESCE(s.district_id, c.district_id, ''),
       COALESCE(sd.name, cd.name, ''),
       a.expected_participants,
       COALESCE(a.printing_pages, 0), COALESCE(a.photocopy_pages, 0), COALESCE(a.photocopy_copies, 0),
       a.status, COALESCE(a.payment_status, 'none')
  FROM activity a
  LEFT JOIN school s ON s.id = a.school_id
  LEFT JOIN district sd ON sd.id = s.district_id
  LEFT JOIN cluster c ON c.id = a.cluster_id
  LEFT JOIN district cd ON cd.id = c.district_id
 WHERE a.daily_visit_batch_id = $1
   AND a.deleted_at IS NULL
   AND NOT (a.status = ANY($2))
 ORDER BY a.id ASC`, batchID, nonFundableStatuses)
	if err != nil {
		return fmt.Errorf("activities: reading batch %s members: %w", batchID, err)
	}
	var members []batchMember
	for mRows.Next() {
		var m batchMember
		if scanErr := mRows.Scan(
			&m.id, &m.activityType, &m.deliveryType, &m.costingProfile,
			&m.schoolID, &m.clusterID, &m.districtID, &m.districtName,
			&m.expectedParticipants, &m.printingPages, &m.photocopyPages, &m.photocopyCopies,
			&m.status, &m.paymentStatus,
		); scanErr != nil {
			mRows.Close()
			return scanErr
		}
		if m.paymentStatus == "disbursed" || m.paymentStatus == "paid" {
			mRows.Close()
			return fmt.Errorf("activity %s already has %s funds", m.id, m.paymentStatus)
		}
		members = append(members, m)
	}
	mRows.Close()
	if err := mRows.Err(); err != nil {
		return err
	}

	prof, err := n.loadStaffProfile(ctx, ownerUID)
	if err != nil {
		return err
	}

	count := len(members)
	wasAway := prevDistrictType == daypool.SecondaryDay && prevSchoolCount > 0

	districtTypes := make([]string, 0, count)
	for _, m := range members {
		districtTypes = append(districtTypes, n.resolveDistrictType(prof, m.districtID, m.districtName))
	}
	dayMark := daypool.PrimaryDay
	pricingType := prevDistrictType
	if pricingType == "" {
		pricingType = daypool.PrimaryDay
	}
	if len(districtTypes) > 0 {
		dayMark = daypool.DayDistrictMark(districtTypes)
		pricingType = daypool.PricingDistrictType(dayMark)
	}

	isAway := pricingType == daypool.SecondaryDay && count > 0
	yesterday := visitDate.AddDate(0, 0, -1)
	tomorrow := visitDate.AddDate(0, 0, 1)
	awayNeighbours := map[string]bool{}
	if wasAway || isAway {
		nRows, err := tx.Query(ctx, `
SELECT visit_date
  FROM daily_visit_batch
 WHERE responsible_user = $1
   AND visit_date IN ($2::date, $3::date)
   AND district_type = 'secondary'
   AND school_count > 0`,
			ownerUID, yesterday.Format(time.DateOnly), tomorrow.Format(time.DateOnly))
		if err != nil {
			return fmt.Errorf("activities: reading neighbouring away days: %w", err)
		}
		for nRows.Next() {
			var d time.Time
			if scanErr := nRows.Scan(&d); scanErr == nil {
				awayNeighbours[d.Format(time.DateOnly)] = true
			}
		}
		nRows.Close()
	}
	returnDay := isAway && awayNeighbours[yesterday.Format(time.DateOnly)] && !awayNeighbours[tomorrow.Format(time.DateOnly)]

	fy := schooldirectory.OperationalFY(visitDate)
	card, err := n.loadRateCard(ctx, fy, "operational")
	if err != nil {
		return err
	}
	if card == nil {
		return fmt.Errorf("no active operational cost catalogue for FY %s", fy)
	}
	accommKey := daypool.AccommodationKeyForUser(prof.Roles, prof.ActiveRole)
	pool, err := daypool.ComputeDailyPool(card.Rates, pricingType, accommKey, returnDay)
	if err != nil {
		return err
	}

	poolTotal := pool.Total()
	perSchool := int64(0)
	if count > 0 {
		perSchool = poolTotal / int64(count)
	}
	rateSnapshotJSON, _ := json.Marshal(pool.Amounts())
	weights, err := readWorkloadWeights(ctx, tx)
	if err != nil {
		return err
	}
	dayTypes := make([]string, 0, count)
	for _, m := range members {
		dayTypes = append(dayTypes, m.activityType)
	}
	mission := daypool.AllocateMission(dayTypes, poolTotal, weights)
	workloadJSON, _ := json.Marshal(map[string]any{
		"total_units":  mission.TotalUnits,
		"visit_units":  mission.VisitUnits,
		"visit_count":  mission.VisitCount,
		"weights_used": mission.WeightsUsed,
	})

	var updated bool
	if err := tx.QueryRow(ctx, `
SELECT gateway_costing.update_batch(
  $1, $2, $3, $4, $5::jsonb, $6, $7, $8, $9, $10, $11, $12::jsonb, $13
)`,
		batchID, pricingType, card.ID, card.Version, string(rateSnapshotJSON),
		poolTotal, count, perSchool, card.RequiredTarget,
		mission.Allocation, mission.PerSchool, string(workloadJSON), now,
	).Scan(&updated); err != nil {
		return fmt.Errorf("activities: updating daily_visit_batch %s: %w", batchID, err)
	}
	if err := ensureDayTransport(ctx, tx, batchID, pool.Amounts(), now); err != nil {
		return err
	}

	if count > 0 {
		memberIDs := make([]string, 0, count)
		for _, m := range members {
			memberIDs = append(memberIDs, m.id)
		}
		oldLines, err := clearDayMoney(ctx, tx, memberIDs, money)
		if err != nil {
			return err
		}
		allocations := daypool.AllocatePool(pool, count)
		periods := periodsOf(visitDate)
		calcBy := actorID
		if calcBy == "" {
			calcBy = ownerUID
		}
		respRole := prof.ActiveRole
		if respRole == "" {
			respRole = actorRole
		}

		for idx, member := range members {
			alloc := allocations[idx]
			type lineJSON struct {
				Key             string         `json:"key"`
				Label           string         `json:"label"`
				Unit            int64          `json:"unit"`
				Qty             int64          `json:"qty"`
				Amount          int64          `json:"amount"`
				Missing         bool           `json:"missing"`
				LineItemType    string         `json:"lineItemType"`
				DailyAllocation map[string]any `json:"dailyAllocation,omitempty"`
			}
			lines := make([]lineJSON, 0, len(pool)+4)
			var total int64
			for _, r := range pool {
				share := alloc[r.Key]
				lines = append(lines, lineJSON{
					Key:          r.Key,
					Label:        dayLineLabel(r.Key, dayMark),
					Unit:         share,
					Qty:          1,
					Amount:       share,
					LineItemType: costing.LineItemType(r.Key),
					DailyAllocation: map[string]any{
						"policy": "staff-day-v2",
						"count":  count,
						"index":  idx,
					},
				})
				total += share
			}

			// Add any activity-specific non-daily components (e.g. group training meals, venue, facilitation, materials).
			own := costing.CostForActivity(costing.Activity{
				ActivityType:         member.activityType,
				DeliveryType:         member.deliveryType,
				DistrictType:         pricingType,
				AccommodationKey:     accommKey,
				ReturnDay:            returnDay,
				CostingKind:          member.costingProfile,
				ExpectedParticipants: member.expectedParticipants,
				PrintingPages:        member.printingPages,
				PhotocopyPages:       member.photocopyPages,
				PhotocopyCopies:      member.photocopyCopies,
			}, card.Rates)
			var missingItems []string
			for _, ol := range own.Lines {
				if _, isDaily := dailyKeyLabels[ol.Key]; isDaily {
					continue
				}
				if ol.Missing {
					missingItems = append(missingItems, ol.Key)
					continue
				}
				unit := int64(0)
				if ol.Unit != nil {
					unit = *ol.Unit
				}
				lines = append(lines, lineJSON{
					Key:          ol.Key,
					Label:        ol.Label,
					Unit:         unit,
					Qty:          ol.Qty,
					Amount:       ol.Amount,
					LineItemType: costing.LineItemType(ol.Key),
				})
				total += ol.Amount
			}

			calcInputsJSON, _ := json.Marshal(map[string]any{
				"batchId":          batchID,
				"visitDate":        visitDate.Format(time.DateOnly),
				"districtType":     pricingType,
				"dayMark":          dayMark,
				"returnDay":        returnDay,
				"accommodationKey": accommKey,
				"schoolCount":      count,
				"allocationIndex":  idx,
			})
			linesBytes, _ := json.Marshal(lines)
			missingBytes, _ := json.Marshal(missingItems)
			if missingItems == nil {
				missingBytes = []byte(`[]`)
			}

			snapshotID := cuid.New()
			var seq int
			if err := tx.QueryRow(ctx, `
SELECT gateway_costing.apply_activity_cost(
  $1, $2, $3, $4::date, $5::date, $6, $7, $8, $9, $10, $11, $12, $13, $14,
  $15, $16::jsonb, $17::jsonb, $18::jsonb, $19::jsonb, $20, $21, $22
)`,
				member.id, total, len(missingItems) > 0,
				periods.weekStart.Format(time.DateOnly), periods.weekEnd.Format(time.DateOnly),
				periods.month, periods.fy, periods.quarter,
				card.ID, card.Version, card.Currency,
				ownerUID, respRole, calcBy,
				snapshotID, string(calcInputsJSON), string(linesBytes),
				string(missingBytes), string(linesBytes),
				cuid.New(), cuid.New(), now,
			).Scan(&seq); err != nil {
				return fmt.Errorf("activities: applying settled cost for activity %s: %w", member.id, err)
			}
			// Activity.save's mirror: the package slot this work fills.
			if _, err := tx.Exec(ctx, `UPDATE core_activity_slot SET status = $2, updated_at = $3
WHERE activity_id = $1 AND status IS DISTINCT FROM $2`, member.id, coreSlotStatus(member.status), now); err != nil {
				return fmt.Errorf("activities: mirroring activity %s to its package slot: %w", member.id, err)
			}
			auditActor := calcBy
			if auditActor == "" {
				auditActor = "system"
			}
			if _, err := audit.Append(ctx, tx, audit.Entry{
				Action:      "activity.cost.calculated",
				SubjectKind: audit.Text("ActivityCostSnapshot"),
				SubjectID:   audit.Text(snapshotID),
				ActorID:     audit.Text(auditActor),
				Success:     true,
				Payload: map[string]any{
					"activityId":                 member.id,
					"sequence":                   seq,
					"operationalCost":            total,
					"operationalRateCardVersion": card.Version,
					"referenceConfigured":        false,
					"referenceRateCardVersion":   nil,
				},
			}, now); err != nil {
				return fmt.Errorf("activities: appending cost audit row for activity %s: %w", member.id, err)
			}
		}
		if err := carryDayMonths(ctx, tx, memberIDs, oldLines, money, now); err != nil {
			return err
		}
		if err := openDayMoney(ctx, tx, memberIDs, ownerUID, visitDate, now, money); err != nil {
			return err
		}
	}

	if err := tx.Commit(ctx); err != nil {
		return fmt.Errorf("activities: committing batch %s settlement: %w", batchID, err)
	}

	// Re-price neighbouring secondary-district days if away status changed (return-day rule).
	if settleNeighbours && len(awayNeighbours) > 0 && wasAway != isAway {
		nRows, err := n.pool.Query(ctx, `
SELECT b.id
  FROM daily_visit_batch b
 WHERE b.responsible_user = $1
   AND b.visit_date IN ($2::date, $3::date)
   AND b.district_type = 'secondary'
   AND b.school_count > 0
   AND NOT EXISTS (
     SELECT 1 FROM activity a
      WHERE a.daily_visit_batch_id = b.id
        AND a.deleted_at IS NULL
        AND NOT (a.status = ANY($4))
        AND NOT (a.status = ANY($5))
   )`,
			ownerUID, yesterday.Format(time.DateOnly), tomorrow.Format(time.DateOnly),
			nonFundableStatuses, plannedDayStatuses)
		if err == nil {
			var neighbourIDs []string
			for nRows.Next() {
				var nid string
				if scanErr := nRows.Scan(&nid); scanErr == nil {
					neighbourIDs = append(neighbourIDs, nid)
				}
			}
			nRows.Close()
			for _, nid := range neighbourIDs {
				_ = n.settleBatch(ctx, nid, ownerUID, actorID, actorRole, false, money)
			}
		}
	}

	return nil
}

// readWorkloadWeights is workload.live_weights: the highest active version of
// each configured type, over the spec's defaults.
func readWorkloadWeights(ctx context.Context, q Querier) (map[string]int, error) {
	weights := daypool.DefaultWorkloadWeights()
	rows, err := q.Query(ctx, `SELECT activity_type, weight_hundredths FROM activity_workload_weight
WHERE active ORDER BY activity_type, version`)
	if err != nil {
		return nil, fmt.Errorf("activities: reading the workload weights: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var activityType string
		var hundredths int
		if err := rows.Scan(&activityType, &hundredths); err != nil {
			return nil, fmt.Errorf("activities: reading a workload weight: %w", err)
		}
		weights[activityType] = hundredths
	}
	if err := rows.Err(); err != nil {
		return nil, fmt.Errorf("activities: reading the workload weights: %w", err)
	}
	return weights, nil
}

// MoveCheck checks whether the target activity exists, whether its old/new days
// are frozen by weekly fund requests or payment status, and whether the target
// day's rate card has all required rates (matching gateway_relay.visit_move_check).
func (n *NativePricing) MoveCheck(ctx context.Context, activityID, newDateStr, _ string) (MoveVerdict, error) {
	if n.pool == nil {
		return MoveVerdict{Pooled: true}, nil
	}
	var status, payment, responsible, schoolID string
	var oldBatchID, batchOwner *string
	var oldVisitDate *time.Time
	err := n.pool.QueryRow(ctx, `
SELECT COALESCE(a.status, ''), COALESCE(a.payment_status, 'none'),
       COALESCE(a.responsible_staff_id, ''), COALESCE(a.school_id, ''),
       a.daily_visit_batch_id, b.responsible_user, b.visit_date
  FROM activity a
  LEFT JOIN daily_visit_batch b ON b.id = a.daily_visit_batch_id
 WHERE a.id = $1 AND a.deleted_at IS NULL`, activityID).Scan(
		&status, &payment, &responsible, &schoolID, &oldBatchID, &batchOwner, &oldVisitDate,
	)
	if err != nil {
		return MoveVerdict{Refusal: "Activity not found."}, nil
	}
	if payment == "disbursed" || payment == "paid" {
		return MoveVerdict{Refusal: "This activity already has disbursed funds and cannot be moved directly.", Stage: "day", Pooled: true}, nil
	}
	prof, _ := n.loadStaffProfile(ctx, responsible)
	ownerUID := prof.UserID
	if batchOwner != nil && *batchOwner != "" {
		ownerUID = *batchOwner
	}
	if ownerUID == "" {
		ownerUID = responsible
	}

	// Check if old day is frozen.
	if oldBatchID != nil && *oldBatchID != "" && oldVisitDate != nil {
		locked, err := n.isWeekLocked(ctx, ownerUID, *oldVisitDate)
		if err != nil {
			return MoveVerdict{}, err
		}
		if locked {
			return MoveVerdict{LeftFrozen: true, Pooled: true}, nil
		}
		refusal, err := n.dayRefusal(ctx, ownerUID, true, *oldVisitDate, activityID, "")
		if err != nil {
			return MoveVerdict{}, err
		}
		if refusal != "" {
			return MoveVerdict{Refusal: refusal, Stage: "day", Pooled: true}, nil
		}
	}

	// Check new day lock & rate card.
	if newDay, parseErr := time.Parse(time.DateOnly, newDateStr); parseErr == nil {
		locked, err := n.isWeekLocked(ctx, ownerUID, newDay)
		if err != nil {
			return MoveVerdict{}, err
		}
		if locked {
			return MoveVerdict{
				Refusal: "This week's request has already been sent for approval. Have it returned before changing the planned activities and daily cost shares.",
				Stage:   "day",
				Pooled:  true,
			}, nil
		}
		refusal, err := n.dayRefusal(ctx, ownerUID, true, newDay, "", activityID)
		if err != nil {
			return MoveVerdict{}, err
		}
		if refusal != "" {
			return MoveVerdict{Refusal: refusal, Stage: "day", Pooled: true}, nil
		}
		var districtID, districtName string
		if schoolID != "" {
			_ = n.pool.QueryRow(ctx, `
SELECT COALESCE(s.district_id, ''), COALESCE(d.name, '')
  FROM school s LEFT JOIN district d ON d.id = s.district_id
 WHERE s.id = $1`, schoolID).Scan(&districtID, &districtName)
		}
		dt := n.resolveDistrictType(prof, districtID, districtName)
		accommKey := daypool.AccommodationKeyForUser(prof.Roles, prof.ActiveRole)
		card, err := n.loadRateCard(ctx, schooldirectory.OperationalFY(newDay), "operational")
		if err != nil {
			return MoveVerdict{}, err
		}
		rates := map[string]int64{}
		if card != nil {
			rates = card.Rates
		}
		if _, err := daypool.ComputeDailyPool(rates, dt, accommKey, false); err != nil {
			return MoveVerdict{Refusal: err.Error(), Stage: "day", Pooled: true}, nil
		}
	}

	return MoveVerdict{Pooled: true}, nil
}

// CancelCheck checks whether the activity exists, whether its week or payment
// state is frozen, whether it has an active milestone progress credit, and
// returns the exact affected day/week/month buckets for post-commit settlement
// (matching gateway_relay.visit_cancel_check).
func (n *NativePricing) CancelCheck(ctx context.Context, activityID, _ string) (CancelVerdict, error) {
	return n.cancelCheck(ctx, activityID, false)
}

// cancelCheck is CancelCheck; planChange is true for a group's cancel, which
// is a planner's change (group_actions.planner_change).
func (n *NativePricing) cancelCheck(ctx context.Context, activityID string, planChange bool) (CancelVerdict, error) {
	if n.pool == nil {
		return CancelVerdict{Found: true}, nil
	}
	var payment, responsible string
	var batchID, batchOwner *string
	var visitDate *time.Time
	err := n.pool.QueryRow(ctx, `
SELECT COALESCE(a.payment_status, 'none'), COALESCE(a.responsible_staff_id, ''),
       a.daily_visit_batch_id, b.responsible_user, b.visit_date
  FROM activity a
  LEFT JOIN daily_visit_batch b ON b.id = a.daily_visit_batch_id
 WHERE a.id = $1 AND a.deleted_at IS NULL`, activityID).Scan(
		&payment, &responsible, &batchID, &batchOwner, &visitDate,
	)
	if err != nil {
		return CancelVerdict{Found: false}, nil
	}
	if payment == "disbursed" || payment == "paid" {
		return CancelVerdict{
			Found:   true,
			Refusal: "This activity already has disbursed funds and must be reconciled before cancellation.",
		}, nil
	}

	var frozenWeeks bool
	_ = n.pool.QueryRow(ctx, `
SELECT EXISTS (
  SELECT 1
    FROM weekly_fund_request w
    JOIN weekly_fund_request_line l ON l.weekly_fund_request_id = w.id
    JOIN activity_schedule_cost_line cl ON cl.id = l.activity_budget_line_id
   WHERE cl.activity_id = $1
     AND NOT (w.status = ANY($2))
     AND w.status NOT IN ('disbursed', 'accounted')
)`, activityID, rebuildableWeeklyStatuses).Scan(&frozenWeeks)

	var credited bool
	_ = n.pool.QueryRow(ctx, `
SELECT EXISTS (
  SELECT 1 FROM hr_milestone_progress_credit
   WHERE activity_id = $1 AND reversed_at IS NULL
)`, activityID).Scan(&credited)

	verdict := CancelVerdict{
		Found:       true,
		FrozenWeeks: frozenWeeks,
		Credited:    credited,
	}

	if batchID != nil && *batchID != "" {
		owner := responsible
		if batchOwner != nil && *batchOwner != "" {
			owner = *batchOwner
		}
		if visitDate != nil {
			locked, err := n.isWeekLocked(ctx, owner, *visitDate)
			if err != nil {
				return CancelVerdict{}, err
			}
			verdict.LeftFrozen = locked
			refusal, err := n.dayRefusal(ctx, owner, planChange, *visitDate, activityID, "")
			if err != nil {
				return CancelVerdict{}, err
			}
			if refusal != "" && !verdict.LeftFrozen {
				return CancelVerdict{Found: true, Refusal: refusal}, nil
			}
		}
		if !verdict.LeftFrozen {
			verdict.Days = [][]string{{*batchID, owner}}
		}
	}

	// Collect prior cost line buckets for weekly/monthly sync.
	weeks, months, err := lineBuckets(ctx, n.pool, activityID)
	if err == nil {
		verdict.Weeks = weeks
		verdict.Months = months
	}

	return verdict, nil
}

// GroupCheck evaluates a group reschedule or group cancel natively in Go
// (matching gateway_relay.visit_group_check) so GroupReschedule and GroupCancel
// operate with zero Django calls.
func (n *NativePricing) GroupCheck(ctx context.Context, q GroupQuestion) (GroupVerdict, error) {
	if n.pool == nil {
		picks := make([]VerdictPick, len(q.ActivityIDs))
		for i, id := range q.ActivityIDs {
			picks[i] = VerdictPick{ID: id, Done: true}
		}
		return GroupVerdict{Together: len(q.ActivityIDs) > 1, Picks: picks}, nil
	}
	picks := make([]VerdictPick, 0, len(q.ActivityIDs))
	doneCount := 0
	for _, id := range q.ActivityIDs {
		var status string
		var planned *time.Time
		err := n.pool.QueryRow(ctx, `SELECT status, planned_date FROM activity WHERE id = $1 AND deleted_at IS NULL`, id).
			Scan(&status, &planned)
		if err != nil {
			picks = append(picks, VerdictPick{ID: id, Done: false, Refusal: "Activity not found."})
			continue
		}
		switch q.Kind {
		case "reschedule":
			if planned != nil && planned.Format(time.DateOnly) == strings.TrimSpace(q.Date) {
				picks = append(picks, VerdictPick{ID: id, Done: false, Refusal: groupAlreadyOnDay})
				continue
			}
			mv, err := n.MoveCheck(ctx, id, q.Date, q.Reason)
			if err != nil {
				return GroupVerdict{}, err
			}
			if mv.Refusal != "" {
				picks = append(picks, VerdictPick{ID: id, Done: false, Refusal: mv.Refusal})
			} else if mv.LeftFrozen || mv.TakesBack {
				picks = append(picks, VerdictPick{ID: id, Done: false, Refusal: "This activity's week has left draft status."})
			} else {
				picks = append(picks, VerdictPick{ID: id, Done: true})
				doneCount++
			}
		case "cancel":
			if status == "cancelled" {
				picks = append(picks, VerdictPick{ID: id, Done: false, Refusal: groupAlreadyOff})
				continue
			}
			cv, err := n.cancelCheck(ctx, id, true)
			if err != nil {
				return GroupVerdict{}, err
			}
			if !cv.Found {
				picks = append(picks, VerdictPick{ID: id, Done: false, Refusal: "Activity not found."})
			} else if cv.Refusal != "" {
				picks = append(picks, VerdictPick{ID: id, Done: false, Refusal: cv.Refusal})
			} else if cv.FrozenWeeks || cv.Credited {
				picks = append(picks, VerdictPick{ID: id, Done: false, Refusal: "This activity has locked finance or milestone records."})
			} else {
				picks = append(picks, VerdictPick{ID: id, Done: true})
				doneCount++
			}
		default:
			return GroupVerdict{Refusal: "Unknown group action."}, nil
		}
	}
	return GroupVerdict{
		Together: doneCount > 1,
		Picks:    picks,
	}, nil
}

// Announce records a durable observable plan.changed domain event in PostgreSQL
// so realtime streams, projections, and tests observe every activity change.
func (n *NativePricing) Announce(ctx context.Context, activityID string) error {
	if n.pool == nil || strings.TrimSpace(activityID) == "" {
		return nil
	}
	tx, err := n.pool.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite})
	if err != nil {
		return fmt.Errorf("activities: begin announce tx: %w", err)
	}
	defer func() { _ = tx.Rollback(ctx) }()
	payload, _ := json.Marshal(map[string]any{"activityId": activityID, "source": "go_gateway"})
	var ok bool
	if err := tx.QueryRow(ctx,
		`SELECT gateway_costing.record_activity_event($1, $2, $3, $4, $5::jsonb, $6)`,
		cuid.New(), "plan.changed", activityID, "", string(payload), n.clock(),
	).Scan(&ok); err != nil {
		return fmt.Errorf("activities: announcing plan.changed for %s: %w", activityID, err)
	}
	return tx.Commit(ctx)
}

// HandedIn notifies the officer's active reporting-line Programme Lead(s)
// natively in Go via notificationcenter.Writer with deterministic SourceEventID
// deduplication, closes any open overdue reminders on the activity, records a
// durable plan.changed event, and returns delivery errors so failures are never
// silently swallowed.
func (n *NativePricing) HandedIn(ctx context.Context, activityID, actorID, _ string) error {
	if n.pool == nil || n.writer == nil || strings.TrimSpace(activityID) == "" {
		return nil
	}
	var staffID, schoolName, schoolID string
	err := n.pool.QueryRow(ctx, `
SELECT COALESCE(a.responsible_staff_id, ''), COALESCE(s.name, 'a school'), COALESCE(a.school_id, '')
  FROM activity a LEFT JOIN school s ON s.id = a.school_id
 WHERE a.id = $1 AND a.deleted_at IS NULL`, activityID).Scan(&staffID, &schoolName, &schoolID)
	if errors.Is(err, pgx.ErrNoRows) || staffID == "" {
		return nil
	}
	if err != nil {
		return fmt.Errorf("activities: reading activity for handed-in notification: %w", err)
	}

	// Resolve active supervisors in the same country (when country_registry records exist).
	rows, err := n.pool.Query(ctx, `
SELECT DISTINCT sup.user_id
  FROM staff_supervisor_assignment ssa
  JOIN staff_profile sup ON sup.id = ssa.supervisor_id AND sup.deleted_at IS NULL
  JOIN "user" u ON u.id = sup.user_id AND u.is_active = true AND u.deleted_at IS NULL
 WHERE ssa.supervisee_id = $1
   AND (
     $2 = ''
     OR NOT EXISTS (
       SELECT 1 FROM country_registry.school_country sc
        WHERE sc.school_id = $2 AND sc.effective_until IS NULL
     )
     OR EXISTS (
       SELECT 1
         FROM country_registry.school_country sc
         JOIN country_registry.country_membership cm
           ON cm.country_id = sc.country_id
          AND cm.user_id = sup.user_id
          AND cm.revoked_at IS NULL
          AND cm.effective_until IS NULL
        WHERE sc.school_id = $2 AND sc.effective_until IS NULL
     )
   )`, staffID, schoolID)
	if err != nil {
		return fmt.Errorf("activities: reading supervisors for handed-in notification: %w", err)
	}
	defer rows.Close()
	var recipients []string
	for rows.Next() {
		var recipient string
		if scanErr := rows.Scan(&recipient); scanErr != nil {
			return scanErr
		}
		if recipient != "" && !slices.Contains(recipients, recipient) {
			recipients = append(recipients, recipient)
		}
	}
	if err := rows.Err(); err != nil {
		return err
	}

	for _, recipient := range recipients {
		if _, err := n.writer.Deliver(ctx, notificationcenter.Delivery{
			RecipientID:     recipient,
			SenderID:        actorID,
			Title:           "Completion awaiting review",
			Body:            "A completed school visit at " + schoolName + " is ready for your confirmation.",
			Category:        "activity_review",
			ContextType:     "activity",
			ContextID:       activityID,
			TargetRoute:     "/pl/review-queue",
			ActionLabel:     "Review",
			ActionRequired:  true,
			Priority:        "high",
			SourceEventType: "activity.completed_handed_in",
			SourceEventID:   activityID,
		}); err != nil {
			return fmt.Errorf("activities: delivering handed-in notification to %s: %w", recipient, err)
		}
	}

	// Close open overdue reminders on this activity (matching gateway_relay.visit_completed).
	_, _ = n.writer.ResolveContext(ctx, "activity_overdue", "activity", activityID)
	return n.Announce(ctx, activityID)
}
