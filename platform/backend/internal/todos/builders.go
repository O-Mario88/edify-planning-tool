package todos

import (
	"context"
	"fmt"
	"strconv"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"
)

// The builders of a field officer's queue, by the queue's own name for each
// (todo_service._get_todos and MODULE_TODO_BUILDERS). Each says, above it,
// which function it ports. A builder whose records Go does not read yet is a
// guard: it answers errPassOn when the reader has any, so the existing
// application builds the page; otherwise it has nothing to add, as the
// builder would not.
func init() {
	for name, build := range map[string]func(context.Context, *Service, *reader) ([]todo, error){
		"_activity_todos":                                   activityTodos,
		"_school_action_todos":                              schoolActionGuard,
		"_visit_request_todos":                              visitRequestGuard,
		"_partner_delay_todos":                              partnerDelayTodos,
		"_partner_assignment_todos":                         partnerAssignmentGuard,
		"_project_ssa_todos":                                projectSSATodos,
		"_extra_work_todos":                                 extraWorkTodos,
		"_returned_assignment_todos":                        returnedAssignmentTodos,
		"_fund_request_todos":                               fundRequestTodos,
		"_school_quality_todos":                             schoolQualityTodos,
		"_route_todos":                                      routeTodos,
		"_my_target_todos":                                  myTargetGuard,
		"_core_school_todos":                                coreSchoolTodos,
		"_pd_todos":                                         pdGuard,
		"_field_debrief_todos":                              fieldDebriefGuard,
		"_business_transformation_todos":                    loanVerificationTodos,
		"apps.staff_activity.todos:follow_up_todos":         followUpGuard,
		"apps.cce_leadership.todos:coaching_todos":          coachingTodos,
		"apps.cce_leadership.guidance_todos:guidance_todos": guidanceTodos,
		"apps.ssa.collection_todos:collection_todos":        returnedSSATodos,
		"apps.impact.evidence_todos:evidence_todos":         evidenceTodos,
		"apps.planning.fy_todos:fy_planning_todos":          fyPlanningTodos,
		"apps.clusters.followups:attendance_todos":          attendanceTodos,
	} {
		Handled[name] = build
	}
}

// Shapes of the links rows carry (rules.OpenLinks).
func idShape(url, id string) string { return strings.Replace(url, "/"+id, "/{id}", 1) }

// pyStr is str() of a value that may be None.
func pyStr(s *string) string {
	if s == nil {
		return "None"
	}
	return *s
}

func dateOf(t time.Time) *time.Time {
	d := time.Date(t.Year(), t.Month(), t.Day(), 0, 0, 0, 0, time.UTC)
	return &d
}

func plural(n int, word string) string {
	if n == 1 {
		return strconv.Itoa(n) + " " + word
	}
	return strconv.Itoa(n) + " " + word + "s"
}

// exists answers whether a statement finds a row.
func (s *Service) exists(ctx context.Context, sql string, args ...any) (bool, error) {
	var found bool
	if err := s.db.QueryRow(ctx, "SELECT EXISTS ("+sql+")", args...).Scan(&found); err != nil {
		return false, err
	}
	return found, nil
}

func passOnIf(found bool, err error) ([]todo, error) {
	if err != nil {
		return nil, err
	}
	if found {
		return nil, errPassOn
	}
	return nil, nil
}

// activityTodos is _activity_todos: the reader's live activities this year
// (responsible, or monitoring partner delivery), at most 120, newest first,
// each with its next action when that is the reader's to take or wait on.
func activityTodos(ctx context.Context, s *Service, r *reader) ([]todo, error) {
	if len(r.owners) == 0 {
		return nil, nil
	}
	rows, err := s.db.Query(ctx, `
SELECT a.id, a.status, COALESCE(a.delivery_type, ''), COALESCE(a.evidence_status, ''), a.planned_date,
  COALESCE(a.salesforce_activity_id, ''), a.activity_type, COALESCE(a.teachers_attended, 0), COALESCE(a.leaders_attended, 0),
  COALESCE(a.ia_verification_status, ''), COALESCE(a.payment_status, ''), a.school_id IS NOT NULL, s.name,
  COALESCE(s.current_fy_ssa_status, ''), a.cluster_id IS NOT NULL, c.name
FROM activity a LEFT OUTER JOIN school s ON s.id = a.school_id LEFT OUTER JOIN cluster c ON c.id = a.cluster_id
WHERE a.deleted_at IS NULL AND a.fy = $1
  AND (a.responsible_staff_id = ANY($2) OR (a.monitored_by_staff_id = ANY($2) AND a.delivery_type = 'partner'))
  AND NOT (a.status = ANY($3))
ORDER BY a.created_at DESC LIMIT 120`, r.fy, r.owners, rules.ActivitySettledStatuses)
	if err != nil {
		return nil, err
	}
	type found struct {
		a                   activity
		hasCluster          bool
		schoolName, cluster *string
	}
	list, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (found, error) {
		var f found
		var planned *time.Time
		err := row.Scan(&f.a.ID, &f.a.Status, &f.a.DeliveryType, &f.a.EvidenceStatus, &planned, &f.a.SalesforceID,
			&f.a.ActivityType, &f.a.Teachers, &f.a.Leaders, &f.a.IAVerification, &f.a.Payment, &f.a.HasSchool,
			&f.schoolName, &f.a.SchoolSSAStatus, &f.hasCluster, &f.cluster)
		if planned != nil {
			f.a.PlannedDate = dateOf(*planned)
		}
		return f, err
	})
	if err != nil || len(list) == 0 {
		return nil, err
	}
	ids := make([]string, len(list))
	for i, f := range list {
		ids[i] = f.a.ID
	}
	advances, err := s.advances(ctx, ids)
	if err != nil {
		return nil, err
	}
	var out []todo
	for _, f := range list {
		a := f.a
		a.Advances = advances[a.ID]
		na := computeNextAction(a, r.today)
		actionable := contains(rules.Actionable, na.Action)
		if !actionable && !contains(rules.Waiting, na.Action) {
			continue
		}
		meta, ok := rules.ActionMeta[na.Action]
		if !ok {
			meta = [2]string{"Execution", "View"}
		}
		where := "—"
		switch {
		case a.HasSchool:
			where = pyStr(f.schoolName)
		case f.hasCluster:
			where = pyStr(f.cluster)
		}
		out = append(out, todo{Title: na.Text, Category: meta[0], Priority: actPriority(a, na.Action, r.today),
			StatusKey: actStatus(a, na.Action, r.today), Actionable: actionable,
			Linked: where + " · " + typeLabel(a.ActivityType), ActionLabel: meta[1], ActionURL: na.URL,
			Shape: idShape(na.URL, a.ID), Due: a.PlannedDate})
	}
	return out, nil
}

