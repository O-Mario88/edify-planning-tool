package activities

import (
	"context"
	"errors"
	"fmt"
	"slices"
	"strings"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/cuid"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// The coordinator's hand-over of project schools to a partner, who
// schedules them (planning_views.special_projects_bulk_partner_view): one
// school from its row's Actions, or the schools ticked on Project Monitoring
// or Special Projects Planning. A project's hand-over goes past the school
// rules (partners.handover_policy), so the partner is any partner; a school
// the partner already has waiting is skipped, one the creation door refuses
// is named and left out.

const (
	projectAssignNoneSelected = "No in-scope project schools were selected."
	projectAssignNoneOpen     = "None of the selected schools can be assigned to a partner: each is a Champion school, which staff deliver themselves, or is closed."
	projectAssignLimit        = 50
	projectAssignPurpose      = "Special project support: "
	projectAssignNotes        = "Project: "
	// projectAssignAction is error_fragment's action: the words before a
	// refusal the view's try block catches.
	projectAssignAction = "Could not assign the selection: "
)

// ProjectAssignRow is one selected project school of the drawer's list.
type ProjectAssignRow struct {
	AssignmentID, ProjectID, ProjectName string
	SchoolID, SchoolName, SchoolType     string
	// Reason is why no partner may take the school (_never_to_a_partner);
	// empty when one may.
	Reason string
	// intervention and targets are the project's, for the hand-over's focus.
	intervention string
	targets      []string
}

// ProjectAssignSelection is the drawer's selection in the reader's projects.
type ProjectAssignSelection struct {
	Rows []ProjectAssignRow
	// ProjectPartners is _project_partner_ids: the partners on the list of
	// every selected project that keeps one; Listed is false when none does.
	ProjectPartners []string
	Listed          bool
}

// Included is the rows a partner may take.
func (sel ProjectAssignSelection) Included() []ProjectAssignRow {
	out := []ProjectAssignRow{}
	for _, r := range sel.Rows {
		if r.Reason == "" {
			out = append(out, r)
		}
	}
	return out
}

// ProjectAssignRequest is the drawer's post.
type ProjectAssignRequest struct {
	Assignments, PartnerID, Purpose, CourseID, Focus, OverrideReason string
}

// projectAssignIDs is _scoped_project_assignments' ids: the posted list,
// unique, the first fifty.
func projectAssignIDs(raw string) []string {
	ids := []string{}
	for _, v := range strings.Split(raw, ",") {
		if v = strings.TrimSpace(v); v != "" && !slices.Contains(ids, v) {
			ids = append(ids, v)
		}
	}
	return ids[:min(len(ids), projectAssignLimit)]
}

// planningProjects is planning_service._scoped_projects as a condition on
// project pr: every live project for a country reader; a coordinator's own
// (managed or assigned); otherwise those the person manages or is assigned
// to, or that hold a school in their reach. False when the reader has none.
func planningProjects(p auth.Principal, sc schooldirectory.Scope, args *[]any) string {
	assigned := func(n int) string {
		return fmt.Sprintf(`(pr.manager_staff_id = $%d OR EXISTS (SELECT 1 FROM project_staff_assignment sa
  WHERE sa.project_id = pr.id AND sa.staff_id = $%d AND sa.is_active))`, n, n)
	}
	switch {
	case sc.CountryScope:
		return "TRUE"
	case p.ActiveRole == "ProjectCoordinator":
		if p.StaffProfileID == "" {
			return "FALSE"
		}
		*args = append(*args, p.StaffProfileID)
		return assigned(len(*args))
	}
	parts := []string{}
	if p.StaffProfileID != "" {
		*args = append(*args, p.StaffProfileID)
		parts = append(parts, assigned(len(*args)))
	}
	if len(sc.SchoolIDs) > 0 {
		*args = append(*args, sc.SchoolIDs)
		parts = append(parts, fmt.Sprintf(`EXISTS (SELECT 1 FROM project_school_assignment psa
  WHERE psa.project_id = pr.id AND psa.school_id = ANY($%d))`, len(*args)))
	}
	if len(parts) == 0 {
		return "FALSE"
	}
	return "(" + strings.Join(parts, " OR ") + ")"
}

// ProjectAssignSelectionFor is the drawer's selection: the posted project
// schools in the reader's projects, by school name, each with why no
// partner may take it, and the selected projects' own partners.
func (s *Service) ProjectAssignSelectionFor(ctx context.Context, p auth.Principal, raw string) (ProjectAssignSelection, error) {
	if rules.ProjectHandOversKeepSchoolRules {
		return ProjectAssignSelection{}, handOn("project hand-overs keep the school rules")
	}
	sc, err := schooldirectory.ResolveScope(ctx, s.db, p, s.now())
	if err != nil {
		return ProjectAssignSelection{}, err
	}
	args := []any{projectAssignIDs(raw)}
	scoped := planningProjects(p, sc, &args)
	rows, err := s.db.Query(ctx, `SELECT a.id, pr.id, pr.name, s.id, s.name, COALESCE(s.school_type, ''), COALESCE(s.operational_status, ''),
  COALESCE(pr.intervention, ''), COALESCE(pr.target_interventions, '[]'::jsonb)
FROM project_school_assignment a JOIN project pr ON pr.id = a.project_id JOIN school s ON s.id = a.school_id
WHERE a.id = ANY($1) AND pr.deleted_at IS NULL AND `+scoped+`
ORDER BY s.name, a.id`, args...)
	if err != nil {
		return ProjectAssignSelection{}, fmt.Errorf("activities: reading the selected project schools: %w", err)
	}
	sel := ProjectAssignSelection{}
	sel.Rows, err = pgx.CollectRows(rows, func(row pgx.CollectableRow) (ProjectAssignRow, error) {
		var r ProjectAssignRow
		var status string
		err := row.Scan(&r.AssignmentID, &r.ProjectID, &r.ProjectName, &r.SchoolID, &r.SchoolName, &r.SchoolType, &status,
			&r.intervention, &r.targets)
		if in(rules.ClosedStatuses, status) {
			r.Reason = rules.ClosedSchoolMessage
		}
		return r, err
	})
	if err != nil {
		return ProjectAssignSelection{}, fmt.Errorf("activities: reading a selected project school: %w", err)
	}
	sel.ProjectPartners, sel.Listed, err = s.projectPartners(ctx, sel.Included())
	return sel, err
}

// projectPartners is _project_partner_ids over the included schools'
// projects.
func (s *Service) projectPartners(ctx context.Context, included []ProjectAssignRow) ([]string, bool, error) {
	projects := []string{}
	for _, r := range included {
		if !slices.Contains(projects, r.ProjectID) {
			projects = append(projects, r.ProjectID)
		}
	}
	rows, err := s.db.Query(ctx, `SELECT project_id, partner_id FROM project_partner_assignment WHERE project_id = ANY($1)`, projects)
	if err != nil {
		return nil, false, fmt.Errorf("activities: reading the projects' partners: %w", err)
	}
	rosters := map[string][]string{}
	for rows.Next() {
		var project, partner string
		if err := rows.Scan(&project, &partner); err != nil {
			rows.Close()
			return nil, false, err
		}
		rosters[project] = append(rosters[project], partner)
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, false, err
	}
	if len(rosters) == 0 {
		return nil, false, nil
	}
	var shared []string
	first := true
	for _, roster := range rosters {
		if first {
			shared, first = slices.Clone(roster), false
			continue
		}
		shared = slices.DeleteFunc(shared, func(id string) bool { return !slices.Contains(roster, id) })
	}
	return shared, true, nil
}

// measured is Project.measured_by_ssa: a target that is an SSA
// intervention, or no General target.
func (r ProjectAssignRow) measured() bool {
	targets := r.projectTargets()
	for _, t := range targets {
		if canonicalNamed(t) {
			return true
		}
	}
	return !slices.Contains(targets, rules.GeneralIntervention)
}

// projectTargets is target_intervention_list.
func (r ProjectAssignRow) projectTargets() []string {
	targets := slices.Clone(r.targets)
	if r.intervention != "" && !slices.Contains(targets, r.intervention) {
		targets = append(targets, r.intervention)
	}
	return targets
}

// primary is intervention_plan()[0]: the explicit intervention when it is a
// target, else the first SSA target.
func (r ProjectAssignRow) primary() string {
	var targets []string
	for _, t := range r.projectTargets() {
		if canonicalNamed(t) && !slices.Contains(targets, t) {
			targets = append(targets, t)
		}
	}
	switch {
	case len(targets) == 0:
		return ""
	case slices.Contains(targets, r.intervention):
		return r.intervention
	}
	return targets[0]
}

// projectFocus is _project_focus: none for a project no SSA intervention
// measures, else the chosen focus or, for work that moves one, the
// project's primary intervention.
func (r ProjectAssignRow) projectFocus(focus, purpose string) string {
	if !r.measured() {
		return ""
	}
	if focus == "" && !in(rules.Purposes.InterventionFree, purpose) {
		focus = r.primary()
	}
	return focus
}

// projectHandOver is one school's turn of the loop, decided before it is
// written.
type projectHandOver struct {
	h    *handOver
	sc   school
	skip bool
	// refusal is the creation door's refusal of this school.
	refusal string
}

// AssignProjectPartner makes the project hand-over, or refuses it in the
// existing words, or hands it on (ErrHandOn) before anything is written.
// The caller has asked can_assign_to_partner.
func (s *Service) AssignProjectPartner(ctx context.Context, p auth.Principal, req ProjectAssignRequest, origin Origin) (Answer, error) {
	if p.InActingAppointment || p.StaffProfileID == "" {
		return Answer{}, handOn("not an account Go saves the project hand-over for")
	}
	sel, err := s.ProjectAssignSelectionFor(ctx, p, req.Assignments)
	if err != nil {
		return Answer{}, err
	}
	if len(sel.Rows) == 0 {
		return Answer{}, refuse(projectAssignNoneSelected)
	}
	included := sel.Included()
	if len(included) == 0 {
		if len(sel.Rows) == 1 {
			return Answer{}, refuse("%s", sel.Rows[0].Reason)
		}
		return Answer{}, refuse(projectAssignNoneOpen)
	}
	partner, err := readAssignablePartner(ctx, s.db, strings.TrimSpace(req.PartnerID))
	if err != nil {
		return Answer{}, err
	}
	if partner == nil {
		return Answer{}, handOn("a partner who may not take new work")
	}
	purpose, it, err := s.bulkHandOverPlan(ctx, p, BulkAssignRequest{Purpose: req.Purpose, Course: req.CourseID})
	var refusal *Refusal
	if errors.As(err, &refusal) {
		return Answer{}, refuse("%s%s", projectAssignAction, refusal.Message)
	}
	if err != nil {
		return Answer{}, err
	}
	focus := strings.TrimSpace(req.Focus)
	if !canonicalNamed(focus) {
		focus = ""
	}
	mappings, err := readMappings(ctx, s.db, it.ID)
	if err != nil {
		return Answer{}, err
	}
	planned := make([]projectHandOver, len(included))
	for i, r := range included {
		if planned[i], err = s.planProjectHandOver(ctx, p, r, *partner, purpose, focus, it, mappings, strings.TrimSpace(req.OverrideReason)); err != nil {
			return Answer{}, err
		}
	}
	created, skipped, refused := 0, 0, []string{}
	for i, b := range planned {
		switch {
		case b.skip:
			skipped++
			continue
		case b.refusal != "":
			refused = append(refused, included[i].SchoolName+": "+b.refusal)
			continue
		}
		err := s.writeProjectHandOver(ctx, b)
		switch {
		case errors.As(err, &refusal):
			refused = append(refused, included[i].SchoolName+": "+refusal.Message)
			continue
		case errors.Is(err, ErrHandOn):
			s.logger.Warn("activities: a project hand-over was handed on after it was planned", "school", b.sc.Code, "err", err)
			refused = append(refused, included[i].SchoolName+": "+partner.Name+" could not be handed this school now.")
			continue
		case err != nil:
			return Answer{}, err
		}
		s.announceHandOver(ctx, p, b.h, origin)
		created++
	}
	message := projectAssignedMessage(created, partner.Name, skipped, refused)
	if created == 0 && len(refused) > 0 {
		return Answer{}, refuse("%s%s", projectAssignAction, message)
	}
	return Answer{Message: message}, nil
}

// projectAssignedMessage is the view's confirmation.
func projectAssignedMessage(count int, partner string, skipped int, refused []string) string {
	message := fmt.Sprintf("No school was assigned to %s.", partner)
	if count > 0 {
		message = fmt.Sprintf("Assigned %d %s to %s. The partner schedules %s from here.", count,
			plural(count, "project school", "project schools"), partner, plural(count, "it", "them"))
	}
	if skipped > 0 {
		message += fmt.Sprintf(" %d %s already assigned to %s and left as they were.", skipped,
			plural(skipped, "school was", "schools were"), partner)
	}
	if len(refused) > 0 {
		message += " Not assigned: " + strings.Join(refused, "; ")
	}
	return message
}

// planProjectHandOver is one school up to create_assignment: the waiting
// hand-over skipped, then the row the door would write. A school whose
// hand-over Go does not make hands the whole selection on.
func (s *Service) planProjectHandOver(ctx context.Context, p auth.Principal, r ProjectAssignRow, partner assignPartner, purpose, focus string,
	it *item, mappings []mapping, override string) (projectHandOver, error) {
	sc, err := schoolByIDOrCode(ctx, s.db, r.SchoolID)
	if err != nil {
		return projectHandOver{}, err
	}
	// reserve_for_assignment holds a Core package's slot for the hand-over.
	if sc == nil || sc.Type == "core" {
		return projectHandOver{}, handOn("a Core school's hand-over holds a package slot")
	}
	label := rules.Purposes.Labels[purpose]
	h := &handOver{id: cuid.New(), school: sc.ID, schoolName: sc.Name, partnerID: partner.ID, partnerName: partner.Name,
		partnerUser: partner.UserID, partnerRole: partner.UserRole, staff: p.StaffProfileID, purpose: purpose, what: label,
		isDataCollection: purpose == ssaSupportPurpose, blankAsNull: true, notes: projectAssignNotes + r.ProjectName,
		reason: visitHandOverReason(label), itemID: it.ID, kind: it.WorkflowKind, assignmentPurpose: projectAssignPurpose + r.ProjectName,
		projectID: r.ProjectID, override: override, outsideSSA: !r.measured()}
	if err := s.reviewUntouched(ctx, s.db, h); err != nil {
		return projectHandOver{}, err
	}
	// The view's skip check builds its instance without the purpose, so it
	// compares the school's support whatever is handed over; the save's own
	// check, in writeProjectHandOver, compares the kind handed over.
	open, err := projectOpenDuplicate(ctx, s.db, h, false)
	if err != nil {
		return projectHandOver{}, err
	}
	if open {
		return projectHandOver{skip: true}, nil
	}
	if sc.closed() {
		return projectHandOver{refusal: rules.ClosedSchoolMessage}, nil
	}
	need, err := schoolNeedOf(ctx, pgNeed{s.db}, sc.ID, sc.ClusterID, s.now())
	if err != nil {
		return projectHandOver{}, err
	}
	if h.focus, err = mappedIntervention(mappings, r.projectFocus(focus, purpose), nil); err != nil {
		var refusal *Refusal
		if errors.As(err, &refusal) {
			return projectHandOver{refusal: refusal.Message}, nil
		}
		return projectHandOver{}, err
	}
	if need.Record != nil {
		h.sourceSSA = need.Record.ID
	}
	return projectHandOver{h: h, sc: *sc}, nil
}

// projectOpenDuplicate is PartnerAssignment.open_duplicate for a new
// project hand-over that names no Core slot: the partner's waiting
// hand-over of the school of the kind asked (data collection or support),
// compared with the project's own alone when no SSA intervention measures
// it.
func projectOpenDuplicate(ctx context.Context, q Querier, h *handOver, dataCollection bool) (bool, error) {
	var open bool
	err := q.QueryRow(ctx, `SELECT EXISTS (SELECT 1 FROM partner_assignment
WHERE school_id = $1 AND partner_id = $2 AND status = ANY($3)
  AND CASE WHEN $4 THEN outside_ssa AND project_id = $5 ELSE NOT outside_ssa END
  AND (COALESCE(purpose_of_visit, '') = $6) = $7
  AND COALESCE(support_type, '') = '' AND COALESCE(visit_number, '') = '' AND COALESCE(training_number, '') = '')`,
		h.school, h.partnerID, []string{handOverAssigned, handOverOpenStatus}, h.outsideSSA, h.projectID, ssaSupportPurpose,
		dataCollection).Scan(&open)
	if err != nil {
		return false, fmt.Errorf("activities: reading the partner's waiting hand-overs: %w", err)
	}
	return open, nil
}

// writeProjectHandOver is create_assignment for a project: the school's row
// locked, the partner's waiting hand-over refused, the row written.
func (s *Service) writeProjectHandOver(ctx context.Context, b projectHandOver) error {
	tx, err := s.db.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite, IsoLevel: pgx.ReadCommitted})
	if err != nil {
		return fmt.Errorf("activities: opening the hand-over: %w", err)
	}
	defer func() { _ = tx.Rollback(ctx) }()
	if _, err := tx.Exec(ctx, `SELECT gateway_lock.lock_school($1)`, b.h.school); err != nil {
		return fmt.Errorf("activities: locking the school: %w", err)
	}
	if err := s.reviewUntouched(ctx, tx, b.h); err != nil {
		return err
	}
	open, err := projectOpenDuplicate(ctx, tx, b.h, b.h.isDataCollection)
	if err != nil {
		return err
	}
	if open {
		return refuse("%s is already assigned to %s and is waiting for the partner to schedule it. A school is assigned to the same partner only once.",
			b.sc.Name, b.h.partnerName)
	}
	if err := insertHandOver(ctx, tx, b.h, s.now()); err != nil {
		return err
	}
	if err := tx.Commit(ctx); err != nil {
		return fmt.Errorf("activities: committing the hand-over: %w", err)
	}
	return nil
}

