package activities

// The Core package credit (apps.core_schools.package_credit
// .credit_school_activity), which Activity.save queues for after its commit:
// a visit or training at a Core School that holds no slot takes the slot a
// partner holds for it, else the package's next open one, else a new one past
// the last, in the package of its own year; the package's counters follow.
// A year whose package is still to be made is handed on, as the booking
// doors hand it on.

import (
	"context"
	_ "embed"
	"encoding/json"
	"errors"
	"fmt"
	"slices"
	"strconv"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schoolprofile"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/visitgate"
)

//go:embed package_credit_rules.json
var packageCreditJSON []byte

// packageCreditRules are package_credit's sets, read from the existing code.
type packageCreditRules struct {
	PackageVisitTypes           []string `json:"package_visit_types"`
	PackageTrainingTypes        []string `json:"package_training_types"`
	SchoolTrainingTypes         []string `json:"school_training_types"`
	OutreachVisitTypes          []string `json:"outreach_visit_types"`
	OutreachVisitPurposes       []string `json:"outreach_visit_purposes"`
	DataCollectionVisitTypes    []string `json:"data_collection_visit_types"`
	DataCollectionVisitPurposes []string `json:"data_collection_visit_purposes"`
	CompanionVisitPurpose       string   `json:"companion_visit_purpose"`
	UncreditedStatuses          []string `json:"uncredited_statuses"`
	CorePlanClosedStatuses      []string `json:"core_plan_closed_statuses"`
	LegacyFY                    string   `json:"legacy_fy"`
}

var creditRules = func() packageCreditRules {
	var r packageCreditRules
	if err := json.Unmarshal(packageCreditJSON, &r); err != nil || len(r.PackageVisitTypes) == 0 || r.LegacyFY == "" {
		panic("activities: package_credit_rules.json is unreadable")
	}
	return r
}()

// ErrPackageCreditHandedOn is a credit whose year's package is still to be
// made (ensure_core_plan would make it).
var ErrPackageCreditHandedOn = errors.New("activities: the work's Core package is still to be made")

// creditWork is what the credit reads of the work.
type creditWork struct {
	deleted                                                          bool
	schoolType, schoolCode, status, kind, purpose, delivery, cluster string
	project, course, item, fy, partner, salesforce                   string
	staff                                                            *string
	scheduled, planned                                               *time.Time
	plannedMonth, plannedWeek                                        *int32
}

// packageKindFor is package_kind_for.
func packageKindFor(activityType, purpose, cluster, delivery string) string {
	r := creditRules
	if cluster != "" || purpose == r.CompanionVisitPurpose || slices.Contains(r.OutreachVisitPurposes, purpose) ||
		slices.Contains(r.OutreachVisitTypes, activityType) {
		return ""
	}
	if slices.Contains(r.DataCollectionVisitTypes, activityType) || slices.Contains(r.DataCollectionVisitPurposes, purpose) {
		if delivery != "partner" {
			return "visit"
		}
		return ""
	}
	if slices.Contains(r.PackageVisitTypes, activityType) {
		return "visit"
	}
	if slices.Contains(r.PackageTrainingTypes, activityType) {
		return "training"
	}
	return ""
}

// slotKindFor is slot_kind_for: the visit an in-school training writes
// beside itself is a package visit.
func slotKindFor(w creditWork) string {
	if w.cluster == "" && w.purpose == creditRules.CompanionVisitPurpose {
		return "visit"
	}
	return packageKindFor(w.kind, w.purpose, w.cluster, w.delivery)
}

