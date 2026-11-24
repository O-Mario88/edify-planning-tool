// Package visitgate is the existing planning rule apps.planning.visit_gate:
// a school's support visit of the year, and whether its work may still go
// to a partner (owners 2026-09-28 and 2026-10-08: one support visit a year
// at a client, Core Trained or Core Graduate school, staff's or a
// partner's; SSA Support handed over only while the year has no SSA;
// Champion schools take donor and story visits and are never handed over).
//
// It ports what a school's profile reads: the lock on the staff support
// visit and why, and whether Assign to Partner is open and why not, by the
// client rule (one support visit a year) and the Core package rule (2 + 2
// staff and partner, core.go). A closed school is not asked here: the
// profile hides the doors of a closed school before the gate is read.
package visitgate

import (
	"context"
	"encoding/json"
	"fmt"
	"slices"
	"strings"

	"github.com/jackc/pgx/v5"
)

// Querier is the read the gate needs; *pgxpool.Pool satisfies it.
type Querier interface {
	Query(ctx context.Context, sql string, args ...any) (pgx.Rows, error)
	QueryRow(ctx context.Context, sql string, args ...any) pgx.Row
}

// Rules are the vocabularies the gate reads, exported from the existing
// code (manage.py export_school_profile_rules, "gate").
type Rules struct {
	ClientRuleTypes             []string          `json:"client_rule_types"`
	CoreRuleTypes               []string          `json:"core_rule_types"`
	OneCommitmentTypes          []string          `json:"one_commitment_types"`
	OutreachOnlyTypes           []string          `json:"outreach_only_types"`
	StaffVisitCap               int               `json:"staff_visit_cap"`
	NotLiveStatuses             []string          `json:"not_live_statuses"`
	CompanionPurpose            string            `json:"companion_purpose"`
	FollowUpVisitTypes          []string          `json:"follow_up_visit_types"`
	SSASupportVisitTypes        []string          `json:"ssa_support_visit_types"`
	InSchoolSupportTypes        []string          `json:"in_school_support_types"`
	ClientVisitLegacyTypes      []string          `json:"client_visit_legacy_types"`
	UnscheduledHandoverStatuses []string          `json:"unscheduled_handover_statuses"`
	DataCollectionTypes         []string          `json:"data_collection_types"`
	DataCollectionPurposes      []string          `json:"data_collection_purposes"`
	GeneralIntervention         string            `json:"general_intervention"`
	LockLabels                  map[string]string `json:"lock_labels"`
	Core                        CoreRules         `json:"core"`
	// Set by the package that holds the rest of the export: SsaIntervention
	// values and SchoolType labels.
	SSAInterventions []string          `json:"-"`
	SchoolTypeLabels map[string]string `json:"-"`
}

// School is what the gate reads of a school; Code is its School ID, which
// a Core plan is filed under.
type School struct {
	ID, Code, Name, Type string
}

const (
	codeStaffVisitScheduled  = "STAFF_VISIT_SCHEDULED"
	codePartnerVisitAssigned = "PARTNER_VISIT_ASSIGNED"

	lockUnlocked         = "unlocked"
	lockStaffScheduled   = "staff_visit_scheduled"
	lockPartnerScheduled = "partner_visit_scheduled"
	lockPartnerAwaiting  = "awaiting_partner_schedule"
	lockNotApplicable    = "not_applicable"
)

// Gate is a school's year, as visit_gate.VisitGate holds it.
type Gate struct {
	School School
	FY     string
	// Rule is "client", "core" or "none".
	Rule string
	// StaffVisits are the year's staff support visits (a Training Follow Up
	// or an In-school Training).
	StaffVisits int
	// Partner work holding the school's visit: dated, and handed over but
	// not dated yet. A Special Project's work holds nothing.
	PartnerHoldingDated, PartnerHoldingPending int
	// Every partner holding the visit, the first first.
	PartnerNames []string
	HasSSA       bool

	StaffCanSchedule bool
	StaffCode        string
	StaffReason      string

	CanAssignVisit    bool
	AssignVisitReason string
	CanAssignSSA      bool
	AssignSSAReason   string
	CanAssignPartner  bool
	AssignReason      string

	// The Core package's split (package_split): what each side holds, and
	// whether the school has a package for the year at all.
	Split CoreSplit
}

