package activities

// The fifth save (docs/migration/32): an In-school Training and its school
// visit, planned together as one decision from Planning's Schedule drawer
// (schedule_action_view 2142–2160 and 2462–2470, then
// apps/planning/services.schedule_in_school_training_pair). The training
// delivers a course and costs nothing; the visit, the same day, is the
// journey and carries the visit's cost (owner, 2026-09-28). Both rows are
// `_create`'s, read for this case as 27.6 reads it for a visit; the pair's
// own steps are said where they come.
//
// Go takes the owner's own staff pair at a school in their own portfolio
// that is not a Core school, for a course linked to one SSA intervention
// or to none (an orientation), with no facilitator, project, priority or
// ceiling set for the course. Everything else is handed on unchanged.

import (
	"context"
	"errors"
	"fmt"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// The pair's words: the view's (2142–2147, 2463–2468) and the service's
// (planning/services.py 689–719), each a literal there.
const (
	noCourse         = "Select the Training to deliver."
	notOffered       = "Select a training from the governed Training Catalogue."
	profilesInactive = "The standard In-school Training and School Visit profiles must both be active before this work can be scheduled."
	pairNoun         = "In-school training and school visit"
	pairWithSSANoun  = "In-school training and school visit with SSA collection"
)

// course is a Training Catalogue course as the in-school picker offers it
// (activity_catalogue.availability.in_school_training_course_options).
type course struct {
	ID, Code, Name, Kind, Category, Indicator string
	Universal                                 bool
	Mappings                                  []courseMapping
}

type courseMapping struct {
	Mode, Intervention string
	Primary            bool
}

// offeredCourse is validate_in_school_training_course_selection(id, on):
// an effective course staff may deliver, or nil.
func offeredCourse(ctx context.Context, q Querier, id string, on time.Time) (*course, error) {
	var c course
	err := q.QueryRow(ctx, `SELECT i.id, i.stable_code, i.display_name, i.workflow_kind, i.training_category,
  i.ssa_indicator_label, i.universal_training
FROM activity_catalogue_item i
WHERE `+effective+` AND i.is_training_course AND i.staff_delivery_allowed AND i.id = $2`,
		on.Format(time.DateOnly), id).Scan(&c.ID, &c.Code, &c.Name, &c.Kind, &c.Category, &c.Indicator, &c.Universal)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, nil
	}
	if err != nil {
		return nil, fmt.Errorf("activities: reading the course: %w", err)
	}
	rows, err := q.Query(ctx, `SELECT mapping_mode, COALESCE(intervention, ''), is_primary
FROM activity_intervention_mapping WHERE catalogue_item_id = $1 AND active ORDER BY is_primary DESC, priority, id`, c.ID)
	if err != nil {
		return nil, fmt.Errorf("activities: reading the course's mappings: %w", err)
	}
	c.Mappings, err = pgx.CollectRows(rows, func(r pgx.CollectableRow) (courseMapping, error) {
		var m courseMapping
		return m, r.Scan(&m.Mode, &m.Intervention, &m.Primary)
	})
	if err != nil {
		return nil, fmt.Errorf("activities: reading the course's mappings: %w", err)
	}
	return &c, nil
}

// focus is the intervention the course carries, and whether Go takes the
// course: one active primary mapping, fixed to one of the canonical
// interventions (intervention_for, resolve_activity_intervention) or
// administrative (an orientation: none). The picker's ssaIntervention, the
// training's focus and the visit's are then the same value.
func (c course) focus() (string, bool) {
	if len(c.Mappings) != 1 || !c.Mappings[0].Primary {
		return "", false
	}
	m := c.Mappings[0]
	switch m.Mode {
	case rules.Pair.FixedMode:
		_, canonical := rules.labels[m.Intervention]
		return m.Intervention, canonical
	case rules.Pair.AdministrativeMode:
		return "", m.Intervention == ""
	}
	return "", false
}

func (c course) modes() []string {
	modes := make([]string, len(c.Mappings))
	for i, m := range c.Mappings {
		modes[i] = m.Mode
	}
	return modes
}

