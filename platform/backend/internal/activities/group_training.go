package activities

// The seventh save (docs/migration/38): a cluster Group Training, planned
// from Planning's Schedule drawer for a cluster
// (/planning/schedule-modal?cluster_id=…&action=training, posting to
// /planning/schedule-action): schedule_action_view's cluster branch, then
// planning.services.schedule_cluster_activity and activities.services
// _create for a cluster, then cluster_attendance.set_invited_schools.
//
// Go takes the owner's own staff Group Training at a cluster they are
// responsible for, for a governed course linked to one SSA intervention or
// to none (an orientation), per school by category, the schools ticked by
// name and none of them a Core school (its package slots stay Django's),
// Facilitated by Staff, in person or online (docs/migration/48), with no project, priority, focus named by
// the planner or training ceiling for the officer and course this year, on a
// day the pricing pools. Everything else is handed on unchanged.

import (
	"context"
	"errors"
	"fmt"
	"net/url"
	"regexp"
	"strconv"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// The words of this save, each a literal where it is said.
const (
	// schedule_action_view 2405–2415.
	noSchoolTicked = "Tick the schools this training is for."
	// schedule_action_view 2493 (noun "Cluster activity").
	groupScheduledMessage = "Cluster activity scheduled. It is on your My Plan — keep planning."
	// _validated_per_school_categories.
	nobodyPerSchool = "Enter how many teachers, school leaders or other participants to invite from each school."
	// _validated_participants_per_school.
	tooManyPerSchool = "Participants per school must be 500 or fewer."
	// _create 2440.
	noActiveSchools = "This cluster has no active schools, so there is nobody to invite. Add schools to the cluster before planning a cluster activity for it."
	// validate_context.
	requiresSchool = "This Catalogue Activity requires a School."
	// set_invited_schools.
	championInvited = "Champion schools receive no cluster training or meeting, so they cannot be invited to this session."
	notAMember      = "Only schools in this cluster can be invited to its session. Add a school from another cluster as a guest when it attends."
	// The duplicate guard (_create 3297–3315).
	identicalActivity = "An identical activity is already scheduled for this target on this date. Reschedule or edit the existing activity instead of creating a duplicate."
	// recommend_cluster_activities' limit (_create 3071) and the weakness
	// line of plan_alignment.cluster_need.
	primaryLimit = 3
	weakLine     = 5.5
	// cluster_credit.credit_cluster_session reads school_type="core".
	coreSchoolType = "core"
	// The bounds of the participant and materials checks.
	maxCategory  = 100000
	maxPerSchool = 500
	maxMaterial  = 1_000_000
	// The view's purpose_type default (1999): a Group Training posts none.
	groupPurposeType = "focus_intervention"
)

// GroupTrainingRequest is the cluster drawer's fields
// (partials/planning/schedule_cluster_drawer.html).
type GroupTrainingRequest struct {
	ClusterID, CourseID, Date, Goal, Outcome, DeviationReason string
	// Per school, by category, as typed.
	Teachers, Leaders, Other string
	// Materials by the page, as typed.
	Printing, PhotocopyPages, PhotocopyCopies string
	// The schools ticked by name, and whether the checklist was shown.
	Invited      []string
	InvitedShown bool
	// Delivered online (docs/migration/48): the drawer's delivery_mode.
	Online bool
}

// groupFormFields are the fields the drawer posts for this case. Any other
// field carrying a value (a school, a focus the planner names, online
// delivery, a responsible person, a project, a priority) names a case Go
// does not take, and the request is handed on whole.
var groupFormFields = map[string]bool{
	"csrfmiddlewaretoken": true, "cluster_id": true, "activity_type": true, "invited_schools_shown": true,
	"invited_school_ids": true, "printing_pages": true, "photocopy_pages": true, "photocopy_copies": true,
	"delivery_type": true, "facilitating_partner_id": true, "ssa_deviation_reason": true, "executor_type": true,
	"teachers_per_school": true, "leaders_per_school": true, "other_per_school": true, "activity_goal": true,
	"activity_purpose_text": true, "expected_outcome": true, "catalogue_item_id": true, "scheduled_date": true,
	// The online drawer's hidden field (docs/migration/48).
	"delivery_mode": true,
}

// IsGroupTrainingForm is whether the posted form is a cluster's Group
// Training (the view's cluster branch, 2078).
func IsGroupTrainingForm(form url.Values) bool {
	return strings.TrimSpace(form.Get("cluster_id")) != "" && form.Get("activity_type") == rules.GroupTraining.ActivityType
}

// GroupTrainingRequestFromForm reads the drawer's form; false when Go does
// not take it.
func GroupTrainingRequestFromForm(form url.Values) (GroupTrainingRequest, bool) {
	if !IsGroupTrainingForm(form) {
		return GroupTrainingRequest{}, false
	}
	for name, values := range form {
		if groupFormFields[name] {
			continue
		}
		for _, v := range values {
			if strings.TrimSpace(v) != "" {
				return GroupTrainingRequest{}, false
			}
		}
	}
	one := func(name string) string { return form.Get(name) }
	trimmed := func(name string) string { return strings.TrimSpace(form.Get(name)) }
	// "Facilitated by" (2441–2449): a drawer that showed it always sends
	// it, blank is Staff. A named partner (the fee) or no field at all (the
	// cluster's standing facilitator) is not this case.
	facilitator, asked := form["facilitating_partner_id"]
	if !asked || strings.TrimSpace(strings.Join(facilitator, "")) != "" {
		return GroupTrainingRequest{}, false
	}
	if (one("delivery_type") != "" && one("delivery_type") != "staff") ||
		(trimmed("executor_type") != "" && trimmed("executor_type") != "staff") {
		return GroupTrainingRequest{}, false
	}
	// Delivery (2357–2363): "online" makes it an online training; the
	// in-person drawer posts no such field. Any other value, or two, is
	// handed on.
	online := false
	if modes, posted := form["delivery_mode"]; posted {
		if len(modes) != 1 || strings.TrimSpace(modes[0]) != onlineDelivery {
			return GroupTrainingRequest{}, false
		}
		online = true
	}
	goal := one("activity_goal")
	if goal == "" {
		goal = one("activity_purpose_text")
	}
	invited := []string{}
	for _, id := range form["invited_school_ids"] {
		if id = strings.TrimSpace(id); id != "" {
			invited = append(invited, id)
		}
	}
	return GroupTrainingRequest{
		ClusterID: trimmed("cluster_id"), CourseID: trimmed("catalogue_item_id"), Date: trimmed("scheduled_date"),
		Goal: strings.TrimSpace(goal), Outcome: trimmed("expected_outcome"), DeviationReason: one("ssa_deviation_reason"),
		Teachers: trimmed("teachers_per_school"), Leaders: trimmed("leaders_per_school"), Other: trimmed("other_per_school"),
		Printing: trimmed("printing_pages"), PhotocopyPages: trimmed("photocopy_pages"),
		PhotocopyCopies: trimmed("photocopy_copies"), Invited: invited,
		InvitedShown: trimmed("invited_schools_shown") != "", Online: online,
	}, true
}

// cluster is a cluster row as far as the save reads it.
type cluster struct {
	ID, Responsible, DistrictID, DistrictName, DistrictType string
}

// groupPlan is everything decided before the transaction.
type groupPlan struct {
	*plan
	cluster cluster
	invited []string
	course  course
	// The year `_create` counts the ceiling in (an online session's row
	// later takes its planned day's year, docs/migration/48).
	ceilingFY string
}

// ScheduleGroupTraining makes the save, or refuses it in the existing words,
// or hands it on (ErrHandOn).
func (s *Service) ScheduleGroupTraining(ctx context.Context, p auth.Principal, req GroupTrainingRequest, origin Origin) (Answer, error) {
	gp, err := s.prepareGroup(ctx, p, req, origin)
	if err != nil {
		return Answer{}, err
	}
	rowID, err := s.writeGroup(ctx, gp)
	if err != nil {
		return Answer{}, err
	}
	if gp.row.group.online {
		s.afterOnlineCommit(ctx, gp.plan)
	} else {
		s.afterCommit(ctx, gp.plan, rowID)
	}
	answer, err := s.answer(ctx, gp.plan)
	if err != nil {
		return Answer{}, err
	}
	answer.Message = groupScheduledMessage
	return answer, nil
}

// canonical is a number as Python's int() reads it and str() writes it
// back: digits, no sign, no leading zero. Anything else is handed on, so
// Django meets its own words for it.
var canonical = regexp.MustCompile(`^(0|[1-9][0-9]{0,6})$`)

// count reads one typed count: blank is 0 and absent; false hands on.
func count(text string) (value int, given, ok bool) {
	if text == "" {
		return 0, false, true
	}
	if !canonical.MatchString(text) {
		return 0, false, false
	}
	n, err := strconv.Atoi(text)
	return n, true, err == nil
}

// prepareGroup is the view's cluster branch and `_create` up to its
// transaction, in their order.
func (s *Service) prepareGroup(ctx context.Context, p auth.Principal, req GroupTrainingRequest, origin Origin) (*groupPlan, error) {
	now := s.now()
	today := dateOnly(now.In(s.kampala))
	g := rules.GroupTraining
	// The drawer's gate (1987).
	if !in(rules.Doors.Drawer, p.ActiveRole) {
		message := noPermission
		if p.ActiveRole == rules.Doors.AdminRole {
			message = rules.Doors.AdminRefusal
		}
		return nil, &Refusal{Message: message, Forbidden: true}
	}
	// Not this case: asking, another's seat, no staff profile, a country,
	// visit-only or summary role (_assert_target_in_scope's other branches),
	// a date in another form.
	if in(rules.Doors.Requesters, p.ActiveRole) || p.InActingAppointment || p.StaffProfileID == "" ||
		in(g.CountryRoles, p.ActiveRole) || in(g.VisitOnlyRoles, p.ActiveRole) || in(g.SummaryRoles, p.ActiveRole) ||
		(req.Date != "" && !isoDate.MatchString(req.Date)) || req.ClusterID == "" {
		return nil, handOn("not the owner's own Group Training")
	}
	// The date (2061–2072).
	if req.Date == "" {
		return nil, refuse("Pick the date this is planned for before scheduling it.")
	}
	day, err := time.ParseInLocation(time.DateOnly, req.Date, s.kampala)
	if err != nil {
		return nil, refuse("That scheduled date is not a valid calendar date.")
	}
	// The course (2078–2104): offered for a cluster today.
	if req.CourseID == "" {
		return nil, refuse(noCourse)
	}
	c, err := clusterCourse(ctx, s.db, req.CourseID, today)
	if err != nil {
		return nil, err
	}
	if c == nil {
		return nil, refuse(notOffered)
	}
	focus, taken := c.focus()
	if !taken || c.Kind != g.ActivityType {
		return nil, handOn("a course Go does not take (its intervention mapping or kind)")
	}
	// The schools ticked (2396–2415).
	if !req.InvitedShown {
		return nil, handOn("no checklist: the whole cluster is invited")
	}
	if len(req.Invited) == 0 {
		return nil, refuse(noSchoolTicked)
	}
	if hasDuplicate(req.Invited) {
		return nil, handOn("a school ticked twice")
	}
	cl, err := clusterOf(ctx, s.db, req.ClusterID)
	if err != nil {
		return nil, err
	}
	if cl == nil {
		return nil, handOn("an unknown or removed cluster")
	}
	return s.createGroup(ctx, p, req, origin, now, today, day, *cl, *c, focus)
}

func hasDuplicate(ids []string) bool {
	seen := map[string]bool{}
	for _, id := range ids {
		if seen[id] {
			return true
		}
		seen[id] = true
	}
	return false
}

// createGroup is `_create` for the cluster session, to its transaction.
func (s *Service) createGroup(ctx context.Context, p auth.Principal, req GroupTrainingRequest, origin Origin,
	now, today, day time.Time, cl cluster, c course, focus string) (*groupPlan, error) {
	g := rules.GroupTraining
	// get_selectable_item(course, day) (2254): the course is the item.
	it, err := selectableItem(ctx, s.db, c.ID, day)
	if err != nil {
		return nil, err
	}
	if it == nil {
		return nil, refuse("The selected Activity Catalogue item is inactive, retired, outside its effective dates, or does not exist.")
	}
	if it.StandardSupport || it.WorkflowKind != g.ActivityType || !it.IsTrainingCourse ||
		it.ParticipantMode != g.PerSchoolMode || rules.CalendarBlocksRefuse {
		// Standard support (no gated course is), a per-total or
		// by-category course, or a calendar that refuses: not ported.
		return nil, handOn("the course is not a governed per-school cluster course")
	}
	scheduledUTC := day.UTC()
	fy := schooldirectory.OperationalFY(scheduledUTC)
	if day.Before(today) {
		return nil, refuse("%s has passed. Schedule work from %s onwards.", longDate(day), longDate(today))
	}
	// The participants (2423–2459), per school by category.
	perSchool, categories, err := perSchoolOf(req)
	if err != nil {
		return nil, err
	}
	members, err := activeSchoolCount(ctx, s.db, cl.ID)
	if err != nil {
		return nil, err
	}
	if members < 1 {
		return nil, refuse(noActiveSchools)
	}
	if len(req.Invited) > members {
		plural := "s"
		if members == 1 {
			plural = ""
		}
		return nil, refuse("This cluster has %d active school%s, so it cannot invite %d.", members, plural, len(req.Invited))
	}
	// The materials (2461).
	materials, err := materialsOf(req)
	if err != nil {
		return nil, err
	}
	// The scope (2578): a cluster the person is responsible for. Any other
	// reading of the portfolio (a cluster reached through one of their
	// schools, or one nobody holds) is handed on.
	if cl.Responsible != p.StaffProfileID {
		return nil, handOn("a cluster the person is not responsible for")
	}
	home, err := staffHomeOf(ctx, s.db, p.StaffProfileID)
	if err != nil {
		return nil, err
	}
	if !home.Found {
		return nil, handOn("no staff profile")
	}
	invitedSchools, err := schoolsByID(ctx, s.db, req.Invited)
	if err != nil {
		return nil, err
	}
	for _, sc := range invitedSchools {
		if sc.Type == coreSchoolType {
			return nil, handOn("a Core school is invited: its package slot is the existing application's")
		}
	}
	// The SSA need of the schools invited (2847).
	need, err := clusterNeedOf(ctx, s.db, cl.ID, req.Invited, now)
	if err != nil {
		return nil, err
	}
	// validate_context (2960).
	if it.RequiresSchool {
		return nil, refuse(requiresSchool)
	}
	version, ok, err := latestVersion(ctx, s.db, it.ID)
	if err != nil {
		return nil, err
	}
	if !ok {
		return nil, handOn("the course has no version yet")
	}
	// The governed recommendation (3041–3100), unless the course's
	// mappings take none.
	reason, source := "", map[string]any{}
	if !intersects(it.Modes, g.UngatedModes) {
		rec, err := recommendForCluster(ctx, s.db, cl.ID, it.ID, now, today)
		if err != nil {
			return nil, err
		}
		reason, source = rec.reason, rec.source()
	}
	focusSource := "planner"
	if focus != "" {
		focusSource = "course"
	}
	ev := assessCluster(g.ActivityType, focus, focusSource, c.modes(), need, today)
	if reason == "" {
		// plan_alignment.stamp: an empty reason takes the verdict's.
		reason = reasonFor(ev)
	}
	row := newRow(rowInput{
		now: now, day: day, fy: fy, quarter: quarterOf(scheduledUTC), activityType: g.ActivityType,
		purpose: groupPurposeType, school: school{}, responsible: p.StaffProfileID, item: *it, version: version,
		goal: req.Goal, outcome: req.Outcome, deviation: req.DeviationReason, collects: false,
		focus: focus, reason: reason, source: source, evidence: ev,
	})
	row.schoolID, row.planningSource, row.contextType = "", "cluster_planning", "cluster"
	row.group = &groupColumns{
		clusterID: cl.ID, perSchool: perSchool, schoolCount: members, invited: len(req.Invited),
		expected: perSchool * len(req.Invited), teachers: categories[0], leaders: categories[1], other: categories[2],
		printing: materials[0], photocopyPages: materials[1], photocopyCopies: materials[2],
		online: req.Online,
	}
	ownerUID, err := fundingOwner(ctx, s.db, p.StaffProfileID, p.UserID)
	if err != nil {
		return nil, err
	}
	// The cost preview (3137) and the day the session joins, asked of the
	// existing application's pricing before the transaction.
	verdict, err := s.pricing.DayCheck(ctx, row.probe())
	if err != nil {
		return nil, err
	}
	if req.Online {
		// No preview and no day (_create 3129–3135, _price_activity):
		// the revision at UGX 0 instead (docs/migration/48).
		if err := takeOnline(&row, verdict); err != nil {
			return nil, err
		}
	} else if verdict.Refusal != "" && verdict.Stage == "preview" {
		return nil, &Refusal{Message: verdict.Refusal}
	}
	if !req.Online && !verdict.Pooled && verdict.Refusal == "" {
		return nil, handOn("the day does not pool the session")
	}
	if set, err := ceilingSet(ctx, s.db, p.StaffProfileID, c.ID, fy); err != nil || set {
		if err != nil {
			return nil, err
		}
		return nil, handOn("a training ceiling is set for the course")
	}
	// The day's batch is made where the cluster is (attach_activity_to_batch
	// reads the session's district).
	where := school{DistrictID: cl.DistrictID, DistrictName: cl.DistrictName, DistrictType: cl.DistrictType}
	pl := &plan{p: p, school: where, item: *it, version: version, focus: focus, evidence: ev, row: row,
		ownerUID: ownerUID, home: home, verdict: verdict, origin: origin, now: now}
	return &groupPlan{plan: pl, cluster: cl, invited: req.Invited, course: c, ceilingFY: fy}, nil
}

func intersects(a, b []string) bool {
	for _, x := range a {
		if in(b, x) {
			return true
		}
	}
	return false
}

// perSchoolOf is _validated_per_school_categories and
// _validated_participants_per_school: teachers, leaders and other per
// school, their sum the per-school figure. None stated is handed on (the
// catalogue's guidance or the preview's refusal decide it there).
func perSchoolOf(req GroupTrainingRequest) (int, [3]int, error) {
	var categories [3]int
	stated := false
	for i, text := range []string{req.Teachers, req.Leaders, req.Other} {
		n, given, ok := count(text)
		if !ok || n > maxCategory {
			return 0, categories, handOn("a participant count Go does not read")
		}
		categories[i], stated = n, stated || given
	}
	if !stated {
		return 0, categories, handOn("no participants stated per school")
	}
	total := categories[0] + categories[1] + categories[2]
	if total < 1 {
		return 0, categories, refuse(nobodyPerSchool)
	}
	if total > maxPerSchool {
		return 0, categories, refuse(tooManyPerSchool)
	}
	return total, categories, nil
}

// materialsOf is _validated_materials: pages to print, pages to photocopy
// and copies, a blank read as none.
func materialsOf(req GroupTrainingRequest) ([3]int, error) {
	var out [3]int
	labels := [3]string{"pages to print", "pages to photocopy", "photocopies"}
	for i, text := range []string{req.Printing, req.PhotocopyPages, req.PhotocopyCopies} {
		n, _, ok := count(text)
		if !ok {
			return out, handOn("a materials count Go does not read")
		}
		if n > maxMaterial {
			return out, refuse("The number of %s is implausibly large.", labels[i])
		}
		out[i] = n
	}
	return out, nil
}

// clusterCourse is validate_priority_training_selection(id, CLUSTER) on the
// day: an effective course staff may deliver to a cluster, or nil.
func clusterCourse(ctx context.Context, q Querier, id string, on time.Time) (*course, error) {
	var c course
	err := q.QueryRow(ctx, `SELECT i.id, i.stable_code, i.display_name, i.workflow_kind
FROM activity_catalogue_item i
WHERE `+effective+` AND i.is_training_course AND i.cluster_delivery_allowed AND i.staff_delivery_allowed AND i.id = $2`,
		on.Format(time.DateOnly), id).Scan(&c.ID, &c.Code, &c.Name, &c.Kind)
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

// clusterOf is the cluster as Cluster.objects reads it (soft-deleted rows
// left out), with its district.
func clusterOf(ctx context.Context, q Querier, id string) (*cluster, error) {
	var c cluster
	var responsible, districtType *string
	err := q.QueryRow(ctx, `SELECT c.id, c.responsible_staff_id, c.district_id, COALESCE(d.name, ''), d.district_type
FROM cluster c LEFT JOIN district d ON d.id = c.district_id
WHERE c.id = $1 AND c.deleted_at IS NULL`, id).Scan(&c.ID, &responsible, &c.DistrictID, &c.DistrictName, &districtType)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, nil
	}
	if err != nil {
		return nil, fmt.Errorf("activities: reading the cluster: %w", err)
	}
	if responsible != nil {
		c.Responsible = strings.TrimSpace(*responsible)
	}
	if districtType != nil {
		c.DistrictType = *districtType
	}
	return &c, nil
}

// activeSchoolCount is clusters.services.active_school_count: live,
// clustered, operating members, Champion schools left out.
func activeSchoolCount(ctx context.Context, q Querier, clusterID string) (int, error) {
	var n int
	err := q.QueryRow(ctx, `SELECT count(*) FROM school WHERE cluster_id = $1 AND cluster_status = 'clustered'
  AND deleted_at IS NULL AND operational_status = ANY($2) AND NOT (school_type = ANY($3))`,
		clusterID, rules.GroupTraining.OperatingStatuses, rules.GroupTraining.ChampionTypes).Scan(&n)
	if err != nil {
		return 0, fmt.Errorf("activities: counting the cluster's schools: %w", err)
	}
	return n, nil
}

// schoolsByID reads the ticked schools that exist (any cluster).
func schoolsByID(ctx context.Context, q Querier, ids []string) ([]school, error) {
	rows, err := q.Query(ctx, `SELECT id, school_type, operational_status, COALESCE(cluster_id, '') FROM school
WHERE id = ANY($1) AND deleted_at IS NULL`, ids)
	if err != nil {
		return nil, fmt.Errorf("activities: reading the ticked schools: %w", err)
	}
	return pgx.CollectRows(rows, func(r pgx.CollectableRow) (school, error) {
		var sc school
		return sc, r.Scan(&sc.ID, &sc.Type, &sc.Status, &sc.ClusterID)
	})
}

// writeGroup is `_create`'s transaction for the session (3207–3561): the
// cluster's lock, the duplicate guard, the invitations' checks, the day it
// joins, the row, its invitations, the recommendations it answers and the
// costs to follow. It answers the costs-to-follow row's id.
func (s *Service) writeGroup(ctx context.Context, gp *groupPlan) (int64, error) {
	pl := gp.plan
	tx, err := s.db.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite, IsoLevel: pgx.ReadCommitted})
	if err != nil {
		return 0, fmt.Errorf("activities: opening the save: %w", err)
	}
	defer func() { _ = tx.Rollback(ctx) }()

	if _, err := tx.Exec(ctx, `SELECT gateway_lock.lock_cluster($1)`, gp.cluster.ID); err != nil {
		return 0, fmt.Errorf("activities: locking the cluster: %w", err)
	}
	if set, err := ceilingSet(ctx, tx, pl.row.responsible, gp.course.ID, gp.ceilingFY); err != nil || set {
		if err != nil {
			return 0, err
		}
		return 0, handOn("a training ceiling is set for the course")
	}
	var identical bool
	if err := tx.QueryRow(ctx, `SELECT EXISTS (SELECT 1 FROM activity WHERE activity_type = $1 AND planned_date = $2
  AND deleted_at IS NULL AND responsible_staff_id = $3 AND assigned_partner_id IS NULL
  AND NOT (status = ANY($4)) AND cluster_id = $5 AND school_id IS NULL)`,
		pl.row.activityType, pl.row.plannedDate.Format(time.DateOnly), pl.row.responsible, identicalExcluded,
		gp.cluster.ID).Scan(&identical); err != nil {
		return 0, fmt.Errorf("activities: reading the day's identical work: %w", err)
	}
	if identical {
		return 0, refuse(identicalActivity)
	}
	if err := checkInvitations(ctx, tx, gp.cluster.ID, gp.invited); err != nil {
		return 0, err
	}
	online := pl.row.group.online
	// The day's refusal is met once the session joins it (costs_follow
	// around the pricing, after the invitations and the verdict). An online
	// session joins none.
	if pl.verdict.Refusal != "" {
		return 0, &Refusal{Message: pl.verdict.Refusal}
	}
	if !online {
		batchID, _, err := s.joinDay(ctx, tx, pl)
		if err != nil {
			return 0, err
		}
		pl.row.batchID = batchID
	}
	if err := insertActivity(ctx, tx, pl.row); err != nil {
		return 0, err
	}
	if err := insertInvitations(ctx, tx, pl, gp.invited); err != nil {
		return 0, err
	}
	recIDs, err := clusterRecommendations(ctx, tx, pl.row.focus, gp.invited)
	if err != nil {
		return 0, err
	}
	if len(recIDs) > 0 {
		if err := markPlanned(ctx, tx, pl, recIDs); err != nil {
			return 0, err
		}
	}
	var rowID int64
	if online {
		// The revision inside the save (_price_activity's online branch);
		// no costs follow it.
		if err := s.writeOnlineCost(ctx, tx, pl); err != nil {
			return 0, err
		}
	} else if rowID, err = keepCosts(ctx, tx, pl); err != nil {
		return 0, err
	}
	if err := tx.Commit(ctx); err != nil {
		return 0, fmt.Errorf("activities: committing the save: %w", err)
	}
	return rowID, nil
}

