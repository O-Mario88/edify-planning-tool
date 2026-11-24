package visitgate

import (
	"context"
	"fmt"
	"slices"
	"strings"
)

// The Core package rule (owner, 2026-09-30): a Core school's package is
// four visits and four trainings, two of each for staff and two for
// partners. apps.core_schools.package_split counts what each side holds;
// visit_gate._decide_by_rule closes a side once it holds its two.

// CoreRules are the package split's vocabularies (export "gate.core").
type CoreRules struct {
	SideCap int `json:"side_cap"`
	Caps    struct {
		StaffVisits      int `json:"staff_visits"`
		PartnerVisits    int `json:"partner_visits"`
		StaffTrainings   int `json:"staff_trainings"`
		PartnerTrainings int `json:"partner_trainings"`
	} `json:"caps"`
	PackageVisitTypes           []string          `json:"package_visit_types"`
	PackageTrainingTypes        []string          `json:"package_training_types"`
	DataCollectionVisitTypes    []string          `json:"data_collection_visit_types"`
	DataCollectionVisitPurposes []string          `json:"data_collection_visit_purposes"`
	OutreachVisitTypes          []string          `json:"outreach_visit_types"`
	OutreachVisitPurposes       []string          `json:"outreach_visit_purposes"`
	NonPackageVisitPurposes     []string          `json:"non_package_visit_purposes"`
	UncreditedStatuses          []string          `json:"uncredited_statuses"`
	ClusterTrainingTypes        []string          `json:"cluster_training_types"`
	PlanClosedStatuses          []string          `json:"plan_closed_statuses"`
	PurposeActivityTypes        map[string]string `json:"purpose_activity_types"`
	LockPackageComplete         string            `json:"lock_package_complete"`
	SlotAllocatedStatuses       []string          `json:"slot_allocated_statuses"`
	SlotHandedOverStatus        string            `json:"slot_handed_over_status"`
	SlotDoneStatuses            []string          `json:"slot_done_statuses"`
}

// SlotState is core_planning_services.slot_state: "done", "planned" (dated,
// or held by a partner) or "open".
func (c CoreRules) SlotState(status string) string {
	s := strings.ToLower(strings.TrimSpace(status))
	switch {
	case slices.Contains(c.SlotDoneStatuses, s):
		return "done"
	case c.SlotTaken(status):
		return "planned"
	}
	return "open"
}

// SlotTaken is CorePackageSchedulingService.status_is_taken.
func (c CoreRules) SlotTaken(status string) bool {
	s := strings.ToLower(strings.TrimSpace(status))
	return slices.Contains(c.SlotAllocatedStatuses, s) || s == c.SlotHandedOverStatus
}

// CoreSplit is package_split.PackageSplit: one package's work by kind and
// by who delivers it.
type CoreSplit struct {
	// HasPackage: the school has a live package for the year, or has had
	// packages and the year's is still to be made (PACKAGE_NOT_MADE_YET).
	HasPackage                                                bool
	StaffVisits, PartnerVisits, PartnerPendingVisits          int
	StaffTrainings, PartnerTrainings, PartnerPendingTrainings int
}

// PartnerHeldVisits is the partner side's visits, waiting hand-overs
// included.
func (s CoreSplit) PartnerHeldVisits() int { return s.PartnerVisits + s.PartnerPendingVisits }

// PartnerHeldTrainings is the partner side's trainings, waiting hand-overs
// included.
func (s CoreSplit) PartnerHeldTrainings() int { return s.PartnerTrainings + s.PartnerPendingTrainings }

const (
	kindVisit    = "visit"
	kindTraining = "training"
)

func (s *CoreSplit) add(kind, delivery string) {
	partner := delivery == "partner"
	switch {
	case kind == kindVisit && partner:
		s.PartnerVisits++
	case kind == kindVisit:
		s.StaffVisits++
	case kind == kindTraining && partner:
		s.PartnerTrainings++
	case kind == kindTraining:
		s.StaffTrainings++
	}
}

