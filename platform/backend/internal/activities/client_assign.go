package activities

import (
	"context"
	"errors"
	"fmt"
	"slices"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/cuid"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schoolprofile"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/visitgate"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/workplan"
)

// The Planning page's Assign to Partner save (planning_views.
// assign_partner_action_view), at a school no Core package holds.
const (
	clientNoItem         = "No approved Partner Activity is configured for this reason."
	clientNoTrainingItem = "The standard In-school Training profile must be active before a training can be assigned. Ask the Country Director to restore it."
	clientFollowUpNeeds  = "Select the completed training this assignment follows up."
	clientSourceNotDone  = "Choose a completed current-FY training this School did."
	clientSourceNotHere  = "A source session is only valid for Training Follow Up."
	noMapping            = "This Catalogue item has no active intervention mapping."
	notCanonical         = "Choose a valid canonical SSA intervention."
	nothingToInherit     = "The selected source Activity has no intervention to inherit. Choose a valid source Training or ask IA to repair its mapping."
	inheritNeedsTarget   = "Choose the Training or support Activity being followed up, or select one current unresolved SSA intervention."
	// clientDedupWindow is the view's DEDUP_WINDOW: a double-click is the
	// same submission.
	clientDedupWindow = 15 * time.Second
	// What a hand-over commits the school to (eligibility.handover_context).
	handOverSSASupport = "partner_ssa_support"
	handOverVisit      = "partner_visit"
)

var (
	// clientAssignFields are what the drawer posts (mobile_feed.
	// planning_drawers.SAVED_FIELDS["assign"] and its school).
	clientAssignFields = map[string]bool{
		"school_id": true, "partner_id": true, "purpose_of_visit": true, "catalogue_item_id": true,
		"activity_type": true, "focus_intervention": true, "source_activity_id": true,
	}
	// partnerPurposeFallback is purposes._fallback_for_activity_type.
	partnerPurposeFallback = map[string]string{
		"in_school_training": "in_school_training", "training": "in_school_training",
		"school_improvement_training": "in_school_training", "training_follow_up_visit": followUpPurpose,
	}
	// oneCommitmentTypes are visit_gate.ONE_COMMITMENT_SCHOOL_TYPES.
	oneCommitmentTypes = []string{"client", "core_trained", "core_graduate"}
)

// ClientAssignRequest is the Planning drawer's Assign to Partner as posted.
type ClientAssignRequest struct {
	SchoolCode, PartnerID, Purpose, ItemID string
	ActivityType, Focus, SourceActivityID  string
}

// ClientAssignRequestFromValues reads the drawer's values; false when it
// names something this save does not take (a cluster, a project, notes).
func ClientAssignRequestFromValues(schoolCode string, values map[string]string) (ClientAssignRequest, bool) {
	for name, value := range values {
		if !clientAssignFields[name] && strings.TrimSpace(value) != "" {
			return ClientAssignRequest{}, false
		}
	}
	text := func(name string) string { return strings.TrimSpace(values[name]) }
	req := ClientAssignRequest{
		SchoolCode: strings.TrimSpace(schoolCode), PartnerID: text("partner_id"), Purpose: text("purpose_of_visit"),
		ItemID: text("catalogue_item_id"), ActivityType: text("activity_type"), Focus: text("focus_intervention"),
		SourceActivityID: text("source_activity_id"),
	}
	// request.POST.get("activity_type", "school_visit"): only an absent field
	// takes the default.
	if _, posted := values["activity_type"]; !posted {
		req.ActivityType = "school_visit"
	}
	return req, true
}

// normalisePartnerPurpose is normalise_visit_purpose(for_partner=True).
func normalisePartnerPurpose(purpose, activityType string) (string, error) {
	if purpose == "" {
		if fallback, ok := partnerPurposeFallback[activityType]; ok {
			return fallback, nil
		}
		return ssaSupportPurpose, nil
	}
	label := rules.Purposes.Labels[purpose]
	if label == "" {
		label = purpose
	}
	if in(rules.Purposes.Retired, purpose) {
		return "", refuse("%s is no longer scheduled on its own. Choose In-school Training for this work.", label)
	}
	if !in(partnerPurposes, purpose) {
		return "", refuse("%s cannot be assigned to a delivery partner.", label)
	}
	return purpose, nil
}

