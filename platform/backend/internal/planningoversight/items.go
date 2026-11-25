package planningoversight

import (
	"context"
	"fmt"
	"slices"
	"strconv"
	"strings"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schoolprofile"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/visitgate"
)

// Piece 2 (second slice): the team's own work in the period, built as
// oversight_service.build_items builds it for a "pl" scope (one activity
// query, the staff directory, the cost lines), Partner work left off as the
// view leaves it, and risk_service.annotate's verdict on each item.

// act is one activity row as build_items reads it, with the columns the
// completion columns read of the same row.
type act struct {
	id, activityType, status, evidence, ia, payment, salesforce, fy  string
	responsible, monitored, partner, delivery                        string
	schoolPK, clusterID, projectID, courseID, catalogueID            string
	focus, purposeIntervention, rationale, purposeText, purposeType  string
	snapshot, pairedVisit, venue, programmeMode                      string
	perSchool, teachersPerSchool, expected, estCost, reschedules     int64
	costMissing                                                      bool
	submittedToIA, scheduled, executionStarted, plReviewed           *time.Time
	plannedDate, actualDelivery, plannedBefore                       *time.Time
	schoolCode, schoolName, schoolType, schoolDistrictID, schoolDist string
	hasSchool                                                        bool
	clusterName, clusterDistrictID, clusterDistrict                  string
	courseDisplay, courseSource                                      string
	partnerName                                                      string
}

const actColumns = `a.id, COALESCE(a.activity_type, ''), COALESCE(a.status, ''), COALESCE(a.evidence_status, ''),
  COALESCE(a.ia_verification_status, ''), COALESCE(a.payment_status, ''), COALESCE(a.salesforce_activity_id, ''),
  COALESCE(a.fy, ''), COALESCE(a.responsible_staff_id, ''), COALESCE(a.monitored_by_staff_id, ''),
  COALESCE(a.assigned_partner_id, ''), COALESCE(a.delivery_type, ''), COALESCE(a.school_id, ''),
  COALESCE(a.cluster_id, ''), COALESCE(a.project_id, ''), COALESCE(a.training_course_id, ''),
  COALESCE(a.catalogue_item_id, ''), COALESCE(a.focus_intervention, ''), COALESCE(a.purpose_intervention, ''),
  COALESCE(a.support_rationale, ''), COALESCE(a.activity_purpose_text, ''), COALESCE(a.purpose_type, ''),
  COALESCE(a.activity_name_snapshot, ''), COALESCE(a.paired_school_visit_id, ''), COALESCE(a.venue, ''),
  COALESCE(a.programme_delivery_mode, ''),
  COALESCE(a.participants_per_school, 0)::bigint, COALESCE(a.teachers_per_school, 0)::bigint,
  COALESCE(a.expected_participants, 0)::bigint, COALESCE(a.est_cost_cents, 0)::bigint,
  COALESCE(a.reschedule_count, 0)::bigint, COALESCE(a.cost_missing, false),
  a.submitted_to_ia_at, a.scheduled_date, a.execution_started_at, a.pl_reviewed_at,
  a.planned_date, a.actual_delivery_date, a.planned_date_before_completion,
  COALESCE(s.school_id, ''), COALESCE(s.name, ''), COALESCE(s.school_type, ''), COALESCE(s.district_id, ''),
  COALESCE(sd.name, ''), s.id IS NOT NULL,
  COALESCE(c.name, ''), COALESCE(c.district_id, ''), COALESCE(cd.name, ''),
  COALESCE(tc.display_name, ''), COALESCE(tc.source_name, ''), COALESCE(pt.name, '')`

const actJoins = ` FROM activity a
LEFT JOIN school s ON s.id = a.school_id
LEFT JOIN district sd ON sd.id = s.district_id
LEFT JOIN cluster c ON c.id = a.cluster_id
LEFT JOIN district cd ON cd.id = c.district_id
LEFT JOIN activity_catalogue_item tc ON tc.id = a.training_course_id
LEFT JOIN partner pt ON pt.id = a.assigned_partner_id`