// OneCommitment is visit_gate's one_commitment: a client school whose type
// takes one visit commitment a year, staff's or a partner's.
func (g Gate) OneCommitment(r Rules) bool { return g.oneCommitment(r) }

func (g Gate) oneCommitment(r Rules) bool {
	return g.Rule == "client" && slices.Contains(r.OneCommitmentTypes, g.School.Type)
}

func (g Gate) partnerHolding() int { return g.PartnerHoldingDated + g.PartnerHoldingPending }

// holder names who holds the visit for a sentence (VisitGate.holder).
func (g Gate) holder() string {
	if len(g.PartnerNames) > 0 {
		return strings.Join(g.PartnerNames, " and ")
	}
	return "a partner"
}

// lockState is VisitGate.lock_state for an open, non-Core school.
func (g Gate) lockState(r Rules) string {
	switch {
	case slices.Contains(r.OutreachOnlyTypes, g.School.Type):
		return lockNotApplicable
	case g.StaffCanSchedule:
		return lockUnlocked
	case g.Rule == "core":
		return r.Core.LockPackageComplete
	case g.StaffCode == codePartnerVisitAssigned:
		if g.PartnerHoldingDated > 0 {
			return lockPartnerScheduled
		}
		return lockPartnerAwaiting
	default:
		return lockStaffScheduled
	}
}

// LockLabel is VisitGate.lock_label: the lock's words where the staff
// support visit is locked, and "" where it is not.
func (g Gate) LockLabel(r Rules) string {
	state := g.lockState(r)
	if state == lockUnlocked || state == lockNotApplicable {
		return ""
	}
	return r.LockLabels[state]
}

func ruleFor(r Rules, schoolType string) string {
	switch {
	case slices.Contains(r.CoreRuleTypes, schoolType):
		return "core"
	case slices.Contains(r.ClientRuleTypes, schoolType):
		return "client"
	default:
		return "none"
	}
}

// Of is visit_gate.visit_gate(school, fy) for an open school; operational
// is the running year (get_operational_fy), which decides whether a Core
// school's package for fy may still be made and whether its waiting
// hand-overs count.
func Of(ctx context.Context, q Querier, r Rules, school School, fy, operational string) (Gate, error) {
	g := Gate{
		School: school, FY: fy, Rule: ruleFor(r, school.Type),
		StaffCanSchedule: true, CanAssignVisit: true, CanAssignSSA: true, CanAssignPartner: true,
	}
	if g.Rule == "none" {
		return g, nil
	}
	outside, err := projectsOutsideSSA(ctx, q, r)
	if err != nil {
		return g, err
	}
	if g.Rule == "core" {
		if g.Split, err = splitOf(ctx, q, r, school, fy, operational, outside); err != nil {
			return g, err
		}
	} else {
		if err := g.countVisits(ctx, q, r, outside); err != nil {
			return g, err
		}
		if err := g.countHandovers(ctx, q, r, outside); err != nil {
			return g, err
		}
	}
	if err := q.QueryRow(ctx, `
SELECT EXISTS (SELECT 1 FROM ssa_record WHERE school_id = $1 AND fy = $2 AND deleted_at IS NULL AND verification_status = 'confirmed')`,
		school.ID, fy).Scan(&g.HasSSA); err != nil {
		return g, fmt.Errorf("visitgate: reading the year's SSA: %w", err)
	}
	if g.Rule == "core" {
		g.decideCore(r)
	} else {
		g.decide(r)
	}
	return g, nil
}