// creditTarget is credit_school_activity up to its lock: the work, the slot
// kind it takes and the package it is credited to, or ok false when there is
// nothing to credit.
func creditTarget(ctx context.Context, q Querier, activityID string, kampala *time.Location, now time.Time) (
	w creditWork, kind, planID string, interventions []string, ok bool, err error) {
	w, found, err := readCreditWork(ctx, q, activityID)
	if err != nil || !found || w.deleted || w.schoolType != "core" || slices.Contains(creditRules.UncreditedStatuses, w.status) {
		return w, "", "", nil, false, err
	}
	if universal, err := namesUniversalCourse(ctx, q, w); err != nil || universal {
		return w, "", "", nil, false, err
	}
	if kind = slotKindFor(w); kind == "" {
		return w, "", "", nil, false, nil
	}
	if outside, err := outsidePackage(ctx, q, w.project); err != nil || outside {
		return w, "", "", nil, false, err
	}
	if beside, err := besideUniversalTraining(ctx, q, activityID, w); err != nil || beside {
		return w, "", "", nil, false, err
	}
	if held, err := holdsSlot(ctx, q, activityID); err != nil || held {
		return w, "", "", nil, false, err
	}
	planID, interventions, err = planForCredit(ctx, q, w.schoolCode, w.fy, kampala, now)
	if err != nil || planID == "" {
		return w, "", "", nil, false, err
	}
	return w, kind, planID, interventions, true, nil
}

// PackageCreditHandedOn says whether the package credit that follows a save
// of this work would make a year's package, which Go does not.
func PackageCreditHandedOn(ctx context.Context, q Querier, activityID string, kampala *time.Location, now time.Time) (bool, error) {
	_, _, _, _, _, err := creditTarget(ctx, q, activityID, kampala, now)
	if errors.Is(err, ErrPackageCreditHandedOn) {
		return true, nil
	}
	return false, err
}

// CreditSchoolActivity is credit_school_activity, in a transaction of its
// own after the save's commit. It says whether a slot was linked.
func CreditSchoolActivity(ctx context.Context, tx pgx.Tx, activityID string, kampala *time.Location, now time.Time) (bool, error) {
	w, kind, planID, interventions, ok, err := creditTarget(ctx, tx, activityID, kampala, now)
	if err != nil || !ok {
		return false, err
	}
	slots, err := lockedSlots(ctx, tx, planID, kind)
	if err != nil {
		return false, err
	}
	if held, err := holdsSlot(ctx, tx, activityID); err != nil || held {
		return false, err
	}
	slotID, err := openSlotFor(ctx, tx, planID, w, kind, slots, interventions, now)
	if err != nil {
		return false, err
	}
	if err := linkSlot(ctx, tx, slotID, activityID, w, kampala, now); err != nil {
		return false, err
	}
	return true, resyncPlanCompletion(ctx, tx, planID, now)
}

func readCreditWork(ctx context.Context, tx Querier, activityID string) (creditWork, bool, error) {
	var w creditWork
	err := tx.QueryRow(ctx, `SELECT a.deleted_at IS NOT NULL, COALESCE(s.school_type, ''), COALESCE(s.school_id, ''),
  COALESCE(a.status, ''), COALESCE(a.activity_type, ''), COALESCE(a.purpose_type, ''), COALESCE(NULLIF(a.delivery_type, ''), 'staff'),
  COALESCE(a.cluster_id, ''), COALESCE(a.project_id, ''), COALESCE(a.training_course_id, ''), COALESCE(a.catalogue_item_id, ''),
  COALESCE(a.fy, ''), a.responsible_staff_id, COALESCE(a.assigned_partner_id, ''),
  COALESCE(a.salesforce_activity_id, ''), a.scheduled_date, a.planned_date, a.planned_month, a.planned_week
FROM activity a JOIN school s ON s.id = a.school_id WHERE a.id = $1`, activityID).Scan(
		&w.deleted, &w.schoolType, &w.schoolCode, &w.status, &w.kind, &w.purpose, &w.delivery, &w.cluster, &w.project,
		&w.course, &w.item, &w.fy, &w.staff, &w.partner, &w.salesforce, &w.scheduled, &w.planned, &w.plannedMonth, &w.plannedWeek)
	if errors.Is(err, pgx.ErrNoRows) {
		return w, false, nil
	}
	if err != nil {
		return w, false, fmt.Errorf("activities: reading the work for its package credit: %w", err)
	}
	return w, true, nil
}