// mapping is an active activity_intervention_mapping, in _mapping's order.
type mapping struct {
	Mode, Intervention string
	Primary            bool
}

func readMappings(ctx context.Context, q Querier, itemID string) ([]mapping, error) {
	rows, err := q.Query(ctx, `SELECT mapping_mode, COALESCE(intervention, ''), is_primary FROM activity_intervention_mapping
WHERE catalogue_item_id = $1 AND active ORDER BY is_primary DESC, priority, id`, itemID)
	if err != nil {
		return nil, fmt.Errorf("activities: reading the item's mappings: %w", err)
	}
	return pgx.CollectRows(rows, func(r pgx.CollectableRow) (mapping, error) {
		var m mapping
		err := r.Scan(&m.Mode, &m.Intervention, &m.Primary)
		return m, err
	})
}

func canonicalNamed(focus string) bool {
	_, ok := rules.labels[focus]
	return ok
}

// mappedIntervention is resolve_activity_intervention for a hand-over (its
// intervention is never optional).
func mappedIntervention(mappings []mapping, requested string, source *followedSession) (string, error) {
	if len(mappings) == 0 {
		return "", refuse(noMapping)
	}
	switch mappings[0].Mode {
	case "any_ssa_intervention":
		if requested == "" {
			return "", nil
		}
		if !canonicalNamed(requested) {
			return "", refuse(notCanonical)
		}
		return requested, nil
	case "ssa_completion_prerequisite", "administrative":
		return "", nil
	case "inherit_from_source_activity":
		switch {
		case source != nil:
			if source.inherited() == "" {
				return "", refuse(nothingToInherit)
			}
			return source.inherited(), nil
		case canonicalNamed(requested):
			return requested, nil
		case requested == "":
			return "", refuse(inheritNeedsTarget)
		}
		return "", refuse(notCanonical)
	}
	if requested != "" {
		if !canonicalNamed(requested) {
			return "", refuse(notCanonical)
		}
		return requested, nil
	}
	var allowed []string
	for _, m := range mappings {
		if m.Primary && m.Intervention != "" {
			return m.Intervention, nil
		}
		if m.Intervention != "" {
			allowed = append(allowed, m.Intervention)
		}
	}
	if len(allowed) == 0 {
		return "", nil
	}
	slices.Sort(allowed)
	return allowed[0], nil
}

// handOverCommitment is eligibility.handover_context: data collection, a
// universal training (on top of every school's year), or the school's visit.
func handOverCommitment(kind, purpose string, universal bool) string {
	gate := schoolprofile.GateRules()
	switch {
	case in(gate.DataCollectionTypes, kind) || purpose == ssaSupportPurpose:
		return handOverSSASupport
	case universal:
		return ""
	}
	return handOverVisit
}

func clientAssignedMessage(partner string) string {
	return fmt.Sprintf("Assigned to %s. The partner schedules it from here.", partner)
}

func alreadyHandedOver(school string) string {
	return school + " already has this work planned, so nothing was added."
}

func clientCourseNotDelivered(partner, course string) string {
	return fmt.Sprintf("%s is not recorded as delivering %s. Choose a partner who delivers it, or add it to this partner's activities on their profile.", partner, course)
}

// programmeSchoolPartnerRefusal is visit_gate.programme_school_partner_refusal.
func programmeSchoolPartnerRefusal(school, schoolType string) string {
	label := rules.Gate.SchoolTypeLabels[schoolType]
	if label == "" {
		label = "Programme"
	}
	return fmt.Sprintf("%s is a %s school. Edify staff deliver its visits and trainings themselves; it is never assigned to a partner.", school, label)
}

// resolveAssignmentItem is resolve_assignment_item for one kind: the first
// effective standard-support item a partner may deliver, in the model's
// ordering (display_name, stable_code).
func resolveAssignmentItem(ctx context.Context, q Querier, kind string, on time.Time) (*item, error) {
	it, err := scanItem(q.QueryRow(ctx, `SELECT `+itemColumns+` FROM activity_catalogue_item i
WHERE `+effective+` AND i.partner_delivery_allowed AND i.standard_support AND i.workflow_kind = $2
ORDER BY i.display_name, i.stable_code LIMIT 1`, on.Format(time.DateOnly), kind))
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, nil
	}
	if err != nil {
		return nil, fmt.Errorf("activities: resolving the hand-over's item: %w", err)
	}
	return &it, nil
}

