package activities

import (
	"context"
	"errors"
	"fmt"
	"net/url"
	"slices"
	"strconv"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/audit"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/cuid"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schoolprofile"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/visitgate"
)

// The Core Schools partner hand-over (core_schools_views.core_assign_partner_action).
const (
	assignNeedsPurpose  = "Select the purpose of this support."
	assignNeedsCourse   = "Select the Training the partner delivers."
	assignCourseClosed  = "The selected Training is not approved for Partner delivery."
	assignFollowUpNeeds = "Select the completed training this support follows up."
	assignNoItem        = "No approved Catalogue Activity is configured for this support. Ask the Country Director to configure one."
	assignBadSlot       = "Choose an available support slot."
	assignNeedsCluster  = "This Catalogue Activity requires a Cluster."
	ssaCollectionKind   = "school_visit_ssa_collection"
	ssaSupportPurpose   = "ssa_support"
	handOverOpenStatus  = "pending_scheduling"
	handOverAssigned    = "assigned"
	handOverReturned    = "returned_to_staff"
	assignEvent         = "core_school_assigned"
	partnerQueueEvent   = "partner_scheduled_activity"
	partnerCategory     = "partner"
	partnerQueueTitle   = "New assignment from Edify staff"
	partnerQueueBody    = "A school or activity slot was assigned to your organisation — it is now in your planning queue."
	coreAssignedTitle   = "New Core School Support Assignment"
	coreSchoolsRoute    = "/core-schools"
	openCoreSchoolLabel = "Open Core School"
)

// partnerPurposes are PARTNER_VISIT_PURPOSES.
var (
	coreAssignRoles  = []string{"CCEO", "Program Lead"}
	partnerPurposes  = []string{"in_school_training", followUpPurpose, ssaSupportPurpose}
	coreAssignFields = map[string]bool{
		"csrfmiddlewaretoken": true, "school_id": true, "partner_id": true, "purpose_of_visit": true, "notes": true,
		"source_activity_id": true, "training_course_id": true, "focus_intervention": true, "visit_training_number": true,
	}
)

// CoreAssignRequest is the Core assign form as posted.
type CoreAssignRequest struct {
	SchoolCode, PartnerID, Purpose, Notes string
	SourceActivityID, CourseID, Focus     string
	SlotNumber                            string
}

// CoreAssignRequestFromForm reads the form; false when Go does not take it.
func CoreAssignRequestFromForm(schoolCode string, form url.Values) (CoreAssignRequest, bool) {
	for name, values := range form {
		if coreAssignFields[name] {
			continue
		}
		for _, value := range values {
			if strings.TrimSpace(value) != "" {
				return CoreAssignRequest{}, false
			}
		}
	}
	text := func(name string) string { return strings.TrimSpace(form.Get(name)) }
	return CoreAssignRequest{
		SchoolCode: strings.TrimSpace(schoolCode), PartnerID: text("partner_id"), Purpose: text("purpose_of_visit"),
		Notes: text("notes"), SourceActivityID: text("source_activity_id"), CourseID: text("training_course_id"),
		Focus: text("focus_intervention"), SlotNumber: text("visit_training_number"),
	}, true
}

// corePartnerSideRefusal is PackageSplit.refusal for the partner's half.
func corePartnerSideRefusal(school, kind string, used int) string {
	many := kind + "s"
	return fmt.Sprintf("%s already has its %d partner core %s (%d/%d). A Core package is %d staff and %d partner %s, so the next %s here is the staff's.",
		school, coreSideCap, many, used, coreSideCap, coreSideCap, coreSideCap, many, kind)
}

// partnerDelivers is capabilities.delivers: a partner with nothing recorded
// is not yet scoped and is offered everything.
func partnerDelivers(codes []string, courseCode string) bool {
	return len(codes) == 0 || slices.Contains(codes, courseCode)
}

// trainingHandOverReason names the priorities the course counts toward.
func trainingHandOverReason(titles []string, category string) string {
	if len(titles) == 0 {
		return fmt.Sprintf("Governed %s training.", category)
	}
	sorted := slices.Sorted(slices.Values(titles))
	return "Priority activity: " + strings.Join(slices.Compact(sorted), ", ")
}

