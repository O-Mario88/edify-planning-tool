package activities

import (
	"context"
	"errors"
	"fmt"
	"sort"
	"strings"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/cuid"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schoolprofile"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/workplan"
)

// The bulk hand-over a list's tick bar opens (planning_views.
// bulk_assign_partner_drawer_view and bulk_action_view's "partner"): the
// planner's one partner and reason, each school through the single Assign's
// rules, a school waiting with the partner skipped, one the rules refuse
// named and left out.

const (
	bulkAssignNoPartner = "Select a partner before confirming."
	bulkAssignNoReason  = "Select the reason for assigning before confirming."
	bulkAssignFollowUp  = "A Training Follow Up names the training it follows, which differs from school to school. Assign it from each school's own Assign."
	bulkAssignNotes     = "Bulk Partner Assignment · final schedule and cost pending"
	bulkAssignNoSchools = "No schools selected"
)

// BulkAssignRequest is the drawer's post.
type BulkAssignRequest struct {
	Codes                             []string
	PartnerID, Purpose, Course, Focus string
}

// BulkAssignRow is one school of the drawer's list.
type BulkAssignRow struct {
	School   TickedSchool
	OK       bool
	Reason   string
	ClosedTo []string
}

// PartnerPurposes are PARTNER_VISIT_PURPOSES, value then label.
func PartnerPurposes() [][2]string {
	out := make([][2]string, 0, len(partnerPurposes))
	for _, value := range partnerPurposes {
		out = append(out, [2]string{value, rules.Purposes.Labels[value]})
	}
	return out
}

// bulkHandOverPurpose is _bulk_partner_handover's reason.
func bulkHandOverPurpose(raw, course string) (string, error) {
	if strings.TrimSpace(raw) == "" {
		return "", refuse(bulkAssignNoReason)
	}
	purpose, err := normalisePartnerPurpose(strings.TrimSpace(raw), "")
	if err != nil {
		return "", err
	}
	if purpose == rules.Pair.TrainingPurpose {
		if strings.TrimSpace(course) == "" {
			return "", refuse(assignNeedsCourse)
		}
		return "", handOn("a training handed over in bulk")
	}
	return purpose, nil
}

func bulkAssignedMessage(count int, partner string, skipped int, gated []string) string {
	message := fmt.Sprintf("Assigned %d %s to %s.", count, plural(count, "school", "schools"), partner)
	if skipped > 0 {
		message += fmt.Sprintf(" %d %s already waiting with this partner and left as they were.", skipped, plural(skipped, "was", "were"))
	}
	if len(gated) > 0 {
		message += " Not assigned (their support is not open to a partner now): " + strings.Join(gated, ", ") + "."
	}
	return message
}

// gatedName is the school as the confirmation names it: with refusal_label's
// words when a hand-over door refused it.
func gatedName(name string, refusal *Refusal) string {
	if refusal != nil && refusal.Label != "" {
		return name + " (" + refusal.Label + ")"
	}
	return name
}

// BulkAssignRows is the drawer's list: each ticked school in the portfolio,
// whether its gate takes a partner, and what it is closed to.
func (s *Service) BulkAssignRows(ctx context.Context, p auth.Principal, values []string) ([]BulkAssignRow, int, error) {
	schools, posted, err := s.TickedSchools(ctx, p, values)
	if err != nil {
		return nil, 0, err
	}
	fy := schooldirectory.OperationalFY(s.now())
	rows := make([]BulkAssignRow, 0, len(schools))
	for _, t := range schools {
		sc, err := schoolByIDOrCode(ctx, s.db, t.ID)
		if err != nil {
			return nil, 0, err
		}
		if sc == nil {
			return nil, 0, handOn("a ticked school gone")
		}
		gate, err := s.gateOf(ctx, s.db, *sc, fy)
		if err != nil {
			return nil, 0, err
		}
		row := BulkAssignRow{School: t, OK: gate.CanAssignPartner}
		if !gate.CanAssignPartner {
			row.Reason = gate.AssignReason
		} else {
			if gate.OneCommitment(schoolprofile.GateRules()) && !gate.CanAssignVisit {
				row.ClosedTo = append(row.ClosedTo, "No visit hand-over: "+gate.AssignVisitReason)
			}
			if !gate.CanAssignSSA {
				row.ClosedTo = append(row.ClosedTo, "No SSA Support: "+gate.AssignSSAReason)
			}
		}
		rows = append(rows, row)
	}
	return rows, posted - len(schools), nil
}

