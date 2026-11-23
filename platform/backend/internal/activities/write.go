package activities

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"sort"
	"strconv"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/audit"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/cuid"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// activityRow is the activity as `_create`, apply_catalogue_snapshot,
// plan_alignment.stamp and the day's join leave it (27.6).
type activityRow struct {
	id, activityType, fy, quarter, purpose, schoolID, responsible string
	scheduled, now                                                time.Time
	plannedDate                                                   time.Time
	plannedMonth, plannedWeek                                     int
	goal, outcome, deviation                                      string
	collects                                                      bool
	focus                                                         string
	item                                                          item
	version                                                       int
	reason                                                        string
	source                                                        map[string]any
	alignment                                                     string
	sourceSSA                                                     *ssaRecord
	sourceScore                                                   *float64
	sourceBand                                                    string
	batchID                                                       string
	recommendationID                                              string
	// The In-school Training pair (docs/migration/32): the course a
	// training delivers, the name it is saved under, and the visit beside it.
	trainingCourseID, nameSnapshot, pairedVisitID string
	// A cluster session (docs/migration/38): its planning source and
	// context ("school_planning" / "school" when blank), and its cluster
	// and head count.
	planningSource, contextType string
	group                       *groupColumns
	// A cluster meeting's kind (docs/migration/49); blank for other work.
	meetingKind string
	// A Training Follow Up's session and its supporting interventions.
	followUpOf string
	secondary  []string
	// A visit request: who decides it, and why the requester needs to go.
	approvalOwner, justification string
	// noOutcomeField: the form that made it asks for no expected outcome.
	noOutcomeField bool
}

// outcomeValue is the expected outcome, NULL for a form that has no such field.
func (r activityRow) outcomeValue() any {
	if r.noOutcomeField {
		return nil
	}
	return r.outcome
}

// isRequest is whether the row waits for the school owner's decision.
func (r activityRow) isRequest() bool { return r.approvalOwner != "" }

// status is the row's first status.
func (r activityRow) status() string {
	if r.isRequest() {
		return awaitingOwnerApproval
	}
	return "scheduled"
}

// groupColumns are the cluster session's own columns (_create 3371–3442).
// A material of 0 is stored as NULL ("or None").
type groupColumns struct {
	clusterID                                 string
	expected, perSchool, schoolCount, invited int
	teachers, leaders, other                  int
	printing, photocopyPages, photocopyCopies int
	// Delivered online (docs/migration/48): free, in no day.
	online bool
}

func (r activityRow) planning() (string, string) {
	if r.planningSource == "" {
		if in(corePlanningTypes, r.activityType) {
			return "core_planning", "school"
		}
		return "school_planning", "school"
	}
	return r.planningSource, r.contextType
}

func zeroAsNull(n int) any {
	if n == 0 {
		return nil
	}
	return n
}

// groupFields are the session's columns by name, for the insert and the
// day check; none for a school's work.
func (r activityRow) groupFields() []struct {
	name  string
	value any
} {
	g := r.group
	if g == nil {
		return nil
	}
	fields := []struct {
		name  string
		value any
	}{
		{"cluster_id", g.clusterID}, {"expected_participants", g.expected}, {"participants_per_school", g.perSchool},
		{"cluster_school_count_snapshot", g.schoolCount}, {"schools_invited", g.invited},
		{"teachers_per_school", g.teachers}, {"leaders_per_school", g.leaders}, {"other_per_school", g.other},
		{"printing_pages", zeroAsNull(g.printing)}, {"photocopy_pages", zeroAsNull(g.photocopyPages)},
		{"photocopy_copies", zeroAsNull(g.photocopyCopies)},
	}
	if g.online {
		fields = append(fields, struct {
			name  string
			value any
		}{"programme_delivery_mode", onlineDelivery})
	}
	return fields
}

// name is the activity_name_snapshot: the item's, or the course's for a
// training (_create 3471–3478).
func (r activityRow) name() string {
	if r.nameSnapshot != "" {
		return r.nameSnapshot
	}
	return r.item.DisplayName
}