// clientHandOver is the save's decisions, made before its transaction.
type clientHandOver struct {
	h          *handOver
	sc         school
	course     *course
	commitment string
	fy         string
	years      []string
}

// AssignClientPartner makes the Planning drawer's Assign to Partner save, or
// refuses it in the existing words, or hands it on (ErrHandOn). The caller
// has asked can_assign_to_partner.
func (s *Service) AssignClientPartner(ctx context.Context, p auth.Principal, req ClientAssignRequest, origin Origin) (Answer, error) {
	if s.requests == nil || p.InActingAppointment || p.StaffProfileID == "" {
		return Answer{}, handOn("not an account Go saves the Planning hand-over for")
	}
	partner, err := readAssignablePartner(ctx, s.db, req.PartnerID)
	if err != nil {
		return Answer{}, err
	}
	if partner == nil {
		return Answer{}, handOn("a partner who may not take new work")
	}
	refusal, found, err := s.requests.OperationalRefusal(ctx, p, req.SchoolCode)
	if err != nil {
		return Answer{}, fmt.Errorf("activities: reading the school's door: %w", err)
	}
	if !found {
		return Answer{}, handOn("no such school")
	}
	if refusal != "" {
		return Answer{}, &Refusal{Message: refusal, Forbidden: true}
	}
	sc, err := schoolByIDOrCode(ctx, s.db, req.SchoolCode)
	if err != nil {
		return Answer{}, err
	}
	if sc == nil || in(rules.Gate.CoreRuleTypes, sc.Type) {
		return Answer{}, handOn("a Core school's hand-over from the Planning page holds a package slot")
	}
	c, err := s.prepareClientHandOver(ctx, p, req, *sc, *partner)
	if err != nil {
		return Answer{}, err
	}
	dup, err := recentHandOver(ctx, s.db, c.h, s.now())
	if err != nil {
		return Answer{}, err
	}
	if dup {
		return Answer{Message: alreadyHandedOver(sc.Name)}, nil
	}
	if err := s.assertClientDoors(ctx, c, *partner); err != nil {
		return Answer{}, err
	}
	if err := s.writeClientHandOver(ctx, c); err != nil {
		return Answer{}, err
	}
	s.announceHandOver(ctx, p, c.h, origin)
	return Answer{ActivityID: c.h.id, Status: handOverOpenStatus, Message: clientAssignedMessage(partner.Name)}, nil
}

// prepareClientHandOver is the view from its purpose to its idempotency
// guard, in its order.
func (s *Service) prepareClientHandOver(ctx context.Context, p auth.Principal, req ClientAssignRequest, sc school,
	partner assignPartner) (*clientHandOver, error) {
	now := s.now()
	today := dateOnly(now.In(s.kampala))
	purpose, err := normalisePartnerPurpose(req.Purpose, req.ActivityType)
	if err != nil {
		return nil, err
	}
	fy := schooldirectory.OperationalFY(now)
	h := &handOver{id: cuid.New(), school: sc.ID, schoolName: sc.Name, partnerID: partner.ID, partnerName: partner.Name,
		partnerUser: partner.UserID, partnerRole: partner.UserRole, staff: p.StaffProfileID, monitor: p.StaffProfileID,
		purpose: purpose, what: rules.Purposes.Labels[purpose], isDataCollection: purpose == ssaSupportPurpose, blankAsNull: true}
	focus := req.Focus
	var it *item
	var crs *course
	if purpose == rules.Pair.TrainingPurpose {
		if it, crs, err = s.handOverTraining(ctx, CoreAssignRequest{CourseID: req.ItemID, Focus: req.Focus}, h, partner, today); err != nil {
			return nil, err
		}
		if it == nil {
			return nil, refuse(clientNoTrainingItem)
		}
		focus = h.focus
	} else {
		if it, err = resolveAssignmentItem(ctx, s.db, rules.Purposes.ActivityTypes[purpose], today); err != nil {
			return nil, err
		}
		if it == nil {
			return nil, refuse(clientNoItem)
		}
		h.reason = visitHandOverReason(h.what)
	}
	if it.RequiresCluster {
		return nil, refuse(assignNeedsCluster)
	}
	h.itemID, h.kind = it.ID, it.WorkflowKind
	h.assignmentPurpose = it.DisplayName
	if crs != nil {
		h.assignmentPurpose = crs.Name
	}
	need, err := schoolNeedOf(ctx, pgNeed{s.db}, sc.ID, sc.ClusterID, now)
	if err != nil {
		return nil, err
	}
	if need.Record != nil {
		h.sourceSSA = need.Record.ID
	}
	source, focus, err := s.clientFollowUp(ctx, p, req, sc, purpose, focus, need, fy)
	if err != nil {
		return nil, err
	}
	mappings, err := readMappings(ctx, s.db, it.ID)
	if err != nil {
		return nil, err
	}
	if h.focus, err = mappedIntervention(mappings, focus, source); err != nil {
		return nil, err
	}
	if source != nil {
		h.sourceActivityID = source.ID
	}
	years := []string{fy}
	next, err := workplan.NextOpenFY(ctx, s.db, p.Country, now.In(s.kampala), s.kampala)
	if err != nil {
		return nil, fmt.Errorf("activities: reading the next open year: %w", err)
	}
	if next != "" && next != fy {
		years = append(years, next)
	}
	return &clientHandOver{h: h, sc: sc, course: crs, fy: fy, years: years,
		commitment: handOverCommitment(h.kind, purpose, crs != nil && crs.Universal)}, nil
}