// advances are each activity's advance requests, cost line by cost line, as
// the prefetch schedule_cost_lines__advance_requests reads them: the lines
// in the order they come back, each line's advances newest first.
func (s *Service) advances(ctx context.Context, activityIDs []string) (map[string][]advance, error) {
	rows, err := s.db.Query(ctx, `SELECT id, activity_id FROM activity_schedule_cost_line WHERE activity_id = ANY($1)`, activityIDs)
	if err != nil {
		return nil, err
	}
	type line struct{ id, activity string }
	lines, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (line, error) {
		var l line
		return l, row.Scan(&l.id, &l.activity)
	})
	if err != nil || len(lines) == 0 {
		return nil, err
	}
	lineIDs := make([]string, len(lines))
	for i, l := range lines {
		lineIDs[i] = l.id
	}
	rows, err = s.db.Query(ctx, `
SELECT budget_line_id, status, reimbursement_receipt_confirmed_at IS NOT NULL, COALESCE(accountability_netsuite_id, '') <> ''
FROM advance_request WHERE budget_line_id = ANY($1) ORDER BY created_at DESC`, lineIDs)
	if err != nil {
		return nil, err
	}
	byLine := map[string][]advance{}
	for rows.Next() {
		var lineID string
		var a advance
		if err := rows.Scan(&lineID, &a.Status, &a.ReceiptConfirmed, &a.NetSuite); err != nil {
			rows.Close()
			return nil, err
		}
		byLine[lineID] = append(byLine[lineID], a)
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, err
	}
	out := map[string][]advance{}
	for _, l := range lines {
		out[l.activity] = append(out[l.activity], byLine[l.id]...)
	}
	return out, nil
}

// schoolActionGuard stands for _school_action_todos: a school action handed
// to the reader opens the route recorded with it, which Go cannot gate yet.
func schoolActionGuard(ctx context.Context, s *Service, r *reader) ([]todo, error) {
	return passOnIf(s.exists(ctx, `SELECT 1 FROM team_action WHERE recipient_id = $1 AND state = ANY($2)`,
		r.p.UserID, rules.TeamActionActiveStates))
}

// visitRequestGuard stands for _visit_request_todos: visits into the
// reader's portfolio waiting for their yes.
func visitRequestGuard(ctx context.Context, s *Service, r *reader) ([]todo, error) {
	return passOnIf(s.exists(ctx, `SELECT 1 FROM activity WHERE deleted_at IS NULL AND status = $1 AND approval_owner_id = ANY($2)`,
		rules.VisitRequestAwaiting, r.owners))
}

// partnerDelayTodos is _partner_delay_todos: partner work the reader
// monitors that is past its date and not yet handed in, at most ten.
func partnerDelayTodos(ctx context.Context, s *Service, r *reader) ([]todo, error) {
	if len(r.owners) == 0 {
		return nil, nil
	}
	rows, err := s.db.Query(ctx, `
SELECT a.id, a.planned_date, a.school_id IS NOT NULL, s.name
FROM activity a LEFT OUTER JOIN school s ON s.id = a.school_id
WHERE a.deleted_at IS NULL AND a.delivery_type = 'partner' AND a.monitored_by_staff_id = ANY($1) AND a.planned_date < $2
  AND NOT (a.status = ANY($3))
ORDER BY a.created_at DESC LIMIT 10`, r.owners, r.today, rules.PartnerDelaySettledStatuses)
	if err != nil {
		return nil, err
	}
	return pgx.CollectRows(rows, func(row pgx.CollectableRow) (todo, error) {
		var id string
		var planned time.Time
		var hasSchool bool
		var name *string
		err := row.Scan(&id, &planned, &hasSchool, &name)
		where := "the field"
		if hasSchool {
			where = pyStr(name)
		}
		return todo{Title: "Chase Partner Delivery", Category: "Partner", Priority: "high", StatusKey: "overdue",
			Actionable: true, Linked: where + " · partner", ActionLabel: "Open", ActionURL: "/my-plan/" + id,
			Shape: "/my-plan/{id}", Due: dateOf(planned)}, err
	})
}