// bulkHandOver is one school's hand-over, decided before its transaction.
type bulkHandOver struct {
	c       *clientHandOver
	refusal *Refusal
	skip    bool
}

// BulkAssignPartner makes the bulk hand-over, or refuses it in the existing
// words, or hands it on (ErrHandOn) before anything is written. The caller
// has asked can_assign_to_partner.
func (s *Service) BulkAssignPartner(ctx context.Context, p auth.Principal, req BulkAssignRequest, origin Origin) (Answer, error) {
	if s.requests == nil || p.InActingAppointment || p.StaffProfileID == "" {
		return Answer{}, handOn("not an account Go saves the bulk hand-over for")
	}
	rows, _, err := s.BulkAssignRows(ctx, p, req.Codes)
	if err != nil {
		return Answer{}, err
	}
	var schools []TickedSchool
	for _, row := range rows {
		if row.OK {
			schools = append(schools, row.School)
		}
	}
	if len(schools) == 0 {
		return Answer{}, refuse(bulkAssignNoSchools)
	}
	if strings.TrimSpace(req.PartnerID) == "" {
		return Answer{}, refuse(bulkAssignNoPartner)
	}
	partner, err := readAssignablePartner(ctx, s.db, strings.TrimSpace(req.PartnerID))
	if err != nil {
		return Answer{}, err
	}
	if partner == nil {
		return Answer{}, handOn("a partner who may not take new work")
	}
	plan, it, err := s.bulkHandOverPlan(ctx, p, req)
	if err != nil {
		return Answer{}, err
	}
	// bulk_action_view's queryset order: the model's, newest school first.
	sort.SliceStable(schools, func(i, j int) bool { return schools[i].CreatedAt.After(schools[j].CreatedAt) })
	years, err := s.handOverYears(ctx, p)
	if err != nil {
		return Answer{}, err
	}
	planned := make([]bulkHandOver, len(schools))
	for i, t := range schools {
		if planned[i], err = s.planBulkHandOver(ctx, p, t, *partner, plan, it, years); err != nil {
			return Answer{}, err
		}
	}
	count, skipped, gated := 0, 0, []string{}
	for i, b := range planned {
		switch {
		case b.skip:
			skipped++
			continue
		case b.refusal != nil:
			gated = append(gated, gatedName(schools[i].Name, b.refusal))
			continue
		}
		err := s.writeClientHandOver(ctx, b.c)
		var refusal *Refusal
		switch {
		case errors.As(err, &refusal):
			gated = append(gated, gatedName(schools[i].Name, refusal))
			continue
		case errors.Is(err, ErrHandOn):
			s.logger.Warn("activities: a bulk hand-over was handed on after it was planned", "school", schools[i].Code, "err", err)
			gated = append(gated, schools[i].Name)
			continue
		case err != nil:
			return Answer{}, err
		}
		s.announceHandOver(ctx, p, b.c.h, origin)
		count++
	}
	return Answer{Message: bulkAssignedMessage(count, partner.Name, skipped, gated)}, nil
}

// bulkHandOverPlan is _bulk_partner_handover's purpose and item.
func (s *Service) bulkHandOverPlan(ctx context.Context, p auth.Principal, req BulkAssignRequest) (string, *item, error) {
	purpose, err := bulkHandOverPurpose(req.Purpose, req.Course)
	if err != nil {
		return "", nil, err
	}
	now := s.now()
	if purpose == followUpPurpose {
		needs, err := followUpNeedsTraining(ctx, s.db, p.Country, schooldirectory.OperationalFY(now))
		if err != nil {
			return "", nil, err
		}
		if needs {
			return "", nil, refuse(bulkAssignFollowUp)
		}
	}
	it, err := resolveAssignmentItem(ctx, s.db, rules.Purposes.ActivityTypes[purpose], dateOnly(now.In(s.kampala)))
	if err != nil {
		return "", nil, err
	}
	if it == nil {
		return "", nil, refuse(clientNoItem)
	}
	return purpose, it, nil
}

