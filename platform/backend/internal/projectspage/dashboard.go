package projectspage

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"math"
	"sort"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// errUnpriced is work the existing page cannot tally (a delivered activity
// whose delivery is neither staff nor partner raises there): passed on.
var errUnpriced = errors.New("projectspage: a delivery the page does not tally")

type project struct {
	id, name, code, category, managerStaff string
	intervention                           *string
	targets                                []string
	ceiling                                int64
}

// targetList is Project.target_intervention_list.
func (p project) targetList() []string {
	out := append([]string{}, p.targets...)
	if p.intervention != nil && *p.intervention != "" && !in(out, *p.intervention) {
		out = append(out, *p.intervention)
	}
	return out
}

type assignment struct {
	projectID            string
	start                *time.Time
	schoolID, code, name string
	district, region     *string
	deleted              bool
	ssa, readiness       string
}

type act struct {
	id, projectID, status, activityType, delivery, evidence, ia, partner, focus string
	school                                                                      *string
	teachers, leaders                                                           *int
	scheduled                                                                   *time.Time
}

type line struct {
	projectID, activityType, payment string
	amount                           int64
}

// dashboard is what get_dashboard computes that the page draws.
type dashboard struct {
	fy, kind, status string
	projects         []project
	assignments      []assignment
	acts             []act
	lines            []line
	partnerLinks     [][2]string // project, partner id, in the links' order
	partnerNames     map[string]string
	live             map[string]liveSchool
	coordinator      string
}

// liveSchool is a school the default manager returns (not deleted).
type liveSchool struct {
	enrollment *int
	ssa        string
}

func dbErr(what string, err error) error {
	return fmt.Errorf("projectspage: reading %s: %w", what, err)
}

// read is get_dashboard's queries for the reader in scope.
func read(ctx context.Context, q schooldirectory.Querier, scope schooldirectory.Scope, f filters) (*dashboard, error) {
	d := &dashboard{fy: f.fy, kind: f.kind, status: f.status, partnerNames: map[string]string{}, live: map[string]liveSchool{}}
	sql := `SELECT p.id, p.name, COALESCE(p.code, ''), COALESCE(p.category, ''), COALESCE(p.manager_staff_id, ''),
	               p.intervention, COALESCE(p.target_interventions, '[]'::jsonb), COALESCE(p.budget_ceiling_ugx, 0)
	        FROM project p WHERE p.deleted_at IS NULL`
	args := []any{}
	if !scope.CountryScope {
		if scope.StaffID == "" {
			return d, nil
		}
		args = append(args, scope.StaffID)
		sql += ` AND (p.manager_staff_id = $1 OR EXISTS (SELECT 1 FROM project_staff_assignment s
		         WHERE s.project_id = p.id AND s.staff_id = $1 AND s.is_active))`
	}
	if f.kind != "" {
		args = append(args, f.kind)
		sql += fmt.Sprintf(` AND p.category = $%d`, len(args))
	}
	rows, err := q.Query(ctx, sql+` ORDER BY p.name`, args...)
	if err != nil {
		return nil, dbErr("the projects", err)
	}
	d.projects, err = pgx.CollectRows(rows, func(row pgx.CollectableRow) (project, error) {
		var p project
		var targets []byte
		if err := row.Scan(&p.id, &p.name, &p.code, &p.category, &p.managerStaff, &p.intervention, &targets, &p.ceiling); err != nil {
			return p, err
		}
		var raw []any
		if err := json.Unmarshal(targets, &raw); err == nil {
			for _, t := range raw {
				if s, ok := t.(string); ok {
					p.targets = append(p.targets, s)
				}
			}
		}
		return p, nil
	})
	if err != nil {
		return nil, dbErr("the projects", err)
	}
	ids := d.projectIDs()
	if len(ids) == 0 {
		return d, nil
	}
	if err := d.readAssignments(ctx, q, ids); err != nil {
		return nil, err
	}
	if err := d.readActs(ctx, q, ids); err != nil {
		return nil, err
	}
	if err := d.readLines(ctx, q, ids); err != nil {
		return nil, err
	}
	if err := d.readPartners(ctx, q, ids); err != nil {
		return nil, err
	}
	return d, d.readLiveSchools(ctx, q)
}

func (d *dashboard) projectIDs() []string {
	out := make([]string, 0, len(d.projects))
	for _, p := range d.projects {
		out = append(out, p.id)
	}
	return out
}

// readAssignments is the project-school rows with their school, as Django
// joins them (no order: the rows come as the database returns that join).
func (d *dashboard) readAssignments(ctx context.Context, q schooldirectory.Querier, ids []string) error {
	rows, err := q.Query(ctx, `
		SELECT psa.project_id, psa.start_date, school.id, COALESCE(school.school_id, ''), COALESCE(school.name, ''),
		       district.name, region.name, school.deleted_at IS NOT NULL,
		       COALESCE(school.current_fy_ssa_status, ''), COALESCE(school.planning_readiness, '')
		FROM project_school_assignment psa INNER JOIN school ON (psa.school_id = school.id)
		LEFT OUTER JOIN region ON (school.region_id = region.id)
		LEFT OUTER JOIN district ON (school.district_id = district.id)
		WHERE psa.project_id = ANY($1)`, ids)
	if err != nil {
		return dbErr("the project schools", err)
	}
	d.assignments, err = pgx.CollectRows(rows, func(row pgx.CollectableRow) (assignment, error) {
		var a assignment
		return a, row.Scan(&a.projectID, &a.start, &a.schoolID, &a.code, &a.name, &a.district, &a.region, &a.deleted, &a.ssa, &a.readiness)
	})
	if err != nil {
		return dbErr("the project schools", err)
	}
	return nil
}