// partnerAssignmentGuard stands for _partner_assignment_todos, which reads
// the partner ids the scope resolves for the partner roles only.
func partnerAssignmentGuard(_ context.Context, _ *Service, r *reader) ([]todo, error) {
	if contains(rules.PartnerScopeRoles, r.role) {
		return nil, errPassOn
	}
	return nil, nil
}

// projectSSATodos is _project_ssa_todos: schools the reader enrolled in a
// project with no baseline, and follow-ups whose window has opened.
func projectSSATodos(ctx context.Context, s *Service, r *reader) ([]todo, error) {
	if r.p.UserID == "" {
		return nil, nil
	}
	var out []todo
	for _, q := range []struct {
		where, title string
		args         []any
	}{
		{`psa.assigned_by = $1 AND psa.baseline_score IS NULL`, "Collect Current FY SSA", []any{r.p.UserID}},
		{`psa.assigned_by = $1 AND psa.impact_classification = $2 AND psa.follow_up_due_on <= $3 AND psa.follow_up_ssa_id IS NULL`,
			"Complete Follow-Up SSA", []any{r.p.UserID, rules.ProjectNotYetMeasurable, r.today}},
	} {
		rows, err := s.db.Query(ctx, `
SELECT psa.school_id, s.name, p.name
FROM project_school_assignment psa INNER JOIN project p ON p.id = psa.project_id INNER JOIN school s ON s.id = psa.school_id
WHERE `+q.where+` LIMIT 20`, q.args...)
		if err != nil {
			return nil, err
		}
		got, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (todo, error) {
			var schoolID string
			var school, project *string
			err := row.Scan(&schoolID, &school, &project)
			return todo{Title: q.title, Category: "Special Project", Priority: "high", StatusKey: "open", Actionable: true,
				Linked: pyStr(school) + " · " + pyStr(project), ActionLabel: "Open school", ActionURL: "/schools/" + schoolID,
				Shape: "/schools/{id}", Due: &r.today}, err
		})
		if err != nil {
			return nil, err
		}
		out = append(out, got...)
	}
	return out, nil
}

// extraWorkTodos is _extra_work_todos: the reader's open extra work, what
// waits on their review, and what they assigned that is overdue.
func extraWorkTodos(ctx context.Context, s *Service, r *reader) ([]todo, error) {
	if r.p.UserID == "" {
		return nil, nil
	}
	row := func(due time.Time, status, title, label, priority, linked string) todo {
		return todo{Title: title, Category: "Extra Work", Priority: priority, StatusKey: status, Actionable: true,
			Linked: linked, ActionLabel: label, ActionURL: "/extra-work", Shape: "/extra-work", Due: dateOf(due)}
	}
	var out []todo
	read := func(sql string, args []any, each func(due time.Time, status, title, urgency string)) error {
		rows, err := s.db.Query(ctx, `SELECT due_date, status, title, urgency FROM hr_extra_assignment WHERE `+sql, args...)
		if err != nil {
			return err
		}
		defer rows.Close()
		for rows.Next() {
			var due time.Time
			var status, title, urgency string
			if err := rows.Scan(&due, &status, &title, &urgency); err != nil {
				return err
			}
			each(due, status, title, urgency)
		}
		return rows.Err()
	}
	err := read(`assignee_id = $1 AND status = ANY($2) ORDER BY due_date ASC LIMIT 20`, []any{r.p.UserID, rules.ExtraOpenStatuses},
		func(due time.Time, status, title, urgency string) {
			switch {
			case status == "returned":
				out = append(out, row(due, status, "Correct Returned Extra Work", "Correct", "high", title))
			case due.Before(r.today):
				out = append(out, row(due, status, "Resolve Overdue Extra Work", "Complete", "high", title))
			default:
				priority := "high"
				if urgency == "normal" {
					priority = "medium"
				}
				out = append(out, row(due, status, "Complete Extra Assignment", "Open", priority, title))
			}
		})
	if err != nil {
		return nil, err
	}
	err = read(`reviewer_id = $1 AND status = 'submitted' ORDER BY submitted_at ASC LIMIT 20`, []any{r.p.UserID},
		func(due time.Time, status, title, _ string) {
			out = append(out, row(due, status, "Review Extra Work", "Review", "high", title))
		})
	if err != nil {
		return nil, err
	}
	err = read(`assigner_id = $1 AND status = ANY($2) AND due_date < $3 ORDER BY due_date ASC LIMIT 10`,
		[]any{r.p.UserID, rules.ExtraOpenStatuses, r.today},
		func(due time.Time, status, title, _ string) {
			out = append(out, row(due, status, "Chase Overdue Extra Work", "Follow up", "medium", title))
		})
	return out, err
}

