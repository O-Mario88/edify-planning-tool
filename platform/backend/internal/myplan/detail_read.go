package myplan

import (
	"context"
	"errors"
	"fmt"
	"time"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/calendarpage"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schoolprofile"
)

// ErrDetailHandOn is an activity's detail drawer Go does not draw: a part
// of it is not ported, or the existing application refuses the reader
// (it writes an audit row then, which a read in Go never does).
var ErrDetailHandOn = errors.New("myplan: the activity drawer needs a part Go does not draw yet")

// handOn is ErrDetailHandOn with what Go does not draw.
func handOn(reason string) error { return fmt.Errorf("%w: %s", ErrDetailHandOn, reason) }

// detailActivity is what activity_detail_view and its template read of one
// activity, its school and its cluster.
type detailActivity struct {
	id, kind, status                      string
	planned, scheduled, end               *time.Time
	schoolID, clusterID, staffID, monitor string
	delivery, salesforce                  string
	reschedules                           int
	purpose, outcome, focus               string
	ia                                    *string
	ssaAlignment, facilitator, partnerID  string
	meetingKind, nameSnapshot, batchID    string
	costMissing                           bool
	pairedVisit                           string
	// The training it delivers: its course, else its catalogue item when
	// that is a course, and the course name a meeting was planned under.
	courseID, courseName, itemID, itemName string
	itemIsCourse                           bool
	plannedCourseName                      string
	// The SSA verdict's words (plan_alignment.verdict_display).
	verdictReason, deviationReason string

	hasSchool                      bool
	schoolName, schoolOwner        string
	schoolCode                     *string
	hasCluster, clusterLive        bool
	clusterName, clusterLead       string
	clusterDistrict, clusterRegion string
	inCountry                      bool
}

// readDetailActivity reads the activity, not deleted; nil when there is none.
// inCountry is whether it is held in the reader's country, for a country
// reader bounded to one.
func readDetailActivity(ctx context.Context, db schooldirectory.Querier, id string, scope schooldirectory.Scope) (*detailActivity, error) {
	args := []any{id}
	inCountry := "false"
	if scope.CountryScope && scope.Country != "" {
		args = append(args, scope.CountryIDs())
		inCountry = schoolprofile.ActivityInCountry(len(args))
	}
	a := &detailActivity{}
	err := db.QueryRow(ctx, `
SELECT a.id, a.activity_type, COALESCE(a.status, ''), a.planned_date, a.scheduled_date, a.end_date,
  COALESCE(a.school_id, ''), COALESCE(a.cluster_id, ''), COALESCE(a.responsible_staff_id, ''),
  COALESCE(a.monitored_by_staff_id, ''), COALESCE(a.delivery_type, ''), COALESCE(a.salesforce_activity_id, ''),
  COALESCE(a.reschedule_count, 0), COALESCE(a.activity_purpose_text, ''), COALESCE(a.expected_outcome, ''),
  COALESCE(a.focus_intervention, ''), a.ia_verification_status, COALESCE(a.ssa_alignment, ''),
  COALESCE(a.facilitating_partner_id, ''), COALESCE(a.assigned_partner_id, ''), COALESCE(a.meeting_kind, ''),
  COALESCE(a.activity_name_snapshot, ''), COALESCE(a.daily_visit_batch_id, ''), COALESCE(a.cost_missing, false),
  COALESCE(a.paired_school_visit_id, ''),
  COALESCE(a.training_course_id, ''), COALESCE(tc.display_name, ''), COALESCE(a.catalogue_item_id, ''),
  COALESCE(ci.display_name, ''), COALESCE(ci.is_training_course, false),
  COALESCE(CASE WHEN jsonb_typeof(a.recommendation_source::jsonb) = 'object' THEN a.recommendation_source::jsonb ->> 'trainingCourseName' END, ''),
  COALESCE(NULLIF(CASE WHEN jsonb_typeof(a.recommendation_source::jsonb -> 'ssa') = 'object' THEN a.recommendation_source::jsonb -> 'ssa' ->> 'reason' END, ''), a.recommendation_reason, ''),
  COALESCE(a.ssa_deviation_reason, ''),
  s.id IS NOT NULL, COALESCE(s.name, ''), COALESCE(s.account_owner_id, ''), s.school_id,
  cl.id IS NOT NULL, cl.id IS NOT NULL AND cl.deleted_at IS NULL, COALESCE(cl.name, ''),
  COALESCE(cl.responsible_staff_id, ''), COALESCE(cl.district_id, ''), COALESCE(cl.region_id, ''), `+inCountry+`
FROM activity a
LEFT JOIN school s ON s.id = a.school_id
LEFT JOIN cluster cl ON cl.id = a.cluster_id
LEFT JOIN activity_catalogue_item tc ON tc.id = a.training_course_id
LEFT JOIN activity_catalogue_item ci ON ci.id = a.catalogue_item_id
WHERE a.id = $1 AND a.deleted_at IS NULL`, args...).Scan(
		&a.id, &a.kind, &a.status, &a.planned, &a.scheduled, &a.end,
		&a.schoolID, &a.clusterID, &a.staffID, &a.monitor, &a.delivery, &a.salesforce,
		&a.reschedules, &a.purpose, &a.outcome, &a.focus, &a.ia, &a.ssaAlignment,
		&a.facilitator, &a.partnerID, &a.meetingKind, &a.nameSnapshot, &a.batchID, &a.costMissing,
		&a.pairedVisit,
		&a.courseID, &a.courseName, &a.itemID, &a.itemName, &a.itemIsCourse, &a.plannedCourseName,
		&a.verdictReason, &a.deviationReason,
		&a.hasSchool, &a.schoolName, &a.schoolOwner, &a.schoolCode,
		&a.hasCluster, &a.clusterLive, &a.clusterName, &a.clusterLead, &a.clusterDistrict, &a.clusterRegion, &a.inCountry)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, nil
	}
	if err != nil {
		return nil, fmt.Errorf("myplan: reading the activity: %w", err)
	}
	return a, nil
}