type rowInput struct {
	now, day                           time.Time
	fy, quarter, activityType, purpose string
	school                             school
	responsible                        string
	item                               item
	version                            int
	goal, outcome, deviation           string
	collects                           bool
	focus, reason                      string
	source                             map[string]any
	need                               schoolNeed
	evidence                           evidence
	// A Training Follow Up's session, and the supporting interventions it
	// carries over.
	followUpOf string
	secondary  []string
	// A visit request: who decides it, and why the requester needs to go.
	approvalOwner, justification string
}

func newRow(in rowInput) activityRow {
	r := activityRow{
		id: cuid.New(), activityType: in.activityType, fy: in.fy, quarter: in.quarter, purpose: in.purpose,
		schoolID: in.school.ID, responsible: in.responsible, scheduled: in.day, now: in.now,
		plannedDate: in.day, plannedMonth: int(in.day.Month()), plannedWeek: min(5, (in.day.Day()-1)/7+1),
		goal: strings.TrimSpace(in.goal), outcome: strings.TrimSpace(in.outcome),
		deviation: truncateRunes(strings.TrimSpace(in.deviation), 2000), collects: in.collects,
		focus: in.focus, item: in.item, version: in.version, reason: in.reason,
		alignment: in.evidence.Alignment, sourceSSA: in.need.Record,
		followUpOf: in.followUpOf, secondary: in.secondary,
		approvalOwner: in.approvalOwner, justification: in.justification,
	}
	// The snapshot's SSA score for the focus (apply_catalogue_snapshot).
	if r.sourceSSA != nil && r.focus != "" {
		for _, s := range r.sourceSSA.Scores {
			if s.Intervention == r.focus && s.Score != nil {
				score := *s.Score
				r.sourceScore = &score
				r.sourceBand, _ = schooldirectory.SSABand(score)
				break
			}
		}
	}
	// The stamp's verdict on the source (plan_alignment.stamp).
	ssa := map[string]any{}
	for k, v := range in.evidence.Data {
		ssa[k] = v
	}
	ssa["reason"] = reasonFor(in.evidence)
	if r.deviation != "" {
		ssa["deviationReason"] = r.deviation
	}
	source := map[string]any{}
	for k, v := range in.source {
		source[k] = v
	}
	source["ssa"] = ssa
	r.source = source
	return r
}

func (r activityRow) salesforceType() any {
	switch r.item.SalesforceRecordType {
	case "TRAINING":
		return "training"
	case "VISIT":
		return "visit"
	}
	return nil
}

// probe is the activity as the day check plays it (gateway_relay.PROBE_FIELDS).
func (r activityRow) probe() map[string]any {
	source, context := r.planning()
	probe := map[string]any{
		"activity_type": r.activityType, "fy": r.fy, "quarter": r.quarter, "delivery_type": "staff",
		"executor_type": "staff", "status": "scheduled", "school_id": r.schoolID,
		"responsible_staff_id": r.responsible, "scheduled_date": r.scheduled.Format(time.RFC3339),
		"planned_date": r.plannedDate.Format(time.DateOnly), "planned_month": r.plannedMonth,
		"planned_week": r.plannedWeek, "purpose_type": r.purpose, "purpose_intervention": optString(r.focus),
		"focus_intervention": optString(r.focus), "activity_purpose_text": r.goal, "expected_outcome": r.outcome,
		"ssa_collection_expected": r.collects, "salesforce_activity_type": r.salesforceType(),
		"catalogue_item_id": r.item.ID, "catalogue_version": r.version,
		"activity_name_snapshot": r.item.DisplayName, "activity_type_snapshot": r.item.ActivityType,
		"delivery_method_snapshot": r.item.DeliveryMethod, "evidence_profile_snapshot": optString(r.item.EvidenceProfile),
		"costing_profile_snapshot":        optString(r.item.CostingProfile),
		"salesforce_record_type_snapshot": optString(r.item.SalesforceRecordType),
		"planning_source":                 source, "activity_context_type": context,
	}
	if r.group != nil {
		probe["school_id"] = nil
		for _, f := range r.groupFields() {
			probe[f.name] = f.value
		}
	}
	return probe
}