// returnedAssignmentTodos is _returned_assignment_todos: partner work handed
// back to the reader and not yet decided, newest return first, at most ten.
func returnedAssignmentTodos(ctx context.Context, s *Service, r *reader) ([]todo, error) {
	if len(r.owners) == 0 {
		return nil, nil
	}
	rows, err := s.db.Query(ctx, `
SELECT pa.school_id IS NOT NULL, s.name, pa.cluster_id IS NOT NULL, c.name, p.name, pa.partner_id, pa.returned_at
FROM partner_assignment pa INNER JOIN partner p ON p.id = pa.partner_id
  LEFT OUTER JOIN school s ON s.id = pa.school_id LEFT OUTER JOIN cluster c ON c.id = pa.cluster_id
WHERE pa.status = $1 AND pa.assigning_staff_id = ANY($2) AND pa.resolved_at IS NULL
ORDER BY pa.returned_at DESC LIMIT 10`, rules.ReturnedToStaffStatus, r.owners)
	if err != nil {
		return nil, err
	}
	return pgx.CollectRows(rows, func(row pgx.CollectableRow) (todo, error) {
		var hasSchool, hasCluster bool
		var school, cluster, partner *string
		var partnerID string
		var returned *time.Time
		err := row.Scan(&hasSchool, &school, &hasCluster, &cluster, &partner, &partnerID, &returned)
		where := "an assignment"
		switch {
		case hasSchool:
			where = pyStr(school)
		case hasCluster:
			where = pyStr(cluster)
		}
		t := todo{Title: "Resolve Returned Partner Assignment", Category: "Partner", Priority: "high", StatusKey: "returned",
			Actionable: true, Linked: where + " · " + pyStr(partner), ActionLabel: "Review",
			ActionURL: "/partner-oversight/?partner=" + partnerID + "&status=returned",
			Shape:     "/partner-oversight/?partner={id}&status=returned"}
		if returned != nil {
			t.Due = dateOf(returned.UTC())
		}
		return t, err
	})
}

// fundRequestTodos is _fund_request_todos for a reader who approves no
// fund requests: their own weekly requests to confirm or fix, returned
// monthly plans, and disbursed funds to confirm. An approver's queue is
// passed on.
func fundRequestTodos(ctx context.Context, s *Service, r *reader) ([]todo, error) {
	if status, approves := rules.WeeklyApproverStatus[r.role]; approves {
		if r.role != leadRole {
			return nil, errPassOn
		}
		if _, err := passOnIf(leadApprovalsGuard(ctx, s, status)); err != nil {
			return nil, err
		}
	}
	uid := r.p.UserID
	var out []todo
	rows, err := s.db.Query(ctx, `SELECT id, status, week_start_date FROM weekly_fund_request
WHERE responsible_user = $1 AND status = ANY($2) ORDER BY week_start_date DESC LIMIT 10`,
		uid, append([]string{rules.WeeklyConfirmStatus}, rules.WeeklyReturnedStatuses...))
	if err != nil {
		return nil, err
	}
	got, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (todo, error) {
		var id, status string
		var week time.Time
		err := row.Scan(&id, &status, &week)
		t := todo{Title: "Confirm Fund Request", Category: "Finance", Priority: "high", StatusKey: "waiting_me",
			Actionable: true, Linked: "Weekly Fund Request · " + week.Format("Jan") + " " + strconv.Itoa(week.Day()),
			ActionLabel: "Open", ActionURL: "/fund-requests/weekly/" + id, Shape: "/fund-requests/weekly/{id}", Due: &r.today}
		if contains(rules.WeeklyReturnedStatuses, status) {
			t.Title, t.Priority, t.StatusKey = "Fix Fund Request", "critical", "returned"
		}
		return t, err
	})
	if err != nil {
		return nil, err
	}
	out = append(out, got...)
	monthly := func(sql, title, priority, status, label string, args ...any) error {
		rows, err := s.db.Query(ctx, `SELECT COALESCE(period_key, 'None') FROM fund_request WHERE `+sql, args...)
		if err != nil {
			return err
		}
		got, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (todo, error) {
			var key string
			err := row.Scan(&key)
			return todo{Title: title, Category: "Finance", Priority: priority, StatusKey: status, Actionable: true,
				Linked: "Monthly Fund Plan · " + key, ActionLabel: label, ActionURL: "/fund-requests/weekly",
				Shape: "/fund-requests/weekly", Due: &r.today}, err
		})
		out = append(out, got...)
		return err
	}
	if err := monthly(`submitted_by_user_id = $1 AND period = 'monthly' AND status = ANY($2) ORDER BY reviewed_at DESC LIMIT 8`,
		"Fix Returned Fund Request", "critical", "returned", "Fix", uid, rules.MonthlyReturnedStatuses); err != nil {
		return nil, err
	}
	rows, err = s.db.Query(ctx, `SELECT id, week_start_date FROM weekly_fund_request
WHERE responsible_user = $1 AND status = 'disbursed' AND receipt_confirmed_at IS NULL ORDER BY disbursed_at DESC LIMIT 5`, uid)
	if err != nil {
		return nil, err
	}
	got, err = pgx.CollectRows(rows, func(row pgx.CollectableRow) (todo, error) {
		var id string
		var week time.Time
		err := row.Scan(&id, &week)
		return todo{Title: "Confirm Receipt of Funds", Category: "Finance", Priority: "high", StatusKey: "waiting_me",
			Actionable: true, Linked: "Weekly Fund Request · " + week.Format("02 Jan"), ActionLabel: "Confirm",
			ActionURL: "/fund-requests/weekly/" + id, Shape: "/fund-requests/weekly/{id}", Due: &r.today}, err
	})
	if err != nil {
		return nil, err
	}
	out = append(out, got...)
	if err := monthly(`submitted_by_user_id = $1 AND period = 'monthly' AND status = 'disbursed' AND receipt_confirmed_at IS NULL
ORDER BY disbursed_at DESC LIMIT 5`, "Confirm Receipt of Funds", "high", "waiting_me", "Confirm", uid); err != nil {
		return nil, err
	}
	return out, nil
}