// readTeamActs is _activity_queryset for the team (both id spaces; nil for
// the country and region lenses) and the regions (nil but for the region
// lens: work at a school in one, or at a cluster whose district is) in the
// years and period read, in the model's order made total.
func (s *Service) readTeamActs(ctx context.Context, team, regions, years []string, read periodRead) ([]*act, error) {
	args := []any{rules.TeamPlan.LiveActivityStatuses, years, team, regions}
	where, args := periodWhere(read, years, args)
	rows, err := s.db.Query(ctx, `SELECT `+actColumns+actJoins+`
WHERE a.deleted_at IS NULL AND a.status = ANY($1) AND a.fy = ANY($2)`+where+`
  AND ($3::text[] IS NULL OR a.responsible_staff_id = ANY($3) OR a.monitored_by_staff_id = ANY($3)
       OR s.account_owner_id = ANY($3) OR c.responsible_staff_id = ANY($3))
  AND ($4::text[] IS NULL OR s.region_id = ANY($4) OR cd.region_id = ANY($4))
ORDER BY a.created_at DESC, a.id`, args...)
	if err != nil {
		return nil, fmt.Errorf("planningoversight: reading the team's work: %w", err)
	}
	defer rows.Close()
	out := []*act{}
	for rows.Next() {
		a := &act{}
		if err := rows.Scan(&a.id, &a.activityType, &a.status, &a.evidence, &a.ia, &a.payment, &a.salesforce,
			&a.fy, &a.responsible, &a.monitored, &a.partner, &a.delivery, &a.schoolPK, &a.clusterID, &a.projectID,
			&a.courseID, &a.catalogueID, &a.focus, &a.purposeIntervention, &a.rationale, &a.purposeText,
			&a.purposeType, &a.snapshot, &a.pairedVisit, &a.venue, &a.programmeMode,
			&a.perSchool, &a.teachersPerSchool, &a.expected, &a.estCost, &a.reschedules, &a.costMissing,
			&a.submittedToIA, &a.scheduled, &a.executionStarted, &a.plReviewed,
			&a.plannedDate, &a.actualDelivery, &a.plannedBefore,
			&a.schoolCode, &a.schoolName, &a.schoolType, &a.schoolDistrictID, &a.schoolDist, &a.hasSchool,
			&a.clusterName, &a.clusterDistrictID, &a.clusterDistrict, &a.courseDisplay, &a.courseSource, &a.partnerName); err != nil {
			return nil, fmt.Errorf("planningoversight: reading the team's work: %w", err)
		}
		out = append(out, a)
	}
	return out, rows.Err()
}

// periodWhere is the period part of _activity_queryset (_in_month, the
// quarter, _dated_between) appended to args.
func periodWhere(read periodRead, years []string, args []any) (string, []any) {
	n := len(args)
	p := func(i int) string { return "$" + strconv.Itoa(n+i) }
	switch {
	case read.month != 0:
		parts := []string{"(a.planned_date IS NULL AND a.scheduled_date IS NULL AND a.planned_month = " + p(1) + ")"}
		args = append(args, read.month)
		for _, fy := range years {
			year, _ := strconv.Atoi(fy)
			if read.month >= 10 {
				year--
			}
			first := time.Date(year, time.Month(read.month), 1, 0, 0, 0, 0, time.UTC)
			args = append(args, first, first.AddDate(0, 1, 0))
			k := len(args) - n
			parts = append(parts, dated(p(k-1)+"::date", p(k)+"::date"))
		}
		return " AND (" + strings.Join(parts, " OR ") + ")", args
	case read.quarter != "":
		return " AND a.quarter = " + p(1), append(args, read.quarter)
	case !read.start.IsZero():
		return " AND " + dated(p(1)+"::date", p(2)+"::date"), append(args, read.start, read.end)
	}
	return "", args
}

// item is a PlanningOversightItem of the team's own (staff) work, with the
// completion columns once annotated.
type item struct {
	a                                            *act
	activityType, status                         string
	schoolPK, schoolCode, schoolName, schoolType string
	districtID, districtName                     string
	clusterID, clusterName                       string
	intervention, purpose, rationale, training   string
	participants                                 *int64
	delivery, plannedFrom                        string
	inSchool, costOnVisit                        bool
	plannedBy, owner, ownerName                  string
	plannedDate, submittedToIA                   *time.Time
	plannedCost                                  int64
	risky                                        bool
	// The completion columns (completion_columns.annotate).
	salesforceID, gap, rowState              string
	plannedBefore, completedOn               *time.Time
	isComplete, finishedEarly, showsComplete bool
	// A cluster session's row for one school it invited.
	invited bool
	// The Programme Lead the owner reports to (the country lens's tabs).
	lead string
	// Partner work (kept for the coverage lens only): delivered by a
	// Partner, or a hand-over it has not dated yet (assignment set).
	partner                      bool
	partnerName                  string
	assignment, assignmentStatus string
}

