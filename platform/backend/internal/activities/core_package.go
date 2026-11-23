package activities

import (
	"context"
	"errors"
	"fmt"
	"time"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schoolprofile"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/visitgate"
)

// A visit at a Core school is package work wherever it is scheduled from
// (apps.core_schools.visit_routing).
const (
	coreVisitKind       = "core_visit"
	inheritMappingMode  = "inherit_from_source_activity"
	coreSideCap         = 2
	activePlanStatus    = "Active"
	noCoreVisitCosting  = "No approved Catalogue Activity costs a Core School visit. Ask the Country Director to configure one."
	followUpNeedsTarget = "Choose the Training or support Activity being followed up, or select one current unresolved SSA intervention."
)

// corePlanningTypes are the work `_create` files under core planning.
var corePlanningTypes = []string{coreVisitKind, "core_training", "core_assessment_visit"}

// coreDoneStatuses are CORE_SLOT_DONE_STATUSES.
var coreDoneStatuses = []string{"completed", "closed", "ia_verified", "accountant_confirmed"}

// coreRoute is how a purpose meets a Core school's package.
type coreRoute int

const (
	// coreOutsidePackage: donor, story, invitation and social visits.
	coreOutsidePackage coreRoute = iota
	// corePackageVisit: booked as a core_visit into a locked slot.
	corePackageVisit
	// coreCreditedVisit: staff SSA Support, saved as itself and credited to a
	// slot once it commits.
	coreCreditedVisit
)

func coreRouteFor(purpose string) coreRoute {
	switch purpose {
	case followUpPurpose:
		return corePackageVisit
	case "ssa_support":
		return coreCreditedVisit
	}
	return coreOutsidePackage
}

// coreSlot is one of a package's slots.
type coreSlot struct{ ID, Status string }

// coreBooking is the package a save counts against.
type coreBooking struct {
	planID string
	route  coreRoute
}

// coreVisit is the Core School follow-up item.
func (it item) coreVisit() bool {
	return !it.StandardSupport && it.WorkflowKind == coreVisitKind && !it.IsTrainingCourse &&
		!it.CountsTowardClientVisit && (it.ParticipantMode == "" || it.ParticipantMode == "none") &&
		len(it.Modes) == 1 && it.Modes[0] == inheritMappingMode
}

// openCoreSlot is _free_slot's answer: the lowest slot not spoken for.
func openCoreSlot(slots []coreSlot, taken func(string) bool) *coreSlot {
	for i := range slots {
		if !taken(slots[i].Status) {
			return &slots[i]
		}
	}
	return nil
}

// coreStaffSideRefusal is PackageSplit.refusal for the staff half's visits.
func coreStaffSideRefusal(school string, used int) string {
	return fmt.Sprintf("%s already has its %d staff core visits (%d/%d). A Core package is %d staff and %d partner visits, so the next visit here is the partner's.",
		school, coreSideCap, used, coreSideCap, coreSideCap, coreSideCap)
}

func coreSlotTaken(status string) bool {
	return schoolprofile.GateRules().Core.SlotTaken(status)
}

// readCorePlan is core_plan_for_visit without its write: the year's package,
// nil for a school with none. A year's package still to be made, or one not
// plainly active, is handed on.
func readCorePlan(ctx context.Context, q Querier, code, fy string) (string, error) {
	var id, status string
	err := q.QueryRow(ctx, `SELECT id, COALESCE(status, '') FROM core_plan WHERE school_id = $1 AND fy = $2 ORDER BY id LIMIT 1`,
		code, fy).Scan(&id, &status)
	if err == nil {
		if status != activePlanStatus {
			return "", handOn("the year's Core package is not active")
		}
		return id, nil
	}
	if !errors.Is(err, pgx.ErrNoRows) {
		return "", fmt.Errorf("activities: reading the Core package: %w", err)
	}
	var earlier bool
	if err := q.QueryRow(ctx, `SELECT EXISTS (SELECT 1 FROM core_plan WHERE school_id = $1)`, code).Scan(&earlier); err != nil {
		return "", fmt.Errorf("activities: reading the school's packages: %w", err)
	}
	if earlier {
		return "", handOn("the year's Core package is still to be made")
	}
	return "", nil
}

func readCoreVisitSlots(ctx context.Context, q Querier, planID, lock string) ([]coreSlot, error) {
	rows, err := q.Query(ctx, `SELECT id, COALESCE(status, '') FROM core_activity_slot
WHERE core_plan_id = $1 AND activity_type = 'visit' ORDER BY sequence_number`+lock, planID)
	if err != nil {
		return nil, fmt.Errorf("activities: reading the package's slots: %w", err)
	}
	slots, err := pgx.CollectRows(rows, func(r pgx.CollectableRow) (coreSlot, error) {
		var slot coreSlot
		return slot, r.Scan(&slot.ID, &slot.Status)
	})
	if err != nil {
		return nil, fmt.Errorf("activities: reading a package slot: %w", err)
	}
	return slots, nil
}

// routeCoreVisit is schedule_as_core_visit up to the save. A nil booking is
// work outside any package, saved in the ordinary way. A package past its
// slots would make a new one: handed on.
func (s *Service) routeCoreVisit(ctx context.Context, target visitTarget, purpose string, day, now time.Time) (*coreBooking, error) {
	route := coreRouteFor(purpose)
	if route == coreOutsidePackage || !in(rules.Gate.CoreRuleTypes, target.school.Type) {
		return nil, nil
	}
	if target.approvalOwner != "" {
		return nil, handOn("a request for a Core school's package visit")
	}
	fy := schooldirectory.OperationalFY(day.UTC())
	planID, err := readCorePlan(ctx, s.db, target.school.Code, fy)
	if err != nil || planID == "" {
		return nil, err
	}
	slots, err := readCoreVisitSlots(ctx, s.db, planID, "")
	if err != nil {
		return nil, err
	}
	if openCoreSlot(slots, coreSlotTaken) == nil {
		return nil, handOn("the Core package has no open visit slot")
	}
	if route == corePackageVisit {
		sc := target.school
		split, err := visitgate.SplitOf(ctx, s.db, schoolprofile.GateRules(),
			visitgate.School{ID: sc.ID, Code: sc.Code, Name: sc.Name, Type: sc.Type}, fy, schooldirectory.OperationalFY(now))
		if err != nil {
			return nil, fmt.Errorf("activities: reading the package's split: %w", err)
		}
		if split.HasPackage && split.StaffVisits >= coreSideCap {
			return nil, refuse("%s", coreStaffSideRefusal(sc.Name, split.StaffVisits))
		}
	}
	return &coreBooking{planID: planID, route: route}, nil
}