// write is `_create`'s transaction (3207–3561): the school's lock, the
// entitlement again, the duplicate tests, the row, the recommendation it
// answers, the day it joins and the costs to follow. It answers the
// costs-to-follow row's id.
func (s *Service) write(ctx context.Context, pl *plan) (int64, error) {
	tx, err := s.db.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite, IsoLevel: pgx.ReadCommitted})
	if err != nil {
		return 0, fmt.Errorf("activities: opening the save: %w", err)
	}
	defer func() { _ = tx.Rollback(ctx) }()

	if _, err := tx.Exec(ctx, `SELECT gateway_lock.lock_school($1)`, pl.school.ID); err != nil {
		return 0, fmt.Errorf("activities: locking the school: %w", err)
	}
	if pl.row.isRequest() {
		if err := requestEntitlement(pl.school, pl.row.activityType); err != nil {
			return 0, err
		}
	} else if err := entitlement(ctx, tx, pl.school, pl.row.activityType, pl.row.purpose, pl.row.fy, pl.now); err != nil {
		return 0, err
	}
	if pl.core != nil && pl.core.route == corePackageTraining {
		if err := coreTrainingSideOpen(ctx, tx, pl.school, *pl.core.course, pl.row.fy, pl.now); err != nil {
			return 0, err
		}
	}
	if pl.ceilingCourse != "" {
		set, err := ceilingSet(ctx, tx, pl.row.responsible, pl.ceilingCourse, pl.row.fy)
		if err != nil {
			return 0, err
		}
		if set {
			return 0, handOn("a training ceiling is set for the course")
		}
	}
	if err := duplicates(ctx, tx, pl); err != nil {
		return 0, err
	}
	// apply_catalogue_snapshot refuses a named focus once the row is made,
	// and the save's transaction takes the row back.
	if !canonicalFocus(pl.row.focus) {
		return 0, refuse("Choose a valid canonical SSA intervention.")
	}
	if pl.interventionRefusal != "" {
		return 0, refuse("%s", pl.interventionRefusal)
	}
	// The day's refusal is met once the visit joins it (attach, then
	// _assert_days_can_follow).
	if pl.verdict.Refusal != "" {
		return 0, &Refusal{Message: pl.verdict.Refusal}
	}
	// A request joins no day and keeps no cost until it is approved.
	if !pl.row.isRequest() {
		batchID, _, err := s.joinDay(ctx, tx, pl)
		if err != nil {
			return 0, err
		}
		pl.row.batchID = batchID
	}
	recIDs, err := planRecommendations(ctx, tx, pl)
	if err != nil {
		return 0, err
	}
	if pl.firstVersion {
		if err := establishVersion(ctx, tx, pl.item.ID, pl.now); err != nil {
			return 0, err
		}
	}
	if err := insertActivity(ctx, tx, pl.row); err != nil {
		return 0, err
	}
	if len(recIDs) > 0 {
		if err := markPlanned(ctx, tx, pl, recIDs); err != nil {
			return 0, err
		}
	}
	if pl.core != nil && (pl.core.route == corePackageVisit || pl.core.route == corePackageTraining) {
		if err := takeCoreSlot(ctx, tx, pl); err != nil {
			return 0, err
		}
	}
	var rowID int64
	if !pl.row.isRequest() {
		if rowID, err = keepCosts(ctx, tx, pl); err != nil {
			return 0, err
		}
	}
	if err := tx.Commit(ctx); err != nil {
		return 0, fmt.Errorf("activities: committing the save: %w", err)
	}
	return rowID, nil
}