func visitHandOverReason(label string) string {
	return label + " selected by the assigning staff member."
}

func coreAssignedBody(school, what string) string {
	return fmt.Sprintf("Your organization has been assigned to support %s with %s. Choose the date to deliver it.", school, what)
}

func coreAssignedMessage(partner string) string {
	return fmt.Sprintf("Core support assigned to %s successfully.", partner)
}

// partnerQueueLink is NotificationLinkResolver's partner_scheduled_activity:
// the link follows the role of the person told.
func partnerQueueLink(role string) (route, label string) {
	switch strings.ToLower(role) {
	case "partnerfieldofficer":
		return "/my-plan", "Partner My Plan"
	case "cceo":
		return "/my-plan", "Staff My Plan"
	case "program lead", "projectleader":
		return "/partner-oversight/", "Open Partner Oversight"
	case "projectcoordinator":
		return "/my-plan", "Open My Plan"
	}
	return "/dashboard", "View Dashboard"
}

// assignPartner is the partner the form names.
type assignPartner struct {
	ID, Name, UserID, UserRole string
	Codes                      []string
}

// readAssignablePartner is assignable_partners().get(id): active, on no hold,
// and not a Loan Partner.
func readAssignablePartner(ctx context.Context, q Querier, id string) (*assignPartner, error) {
	var a assignPartner
	var user, role *string
	err := q.QueryRow(ctx, `SELECT p.id, p.name, p.user_id, u.active_role, p.activity_codes FROM partner p
LEFT JOIN "user" u ON u.id = p.user_id
WHERE p.id = $1 AND p.deleted_at IS NULL AND p.active_status AND p.partner_role <> 'loan'
  AND NOT EXISTS (SELECT 1 FROM partner_hold h WHERE h.partner_id = p.id AND h.lifted_at IS NULL)`, id).
		Scan(&a.ID, &a.Name, &user, &role, &a.Codes)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, nil
	}
	if err != nil {
		return nil, fmt.Errorf("activities: reading the partner: %w", err)
	}
	if user != nil {
		a.UserID = *user
	}
	if role != nil {
		a.UserRole = *role
	}
	return &a, nil
}

// handOver is the row the save writes, decided before its transaction.
type handOver struct {
	id, school, schoolName, partnerID, partnerName, partnerUser string
	partnerRole                                                 string
	staff, purpose, kind, focus, notes, reason                  string
	itemID, courseID, sourceActivityID, sourceSSA               string
	what, supportType, visitNumber, trainingNumber              string
	planID                                                      string
	slotKind                                                    string
	// monitor and assignmentPurpose are the Planning hand-over's
	// monitoring_staff_id and purpose; the Core form sets neither.
	monitor, assignmentPurpose string
	// blankAsNull: the Planning view leaves notes and the slot fields None,
	// where the Core form posts them as text.
	blankAsNull      bool
	preferred        int
	isDataCollection bool
}

// AssignCorePartner makes the Core assign form's save, or refuses it in the
// existing words, or hands it on (ErrHandOn).
func (s *Service) AssignCorePartner(ctx context.Context, p auth.Principal, req CoreAssignRequest, origin Origin) (Answer, error) {
	if s.requests == nil || p.InActingAppointment || p.StaffProfileID == "" || !in(coreAssignRoles, p.ActiveRole) {
		return Answer{}, handOn("not a role Go saves the Core assign form for")
	}
	now := s.now()
	today := dateOnly(now.In(s.kampala))
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
	if sc == nil || sc.Code != req.SchoolCode || !in(rules.Gate.CoreRuleTypes, sc.Type) {
		return Answer{}, handOn("not a Core school by its code")
	}
	partner, err := readAssignablePartner(ctx, s.db, req.PartnerID)
	if err != nil {
		return Answer{}, err
	}
	if partner == nil {
		return Answer{}, handOn("a partner who may not take new work")
	}
	h, err := s.prepareHandOver(ctx, p, req, *sc, *partner, now, today)
	if err != nil {
		return Answer{}, err
	}
	if err := s.writeHandOver(ctx, h, *sc, now); err != nil {
		return Answer{}, err
	}
	s.afterHandOver(ctx, p, h, origin)
	return Answer{ActivityID: h.id, Status: handOverOpenStatus, Message: coreAssignedMessage(partner.Name)}, nil
}