// readActs is the projects' live work in the year, newest first
// (Activity's default ordering).
func (d *dashboard) readActs(ctx context.Context, q schooldirectory.Querier, ids []string) error {
	rows, err := q.Query(ctx, `
		SELECT id, project_id, COALESCE(status, ''), COALESCE(activity_type, ''), COALESCE(delivery_type, ''),
		       COALESCE(evidence_status, ''), COALESCE(ia_verification_status, ''), COALESCE(assigned_partner_id, ''),
		       COALESCE(focus_intervention, ''), school_id, teachers_attended, leaders_attended, scheduled_date
		FROM activity
		WHERE deleted_at IS NULL AND project_id = ANY($1) AND (fy = $2 OR fiscal_year = $2)
		ORDER BY created_at DESC`, ids, d.fy)
	if err != nil {
		return dbErr("the project work", err)
	}
	d.acts, err = pgx.CollectRows(rows, func(row pgx.CollectableRow) (act, error) {
		var a act
		return a, row.Scan(&a.id, &a.projectID, &a.status, &a.activityType, &a.delivery, &a.evidence, &a.ia,
			&a.partner, &a.focus, &a.school, &a.teachers, &a.leaders, &a.scheduled)
	})
	if err != nil {
		return dbErr("the project work", err)
	}
	return nil
}

// readLines is the cost lines of the projects' work in the year (any
// activity, deleted or not: the lines are asked through the activity).
func (d *dashboard) readLines(ctx context.Context, q schooldirectory.Querier, ids []string) error {
	rows, err := q.Query(ctx, `
		SELECT a.project_id, COALESCE(a.activity_type, ''), COALESCE(a.payment_status, ''), COALESCE(l.amount, 0)
		FROM activity_schedule_cost_line l INNER JOIN activity a ON (l.activity_id = a.id)
		WHERE a.project_id = ANY($1) AND a.fy = $2`, ids, d.fy)
	if err != nil {
		return dbErr("the project costs", err)
	}
	d.lines, err = pgx.CollectRows(rows, func(row pgx.CollectableRow) (line, error) {
		var l line
		return l, row.Scan(&l.projectID, &l.activityType, &l.payment, &l.amount)
	})
	if err != nil {
		return dbErr("the project costs", err)
	}
	return nil
}

// readPartners is the project-partner links with their partner, as Django
// joins them.
func (d *dashboard) readPartners(ctx context.Context, q schooldirectory.Querier, ids []string) error {
	rows, err := q.Query(ctx, `
		SELECT ppa.project_id, ppa.partner_id, COALESCE(partner.name, '')
		FROM project_partner_assignment ppa INNER JOIN partner ON (ppa.partner_id = partner.id)
		WHERE ppa.project_id = ANY($1)`, ids)
	if err != nil {
		return dbErr("the project partners", err)
	}
	defer rows.Close()
	for rows.Next() {
		var project, partner, name string
		if err := rows.Scan(&project, &partner, &name); err != nil {
			return dbErr("the project partners", err)
		}
		d.partnerLinks = append(d.partnerLinks, [2]string{project, partner})
		d.partnerNames[partner] = name
	}
	return rows.Err()
}

// readLiveSchools is what School.objects (not deleted) holds of the schools
// the figures read: the delivered work's schools and the project schools.
func (d *dashboard) readLiveSchools(ctx context.Context, q schooldirectory.Querier) error {
	ids := []string{}
	for _, a := range d.acts {
		if a.school != nil {
			ids = append(ids, *a.school)
		}
	}
	for _, a := range d.assignments {
		ids = append(ids, a.schoolID)
	}
	rows, err := q.Query(ctx, `SELECT id, enrollment, COALESCE(current_fy_ssa_status, '') FROM school
		WHERE id = ANY($1) AND deleted_at IS NULL`, ids)
	if err != nil {
		return dbErr("the schools", err)
	}
	defer rows.Close()
	for rows.Next() {
		var id string
		var s liveSchool
		if err := rows.Scan(&id, &s.enrollment, &s.ssa); err != nil {
			return dbErr("the schools", err)
		}
		d.live[id] = s
	}
	return rows.Err()
}

