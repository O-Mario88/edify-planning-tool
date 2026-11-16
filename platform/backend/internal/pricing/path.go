package pricing

import (
	"context"
	"errors"
	"fmt"
	"sort"
	"time"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/costing"
)

// The ways a stored activity is priced (activities.services._price_activity).
const (
	PathOnline = "online" // a training delivered online: free
	PathPair   = "pair"   // an in-school Training carried by its visit: its partner's fee alone
	PathDay    = "day"    // a visit sharing its day: its share and its own lines
	PathAlone  = "alone"  // anything else, on its own
)

// ErrLeftAsPriced is a pooled visit whose status draws no money: the writer
// puts it on its day but prices only the day's live members, so its lines
// stay as they were.
var ErrLeftAsPriced = errors.New("pricing: the writer leaves this activity's lines as they were")

// ErrLockedWeek is a pooled visit whose week's request has left its
// owner's hands: the existing writer refuses to price its day again.
var ErrLockedWeek = errors.New("pricing: the week's request has already been sent for approval")

// Priced is what the single cost writer would write for the activity.
type Priced struct {
	Path string
	Cost costing.Cost
}

type pathRow struct {
	activityType, delivery, mode, paired, responsible, facilitator, school, status string
	plannedDate, endDate                                                           *time.Time
}

// PriceStored is _price_activity(activity, {}) read-only: which way the
// activity is priced, and the cost it would be written with. The finance
// locks a write asks (money moved on an advance, a locked request) are the
// writer's; only the day's week lock is answered here.
func PriceStored(ctx context.Context, db Querier, activityID string) (Priced, error) {
	var a pathRow
	err := db.QueryRow(ctx, `
		SELECT COALESCE(activity_type, ''), COALESCE(delivery_type, ''), COALESCE(programme_delivery_mode, ''),
		       COALESCE(paired_school_visit_id, ''), COALESCE(responsible_staff_id, ''),
		       COALESCE(facilitating_partner_id, ''), COALESCE(school_id, ''), COALESCE(status, ''), planned_date, end_date
		FROM activity WHERE id = $1`, activityID).Scan(&a.activityType, &a.delivery, &a.mode, &a.paired,
		&a.responsible, &a.facilitator, &a.school, &a.status, &a.plannedDate, &a.endDate)
	if err != nil {
		return Priced{}, fmt.Errorf("pricing: reading activity %s: %w", activityID, err)
	}
	if in(rules.OnlineTrainingTypes, a.activityType) && a.mode == rules.OnlineMode {
		return Priced{Path: PathOnline, Cost: emptyCost()}, nil
	}
	pair, err := uncostedPair(ctx, db, a)
	if err != nil {
		return Priced{}, err
	}
	input, err := StoredInput(ctx, db, activityID)
	if err != nil {
		return Priced{}, err
	}
	if pair {
		if a.facilitator == "" {
			return Priced{Path: PathPair, Cost: emptyCost()}, nil
		}
		// facilitation_fee_for: the fee alone, on the operational card of the
		// activity's day.
		act, err := Profiled(input)
		if err != nil {
			return Priced{}, err
		}
		card, err := ReadCard(ctx, db, rules.OperationalKind, input.PlannedDate)
		if err != nil {
			return Priced{}, err
		}
		return Priced{Path: PathPair, Cost: costing.FacilitationFeeCost(act, ratesOf(card))}, nil
	}
	owner, err := fundingOwner(ctx, db, a.responsible)
	if err != nil {
		return Priced{}, err
	}
	if owner != "" && a.delivery == "staff" && poolable(a) && a.plannedDate != nil {
		priced, joined, err := joinDay(ctx, db, activityID, owner, *a.plannedDate, in(rules.NonFundableStatuses, a.status))
		if err != nil || joined {
			return priced, err
		}
	}
	dual, err := Price(ctx, db, input)
	if err != nil {
		return Priced{}, err
	}
	return Priced{Path: PathAlone, Cost: dual.Operational}, nil
}

func emptyCost() costing.Cost { return costing.Cost{MissingItems: []string{}} }

// uncostedPair is is_uncosted_pair_training: an in-school Training whose
// School Visit still makes the journey.
func uncostedPair(ctx context.Context, db Querier, a pathRow) (bool, error) {
	if a.activityType != "in_school_training" || a.paired == "" {
		return false, nil
	}
	var live bool
	err := db.QueryRow(ctx, `
		SELECT EXISTS (SELECT 1 FROM activity WHERE id = $1 AND deleted_at IS NULL
		               AND (status IS NULL OR NOT (status = ANY($2))))`,
		a.paired, rules.CompanionGoneStatuses).Scan(&live)
	if err != nil {
		return false, fmt.Errorf("pricing: reading the Training's visit: %w", err)
	}
	return live, nil
}

// poolable is batch_poolable for an activity that is not an uncosted pair
// Training (PriceStored answers those first).
func poolable(a pathRow) bool {
	if in(rules.DailyBatchEligibleTypes, a.activityType) {
		return a.school != ""
	}
	if !in(rules.DayPoolExtraTypes, a.activityType) {
		return false
	}
	return !(a.endDate != nil && a.plannedDate != nil && a.endDate.After(*a.plannedDate))
}