// establishVersion is _latest_version for an item with none: version 1, a
// snapshot of the item as it stands. A concurrent save may have written it.
func establishVersion(ctx context.Context, tx pgx.Tx, itemID string, now time.Time) error {
	_, err := tx.Exec(ctx, `INSERT INTO activity_catalogue_version (id, created_at, updated_at, catalogue_item_id, version, snapshot, change_reason, created_by)
SELECT $1, $2, $2, i.id, 1, jsonb_build_object(
    'stableCode', i.stable_code, 'displayName', i.display_name, 'sourceName', i.source_name,
    'activityType', i.activity_type, 'deliveryMethod', i.delivery_method, 'workflowKind', i.workflow_kind,
    'targetAudience', i.target_audience, 'salesforceRecordType', i.salesforce_record_type,
    'salesforceExpectedPrefix', i.salesforce_expected_prefix, 'evidenceProfile', i.evidence_profile,
    'costingProfile', i.costing_profile, 'supportObjective', i.support_objective,
    'standardSupport', i.standard_support, 'isTrainingCourse', i.is_training_course,
    'trainingCategory', i.training_category, 'ssaIndicatorLabel', i.ssa_indicator_label,
    'participantMode', i.participant_mode, 'certifiedAgencyDeliveryAllowed', i.certified_agency_delivery_allowed,
    'mappingModes', COALESCE((SELECT jsonb_agg(m.mapping_mode ORDER BY m.is_primary DESC, m.priority, m.id)
       FROM activity_intervention_mapping m WHERE m.catalogue_item_id = i.id AND m.active), '[]'::jsonb),
    'interventions', COALESCE((SELECT jsonb_agg(m.intervention ORDER BY m.is_primary DESC, m.priority, m.id)
       FROM activity_intervention_mapping m WHERE m.catalogue_item_id = i.id AND m.active
        AND m.intervention IS NOT NULL), '[]'::jsonb)),
  'Version established when first scheduled.', 'system'
FROM activity_catalogue_item i WHERE i.id = $3
ON CONFLICT (catalogue_item_id, version) DO NOTHING`, cuid.New(), now, itemID)
	if err != nil {
		return fmt.Errorf("activities: establishing the item's first version: %w", err)
	}
	return nil
}

// duplicates are _create's two same-day tests (3296–3330).
func duplicates(ctx context.Context, q Querier, pl *plan) error {
	r := pl.row
	var identical bool
	if err := q.QueryRow(ctx, `SELECT EXISTS (SELECT 1 FROM activity WHERE activity_type = $1 AND planned_date = $2
  AND deleted_at IS NULL AND responsible_staff_id = $3 AND assigned_partner_id IS NULL
  AND NOT (status = ANY($4)) AND school_id = $5)`,
		r.activityType, r.plannedDate.Format(time.DateOnly), r.responsible, identicalExcluded, r.schoolID).Scan(&identical); err != nil {
		return fmt.Errorf("activities: reading the day's identical work: %w", err)
	}
	if identical {
		return refuse("An identical activity is already scheduled for this target on this date. Reschedule or edit the existing activity instead of creating a duplicate.")
	}
	// existing_same_day_visit: a client-rule school's visit of a kind the
	// client visit counts.
	if !in(rules.Gate.ClientRuleTypes, pl.school.Type) || r.purpose == rules.Gate.CompanionPurpose ||
		!in(rules.Gate.FollowUpVisitTypes, r.activityType) {
		return nil
	}
	var same bool
	if err := q.QueryRow(ctx, `SELECT EXISTS (SELECT 1 FROM activity WHERE school_id = $1 AND planned_date = $2
  AND activity_type = $3 AND catalogue_item_id = $4 AND NOT (status = ANY($5))
  AND NOT COALESCE(purpose_type = $6, false) AND deleted_at IS NULL)`,
		r.schoolID, r.plannedDate.Format(time.DateOnly), r.activityType, r.item.ID,
		rules.DuplicateGoneStatuses, rules.Gate.CompanionPurpose).Scan(&same); err != nil {
		return fmt.Errorf("activities: reading the school's visits that day: %w", err)
	}
	if same {
		return refuse("%s already has this visit on %s. Open that visit instead of planning a second one for the same day.",
			pl.school.Name, shortDate(r.plannedDate))
	}
	return nil
}

// joinDay is attach_activity_to_batch's join: the owner's day, locked, or
// a new one made with its defaults. The pricing is kept for after the save.
func (s *Service) joinDay(ctx context.Context, tx pgx.Tx, pl *plan) (string, bool, error) {
	var batchID string
	err := tx.QueryRow(ctx, `SELECT id FROM daily_visit_batch WHERE responsible_user = $1 AND visit_date = $2
ORDER BY created_at LIMIT 1 FOR UPDATE`, pl.ownerUID, pl.row.plannedDate.Format(time.DateOnly)).Scan(&batchID)
	if err == nil {
		return batchID, false, nil
	}
	if !errors.Is(err, pgx.ErrNoRows) {
		return "", false, fmt.Errorf("activities: locking the day: %w", err)
	}
	districtType := districtTypeFor(pl.home, pl.school.DistrictID, pl.school.DistrictName, pl.school.DistrictType)
	batchID = cuid.New()
	if _, err := tx.Exec(ctx, `
INSERT INTO daily_visit_batch (id, created_at, updated_at, responsible_user, visit_date, district_type,
  rate_snapshot, daily_pool_amount, school_count, per_school_amount, workload_snapshot)
VALUES ($1, $2, $2, $3, $4, $5, '{}', 0, 0, 0, '{}')`,
		batchID, pl.now, pl.ownerUID, pl.row.plannedDate.Format(time.DateOnly), districtType); err != nil {
		return "", false, fmt.Errorf("activities: making the day: %w", err)
	}
	return batchID, true, nil
}

