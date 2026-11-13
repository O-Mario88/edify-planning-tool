package trainingsummary

import (
	"context"
	"fmt"
	"slices"
	"strconv"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// The routes and statuses of apps.planning.training_coverage.
const (
	routeStaff   = "staff"
	routePartner = "partner"
	routeGroup   = "group"

	notCovered       = "not_covered"
	staffPlanned     = "staff_planned"
	partnerAssigned  = "partner_assigned"
	partnerScheduled = "partner_scheduled"
	groupScheduled   = "group_scheduled"
	inProgress       = "in_progress"
	completed        = "completed"

	showRemaining = "remaining"
)

// coverageRow is training_coverage.Commitment as the table draws it.
type coverageRow struct {
	schoolPK, schoolName     string
	trainingID, trainingName string
	staffID, staffName       string
	route, status            string
	responsible, partner     string
	cluster                  string
	date                     *time.Time
	activityID, assignmentID string
	dated, repeat            bool
}

func (r coverageRow) scheduled() bool { return r.status != notCovered && r.status != partnerAssigned }

// nextAction is Commitment.next_action.
func (r coverageRow) nextAction() string {
	switch {
	case r.status == notCovered:
		return "Plan"
	case r.status == partnerAssigned:
		return "Partner to schedule"
	case r.status == completed:
		return "None"
	case r.route == routePartner && r.status == inProgress:
		return "Partner to complete"
	case r.route == routePartner:
		return "Partner to conduct"
	case r.status == inProgress:
		return "Complete and submit"
	}
	return "Conduct"
}

// statusOf is training_coverage._status_of.
func statusOf(route, activityStatus string, dated bool) string {
	switch {
	case in(rules.Coverage.CompletedStatuses, activityStatus):
		return completed
	case in(rules.Coverage.UnderWayStatuses, activityStatus):
		return inProgress
	case route == routeGroup:
		return groupScheduled
	case route == routePartner && dated:
		return partnerScheduled
	case route == routePartner:
		return partnerAssigned
	}
	return staffPlanned
}

// identities is training_coverage._by_identity: {identity: profile id}
// and {profile id: name}, with every identity in the order first met.
func identities(staff []profile) (map[string]string, map[string]string, []string) {
	byIdentity, names, ids := map[string]string{}, map[string]string{}, []string{}
	for _, p := range staff {
		names[p.id] = p.display()
		for _, identity := range []string{p.id, p.userID} {
			if identity == "" {
				continue
			}
			if _, seen := byIdentity[identity]; !seen {
				ids = append(ids, identity)
			}
			byIdentity[identity] = p.id
		}
	}
	return byIdentity, names, ids
}

// courseFilter narrows a statement to one course (course_id=...), as its
// next parameter.
func courseFilter(course, training string, args []any) (string, []any) {
	if training == "" {
		return "", args
	}
	args = append(args, training)
	return " AND " + course + " = $" + strconv.Itoa(len(args)), args
}

type rawCommitment struct {
	id, school, schoolName, course, owner, cluster, status, partner string
	date                                                            *time.Time
	dated                                                           bool
}

func scanCommitments(ctx context.Context, q schooldirectory.Querier, sql string, args []any,
	scan func(row pgx.CollectableRow, c *rawCommitment) error) ([]rawCommitment, error) {
	rows, err := q.Query(ctx, sql, args...)
	if err != nil {
		return nil, err
	}
	return pgx.CollectRows(rows, func(row pgx.CollectableRow) (rawCommitment, error) {
		var c rawCommitment
		return c, scan(row, &c)
	})
}

func str(p *string) string {
	if p == nil {
		return ""
	}
	return *p
}

// coverageGroup is _group_rows(...).values(...) as training_coverage.commitments reads it.
func coverageGroup(ctx context.Context, q schooldirectory.Querier, owners []string, fy, training string) ([]rawCommitment, error) {
	course := courseSQL("a")
	filter, args := courseFilter(course, training, append(baseArgs(fy), owners))
	sql := `SELECT att.school_id, s.name, ` + course + `, att.activity_id, a.responsible_staff_id, c.name, a.planned_date, a.status
FROM cluster_activity_attendance att
JOIN activity a ON att.activity_id = a.id
JOIN cluster c ON a.cluster_id = c.id
LEFT JOIN activity_catalogue_item ci ON a.catalogue_item_id = ci.id
JOIN school s ON att.school_id = s.id
WHERE ` + trainingSQL + ` AND (att.invited OR att.attended) AND a.cluster_id IS NOT NULL AND a.school_id IS NULL
  AND ` + notProjectSQL(course) + ` AND a.responsible_staff_id = ANY($8)` + filter + `
ORDER BY 2 ASC`
	out, err := scanCommitments(ctx, q, sql, args, func(row pgx.CollectableRow, c *rawCommitment) error {
		var name, owner, cluster *string
		err := row.Scan(&c.school, &name, &c.course, &c.id, &owner, &cluster, &c.date, &c.status)
		c.schoolName, c.owner, c.cluster = str(name), str(owner), str(cluster)
		return err
	})
	if err != nil {
		return nil, fmt.Errorf("trainingsummary: reading group trainings' schools: %w", err)
	}
	return out, nil
}

// coverageInSchool is _in_school_rows(...).values(...).
func coverageInSchool(ctx context.Context, q schooldirectory.Querier, owners []string, fy, training string) ([]rawCommitment, error) {
	course := courseSQL("a")
	filter, args := courseFilter(course, training, append(baseArgs(fy), owners, rules.PartnerDeliveryType))
	sql := `SELECT a.id, a.school_id, s.name, ` + course + `, a.responsible_staff_id, a.planned_date, a.status
FROM activity a
JOIN school s ON a.school_id = s.id
LEFT JOIN activity_catalogue_item ci ON a.catalogue_item_id = ci.id
WHERE ` + trainingSQL + ` AND a.school_id IS NOT NULL
  AND ` + notProjectSQL(course) + filter + ` AND NOT (a.delivery_type = $9) AND a.responsible_staff_id = ANY($8)
ORDER BY a.created_at DESC`
	out, err := scanCommitments(ctx, q, sql, args, func(row pgx.CollectableRow, c *rawCommitment) error {
		var name, owner *string
		err := row.Scan(&c.id, &c.school, &name, &c.course, &owner, &c.date, &c.status)
		c.schoolName, c.owner = str(name), str(owner)
		return err
	})
	if err != nil {
		return nil, fmt.Errorf("trainingsummary: reading in-school trainings' schools: %w", err)
	}
	return out, nil
}

// coveragePartner is _partner_rows(...).values(...).
func coveragePartner(ctx context.Context, q schooldirectory.Querier, owners []string, fy, training string) ([]rawCommitment, error) {
	course := courseSQL("a")
	owner := `COALESCE(NULLIF(a.monitored_by_staff_id, ''), NULLIF(a.responsible_staff_id, ''), s.account_owner_id)`
	planned := `a.status = ANY($11) AND (a.planned_date IS NOT NULL OR a.scheduled_date IS NOT NULL)`
	dated := `CASE WHEN ((a.delivery_type = $9 AND ` + planned + ` AND (a.partner_date_set_by = $12 OR (a.partner_date_set_by = '' AND NOT (a.executor_type = $13))))
  OR (` + planned + ` AND a.executor_type = $13)) THEN 1 ELSE 0 END`
	filter, args := courseFilter(course, training, append(baseArgs(fy), owners, rules.PartnerDeliveryType,
		rules.UnscheduledHandoverStatuses, rules.PlannedStates, rules.DatedByPartner, rules.CertifiedPartnerAgency))
	sql := `SELECT a.id, a.school_id, s.name, ` + course + `, ` + owner + `, ` + dated + `, a.assigned_partner_id, a.planned_date, a.status
FROM activity a
JOIN school s ON a.school_id = s.id
LEFT JOIN activity_catalogue_item ci ON a.catalogue_item_id = ci.id
WHERE ` + trainingSQL + ` AND a.school_id IS NOT NULL
  AND ` + notProjectSQL(course) + filter + ` AND a.delivery_type = $9
  AND NOT (a.id IN (SELECT h.source_activity_id FROM partner_assignment h WHERE h.status = ANY($10) AND h.source_activity_id IS NOT NULL))
  AND ` + owner + ` = ANY($8)
ORDER BY a.created_at DESC`
	out, err := scanCommitments(ctx, q, sql, args, func(row pgx.CollectableRow, c *rawCommitment) error {
		var name, who, partner *string
		var dated int
		err := row.Scan(&c.id, &c.school, &name, &c.course, &who, &dated, &partner, &c.date, &c.status)
		c.schoolName, c.owner, c.partner, c.dated = str(name), str(who), str(partner), dated == 1
		return err
	})
	if err != nil {
		return nil, fmt.Errorf("trainingsummary: reading partner trainings' schools: %w", err)
	}
	return out, nil
}

// coverageHandovers is _handover_rows(...).values(...).
func coverageHandovers(ctx context.Context, q schooldirectory.Querier, owners []string, fy, training string, now time.Time) ([]rawCommitment, error) {
	if !handoversReadIn(fy, now) {
		return nil, nil
	}
	course := courseSQL("pa")
	owner := `COALESCE(NULLIF(pa.monitoring_staff_id, ''), NULLIF(pa.assigning_staff_id, ''), s.account_owner_id)`
	filter, args := courseFilter(course, training, []any{rules.CatalogueTrainingType, rules.LiveProjectStatuses,
		rules.UnscheduledHandoverStatuses, owners})
	sql := `SELECT pa.id, pa.school_id, s.name, ` + course + `, ` + owner + `, pa.partner_id
FROM partner_assignment pa
JOIN school s ON pa.school_id = s.id
LEFT JOIN activity_catalogue_item ci ON pa.catalogue_item_id = ci.id
WHERE pa.status = ANY($3) AND pa.project_id IS NULL AND pa.school_id IS NOT NULL
  AND ` + notProjectSQL(course) + ` AND ` + owner + ` = ANY($4)` + filter + `
ORDER BY pa.created_at DESC`
	out, err := scanCommitments(ctx, q, sql, args, func(row pgx.CollectableRow, c *rawCommitment) error {
		var name, who, partner *string
		err := row.Scan(&c.id, &c.school, &name, &c.course, &who, &partner)
		c.schoolName, c.owner, c.partner = str(name), str(who), str(partner)
		return err
	})
	if err != nil {
		return nil, fmt.Errorf("trainingsummary: reading partner hand-overs' schools: %w", err)
	}
	return out, nil
}

// partnerNames is Partner.all_objects' names.
func partnerNames(ctx context.Context, q schooldirectory.Querier, ids []string) (map[string]string, error) {
	out := map[string]string{}
	if len(ids) == 0 {
		return out, nil
	}
	rows, err := q.Query(ctx, `SELECT id, name FROM partner WHERE id = ANY($1)`, ids)
	if err != nil {
		return nil, fmt.Errorf("trainingsummary: reading partners: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var id string
		var name *string
		if err := rows.Scan(&id, &name); err != nil {
			return nil, fmt.Errorf("trainingsummary: reading partners: %w", err)
		}
		out[id] = str(name)
	}
	return out, rows.Err()
}

// coverageCommitments is training_coverage.commitments: every school these
// staff have committed to a training in the year, one row per school and
// session, in the table's order.
func coverageCommitments(ctx context.Context, q schooldirectory.Querier, staff []profile, fy, training string, now time.Time) ([]coverageRow, error) {
	byIdentity, names, owners := identities(staff)
	if len(byIdentity) == 0 {
		return nil, nil
	}
	out := []coverageRow{}
	add := func(owner string, r coverageRow) {
		staffID, ok := byIdentity[owner]
		if !ok {
			return
		}
		r.staffID, r.staffName = staffID, names[staffID]
		out = append(out, r)
	}
	group, err := coverageGroup(ctx, q, owners, fy, training)
	if err != nil {
		return nil, err
	}
	for _, c := range group {
		add(c.owner, coverageRow{schoolPK: c.school, schoolName: c.schoolName, trainingID: c.course, route: routeGroup,
			status: statusOf(routeGroup, c.status, true), responsible: names[byIdentity[c.owner]], cluster: c.cluster,
			date: c.date, activityID: c.id, dated: true})
	}
	inSchool, err := coverageInSchool(ctx, q, owners, fy, training)
	if err != nil {
		return nil, err
	}
	for _, c := range inSchool {
		add(c.owner, coverageRow{schoolPK: c.school, schoolName: c.schoolName, trainingID: c.course, route: routeStaff,
			status: statusOf(routeStaff, c.status, true), responsible: names[byIdentity[c.owner]],
			date: c.date, activityID: c.id, dated: true})
	}
	partnerIDs := []string{}
	partner, err := coveragePartner(ctx, q, owners, fy, training)
	if err != nil {
		return nil, err
	}
	for _, c := range partner {
		partnerIDs = append(partnerIDs, c.partner)
		r := coverageRow{schoolPK: c.school, schoolName: c.schoolName, trainingID: c.course, route: routePartner,
			status: statusOf(routePartner, c.status, c.dated), partner: c.partner, activityID: c.id, dated: c.dated}
		if c.dated {
			r.date = c.date
		}
		add(c.owner, r)
	}
	handovers, err := coverageHandovers(ctx, q, owners, fy, training, now)
	if err != nil {
		return nil, err
	}
	for _, c := range handovers {
		partnerIDs = append(partnerIDs, c.partner)
		add(c.owner, coverageRow{schoolPK: c.school, schoolName: c.schoolName, trainingID: c.course, route: routePartner,
			status: partnerAssigned, partner: c.partner, assignmentID: c.id})
	}
	partners, err := partnerNames(ctx, q, slices.DeleteFunc(partnerIDs, func(id string) bool { return id == "" }))
	if err != nil {
		return nil, err
	}
	courses := []string{}
	for _, r := range out {
		courses = append(courses, r.trainingID)
	}
	items, err := catalogueItems(ctx, q, courses)
	if err != nil {
		return nil, err
	}
	trainingNames := map[string]string{}
	for _, it := range items {
		trainingNames[it.id] = it.name
	}
	for i := range out {
		out[i].trainingName = "Training"
		if name, ok := trainingNames[out[i].trainingID]; ok {
			out[i].trainingName = name
		}
		if out[i].route == routePartner {
			out[i].partner = partners[out[i].partner]
			if out[i].partner == "" {
				out[i].partner = "Partner"
			}
			out[i].responsible = out[i].partner
		}
	}
	return inOrder(out), nil
}

func dateKey(d *time.Time) string {
	if d == nil {
		return "9999"
	}
	return d.Format("2006-01-02")
}

// inOrder is training_coverage._in_order: by school, training, officer, day
// and record, a school's second row for one training and officer marked.
func inOrder(rows []coverageRow) []coverageRow {
	slices.SortStableFunc(rows, func(a, b coverageRow) int {
		for _, pair := range [][2]string{
			{strings.ToLower(a.schoolName), strings.ToLower(b.schoolName)},
			{strings.ToLower(a.trainingName), strings.ToLower(b.trainingName)},
			{strings.ToLower(a.staffName), strings.ToLower(b.staffName)},
			{dateKey(a.date), dateKey(b.date)},
			{a.activityID + a.assignmentID, b.activityID + b.assignmentID},
		} {
			if c := strings.Compare(pair[0], pair[1]); c != 0 {
				return c
			}
		}
		return 0
	})
	return remark(rows)
}

// remark is training_coverage._remark.
func remark(rows []coverageRow) []coverageRow {
	seen := map[[3]string]bool{}
	for i := range rows {
		key := [3]string{rows[i].schoolPK, rows[i].trainingID, rows[i].staffID}
		rows[i].repeat = seen[key]
		seen[key] = true
	}
	return rows
}

// ofFigure is training_coverage._of_figure.
func ofFigure(rows []coverageRow, figure string) []coverageRow {
	keep := func(ok func(coverageRow) bool) []coverageRow {
		out := []coverageRow{}
		for _, r := range rows {
			if ok(r) {
				out = append(out, r)
			}
		}
		return out
	}
	switch figure {
	case "", "covered":
		return rows
	case routeStaff, routeGroup:
		return keep(func(r coverageRow) bool { return r.route == figure })
	case routePartner:
		return keep(func(r coverageRow) bool { return r.route == routePartner })
	case partnerScheduled:
		return keep(func(r coverageRow) bool { return r.route == routePartner && r.dated })
	case "awaiting":
		dated := map[[3]string]bool{}
		for _, r := range rows {
			if r.route == routePartner && r.dated {
				dated[[3]string{r.schoolPK, r.trainingID, r.staffID}] = true
			}
		}
		return keep(func(r coverageRow) bool {
			return r.route == routePartner && !dated[[3]string{r.schoolPK, r.trainingID, r.staffID}]
		})
	}
	return rows
}

// uncovered is training_coverage.uncovered: the schools this person holds
// that take a training and have no commitment to it yet.
func uncovered(ctx context.Context, q schooldirectory.Querier, p profile, training item, covered map[string]bool) ([]coverageRow, error) {
	owners := []string{}
	for _, identity := range []string{p.id, p.userID} {
		if identity != "" {
			owners = append(owners, identity)
		}
	}
	args := []any{rules.Coverage.OperatingStatuses, owners, rules.Coverage.TrainedTypes, rules.Coverage.ExcludedDuplicateStatuses}
	notIn := ""
	if len(covered) > 0 {
		ids := make([]string, 0, len(covered))
		for id := range covered {
			ids = append(ids, id)
		}
		slices.Sort(ids)
		args = append(args, ids)
		notIn = ` AND NOT (s.id = ANY($5))`
	}
	rows, err := q.Query(ctx, `SELECT s.id, s.name FROM school s
WHERE (s.deleted_at IS NULL AND s.deleted_at IS NULL AND s.operational_status = ANY($1) AND s.account_owner_id = ANY($2)
  AND s.school_type = ANY($3) AND NOT (s.duplicate_status = ANY($4))`+notIn+`)
ORDER BY 2 ASC`, args...)
	if err != nil {
		return nil, fmt.Errorf("trainingsummary: reading schools not yet covered: %w", err)
	}
	found, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (coverageRow, error) {
		var r coverageRow
		var name *string
		err := row.Scan(&r.schoolPK, &name)
		r.schoolName = str(name)
		return r, err
	})
	if err != nil {
		return nil, fmt.Errorf("trainingsummary: reading schools not yet covered: %w", err)
	}
	name := p.display()
	for i := range found {
		found[i].trainingID, found[i].trainingName = training.id, training.name
		found[i].staffID, found[i].staffName = p.id, name
		found[i].status, found[i].responsible = notCovered, name
	}
	return found, nil
}

// coverage is training_coverage.table, as the template reads it.
type coverage struct {
	rows          []coverageRow
	show          string
	schoolCount   int
	counts        [][2]string // status label, count
	needsTraining bool
}

func schoolsOf(rows []coverageRow) map[[2]string]bool {
	out := map[[2]string]bool{}
	for _, r := range rows {
		out[[2]string{r.schoolPK, r.trainingID}] = true
	}
	return out
}

// findTraining is ActivityCatalogueItem.objects.filter(id=...).first().
func findTraining(ctx context.Context, q schooldirectory.Querier, id string) (*item, error) {
	if id == "" {
		return nil, nil
	}
	found, err := catalogueItems(ctx, q, []string{id})
	if err != nil || len(found) == 0 {
		return nil, err
	}
	return &found[0], nil
}

// coverageTable is training_coverage.table.
func coverageTable(ctx context.Context, q schooldirectory.Querier, staff []profile, fy, trainingID, staffID, show string, now time.Time) (coverage, error) {
	if staffID != "" {
		staff = slices.DeleteFunc(slices.Clone(staff), func(p profile) bool { return p.id != staffID })
	}
	if !slices.ContainsFunc(rules.Coverage.ShowOptions, func(o [2]string) bool { return o[0] == show }) {
		show = ""
	}
	training, err := findTraining(ctx, q, trainingID)
	if err != nil {
		return coverage{}, err
	}
	course := ""
	if training != nil {
		course = training.id
	}
	rows, err := coverageCommitments(ctx, q, staff, fy, course, now)
	if err != nil {
		return coverage{}, err
	}
	at := map[string]map[[2]string]bool{}
	for _, r := range rows {
		if at[r.status] == nil {
			at[r.status] = map[[2]string]bool{}
		}
		at[r.status][[2]string{r.schoolPK, r.trainingID}] = true
	}
	missing := []coverageRow{}
	if training != nil && (show == "" || show == showRemaining) {
		coveredBy := map[string]map[string]bool{}
		for _, r := range rows {
			if coveredBy[r.staffID] == nil {
				coveredBy[r.staffID] = map[string]bool{}
			}
			coveredBy[r.staffID][r.schoolPK] = true
		}
		for _, p := range staff {
			found, err := uncovered(ctx, q, p, *training, coveredBy[p.id])
			if err != nil {
				return coverage{}, err
			}
			missing = append(missing, found...)
		}
		at[notCovered] = schoolsOf(missing)
	}
	switch {
	case show == showRemaining:
		rows = missing
	case show == inProgress || show == completed:
		rows = slices.DeleteFunc(rows, func(r coverageRow) bool { return r.status != show })
	case show != "":
		rows = ofFigure(rows, show)
	default:
		rows = append(rows, missing...)
	}
	rows = inOrder(rows)
	out := coverage{rows: rows, show: show, schoolCount: len(schoolsOf(rows)), needsTraining: show == showRemaining && training == nil}
	for _, key := range rules.Coverage.StatusOrder {
		if n := len(at[key]); n > 0 {
			out.counts = append(out.counts, [2]string{rules.Coverage.StatusLabels[key], intcomma(n)})
		}
	}
	return out, nil
}

// trainingsCommitted is training_coverage.trainings_committed: the
// trainings these staff have a school committed to, by name.
func trainingsCommitted(ctx context.Context, q schooldirectory.Querier, staff []profile, fy string, now time.Time) ([][2]string, error) {
	rows, err := summaryForStaff(ctx, q, staff, fy, now)
	if err != nil {
		return nil, err
	}
	out := [][2]string{}
	for _, r := range rows {
		if r.total() > 0 && !slices.ContainsFunc(out, func(o [2]string) bool { return o[0] == r.trainingID }) {
			out = append(out, [2]string{r.trainingID, r.trainingName})
		}
	}
	slices.SortStableFunc(out, func(a, b [2]string) int { return strings.Compare(strings.ToLower(a[1]), strings.ToLower(b[1])) })
	return out, nil
}

// coverageProfiles is training_summary.coverage_profiles: the summary's
// columns, or for a reader of the whole country with no team chosen,
// every staff profile of the country (and of none), left staff included.
func coverageProfiles(ctx context.Context, q schooldirectory.Querier, s summary, country string) ([]profile, error) {
	if !s.countryLinks || s.lead != "" {
		return s.staff, nil
	}
	sql := `SELECT ` + profileColumns + ` FROM staff_profile sp JOIN "user" u ON sp.user_id = u.id WHERE sp.deleted_at IS NULL`
	args := []any{}
	if country != "" {
		sql += ` AND (sp.country = $1 OR sp.country = $2)`
		args = append(args, country, "")
	}
	out, err := profiles(ctx, q, sql, args...)
	if err != nil {
		return nil, fmt.Errorf("trainingsummary: reading the country's staff: %w", err)
	}
	return out, nil
}