// fundingOwner is _funding_owner_id(activity) with no one saving: the
// account behind the responsible staff profile, or the id itself when it
// names an account.
func fundingOwner(ctx context.Context, db Querier, responsible string) (string, error) {
	if responsible == "" {
		return "", nil
	}
	var user *string
	err := db.QueryRow(ctx, `SELECT user_id FROM staff_profile WHERE id = $1 AND deleted_at IS NULL`, responsible).Scan(&user)
	switch {
	case err == nil && user != nil && *user != "":
		return *user, nil
	case err != nil && !errors.Is(err, pgx.ErrNoRows):
		return "", fmt.Errorf("pricing: reading the funding owner: %w", err)
	}
	var exists bool
	if err := db.QueryRow(ctx, `SELECT EXISTS (SELECT 1 FROM "user" WHERE id = $1)`, responsible).Scan(&exists); err != nil {
		return "", fmt.Errorf("pricing: reading the funding owner: %w", err)
	}
	if exists {
		return responsible, nil
	}
	return "", nil
}

// joinDay is attach_activity_to_batch read-only: the owner's day on the
// visit's date with the visit on it. joined is false when there is no such
// day yet and its rates are missing (the writer then prices the visit on
// its own).
func joinDay(ctx context.Context, db Querier, activityID, owner string, date time.Time, unfundable bool) (Priced, bool, error) {
	b := dayRow{user: owner, date: date}
	var batchID string
	err := db.QueryRow(ctx, `
		SELECT id, COALESCE(district_type, ''), COALESCE(school_count, 0) FROM daily_visit_batch
		WHERE responsible_user = $1 AND visit_date = $2 ORDER BY id LIMIT 1`, owner, date).
		Scan(&batchID, &b.storedType, &b.schoolCount)
	exists := err == nil
	if err != nil && !errors.Is(err, pgx.ErrNoRows) {
		return Priced{}, false, fmt.Errorf("pricing: reading the visit's day: %w", err)
	}
	var locked bool
	if err := db.QueryRow(ctx, `
		SELECT EXISTS (SELECT 1 FROM weekly_fund_request WHERE responsible_user = $1
		               AND week_start_date <= $2 AND week_end_date >= $2 AND NOT (status = ANY($3)))`,
		owner, date, rules.RebuildableWeeklyStatuses).Scan(&locked); err != nil {
		return Priced{}, false, fmt.Errorf("pricing: reading the week's request: %w", err)
	}
	if locked {
		return Priced{}, true, ErrLockedWeek
	}
	var members []dayMember
	if exists {
		if members, err = dayMembers(ctx, db, batchID); err != nil {
			return Priced{}, false, err
		}
	}
	self, err := memberOf(ctx, db, activityID)
	if err != nil {
		return Priced{}, false, err
	}
	// The day's full rates, as attach_activity_to_batch asks before joining:
	// secondary when any member is, no trip home. Missing, a day that exists
	// refuses the visit; one that does not is not made.
	traveller, err := readTraveller(ctx, db, owner)
	if err != nil {
		return Priced{}, false, err
	}
	dayType := "primary"
	for _, m := range append(append([]dayMember{}, members...), self) {
		if m.district == "" {
			continue
		}
		t, err := traveller.districtType(ctx, db, m.district)
		if err != nil {
			return Priced{}, false, err
		}
		if t == "secondary" {
			dayType = "secondary"
		}
	}
	card, err := ReadCard(ctx, db, rules.OperationalKind, &date)
	if err != nil {
		return Priced{}, false, err
	}
	required, _ := costing.DayKeys(dayType, traveller.accommodationKey(), false)
	for _, k := range required {
		if _, ok := ratesOf(card)[k]; !ok {
			if exists {
				return Priced{}, true, &DayRefusal{Missing: []string{k}}
			}
			return Priced{}, false, nil
		}
	}
	if unfundable {
		return Priced{}, true, ErrLeftAsPriced
	}
	present := false
	for _, m := range members {
		present = present || m.id == activityID
	}
	if !present {
		members = append(members, self)
		sort.Slice(members, func(i, j int) bool { return members[i].id < members[j].id })
	}
	if !exists {
		b.storedType = dayType
	}
	day, err := planDay(ctx, db, b, members)
	if err != nil {
		return Priced{}, true, err
	}
	for _, m := range day.Members {
		if m.ActivityID == activityID {
			return Priced{Path: PathDay, Cost: m.Cost}, true, nil
		}
	}
	return Priced{}, true, fmt.Errorf("pricing: activity %s is not on its day", activityID)
}

func memberOf(ctx context.Context, db Querier, activityID string) (dayMember, error) {
	var m dayMember
	err := db.QueryRow(ctx, `
		SELECT a.id, COALESCE(sc.district_id, cl.district_id, a.event_district_id, '')
		FROM activity a LEFT JOIN school sc ON sc.id = a.school_id LEFT JOIN cluster cl ON cl.id = a.cluster_id
		WHERE a.id = $1`, activityID).Scan(&m.id, &m.district)
	if err != nil {
		return m, fmt.Errorf("pricing: reading activity %s: %w", activityID, err)
	}
	return m, nil
}