// conflicts is the view's pinned-item test (2226–2273) for a course: its
// workflow kind is another purpose's, so the view would replace it.
func (c course) conflicts() bool {
	for purpose, kind := range rules.Purposes.ActivityTypes {
		if kind == c.Kind && kind != rules.Pair.TrainingKind && purpose != rules.Pair.TrainingPurpose {
			return true
		}
	}
	return false
}

// ceilingSet is whether the officer has a training ceiling for the course
// this year: reserve_for_activity then counts their schools, which Go does
// not port (handed on).
func ceilingSet(ctx context.Context, q Querier, staffID, courseID, fy string) (bool, error) {
	var set bool
	if err := q.QueryRow(ctx, `SELECT EXISTS (SELECT 1 FROM training_ceiling WHERE staff_id = $1 AND training_id = $2 AND fy = $3)`,
		staffID, courseID, fy).Scan(&set); err != nil {
		return false, fmt.Errorf("activities: reading the training ceiling: %w", err)
	}
	return set, nil
}

// pairPlan is both rows, decided before the transaction.
type pairPlan struct {
	training, visit *plan
	course          course
	message         string
	// corePlanID is the Core package the two are credited to, if any.
	corePlanID string
}

// IsPairPurpose is whether the drawer's purpose plans the pair.
func IsPairPurpose(purpose string) bool {
	purpose = strings.TrimSpace(purpose)
	return purpose == rules.Pair.TrainingPurpose || purpose == rules.Pair.CollectsSSAPurpose
}

// schedulePair makes the pair, or refuses it in the existing words, or
// hands it on (ErrHandOn).
func (s *Service) schedulePair(ctx context.Context, p auth.Principal, req Request, origin Origin) (Answer, error) {
	pp, err := s.preparePair(ctx, p, req, origin)
	if err != nil {
		return Answer{}, err
	}
	rowID, err := s.writePair(ctx, pp)
	if err != nil {
		return Answer{}, err
	}
	s.afterPair(ctx, pp, rowID)
	answer, err := s.answer(ctx, pp.training)
	if err != nil {
		return Answer{}, err
	}
	answer.Message = pp.message
	answer.PairedVisitID = pp.visit.row.id
	return answer, nil
}