// prepareHandOver is the view up to its create_assignment, in its order.
func (s *Service) prepareHandOver(ctx context.Context, p auth.Principal, req CoreAssignRequest, sc school, partner assignPartner,
	now, today time.Time) (*handOver, error) {
	if req.Purpose == "" {
		return nil, refuse(assignNeedsPurpose)
	}
	if !in(partnerPurposes, req.Purpose) {
		return nil, handOn("a purpose a partner is not handed")
	}
	fy := schooldirectory.OperationalFY(now)
	planID, err := readCorePlan(ctx, s.db, sc.Code, fy)
	if err != nil {
		return nil, err
	}
	if planID == "" {
		return nil, refuse(noActivePackage)
	}
	need, err := schoolNeedOf(ctx, pgNeed{s.db}, sc.ID, sc.ClusterID, now)
	if err != nil {
		return nil, err
	}
	h := &handOver{id: cuid.New(), school: sc.ID, schoolName: sc.Name, partnerID: partner.ID, partnerName: partner.Name,
		partnerUser: partner.UserID, partnerRole: partner.UserRole, staff: p.StaffProfileID, purpose: req.Purpose, notes: req.Notes, planID: planID,
		what: rules.Purposes.Labels[req.Purpose], isDataCollection: req.Purpose == ssaSupportPurpose}
	if need.Record != nil {
		h.sourceSSA = need.Record.ID
	}
	var it *item
	var c *course
	switch req.Purpose {
	case rules.Pair.TrainingPurpose:
		if it, c, err = s.handOverTraining(ctx, req, h, partner, today); err != nil {
			return nil, err
		}
	case ssaSupportPurpose:
		h.reason = visitHandOverReason(h.what)
		if it, err = resolveForKind(ctx, s.db, ssaCollectionKind, today); err != nil {
			return nil, err
		}
	default:
		h.reason = visitHandOverReason(h.what)
		if it, err = resolveForKind(ctx, s.db, coreVisitKind, today); err != nil {
			return nil, err
		}
		if err := s.handOverFollowUp(ctx, p, req, h, sc, need, fy); err != nil {
			return nil, err
		}
	}
	if it == nil {
		return nil, refuse(assignNoItem)
	}
	if it.RequiresCluster {
		return nil, refuse(assignNeedsCluster)
	}
	h.itemID, h.kind = it.ID, it.WorkflowKind
	number := 1
	if req.SlotNumber != "" {
		if number, err = strconv.Atoi(req.SlotNumber); err != nil {
			return nil, refuse(assignBadSlot)
		}
	}
	if !h.isDataCollection {
		if err := s.reserveHandOverSlot(ctx, h, sc, c, number, fy, now); err != nil {
			return nil, err
		}
	}
	if c != nil {
		if !partnerDelivers(partner.Codes, c.Code) {
			return nil, refuse("%s is not recorded as delivering %s. Choose a partner who delivers it, or add it to this partner's activities on their profile.", partner.Name, c.Name)
		}
		set, err := ceilingSet(ctx, s.db, p.StaffProfileID, c.ID, fy)
		if err != nil {
			return nil, err
		}
		if set {
			return nil, handOn("a training ceiling is set for the course")
		}
	}
	if err := s.assertHandOverRoom(ctx, s.db, h, sc, now); err != nil {
		return nil, err
	}
	return h, s.assertNoOpenHandOver(ctx, s.db, h, sc)
}