// splitOf is package_splits for one Core school.
func splitOf(ctx context.Context, q Querier, r Rules, school School, fy, operational string, outside []string) (CoreSplit, error) {
	c := r.Core
	var split CoreSplit
	rows, err := q.Query(ctx, `
SELECT id, fy FROM core_plan WHERE school_id = $1 AND NOT (status = ANY($2)) ORDER BY id`, school.Code, c.PlanClosedStatuses)
	if err != nil {
		return split, fmt.Errorf("visitgate: reading the Core plans: %w", err)
	}
	planID, hasPlans := "", false
	for rows.Next() {
		var id, planFY string
		if err := rows.Scan(&id, &planFY); err != nil {
			rows.Close()
			return split, err
		}
		hasPlans = true
		if planFY == fy && planID == "" {
			planID = id
		}
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return split, err
	}
	switch {
	case planID != "":
	case hasPlans && fy >= operational:
		// PACKAGE_NOT_MADE_YET: the split applies; there are no slots yet.
	default:
		return split, nil
	}
	split.HasPackage = true

	// 1. The visits and trainings at the school dated in the year, with the
	//    existing query's joins (a visit paired with two trainings is two
	//    rows there, and so here).
	work, err := q.Query(ctx, `
SELECT COALESCE(a.activity_type, ''), COALESCE(a.purpose_type, ''), COALESCE(a.delivery_type, '')
FROM activity a
LEFT JOIN activity_catalogue_item t5 ON t5.id = a.training_course_id
LEFT JOIN activity_catalogue_item ci ON ci.id = a.catalogue_item_id
LEFT JOIN activity t6 ON t6.paired_school_visit_id = a.id
LEFT JOIN activity_catalogue_item t7 ON t7.id = t6.training_course_id
WHERE a.deleted_at IS NULL AND a.fy = $1 AND a.school_id = $2
  AND ((a.activity_type = ANY($3) AND a.cluster_id IS NULL
        AND NOT (a.purpose_type = ANY($4) AND a.purpose_type IS NOT NULL))
    OR ((a.activity_type = ANY($5) OR a.purpose_type = ANY($6))
        AND NOT (a.delivery_type = 'partner') AND a.cluster_id IS NULL
        AND NOT (a.activity_type = ANY($7))
        AND NOT (a.purpose_type = ANY($8) AND a.purpose_type IS NOT NULL))
    OR (a.purpose_type = $9 AND a.cluster_id IS NULL))
  AND NOT (a.project_id = ANY($10) AND a.project_id IS NOT NULL)
  AND NOT ((t5.universal_training AND t5.universal_training IS NOT NULL)
        OR (ci.universal_training AND ci.universal_training IS NOT NULL)
        OR (t7.universal_training AND t7.universal_training IS NOT NULL))
  AND NOT (a.status = ANY($11))`,
		fy, school.ID,
		append(append([]string{}, c.PackageVisitTypes...), c.PackageTrainingTypes...),
		append([]string{r.CompanionPurpose}, c.NonPackageVisitPurposes...),
		c.DataCollectionVisitTypes, c.DataCollectionVisitPurposes, c.OutreachVisitTypes,
		append([]string{r.CompanionPurpose}, c.OutreachVisitPurposes...),
		r.CompanionPurpose, outside, c.UncreditedStatuses)
	if err != nil {
		return split, fmt.Errorf("visitgate: reading the package's work: %w", err)
	}
	for work.Next() {
		var kind, purpose, delivery string
		if err := work.Scan(&kind, &purpose, &delivery); err != nil {
			work.Close()
			return split, err
		}
		if delivery == "" {
			delivery = "staff"
		}
		split.add(slotKind(r, kind, purpose, delivery), delivery)
	}
	work.Close()
	if err := work.Err(); err != nil {
		return split, err
	}

	// 2. Group trainings in the package's training slots: what a session
	//    holds is what it counts.
	if planID != "" {
		held, err := q.Query(ctx, `
SELECT COALESCE(a.delivery_type, '')
FROM core_activity_slot sl
JOIN activity a ON a.id = sl.activity_id
LEFT JOIN activity_catalogue_item t5 ON t5.id = a.training_course_id
LEFT JOIN activity_catalogue_item ci ON ci.id = a.catalogue_item_id
WHERE sl.core_plan_id = $1 AND sl.activity_type = 'training' AND sl.activity_id IS NOT NULL AND sl.activity_id <> ''
  AND a.cluster_id IS NOT NULL AND a.activity_type = ANY($2) AND a.deleted_at IS NULL
  AND NOT (a.project_id = ANY($3) AND a.project_id IS NOT NULL)
  AND NOT ((t5.universal_training AND t5.universal_training IS NOT NULL)
        OR (ci.universal_training AND ci.universal_training IS NOT NULL)
        OR EXISTS (SELECT 1 FROM activity t6 JOIN activity_catalogue_item t7 ON t7.id = t6.training_course_id
                   WHERE t6.paired_school_visit_id = a.id AND t7.universal_training))
  AND NOT (a.status = ANY($4))`, planID, c.ClusterTrainingTypes, outside, c.UncreditedStatuses)
		if err != nil {
			return split, fmt.Errorf("visitgate: reading the package's group trainings: %w", err)
		}
		for held.Next() {
			var delivery string
			if err := held.Scan(&delivery); err != nil {
				held.Close()
				return split, err
			}
			split.add(kindTraining, delivery)
		}
		held.Close()
		if err := held.Err(); err != nil {
			return split, err
		}
	}

	// 3. Hand-overs waiting to be dated: the running year's.
	if fy == operational {
		handovers, err := q.Query(ctx, `
SELECT COALESCE(pa.project_id, ''), COALESCE(pa.support_type, ''), COALESCE(pa.visit_number, '') <> '',
  COALESCE(pa.training_number, '') <> '', COALESCE(pa.purpose_of_visit, ''), COALESCE(pa.expected_activity_type, ''),
  COALESCE(ci.is_training_course AND ci.universal_training, false)
FROM partner_assignment pa
LEFT JOIN activity_catalogue_item ci ON ci.id = pa.training_course_id
WHERE pa.school_id = $1 AND pa.status = ANY($2)`, school.ID, r.UnscheduledHandoverStatuses)
		if err != nil {
			return split, fmt.Errorf("visitgate: reading the package's hand-overs: %w", err)
		}
		defer handovers.Close()
		for handovers.Next() {
			var h handover
			if err := handovers.Scan(&h.project, &h.support, &h.visitNumber, &h.trainingNumber, &h.purpose, &h.expected, &h.universal); err != nil {
				return split, err
			}
			switch assignmentKind(r, h, outside) {
			case kindVisit:
				split.PartnerPendingVisits++
			case kindTraining:
				split.PartnerPendingTrainings++
			}
		}
		if err := handovers.Err(); err != nil {
			return split, err
		}
	}
	return split, nil
}