// preparePair is the view and the pair's service up to the training's
// transaction, then the visit's create up to its own, in their order.
func (s *Service) preparePair(ctx context.Context, p auth.Principal, req Request, origin Origin) (*pairPlan, error) {
	now := s.now()
	today := dateOnly(now.In(s.kampala))
	if !in(rules.Doors.Drawer, p.ActiveRole) {
		message := noPermission
		if p.ActiveRole == rules.Doors.AdminRole {
			message = rules.Doors.AdminRefusal
		}
		return nil, &Refusal{Message: message, Forbidden: true}
	}
	purpose := strings.TrimSpace(req.Purpose)
	date := strings.TrimSpace(req.Date)
	requester := in(rules.Doors.Requesters, p.ActiveRole)
	if (requester && s.requests == nil) || p.InActingAppointment || p.StaffProfileID == "" ||
		!IsPairPurpose(purpose) || (date != "" && !isoDate.MatchString(date)) || req.SourceActivityID != "" {
		// A posted focus needs no case: schedule_in_school_training_pair
		// replaces it with the course's own intervention.
		return nil, handOn("not the owner's own In-school Training")
	}
	// split_training_purpose (2030): the SSA purpose is the pair, its visit
	// collecting the SSA.
	collects := purpose == rules.Pair.CollectsSSAPurpose
	if date == "" {
		return nil, refuse("Pick the date this is planned for before scheduling it.")
	}
	day, err := time.ParseInLocation(time.DateOnly, date, s.kampala)
	if err != nil {
		return nil, refuse("That scheduled date is not a valid calendar date.")
	}
	// The course (2142–2160), offered today.
	courseID := strings.TrimSpace(req.CatalogueItemID)
	if courseID == "" {
		return nil, refuse(noCourse)
	}
	c, err := offeredCourse(ctx, s.db, courseID, today)
	if err != nil {
		return nil, err
	}
	if c == nil {
		return nil, refuse(notOffered)
	}
	focus, taken := c.focus()
	if !taken || c.conflicts() {
		return nil, handOn("a course Go does not take (its intervention mapping or kind)")
	}
	var target visitTarget
	if requester {
		asked, err := s.requestTarget(ctx, p, req.SchoolID, purpose, now)
		if err != nil {
			return nil, err
		}
		target = *asked
	} else {
		visited, owner, err := s.visitSchool(ctx, p, req.SchoolID, purpose, now)
		if err != nil {
			return nil, err
		}
		target = visitTarget{school: *visited, responsible: owner}
	}
	sc, responsible, approvalOwner := &target.school, target.responsible, target.approvalOwner
	// schedule_in_school_training_pair (689–719): the course offered on the
	// day (get_selectable_item then finds it too), and both profiles.
	onDay, err := offeredCourse(ctx, s.db, courseID, day)
	if err != nil {
		return nil, err
	}
	if onDay == nil {
		return nil, refuse(notOffered)
	}
	trainingProfile, err := resolveForKind(ctx, s.db, rules.Pair.TrainingKind, day)
	if err != nil {
		return nil, err
	}
	visitProfile, err := resolveForKind(ctx, s.db, rules.Pair.VisitKind, day)
	if err != nil {
		return nil, err
	}
	if trainingProfile == nil || visitProfile == nil {
		return nil, refuse(profilesInactive)
	}
	// A request holds no package slot until its owner approves it.
	corePlanID := ""
	if approvalOwner == "" {
		if corePlanID, err = s.routeCorePair(ctx, *sc, *c, day); err != nil {
			return nil, err
		}
	}
	training, err := s.pairTraining(ctx, p, req, origin, now, today, day, *sc, responsible, approvalOwner, *c, focus, trainingProfile.ID)
	if err != nil {
		return nil, err
	}
	visit, err := s.pairVisit(ctx, p, req, origin, now, today, day, *sc, responsible, approvalOwner, *c, focus, collects, visitProfile.ID, training)
	if err != nil {
		return nil, err
	}
	noun := pairNoun
	if collects {
		noun = pairWithSSANoun
	}
	var message string
	if approvalOwner != "" {
		who, err := staffName(ctx, s.db, approvalOwner, schoolOwnerStandIn)
		if err != nil {
			return nil, err
		}
		message = requestedMessage(who)
	} else {
		owner := ""
		if responsible != p.StaffProfileID && responsible != p.UserID {
			if owner, err = staffName(ctx, s.db, responsible, schoolCCEOStandIn); err != nil {
				return nil, err
			}
		}
		message = pairConfirmation(noun, owner)
	}
	return &pairPlan{training: training, visit: visit, course: *c, message: message, corePlanID: corePlanID}, nil
}

// pairConfirmation is the view's sentence: on the person's own plan, or on
// the plan of the owner it was filed against.
func pairConfirmation(noun, owner string) string {
	if owner == "" {
		return noun + " scheduled. It is on your My Plan — keep planning."
	}
	return fmt.Sprintf("%s scheduled onto %s's My Plan, because the responsible staff member comes from the school's owner.", noun, owner)
}

// standardItem is get_selectable_item(profile) and the checks the first
// save makes of its item: a standard-support profile of the kind, priced
// with no participants, mapped to any intervention.
func standardItem(ctx context.Context, q Querier, id, kind string, day time.Time) (*item, error) {
	it, err := selectableItem(ctx, q, id, day)
	if err != nil {
		return nil, err
	}
	if it == nil {
		return nil, refuse("The selected Activity Catalogue item is inactive, retired, outside its effective dates, or does not exist.")
	}
	if !it.StandardSupport || it.WorkflowKind != kind || it.IsTrainingCourse || it.CountsTowardClientVisit ||
		(it.ParticipantMode != "" && it.ParticipantMode != "none") || len(it.Modes) == 0 ||
		it.Modes[0] != "any_ssa_intervention" || rules.CalendarBlocksRefuse {
		return nil, handOn("the profile is not standard support")
	}
	if it.RequiresCluster {
		return nil, refuse("This Catalogue Activity requires a Cluster.")
	}
	return it, nil
}