// planRecommendations is link_recommendations' read: the school's open
// recommendations for the plan's intervention, newest first.
func planRecommendations(ctx context.Context, tx pgx.Tx, pl *plan) ([]string, error) {
	if pl.row.focus == "" {
		return nil, nil
	}
	rows, err := tx.Query(ctx, `SELECT id FROM ssa_recommendation WHERE school_id = $1 AND intervention = $2
  AND state = ANY($3) ORDER BY school_id, created_at DESC`,
		pl.row.schoolID, pl.row.focus, []string{"generated", "accepted", "deferred"})
	if err != nil {
		return nil, fmt.Errorf("activities: reading the open recommendations: %w", err)
	}
	ids, err := pgx.CollectRows(rows, pgx.RowTo[string])
	if err != nil {
		return nil, fmt.Errorf("activities: reading the open recommendations: %w", err)
	}
	if len(ids) > 0 {
		pl.row.recommendationID = ids[0]
	}
	return ids, nil
}

func insertActivity(ctx context.Context, tx pgx.Tx, r activityRow) error {
	source, err := json.Marshal(r.source)
	if err != nil {
		return fmt.Errorf("activities: encoding the recommendation source: %w", err)
	}
	var sourceSSA, sourceState, band any
	if r.sourceSSA != nil {
		sourceSSA, sourceState = r.sourceSSA.ID, "confirmed"
	}
	if r.sourceBand != "" {
		band = r.sourceBand
	}
	planningSource, contextType := r.planning()
	// Every column the row sets, the model defaults among them.
	columns := []struct {
		name  string
		value any
	}{
		{"id", r.id}, {"created_at", r.now}, {"updated_at", r.now}, {"activity_type", r.activityType},
		{"fy", r.fy}, {"quarter", r.quarter}, {"delivery_type", "staff"}, {"executor_type", "staff"},
		{"status", r.status()}, {"evidence_status", "none"}, {"ia_verification_status", "pending"},
		{"payment_status", "none"}, {"reschedule_count", 0}, {"est_cost_cents", 0}, {"cost_missing", false},
		{"environment", "production"}, {"source", "manual_upload"}, {"school_id", optString(r.schoolID)},
		{"responsible_staff_id", r.responsible}, {"scheduled_date", r.scheduled},
		{"planned_date", r.plannedDate.Format(time.DateOnly)}, {"planned_month", r.plannedMonth},
		{"planned_week", r.plannedWeek}, {"purpose_type", r.purpose}, {"purpose_intervention", optString(r.focus)},
		{"focus_intervention", optString(r.focus)}, {"secondary_focus_interventions", append([]string{}, r.secondary...)},
		{"activity_purpose_text", r.goal}, {"expected_outcome", r.outcomeValue()},
		{"ssa_collection_expected", r.collects}, {"attended_school_ids", []string{}},
		{"salesforce_activity_type", r.salesforceType()}, {"catalogue_item_id", r.item.ID},
		{"catalogue_version", r.version}, {"activity_name_snapshot", r.name()},
		{"activity_type_snapshot", r.item.ActivityType}, {"delivery_method_snapshot", r.item.DeliveryMethod},
		{"evidence_profile_snapshot", optString(r.item.EvidenceProfile)},
		{"costing_profile_snapshot", optString(r.item.CostingProfile)},
		{"salesforce_record_type_snapshot", optString(r.item.SalesforceRecordType)},
		{"recommendation_reason", r.reason}, {"recommendation_source", source}, {"override_reason", ""},
		{"source_ssa_id", sourceSSA}, {"source_ssa_verification_state", sourceState},
		{"source_score", r.sourceScore}, {"source_classification", band},
		{"ssa_recommendation_id", optString(r.recommendationID)}, {"ssa_alignment", r.alignment},
		{"ssa_deviation_reason", r.deviation}, {"planning_source", planningSource},
		{"activity_context_type", contextType}, {"support_rationale", ""}, {"venue", ""},
		{"primary_driver_type", ""}, {"primary_driver_id", ""}, {"driver_reason", ""},
		{"delivery_contact_name", ""}, {"approval_owner_id", r.approvalOwner}, {"owner_decision_note", ""},
		{"visit_justification", r.justification}, {"partner_date_set_by", ""}, {"meeting_kind", r.meetingKind},
		{"daily_visit_batch_id", optString(r.batchID)},
		{"training_course_id", optString(r.trainingCourseID)}, {"paired_school_visit_id", optString(r.pairedVisitID)},
	}
	columns = append(columns, r.groupFields()...)
	columns = append(columns, r.onlineFields()...)
	if r.followUpOf != "" {
		columns = append(columns, struct {
			name  string
			value any
		}{"follow_up_of_activity_id", r.followUpOf})
	}
	names := make([]string, len(columns))
	marks := make([]string, len(columns))
	values := make([]any, len(columns))
	for i, c := range columns {
		names[i], marks[i], values[i] = c.name, fmt.Sprintf("$%d", i+1), c.value
	}
	_, err = tx.Exec(ctx, "INSERT INTO activity ("+strings.Join(names, ", ")+") VALUES ("+strings.Join(marks, ", ")+")", values...)
	if err != nil {
		return fmt.Errorf("activities: inserting the activity: %w", err)
	}
	return nil
}