// planBulkHandOver is one school's turn of the loop up to create_assignment:
// the open hand-over skipped, the gate, then the single Assign's doors. A
// school Go does not take hands the whole selection on.
func (s *Service) planBulkHandOver(ctx context.Context, p auth.Principal, t TickedSchool, partner assignPartner, purpose string, it *item,
	years []string) (bulkHandOver, error) {
	sc, err := schoolByIDOrCode(ctx, s.db, t.ID)
	if err != nil {
		return bulkHandOver{}, err
	}
	if sc == nil || in(rules.Gate.CoreRuleTypes, sc.Type) {
		return bulkHandOver{}, handOn("a Core school's hand-over holds a package slot")
	}
	var open bool
	if err := s.db.QueryRow(ctx, `SELECT EXISTS (SELECT 1 FROM partner_assignment WHERE school_id = $1 AND partner_id = $2
  AND status = ANY($3) AND NOT outside_ssa)`, sc.ID, partner.ID, []string{handOverAssigned, handOverOpenStatus}).Scan(&open); err != nil {
		return bulkHandOver{}, fmt.Errorf("activities: reading the partner's open hand-overs: %w", err)
	}
	if open {
		return bulkHandOver{skip: true}, nil
	}
	now := s.now()
	fy := schooldirectory.OperationalFY(now)
	gate, err := s.gateOf(ctx, s.db, *sc, fy)
	if err != nil {
		return bulkHandOver{}, err
	}
	if !gate.CanAssignPartner {
		return bulkHandOver{refusal: &Refusal{Message: gate.AssignReason}}, nil
	}
	label := rules.Purposes.Labels[purpose]
	h := &handOver{id: cuid.New(), school: sc.ID, schoolName: sc.Name, partnerID: partner.ID, partnerName: partner.Name,
		partnerUser: partner.UserID, partnerRole: partner.UserRole, staff: p.StaffProfileID, monitor: p.StaffProfileID,
		purpose: purpose, what: label, isDataCollection: purpose == ssaSupportPurpose, blankAsNull: true,
		notes: bulkAssignNotes, reason: visitHandOverReason(label), itemID: it.ID, kind: it.WorkflowKind,
		assignmentPurpose: it.DisplayName}
	if it.RequiresCluster {
		return bulkHandOver{refusal: &Refusal{Message: assignNeedsCluster}}, nil
	}
	need, err := schoolNeedOf(ctx, pgNeed{s.db}, sc.ID, sc.ClusterID, now)
	if err != nil {
		return bulkHandOver{}, err
	}
	if need.Record != nil {
		h.sourceSSA = need.Record.ID
	}
	focus := ""
	if purpose == followUpPurpose && len(need.Priorities) > 0 {
		focus = need.Priorities[0]
	}
	mappings, err := readMappings(ctx, s.db, it.ID)
	if err != nil {
		return bulkHandOver{}, err
	}
	if h.focus, err = mappedIntervention(mappings, focus, nil); err != nil {
		var refusal *Refusal
		if errors.As(err, &refusal) {
			return bulkHandOver{refusal: refusal}, nil
		}
		return bulkHandOver{}, err
	}
	c := &clientHandOver{h: h, sc: *sc, fy: fy, years: years, commitment: handOverCommitment(h.kind, purpose, false)}
	if err := s.assertClientDoors(ctx, c, partner); err != nil {
		var refusal *Refusal
		if errors.As(err, &refusal) {
			return bulkHandOver{refusal: refusal}, nil
		}
		return bulkHandOver{}, err
	}
	if !h.isDataCollection {
		if err := anotherPartnerHolds(ctx, s.db, h); err != nil {
			return bulkHandOver{}, err
		}
	}
	return bulkHandOver{c: c}, nil
}

// handOverYears is visit_gate.handover_years: the operational year, and the
// next once it is open for planning.
func (s *Service) handOverYears(ctx context.Context, p auth.Principal) ([]string, error) {
	now := s.now()
	fy := schooldirectory.OperationalFY(now)
	years := []string{fy}
	next, err := workplan.NextOpenFY(ctx, s.db, p.Country, now.In(s.kampala), s.kampala)
	if err != nil {
		return nil, fmt.Errorf("activities: reading the next open year: %w", err)
	}
	if next != "" && next != fy {
		years = append(years, next)
	}
	return years, nil
}