// schoolQualityTodos is _school_quality_todos: the reader's own operating
// schools (a lead's own only; anyone else's own, or their scope when they
// own none) with no contact, no cluster, or no SSA this year, eight of each.
func schoolQualityTodos(ctx context.Context, s *Service, r *reader) ([]todo, error) {
	ids := r.scope.OwnSchoolIDs
	if len(ids) == 0 && r.role != "Program Lead" {
		ids = r.scope.SchoolIDs
	}
	if len(ids) == 0 {
		return nil, nil
	}
	var out []todo
	for _, q := range []struct{ where, title, category, priority, label, url string }{
		{`(s.primary_contact_name IS NULL OR s.primary_contact_name = '')`, "Fix School Contact", "Data Quality", "low", "Fix", "/schools"},
		{`s.cluster_status = 'unclustered'`, "Add School to Cluster", "Planning", "medium", "Cluster", "/clusters"},
		{`s.cluster_status = 'clustered' AND s.current_fy_ssa_status = 'not_done'`, "Schedule SSA Visit", "SSA", "medium", "Schedule", "/planning"},
	} {
		rows, err := s.db.Query(ctx, `SELECT s.name FROM school s
WHERE s.deleted_at IS NULL AND s.id = ANY($1) AND s.operational_status = ANY($2) AND `+q.where+`
ORDER BY s.created_at DESC LIMIT 8`, ids, rules.OperatingStatuses)
		if err != nil {
			return nil, err
		}
		got, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (todo, error) {
			var name *string
			err := row.Scan(&name)
			return todo{Title: q.title, Category: q.category, Priority: q.priority, StatusKey: "waiting_me", Actionable: true,
				Linked: pyStr(name), ActionLabel: q.label, ActionURL: q.url, Shape: q.url}, err
		})
		if err != nil {
			return nil, err
		}
		out = append(out, got...)
	}
	return out, nil
}

// routeTodos is _route_todos: the reader's coming visit days whose route
// reads weak location data, and the first that is not feasible.
func routeTodos(ctx context.Context, s *Service, r *reader) ([]todo, error) {
	if r.role != "CCEO" && r.role != "Program Lead" {
		return nil, nil
	}
	rows, err := s.db.Query(ctx, `SELECT visit_date, COALESCE(confidence, ''), COALESCE(feasible, false), COALESCE(status, '')
FROM daily_visit_route_batch WHERE responsible_user = $1 AND visit_date >= $2 ORDER BY visit_date ASC LIMIT 10`, r.p.UserID, r.today)
	if err != nil {
		return nil, err
	}
	type batch struct {
		day                time.Time
		confidence, status string
		feasible           bool
	}
	batches, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (batch, error) {
		var b batch
		return b, row.Scan(&b.day, &b.confidence, &b.feasible, &b.status)
	})
	if err != nil {
		return nil, err
	}
	var out []todo
	for _, b := range batches {
		if b.confidence == "low" || b.confidence == "needs_cleanup" {
			out = append(out, todo{Title: "Fix school location / coordinates", Category: "Data Quality", Priority: "medium",
				StatusKey: "waiting_me", Actionable: true, Linked: "Route Intelligence", ActionLabel: "Review Schools",
				ActionURL: "/my-plan", Shape: "/my-plan", Due: &r.today})
			break
		}
	}
	for _, b := range batches {
		if !b.feasible || b.status == "not_feasible" || b.status == "blocked" {
			out = append(out, todo{Title: "Rework route plan — day overloaded", Category: "Planning", Priority: "high",
				StatusKey: "waiting_me", Actionable: true, Linked: "Route Intelligence", ActionLabel: "Open My Plan",
				ActionURL: "/my-plan", Shape: "/my-plan", Due: dateOf(b.day)})
			break
		}
	}
	return out, nil
}

// myTargetGuard stands for _my_target_todos, whose focus list is drawn from
// the reader's agreed priorities or legacy monthly targets: with neither it
// is empty (and the achievement rebuild it runs first writes nothing that
// the list reads).
func myTargetGuard(ctx context.Context, s *Service, r *reader) ([]todo, error) {
	found, err := s.exists(ctx, `SELECT 1 FROM hr_performance_review WHERE staff_id = $1 AND review_type = $2 AND NOT (stage = ANY($3))
UNION ALL SELECT 1 FROM monthly_personal_target WHERE user_id = $4 AND target > 0`,
		r.p.StaffProfileID, rules.TargetReviewType, rules.TargetReviewStagesNotAgreed, r.p.UserID)
	return passOnIf(found, err)
}