// detailReaderHandedOn are the readers whose drawer Go does not decide:
// a partner's team (member_scope and the partner's own money), and the
// Country Director and Regional Vice President, whom can_view_record
// refuses raw activities (an audit row Go never writes on a read).
var detailReaderHandedOn = []string{"PartnerAdmin", "PartnerFieldOfficer", "CountryDirector", "RegionalVicePresident"}

// mayView is RolePermissionService.can_view_record for the activity.
func mayView(ctx context.Context, db schooldirectory.Querier, p auth.Principal, scope schooldirectory.Scope, a *detailActivity, now time.Time) (bool, error) {
	if p.ActiveRole == "Admin" {
		return true, nil
	}
	if scope.CountryScope {
		// The country lens: a reader bounded to a country opens its own
		// country's work (docs/migration/80, §21).
		return scope.Country == "" || a.inCountry, nil
	}
	return calendarpage.CanViewActivity(ctx, db, p, scope, calendarpage.ViewedActivity{
		StaffID: a.staffID, MonitorID: a.monitor, SchoolID: a.schoolID, ClusterID: a.clusterID,
		ClusterLead: a.clusterLead, ClusterDistrict: a.clusterDistrict, ClusterRegion: a.clusterRegion,
		HasCluster: a.hasCluster, ClusterLive: a.clusterLive,
	}, now)
}

// accountantReaches is evidence.services._assert_activity_in_scope for the
// Accountant, whose evidence reach is narrower than the records it reads:
// work with money moving on it. The drawer lists the evidence, so the
// existing application refuses the rest.
func accountantReaches(ctx context.Context, db schooldirectory.Querier, id string) (bool, error) {
	var reaches bool
	err := db.QueryRow(ctx, `SELECT COALESCE(a.payment_status, '') NOT IN ('', 'none')
  OR EXISTS (SELECT 1 FROM advance_request r WHERE r.activity_id = a.id)
FROM activity a WHERE a.id = $1`, id).Scan(&reaches)
	if err != nil {
		return false, fmt.Errorf("myplan: reading the activity's money: %w", err)
	}
	return reaches, nil
}

// mayCancel is the view's can_cancel: live work (group_actions.may_tick)
// the reader may run (profile_activities._may_run).
func mayCancel(ctx context.Context, db schooldirectory.Querier, p auth.Principal, scope schooldirectory.Scope, a *detailActivity) (bool, error) {
	if in(rules.Detail.UntickableStatuses, a.status) {
		return false, nil
	}
	return schoolprofile.MayRun(ctx, db, p, scope, schoolprofile.RunnableActivity{
		StaffID: a.staffID, MonitorID: a.monitor, SchoolID: a.schoolID, SchoolOwner: a.schoolOwner,
		HasSchool: a.hasSchool, ClusterID: a.clusterID, ClusterDistrict: a.clusterDistrict,
		ClusterLead: a.clusterLead, ClusterLive: a.clusterLive, InCountry: a.inCountry,
	})
}