// pairTraining is `_create` for the training (create(training_course=…,
// skip_cost_snapshot=True)): the profile prices nothing, the course names
// it and decides its intervention.
func (s *Service) pairTraining(ctx context.Context, p auth.Principal, req Request, origin Origin, now, today, day time.Time,
	sc school, responsible, approvalOwner string, c course, focus, profileID string) (*plan, error) {
	kind := rules.Pair.TrainingKind
	it, err := standardItem(ctx, s.db, profileID, kind, day)
	if err != nil {
		return nil, err
	}
	scheduledUTC := day.UTC()
	fy := schooldirectory.OperationalFY(scheduledUTC)
	if day.Before(today) {
		return nil, refuse("%s has passed. Schedule work from %s onwards.", longDate(day), longDate(today))
	}
	if approvalOwner != "" {
		if err := requestEntitlement(sc, kind); err != nil {
			return nil, err
		}
	} else {
		if err := trainingEntitlement(ctx, s.db, sc, c, fy, now); err != nil {
			return nil, err
		}
		if err := coreTrainingSideOpen(ctx, s.db, sc, c, fy, now); err != nil {
			return nil, err
		}
	}
	home, err := staffHomeOf(ctx, s.db, responsible)
	if err != nil {
		return nil, err
	}
	if !home.Found {
		return nil, handOn("no staff profile")
	}
	if set, err := ceilingSet(ctx, s.db, responsible, c.ID, fy); err != nil || set {
		if err != nil {
			return nil, err
		}
		return nil, handOn("a training ceiling is set for the course")
	}
	need, err := schoolNeedOf(ctx, pgNeed{s.db}, sc.ID, sc.ClusterID, now)
	if err != nil {
		return nil, err
	}
	version, ok, err := latestVersion(ctx, s.db, it.ID)
	if err != nil {
		return nil, err
	}
	if !ok {
		return nil, handOn("the profile has no version yet")
	}
	reason, source := standardSupport(req.RecReason, focus, it.ID, need.Record)
	// The course's identity on the plan (3479–3488).
	source["trainingCourseId"], source["trainingCourseName"] = c.ID, c.Name
	source["trainingCourseCode"], source["trainingCategory"], source["ssaIndicator"] = c.Code, c.Category, c.Indicator
	focusSource := "planner"
	if focus != "" {
		focusSource = "course"
	}
	ev := assess(kind, focus, focusSource, c.modes(), need, false, today)
	row := newRow(rowInput{
		now: now, day: day, fy: fy, quarter: quarterOf(scheduledUTC), activityType: kind,
		purpose: rules.Pair.TrainingPurpose, school: sc, responsible: responsible, item: *it, version: version,
		goal: req.Goal, outcome: req.Outcome, deviation: req.DeviationReason, collects: false,
		focus: focus, reason: reason, source: source, need: need, evidence: ev,
	})
	row.trainingCourseID, row.nameSnapshot = c.ID, c.Name
	row.approvalOwner, row.justification = approvalOwner, req.Justification
	if approvalOwner != "" && req.Justification == "" {
		return nil, refuse(justificationRequired)
	}
	return &plan{p: p, school: sc, item: *it, version: version, need: need, focus: focus, evidence: ev,
		row: row, home: home, origin: origin, now: now}, nil
}