// projectsOutsideSSA is projects.models.projects_outside_ssa: live projects
// whose targets name General and no SSA intervention (Alumni).
func projectsOutsideSSA(ctx context.Context, q Querier, r Rules) ([]string, error) {
	rows, err := q.Query(ctx, `
SELECT id, COALESCE(intervention, ''), COALESCE(target_interventions, '[]'::jsonb) FROM project WHERE deleted_at IS NULL`)
	if err != nil {
		return nil, fmt.Errorf("visitgate: reading projects: %w", err)
	}
	defer rows.Close()
	out := []string{}
	for rows.Next() {
		var id, intervention string
		var raw []byte
		if err := rows.Scan(&id, &intervention, &raw); err != nil {
			return nil, err
		}
		targets := []string{}
		if err := json.Unmarshal(raw, &targets); err != nil {
			return nil, fmt.Errorf("visitgate: reading project %s's targets: %w", id, err)
		}
		if intervention != "" && !slices.Contains(targets, intervention) {
			targets = append(targets, intervention)
		}
		measured := !slices.Contains(targets, r.GeneralIntervention)
		for _, t := range targets {
			measured = measured || slices.Contains(r.SSAInterventions, t)
		}
		if !measured {
			out = append(out, id)
		}
	}
	return out, rows.Err()
}

// supportVisits is visit_gates' client tally of the year's live support
// visits, with the existing query's joins, so a visit paired with two
// trainings counts as it does there. The partner's name is read from every
// partner row, deleted or not (Partner.all_objects).
const supportVisits = `
FROM activity a
LEFT JOIN partner p ON p.id = a.assigned_partner_id
LEFT JOIN activity_catalogue_item ci ON ci.id = a.catalogue_item_id
LEFT JOIN activity_eligibility_rule er ON er.catalogue_item_id = ci.id
LEFT JOIN activity_catalogue_item t5 ON t5.id = a.training_course_id
LEFT JOIN activity t6 ON t6.paired_school_visit_id = a.id
LEFT JOIN activity_catalogue_item t7 ON t7.id = t6.training_course_id
WHERE a.deleted_at IS NULL AND a.fy = $1 AND NOT (a.status = ANY($2)) AND a.school_id = $3
  AND NOT (a.project_id IS NOT NULL AND a.project_id = ANY($4))
  AND NOT (a.purpose_type IS NOT NULL AND a.purpose_type = $5)
  AND NOT (ci.counts_toward_client_visit IS NOT NULL AND ci.counts_toward_client_visit
           AND er.counts_toward_entitlement IS NOT NULL AND NOT er.counts_toward_entitlement)
  AND NOT ((t5.universal_training IS NOT NULL AND t5.universal_training)
        OR (ci.universal_training IS NOT NULL AND ci.universal_training)
        OR (t7.universal_training IS NOT NULL AND t7.universal_training))
  AND (((a.activity_type = ANY($6) OR ci.counts_toward_client_visit
         OR (a.activity_type = ANY($7) AND a.catalogue_item_id IS NULL))
        AND NOT (a.activity_type = ANY($8)))
       OR a.activity_type = ANY($9))`