// pdGuard stands for _pd_todos: any Professional Development request.
func pdGuard(ctx context.Context, s *Service, _ *reader) ([]todo, error) {
	return passOnIf(s.exists(ctx, `SELECT 1 FROM pd_request`))
}

// fieldDebriefGuard stands for _field_debrief_todos: any live debrief, or a
// debrief action the reader owns.
func fieldDebriefGuard(ctx context.Context, s *Service, r *reader) ([]todo, error) {
	return passOnIf(s.exists(ctx, `SELECT 1 FROM daily_debrief WHERE deleted_at IS NULL
UNION ALL SELECT 1 FROM daily_debrief_action WHERE owner_user_id = $1`, r.p.UserID))
}

// followUpGuard stands for follow_up_todos: a Staff Activity follow-up sent
// to the reader or by them (whose listing also resolves those the record
// shows were met, a write Go does not make).
func followUpGuard(ctx context.Context, s *Service, r *reader) ([]todo, error) {
	return passOnIf(s.exists(ctx, `SELECT 1 FROM staff_usage_follow_up WHERE assignee_id = $1 OR created_by_id = $1`, r.p.UserID))
}

// coachingGuard stands for coaching_todos: coaching addressed to the reader
// and not yet acknowledged.
func coachingGuard(ctx context.Context, s *Service, r *reader) ([]todo, error) {
	return passOnIf(s.exists(ctx, `SELECT 1 FROM cce_cceo_coaching WHERE acknowledged_at IS NULL
  AND (cceo_user_id = $1 OR cceo_staff_id = $2)`, r.p.UserID, r.p.StaffProfileID))
}

// guidanceGuard stands for guidance_todos: guidance addressed to the reader
// and not yet acknowledged.
func guidanceGuard(ctx context.Context, s *Service, r *reader) ([]todo, error) {
	return passOnIf(s.exists(ctx, `SELECT 1 FROM cce_team_guidance_receipt WHERE acknowledged_at IS NULL
  AND (recipient_user_id = $1 OR recipient_staff_id = $2)`, r.p.UserID, r.p.StaffProfileID))
}

// coreSchoolTodos is _core_school_todos for a field officer: for each core
// school in their scope, its returned slots (two) and the next unscheduled
// slot of each kind, twelve rows at most.
func coreSchoolTodos(ctx context.Context, s *Service, r *reader) ([]todo, error) {
	if r.role == leadRole {
		return leadCoreGuard(ctx, s, r)
	}
	if r.role != "CCEO" {
		return nil, errPassOn
	}
	if len(r.scope.SchoolIDs) == 0 {
		return nil, nil
	}
	rows, err := s.db.Query(ctx, `SELECT school_id, name FROM school
WHERE deleted_at IS NULL AND operational_status = ANY($1) AND id = ANY($2) AND school_type = 'core' ORDER BY created_at DESC`,
		rules.OperatingStatuses, r.scope.SchoolIDs)
	if err != nil {
		return nil, err
	}
	names := map[string]string{}
	var codes []string
	for rows.Next() {
		var code, name *string
		if err := rows.Scan(&code, &name); err != nil {
			rows.Close()
			return nil, err
		}
		if code == nil {
			continue // a None key matches no plan
		}
		if _, seen := names[*code]; !seen {
			codes = append(codes, *code)
		}
		names[*code] = pyStr(name)
	}
	rows.Close()
	if err := rows.Err(); err != nil || len(codes) == 0 {
		return nil, err
	}
	rows, err = s.db.Query(ctx, `SELECT id, school_id FROM core_plan
WHERE school_id = ANY($1) AND fy = $2 AND NOT (status = ANY($3) AND status IS NOT NULL) LIMIT 40`,
		codes, r.fy, []string{"Cancelled", "cancelled"})
	if err != nil {
		return nil, err
	}
	type plan struct{ id, school string }
	plans, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (plan, error) {
		var p plan
		return p, row.Scan(&p.id, &p.school)
	})
	if err != nil || len(plans) == 0 {
		return nil, err
	}
	planIDs := make([]string, len(plans))
	for i, p := range plans {
		planIDs[i] = p.id
	}
	rows, err = s.db.Query(ctx, `SELECT id, core_plan_id, activity_type, sequence_number, status FROM core_activity_slot
WHERE core_plan_id = ANY($1)`, planIDs)
	if err != nil {
		return nil, err
	}
	slots := map[string][]coreSlot{}
	for rows.Next() {
		var sl coreSlot
		var planID string
		if err := rows.Scan(&sl.ID, &planID, &sl.Kind, &sl.Sequence, &sl.Status); err != nil {
			rows.Close()
			return nil, err
		}
		slots[planID] = append(slots[planID], sl)
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, err
	}
	var out []todo
	for _, p := range plans {
		name, ok := names[p.school]
		if !ok {
			name = p.school
		}
		returned, missing := corePlanGaps(slots[p.id])
		for _, sl := range returned[:min(2, len(returned))] {
			out = append(out, todo{Title: "Fix returned core " + sl.Kind + " — " + name, Category: "Core Schools",
				Priority: "high", StatusKey: "returned", Actionable: true, Linked: name, ActionLabel: "Open Core Schools",
				ActionURL: "/core-schools", Shape: "/core-schools", Due: &r.today})
		}
		for _, m := range missing {
			tag := "Core Assessment"
			if m.kind != "assessment" {
				tag = m.label[:1] + strconv.Itoa(m.slot.Sequence) + " Core " + m.label
			}
			out = append(out, todo{Title: "Schedule " + tag + " — " + name, Category: "Core Schools", Priority: "medium",
				StatusKey: "waiting_me", Actionable: true, Linked: name, ActionLabel: "Plan Now", ActionURL: "/core-schools",
				Shape: "/core-schools", Due: &r.today})
		}
	}
	return out[:min(12, len(out))], nil
}

