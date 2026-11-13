package workplan

import (
	"context"
	"fmt"
	"strconv"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

const (
	roleAdmin           = "Admin"
	roleCountryDirector = "CountryDirector"
	roleAccountant      = "Accountant"
	roleRVP             = "RegionalVicePresident"
	roleCoordinator     = "ProjectCoordinator"
	roleProgramLead     = "Program Lead"
)

// activity is one row of the page's queryset, with the school, cluster,
// districts and catalogue item select_related joins.
type activity struct {
	id, status, activityType, delivery, planningSource string
	planned, endDate                                   *time.Time
	scheduled                                          *time.Time // the local day of scheduled_date
	month                                              *int
	staffID, monitorID, partnerID, projectID           *string
	schoolPK, clusterID, eventDistrictID               *string
	itemID, itemName, nameSnapshot                     *string
	costMissing                                        bool
	pairedVisit, deliveryMode, programmeType           *string
	deliveryMethod, purposeType, focus                 *string
	sourceScore                                        *float64
	alignment, deviation                               string
	evidence, iaVerification, payment                  string
	salesforce                                         *string
	teachersAttended, leadersAttended                  *int

	schoolName, schoolCode, schoolDistrict, schoolCluster, schoolSSA *string
	clusterName, clusterDistrict, eventDistrict                      *string
}

func str(p *string) string {
	if p == nil {
		return ""
	}
	return *p
}

func isSet(p *string) bool { return p != nil && *p != "" }

// scopeFilter is _scoped_activities' narrowing of the FY ledger, as SQL
// over "a" (activity) with its arguments from $n on.
type scopeFilter struct {
	sql  string
	args []any
}

// scoped is _scoped_activities: the whole country for the Admin, the
// Country Director and the Accountant; the RVP's region (or everything
// without one); a coordinator's projects; otherwise the reader's own work in
// both id spaces (a Program Lead's direct team too, on My Plan + Team), and
// partner work they monitor.
func scoped(ctx context.Context, db schooldirectory.Querier, p auth.Principal, scope schooldirectory.Scope, planScope string) (scopeFilter, error) {
	switch p.ActiveRole {
	case roleAdmin, roleCountryDirector, roleAccountant:
		return scopeFilter{sql: "true"}, nil
	case roleRVP:
		if len(scope.RegionIDs) == 0 {
			return scopeFilter{sql: "true"}, nil
		}
		return scopeFilter{sql: `(sd.region_id = ANY($R) OR cd.region_id = ANY($R) OR ed.region_id = ANY($R))`,
			args: []any{scope.RegionIDs}}, nil
	case roleCoordinator:
		ids, err := scopedProjectIDs(ctx, db, p, scope)
		if err != nil {
			return scopeFilter{}, err
		}
		return scopeFilter{sql: `a.project_id = ANY($R)`, args: []any{ids}}, nil
	}
	owners, err := planOwnerIDs(ctx, db, p, planScope)
	if err != nil {
		return scopeFilter{}, err
	}
	return scopeFilter{sql: `(a.responsible_staff_id = ANY($R) OR (a.monitored_by_staff_id = ANY($R) AND a.delivery_type = 'partner'))`,
		args: []any{owners}}, nil
}

// planOwnerIDs is _plan_owner_ids for a reader in their own role: their two
// ids, and on My Plan + Team a Program Lead's live supervisees' two.
func planOwnerIDs(ctx context.Context, db schooldirectory.Querier, p auth.Principal, planScope string) ([]string, error) {
	ids := []string{}
	for _, v := range []string{p.UserID, p.StaffProfileID} {
		if v != "" && !in(ids, v) {
			ids = append(ids, v)
		}
	}
	if p.ActiveRole != roleProgramLead || planScope != "team" || p.StaffProfileID == "" {
		return ids, nil
	}
	rows, err := db.Query(ctx, `SELECT a.supervisee_id, sp.user_id FROM staff_supervisor_assignment a
JOIN staff_profile sp ON sp.id = a.supervisee_id
WHERE a.supervisor_id = $1 AND sp.deleted_at IS NULL`, p.StaffProfileID)
	if err != nil {
		return nil, fmt.Errorf("workplan: team: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var staff string
		var user *string
		if err := rows.Scan(&staff, &user); err != nil {
			return nil, err
		}
		for _, v := range []string{staff, str(user)} {
			if v != "" && !in(ids, v) {
				ids = append(ids, v)
			}
		}
	}
	return ids, rows.Err()
}

// scopedProjects is apps.projects.scoping.scoped_projects: (id, name) by
// name.
func scopedProjects(ctx context.Context, db schooldirectory.Querier, p auth.Principal, scope schooldirectory.Scope) ([][2]string, error) {
	sql := `SELECT DISTINCT pr.id, pr.name FROM project pr WHERE pr.deleted_at IS NULL`
	args := []any{}
	switch {
	case scope.CountryScope:
		if scope.Country != "" {
			sql += ` AND (EXISTS (SELECT 1 FROM project_school_assignment pa JOIN school sc ON sc.id = pa.school_id
    JOIN region r ON r.id = sc.region_id WHERE pa.project_id = pr.id AND r.country = $1)
 OR pr.manager_staff_id IN (SELECT id FROM staff_profile WHERE country = $1 AND deleted_at IS NULL)
 OR (NOT EXISTS (SELECT 1 FROM project_school_assignment pa WHERE pa.project_id = pr.id)
     AND (pr.manager_staff_id IS NULL OR pr.manager_staff_id = '')))`
			args = append(args, scope.Country)
		}
	case p.ActiveRole == roleCoordinator:
		if p.StaffProfileID == "" {
			return [][2]string{}, nil
		}
		sql += ` AND (pr.manager_staff_id = $1 OR EXISTS (SELECT 1 FROM project_staff_assignment a
    WHERE a.project_id = pr.id AND a.staff_id = $1 AND a.is_active))`
		args = append(args, p.StaffProfileID)
	default:
		parts := []string{}
		if staff := p.StaffProfileID; staff != "" {
			args = append(args, staff)
			parts = append(parts, `pr.manager_staff_id = $1`,
				`EXISTS (SELECT 1 FROM project_staff_assignment a WHERE a.project_id = pr.id AND a.staff_id = $1 AND a.is_active)`,
				`EXISTS (SELECT 1 FROM project_staff_capacity c WHERE c.project_id = pr.id AND c.staff_id = $1)`,
				`EXISTS (SELECT 1 FROM project_staff_capacity c WHERE c.project_id = pr.id AND c.staff_id IN (
    SELECT s.supervisee_id FROM staff_supervisor_assignment s WHERE s.supervisor_id = $1))`)
		}
		if len(scope.SchoolIDs) > 0 {
			args = append(args, scope.SchoolIDs)
			parts = append(parts, `EXISTS (SELECT 1 FROM project_school_assignment pa WHERE pa.project_id = pr.id
    AND pa.school_id = ANY($`+strconv.Itoa(len(args))+`))`)
		}
		if len(parts) == 0 {
			return [][2]string{}, nil
		}
		sql += ` AND (` + strings.Join(parts, " OR ") + `)`
	}
	rows, err := db.Query(ctx, sql+` ORDER BY pr.name`, args...)
	if err != nil {
		return nil, fmt.Errorf("workplan: projects: %w", err)
	}
	return pgx.CollectRows(rows, func(row pgx.CollectableRow) ([2]string, error) {
		var out [2]string
		err := row.Scan(&out[0], &out[1])
		return out, err
	})
}

func scopedProjectIDs(ctx context.Context, db schooldirectory.Querier, p auth.Principal, scope schooldirectory.Scope) ([]string, error) {
	projects, err := scopedProjects(ctx, db, p, scope)
	if err != nil {
		return nil, err
	}
	ids := make([]string, 0, len(projects))
	for _, pr := range projects {
		ids = append(ids, pr[0])
	}
	return ids, nil
}

// filters are the queryset's own filters after the scope: the status (a
// terminal one only when asked for), the person, project, type and
// executor, and the FY.
func (s state) where(f scopeFilter) (string, []any) {
	args := []any{s.fy}
	sql := []string{`a.deleted_at IS NULL`, `a.fy = $1`}
	add := func(clause string, values ...any) {
		for _, v := range values {
			args = append(args, v)
			clause = strings.Replace(clause, "$?", "$"+strconv.Itoa(len(args)), 1)
		}
		sql = append(sql, clause)
	}
	scopeSQL := f.sql
	for _, v := range f.args {
		args = append(args, v)
		scopeSQL = strings.ReplaceAll(scopeSQL, "$R", "$"+strconv.Itoa(len(args)))
	}
	sql = append(sql, scopeSQL)
	if s.status != "" {
		add(`a.status = $?`, s.status)
	} else {
		add(`NOT COALESCE(a.status = ANY($?), false)`, rules.HiddenTerminalStatuses)
	}
	if s.responsible != "" {
		add(`a.responsible_staff_id = $?`, s.responsible)
	}
	if s.project != "" {
		add(`a.project_id = $?`, s.project)
	}
	if valueIn(rules.ActivityTypes, s.activityType) {
		add(`a.activity_type = $?`, s.activityType)
	}
	if valueIn(rules.DeliveryTypes, s.executor) {
		add(`a.delivery_type = $?`, s.executor)
	}
	return strings.Join(sql, " AND "), args
}

// windowSQL is _window_q: work whose service window touches [start, end],
// a legacy row without a planned date read by its scheduled day.
func windowSQL(args []any, start, end time.Time) (string, []any) {
	n := len(args)
	args = append(args, start, end)
	a, b := "$"+strconv.Itoa(n+1), "$"+strconv.Itoa(n+2)
	return `((a.planned_date BETWEEN ` + a + `::date AND ` + b + `::date)
 OR (a.planned_date < ` + a + `::date AND a.end_date >= ` + a + `::date)
 OR (a.planned_date IS NULL AND (a.scheduled_date AT TIME ZONE '` + zoneName + `')::date BETWEEN ` + a + `::date AND ` + b + `::date))`, args
}

const joins = `
LEFT JOIN school s ON s.id = a.school_id
LEFT JOIN district sd ON sd.id = s.district_id
LEFT JOIN cluster c ON c.id = a.cluster_id
LEFT JOIN district cd ON cd.id = c.district_id
LEFT JOIN district ed ON ed.id = a.event_district_id
LEFT JOIN activity_catalogue_item ci ON ci.id = a.catalogue_item_id`

const activitySelect = `SELECT a.id, COALESCE(a.status, ''), a.activity_type, a.delivery_type, a.planning_source,
  a.planned_date, a.end_date, (a.scheduled_date AT TIME ZONE '` + zoneName + `')::date, a.month,
  a.responsible_staff_id, a.monitored_by_staff_id, a.assigned_partner_id, a.project_id,
  a.school_id, a.cluster_id, a.event_district_id, a.catalogue_item_id, ci.display_name, a.activity_name_snapshot,
  a.cost_missing, a.paired_school_visit_id, a.programme_delivery_mode, a.programme_activity_type,
  a.delivery_method_snapshot, a.purpose_type, a.focus_intervention, a.source_score::float8,
  COALESCE(a.ssa_alignment, ''), COALESCE(a.ssa_deviation_reason, ''),
  a.evidence_status, a.ia_verification_status, a.payment_status, a.salesforce_activity_id,
  a.teachers_attended, a.leaders_attended,
  s.name, s.school_id, sd.name, s.cluster_id, s.current_fy_ssa_status,
  c.name, cd.name, ed.name
FROM activity a` + joins

func readActivities(ctx context.Context, db schooldirectory.Querier, where string, args []any) ([]*activity, error) {
	rows, err := db.Query(ctx, activitySelect+` WHERE `+where+` ORDER BY a.planned_date ASC, a.created_at ASC, a.id ASC`, args...)
	if err != nil {
		return nil, fmt.Errorf("workplan: activities: %w", err)
	}
	defer rows.Close()
	out := []*activity{}
	for rows.Next() {
		a := &activity{}
		if err := rows.Scan(&a.id, &a.status, &a.activityType, &a.delivery, &a.planningSource,
			&a.planned, &a.endDate, &a.scheduled, &a.month,
			&a.staffID, &a.monitorID, &a.partnerID, &a.projectID,
			&a.schoolPK, &a.clusterID, &a.eventDistrictID, &a.itemID, &a.itemName, &a.nameSnapshot,
			&a.costMissing, &a.pairedVisit, &a.deliveryMode, &a.programmeType,
			&a.deliveryMethod, &a.purposeType, &a.focus, &a.sourceScore,
			&a.alignment, &a.deviation,
			&a.evidence, &a.iaVerification, &a.payment, &a.salesforce,
			&a.teachersAttended, &a.leadersAttended,
			&a.schoolName, &a.schoolCode, &a.schoolDistrict, &a.schoolCluster, &a.schoolSSA,
			&a.clusterName, &a.clusterDistrict, &a.eventDistrict); err != nil {
			return nil, fmt.Errorf("workplan: activities: %w", err)
		}
		out = append(out, a)
	}
	return out, rows.Err()
}

func countActivities(ctx context.Context, db schooldirectory.Querier, where string, args []any) (int, error) {
	var n int
	err := db.QueryRow(ctx, `SELECT count(*) FROM activity a`+joins+` WHERE `+where, args...).Scan(&n)
	if err != nil {
		return 0, fmt.Errorf("workplan: this month: %w", err)
	}
	return n, nil
}

// costLine is one schedule cost line, with the weekly request status of
// each of its weekly request lines and its advance requests (newest first).
type costLine struct {
	id, label  string
	amount     int64
	planned    *time.Time
	month      *int
	fiscalYear *string
	requests   []string
	advances   []advance
}

type advance struct {
	status           string
	receiptConfirmed bool
	netsuite         *string
}

// readCostLines is the prefetch of schedule_cost_lines and, under each,
// weekly_request_lines__weekly_fund_request and advance_requests: each read
// on its own, in the order the prefetch reads it.
func readCostLines(ctx context.Context, db schooldirectory.Querier, ids []string) (map[string][]*costLine, error) {
	out := map[string][]*costLine{}
	if len(ids) == 0 {
		return out, nil
	}
	rows, err := db.Query(ctx, `SELECT id, activity_id, label, amount, planned_date, month, fiscal_year
FROM activity_schedule_cost_line WHERE activity_id = ANY($1)`, ids)
	if err != nil {
		return nil, fmt.Errorf("workplan: cost lines: %w", err)
	}
	byID := map[string]*costLine{}
	lineIDs := []string{}
	for rows.Next() {
		l := &costLine{}
		var activityID string
		if err := rows.Scan(&l.id, &activityID, &l.label, &l.amount, &l.planned, &l.month, &l.fiscalYear); err != nil {
			rows.Close()
			return nil, fmt.Errorf("workplan: cost lines: %w", err)
		}
		out[activityID] = append(out[activityID], l)
		byID[l.id] = l
		lineIDs = append(lineIDs, l.id)
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, err
	}
	if len(lineIDs) == 0 {
		return out, nil
	}

	type requestLine struct{ line, request string }
	rows, err = db.Query(ctx, `SELECT activity_budget_line_id, weekly_fund_request_id FROM weekly_fund_request_line
WHERE activity_budget_line_id = ANY($1)`, lineIDs)
	if err != nil {
		return nil, fmt.Errorf("workplan: weekly request lines: %w", err)
	}
	requestLines := []requestLine{}
	requestIDs := []string{}
	for rows.Next() {
		var r requestLine
		if err := rows.Scan(&r.line, &r.request); err != nil {
			rows.Close()
			return nil, err
		}
		requestLines = append(requestLines, r)
		if !in(requestIDs, r.request) {
			requestIDs = append(requestIDs, r.request)
		}
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, err
	}
	statuses := map[string]string{}
	if len(requestIDs) > 0 {
		rows, err = db.Query(ctx, `SELECT id, status FROM weekly_fund_request WHERE id = ANY($1)`, requestIDs)
		if err != nil {
			return nil, fmt.Errorf("workplan: weekly requests: %w", err)
		}
		for rows.Next() {
			var id, status string
			if err := rows.Scan(&id, &status); err != nil {
				rows.Close()
				return nil, err
			}
			statuses[id] = status
		}
		rows.Close()
		if err := rows.Err(); err != nil {
			return nil, err
		}
	}
	for _, r := range requestLines {
		status, ok := statuses[r.request]
		if !ok {
			return nil, fmt.Errorf("workplan: weekly request %s of a line is missing", r.request)
		}
		byID[r.line].requests = append(byID[r.line].requests, status)
	}

	rows, err = db.Query(ctx, `SELECT budget_line_id, status, reimbursement_receipt_confirmed_at IS NOT NULL, accountability_netsuite_id
FROM advance_request WHERE budget_line_id = ANY($1) ORDER BY created_at DESC`, lineIDs)
	if err != nil {
		return nil, fmt.Errorf("workplan: advances: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var line string
		var adv advance
		if err := rows.Scan(&line, &adv.status, &adv.receiptConfirmed, &adv.netsuite); err != nil {
			return nil, err
		}
		byID[line].advances = append(byID[line].advances, adv)
	}
	return out, rows.Err()
}

// names are the display-name maps: a person's name and the account a
// message to them goes to, by either id; and for the Country Director the
// Program Lead a row's message goes to instead.
type names struct {
	name, recipient map[string]string
	lead            map[string][2]string
}

func readNames(ctx context.Context, db schooldirectory.Querier, ids []string, cd bool) (names, error) {
	n := names{name: map[string]string{}, recipient: map[string]string{}, lead: map[string][2]string{}}
	if len(ids) == 0 {
		return n, nil
	}
	type profile struct {
		id                 string
		user, name, active *string
	}
	rows, err := db.Query(ctx, `SELECT sp.id, sp.user_id, u.name, u.active_role FROM staff_profile sp
LEFT JOIN "user" u ON u.id = sp.user_id
WHERE sp.deleted_at IS NULL AND (sp.id = ANY($1) OR sp.user_id = ANY($1))`, ids)
	if err != nil {
		return n, fmt.Errorf("workplan: staff names: %w", err)
	}
	profiles, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (profile, error) {
		var p profile
		err := row.Scan(&p.id, &p.user, &p.name, &p.active)
		return p, err
	})
	if err != nil {
		return n, fmt.Errorf("workplan: staff names: %w", err)
	}
	for _, p := range profiles {
		display := ""
		if isSet(p.user) {
			display = str(p.name)
		}
		if display == "" {
			continue
		}
		n.name[p.id] = display
		n.recipient[p.id] = *p.user
		n.recipient[*p.user] = *p.user
		n.name[*p.user] = display
	}
	unresolved := []string{}
	for _, id := range ids {
		if _, ok := n.name[id]; !ok {
			unresolved = append(unresolved, id)
		}
	}
	if len(unresolved) > 0 {
		rows, err := db.Query(ctx, `SELECT id, name FROM "user" WHERE id = ANY($1)`, unresolved)
		if err != nil {
			return n, fmt.Errorf("workplan: user names: %w", err)
		}
		for rows.Next() {
			var id string
			var name *string
			if err := rows.Scan(&id, &name); err != nil {
				rows.Close()
				return n, err
			}
			n.name[id] = str(name)
			if n.name[id] == "" {
				n.name[id] = "Staff"
			}
			n.recipient[id] = id
		}
		rows.Close()
		if err := rows.Err(); err != nil {
			return n, err
		}
	}
	if !cd {
		return n, nil
	}
	byProfile := map[string]profile{}
	leads := map[string][2]string{}
	for _, p := range profiles {
		byProfile[p.id] = p
		if isSet(p.user) && str(p.active) == roleProgramLead {
			leads[p.id] = [2]string{*p.user, str(p.name)}
		}
	}
	others := []string{}
	for id := range byProfile {
		if _, ok := leads[id]; !ok {
			others = append(others, id)
		}
	}
	if len(others) > 0 {
		rows, err := db.Query(ctx, `SELECT a.supervisee_id, sv.user_id, u.name FROM staff_supervisor_assignment a
JOIN staff_profile sv ON sv.id = a.supervisor_id
JOIN "user" u ON u.id = sv.user_id
WHERE a.supervisee_id = ANY($1) AND u.active_role = $2 AND u.is_active
ORDER BY a.supervisee_id ASC, a.id ASC`, others, roleProgramLead)
		if err != nil {
			return n, fmt.Errorf("workplan: leads: %w", err)
		}
		for rows.Next() {
			var supervisee, user, name string
			if err := rows.Scan(&supervisee, &user, &name); err != nil {
				rows.Close()
				return n, err
			}
			if _, ok := leads[supervisee]; !ok {
				leads[supervisee] = [2]string{user, name}
			}
		}
		rows.Close()
		if err := rows.Err(); err != nil {
			return n, err
		}
	}
	for id, lead := range leads {
		n.lead[id] = lead
		n.lead[str(byProfile[id].user)] = lead
	}
	delete(n.lead, "")
	return n, nil
}

// namesOf is `SELECT id, name FROM <table>` over live rows of ids.
func namesOf(ctx context.Context, db schooldirectory.Querier, table string, ids []string) (map[string]string, error) {
	out := map[string]string{}
	if len(ids) == 0 {
		return out, nil
	}
	rows, err := db.Query(ctx, `SELECT id, name FROM `+table+` WHERE deleted_at IS NULL AND id = ANY($1)`, ids)
	if err != nil {
		return nil, fmt.Errorf("workplan: %s names: %w", table, err)
	}
	defer rows.Close()
	for rows.Next() {
		var id, name string
		if err := rows.Scan(&id, &name); err != nil {
			return nil, err
		}
		out[id] = name
	}
	return out, rows.Err()
}

// nextOpenFY is fy_policy.next_open_fy at noon of today: the nearest
// future year whose planning has opened.
func nextOpenFY(ctx context.Context, db schooldirectory.Querier, today time.Time, zone *time.Location) (string, error) {
	at := time.Date(today.Year(), today.Month(), today.Day(), 12, 0, 0, 0, zone)
	rows, err := db.Query(ctx, `SELECT fy FROM fiscal_year_planning_policy WHERE country = $1 AND planning_open_at <= $2 ORDER BY fy`,
		rules.PlanningCountry, at)
	if err != nil {
		return "", fmt.Errorf("workplan: planning policy: %w", err)
	}
	years, err := pgx.CollectRows(rows, pgx.RowTo[string])
	if err != nil {
		return "", fmt.Errorf("workplan: planning policy: %w", err)
	}
	operational, _ := strconv.Atoi(operationalFY(today))
	for _, fy := range years {
		if n, err := strconv.Atoi(fy); err == nil && n > operational {
			return fy, nil
		} else if err != nil {
			return "", fmt.Errorf("workplan: planning policy year %q: %w", fy, err)
		}
	}
	return "", nil
}

// approval is approval_context: the year's country budget envelope and
// what keeps the plan from being submitted.
type approval struct {
	status, label, note  string
	issues               []string
	canSubmit, canDecide bool
}

func readApproval(ctx context.Context, db schooldirectory.Querier, role, fy string) (approval, error) {
	out := approval{status: "draft"}
	var status, note *string
	err := db.QueryRow(ctx, `SELECT status, rvp_review_note FROM country_annual_budget WHERE fy = $1 AND country_id = $2
ORDER BY id LIMIT 1`, fy, rules.Approval.Country).Scan(&status, &note)
	switch {
	case err == pgx.ErrNoRows:
	case err != nil:
		return out, fmt.Errorf("workplan: approval: %w", err)
	default:
		out.status, out.note = str(status), str(note)
	}
	out.label = "Draft"
	for _, pair := range rules.Approval.Statuses {
		if pair[0] == out.status {
			out.label = pair[1]
		}
	}
	excluded := `a.deleted_at IS NULL AND a.fy = $1 AND NOT COALESCE(a.status = ANY($2), false)`
	var any_, undated, unassigned, missing bool
	err = db.QueryRow(ctx, `SELECT
  EXISTS (SELECT 1 FROM activity a WHERE `+excluded+`),
  EXISTS (SELECT 1 FROM activity a WHERE `+excluded+` AND a.planned_date IS NULL AND a.scheduled_date IS NULL),
  EXISTS (SELECT 1 FROM activity a WHERE `+excluded+` AND (
    (a.delivery_type = 'staff' AND (a.responsible_staff_id IS NULL OR a.responsible_staff_id = ''))
    OR (a.delivery_type = 'partner' AND (a.assigned_partner_id IS NULL OR a.assigned_partner_id = '')))),
  EXISTS (SELECT 1 FROM activity a WHERE `+excluded+` AND a.cost_missing)`, fy, rules.Approval.ExcludedStatuses).
		Scan(&any_, &undated, &unassigned, &missing)
	if err != nil {
		return out, fmt.Errorf("workplan: readiness: %w", err)
	}
	issues := rules.Approval.Issues
	if !any_ {
		out.issues = []string{issues["no_activity"]}
	} else {
		if undated {
			out.issues = append(out.issues, issues["undated"])
		}
		if unassigned {
			out.issues = append(out.issues, issues["unassigned"])
		}
		if missing {
			out.issues = append(out.issues, issues["cost_missing"])
		}
	}
	out.canSubmit = (role == roleCountryDirector || role == roleAdmin) &&
		(out.status == "draft" || out.status == "returned_by_rvp")
	out.canDecide = (role == roleRVP || role == roleAdmin) && out.status == "submitted_to_rvp"
	return out, nil
}
