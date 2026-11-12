package myplan

import (
	"context"
	"errors"
	"fmt"
	"slices"
	"strconv"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// ErrUnported is a plan whose rows need a part of the existing code Go
// does not draw yet (a rate only the live catalogue answers, a stored cost
// the existing code would fail on): the caller passes the page to the
// existing application rather than approximate it.
var ErrUnported = errors.New("myplan: the rows need a part Go does not draw yet")

// activity is one planned activity as get_frontend_context reads it, with
// the school, district, cluster and catalogue items select_related joins.
type activity struct {
	id, activityType, status                          string
	fy                                                *string
	plannedDate, scheduledDate, createdAt             *time.Time
	schoolPK, clusterID, staffID, partnerID, delivery *string
	salesforce                                        *string
	rescheduleCount                                   int
	purposeText, purposeType, focus                   *string
	teachersAttended, leadersAttended, others         *int
	expected, perSchool, teachersPerSchool            *int
	courseID, courseName, itemID, itemName            *string
	itemIsCourse                                      bool
	deliveryMode, planningSource                      *string
	costMissing                                       bool
	pairedVisit, iaVerification                       *string
	ssaExpected                                       bool
	batchID, eventDistrictID                          *string
	actualDelivery, executionStarted                  *time.Time
	submittedToIA, plReviewed, plannedBefore          *time.Time

	hasSchool                            bool
	schoolCode, schoolName, schoolType   *string
	schoolDistrictID, schoolDistrictName *string
	hasCluster                           bool
	clusterName, clusterDistrictID       *string
	schoolClusterID                      *string
}

func str(p *string) string {
	if p == nil {
		return ""
	}
	return *p
}

func isSet(p *string) bool { return p != nil && *p != "" }

const activitySelect = `SELECT a.id, a.activity_type, COALESCE(a.status, ''), a.fy, a.planned_date, a.scheduled_date, a.created_at,
  a.school_id, a.cluster_id, a.responsible_staff_id, a.assigned_partner_id, a.delivery_type, a.salesforce_activity_id,
  COALESCE(a.reschedule_count, 0), a.activity_purpose_text, a.purpose_type, a.focus_intervention,
  a.teachers_attended, a.leaders_attended, a.other_participants, a.expected_participants,
  a.participants_per_school, a.teachers_per_school,
  a.training_course_id, tc.display_name, a.catalogue_item_id, ci.display_name, COALESCE(ci.is_training_course, false),
  a.programme_delivery_mode, a.planning_source, COALESCE(a.cost_missing, false), a.paired_school_visit_id,
  a.ia_verification_status, COALESCE(a.ssa_collection_expected, false), a.daily_visit_batch_id, a.event_district_id,
  a.actual_delivery_date, a.execution_started_at, a.submitted_to_ia_at, a.pl_reviewed_at, a.planned_date_before_completion,
  s.id IS NOT NULL, s.school_id, s.name, s.school_type, s.district_id, sd.name,
  c.id IS NOT NULL, c.name, c.district_id, s.cluster_id
FROM activity a
LEFT JOIN school s ON s.id = a.school_id
LEFT JOIN district sd ON sd.id = s.district_id
LEFT JOIN cluster c ON c.id = a.cluster_id
LEFT JOIN activity_catalogue_item tc ON tc.id = a.training_course_id
LEFT JOIN activity_catalogue_item ci ON ci.id = a.catalogue_item_id`

// readActivities is context_for's queryset as get_frontend_context reads
// it: exactly these activities, not deleted, by planned date then made.
func readActivities(ctx context.Context, db schooldirectory.Querier, ids []string) ([]*activity, error) {
	rows, err := db.Query(ctx, activitySelect+`
WHERE a.deleted_at IS NULL AND a.id IN (SELECT unnest($1::varchar[]))
ORDER BY a.planned_date ASC, a.created_at ASC`, ids)
	if err != nil {
		return nil, fmt.Errorf("myplan: activities: %w", err)
	}
	defer rows.Close()
	var out []*activity
	for rows.Next() {
		a := &activity{}
		if err := rows.Scan(&a.id, &a.activityType, &a.status, &a.fy, &a.plannedDate, &a.scheduledDate, &a.createdAt,
			&a.schoolPK, &a.clusterID, &a.staffID, &a.partnerID, &a.delivery, &a.salesforce,
			&a.rescheduleCount, &a.purposeText, &a.purposeType, &a.focus,
			&a.teachersAttended, &a.leadersAttended, &a.others, &a.expected,
			&a.perSchool, &a.teachersPerSchool,
			&a.courseID, &a.courseName, &a.itemID, &a.itemName, &a.itemIsCourse,
			&a.deliveryMode, &a.planningSource, &a.costMissing, &a.pairedVisit,
			&a.iaVerification, &a.ssaExpected, &a.batchID, &a.eventDistrictID,
			&a.actualDelivery, &a.executionStarted, &a.submittedToIA, &a.plReviewed, &a.plannedBefore,
			&a.hasSchool, &a.schoolCode, &a.schoolName, &a.schoolType, &a.schoolDistrictID, &a.schoolDistrictName,
			&a.hasCluster, &a.clusterName, &a.clusterDistrictID, &a.schoolClusterID); err != nil {
			return nil, fmt.Errorf("myplan: activities: %w", err)
		}
		out = append(out, a)
	}
	return out, rows.Err()
}

// schoolID is a row's "school_id": the school's School ID (None when the
// school has none), "" for work at no school.
type schoolID struct {
	value string
	null  bool
}

func (s schoolID) truthy() bool { return !s.null && s.value != "" }

// row is one row of a plan table: the activity_data dict, with the fields
// the post-loop pass adds.
type row struct {
	a                                         *activity
	schoolID                                  schoolID
	schoolName, schoolDistrict                string
	clusterID, clusterName                    string
	isClusterInvited                          bool
	expected                                  *int
	activityTypeLabel                         *string
	visitNumber, trainingNumber, coreProgress string
	purpose, focus, owner                     string
	trainingName, trainingMode                string
	budgetTotal                               *int64
	costNote                                  string
	budgetStatus, verification                string
	statusLabel                               string
	awaitingSSA                               bool

	districtType  string
	salesforceID  string
	plannedBefore *time.Time
	completedOn   *time.Time
	isComplete    bool
}

func (r *row) copy() *row {
	c := *r
	return &c
}

// typeLabel is choice_label(a, "activity_type"): the choice's label, the
// value itself when it is not a choice.
func typeLabel(value string) string {
	if label, ok := rules.Rows.ActivityTypeLabels[value]; ok {
		return label
	}
	return value
}

func isTraining(a *activity) bool { return in(rules.Rows.TrainingTypes, a.activityType) }

func isOnline(a *activity) bool {
	return in(rules.Rows.OnlineTrainingTypes, a.activityType) && str(a.deliveryMode) == rules.Rows.OnlineMode
}

// courseName is training_names.course_name_of.
func courseName(a *activity) string {
	if !isTraining(a) {
		return ""
	}
	if isSet(a.courseID) {
		return str(a.courseName)
	}
	if isSet(a.itemID) && a.itemIsCourse {
		return str(a.itemName)
	}
	return ""
}

// modeOfDelivery is training_names.mode_of_delivery.
func modeOfDelivery(a *activity) string {
	if isOnline(a) {
		return rules.Rows.OnlineTrainingLabel
	}
	if !isTraining(a) {
		return ""
	}
	if isSet(a.schoolPK) {
		return rules.Rows.ModeOfDelivery["in_school"]
	}
	if isSet(a.clusterID) {
		return rules.Rows.ModeOfDelivery["group"]
	}
	return ""
}

// purpose is the row's "purpose": the purpose written, else the visit
// purpose's label, else the activity type's.
func purpose(a *activity) string {
	if isSet(a.purposeText) {
		return *a.purposeText
	}
	if isSet(a.purposeType) {
		if label := rules.Rows.PurposeLabels[*a.purposeType]; label != "" {
			return label
		}
	}
	return typeLabel(a.activityType)
}

// expectedParticipants is who turned up, else who was planned for.
func expectedParticipants(a *activity) *int {
	n := 0
	for _, p := range []*int{a.teachersAttended, a.leadersAttended, a.others} {
		if p != nil {
			n += *p
		}
	}
	if n != 0 {
		return &n
	}
	if a.expected != nil && *a.expected != 0 {
		v := *a.expected
		return &v
	}
	return nil
}

func partnerWork(a *activity) bool {
	return str(a.delivery) == "partner" || isSet(a.partnerID) ||
		a.status == "assigned_to_partner" || a.status == "partner_scheduled"
}

// names are partners_map and users_map.
type names struct {
	partners map[string]string
	users    map[string]*string
}

func (n names) owner(a *activity) string {
	if partnerWork(a) {
		if name, ok := n.partners[str(a.partnerID)]; ok && a.partnerID != nil {
			return name
		}
		return "Partner"
	}
	if a.staffID != nil {
		if name, ok := n.users[*a.staffID]; ok {
			return str(name)
		}
	}
	return "Staff"
}

// readNames is partners_map (live partners) and users_map (every account
// by id, then each live staff profile's account name by the profile's id).
func readNames(ctx context.Context, db schooldirectory.Querier) (names, error) {
	n := names{partners: map[string]string{}, users: map[string]*string{}}
	rows, err := db.Query(ctx, `SELECT id, name FROM partner WHERE deleted_at IS NULL`)
	if err != nil {
		return n, fmt.Errorf("myplan: partners: %w", err)
	}
	for rows.Next() {
		var id, name string
		if err := rows.Scan(&id, &name); err != nil {
			rows.Close()
			return n, err
		}
		n.partners[id] = name
	}
	rows.Close()
	rows, err = db.Query(ctx, `SELECT id, name FROM "user"`)
	if err != nil {
		return n, fmt.Errorf("myplan: users: %w", err)
	}
	for rows.Next() {
		var id string
		var name *string
		if err := rows.Scan(&id, &name); err != nil {
			rows.Close()
			return n, err
		}
		n.users[id] = name
	}
	rows.Close()
	rows, err = db.Query(ctx, `SELECT sp.id, u.name FROM staff_profile sp JOIN "user" u ON u.id = sp.user_id
WHERE sp.deleted_at IS NULL AND u.name IS NOT NULL AND u.name <> ''`)
	if err != nil {
		return n, fmt.Errorf("myplan: staff names: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var id, name string
		if err := rows.Scan(&id, &name); err != nil {
			return n, err
		}
		n.users[id] = &name
	}
	return n, rows.Err()
}

// coreSlots are the Core package's V/T numbers and "n/m Completed", read
// from CoreActivitySlot as the loop reads them.
type coreSlots struct {
	kind     map[string]string
	sequence map[string]*int
	progress map[string]string
}

func slotComplete(status *string) bool {
	s := pyStrip(str(status))
	return in(rules.Plan.CompletedWorkStatuses, toLower(s)) || slices.Contains(spacedCompleted(), toLower(s))
}

func readCoreSlots(ctx context.Context, db schooldirectory.Querier, codes []string) (coreSlots, error) {
	out := coreSlots{kind: map[string]string{}, sequence: map[string]*int{}, progress: map[string]string{}}
	if len(codes) == 0 {
		return out, nil
	}
	rows, err := db.Query(ctx, `SELECT s.activity_id, s.activity_type, s.sequence_number, s.status, p.school_id, p.fy
FROM core_activity_slot s INNER JOIN core_plan p ON p.id = s.core_plan_id WHERE p.school_id = ANY($1)`, codes)
	if err != nil {
		return out, fmt.Errorf("myplan: core slots: %w", err)
	}
	defer rows.Close()
	type plan struct{ school, fy string }
	type slot struct {
		kind string
		seq  string
	}
	planOf := map[string]plan{}
	var order []string
	taken, done := map[plan]map[slot]bool{}, map[plan]map[slot]bool{}
	for rows.Next() {
		var activityID, kind, status, school, fy *string
		var seq *int
		if err := rows.Scan(&activityID, &kind, &seq, &status, &school, &fy); err != nil {
			return out, err
		}
		p := plan{str(school), pyNone(fy)}
		s := slot{str(kind), pyIntNone(seq)}
		packaged := str(kind) == "visit" || str(kind) == "training"
		if packaged {
			if taken[p] == nil {
				taken[p] = map[slot]bool{}
			}
			taken[p][s] = true
		}
		if isSet(activityID) {
			out.kind[*activityID] = str(kind)
			out.sequence[*activityID] = seq
			if _, seen := planOf[*activityID]; !seen {
				order = append(order, *activityID)
			}
			planOf[*activityID] = p
		}
		if slotComplete(status) && packaged {
			if done[p] == nil {
				done[p] = map[slot]bool{}
			}
			done[p][s] = true
		}
	}
	for _, id := range order {
		p := planOf[id]
		out.progress[id] = strconv.Itoa(len(done[p])) + "/" + strconv.Itoa(len(taken[p])) + " Completed"
	}
	return out, rows.Err()
}

func pyNone(p *string) string {
	if p == nil {
		return "\x00None"
	}
	return *p
}

func pyIntNone(p *int) string {
	if p == nil {
		return "None"
	}
	return strconv.Itoa(*p)
}
