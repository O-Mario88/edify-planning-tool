package plreview

import (
	"context"
	"fmt"
	"slices"
	"strings"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

const (
	visitForm      = "visit_form"
	attendanceForm = "attendance_form"
)

// ReviewDetail is the rest of the completion the Verify form shows, read only
// after Reviewable has settled that this reviewer may decide it.
type ReviewDetail struct {
	Intervention, SSABasis, SSADeparture, Attendance string
	Purpose, Outcome, Observations, FollowUp         string
	SalesforceID                                     string
	SalesforceKind                                   string // "training", "visit", or "" for work Salesforce does not record
	UploadedForm                                     string // the form's name, "" when nothing is uploaded
}

// ReturnReasons is apps.activities.return_notes.COMMON_REASONS.
func ReturnReasons() []string { return slices.Clone(rules.ReturnReasons) }

// ReadReviewDetail is what _review_facts and pl_review_drawer read.
func ReadReviewDetail(ctx context.Context, q schooldirectory.Querier, activityID string) (ReviewDetail, error) {
	var d ReviewDetail
	var c completion
	var intervention, alignment, reason, salesforceID, recordType, activityType, profile string
	var uploaded bool
	err := q.QueryRow(ctx, `
SELECT COALESCE(a.focus_intervention, ''), COALESCE(a.ssa_alignment, ''),
  COALESCE(NULLIF(a.recommendation_source->'ssa'->>'reason', ''), a.recommendation_reason, ''),
  COALESCE(a.ssa_deviation_reason, ''),
  COALESCE(a.teachers_attended, 0), COALESCE(a.leaders_attended, 0), COALESCE(a.other_participants, 0),
  CASE WHEN a.cluster_id IS NOT NULL AND a.school_id IS NULL THEN COALESCE(cardinality(a.attended_school_ids), 0) ELSE 0 END,
  COALESCE(a.activity_purpose_text, ''), COALESCE(a.actual_outcome, ''), COALESCE(a.actual_observations, ''),
  COALESCE(a.follow_up_note, ''), COALESCE(a.salesforce_activity_id, ''), COALESCE(a.salesforce_record_type_snapshot, ''),
  COALESCE(a.activity_type, ''), COALESCE(a.evidence_profile_snapshot, ''),
  EXISTS (SELECT 1 FROM evidence_record e WHERE e.activity_id = a.id AND NOT e.quarantined)
FROM activity a WHERE a.id = $1 AND a.deleted_at IS NULL`, activityID).Scan(
		&intervention, &alignment, &reason, &d.SSADeparture,
		&c.Teachers, &c.Leaders, &c.Others, &c.AttendedSchools,
		&d.Purpose, &d.Outcome, &d.Observations, &d.FollowUp, &salesforceID, &recordType,
		&activityType, &profile, &uploaded)
	if err != nil {
		return ReviewDetail{}, fmt.Errorf("plreview: reading the completion's detail: %w", err)
	}
	d.Intervention = rules.InterventionLabels[intervention]
	d.SSABasis = ssaBasis(alignment, reason)
	if alignment == "" {
		d.SSADeparture = ""
	}
	d.Attendance = attendance(c)
	d.SalesforceID = strings.TrimSpace(salesforceID)
	d.SalesforceKind = salesforceKind(recordType, activityType)
	if uploaded {
		d.UploadedForm = uploadedFormName(profile, activityType)
	}
	return d, nil
}

// ssaBasis is the "SSA basis" line of _ssa_basis_facts: nothing when the plan
// carries no verdict.
func ssaBasis(alignment, reason string) string {
	if alignment == "" {
		return ""
	}
	label, ok := rules.SSAAlignmentLabels[alignment]
	if !ok {
		label = alignment
	}
	return strings.TrimSpace(label + ". " + reason)
}

// salesforceKind is apps.activities.services.sf_kind_for_activity: the ID the
// completion stands on, "" for work Salesforce does not record.
func salesforceKind(recordType, activityType string) string {
	configured := strings.ToUpper(recordType)
	switch {
	case slices.Contains(rules.NoSalesforceRecordTypes, configured):
		return ""
	case configured == "TRAINING":
		return "training"
	case configured == "VISIT" || configured == "SSA_DATA_GATHERING":
		return "visit"
	case slices.Contains(rules.SalesforceTrainingKinds, activityType):
		return "training"
	}
	return "visit"
}

// uploadedFormName is form_document.form_name: the governed form the profile
// requires, else the activity type's, else the one its type is completed with.
func uploadedFormName(profile, activityType string) string {
	kind, ok := rules.ProfileForms[profile]
	if !ok {
		kind = rules.TypeForms[activityType]
	}
	if kind == "" {
		kind = visitForm
		if slices.Contains(rules.AttendanceTypes, activityType) {
			kind = attendanceForm
		}
	}
	return rules.FormNames[kind]
}