// clientFollowUp is the view's Training Follow Up rules: the session it
// follows, and the intervention the hand-over aims at before its mapping.
func (s *Service) clientFollowUp(ctx context.Context, p auth.Principal, req ClientAssignRequest, sc school, purpose, focus string,
	need schoolNeed, fy string) (*followedSession, string, error) {
	switch {
	case purpose == followUpPurpose && req.SourceActivityID == "":
		needs, err := followUpNeedsTraining(ctx, s.db, p.Country, fy)
		if err != nil {
			return nil, "", err
		}
		if needs {
			return nil, "", refuse(clientFollowUpNeeds)
		}
		if focus == "" && len(need.Priorities) > 0 {
			focus = need.Priorities[0]
		}
		return nil, focus, nil
	case purpose == followUpPurpose:
		session, err := readFollowedSession(ctx, s.db, req.SourceActivityID, sc.ID)
		if err != nil {
			return nil, "", err
		}
		if session == nil || session.problem(sc.ID, fy) != "" {
			return nil, "", refuse(clientSourceNotDone)
		}
		return session, session.Focus, nil
	case req.SourceActivityID != "":
		return nil, "", refuse(clientSourceNotHere)
	}
	return nil, focus, nil
}

// recentHandOver is _recent_duplicate: the same hand-over made moments ago
// by the same staff member.
func recentHandOver(ctx context.Context, q Querier, h *handOver, now time.Time) (bool, error) {
	var dup bool
	err := q.QueryRow(ctx, `SELECT EXISTS (SELECT 1 FROM partner_assignment WHERE partner_id = $1 AND school_id = $2
  AND assigning_staff_id = $3 AND expected_activity_type = $4 AND created_at >= $5)`,
		h.partnerID, h.school, h.staff, h.kind, now.Add(-clientDedupWindow)).Scan(&dup)
	if err != nil {
		return false, fmt.Errorf("activities: reading the recent hand-overs: %w", err)
	}
	return dup, nil
}

// assertClientDoors is the visit gate's can_assign_partner, then
// create_assignment's doors before its transaction.
func (s *Service) assertClientDoors(ctx context.Context, c *clientHandOver, partner assignPartner) error {
	gate, err := s.gateOf(ctx, s.db, c.sc, c.fy)
	if err != nil {
		return err
	}
	if !gate.CanAssignPartner {
		return refuse("%s", gate.AssignReason)
	}
	if c.sc.closed() {
		return refuse("%s", rules.ClosedSchoolMessage)
	}
	if in(rules.Gate.OutreachOnlyTypes, c.sc.Type) {
		return refuse("%s", programmeSchoolPartnerRefusal(c.sc.Name, c.sc.Type))
	}
	if c.course != nil && !partnerDelivers(partner.Codes, c.course.Code) {
		return refuse("%s", clientCourseNotDelivered(partner.Name, c.course.Name))
	}
	return nil
}