// pairVisit is `_create` for the visit beside it (ssa_default_focus=False):
// the companion purpose, the course's intervention, the default words, the
// day's join and its costs.
func (s *Service) pairVisit(ctx context.Context, p auth.Principal, req Request, origin Origin, now, today, day time.Time,
	sc school, responsible, approvalOwner string, c course, focus string, collects bool, profileID string, training *plan) (*plan, error) {
	kind := rules.Pair.VisitKind
	it, err := standardItem(ctx, s.db, profileID, kind, day)
	if err != nil {
		return nil, err
	}
	fy := training.row.fy
	if approvalOwner != "" {
		if err := requestEntitlement(sc, kind); err != nil {
			return nil, err
		}
	} else if err := entitlement(ctx, s.db, sc, kind, rules.Gate.CompanionPurpose, fy, now); err != nil {
		return nil, err
	}
	version, ok, err := latestVersion(ctx, s.db, it.ID)
	if err != nil {
		return nil, err
	}
	if !ok {
		return nil, handOn("the profile has no version yet")
	}
	need := training.need
	reason, source := standardSupport(req.RecReason, focus, it.ID, need.Record)
	outcome := strings.TrimSpace(req.Outcome)
	if outcome == "" {
		outcome = fmt.Sprintf("Complete the school visit and %s training.", c.Name)
	}
	ev := assess(kind, focus, "planner", it.Modes, need, collects, today)
	row := newRow(rowInput{
		now: now, day: day, fy: fy, quarter: training.row.quarter, activityType: kind,
		purpose: rules.Gate.CompanionPurpose, school: sc, responsible: responsible, item: *it, version: version,
		goal: "School visit accompanying " + c.Name, outcome: outcome, deviation: req.DeviationReason,
		collects: collects, focus: focus, reason: reason, source: source, need: need, evidence: ev,
	})
	// One mission, one SSA verdict: the visit carries the training's
	// (planning/services.py 787–797).
	ssa := map[string]any{}
	if trainingSSA, ok := training.row.source["ssa"].(map[string]any); ok {
		for k, v := range trainingSSA {
			ssa[k] = v
		}
	}
	ssa["pairedWithActivityId"] = training.row.id
	row.source["ssa"] = ssa
	row.alignment = training.row.alignment
	row.approvalOwner, row.justification = approvalOwner, req.Justification
	ownerUID, err := fundingOwner(ctx, s.db, responsible, p.UserID)
	if err != nil {
		return nil, err
	}
	// A request draws no money and joins no day until it is approved.
	var verdict DayVerdict
	if approvalOwner == "" {
		verdict, err = s.pricing.DayCheck(ctx, row.probe())
		if err != nil {
			return nil, err
		}
		if !verdict.Pooled && verdict.Refusal == "" {
			return nil, handOn("the day does not pool the visit")
		}
	}
	return &plan{p: p, school: sc, item: *it, version: version, need: need, focus: focus, evidence: ev,
		row: row, ownerUID: ownerUID, home: training.home, verdict: verdict, origin: origin, now: now}, nil
}

// trainingEntitlement is _assert_schedule_entitlement for the training: a
// universal course is never refused over the school's entitlement
// (training_entitlement.never_refused), after the Champion rule.
func trainingEntitlement(ctx context.Context, q Querier, sc school, c course, fy string, now time.Time) error {
	kind := rules.Pair.TrainingKind
	if c.Universal && in(rules.Pair.TrainingShapes, kind) {
		if in(rules.Gate.OutreachOnlyTypes, sc.Type) && !in(rules.Gate.OutreachActivityTypes, kind) {
			// The Champion rule's words, asked first (entitlement).
			return entitlement(ctx, q, sc, kind, rules.Pair.TrainingPurpose, fy, now)
		}
		return nil
	}
	return entitlement(ctx, q, sc, kind, rules.Pair.TrainingPurpose, fy, now)
}