// markPlanned is link_recommendations' write and its audit row
// (plan_alignment 632–676, _audit_recommendations).
func markPlanned(ctx context.Context, tx pgx.Tx, pl *plan, ids []string) error {
	if _, err := tx.Exec(ctx, `UPDATE ssa_recommendation SET state = 'planned', planned_activity_id = $1,
  decided_at = $2, updated_at = $2 WHERE id = ANY($3)`, pl.row.id, pl.now, ids); err != nil {
		return fmt.Errorf("activities: planning the recommendations: %w", err)
	}
	listed := []any{}
	for _, id := range ids[:min(len(ids), 200)] {
		listed = append(listed, id)
	}
	empty := ""
	_, err := audit.Append(ctx, tx, audit.Entry{
		Action: "ssa.recommendation_planned", SubjectKind: audit.Text("Activity"), SubjectID: audit.Text(pl.row.id),
		ActorID: audit.Text("system"), ActorRole: &empty, Success: true,
		Payload:   map[string]any{"recommendationIds": listed, "intervention": pl.row.focus, "status": "scheduled"},
		IPAddress: nilIfEmpty(pl.origin.IP), UserAgent: nilIfEmpty(pl.origin.UserAgent),
		CorrelationID: nilIfEmpty(pl.origin.CorrelationID),
	}, pl.now)
	return err
}

// keepCosts is costs_follow._hand_over's row: the day to price, for whom,
// who asked and the request it came in on.
func keepCosts(ctx context.Context, tx pgx.Tx, pl *plan) (int64, error) {
	steps, err := json.Marshal(map[string]any{
		"days": [][]string{{pl.row.batchID, pl.ownerUID}}, "together": false,
		"weeks": []any{}, "months": []any{}, "notes": []any{}, "change": nil,
	})
	if err != nil {
		return 0, err
	}
	owners := []string{pl.ownerUID}
	sort.Strings(owners)
	ownersJSON, _ := json.Marshal(owners)
	provenance, _ := json.Marshal(map[string]any{
		"ip": nilIfEmpty(pl.origin.IP), "agent": nilIfEmpty(pl.origin.UserAgent),
		"correlation": nilIfEmpty(pl.origin.CorrelationID), "acting": nil,
	})
	var id int64
	err = tx.QueryRow(ctx, `
INSERT INTO daily_visit_costs_to_follow (created_at, updated_at, owners, asked_by, asked_by_role, steps,
  provenance, attempts, held_reason)
VALUES ($1, $1, $2, $3, $4, $5, $6, 0, '') RETURNING id`,
		pl.now, ownersJSON, pl.p.UserID, pl.p.ActiveRole, steps, provenance).Scan(&id)
	if err != nil {
		return 0, fmt.Errorf("activities: keeping the costs to follow: %w", err)
	}
	return id, nil
}