// coordinatorName is _coordinator_name: the account's name behind the
// (live) staff profile, "Assigned" when it has none, "Unassigned" without
// a profile id.
func coordinatorName(ctx context.Context, q schooldirectory.Querier, staffID string) (string, error) {
	if staffID == "" {
		return "Unassigned", nil
	}
	var name *string
	err := q.QueryRow(ctx, `SELECT u.name FROM staff_profile sp LEFT JOIN "user" u ON u.id = sp.user_id
		WHERE sp.id = $1 AND sp.deleted_at IS NULL`, staffID).Scan(&name)
	switch {
	case errors.Is(err, pgx.ErrNoRows):
		return "Assigned", nil
	case err != nil:
		return "", dbErr("the coordinator", err)
	case name == nil || *name == "":
		return "Assigned", nil
	}
	return *name, nil
}

// ── The figures ─────────────────────────────────────────────────────────────

var gone = []string{"closed", "cancelled", "rejected"}

func (a act) delivered() bool { return in(rules.DeliveredStatuses, a.status) }
func (a act) inPlan() bool    { return !in(rules.NotInPlanStatuses, a.status) }
func (a act) training() bool  { return in(rules.TrainingTypes, a.activityType) }
func (a act) closedOut() bool { return a.status != "" && in(gone, a.status) }
func (a act) evidenceDue() bool {
	return (a.status == "in_progress" || a.status == "completion_started" ||
		a.evidence == "uploaded" || a.evidence == "returned") && !a.closedOut()
}
func (a act) iaDue() bool {
	return (a.status == "awaiting_ia_verification" || a.status == "returned_by_ia" || a.ia == "flagged") && !a.closedOut()
}

// pyRound is Python's round() of a float to an int (half to even).
func pyRound(v float64) int { return int(math.RoundToEven(v)) }

func percent(part, whole int64) int {
	if whole == 0 {
		return 0
	}
	return pyRound(float64(part) / float64(whole) * 100)
}

// statusBand is _status_band: the label and its tone.
func statusBand(completion, total int) (string, string) {
	switch {
	case total == 0:
		return "Planning", "neutral"
	case completion >= 60:
		return "On Track", "success"
	case completion >= 30:
		return "At Risk", "warning"
	}
	return "Behind", "danger"
}

type counts struct{ total, closed int }

func (d *dashboard) countsBy() map[string]counts {
	out := map[string]counts{}
	for _, a := range d.acts {
		c := out[a.projectID]
		c.total++
		if a.status == "closed" {
			c.closed++
		}
		out[a.projectID] = c
	}
	return out
}

func (d *dashboard) budgetBy() map[string]int64 {
	out := map[string]int64{}
	for _, l := range d.lines {
		out[l.projectID] += l.amount
	}
	return out
}

func (d *dashboard) budget() int64 {
	var n int64
	for _, l := range d.lines {
		n += l.amount
	}
	return n
}

// upcoming is each project's next scheduled follow-up: the first of the
// work still to come (at most 200), by its time.
func (d *dashboard) upcoming(now time.Time) map[string]time.Time {
	type due struct {
		project string
		at      time.Time
	}
	list := []due{}
	statuses := append(append([]string{}, rules.NotInPlanStatuses...), "in_progress")
	for _, a := range d.acts {
		if a.scheduled == nil || a.scheduled.Before(now) || !in(statuses, a.status) || a.closedOut() {
			continue
		}
		list = append(list, due{a.projectID, *a.scheduled})
	}
	sort.SliceStable(list, func(i, j int) bool { return list[i].at.Before(list[j].at) })
	if len(list) > 200 {
		list = list[:200]
	}
	out := map[string]time.Time{}
	for _, u := range list {
		if _, ok := out[u.project]; !ok {
			out[u.project] = u.at
		}
	}
	return out
}

// interventionLabel is the focus label, or the code read as words.
func interventionLabel(code string) string {
	if l, ok := label(rules.Interventions, code); ok {
		return l
	}
	return pyTitle(strings.ReplaceAll(code, "_", " "))
}

// pyTitle is Python's str.title().
func pyTitle(s string) string {
	out := []rune(strings.ToLower(s))
	start := true
	for i, r := range out {
		letter := r >= 'a' && r <= 'z'
		if letter && start {
			out[i] = r - 'a' + 'A'
		}
		start = !letter
	}
	return string(out)
}

type bar struct {
	label          string
	staff, partner int
}

// impactBars is the delivered work by its focus, staff and partner, the
// six largest (ties in the order the work was read).
func (d *dashboard) impactBars() ([]bar, error) {
	order := []string{}
	byFocus := map[string]*bar{}
	for _, a := range d.acts {
		if !a.delivered() {
			continue
		}
		fi := a.focus
		if fi == "" {
			fi = "unspecified"
		}
		b, ok := byFocus[fi]
		if !ok {
			b = &bar{label: interventionLabel(fi)}
			byFocus[fi] = b
			order = append(order, fi)
		}
		switch a.delivery {
		case "", "staff":
			b.staff++
		case "partner":
			b.partner++
		default:
			return nil, errUnpriced
		}
	}
	out := make([]bar, 0, len(order))
	for _, fi := range order {
		out = append(out, *byFocus[fi])
	}
	sort.SliceStable(out, func(i, j int) bool { return out[i].staff+out[i].partner > out[j].staff+out[j].partner })
	if len(out) > 6 {
		out = out[:6]
	}
	return out, nil
}