func (it *item) contextLabel() string {
	return first(it.schoolName, it.clusterName, it.a.venue, "No context")
}

func (it *item) completed() bool {
	return slices.Contains(rules.TeamPlan.Items.CompletedWorkStatuses, it.status)
}

func first(values ...string) string {
	for _, v := range values {
		if v != "" {
			return v
		}
	}
	return ""
}

// isPartner is _activity_item's Partner rule (staff_my_plan_q's).
func (a *act) isPartner() bool {
	return a.partner != "" || a.delivery == "partner" || slices.Contains(rules.TeamPlan.Items.PartnerOnlyStatuses, a.status)
}

// buildItems is build_items for the lens with the view's Partner filter:
// the team's staff work, sorted by date then context, risk-annotated.
func (s *Service) buildItems(ctx context.Context, team, regions, years []string, read periodRead, today time.Time) ([]*item, error) {
	return s.buildItemsKeeping(ctx, team, regions, years, read, today, false)
}

// buildItemsKeeping is buildItems, with the Partner-delivered work kept
// when withPartner (the coverage lens reads every school's planned work).
func (s *Service) buildItemsKeeping(ctx context.Context, team, regions, years []string, read periodRead, today time.Time, withPartner bool) ([]*item, error) {
	acts, err := s.readTeamActs(ctx, team, regions, years, read)
	if err != nil {
		return nil, err
	}
	staff := []*act{}
	for _, a := range acts {
		if withPartner || !a.isPartner() {
			staff = append(staff, a)
		}
	}
	if len(staff) == 0 {
		return nil, nil
	}
	ids, people := []string{}, []string{}
	for _, a := range staff {
		ids = append(ids, a.id)
		people = append(people, a.responsible, a.monitored)
	}
	names, err := s.staffNames(ctx, people)
	if err != nil {
		return nil, err
	}
	costs, err := s.costs(ctx, ids)
	if err != nil {
		return nil, err
	}
	live, err := s.liveCompanions(ctx, staff)
	if err != nil {
		return nil, err
	}
	fixed, err := s.fixedInterventions(ctx)
	if err != nil {
		return nil, err
	}
	outside, err := visitgate.ProjectsOutsideSSA(ctx, s.db, schoolprofile.GateRules())
	if err != nil {
		return nil, err
	}
	items := make([]*item, 0, len(staff))
	for _, a := range staff {
		it := buildItem(a, names, costs, live, fixed, outside)
		it.risky = hasRisk(it, today)
		items = append(items, it)
	}
	slices.SortStableFunc(items, func(x, y *item) int {
		if c := compareDay(x.plannedDate, y.plannedDate); c != 0 {
			return c
		}
		return strings.Compare(x.contextLabel(), y.contextLabel())
	})
	return items, nil
}

// compareDay orders days with no day last (date.max).
func compareDay(x, y *time.Time) int {
	switch {
	case x == nil && y == nil:
		return 0
	case x == nil:
		return 1
	case y == nil:
		return -1
	}
	return x.Compare(*y)
}

