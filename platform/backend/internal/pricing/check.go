package pricing

import (
	"context"
	"errors"
	"fmt"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/costing"
)

// Proposed is the activity a save is about to insert, as the save sends it
// to the existing day check (gateway_relay.PROBE_FIELDS): staff delivery,
// scheduled. ID is the id the save will insert it with.
type Proposed struct {
	ID                   string
	ActivityType         string
	Mode                 string // programme_delivery_mode
	SchoolID             string
	ClusterID            string
	ResponsibleStaffID   string
	CatalogueItemID      string
	PlannedDate          *time.Time
	ExpectedParticipants *int
	PrintingPages        *int
	PhotocopyPages       *int
	PhotocopyCopies      *int
}

// Verdict is the day check's answer (gateway_relay._probe): the pricing's
// refusal and where the existing save meets it ("preview", before its
// transaction; "day", once the visit has joined its day), whether the day
// pools the visit, and whether it is a Group Training delivered online,
// which asks no preview and joins no day.
type Verdict struct {
	Refusal string
	Stage   string
	Pooled  bool
	Online  bool
}

// The day check's refusals, in the existing pricing's words.
const (
	lockedWeekRefusal = "This week's request has already been sent for approval. " +
		"Have it returned before changing the planned activities and daily cost shares."
	participantsRefusal = "Enter the planned participant count in the activity drawer before scheduling."
	moneyMovedRefusal   = "This activity already has a disbursed or accounted advance — its " +
		"cost snapshot is locked. Use a budget amendment instead of rescheduling to change its cost."
	withAccountantRefusal = "This activity's advance is already confirmed and sitting in the " +
		"accountant's queue. Ask the accountant to return the advance first, then reschedule."
	weeklyHoldsRefusal = "This activity is already included in a submitted or approved " +
		"weekly fund request. Return that request before changing its cost."
	monthlyHoldsRefusal = "This activity is already included in a submitted or approved " +
		"monthly fund request. Return that request before changing its cost."
)

// DayCheck is gateway_relay._probe, worked out without writing: what the
// existing save of p would refuse for money's sake, and whether its day
// pools it. A request that follows a planner's change (plan_changes) is not
// in hand here, as it is not in the probe.
func DayCheck(ctx context.Context, db Querier, p Proposed) (Verdict, error) {
	if in(rules.OnlineTrainingTypes, p.ActivityType) && p.Mode == rules.OnlineMode {
		return Verdict{Online: true}, nil
	}
	refusal, err := previewRefusal(ctx, db, p)
	if err != nil || refusal != "" {
		return Verdict{Refusal: refusal, Stage: "preview"}, err
	}
	owner, err := fundingOwner(ctx, db, p.ResponsibleStaffID)
	if err != nil {
		return Verdict{}, err
	}
	if owner == "" || p.PlannedDate == nil || !poolable(pathRow{activityType: p.ActivityType, school: p.SchoolID, plannedDate: p.PlannedDate}) {
		return Verdict{}, nil
	}
	self, err := proposedMember(ctx, db, p)
	if err != nil {
		return Verdict{}, err
	}
	at, joined, err := attach(ctx, db, self, owner, *p.PlannedDate)
	var refused *DayRefusal
	switch {
	case errors.Is(err, ErrLockedWeek):
		return Verdict{Refusal: lockedWeekRefusal, Stage: "day", Pooled: true}, nil
	case errors.As(err, &refused):
		return Verdict{Refusal: refused.Message(), Stage: "day", Pooled: true}, nil
	case err != nil:
		return Verdict{}, err
	case !joined:
		return Verdict{}, nil
	}
	refusal, err = daysCanFollow(ctx, db, at, p)
	if err != nil {
		return Verdict{}, err
	}
	return Verdict{Refusal: refusal, Stage: stageOf(refusal), Pooled: true}, nil
}

func stageOf(refusal string) string {
	if refusal == "" {
		return ""
	}
	return "day"
}