// coreSlot is one slot of a core plan.
type coreSlot struct {
	ID, Kind, Status string
	Sequence         int
}

type coreGap struct {
	kind, label string
	slot        coreSlot
}

// corePlanGaps is _core_plan_gaps: a plan's returned slots, and for each
// kind its first slot by sequence that is neither done, in flight nor
// returned.
func corePlanGaps(slots []coreSlot) ([]coreSlot, []coreGap) {
	var returned []coreSlot
	for _, sl := range slots {
		if contains(rules.CoreReturnedStatuses, sl.Status) {
			returned = append(returned, sl)
		}
	}
	var missing []coreGap
	for _, k := range rules.CoreKinds {
		var kind []coreSlot
		for _, sl := range slots {
			if sl.Kind == k[0] {
				kind = append(kind, sl)
			}
		}
		sortStable(kind, func(a, b coreSlot) bool { return a.Sequence < b.Sequence })
		for _, sl := range kind {
			if !contains(rules.CoreDoneStatuses, sl.Status) && !contains(rules.CoreInFlightStatuses, sl.Status) &&
				!contains(rules.CoreReturnedStatuses, sl.Status) {
				missing = append(missing, coreGap{k[0], k[1], sl})
				break
			}
		}
	}
	return returned, missing
}

// loanVerificationTodos is _business_transformation_todos for a field
// officer: loan-use verification visits to plan at their schools.
func loanVerificationTodos(ctx context.Context, s *Service, r *reader) ([]todo, error) {
	if r.role == leadRole {
		return passOnIf(len(r.scope.OwnSchoolIDs) > 0, nil)
	}
	if r.role != "CCEO" {
		return nil, errPassOn
	}
	if len(r.scope.SchoolIDs) == 0 {
		return nil, nil
	}
	rows, err := s.db.Query(ctx, `
SELECT r.due_date, s.name, s.school_id
FROM bt_loan_verification_requirement r INNER JOIN bt_mfi_loan l ON l.id = r.loan_id INNER JOIN school s ON s.id = l.school_id
WHERE r.loan_id IN (SELECT id FROM bt_mfi_loan WHERE deleted_at IS NULL AND school_id = ANY($1))
  AND r.activity_id IS NULL AND r.status = ANY($2)
ORDER BY r.due_date ASC LIMIT 30`, r.scope.SchoolIDs, rules.LoanFieldVerificationStates)
	if err != nil {
		return nil, err
	}
	return pgx.CollectRows(rows, func(row pgx.CollectableRow) (todo, error) {
		var due time.Time
		var name, code *string
		err := row.Scan(&due, &name, &code)
		t := todo{Title: "Complete Loan-Use Verification", Category: "Business Transformation", Priority: "high",
			StatusKey: "waiting_me", Actionable: true, Linked: pyStr(name), ActionLabel: "Plan Visit",
			ActionURL: "/schools/" + pyStr(code) + "#school-bt-title", Shape: "/schools/{code}#school-bt-title", Due: dateOf(due)}
		if dateOf(due).Before(r.today) {
			t.Priority, t.StatusKey = "critical", "overdue"
		}
		return t, err
	})
}

// returnedSSATodos is collection_todos for a field officer: SSA records a
// verifier returned to them, as one row due a week after the oldest return.
func returnedSSATodos(ctx context.Context, s *Service, r *reader) ([]todo, error) {
	if r.role == leadRole {
		if _, err := passOnIf(leadSSAConfirmGuard(ctx, s, r)); err != nil {
			return nil, err
		}
	} else if r.role != "CCEO" {
		return nil, errPassOn
	}
	if len(r.owners) == 0 {
		return nil, nil
	}
	var n int
	var oldest *time.Time
	if err := s.db.QueryRow(ctx, `SELECT COUNT(id), MIN(returned_at) FROM ssa_record
WHERE deleted_at IS NULL AND verification_status = 'returned' AND collected_by_user_id = ANY($1)`, r.owners).Scan(&n, &oldest); err != nil {
		return nil, err
	}
	if n == 0 {
		return nil, nil
	}
	t := todo{Title: "Correct " + plural(n, "SSA record") + " returned to you", Category: "Baseline & Field Data",
		Priority: "high", StatusKey: "waiting_me", Actionable: true, Linked: plural(n, "record"),
		ActionLabel: "Open Returned SSA", ActionURL: "/ssa/verification/?status=returned&mine=1",
		Shape: "/ssa/verification/?status=returned&mine=1", Due: &r.today}
	if oldest != nil {
		due := dateOf(oldest.In(zone)).AddDate(0, 0, 7)
		t.Due = &due
		if due.Before(r.today) {
			t.StatusKey = "overdue"
		}
	}
	return []todo{t}, nil
}