func buildItem(a *act, names, costs map[string]int64Name, live map[string]bool, fixed map[string]string, outside []string) *item {
	r := rules.TeamPlan.Items
	owner := first(a.responsible, a.monitored)
	if a.isPartner() {
		owner = first(a.monitored, a.responsible)
	}
	inSchool := a.pairedVisit != "" || a.activityType == "in_school_training" || a.delivery == "in-school"
	cost := a.estCost
	if c, ok := costs[a.id]; ok && c.n != 0 {
		cost = c.n
	}
	isVisit := slices.Contains(r.VisitTypes, a.activityType) && !inSchool
	isTraining := !isVisit && (slices.Contains(r.TrainingTypes, a.activityType) ||
		strings.Contains(strings.ToLower(a.activityType), "training") || inSchool || a.courseID != "")
	training := "—"
	if isTraining {
		training = first(a.courseDisplay, a.courseSource, a.snapshot, pyTitle(strings.ReplaceAll(a.activityType, "_", " ")))
	}
	purposeLabel := ""
	if a.purposeType != "" {
		purposeLabel = r.PurposeLabels[a.purposeType]
	}
	focus := first(a.focus, a.purposeIntervention)
	if focus == "" && isTraining {
		for _, id := range []string{a.courseID, a.catalogueID} {
			if id != "" && fixed[id] != "" {
				focus = fixed[id]
				break
			}
		}
	}
	if focus == "" && a.projectID != "" && slices.Contains(outside, a.projectID) {
		focus = r.GeneralIntervention
	}
	participants := a.perSchool
	if participants == 0 {
		participants = a.expected
	}
	it := &item{
		a: a, activityType: a.activityType, status: a.status,
		schoolPK: a.schoolPK, schoolName: a.schoolName, schoolType: a.schoolType,
		clusterID: a.clusterID, clusterName: a.clusterName,
		intervention: focus,
		purpose:      first(a.purposeText, purposeLabel, a.rationale, a.purposeIntervention, "—"),
		rationale:    first(a.rationale, a.purposeText),
		training:     training,
		participants: &participants,
		delivery:     "group",
		plannedFrom:  first(a.clusterName, "—"),
		inSchool:     inSchool,
		costOnVisit:  a.activityType == "in_school_training" && a.pairedVisit != "" && live[a.pairedVisit],
		plannedBy:    owner, owner: owner, ownerName: names[owner].name,
		plannedDate: a.plannedDate, submittedToIA: a.submittedToIA,
		plannedCost: cost,
	}
	it.schoolCode = first(a.schoolCode, a.schoolPK, "—")
	if a.isPartner() {
		it.partner, it.partnerName = true, a.partnerName
	}
	if inSchool {
		it.plannedFrom, it.delivery = "School Visit", "in-school"
	}
	if a.hasSchool {
		it.districtID, it.districtName = a.schoolDistrictID, a.schoolDist
	}
	if it.districtName == "" && a.clusterID != "" && a.clusterDistrictID != "" {
		it.districtID, it.districtName = a.clusterDistrictID, a.clusterDistrict
	}
	return it
}

// int64Name is a figure or a name by id.
type int64Name struct {
	n    int64
	name string
}

// pyTitle is str.title: each run of letters capitalised after a non-letter.
func pyTitle(s string) string {
	out := []rune{}
	prevLetter := false
	for _, r := range s {
		isLetter := (r >= 'a' && r <= 'z') || (r >= 'A' && r <= 'Z')
		switch {
		case isLetter && !prevLetter:
			out = append(out, []rune(strings.ToUpper(string(r)))...)
		case isLetter:
			out = append(out, []rune(strings.ToLower(string(r)))...)
		default:
			out = append(out, r)
		}
		prevLetter = isLetter
	}
	return string(out)
}

