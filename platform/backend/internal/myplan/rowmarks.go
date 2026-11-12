package myplan

import (
	"context"
	"fmt"
	"slices"
	"strings"
	"time"
	"unicode"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

func pyStrip(s string) string { return strings.TrimFunc(s, unicode.IsSpace) }

func toLower(s string) string { return strings.ToLower(s) }

// spacedCompleted is the completed statuses written with spaces, which a
// Core slot's status may carry (_COMPLETE_SLOT_STATUSES).
func spacedCompleted() []string {
	out := make([]string, 0, len(rules.Plan.CompletedWorkStatuses))
	for _, s := range rules.Plan.CompletedWorkStatuses {
		out = append(out, strings.ReplaceAll(s, "_", " "))
	}
	return out
}

// day is clock.local_day: the day an instant falls on in Kampala.
func day(t *time.Time) *time.Time {
	if t == nil {
		return nil
	}
	d := t.In(kampala)
	v := time.Date(d.Year(), d.Month(), d.Day(), 0, 0, 0, 0, time.UTC)
	return &v
}

// date is a DATE column's day.
func date(t *time.Time) *time.Time {
	if t == nil {
		return nil
	}
	v := time.Date(t.Year(), t.Month(), t.Day(), 0, 0, 0, 0, time.UTC)
	return &v
}

func before(a, b *time.Time) bool { return a.Before(*b) }

// leadVerifiedIDs is pl_review.services.lead_verified_owner_ids: every id
// (profile and account) of a live staff profile whose account holds a role
// a Programme Lead verifies, or whom a live Programme Lead supervises.
func leadVerifiedIDs(ctx context.Context, db schooldirectory.Querier) (map[string]bool, error) {
	rows, err := db.Query(ctx, `SELECT DISTINCT sp.id, sp.user_id FROM staff_profile sp
LEFT JOIN "user" u ON u.id = sp.user_id
WHERE sp.deleted_at IS NULL AND (u.roles && $1::varchar[] OR EXISTS (
  SELECT 1 FROM staff_supervisor_assignment l
  JOIN staff_profile sup ON sup.id = l.supervisor_id AND sup.deleted_at IS NULL
  JOIN "user" su ON su.id = sup.user_id
  WHERE l.supervisee_id = sp.id AND su.roles @> ARRAY[$2::varchar]))`, rules.Rows.LeadVerifiedRoles, rules.ProgramLeadRole)
	if err != nil {
		return nil, fmt.Errorf("myplan: lead-verified staff: %w", err)
	}
	defer rows.Close()
	out := map[string]bool{}
	for rows.Next() {
		var id string
		var user *string
		if err := rows.Scan(&id, &user); err != nil {
			return nil, err
		}
		out[id] = true
		if isSet(user) {
			out[*user] = true
		}
	}
	return out, rows.Err()
}

// verification is my_plan.services.verification_label's words.
func verification(a *activity, leads map[string]bool) string {
	byLead := str(a.delivery) != "partner" && leads[str(a.staffID)]
	ia := str(a.iaVerification)
	switch {
	case in(rules.Rows.ApprovedStatuses, a.status) || ia == "confirmed":
		if byLead {
			return "PL Approved"
		}
		return "Verified"
	case a.status == "returned_by_pl" || a.status == "returned_by_ia" || ia == "returned":
		return "Returned"
	case byLead:
		return "PL Pending"
	}
	return "IA Pending"
}

// statusLabel is get_activity_status_label_and_class's words.
func statusLabel(a *activity, today time.Time) string {
	planned := date(a.plannedDate)
	switch a.status {
	case "completed", "closed":
		return rules.Rows.CompleteLabel
	case "awaiting_owner_approval":
		return "Awaiting owner approval"
	case "submitted_to_pl", "awaiting_ia_verification", "ia_verified", "accountant_confirmed":
		if !isSet(a.salesforce) {
			return "Activity ID Missing"
		}
		return rules.Rows.CompleteLabel
	case "returned", "returned_by_pl", "returned_by_ia":
		return "Returned for Correction"
	}
	if planned != nil && planned.Equal(today) {
		return "Due Today"
	}
	if a.rescheduleCount > 0 {
		return "Rescheduled"
	}
	if planned != nil && today.Before(*planned) && !planned.After(today.AddDate(0, 0, 7)) {
		return "This Week"
	}
	return "Scheduled"
}

func officerCompleted(status string) bool { return in(rules.Plan.OfficerCompletedStatuses, status) }

// awaitingSSA is visit_scores.awaiting_scores: completed SSA visits whose
// school has no SSA holding the visit's year.
func awaitingSSA(ctx context.Context, db schooldirectory.Querier, acts []*activity) (map[string]bool, error) {
	var waiting []*activity
	var schools, years []string
	for _, a := range acts {
		collects := isSet(a.schoolPK) && (a.ssaExpected || str(a.purposeType) == "ssa_support" || in(rules.Rows.PartnerSSASupportTypes, a.activityType))
		if officerCompleted(a.status) && collects && !in(rules.Rows.NotAssessedTypes, str(a.schoolType)) {
			waiting = append(waiting, a)
			schools = append(schools, *a.schoolPK)
			years = append(years, pyNone(a.fy))
		}
	}
	out := map[string]bool{}
	if len(waiting) == 0 {
		return out, nil
	}
	rows, err := db.Query(ctx, `SELECT school_id, fy FROM ssa_record
WHERE school_id = ANY($1) AND fy = ANY($2) AND deleted_at IS NULL AND verification_status = ANY($3)`,
		schools, years, rules.Rows.SSAHoldingStatuses)
	if err != nil {
		return nil, fmt.Errorf("myplan: SSA records: %w", err)
	}
	defer rows.Close()
	held := map[[2]string]bool{}
	for rows.Next() {
		var school, fy *string
		if err := rows.Scan(&school, &fy); err != nil {
			return nil, err
		}
		held[[2]string{str(school), pyNone(fy)}] = true
	}
	for _, a := range waiting {
		if !held[[2]string{*a.schoolPK, pyNone(a.fy)}] {
			out[a.id] = true
		}
	}
	return out, rows.Err()
}

// completion is completion_columns.completion_columns for one activity:
// the Salesforce ID, whether its form is in, the day it was done before
// its planned day, the day it was done and the day it was planned before.
type completion struct {
	salesforce    string
	evidenceOK    bool
	earlyOn       *time.Time
	deliveredOn   *time.Time
	plannedBefore *time.Time
}

// planDay is completion_columns.plan_day.
func planDay(planned, scheduled *time.Time) *time.Time {
	if planned != nil {
		return date(planned)
	}
	return day(scheduled)
}

// evidenceKinds is _records' evidence: the kinds of form uploaded, and not
// quarantined, for the activities asked for an upload (a partner's work),
// read through gateway_read.activity_evidence_kind (evidence_roles.sql): the
// gateway may not read evidence_record itself.
func evidenceKinds(ctx context.Context, db schooldirectory.Querier, acts []*activity) (map[string]map[string]bool, error) {
	var asked []string
	for _, a := range acts {
		if str(a.delivery) == "partner" {
			asked = append(asked, a.id)
		}
	}
	out := map[string]map[string]bool{}
	if len(asked) == 0 {
		return out, nil
	}
	rows, err := db.Query(ctx, `SELECT activity_id, kind FROM gateway_read.activity_evidence_kind WHERE activity_id = ANY($1)`, asked)
	if err != nil {
		return nil, fmt.Errorf("myplan: reading the forms uploaded: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var id, kind string
		if err := rows.Scan(&id, &kind); err != nil {
			return nil, err
		}
		if out[id] == nil {
			out[id] = map[string]bool{}
		}
		out[id][kind] = true
	}
	return out, rows.Err()
}

// expectedEvidence is completion_columns.expected_evidence's kind: an
// attendance form for a training or meeting, a visit form for the rest.
func expectedEvidence(activityType string) string {
	if slices.Contains(rules.Rows.EvidenceAttendanceTypes, activityType) {
		return rules.Rows.EvidenceAttendanceKind
	}
	return rules.Rows.EvidenceVisitKind
}

func completions(acts []*activity, today time.Time, kinds map[string]map[string]bool) map[string]completion {
	out := map[string]completion{}
	for _, a := range acts {
		c := completion{salesforce: pyStrip(str(a.salesforce)), evidenceOK: true, plannedBefore: date(a.plannedBefore)}
		c.deliveredOn = date(a.actualDelivery)
		if c.deliveredOn == nil {
			c.deliveredOn = day(a.executionStarted)
		}
		planned, scheduled := a.plannedDate, a.scheduledDate
		if a.plannedBefore != nil {
			planned, scheduled = a.plannedBefore, nil
		}
		finishedBy := today
		for _, d := range []*time.Time{day(a.submittedToIA), day(a.plReviewed)} {
			if d != nil && d.Before(finishedBy) {
				finishedBy = *d
			}
		}
		if p := planDay(planned, scheduled); p != nil {
			if actual := date(a.actualDelivery); actual != nil {
				if before(actual, p) {
					c.earlyOn = actual
				}
			} else if started := day(a.executionStarted); started != nil && finishedBy.Before(*p) {
				c.earlyOn = started
			}
		}
		// A partner's work is complete only with its form uploaded
		// (completion_columns: evidence_ok for the work asked for an upload).
		if str(a.delivery) == "partner" {
			c.evidenceOK = kinds[a.id][expectedEvidence(a.activityType)]
		}
		out[a.id] = c
	}
	return out
}

// pairNotes is pair_costing.pair_cost_notes over the page's activities.
func pairNotes(ctx context.Context, db schooldirectory.Querier, acts []*activity, lines costLines) (map[string]string, error) {
	r := rules.Rows
	byID := map[string]*activity{}
	for _, a := range acts {
		byID[a.id] = a
	}
	has := func(id string) bool { return len(lines[id]) > 0 }
	var visitIDs []string
	for _, a := range acts {
		if a.activityType == "in_school_training" && isSet(a.pairedVisit) {
			visitIDs = append(visitIDs, *a.pairedVisit)
		}
	}
	live := map[string]bool{}
	if len(visitIDs) > 0 {
		ids, err := idsWhere(ctx, db, `SELECT id FROM activity WHERE id = ANY($1) AND deleted_at IS NULL
AND NOT COALESCE(status = ANY($2), false)`, visitIDs, r.CompanionGoneStatuses)
		if err != nil {
			return nil, err
		}
		for _, id := range ids {
			live[id] = true
		}
	}
	type pair struct{ training, visit string }
	pairs := map[pair]bool{}
	paired := map[string]bool{}
	for _, a := range acts {
		if a.activityType == "in_school_training" && isSet(a.pairedVisit) && live[*a.pairedVisit] {
			pairs[pair{a.id, *a.pairedVisit}] = true
			paired[*a.pairedVisit] = true
		}
	}
	var bare []string
	for _, a := range acts {
		if a.activityType == "school_visit" && !paired[a.id] && !has(a.id) {
			bare = append(bare, a.id)
		}
	}
	if len(bare) > 0 {
		rows, err := db.Query(ctx, `SELECT paired_school_visit_id, id FROM activity WHERE paired_school_visit_id = ANY($1)
AND activity_type = 'in_school_training' AND deleted_at IS NULL AND NOT COALESCE(status = ANY($2), false)`, bare, r.CompanionGoneStatuses)
		if err != nil {
			return nil, fmt.Errorf("myplan: pair trainings: %w", err)
		}
		for rows.Next() {
			var visit, training string
			if err := rows.Scan(&visit, &training); err != nil {
				rows.Close()
				return nil, err
			}
			pairs[pair{training, visit}] = true
		}
		rows.Close()
		if err := rows.Err(); err != nil {
			return nil, err
		}
	}
	online := map[string]string{}
	for _, a := range acts {
		if isOnline(a) && !has(a.id) {
			online[a.id] = r.OnlineFreeNote
		}
	}
	if len(pairs) == 0 {
		return online, nil
	}
	priced := map[string]bool{}
	for _, a := range acts {
		if !a.costMissing && has(a.id) {
			priced[a.id] = true
		}
	}
	var outside []string
	for p := range pairs {
		for _, half := range []string{p.training, p.visit} {
			if byID[half] == nil && !in(outside, half) {
				outside = append(outside, half)
			}
		}
	}
	if len(outside) > 0 {
		ids, err := idsWhere(ctx, db, `SELECT a.id FROM activity a WHERE a.id = ANY($1) AND a.deleted_at IS NULL
AND a.cost_missing = false AND NOT COALESCE(a.status = ANY($2), false)
AND EXISTS (SELECT 1 FROM activity_schedule_cost_line l WHERE l.activity_id = a.id)`, outside, r.CompanionGoneStatuses)
		if err != nil {
			return nil, err
		}
		for _, id := range ids {
			priced[id] = true
		}
	}
	notes := map[string]string{}
	for p := range pairs {
		training, visit := byID[p.training], byID[p.visit]
		switch {
		case training != nil && !has(p.training) && priced[p.visit]:
			notes[p.training] = r.CapturedInVisitNote
		case visit != nil && !has(p.visit) && priced[p.training]:
			notes[p.visit] = r.CapturedInTrainingNote
		}
	}
	for id, note := range online {
		notes[id] = note
	}
	return notes, nil
}

func idsWhere(ctx context.Context, db schooldirectory.Querier, sql string, args ...any) ([]string, error) {
	rows, err := db.Query(ctx, sql, args...)
	if err != nil {
		return nil, fmt.Errorf("myplan: %w", err)
	}
	defer rows.Close()
	var out []string
	for rows.Next() {
		var id string
		if err := rows.Scan(&id); err != nil {
			return nil, err
		}
		out = append(out, id)
	}
	return out, rows.Err()
}