// handOverTraining is the view's training branch.
func (s *Service) handOverTraining(ctx context.Context, req CoreAssignRequest, h *handOver, partner assignPartner, today time.Time) (*item, *course, error) {
	if req.CourseID == "" {
		return nil, nil, refuse(assignNeedsCourse)
	}
	c, err := offeredCourse(ctx, s.db, req.CourseID, today)
	if err != nil {
		return nil, nil, err
	}
	if c == nil {
		return nil, nil, refuse(notOffered)
	}
	var allowed bool
	if err := s.db.QueryRow(ctx, `SELECT partner_delivery_allowed FROM activity_catalogue_item WHERE id = $1`, c.ID).Scan(&allowed); err != nil {
		return nil, nil, fmt.Errorf("activities: reading the course's delivery: %w", err)
	}
	if !allowed {
		return nil, nil, refuse(assignCourseClosed)
	}
	focus, taken := c.focus()
	if !taken {
		return nil, nil, handOn("a course Go does not take (its intervention mapping)")
	}
	if focus == "" && req.Focus != "" && canonicalFocus(req.Focus) {
		focus = req.Focus
	}
	rows, err := s.db.Query(ctx, `SELECT m.title FROM hr_milestone_activity_rule r
JOIN hr_priority_milestone m ON m.id = r.milestone_id WHERE r.catalogue_item_id = $1 AND r.active`, c.ID)
	if err != nil {
		return nil, nil, fmt.Errorf("activities: reading the course's priorities: %w", err)
	}
	titles, err := pgx.CollectRows(rows, pgx.RowTo[string])
	if err != nil {
		return nil, nil, fmt.Errorf("activities: reading a priority: %w", err)
	}
	it, err := resolveForKind(ctx, s.db, rules.Pair.TrainingKind, today)
	if err != nil {
		return nil, nil, err
	}
	h.focus, h.courseID = focus, c.ID
	h.reason = trainingHandOverReason(titles, c.Category)
	h.what = h.what + ": " + c.Name
	return it, c, nil
}

// handOverFollowUp is the view's Training Follow Up branch.
func (s *Service) handOverFollowUp(ctx context.Context, p auth.Principal, req CoreAssignRequest, h *handOver, sc school, need schoolNeed, fy string) error {
	if req.SourceActivityID == "" {
		needs, err := followUpNeedsTraining(ctx, s.db, p.Country, fy)
		if err != nil {
			return err
		}
		if needs {
			return refuse(assignFollowUpNeeds)
		}
		if len(need.Priorities) > 0 {
			h.focus = need.Priorities[0]
		}
		return nil
	}
	session, err := readFollowedSession(ctx, s.db, req.SourceActivityID, sc.ID)
	if err != nil {
		return err
	}
	if session == nil || session.problem(sc.ID, fy) != "" {
		return refuse(coreSourceNotEligible)
	}
	h.sourceActivityID, h.focus = session.ID, session.inherited()
	return nil
}

// reserveHandOverSlot is assert_can_assign: the partner's half, then the slot.
func (s *Service) reserveHandOverSlot(ctx context.Context, h *handOver, sc school, c *course, number int, fy string, now time.Time) error {
	h.slotKind, h.supportType = coreSlotVisit, "Visit"
	if c != nil {
		h.slotKind, h.supportType = coreSlotTraining, "Training"
	}
	split, err := visitgate.SplitOf(ctx, s.db, schoolprofile.GateRules(),
		visitgate.School{ID: sc.ID, Code: sc.Code, Name: sc.Name, Type: sc.Type}, fy, schooldirectory.OperationalFY(now))
	if err != nil {
		return fmt.Errorf("activities: reading the package's split: %w", err)
	}
	used := split.PartnerHeldVisits()
	if c != nil {
		used = split.PartnerHeldTrainings()
	}
	if split.HasPackage && used >= coreSideCap {
		return refuse("%s", corePartnerSideRefusal(sc.Name, h.slotKind, used))
	}
	slots, err := readCoreSlots(ctx, s.db, h.planID, h.slotKind, "")
	if err != nil {
		return err
	}
	open := openCoreSlotAt(slots, number, coreSlotTaken)
	if open == nil {
		return handOn("the Core package has no open slot for the hand-over")
	}
	h.preferred = open.Sequence
	if c != nil {
		h.trainingNumber = strconv.Itoa(open.Sequence)
	} else {
		h.visitNumber = strconv.Itoa(open.Sequence)
	}
	return nil
}