// evidenceTodos is evidence_todos for a field officer: evidence returned to
// them passes the reader on; delivered OneTest visits with no results
// recorded are a row each (ten).
func evidenceTodos(ctx context.Context, s *Service, r *reader) ([]todo, error) {
	if r.role != "CCEO" && r.role != leadRole {
		return nil, errPassOn
	}
	var parts []string
	for _, table := range rules.EvidenceTables {
		parts = append(parts, `SELECT 1 FROM `+pgx.Identifier{table}.Sanitize()+` WHERE verification_status = $1 AND recorded_by_user_id = $2`)
	}
	if found, err := s.exists(ctx, strings.Join(parts, " UNION ALL "), rules.EvidenceReturned, r.p.UserID); err != nil || found {
		return passOnIf(found, err)
	}
	if len(r.owners) == 0 {
		return nil, nil
	}
	rows, err := s.db.Query(ctx, `
SELECT a.id, s.name, a.actual_delivery_date, a.planned_date
FROM activity a INNER JOIN school s ON s.id = a.school_id LEFT OUTER JOIN activity_catalogue_item ci ON ci.id = a.catalogue_item_id
WHERE (a.responsible_staff_id = ANY($1) OR a.monitored_by_staff_id = ANY($1))
  AND (a.costing_profile_snapshot = 'ONETEST' OR ci.costing_profile = 'ONETEST')
  AND a.deleted_at IS NULL AND a.school_id IS NOT NULL AND a.status = ANY($2) AND a.fy = $3
  AND NOT EXISTS (SELECT 1 FROM impact_learning_result lr WHERE lr.source_activity_id = a.id AND lr.deleted_at IS NULL)
ORDER BY a.actual_delivery_date ASC, a.planned_date ASC, a.id ASC LIMIT 10`, r.owners, rules.OnetestDeliveredStatuses, r.fy)
	if err != nil {
		return nil, err
	}
	return pgx.CollectRows(rows, func(row pgx.CollectableRow) (todo, error) {
		var id string
		var name *string
		var delivered, planned *time.Time
		err := row.Scan(&id, &name, &delivered, &planned)
		if delivered == nil {
			delivered = planned
		}
		t := todo{Title: "Record OneTest results for " + pyStr(name), Category: "My Work", Priority: "normal",
			StatusKey: "waiting_me", Actionable: true, Linked: "1 waiting", ActionLabel: "Record Results",
			ActionURL: "/my-plan/" + id + "?learning_results=1", Shape: "/my-plan/{id}?learning_results=1", Due: &r.today}
		if delivered != nil {
			d := dateOf(*delivered)
			t.Due = d
			if r.today.Sub(*d) > 7*24*time.Hour {
				t.Priority, t.StatusKey = "critical", "overdue"
			}
		}
		return t, err
	})
}

// fyPlanningTodos is fy_planning_todos for a planner: the nearest future
// year open for planning, while nothing of theirs is planned in it.
func fyPlanningTodos(ctx context.Context, s *Service, r *reader) ([]todo, error) {
	if r.role != "CCEO" && r.role != leadRole {
		return nil, errPassOn
	}
	operational, _ := strconv.Atoi(r.fy)
	rows, err := s.db.Query(ctx, `SELECT fy, execution_start FROM fiscal_year_planning_policy
WHERE country = $1 AND planning_open_at <= $2 ORDER BY fy ASC`, rules.PlanningCountry, r.now)
	if err != nil {
		return nil, err
	}
	type policy struct {
		fy     string
		starts *time.Time
	}
	policies, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (policy, error) {
		var p policy
		return p, row.Scan(&p.fy, &p.starts)
	})
	if err != nil {
		return nil, err
	}
	for _, p := range policies {
		fy, err := strconv.Atoi(p.fy)
		if err != nil {
			return nil, fmt.Errorf("a planning year that is not a year: %q", p.fy)
		}
		if fy <= operational {
			continue
		}
		if len(r.owners) == 0 {
			return nil, nil
		}
		planned, err := s.exists(ctx, `SELECT 1 FROM activity WHERE fy = $1 AND deleted_at IS NULL AND responsible_staff_id = ANY($2)`,
			p.fy, r.owners)
		if err != nil || planned {
			return nil, err
		}
		t := todo{Title: "Plan FY" + p.fy + " Activities", Category: "Planning", Priority: "medium", StatusKey: "waiting_me",
			Actionable: true, Linked: "FY" + p.fy, ActionLabel: "Open Planning", ActionURL: "/planning", Shape: "/planning",
			Due: &r.today}
		if p.starts != nil {
			d := dateOf(*p.starts)
			t.Due = d
			switch {
			case d.Before(r.today):
				t.StatusKey = "overdue"
			case d.Equal(r.today):
				t.StatusKey = "due_today"
			}
		}
		return []todo{t}, nil
	}
	return nil, nil
}