// staffName is the view's responsible_staff_name: the account by its id or
// its staff profile's, "Unknown Staff" when there is none. ok is false when
// both name somebody (User.objects.get fails there).
func staffName(ctx context.Context, db schooldirectory.Querier, id string) (string, bool, error) {
	if id == "" {
		return "Unknown Staff", true, nil
	}
	rows, err := db.Query(ctx, `SELECT COALESCE(u.name, '') FROM "user" u
WHERE u.id = $1 OR u.id IN (SELECT sp.user_id FROM staff_profile sp WHERE sp.id = $1)`, id)
	if err != nil {
		return "", false, fmt.Errorf("myplan: reading the responsible officer: %w", err)
	}
	names, err := pgx.CollectRows(rows, pgx.RowTo[string])
	if err != nil {
		return "", false, fmt.Errorf("myplan: reading the responsible officer: %w", err)
	}
	switch len(names) {
	case 0:
		return "Unknown Staff", true, nil
	case 1:
		return names[0], true, nil
	}
	return "", false, nil
}

// isTraining is training_ceilings.is_training: a training, or a cluster
// meeting held as one.
func (a *detailActivity) isTraining() bool {
	d := rules.Detail
	return in(d.TrainingTypes, a.kind) || (in(d.MeetingTypes, a.kind) && a.meetingKind == d.TrainingMeetingKind)
}

// trainingFact is the Training fact (_training_profile_context): the
// course it delivers, by the name it was scheduled under, and how it is
// delivered; "" for work that is not a training.
func (a *detailActivity) trainingFact() string {
	if !a.isTraining() {
		return ""
	}
	name := ""
	// course_id_of, then a.training_course or a.catalogue_item.
	if a.courseID != "" || (a.itemID != "" && a.itemIsCourse) {
		course := a.itemName
		if a.courseID != "" {
			course = a.courseName
		}
		if in(rules.Detail.MeetingTypes, a.kind) {
			name = orText(a.plannedCourseName, course)
		} else {
			name = orText(a.nameSnapshot, course)
		}
	}
	fact := orText(name, "No training named yet")
	delivery := ""
	switch {
	case a.schoolID != "":
		delivery = rules.Detail.DeliveryLabels["school"]
	case a.clusterID != "":
		delivery = rules.Detail.DeliveryLabels["cluster"]
	}
	if delivery != "" {
		fact += " (" + delivery + ")"
	}
	return fact
}

// mayChangeFacilitator is the view's can_change_facilitator: a staff-run
// training or meeting still to be held (the reader is not a partner).
func (a *detailActivity) mayChangeFacilitator() bool {
	return in(rules.Detail.FacilitatorTypes, a.kind) && a.delivery == "staff" && in(rules.Tables.FacilitatorEditableStatuses, a.status)
}

// facilitatedBy is facilitation.facilitated_by_display: "Staff", or the
// partner who facilitates it.
func facilitatedBy(ctx context.Context, db schooldirectory.Querier, a *detailActivity) (string, error) {
	partner := a.facilitator
	if partner == "" && a.delivery == "partner" {
		partner = a.partnerID
	}
	if partner == "" {
		return rules.Detail.StaffFacilitatorLabel, nil
	}
	var name *string
	err := db.QueryRow(ctx, `SELECT name FROM partner WHERE id = $1`, partner).Scan(&name)
	if err != nil && !errors.Is(err, pgx.ErrNoRows) {
		return "", fmt.Errorf("myplan: reading the facilitating partner: %w", err)
	}
	if name == nil || *name == "" {
		return "Partner", nil
	}
	return "Partner (" + *name + ")", nil
}

// hasEvidence is whether evidence uploaded before uploads were switched off
// still sits on the activity: the drawer lists it, which Go does not draw.
func hasEvidence(ctx context.Context, db schooldirectory.Querier, id string) (bool, error) {
	var any bool
	err := db.QueryRow(ctx, `SELECT EXISTS (SELECT 1 FROM evidence_record WHERE activity_id = $1 AND NOT COALESCE(quarantined, false))`, id).Scan(&any)
	if err != nil {
		return false, fmt.Errorf("myplan: reading the activity's evidence: %w", err)
	}
	return any, nil
}