// assertHandOverRoom is _assert_school_has_room, and what the model's save
// asks of a school another partner already holds: that case is handed on.
func (s *Service) assertHandOverRoom(ctx context.Context, q Querier, h *handOver, sc school, now time.Time) error {
	if h.isDataCollection {
		gate, err := visitgate.Of(ctx, q, schoolprofile.GateRules(),
			visitgate.School{ID: sc.ID, Code: sc.Code, Name: sc.Name, Type: sc.Type},
			schooldirectory.OperationalFY(now), schooldirectory.OperationalFY(now))
		if err != nil {
			return fmt.Errorf("activities: reading the school's gate: %w", err)
		}
		if !gate.CanAssignSSA {
			return refuse("%s", gate.AssignSSAReason)
		}
	}
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

// assertNoOpenHandOver is PartnerAssignment.open_duplicate's refusal.
func (s *Service) assertNoOpenHandOver(ctx context.Context, q Querier, h *handOver, sc school) error {
	var open bool
	err := q.QueryRow(ctx, `SELECT EXISTS (SELECT 1 FROM partner_assignment
WHERE school_id = $1 AND partner_id = $2 AND status = ANY($3) AND NOT outside_ssa
  AND (COALESCE(purpose_of_visit, '') = $4) = $5
  AND COALESCE(support_type, '') = $6 AND COALESCE(visit_number, '') = $7 AND COALESCE(training_number, '') = $8)`,
		h.school, h.partnerID, []string{handOverAssigned, handOverOpenStatus}, ssaSupportPurpose, h.isDataCollection,
		h.supportType, h.visitNumber, h.trainingNumber).Scan(&open)
	if err != nil {
		return fmt.Errorf("activities: reading the open hand-overs: %w", err)
	}
	if open {
		return refuse("%s is already assigned to %s and is waiting for the partner to schedule it. A school is assigned to the same partner only once.", sc.Name, h.partnerName)
	}
	return nil
}

// writeHandOver is create_assignment's transaction and commit_assign.
func (s *Service) writeHandOver(ctx context.Context, h *handOver, sc school, now time.Time) error {
	tx, err := s.db.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite, IsoLevel: pgx.ReadCommitted})
	if err != nil {
		return fmt.Errorf("activities: opening the hand-over: %w", err)
	}
	defer func() { _ = tx.Rollback(ctx) }()
	if _, err := tx.Exec(ctx, `SELECT gateway_lock.lock_school($1)`, h.school); err != nil {
		return fmt.Errorf("activities: locking the school: %w", err)
	}
	if err := s.assertHandOverRoom(ctx, tx, h, sc, now); err != nil {
		return err
	}
	if err := s.assertNoOpenHandOver(ctx, tx, h, sc); err != nil {
		return err
	}
	var slot *coreSlot
	if h.slotKind != "" {
		slots, err := readCoreSlots(ctx, tx, h.planID, h.slotKind, " FOR UPDATE")
		if err != nil {
			return err
		}
		if slot = openCoreSlotAt(slots, h.preferred, coreSlotTaken); slot == nil || slot.Sequence != h.preferred {
			return handOn("the hand-over's slot was taken")
		}
	}
	if err := insertHandOver(ctx, tx, h, now); err != nil {
		return err
	}
	if slot != nil {
		if _, err := tx.Exec(ctx, `UPDATE core_activity_slot SET status = 'Assigned', assigned_partner_id = $2,
  assigned_partner_name = $3, owner = 'partner', updated_at = $4 WHERE id = $1`, slot.ID, h.partnerID, h.partnerName, now); err != nil {
			return fmt.Errorf("activities: reserving the package slot: %w", err)
		}
	}
	if err := tx.Commit(ctx); err != nil {
		return fmt.Errorf("activities: committing the hand-over: %w", err)
	}
	return nil
}