func (g *Gate) countVisits(ctx context.Context, q Querier, r Rules, outside []string) error {
	args := []any{g.FY, r.NotLiveStatuses, g.School.ID, outside, r.CompanionPurpose,
		r.FollowUpVisitTypes, r.ClientVisitLegacyTypes, r.SSASupportVisitTypes, r.InSchoolSupportTypes}
	if err := q.QueryRow(ctx, `SELECT COUNT(a.id)`+supportVisits+`
  AND a.delivery_type IS DISTINCT FROM 'partner'`, args...).Scan(&g.StaffVisits); err != nil {
		return fmt.Errorf("visitgate: counting staff support visits: %w", err)
	}
	// The partner's dated visits that hold the school's visit: not a
	// Special Project's (owner, 2026-10-08).
	rows, err := q.Query(ctx, `SELECT COALESCE(p.name, '')`+supportVisits+`
  AND a.delivery_type = 'partner' AND a.project_id IS NULL ORDER BY a.created_at`, args...)
	if err != nil {
		return fmt.Errorf("visitgate: reading partner visits: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var name string
		if err := rows.Scan(&name); err != nil {
			return err
		}
		g.PartnerHoldingDated++
		g.nameHolder(name)
	}
	return rows.Err()
}

// countHandovers is visit_gates' hand-overs still waiting on the partner.
func (g *Gate) countHandovers(ctx context.Context, q Querier, r Rules, outside []string) error {
	rows, err := q.Query(ctx, `
SELECT COALESCE(pa.partner_id, ''), COALESCE(p.name, ''), pa.project_id IS NOT NULL,
  COALESCE(pa.expected_activity_type, ''), COALESCE(pa.purpose_of_visit, ''),
  COALESCE(ci.is_training_course AND ci.universal_training, false)
FROM partner_assignment pa
LEFT JOIN partner p ON p.id = pa.partner_id
LEFT JOIN activity_catalogue_item ci ON ci.id = pa.training_course_id
WHERE pa.school_id = $1 AND pa.status = ANY($2)
  AND NOT (pa.project_id IS NOT NULL AND pa.project_id = ANY($3))
ORDER BY pa.created_at`, g.School.ID, r.UnscheduledHandoverStatuses, outside)
	if err != nil {
		return fmt.Errorf("visitgate: reading hand-overs: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var partnerID, name, expected, purpose string
		var project, universal bool
		if err := rows.Scan(&partnerID, &name, &project, &expected, &purpose, &universal); err != nil {
			return err
		}
		// Data collection is assigned on any school and is not its visit; a
		// universal training is on top of the school's entitlement; a
		// Special Project's hand-over waits beside the school's own support.
		dataCollection := slices.Contains(r.DataCollectionTypes, expected) || slices.Contains(r.DataCollectionPurposes, purpose)
		if dataCollection || universal || project {
			continue
		}
		g.PartnerHoldingPending++
		if partnerID != "" {
			g.nameHolder(name)
		}
	}
	return rows.Err()
}

func (g *Gate) nameHolder(name string) {
	if name != "" && !slices.Contains(g.PartnerNames, name) {
		g.PartnerNames = append(g.PartnerNames, name)
	}
}

// decide is visit_gate._decide for the client rule, in its words.
func (g *Gate) decide(r Rules) {
	name, fy := g.School.Name, g.FY
	if g.StaffVisits >= r.StaffVisitCap {
		g.StaffCanSchedule = false
		g.StaffCode = codeStaffVisitScheduled
		g.StaffReason = fmt.Sprintf("%s has had its staff support visit (a Training Follow Up or an In-school Training) for FY%s (%d/%d).",
			name, fy, g.StaffVisits, r.StaffVisitCap)
	} else if g.oneCommitment(r) && g.partnerHolding() > 0 {
		g.StaffCanSchedule = false
		g.StaffCode = codePartnerVisitAssigned
		g.StaffReason = fmt.Sprintf("%s is assigned to %s for its support visit in FY%s. Staff plan a Training Follow Up or an In-school Training there only once the school is withdrawn from the partner.",
			name, g.holder(), fy)
	}
	if g.oneCommitment(r) {
		if g.StaffVisits > 0 {
			g.CanAssignVisit = false
			g.AssignVisitReason = fmt.Sprintf("%s already has its staff support visit for FY%s. It is not handed to a partner for another.", name, fy)
		} else if g.partnerHolding() > 0 {
			g.CanAssignVisit = false
			g.AssignVisitReason = fmt.Sprintf("%s is already assigned to %s for its support visit in FY%s. A school is handed to a partner for one visit a year.",
				name, g.holder(), fy)
		}
	}
	// SSA Support handed to a partner (_decide_ssa_support).
	if g.HasSSA {
		g.CanAssignSSA = false
		g.AssignSSAReason = fmt.Sprintf("%s has completed its SSA for FY%s. SSA Support is assigned to a partner only where the year's SSA is still to be collected.", name, fy)
	}
	if !g.CanAssignVisit && !g.CanAssignSSA {
		g.CanAssignPartner = false
		g.AssignReason = g.AssignVisitReason + " " + g.AssignSSAReason
	}
	// Champion takes donor and story visits only (programme_school_partner_refusal).
	if slices.Contains(r.OutreachOnlyTypes, g.School.Type) {
		label, ok := r.SchoolTypeLabels[g.School.Type]
		if !ok {
			label = "Programme"
		}
		refusal := fmt.Sprintf("%s is a %s school. Edify staff deliver its visits and trainings themselves; it is never assigned to a partner.",
			name, label)
		g.CanAssignPartner, g.CanAssignVisit, g.CanAssignSSA = false, false, false
		g.AssignReason, g.AssignVisitReason, g.AssignSSAReason = refusal, refusal, refusal
	}
}