// writePair is the pair's one transaction (planning/services.py 661, the
// outer atomic): the training's create under the school's lock, then the
// visit's, then the pair joined. Rows are inserted visit first so the
// training can name it; the existing save inserts the training and then
// sets the name, which leaves the same rows.
func (s *Service) writePair(ctx context.Context, pp *pairPlan) (int64, error) {
	t, v := pp.training, pp.visit
	tx, err := s.db.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite, IsoLevel: pgx.ReadCommitted})
	if err != nil {
		return 0, fmt.Errorf("activities: opening the save: %w", err)
	}
	defer func() { _ = tx.Rollback(ctx) }()

	if _, err := tx.Exec(ctx, `SELECT gateway_lock.lock_school($1)`, t.school.ID); err != nil {
		return 0, fmt.Errorf("activities: locking the school: %w", err)
	}
	// The training's create (3207–3343).
	isRequest := t.row.isRequest()
	if isRequest {
		if err := requestEntitlement(t.school, t.row.activityType); err != nil {
			return 0, err
		}
	} else {
		if err := trainingEntitlement(ctx, tx, t.school, pp.course, t.row.fy, t.now); err != nil {
			return 0, err
		}
		if err := coreTrainingSideOpen(ctx, tx, t.school, pp.course, t.row.fy, t.now); err != nil {
			return 0, err
		}
	}
	if set, err := ceilingSet(ctx, tx, t.row.responsible, pp.course.ID, t.row.fy); err != nil || set {
		if err != nil {
			return 0, err
		}
		return 0, handOn("a training ceiling is set for the course")
	}
	if err := duplicates(ctx, tx, t); err != nil {
		return 0, err
	}
	// The visit's create: the cost preview's refusal (3137), then its own
	// lock, entitlement and duplicate tests, then its day.
	if v.verdict.Refusal != "" && v.verdict.Stage == "preview" {
		return 0, &Refusal{Message: v.verdict.Refusal}
	}
	if isRequest {
		if err := requestEntitlement(v.school, v.row.activityType); err != nil {
			return 0, err
		}
	} else if err := entitlement(ctx, tx, v.school, v.row.activityType, v.row.purpose, v.row.fy, v.now); err != nil {
		return 0, err
	}
	if err := duplicates(ctx, tx, v); err != nil {
		return 0, err
	}
	if v.verdict.Refusal != "" {
		return 0, &Refusal{Message: v.verdict.Refusal}
	}
	if !isRequest {
		batchID, _, err := s.joinDay(ctx, tx, v)
		if err != nil {
			return 0, err
		}
		v.row.batchID = batchID
	}
	recIDs, err := planRecommendations(ctx, tx, t)
	if err != nil {
		return 0, err
	}
	if err := insertActivity(ctx, tx, v.row); err != nil {
		return 0, err
	}
	t.row.pairedVisitID = v.row.id
	if err := insertActivity(ctx, tx, t.row); err != nil {
		return 0, err
	}
	if len(recIDs) > 0 {
		if err := markPlanned(ctx, tx, t, recIDs); err != nil {
			return 0, err
		}
	}
	var rowID int64
	if !isRequest {
		if rowID, err = keepCosts(ctx, tx, v); err != nil {
			return 0, err
		}
	}
	if err := tx.Commit(ctx); err != nil {
		return 0, fmt.Errorf("activities: committing the save: %w", err)
	}
	return rowID, nil
}

// afterPair is what follows the commit: the ledger's one mark for the
// owner's year (both rows share it), the training's and then the visit's
// activity.scheduled rows, then the visit's costs settled by the existing
// application.
func (s *Service) afterPair(ctx context.Context, pp *pairPlan, rowID int64) {
	marked := pp.training
	if !in(rules.LedgerCreditedTypes, marked.row.activityType) {
		marked = pp.visit
	}
	if err := s.markLedger(ctx, marked); err != nil {
		s.logger.Warn("activities: the target ledger was not marked", "activity", pp.training.row.id, "err", err)
	}
	for _, pl := range []*plan{pp.training, pp.visit} {
		if err := s.auditScheduled(ctx, pl); err != nil {
			s.logger.Warn("activities: the scheduled audit row was not written", "activity", pl.row.id, "err", err)
		}
		// notify_requested follows each row's own audit.
		if pl.row.isRequest() {
			if err := s.tellRequestOwner(ctx, pl); err != nil {
				s.logger.Warn("activities: the owner was not asked about the visit", "activity", pl.row.id, "err", err)
			}
		}
	}
	if pp.training.row.isRequest() {
		return
	}
	// Of the two, only the visit is news to its owner (_notify_scheduled_owner).
	if err := s.tellScheduledOwner(ctx, pp.visit); err != nil {
		s.logger.Warn("activities: the owner was not told of the visit", "activity", pp.visit.row.id, "err", err)
	}
	if err := s.pricing.Settle(ctx, []int64{rowID}, pp.visit.row.id); err != nil {
		s.logger.Warn("activities: the costs to follow were not settled; the sweep takes them",
			"activity", pp.visit.row.id, "row", rowID, "err", err)
	}
	if pp.corePlanID != "" {
		// schedule_package_credit, once each commits.
		if err := s.creditCoreSlot(ctx, pp.training, pp.corePlanID, coreSlotTraining); err != nil {
			s.logger.Warn("activities: the Core package was not credited", "activity", pp.training.row.id, "err", err)
		}
		if err := s.creditCoreSlot(ctx, pp.visit, pp.corePlanID, coreSlotVisit); err != nil {
			s.logger.Warn("activities: the Core package was not credited", "activity", pp.visit.row.id, "err", err)
		}
	}
}
