package partneroversight

import (
	"context"
	"fmt"
	"sort"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// The page's partner work for a team lens (partner_oversight_service.
// build_items with _resolve_scope's "team"): every hand-over the team may
// oversee that is still the Partner's, for the years read, and every
// Partner-delivered activity no hand-over points at.

// assignmentSQL reads the hand-overs of the team ($1, both id spaces) still
// the Partner's (not left_partner_q: $2 the statuses that left, $3 the
// hand-back status).
const assignmentSQL = `
SELECT pa.id, pa.status, COALESCE(pa.partner_id, ''), COALESCE(p.name, ''),
  COALESCE(pa.school_id, ''), COALESCE(s.school_id, ''), COALESCE(s.name, ''), COALESCE(s.school_type, ''),
  COALESCE(d.name, ''), COALESCE(s.account_owner_id, ''), COALESCE(s.account_owner_name_raw, ''),
  COALESCE(pa.cluster_id, ''), COALESCE(c.name, ''), COALESCE(c.responsible_staff_id, ''),
  COALESCE(pa.project_id, ''), COALESCE(pr.name, ''),
  COALESCE(pa.monitoring_staff_id, ''), COALESCE(pa.assigning_staff_id, ''),
  COALESCE(pa.purpose_of_visit, ''), COALESCE(pa.expected_activity_type, ''), COALESCE(pa.focus_intervention, ''),
  COALESCE(NULLIF(tc.display_name, ''), tc.source_name, ''), COALESCE(NULLIF(ci.display_name, ''), ci.source_name, ''),
  sa.id IS NOT NULL, COALESCE(NULLIF(sc.display_name, ''), sc.source_name, ''),
  COALESCE(sa.activity_name_snapshot, ''), COALESCE(sa.activity_type, ''),
  COALESCE(pa.return_reason_category, ''), COALESCE(pa.return_reason, ''), COALESCE(pa.resolution, ''),
  pa.created_at, pa.scheduled_date, COALESCE(pa.scheduled_activity_id, ''), pa.resolved_at IS NOT NULL,
  COALESCE(pa.support_type, '')
FROM partner_assignment pa
LEFT JOIN partner p ON p.id = pa.partner_id
LEFT JOIN school s ON s.id = pa.school_id
LEFT JOIN district d ON d.id = s.district_id
LEFT JOIN cluster c ON c.id = pa.cluster_id
LEFT JOIN project pr ON pr.id = pa.project_id
LEFT JOIN activity_catalogue_item tc ON tc.id = pa.training_course_id
LEFT JOIN activity_catalogue_item ci ON ci.id = pa.catalogue_item_id
LEFT JOIN activity sa ON sa.id = pa.source_activity_id
LEFT JOIN activity_catalogue_item sc ON sc.id = sa.training_course_id
WHERE NOT (pa.status = ANY($2) OR (pa.status = $3 AND pa.resolved_at IS NOT NULL))
  AND ($1::text[] IS NULL OR pa.monitoring_staff_id = ANY($1) OR pa.assigning_staff_id = ANY($1)
    OR s.account_owner_id = ANY($1) OR c.responsible_staff_id = ANY($1))
  AND ($4::text[] IS NULL OR s.region_id = ANY($4) OR c.region_id = ANY($4))
ORDER BY pa.created_at DESC, pa.id`

// activity is the fields of an activity the page reads.
type activity struct {
	id, activityType, status, evidence, salesforce, ia, payment string
	submittedToIA, updated, executionStarted, plReviewed        *time.Time
	plannedDate, actualDelivery, plannedBefore                  *time.Time
	scheduled                                                   *time.Time
	contact, monitor, fy, quarter, courseName, snapshot         string
	focus, purposeIntervention, purposeType, dateSetBy          string
	reschedules                                                 int
	plannedMonth                                                *int
	delivery                                                    string
	// For an activity no hand-over points at.
	partnerID, schoolID, clusterID, projectID, responsible string
	schoolCode, schoolName, schoolType, district           string
	owner, ownerRaw, clusterName, clusterOwner             string
	partnerName, projectName                               string
	ssaExpected                                            bool
}

const activityColumns = `a.id, COALESCE(a.activity_type, ''), COALESCE(a.status, ''), COALESCE(a.evidence_status, ''),
  COALESCE(a.salesforce_activity_id, ''), COALESCE(a.ia_verification_status, ''), COALESCE(a.payment_status, ''),
  a.submitted_to_ia_at, a.updated_at, a.execution_started_at, a.pl_reviewed_at,
  a.planned_date, a.actual_delivery_date, a.planned_date_before_completion, a.scheduled_date,
  COALESCE(a.delivery_contact_name, ''), COALESCE(a.monitored_by_staff_id, ''), COALESCE(a.fy, ''), COALESCE(a.quarter, ''),
  COALESCE(NULLIF(tc.display_name, ''), tc.source_name, ''), COALESCE(a.activity_name_snapshot, ''),
  COALESCE(a.focus_intervention, ''), COALESCE(a.purpose_intervention, ''), COALESCE(a.purpose_type, ''),
  COALESCE(a.partner_date_set_by, ''), COALESCE(a.reschedule_count, 0), a.planned_month, COALESCE(a.delivery_type, ''),
  COALESCE(a.assigned_partner_id, ''), COALESCE(a.school_id, ''), COALESCE(a.cluster_id, ''), COALESCE(a.project_id, ''),
  COALESCE(a.responsible_staff_id, ''),
  COALESCE(s.school_id, ''), COALESCE(s.name, ''), COALESCE(s.school_type, ''), COALESCE(sd.name, ''),
  COALESCE(s.account_owner_id, ''), COALESCE(s.account_owner_name_raw, ''), COALESCE(c.name, ''),
  COALESCE(c.responsible_staff_id, ''), COALESCE(pt.name, ''), COALESCE(pr.name, ''),
  COALESCE(a.ssa_collection_expected, false)`

func scanActivity(row pgx.Row, a *activity) error {
	return row.Scan(&a.id, &a.activityType, &a.status, &a.evidence, &a.salesforce, &a.ia, &a.payment,
		&a.submittedToIA, &a.updated, &a.executionStarted, &a.plReviewed,
		&a.plannedDate, &a.actualDelivery, &a.plannedBefore, &a.scheduled,
		&a.contact, &a.monitor, &a.fy, &a.quarter, &a.courseName, &a.snapshot,
		&a.focus, &a.purposeIntervention, &a.purposeType, &a.dateSetBy, &a.reschedules, &a.plannedMonth, &a.delivery,
		&a.partnerID, &a.schoolID, &a.clusterID, &a.projectID, &a.responsible,
		&a.schoolCode, &a.schoolName, &a.schoolType, &a.district, &a.owner, &a.ownerRaw, &a.clusterName,
		&a.clusterOwner, &a.partnerName, &a.projectName, &a.ssaExpected)
}

// day is activity_day: the planned day, else the scheduled moment's day in
// Kampala.
func (a *activity) day() *time.Time {
	if a.plannedDate != nil {
		d := dateOf(*a.plannedDate)
		return &d
	}
	return localDay(a.scheduled)
}

func dateOf(t time.Time) time.Time {
	return time.Date(t.Year(), t.Month(), t.Day(), 0, 0, 0, 0, time.UTC)
}

func localDay(t *time.Time) *time.Time {
	if t == nil {
		return nil
	}
	d := dateOf(t.In(zone))
	return &d
}

// hasDated is dating_policy.partner_has_dated.
func (a *activity) hasDated() bool {
	if a.status == "assigned_to_partner" || a.dateSetBy == rules.Work.DatedByStaff {
		return false
	}
	return a.plannedDate != nil || a.scheduled != nil
}

func readActivities(ctx context.Context, db schooldirectory.Querier, where string, args ...any) ([]*activity, error) {
	rows, err := db.Query(ctx, `SELECT `+activityColumns+` FROM activity a
LEFT JOIN activity_catalogue_item tc ON tc.id = a.training_course_id
LEFT JOIN school s ON s.id = a.school_id
LEFT JOIN district sd ON sd.id = s.district_id
LEFT JOIN cluster c ON c.id = a.cluster_id
LEFT JOIN partner pt ON pt.id = a.assigned_partner_id
LEFT JOIN project pr ON pr.id = a.project_id
WHERE `+where, args...)
	if err != nil {
		return nil, fmt.Errorf("partneroversight: reading the Partner activities: %w", err)
	}
	defer rows.Close()
	out := []*activity{}
	for rows.Next() {
		a := &activity{}
		if err := scanActivity(rows, a); err != nil {
			return nil, fmt.Errorf("partneroversight: reading the Partner activities: %w", err)
		}
		out = append(out, a)
	}
	return out, rows.Err()
}

// directory is _staff_directory: each officer's name (in both id spaces),
// their profile id, and the Country Programme Lead they report to.
type directory struct {
	names, canonical map[string]string
	supervisor       map[string][2]string
}

func readDirectory(ctx context.Context, db schooldirectory.Querier, ids []string) (directory, error) {
	dir := directory{names: map[string]string{}, canonical: map[string]string{}, supervisor: map[string][2]string{}}
	if len(ids) == 0 {
		return dir, nil
	}
	rows, err := db.Query(ctx, `
SELECT sp.id, COALESCE(sp.user_id, ''), COALESCE(NULLIF(u.name, ''), u.email, ''),
  COALESCE($2 = ANY(COALESCE(u.roles, '{}')) OR u.active_role = $2, false)
FROM staff_profile sp LEFT JOIN "user" u ON u.id = sp.user_id
WHERE sp.id = ANY($1) OR sp.user_id = ANY($1)
ORDER BY sp.id`, ids, rules.RosterLeadRole)
	if err != nil {
		return dir, fmt.Errorf("partneroversight: reading the staff: %w", err)
	}
	profiles := []string{}
	for rows.Next() {
		var id, user, name string
		var lead bool
		if err := rows.Scan(&id, &user, &name, &lead); err != nil {
			rows.Close()
			return dir, fmt.Errorf("partneroversight: reading the staff: %w", err)
		}
		profiles = append(profiles, id)
		for _, key := range []string{id, user} {
			if key != "" {
				dir.names[key] = name
				dir.canonical[key] = id
			}
		}
		if lead {
			dir.supervisor[id] = [2]string{id, name}
			if user != "" {
				dir.supervisor[user] = [2]string{id, name}
			}
		}
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return dir, err
	}
	rows, err = db.Query(ctx, `
SELECT a.supervisee_id, a.supervisor_id, COALESCE(NULLIF(u.name, ''), u.email, '')
FROM staff_supervisor_assignment a
JOIN staff_profile sp ON sp.id = a.supervisor_id
JOIN "user" u ON u.id = sp.user_id
WHERE a.supervisee_id = ANY($1) AND ($2 = ANY(COALESCE(u.roles, '{}')) OR u.active_role = $2)
ORDER BY a.supervisee_id, a.supervisor_id`, profiles, rules.RosterLeadRole)
	if err != nil {
		return dir, fmt.Errorf("partneroversight: reading the supervisors: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var supervisee, supervisor, name string
		if err := rows.Scan(&supervisee, &supervisor, &name); err != nil {
			return dir, fmt.Errorf("partneroversight: reading the supervisors: %w", err)
		}
		if _, ok := dir.supervisor[supervisee]; !ok {
			dir.supervisor[supervisee] = [2]string{supervisor, name}
		}
	}
	return dir, rows.Err()
}

func readCosts(ctx context.Context, db schooldirectory.Querier, ids []string) (map[string]int64, error) {
	out := map[string]int64{}
	if len(ids) == 0 {
		return out, nil
	}
	rows, err := db.Query(ctx, `SELECT activity_id, SUM(COALESCE(amount, 0))::bigint FROM activity_schedule_cost_line
WHERE activity_id = ANY($1) GROUP BY activity_id`, ids)
	if err != nil {
		return nil, fmt.Errorf("partneroversight: reading the costs: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var id string
		var total int64
		if err := rows.Scan(&id, &total); err != nil {
			return nil, fmt.Errorf("partneroversight: reading the costs: %w", err)
		}
		out[id] = total
	}
	return out, rows.Err()
}

// choiceLabel is partner_oversight_service.choice_label.
func choiceLabel(value string, labels map[string]string) string {
	if value == "" {
		return ""
	}
	if l, ok := labels[value]; ok {
		return l
	}
	return pyTitle(strings.ReplaceAll(value, "_", " "))
}

// work is describe_work's inputs.
type work struct {
	purpose, activityType, course, catalogue, focus string
	sourceCourse, sourceSnapshot, sourceType        string
	hasSource                                       bool
	act                                             *activity
}

// describe is describe_work: (Training, Purpose of Assignment, SSA
// Intervention).
func describe(w work) (training, purpose, intervention string) {
	r := rules.Work
	if w.purpose == "" && w.act != nil {
		w.purpose = w.act.purposeType
	}
	if w.activityType == "" && w.act != nil {
		w.activityType = w.act.activityType
	}
	isTraining := w.purpose == "in_school_training" || in(r.TrainingTypes, w.activityType)
	training = w.course
	if training == "" && w.act != nil {
		training = w.act.courseName
	}
	if training == "" && isTraining {
		training = w.catalogue
		if training == "" && w.act != nil {
			training = w.act.snapshot
		}
	}
	if training == "" && w.purpose == "training_follow_up" && w.hasSource {
		training = w.sourceCourse
		if training == "" {
			training = w.sourceSnapshot
		}
		if training == "" {
			training = choiceLabel(w.sourceType, r.ActivityTypeLabels)
		}
	}
	if w.purpose != "" {
		purpose = r.PurposeLabels[w.purpose]
	}
	if purpose == "" {
		purpose = choiceLabel(w.activityType, r.ActivityTypeLabels)
	}
	code := w.focus
	if code == "" && w.act != nil {
		code = w.act.focus
		if code == "" {
			code = w.act.purposeIntervention
		}
	}
	intervention = choiceLabel(code, r.InterventionLabels)
	if intervention == "" && (w.purpose == "ssa_support" || in(r.DataGatheringTypes, w.activityType)) {
		intervention = r.DataGatheringLabel
	}
	return training, purpose, intervention
}

// readItems is build_items for a team lens (team nil: the country's) over
// the years read, before the period narrows them.
func readItems(ctx context.Context, db schooldirectory.Querier, team, regions []string, years []string, today time.Time) ([]*item, error) {
	rows, err := db.Query(ctx, assignmentSQL, team, rules.LeftPartnerStatuses, rules.ReturnedToStaff, regions)
	if err != nil {
		return nil, fmt.Errorf("partneroversight: reading the hand-overs: %w", err)
	}
	type handover struct {
		it                                           *item
		w                                            work
		owner, ownerRaw, clusterOwner, mon, assigner string
		created                                      time.Time
		scheduledOn                                  *time.Time
		activityID                                   string
		resolved                                     bool
	}
	handovers := []*handover{}
	for rows.Next() {
		h := &handover{it: &item{}}
		it := h.it
		if err := rows.Scan(&it.assignmentID, &it.assignmentStatus, &it.partnerID, &it.partnerName,
			&it.schoolID, &it.schoolCode, &it.schoolName, &it.schoolType, &it.district, &h.owner, &h.ownerRaw,
			&it.clusterID, &it.clusterName, &h.clusterOwner, &it.projectID, &it.projectName,
			&h.mon, &h.assigner, &h.w.purpose, &h.w.activityType, &h.w.focus, &h.w.course, &h.w.catalogue,
			&h.w.hasSource, &h.w.sourceCourse, &h.w.sourceSnapshot, &h.w.sourceType,
			&it.returnReasonCategory, &it.returnReason, &it.resolution,
			&h.created, &h.scheduledOn, &h.activityID, &h.resolved, &it.supportType); err != nil {
			rows.Close()
			return nil, fmt.Errorf("partneroversight: reading the hand-overs: %w", err)
		}
		handovers = append(handovers, h)
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, err
	}

	activityIDs := []string{}
	for _, h := range handovers {
		if h.activityID != "" {
			activityIDs = append(activityIDs, h.activityID)
		}
	}
	acts, err := readActivities(ctx, db, `a.id = ANY($1)`, activityIDs)
	if err != nil {
		return nil, err
	}
	byID := map[string]*activity{}
	for _, a := range acts {
		byID[a.id] = a
	}
	wanted := map[string]bool{}
	for _, y := range years {
		wanted[y] = true
	}
	kept := []*handover{}
	for _, h := range handovers {
		a := byID[h.activityID]
		open := h.activityID == "" && (in(rules.Work.UnscheduledStatuses, h.it.assignmentStatus) ||
			(h.it.assignmentStatus == rules.ReturnedToStaff && !h.resolved))
		var fy string
		switch {
		case h.activityID != "" && a != nil:
			fy = a.fy
		case h.scheduledOn != nil:
			fy = schooldirectory.OperationalFY(*h.scheduledOn)
		default:
			fy = schooldirectory.OperationalFY(h.created.UTC())
		}
		if len(wanted) == 0 || open || wanted[fy] {
			h.it.activityID = ""
			if a != nil {
				h.it.activityID = a.id
			}
			kept = append(kept, h)
		}
	}

	keptActivities := []string{}
	for _, h := range kept {
		if h.it.activityID != "" {
			keptActivities = append(keptActivities, h.it.activityID)
		}
	}
	unassigned, err := readActivities(ctx, db, `a.deleted_at IS NULL AND a.delivery_type = $1
  AND COALESCE(a.assigned_partner_id, '') <> '' AND a.status <> ALL($2) AND a.fy = ANY($3) AND NOT (a.id = ANY($4))
  AND ($5::text[] IS NULL OR a.monitored_by_staff_id = ANY($5) OR a.responsible_staff_id = ANY($5)
    OR s.account_owner_id = ANY($5) OR c.responsible_staff_id = ANY($5))
  AND ($6::text[] IS NULL OR s.region_id = ANY($6) OR c.region_id = ANY($6))
ORDER BY a.created_at DESC, a.id`, rules.PartnerDelivery, []string{"cancelled", "rejected", "deferred"}, years, keptActivities, team, regions)
	if err != nil {
		return nil, err
	}

	staff := []string{}
	for _, h := range kept {
		staff = append(staff, h.mon, h.assigner, h.owner, h.clusterOwner)
	}
	for _, a := range unassigned {
		staff = append(staff, a.monitor, a.responsible, a.owner, a.clusterOwner)
	}
	dir, err := readDirectory(ctx, db, nonEmpty(staff))
	if err != nil {
		return nil, err
	}
	costIDs := append(append([]string{}, keptActivities...), func() []string {
		out := []string{}
		for _, a := range unassigned {
			out = append(out, a.id)
		}
		return out
	}()...)
	costs, err := readCosts(ctx, db, costIDs)
	if err != nil {
		return nil, err
	}
	officer := func(it *item, ids ...string) {
		id := first(ids...)
		it.cceoID = id
		if c, ok := dir.canonical[id]; ok {
			it.cceoID = c
		}
		it.cceoName = dir.names[id]
		if s, ok := dir.supervisor[it.cceoID]; ok {
			it.plID, it.plName = s[0], s[1]
		}
	}

	items := []*item{}
	for _, h := range kept {
		it := h.it
		a := byID[it.activityID]
		officer(it, h.mon, h.assigner, h.owner, h.clusterOwner)
		switch {
		case it.assignmentStatus == rules.ReturnedToStaff:
			it.stage = stageReturned
		case a != nil:
			it.stage = stageScheduled
		default:
			it.stage = stageAwaiting
		}
		h.w.act = a
		if a != nil && a.activityType != "" {
			h.w.activityType = a.activityType
		}
		it.activityType = h.w.activityType
		it.purposeCode = h.w.purpose
		it.targetIntervention = h.w.focus
		it.trainingName, it.purposeLabel, it.interventionLabel = describe(h.w)
		created := dateOf(h.created.In(zone))
		it.assignmentDate = &created
		if a != nil {
			fill(it, a, costs)
		}
		it.withdrawalLabel = withdrawalLabelOf(it.withdrawalKind(), it.partnerHasDated)
		items = append(items, it)
	}
	for _, a := range unassigned {
		it := &item{activityID: a.id, schoolID: a.schoolID, schoolCode: a.schoolCode, schoolName: a.schoolName,
			schoolType: a.schoolType, district: a.district, clusterID: a.clusterID, clusterName: a.clusterName,
			partnerID: a.partnerID, partnerName: a.partnerName, projectID: a.projectID, projectName: a.projectName}
		officer(it, a.monitor, a.responsible, a.owner, a.clusterOwner)
		it.stage = stageAwaiting
		if a.plannedDate != nil || a.scheduled != nil {
			it.stage = stageScheduled
		}
		it.activityType = a.activityType
		it.targetIntervention = a.focus
		it.trainingName, it.purposeLabel, it.interventionLabel = describe(work{act: a})
		fill(it, a, costs)
		it.withdrawalLabel = withdrawalLabelOf(it.withdrawalKind(), it.partnerHasDated)
		items = append(items, it)
	}
	for _, it := range items {
		it.risks = risksOf(it, today)
	}
	if err := attachClusters(ctx, db, items); err != nil {
		return nil, err
	}
	sortItems(items)
	return items, nil
}

// fill sets what the activity a Partner's scheduling created says.
func fill(it *item, a *activity, costs map[string]int64) {
	it.scheduledDate = a.day()
	it.quarter = a.quarter
	it.activityStatus = a.status
	it.evidenceStatus = a.evidence
	it.salesforceRecorded = a.salesforce != ""
	it.iaStatus = a.ia
	it.paymentStatus = a.payment
	it.submittedToIA = localDay(a.submittedToIA)
	it.fieldOfficer = a.contact
	it.rescheduleCount = a.reschedules
	cost := costs[a.id]
	it.plannedCost = &cost
	it.partnerHasDated = a.hasDated()
	it.act = a
}

// attachClusters is _attach_school_clusters: each row's own school's
// cluster, else the cluster the work was handed over against.
func attachClusters(ctx context.Context, db schooldirectory.Querier, items []*item) error {
	ids := []string{}
	for _, it := range items {
		if it.schoolID != "" {
			ids = append(ids, it.schoolID)
		}
	}
	names := map[string]string{}
	if len(ids) > 0 {
		rows, err := db.Query(ctx, `SELECT s.id, COALESCE(c.name, '') FROM school s JOIN cluster c ON c.id = s.cluster_id
WHERE s.id = ANY($1)`, ids)
		if err != nil {
			return fmt.Errorf("partneroversight: reading the schools' clusters: %w", err)
		}
		defer rows.Close()
		for rows.Next() {
			var id, name string
			if err := rows.Scan(&id, &name); err != nil {
				return fmt.Errorf("partneroversight: reading the schools' clusters: %w", err)
			}
			names[id] = name
		}
		if err := rows.Err(); err != nil {
			return err
		}
	}
	for _, it := range items {
		it.schoolClusterName = names[it.schoolID]
		if it.schoolClusterName == "" {
			it.schoolClusterName = it.clusterName
		}
	}
	return nil
}

func first(values ...string) string {
	for _, v := range values {
		if v != "" {
			return v
		}
	}
	return ""
}

func nonEmpty(values []string) []string {
	out := []string{}
	for _, v := range values {
		if v != "" && !contains(out, v) {
			out = append(out, v)
		}
	}
	return out
}

// sortItems is build_items' order: by Partner, then school, as Python's
// stable sort.
func sortItems(items []*item) {
	sort.SliceStable(items, func(a, b int) bool {
		if items[a].partnerName != items[b].partnerName {
			return items[a].partnerName < items[b].partnerName
		}
		return items[a].schoolName < items[b].schoolName
	})
}

// DescribeActivity is describe_work for one activity and its own catalogue
// item (describe_work(activity=a, catalogue_item=a.catalogue_item)), as
// Country Planning Oversight's tables read it: (Training, Purpose of
// Assignment, SSA Intervention).
func DescribeActivity(purpose, activityType, course, catalogue, snapshot, focus, purposeIntervention string) (string, string, string) {
	return describe(work{catalogue: catalogue, act: &activity{purposeType: purpose, activityType: activityType,
		courseName: course, snapshot: snapshot, focus: focus, purposeIntervention: purposeIntervention}})
}