// slotKind is package_credit.slot_kind_for at a school (no cluster).
func slotKind(r Rules, activityType, purpose, delivery string) string {
	c := r.Core
	if purpose == r.CompanionPurpose {
		return kindVisit
	}
	if slices.Contains(c.OutreachVisitPurposes, purpose) || slices.Contains(c.OutreachVisitTypes, activityType) {
		return ""
	}
	if slices.Contains(c.DataCollectionVisitTypes, activityType) || slices.Contains(c.DataCollectionVisitPurposes, purpose) {
		// Staff's SSA Support is a package visit; a partner's is not.
		if delivery != "partner" {
			return kindVisit
		}
		return ""
	}
	if slices.Contains(c.PackageVisitTypes, activityType) {
		return kindVisit
	}
	if slices.Contains(c.PackageTrainingTypes, activityType) {
		return kindTraining
	}
	return ""
}

type handover struct {
	project, support, purpose, expected    string
	visitNumber, trainingNumber, universal bool
}

// assignmentKind is package_credit.assignment_kind.
func assignmentKind(r Rules, h handover, outside []string) string {
	c := r.Core
	if h.project != "" && slices.Contains(outside, h.project) {
		return ""
	}
	if h.universal {
		return ""
	}
	switch support := strings.ToLower(strings.TrimSpace(h.support)); support {
	case kindVisit, kindTraining:
		return support
	}
	if h.visitNumber {
		return kindVisit
	}
	if h.trainingNumber {
		return kindTraining
	}
	if slices.Contains(c.NonPackageVisitPurposes, h.purpose) {
		return ""
	}
	expected := h.expected
	if expected == "" && h.purpose != "" {
		expected = c.PurposeActivityTypes[h.purpose]
	}
	if slices.Contains(c.PackageTrainingTypes, expected) || expected == "in_school_training" {
		return kindTraining
	}
	if slices.Contains(c.PackageVisitTypes, expected) {
		return kindVisit
	}
	return ""
}

// decideCore is visit_gate._decide for a Core school: each side holds two
// of each kind; SSA Support goes to a partner only while the year has no
// SSA.
func (g *Gate) decideCore(r Rules) {
	caps := r.Core.Caps
	s := g.Split
	if s.HasPackage {
		if s.StaffVisits >= caps.StaffVisits {
			g.StaffCanSchedule = false
			g.StaffReason = fmt.Sprintf("Staff core visits complete on this package (%d/%d). The other %d visits are the partner's.",
				s.StaffVisits, caps.StaffVisits, caps.PartnerVisits)
		}
		if s.PartnerHeldVisits() >= caps.PartnerVisits {
			g.CanAssignVisit = false
			g.AssignVisitReason = fmt.Sprintf("Partner core visits complete on this package (%d/%d). The other %d visits are staff's.",
				s.PartnerHeldVisits(), caps.PartnerVisits, caps.StaffVisits)
			g.AssignVisitCode = CodeCorePackageSideComplete
		}
		trainingsOpen := s.PartnerHeldTrainings() < caps.PartnerTrainings
		if !g.CanAssignVisit && !trainingsOpen {
			g.CanAssignPartner = false
			g.AssignReason = fmt.Sprintf("The partner's half of this package is taken: %d/%d visits and %d/%d trainings.",
				s.PartnerHeldVisits(), caps.PartnerVisits, s.PartnerHeldTrainings(), caps.PartnerTrainings)
		}
	}
	if g.HasSSA {
		g.CanAssignSSA = false
		g.AssignSSAReason = fmt.Sprintf("%s has completed its SSA for FY%s. SSA Support is assigned to a partner only where the year's SSA is still to be collected.",
			g.School.Name, g.FY)
		g.AssignSSACode = CodeCurrentFYSSAExists
	}
}

// SplitOf is package_split.package_split(school, fy): a Core school's split
// for fy, the running year being operational. Any other school's is empty.
func SplitOf(ctx context.Context, q Querier, r Rules, school School, fy, operational string) (CoreSplit, error) {
	if ruleFor(r, school.Type) != "core" {
		return CoreSplit{}, nil
	}
	outside, err := projectsOutsideSSA(ctx, q, r)
	if err != nil {
		return CoreSplit{}, err
	}
	return splitOf(ctx, q, r, school, fy, operational, outside)
}