// namesUniversalCourse is names_universal_course.
func namesUniversalCourse(ctx context.Context, tx Querier, w creditWork) (bool, error) {
	if w.course == "" && !slices.Contains(creditRules.SchoolTrainingTypes, w.kind) && w.cluster == "" {
		return false, nil
	}
	var universal bool
	err := tx.QueryRow(ctx, `SELECT EXISTS (SELECT 1 FROM activity_catalogue_item WHERE is_training_course AND universal_training
  AND id IN ($1, $2))`, w.course, w.item).Scan(&universal)
	if err != nil {
		return false, fmt.Errorf("activities: reading the universal trainings: %w", err)
	}
	return universal, nil
}

// outsidePackage is outside_package: work of a project no SSA intervention
// measures.
func outsidePackage(ctx context.Context, tx Querier, project string) (bool, error) {
	if project == "" {
		return false, nil
	}
	outside, err := visitgate.ProjectsOutsideSSA(ctx, tx, schoolprofile.GateRules())
	if err != nil {
		return false, err
	}
	return slices.Contains(outside, project), nil
}

// besideUniversalTraining is activity_is_universal's second half: the visit a
// universal in-school training wrote beside itself.
func besideUniversalTraining(ctx context.Context, tx Querier, activityID string, w creditWork) (bool, error) {
	if w.purpose != creditRules.CompanionVisitPurpose {
		return false, nil
	}
	var beside bool
	if err := tx.QueryRow(ctx, `SELECT EXISTS (SELECT 1 FROM activity t JOIN activity_catalogue_item c ON c.id = t.training_course_id
WHERE t.paired_school_visit_id = $1 AND c.universal_training)`, activityID).Scan(&beside); err != nil {
		return false, fmt.Errorf("activities: reading the training beside the visit: %w", err)
	}
	return beside, nil
}

func holdsSlot(ctx context.Context, tx Querier, activityID string) (bool, error) {
	var held bool
	if err := tx.QueryRow(ctx, `SELECT EXISTS (SELECT 1 FROM core_activity_slot WHERE activity_id = $1)`, activityID).Scan(&held); err != nil {
		return false, fmt.Errorf("activities: reading whether the work holds a slot: %w", err)
	}
	return held, nil
}

// planForCredit is plan_for_activity: the package of the work's own year.
// An earlier year's is read as it is; a running or later year's still to be
// made is handed on.
func planForCredit(ctx context.Context, tx Querier, code, fy string, kampala *time.Location, now time.Time) (string, []string, error) {
	if fy == "" {
		return "", nil, nil
	}
	var id, status string
	var interventions []byte
	err := tx.QueryRow(ctx, `SELECT id, COALESCE(status, ''), interventions FROM core_plan WHERE school_id = $1 AND fy = $2
ORDER BY id LIMIT 1`, code, fy).Scan(&id, &status, &interventions)
	if errors.Is(err, pgx.ErrNoRows) {
		if fy < schooldirectory.OperationalFY(now.In(kampala)) {
			return "", nil, nil
		}
		var earlier bool
		if err := tx.QueryRow(ctx, `SELECT EXISTS (SELECT 1 FROM core_plan WHERE school_id = $1 AND NOT (status = ANY($2)))`,
			code, creditRules.CorePlanClosedStatuses).Scan(&earlier); err != nil {
			return "", nil, fmt.Errorf("activities: reading the school's packages: %w", err)
		}
		if earlier {
			return "", nil, ErrPackageCreditHandedOn
		}
		return "", nil, nil
	}
	if err != nil {
		return "", nil, fmt.Errorf("activities: reading the work's Core package: %w", err)
	}
	if slices.Contains(creditRules.CorePlanClosedStatuses, status) {
		return "", nil, nil
	}
	var names []string
	if len(interventions) > 0 {
		_ = json.Unmarshal(interventions, &names)
	}
	return id, names, nil
}