// previewRefusal is _preview_refusal: the cost preview of the visit
// (costing_service.preview, no one's day yet), worded as _create words it.
func previewRefusal(ctx context.Context, db Querier, p Proposed) (string, error) {
	var itemID, profile string
	err := db.QueryRow(ctx, `SELECT id, COALESCE(costing_profile, '') FROM activity_catalogue_item WHERE id = $1`,
		p.CatalogueItemID).Scan(&itemID, &profile)
	if err != nil && !errors.Is(err, pgx.ErrNoRows) {
		return "", fmt.Errorf("pricing: reading the catalogue item: %w", err)
	}
	traveller, err := readTraveller(ctx, db, p.ResponsibleStaffID)
	if err != nil {
		return "", err
	}
	a := costing.Activity{ActivityType: p.ActivityType, DeliveryType: "staff",
		AccommodationKey: traveller.accommodationKey(), Days: 1}
	district := ""
	switch {
	case p.SchoolID != "":
		err = db.QueryRow(ctx, `SELECT COALESCE(district_id, '') FROM school WHERE id = $1`, p.SchoolID).Scan(&district)
	case p.ClusterID != "":
		// _cluster_preview_inputs: the cluster's district, the session's head
		// count and its materials, a blank read as 0.
		err = db.QueryRow(ctx, `SELECT COALESCE(district_id, '') FROM cluster WHERE id = $1`, p.ClusterID).Scan(&district)
		a.ExpectedParticipants = p.ExpectedParticipants
		a.PrintingPages, a.PhotocopyPages, a.PhotocopyCopies = deref(p.PrintingPages), deref(p.PhotocopyPages), deref(p.PhotocopyCopies)
	}
	if err != nil && !errors.Is(err, pgx.ErrNoRows) {
		return "", fmt.Errorf("pricing: reading where the visit happens: %w", err)
	}
	if district != "" {
		if a.DistrictType, err = traveller.districtType(ctx, db, district); err != nil {
			return "", err
		}
	}
	d, err := Price(ctx, db, Input{Activity: a, CatalogueItemID: itemID, Profile: profile})
	if err != nil {
		return "", err
	}
	blockers := []string{}
	if d.OperationalCard == nil {
		blockers = append(blockers, "No active CD Cost Catalogue — publish one before scheduling.")
	}
	for _, k := range d.Operational.MissingItems {
		if k == "expectedParticipants" {
			return participantsRefusal, nil
		}
		blockers = append(blockers, missingLabel(k)+" is not set in the active CD Cost Catalogue.")
	}
	if len(blockers) == 0 {
		return "", nil
	}
	return "Cannot schedule — " + strings.Join(blockers, " · ") +
		" Ask the Country Director to set the missing rate in the Cost Catalogue first.", nil
}

// missingLabel is costing_service._missing_label.
func missingLabel(key string) string {
	if l, ok := rules.KeyLabels[key]; ok {
		return l
	}
	return pyTitle(strings.ReplaceAll(key, "_", " "))
}

// proposedMember is the visit as a member of its day: member_district, the
// school's district, else the cluster's.
func proposedMember(ctx context.Context, db Querier, p Proposed) (dayMember, error) {
	m := dayMember{id: p.ID}
	err := db.QueryRow(ctx, `
		SELECT COALESCE((SELECT district_id FROM school WHERE id = $1), (SELECT district_id FROM cluster WHERE id = $2), '')`,
		p.SchoolID, p.ClusterID).Scan(&m.district)
	if err != nil {
		return m, fmt.Errorf("pricing: reading where the visit happens: %w", err)
	}
	return m, nil
}

// daysCanFollow is costs_follow._assert_days_can_follow for the one day the
// visit joined (together=False): the day as the pricing will find it, then
// whether its paid transport would change, then each member's finance
// guards, in the order the pricing asks them.
func daysCanFollow(ctx context.Context, db Querier, at attachment, p Proposed) (string, error) {
	day, err := dayPool(ctx, db, at.day, at.members)
	var refused *DayRefusal
	switch {
	case errors.As(err, &refused):
		return refused.Message(), nil
	case err != nil:
		return "", err
	}
	if at.exists {
		changed, err := paidTransportChanges(ctx, db, at.batchID, day, p)
		if err != nil {
			return "", err
		}
		if changed {
			return rules.TransportPaid, nil
		}
	}
	return moneyGuards(ctx, db, at.members, p.ID)
}