// reviewUntouched hands on a hand-over after which the school's
// multiple-Partner review would change (support_responsibility.
// sync_multiple_partner_exception, which Go does not keep yet): another
// partner holding the school's live support (active_assignment_q of the
// operational year), or the review already open. Otherwise the sync writes
// nothing.
func (s *Service) reviewUntouched(ctx context.Context, q Querier, h *handOver) error {
	var touched bool
	err := q.QueryRow(ctx, `SELECT EXISTS (SELECT 1 FROM partner_assignment pa LEFT JOIN activity sa ON sa.id = pa.scheduled_activity_id
  WHERE pa.school_id = $1 AND pa.partner_id IS DISTINCT FROM $2 AND pa.status IS DISTINCT FROM 'returned_to_staff'
    AND (pa.scheduled_activity_id IS NULL
      OR (sa.deleted_at IS NULL AND NOT COALESCE(sa.status = ANY($3), false) AND sa.fy >= $4)))
  OR EXISTS (SELECT 1 FROM data_quality_issue WHERE condition_key = $5 AND status = 'open')`,
		h.school, h.partnerID, rules.ClosedHandoverActivityStatuses, schooldirectory.OperationalFY(s.now()),
		"school:"+h.school+"|dq:"+rules.MultiplePartnerIssueType).Scan(&touched)
	if err != nil {
		return fmt.Errorf("activities: reading the school's live partners: %w", err)
	}
	if touched {
		return handOn("the school's multiple-Partner review would change")
	}
	return nil
}