// checkInvitations is set_invited_schools' refusals: no Champion school,
// members only (live, operating, of this cluster), and a Core school among
// them handed on (credit_cluster_session would take its slot).
func checkInvitations(ctx context.Context, q Querier, clusterID string, invited []string) error {
	g := rules.GroupTraining
	rows, err := q.Query(ctx, `SELECT id, school_type FROM school WHERE cluster_id = $1 AND deleted_at IS NULL
  AND operational_status = ANY($2)`, clusterID, g.OperatingStatuses)
	if err != nil {
		return fmt.Errorf("activities: reading the cluster's members: %w", err)
	}
	members, err := pgx.CollectRows(rows, func(r pgx.CollectableRow) (school, error) {
		var sc school
		return sc, r.Scan(&sc.ID, &sc.Type)
	})
	if err != nil {
		return fmt.Errorf("activities: reading the cluster's members: %w", err)
	}
	types := map[string]string{}
	for _, m := range members {
		types[m.ID] = m.Type
	}
	core := false
	for _, id := range invited {
		kind, member := types[id]
		if member && in(g.ChampionTypes, kind) {
			return refuse(championInvited)
		}
		core = core || (member && kind == coreSchoolType)
	}
	for _, id := range invited {
		if _, member := types[id]; !member {
			return refuse(notAMember)
		}
	}
	if core {
		return handOn("a Core school is invited")
	}
	return nil
}