// paidTransportChanges is whether the day's transport has been paid and
// pricing it with day's pool would leave the provider a different amount
// (vendor_channel.school_transport_amount): the shares of the members at a
// school.
func paidTransportChanges(ctx context.Context, db Querier, batchID string, day Day, p Proposed) (bool, error) {
	var paid *int64
	err := db.QueryRow(ctx, `SELECT amount FROM transport_payment WHERE batch_id = $1 AND status = 'paid'`,
		batchID).Scan(&paid)
	if errors.Is(err, pgx.ErrNoRows) {
		return false, nil
	}
	if err != nil {
		return false, fmt.Errorf("pricing: reading the day's transport payment: %w", err)
	}
	var transport int64
	for _, s := range day.Pool {
		if strings.Contains(s.Key, "transport") {
			transport += s.Amount
		}
	}
	rows, err := db.Query(ctx, `
		SELECT id, COALESCE(school_id, '') <> '' FROM activity
		WHERE daily_visit_batch_id = $1 AND deleted_at IS NULL AND id <> $3
		  AND (status IS NULL OR NOT (status = ANY($2)))
		UNION ALL SELECT $3, $4
		ORDER BY 1`, batchID, rules.TransportGoneStatuses, p.ID, p.SchoolID != "")
	if err != nil {
		return false, fmt.Errorf("pricing: reading the day's transport members: %w", err)
	}
	type member struct {
		id       string
		atSchool bool
	}
	members, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (member, error) {
		var m member
		return m, row.Scan(&m.id, &m.atSchool)
	})
	if err != nil {
		return false, fmt.Errorf("pricing: reading the day's transport members: %w", err)
	}
	var owed int64
	for i, m := range members {
		if m.atSchool {
			owed += split(transport, len(members), i)
		}
	}
	return paid == nil || *paid != owed, nil
}

// moneyGuards is _ask_money_guards over the day's members, by id: of each,
// whether money has moved on an advance on its lines, whether an advance is
// with the accountant, and whether a weekly or monthly request carrying its
// lines has left its owner's hands. The visit being saved has no lines yet.
func moneyGuards(ctx context.Context, db Querier, members []dayMember, selfID string) (string, error) {
	ids := []string{}
	for _, m := range members {
		if m.id != selfID {
			ids = append(ids, m.id)
		}
	}
	if len(ids) == 0 {
		return "", nil
	}
	rows, err := db.Query(ctx, `
		SELECT m.id,
		  EXISTS (SELECT 1 FROM advance_request ar JOIN activity_schedule_cost_line l ON l.id = ar.budget_line_id
		          WHERE l.activity_id = m.id AND ar.status = ANY($2)),
		  EXISTS (SELECT 1 FROM advance_request ar JOIN activity_schedule_cost_line l ON l.id = ar.budget_line_id
		          WHERE l.activity_id = m.id AND ar.status = ANY($3)),
		  EXISTS (SELECT 1 FROM weekly_fund_request w
		          WHERE w.id IN (SELECT wl.weekly_fund_request_id FROM weekly_fund_request_line wl
		                         JOIN activity_schedule_cost_line l ON l.id = wl.activity_budget_line_id
		                         WHERE l.activity_id = m.id)
		            AND NOT (COALESCE(w.status, '') = ANY($4))),
		  EXISTS (SELECT 1 FROM fund_request f
		          WHERE f.id IN (SELECT fi.fund_request_id FROM fund_request_item fi
		                         JOIN activity_schedule_cost_line l ON l.id = fi.activity_schedule_cost_line_id
		                         WHERE l.activity_id = m.id)
		            AND NOT (COALESCE(f.status, '') = ANY($5)))
		FROM unnest($1::text[]) AS m(id) ORDER BY m.id`,
		ids, rules.MoneyMovedAdvanceStatuses, rules.AdvanceWithAccountant,
		rules.RebuildableWeeklyStatuses, rules.RepriceableMonthlyStatuses)
	if err != nil {
		return "", fmt.Errorf("pricing: reading the day's finance guards: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var id string
		var moved, accountant, weekly, monthly bool
		if err := rows.Scan(&id, &moved, &accountant, &weekly, &monthly); err != nil {
			return "", fmt.Errorf("pricing: reading the day's finance guards: %w", err)
		}
		switch {
		case moved:
			return moneyMovedRefusal, nil
		case accountant:
			return withAccountantRefusal, nil
		case weekly:
			return weeklyHoldsRefusal, nil
		case monthly:
			return monthlyHoldsRefusal, nil
		}
	}
	return "", rows.Err()
}