// staffNames is _StaffDirectory.name: each profile's user's name (else
// email), under its profile id and its user id.
func (s *Service) staffNames(ctx context.Context, ids []string) (map[string]int64Name, error) {
	out := map[string]int64Name{}
	ids = slices.DeleteFunc(slices.Clone(ids), func(id string) bool { return id == "" })
	if len(ids) == 0 {
		return out, nil
	}
	rows, err := s.db.Query(ctx, `
SELECT sp.id, COALESCE(sp.user_id, ''), COALESCE(NULLIF(u.name, ''), u.email, '')
FROM staff_profile sp LEFT JOIN "user" u ON u.id = sp.user_id
WHERE sp.id = ANY($1) OR sp.user_id = ANY($1) ORDER BY sp.id`, ids)
	if err != nil {
		return nil, fmt.Errorf("planningoversight: reading the staff: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var id, user, name string
		if err := rows.Scan(&id, &user, &name); err != nil {
			return nil, fmt.Errorf("planningoversight: reading the staff: %w", err)
		}
		for _, key := range []string{id, user} {
			if key != "" {
				out[key] = int64Name{name: name}
			}
		}
	}
	return out, rows.Err()
}

// costs is _cost_by_activity: the sum of each activity's cost lines.
func (s *Service) costs(ctx context.Context, ids []string) (map[string]int64Name, error) {
	out := map[string]int64Name{}
	rows, err := s.db.Query(ctx, `SELECT activity_id, COALESCE(SUM(amount), 0)::bigint FROM activity_schedule_cost_line
WHERE activity_id = ANY($1) GROUP BY activity_id`, ids)
	if err != nil {
		return nil, fmt.Errorf("planningoversight: reading the costs: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var id string
		var total int64
		if err := rows.Scan(&id, &total); err != nil {
			return nil, fmt.Errorf("planningoversight: reading the costs: %w", err)
		}
		out[id] = int64Name{n: total}
	}
	return out, rows.Err()
}

// liveCompanions is pair_costing.live_companions: the paired School Visits
// that still make the journey.
func (s *Service) liveCompanions(ctx context.Context, acts []*act) (map[string]bool, error) {
	out := map[string]bool{}
	visits := []string{}
	for _, a := range acts {
		if a.activityType == "in_school_training" && a.pairedVisit != "" {
			visits = append(visits, a.pairedVisit)
		}
	}
	if len(visits) == 0 {
		return out, nil
	}
	rows, err := s.db.Query(ctx, `SELECT id FROM activity WHERE id = ANY($1) AND deleted_at IS NULL
  AND (status IS NULL OR NOT status = ANY($2))`, visits, rules.TeamPlan.Items.CompanionGoneStatuses)
	if err != nil {
		return nil, fmt.Errorf("planningoversight: reading the paired visits: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var id string
		if err := rows.Scan(&id); err != nil {
			return nil, fmt.Errorf("planningoversight: reading the paired visits: %w", err)
		}
		out[id] = true
	}
	return out, rows.Err()
}

// fixedInterventions is training_intervention.fixed_interventions.
func (s *Service) fixedInterventions(ctx context.Context) (map[string]string, error) {
	out := map[string]string{}
	rows, err := s.db.Query(ctx, `SELECT catalogue_item_id, intervention FROM activity_intervention_mapping
WHERE active AND mapping_mode = 'fixed' AND intervention IS NOT NULL AND intervention <> ''
ORDER BY is_primary DESC, priority, id`)
	if err != nil {
		return nil, fmt.Errorf("planningoversight: reading the courses' interventions: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var id, intervention string
		if err := rows.Scan(&id, &intervention); err != nil {
			return nil, fmt.Errorf("planningoversight: reading the courses' interventions: %w", err)
		}
		if _, seen := out[id]; !seen {
			out[id] = intervention
		}
	}
	return out, rows.Err()
}

// hasRisk is whether risk_service.risks_for finds any risk on a staff item
// (the Partner's own detector never fires on one).
func hasRisk(it *item, today time.Time) bool {
	r := rules.TeamPlan.Items.Risk
	a := it.a
	in := slices.Contains[[]string]
	days := func(t *time.Time, n int) time.Time { return t.AddDate(0, 0, n) }
	// scheduled_without_cost
	if a.costMissing || !(it.costOnVisit || it.plannedCost > 0) {
		return true
	}
	if p := it.plannedDate; p != nil {
		// activity_overdue
		if p.Before(today) && !it.completed() && !in(r.PostFieldStatuses, it.status) && it.submittedToIA == nil {
			return true
		}
		// evidence_outstanding
		if (a.evidence == "" || a.evidence == "none") && days(p, r.EvidenceGraceDays).Before(today) &&
			in(r.EvidenceExpectedStatuses, it.status) {
			return true
		}
	}
	// salesforce_missing
	if a.salesforce == "" && in(r.SalesforceExpectedStatuses, it.status) {
		return true
	}
	// ia_returned
	if it.status == "returned_by_ia" || a.ia == "returned" {
		return true
	}
	// repeated_reschedule
	if a.reschedules > int64(r.RescheduleLimit) {
		return true
	}
	// ia_verification_overdue
	if sub := utcDay(it.submittedToIA); sub != nil && !in(r.IASettledStatuses, first(a.ia, "pending")) &&
		today.After(days(sub, r.IAVerificationGraceDays)) {
		return true
	}
	// payment_overdue
	if a.ia == "confirmed" && !in(r.PaymentSettledStatuses, first(a.payment, "none")) && it.plannedDate != nil &&
		today.After(days(it.plannedDate, r.PaymentGraceDays)) {
		return true
	}
	return false
}

// utcDay is a stored moment's .date() (the database's UTC).
func utcDay(t *time.Time) *time.Time {
	if t == nil {
		return nil
	}
	u := t.UTC()
	d := time.Date(u.Year(), u.Month(), u.Day(), 0, 0, 0, 0, time.UTC)
	return &d
}

// localDay is clock.local_day: a moment's day in the application's zone.
func localDay(t *time.Time) *time.Time {
	if t == nil {
		return nil
	}
	l := t.In(zone)
	d := time.Date(l.Year(), l.Month(), l.Day(), 0, 0, 0, 0, time.UTC)
	return &d
}

// dateOnly is a date column's day.
func dateOnly(t *time.Time) *time.Time {
	if t == nil {
		return nil
	}
	d := time.Date(t.Year(), t.Month(), t.Day(), 0, 0, 0, 0, time.UTC)
	return &d
}