// insertInvitations is set_invited_schools' rows: one invitation per
// ticked school with the session's per-school composition, recorded by the
// person saving it. The serial id is the table's own.
func insertInvitations(ctx context.Context, tx pgx.Tx, pl *plan, invited []string) error {
	gc := pl.row.group
	for _, id := range invited {
		if _, err := tx.Exec(ctx, `INSERT INTO cluster_activity_attendance (created_at, updated_at, invited, attended,
  is_guest, teachers, leaders, other, recorded_by, activity_id, school_id)
VALUES ($1, $1, true, false, false, $2, $3, $4, $5, $6, $7)`,
			pl.now, gc.teachers, gc.leaders, gc.other, pl.p.UserID, pl.row.id, id); err != nil {
			return fmt.Errorf("activities: inviting a school: %w", err)
		}
	}
	return nil
}

// clusterRecommendations is link_recommendations' read for a session: the
// invited schools' open recommendations for its intervention.
func clusterRecommendations(ctx context.Context, tx pgx.Tx, focus string, invited []string) ([]string, error) {
	if focus == "" {
		return nil, nil
	}
	rows, err := tx.Query(ctx, `SELECT id FROM ssa_recommendation WHERE school_id = ANY($1) AND intervention = $2
  AND state = ANY($3) ORDER BY school_id, created_at DESC`, invited, focus, []string{"generated", "accepted", "deferred"})
	if err != nil {
		return nil, fmt.Errorf("activities: reading the open recommendations: %w", err)
	}
	ids, err := pgx.CollectRows(rows, pgx.RowTo[string])
	if err != nil {
		return nil, fmt.Errorf("activities: reading the open recommendations: %w", err)
	}
	return ids, nil
}