func nilIfEmpty(s string) *string {
	if s == "" {
		return nil
	}
	return &s
}

// afterCommit is what follows the save's commit, in the existing order: the
// target ledger's mark (on commit), the activity.scheduled audit row (after
// the save's block), then the pricing and the live announcement, which the
// existing application does once the costs are in. None of it can undo the
// save; a failure is logged, as the existing application logs it.
func (s *Service) afterCommit(ctx context.Context, pl *plan, rowID int64) {
	if err := s.markLedger(ctx, pl); err != nil {
		s.logger.Warn("activities: the target ledger was not marked", "activity", pl.row.id, "err", err)
	}
	if err := s.auditScheduled(ctx, pl); err != nil {
		s.logger.Warn("activities: the scheduled audit row was not written", "activity", pl.row.id, "err", err)
	}
	if err := s.auditMeetingAdded(ctx, pl); err != nil {
		s.logger.Warn("activities: the meeting's audit row was not written", "activity", pl.row.id, "err", err)
	}
	if pl.row.isRequest() {
		if err := s.tellRequestOwner(ctx, pl); err != nil {
			s.logger.Warn("activities: the owner was not asked about the visit", "activity", pl.row.id, "err", err)
		}
		if err := s.auditCoreDoor(ctx, pl); err != nil {
			s.logger.Warn("activities: the form's audit row was not written", "activity", pl.row.id, "err", err)
		}
		return
	}
	if err := s.tellScheduledOwner(ctx, pl); err != nil {
		s.logger.Warn("activities: the owner was not told of the visit", "activity", pl.row.id, "err", err)
	}
	if err := s.auditCoreDoor(ctx, pl); err != nil {
		s.logger.Warn("activities: the form's audit row was not written", "activity", pl.row.id, "err", err)
	}
	if err := s.pricing.Settle(ctx, []int64{rowID}, pl.row.id); err != nil {
		s.logger.Warn("activities: the costs to follow were not settled; the sweep takes them",
			"activity", pl.row.id, "row", rowID, "err", err)
	}
	if pl.core != nil && pl.core.route == coreCreditedVisit {
		if err := s.creditCoreSlot(ctx, pl, pl.core.planID, coreSlotVisit); err != nil {
			s.logger.Warn("activities: the Core package was not credited", "activity", pl.row.id, "err", err)
		}
	}
}

// takeCoreSlot is assert_can_schedule's lock and commit_schedule: the
// package's next open visit, inside the save.
func takeCoreSlot(ctx context.Context, tx pgx.Tx, pl *plan) error {
	slots, err := readCoreSlots(ctx, tx, pl.core.planID, pl.core.slotKind(), " FOR UPDATE")
	if err != nil {
		return err
	}
	open := openCoreSlotAt(slots, pl.core.preferred, coreSlotTaken)
	if open == nil {
		return handOn("the Core package has no open slot")
	}
	pl.core.slotNumber = open.Sequence
	return bookCoreSlot(ctx, tx, open.ID, "Scheduled", pl)
}

// slotStaff is the slot's assigned staff: the training form names nobody, so
// its commit_schedule writes none.
func slotStaff(pl *plan) any {
	if pl.core != nil && pl.core.route == corePackageTraining {
		return nil
	}
	return pl.row.responsible
}

// creditCoreSlot is credit_school_activity for staff SSA Support: after the
// save, the visit takes the package's next open slot unless it holds one.
func (s *Service) creditCoreSlot(ctx context.Context, pl *plan, planID, kind string) error {
	tx, err := s.db.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite})
	if err != nil {
		return err
	}
	defer func() { _ = tx.Rollback(ctx) }()
	slots, err := readCoreSlots(ctx, tx, planID, kind, " FOR UPDATE")
	if err != nil {
		return err
	}
	var linked bool
	if err := tx.QueryRow(ctx, `SELECT EXISTS (SELECT 1 FROM core_activity_slot WHERE activity_id = $1)`, pl.row.id).Scan(&linked); err != nil {
		return err
	}
	if linked {
		return nil
	}
	open := openCoreSlot(slots, coreSlotTaken)
	if open == nil {
		return fmt.Errorf("the package has no open %s slot", kind)
	}
	if err := bookCoreSlot(ctx, tx, open.ID, pl.row.status(), pl); err != nil {
		return err
	}
	// resync_plan_completion: recomputed from the slots, written if it moved.
	if _, err := tx.Exec(ctx, `UPDATE core_plan p SET visits_completed = c.visits, trainings_completed = c.trainings, updated_at = $3
FROM (SELECT count(*) FILTER (WHERE activity_type = 'visit' AND status = ANY($2)) AS visits,
             count(*) FILTER (WHERE activity_type = 'training' AND status = ANY($2)) AS trainings
      FROM core_activity_slot WHERE core_plan_id = $1) c
WHERE p.id = $1 AND (p.visits_completed IS DISTINCT FROM c.visits OR p.trainings_completed IS DISTINCT FROM c.trainings)`,
		planID, coreDoneStatuses, s.now()); err != nil {
		return err
	}
	return tx.Commit(ctx)
}