// creditSlot is one of the package's slots of the work's kind.
type creditSlot struct {
	id, status, partner string
	sequence            int
	linked              bool
}

func lockedSlots(ctx context.Context, tx pgx.Tx, planID, kind string) ([]creditSlot, error) {
	rows, err := tx.Query(ctx, `SELECT id, COALESCE(status, ''), COALESCE(assigned_partner_id, ''), sequence_number,
  COALESCE(activity_id, '') <> ''
FROM core_activity_slot WHERE core_plan_id = $1 AND activity_type = $2 ORDER BY sequence_number FOR UPDATE`, planID, kind)
	if err != nil {
		return nil, fmt.Errorf("activities: reading the package's slots: %w", err)
	}
	return pgx.CollectRows(rows, func(row pgx.CollectableRow) (creditSlot, error) {
		var s creditSlot
		err := row.Scan(&s.id, &s.status, &s.partner, &s.sequence, &s.linked)
		return s, err
	})
}

// openSlotFor is _open_slot.
func openSlotFor(ctx context.Context, tx pgx.Tx, planID string, w creditWork, kind string, slots []creditSlot,
	interventions []string, now time.Time) (string, error) {
	if w.delivery == "partner" && w.partner != "" {
		for _, s := range slots {
			if strings.EqualFold(strings.TrimSpace(s.status), "assigned") && s.partner == w.partner && !s.linked {
				return s.id, nil
			}
		}
	}
	for _, s := range slots {
		if !coreSlotTaken(s.status) {
			return s.id, nil
		}
	}
	sequence := 1
	for _, s := range slots {
		sequence = max(sequence, s.sequence+1)
	}
	letter := map[string]string{"visit": "v", "training": "t"}[kind]
	id := "cslot-" + w.schoolCode + "-" + w.fy + "-" + letter + strconv.Itoa(sequence)
	if w.fy == creditRules.LegacyFY {
		id = "cslot-" + w.schoolCode + "-" + letter + strconv.Itoa(sequence)
	}
	intervention := "christlike_behaviour"
	if len(interventions) > 0 {
		intervention = interventions[0]
	}
	if _, err := tx.Exec(ctx, `INSERT INTO core_activity_slot (id, created_at, updated_at, core_plan_id, school_id, intervention,
  activity_type, sequence_number, status, owner)
VALUES ($1, $2, $2, $3, $4, $5, $6, $7, 'Planned', 'unassigned') ON CONFLICT (id) DO NOTHING`,
		id, now, planID, w.schoolCode, intervention, kind, sequence); err != nil {
		return "", fmt.Errorf("activities: adding a package slot: %w", err)
	}
	return id, nil
}

// linkSlot writes the work onto the slot, as credit_school_activity's
// slot.save() writes it.
func linkSlot(ctx context.Context, tx pgx.Tx, slotID, activityID string, w creditWork, kampala *time.Location, now time.Time) error {
	var day *string
	switch {
	case w.scheduled != nil:
		d := w.scheduled.In(kampala).Format(time.DateOnly)
		day = &d
	case w.planned != nil:
		d := w.planned.Format(time.DateOnly)
		day = &d
	}
	var month *string
	if w.plannedMonth != nil && *w.plannedMonth != 0 {
		m := strconv.Itoa(int(*w.plannedMonth))
		month = &m
	}
	owner := "staff"
	if w.delivery == "partner" {
		owner = "partner"
	}
	if _, err := tx.Exec(ctx, `SELECT gateway_core_slots.link_slot($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)`,
		slotID, activityID, coreSlotStatus(w.status), owner, w.staff, w.partner, day, month, w.plannedWeek, w.salesforce, now); err != nil {
		return fmt.Errorf("activities: linking the work to its package slot: %w", err)
	}
	return nil
}