func insertHandOver(ctx context.Context, tx pgx.Tx, h *handOver, now time.Time) error {
	text := func(v string) any {
		if h.blankAsNull {
			return optString(v)
		}
		return v
	}
	_, err := tx.Exec(ctx, `INSERT INTO partner_assignment (id, created_at, updated_at, assigning_staff_id, focus_intervention,
  expected_activity_type, status, notes, partner_id, school_id, support_type, training_number, visit_number, purpose_of_visit,
  assignment_mode, catalogue_item_id, catalogue_snapshot, override_reason, recommendation_reason, source_ssa_id,
  source_activity_id, reassignment_sequence, training_course_id, resolution, resolution_note, outside_ssa,
  monitoring_staff_id, purpose)
SELECT $1, $2, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, 'specific_activity', i.id, `+catalogueSnapshotSQL+`,
  '', $14, $15, $16, 0, $17, '', '', false, $19, $20
FROM activity_catalogue_item i WHERE i.id = $18`,
		h.id, now, h.staff, optString(h.focus), h.kind, handOverOpenStatus, text(h.notes), h.partnerID, h.school, text(h.supportType),
		text(h.trainingNumber), text(h.visitNumber), h.purpose, h.reason, optString(h.sourceSSA), optString(h.sourceActivityID),
		optString(h.courseID), h.itemID, optString(h.monitor), optString(h.assignmentPurpose))
	if err != nil {
		return fmt.Errorf("activities: writing the hand-over: %w", err)
	}
	return nil
}

// afterHandOver is what the save's signals and view do once the row is made,
// in their order. None of it can undo the hand-over.
func (s *Service) afterHandOver(ctx context.Context, p auth.Principal, h *handOver, origin Origin) {
	s.announceHandOver(ctx, p, h, origin)
	if err := s.auditHandOver(ctx, "assign_core_partner", p.UserID, p.ActiveRole, h, origin, nil); err != nil {
		s.logger.Warn("activities: the form's audit row was not written", "assignment", h.id, "err", err)
	}
	if h.partnerUser != "" {
		if err := s.sendNotice(ctx, h.school, p.UserID, origin, scheduledNotice{
			title: coreAssignedTitle, body: coreAssignedBody(h.schoolName, h.what), event: assignEvent, category: partnerCategory,
			contextType: "School", route: coreSchoolsRoute, label: openCoreSchoolLabel, recipient: h.partnerUser,
		}); err != nil {
			s.logger.Warn("activities: the partner was not told", "assignment", h.id, "err", err)
		}
	}
}

// announceHandOver is the hand-over's post_save signals (apps/partners/
// signals.py): its audit row, then the partner's queue notice.
func (s *Service) announceHandOver(ctx context.Context, p auth.Principal, h *handOver, origin Origin) {
	if err := s.auditHandOver(ctx, "partner.assigned", h.staff, "", h, origin, map[string]any{
		"partner_id": h.partnerID, "school_id": h.school, "cluster_id": nil, "project_id": nil,
	}); err != nil {
		s.logger.Warn("activities: the hand-over's audit row was not written", "assignment", h.id, "err", err)
	}
	if h.partnerUser != "" {
		route, label := partnerQueueLink(h.partnerRole)
		if err := s.sendNotice(ctx, h.id, p.UserID, origin, scheduledNotice{
			title: partnerQueueTitle, body: partnerQueueBody, event: partnerQueueEvent, category: partnerCategory,
			contextType: "partner_assignment", route: route, label: label, recipient: h.partnerUser,
		}); err != nil {
			s.logger.Warn("activities: the partner was not told", "assignment", h.id, "err", err)
		}
	}
}

func (s *Service) auditHandOver(ctx context.Context, action, actor, role string, h *handOver, origin Origin, payload map[string]any) error {
	now := s.now()
	tx, err := s.db.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite})
	if err != nil {
		return err
	}
	defer func() { _ = tx.Rollback(ctx) }()
	cover, err := coverageStamp(ctx, tx, actor, now)
	if err != nil {
		return err
	}
	var data any
	if stamped := withStamps(payload, cover); len(stamped) > 0 {
		data = stamped
	}
	if _, err := audit.Append(ctx, tx, audit.Entry{
		Action: action, SubjectKind: audit.Text("PartnerAssignment"), SubjectID: audit.Text(h.id),
		ActorID: audit.Text(actor), ActorRole: &role, Success: true, Payload: data,
		IPAddress: nilIfEmpty(origin.IP), UserAgent: nilIfEmpty(origin.UserAgent), CorrelationID: nilIfEmpty(origin.CorrelationID),
	}, now); err != nil {
		return err
	}
	return tx.Commit(ctx)
}