// bookCoreSlot writes the visit onto its slot.
func bookCoreSlot(ctx context.Context, tx pgx.Tx, slotID, status string, pl *plan) error {
	r := pl.row
	_, err := tx.Exec(ctx, `UPDATE core_activity_slot SET status = $2, activity_id = $3, scheduled_for = $4,
  scheduled_month = $5, scheduled_week = $6, assigned_staff_id = $7, owner = 'staff', updated_at = $8 WHERE id = $1`,
		slotID, status, r.id, r.plannedDate.Format(time.DateOnly), strconv.Itoa(r.plannedMonth), r.plannedWeek, slotStaff(pl), pl.now)
	if err != nil {
		return fmt.Errorf("activities: writing the package slot: %w", err)
	}
	return nil
}

// markLedger is ledger_sync's mark for the responsible person and the
// planned day's year, when a target area counts the visit's type.
func (s *Service) markLedger(ctx context.Context, pl *plan) error {
	if !in(rules.LedgerCreditedTypes, pl.row.activityType) {
		return nil
	}
	day := pl.row.plannedDate
	fy := schooldirectory.OperationalFY(time.Date(day.Year(), day.Month(), day.Day(), 0, 0, 0, 0, time.UTC))
	tx, err := s.db.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite})
	if err != nil {
		return err
	}
	defer func() { _ = tx.Rollback(ctx) }()
	if _, err := tx.Exec(ctx, `INSERT INTO target_ledger_dirty (owner_id, fy, marked_at) VALUES ($1, $2, $3)
ON CONFLICT (owner_id, fy) DO UPDATE SET marked_at = EXCLUDED.marked_at`, pl.row.responsible, fy, s.now()); err != nil {
		return err
	}
	return tx.Commit(ctx)
}

// auditScheduled is the `activity.scheduled` row `_create` appends after
// its block (3566–3597), with the stamps log() adds.
func (s *Service) auditScheduled(ctx context.Context, pl *plan) error {
	r := pl.row
	payload := map[string]any{
		"activity_type": r.activityType, "catalogue_item": r.item.ID, "catalogue_version": r.version,
		"school_id": optString(r.schoolID), "cluster_id": nil, "project_id": nil, "fy": r.fy,
		"planned_date": r.plannedDate.Format(time.DateOnly), "delivery_type": "staff",
		"executor_type": "staff", "focus_intervention": r.focus,
	}
	if r.group != nil {
		payload["cluster_id"] = r.group.clusterID
	}
	role := pl.p.ActiveRole
	tx, err := s.db.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite})
	if err != nil {
		return err
	}
	defer func() { _ = tx.Rollback(ctx) }()
	cover, err := coverageStamp(ctx, tx, pl.p.UserID, s.now())
	if err != nil {
		return err
	}
	if _, err := audit.Append(ctx, tx, audit.Entry{
		Action: "activity.scheduled", SubjectKind: audit.Text("Activity"), SubjectID: audit.Text(r.id),
		ActorID: audit.Text(pl.p.UserID), ActorRole: &role, Success: true, Payload: withStamps(payload, cover),
		IPAddress: nilIfEmpty(pl.origin.IP), UserAgent: nilIfEmpty(pl.origin.UserAgent),
		CorrelationID: nilIfEmpty(pl.origin.CorrelationID),
	}, s.now()); err != nil {
		return err
	}
	return tx.Commit(ctx)
}