func (s *Service) gateOf(ctx context.Context, q Querier, sc school, fy string) (visitgate.Gate, error) {
	gate, err := visitgate.Of(ctx, q, schoolprofile.GateRules(),
		visitgate.School{ID: sc.ID, Code: sc.Code, Name: sc.Name, Type: sc.Type}, fy, schooldirectory.OperationalFY(s.now()))
	if err != nil {
		return visitgate.Gate{}, fmt.Errorf("activities: reading the school's gate: %w", err)
	}
	return gate, nil
}

// assertClientRoom is _assert_school_has_room, read under the school's lock:
// SSA Support where the year's SSA is still to be collected, and one visit
// commitment in a year a hand-over may be dated in.
func (s *Service) assertClientRoom(ctx context.Context, q Querier, c *clientHandOver) error {
	switch c.commitment {
	case handOverSSASupport:
		if !in(rules.Gate.CoreRuleTypes, c.sc.Type) && !in(rules.Gate.ClientRuleTypes, c.sc.Type) {
			return nil
		}
		gate, err := s.gateOf(ctx, q, c.sc, c.fy)
		if err != nil {
			return err
		}
		if !gate.CanAssignSSA {
			return refuse("%s", gate.AssignSSAReason)
		}
	case handOverVisit:
		if !in(oneCommitmentTypes, c.sc.Type) {
			return nil
		}
		var first *visitgate.Gate
		for _, year := range c.years {
			gate, err := s.gateOf(ctx, q, c.sc, year)
			if err != nil {
				return err
			}
			if first == nil {
				first = &gate
			}
			if gate.CanAssignVisit {
				return nil
			}
		}
		return refuse("%s", first.AssignVisitReason)
	}
	return nil
}

// writeClientHandOver is create_assignment's transaction: the school's lock
// and room, the training ceiling, the model's own checks, then the row.
func (s *Service) writeClientHandOver(ctx context.Context, c *clientHandOver) error {
	tx, err := s.db.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite, IsoLevel: pgx.ReadCommitted})
	if err != nil {
		return fmt.Errorf("activities: opening the hand-over: %w", err)
	}
	defer func() { _ = tx.Rollback(ctx) }()
	if _, err := tx.Exec(ctx, `SELECT gateway_lock.lock_school($1)`, c.h.school); err != nil {
		return fmt.Errorf("activities: locking the school: %w", err)
	}
	if err := s.assertClientRoom(ctx, tx, c); err != nil {
		return err
	}
	if c.course != nil {
		set, err := ceilingSet(ctx, tx, c.h.staff, c.course.ID, c.fy)
		if err != nil {
			return err
		}
		if set {
			return handOn("a training ceiling is set for the course")
		}
	}
	if !c.h.isDataCollection {
		if err := anotherPartnerHolds(ctx, tx, c.h); err != nil {
			return err
		}
	}
	if err := s.assertNoOpenHandOver(ctx, tx, c.h, c.sc); err != nil {
		return err
	}
	if err := insertHandOver(ctx, tx, c.h, s.now()); err != nil {
		return err
	}
	if err := tx.Commit(ctx); err != nil {
		return fmt.Errorf("activities: committing the hand-over: %w", err)
	}
	return nil
}

// anotherPartnerHolds is assert_school_accepts_another_partner: a school
// another partner holds is handed on, as the Core hand-over does.
func anotherPartnerHolds(ctx context.Context, q Querier, h *handOver) error {
	var another bool
	err := q.QueryRow(ctx, `SELECT EXISTS (SELECT 1 FROM partner_assignment
    WHERE school_id = $1 AND partner_id <> $2 AND status <> $3)
  OR EXISTS (SELECT 1 FROM data_quality_issue WHERE school_id = $1 AND field_name = 'partner_assignment' AND status = 'open')`,
		h.school, h.partnerID, handOverReturned).Scan(&another)
	if err != nil {
		return fmt.Errorf("activities: reading the school's partners: %w", err)
	}
	if another {
		return handOn("another partner holds this school")
	}
	return nil
}
