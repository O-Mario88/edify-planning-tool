package activities

// The tenth save Go owns: completing a staff school visit from My Plan's
// Complete drawer (docs/migration/183), exactly 183.1's case. The rules are
// the view (apps/frontend/views/my_plan_views.py complete_activity_action),
// the completion (apps/activities/services.py complete) and the reservation
// of its Salesforce ID (apps/activities/salesforce.py reserve_salesforce_id),
// for that case, in their order (183.3). The writes the gateway may not make
// itself go through one narrow function (deploy/db/completion_roles.sql);
// what follows the hand-in (the Programme Lead told, the overdue reminder
// closed, plan.changed said) is asked of the existing application after
// commit, as its notices are its own until M11 (HandedIn). Every other
// completion is handed on unchanged, so none is made by both.

import (
	"context"
	"errors"
	"fmt"
	"net/url"
	"regexp"
	"slices"
	"strconv"
	"strings"
	"time"
	"unicode"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgconn"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/audit"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/cuid"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/myplan"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// The existing words (salesforce.py accepted_forms and DuplicateSalesforceId)
// and the audit actions the completion writes.
const (
	salesforceFormsRefusal = "Enter the Salesforce ID as SV-… or SVE-…, or the record's own Salesforce ID."
	salesforceTakenRefusal = "This Salesforce Activity ID has already been used. Check the ID in " +
		"Salesforce and enter the correct record."
	completeAuditAction    = "complete_activity"
	salesforceAuditAction  = "activity.salesforce_id_entered"
	staffSelfEntry         = "staff_self_entry"
	handedInStatus         = "submitted_to_pl"
	startedStatus          = "completion_started"
	maxSalesforceRaw       = 128
	maxAttendanceDigits    = 9
	uniqueViolation        = "23505"
	confirmedVerification  = "confirmed"
	onetestCostingProfile  = "ONETEST"
	programmeLeadRole      = "Program Lead"
	officerRole            = "CCEO"
	trainingSalesforcePart = "TS-"
)

// The forms a visit's ID may take (salesforce.py _SVE_RE, _SV_RE and
// _RECORD_ID_RE), once normalised.
var (
	salesforceVisitForms = []*regexp.Regexp{
		regexp.MustCompile(`^SVE-[A-Z0-9-]{3,}$`),
		regexp.MustCompile(`^SV-[A-Z0-9-]{3,}$`),
		regexp.MustCompile(`^[A-Z0-9]{15}(?:[A-Z0-9]{3})?$`),
	}
	attendanceCount = regexp.MustCompile(`^[0-9]+$`)
	// completionPurposes are the purposes the drawer may give a visit as it
	// is completed (completion_purpose.COMPLETION_PURPOSES): a visit holding
	// one, or given one, completes in the existing application.
	completionPurposes = []string{"ssa_support", "in_school_training", "in_school_training_ssa", "training_follow_up"}
	// completedVisitTypes are the staff school visits 183.1 completes: a
	// School Visit, and the visits a donor, story-gathering, invitation or
	// social purpose is planned as (rules.Purposes.ActivityTypes); the
	// SSA, follow-up, coaching and training workflows are the existing
	// application's. deploy/db/completion_roles.sql names the same list.
	completedVisitTypes = []string{"school_visit", "donor_visit", "story_gathering_visit", "school_invitation", "social_visit"}
	// visitRecordTypes are the catalogue record types a visit's ID is kept
	// under (sf_kind_for_activity), "" being none recorded.
	visitRecordTypes = []string{"", "VISIT", "SSA_DATA_GATHERING"}
	// handedOnFields are drawer fields whose presence takes the completion
	// out of 183.1's case: a training's ID, the school's feedback, a
	// register's schools.
	handedOnFields = []string{"training_salesforce_id", "feedback_finding", "school_improvements", "attended_school_ids"}
)

// CompleteRequest is the Complete drawer's form, as the existing save would
// receive it (the drawer's form_only answer).
type CompleteRequest struct {
	ActivityID string
	Form       url.Values
}

// CompleteAnswer is the handed-in visit and the toast the web shows.
type CompleteAnswer struct {
	ActivityID, Status, Message string
}

// CompletionFollower asks the existing application for what follows a
// hand-in (gateway_relay.visit_completed).
type CompletionFollower interface {
	HandedIn(ctx context.Context, activityID, userID, role string) error
}

// completedVisit is the visit as the completion reads it.
type completedVisit struct {
	id, activityType, status, purpose string
	schoolID, responsible             string
	verification, recordType, costing string
	salesforceID                      string
	collectsSSA, other                bool
	plannedDate                       time.Time
}

// completionPlan is everything decided before the transaction.
type completionPlan struct {
	p                            auth.Principal
	a                            completedVisit
	delivered                    time.Time
	raw, normalized              string
	teachers, leaders, others    int
	outcome, observations, notes *string
	payload                      map[string]any
	origin                       Origin
	now                          time.Time
}

// Complete hands the visit in, or refuses it in the existing words, or
// hands it on (ErrHandOn). A refusal and a hand-on write nothing, as the
// existing completion's refusals roll its one transaction back.
func (s *Service) Complete(ctx context.Context, p auth.Principal, req CompleteRequest, origin Origin) (CompleteAnswer, error) {
	pl, err := s.prepareCompletion(ctx, p, req, origin)
	if err != nil {
		return CompleteAnswer{}, err
	}
	if err := s.writeCompletion(ctx, pl); err != nil {
		return CompleteAnswer{}, err
	}
	s.afterCompletion(ctx, pl)
	return CompleteAnswer{ActivityID: pl.a.id, Status: handedInStatus, Message: rules.Move.SavedMessage}, nil
}

// prepareCompletion is the view and complete() up to the reservation's
// transaction: who completes, which visit, and what the drawer posted.
func (s *Service) prepareCompletion(ctx context.Context, p auth.Principal, req CompleteRequest, origin Origin) (*completionPlan, error) {
	now := s.now()
	// A CCEO's own work routes to their Programme Lead (routes_to_lead); a
	// lead's own work is approved as it lands (approve_on_hand_in): handed on.
	if p.InActingAppointment || p.StaffProfileID == "" || p.ActiveRole != officerRole || slices.Contains(p.Roles, programmeLeadRole) {
		return nil, handOn("not an officer completing their own visit")
	}
	a, err := readCompletedVisit(ctx, s.db, strings.TrimSpace(req.ActivityID))
	if err != nil {
		return nil, err
	}
	if why := a.outOfCase(p); why != "" {
		return nil, handOn(why)
	}
	if err := s.ownVisitSchool(ctx, p, a.schoolID, now); err != nil {
		return nil, err
	}
	ownerUID, err := fundingOwner(ctx, s.db, a.responsible, p.UserID)
	if err != nil {
		return nil, err
	}
	if why, err := moveNotices(ctx, s.db, a.id, ownerUID); err != nil || why != "" {
		if err != nil {
			return nil, err
		}
		return nil, handOn(why)
	}
	pl := &completionPlan{p: p, a: *a, origin: origin, now: now}
	if err := s.readCompletionForm(pl, req.Form); err != nil {
		return nil, err
	}
	return pl, nil
}

// ownVisitSchool hands on a visit whose school is a Core school, gone, or
// outside the person's own portfolio, as the visit saves before it do.
func (s *Service) ownVisitSchool(ctx context.Context, p auth.Principal, schoolID string, now time.Time) error {
	sc, err := schoolByIDOrCode(ctx, s.db, schoolID)
	if err != nil {
		return err
	}
	if sc == nil || sc.ID != schoolID || in(rules.Gate.CoreRuleTypes, sc.Type) {
		return handOn("a Core school, or no school")
	}
	scope, err := schooldirectory.ResolveScope(ctx, s.db, p, now)
	if err != nil {
		return handOn("no scope: " + err.Error())
	}
	owner, err := schoolOwner(ctx, s.db, sc.ID)
	if err != nil {
		return err
	}
	if !slices.Contains(scope.OwnSchoolIDs, sc.ID) || owner != p.StaffProfileID {
		return handOn("outside the person's own portfolio")
	}
	return nil
}

// outOfCase says why the visit is not 183.1's case ("" when it is): a
// started staff school visit, owned by the person, holding no purpose the
// drawer decides, collecting no SSA, not a OneTest visit, with no ID yet.
func (a *completedVisit) outOfCase(p auth.Principal) string {
	switch {
	case a == nil:
		return "not a staff school visit with a school and a day"
	case a.other:
		return "a visit in a cluster, a project, a pair or a partner's hands, or a OneTest visit"
	case a.responsible != p.StaffProfileID:
		return "someone else's visit"
	case a.status != startedStatus:
		return "a visit in status " + a.status + ", not started"
	case in(completionPurposes, a.purpose) || a.collectsSSA:
		return "a visit whose purpose the drawer decides, or one collecting the SSA"
	case a.verification == confirmedVerification:
		return "a visit IA has confirmed"
	case !in(visitRecordTypes, strings.ToUpper(a.recordType)) || a.costing == onetestCostingProfile:
		return "a visit kept under another Salesforce record type, or a OneTest visit"
	case a.salesforceID != "":
		return "a visit that already holds a Salesforce ID"
	}
	return ""
}

// readCompletedVisit reads the visit; nil when there is none.
func readCompletedVisit(ctx context.Context, q Querier, id string) (*completedVisit, error) {
	if id == "" {
		return nil, nil
	}
	var a completedVisit
	var purpose, school, responsible, verification, recordType, costing, salesforce *string
	var planned *time.Time
	err := q.QueryRow(ctx, `
SELECT a.id, a.activity_type, a.status, a.purpose_type, a.school_id, a.responsible_staff_id, a.planned_date,
       a.ia_verification_status, a.salesforce_record_type_snapshot, a.costing_profile_snapshot,
       a.salesforce_activity_id, a.ssa_collection_expected,
       (a.cluster_id IS NOT NULL OR a.project_id IS NOT NULL OR a.assigned_partner_id IS NOT NULL
        OR a.delivery_type IS DISTINCT FROM 'staff' OR a.paired_school_visit_id IS NOT NULL
        OR a.monitored_by_staff_id IS NOT NULL
        OR EXISTS (SELECT 1 FROM activity o WHERE o.paired_school_visit_id = a.id AND o.deleted_at IS NULL)
        OR EXISTS (SELECT 1 FROM activity_catalogue_item c WHERE c.id = a.catalogue_item_id
                   AND c.costing_profile = 'ONETEST'))
FROM activity a WHERE a.id = $1 AND a.deleted_at IS NULL`, id).Scan(
		&a.id, &a.activityType, &a.status, &purpose, &school, &responsible, &planned,
		&verification, &recordType, &costing, &salesforce, &a.collectsSSA, &a.other)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, nil
	}
	if err != nil {
		return nil, fmt.Errorf("activities: reading the visit: %w", err)
	}
	if !in(completedVisitTypes, a.activityType) || school == nil || planned == nil {
		return nil, nil
	}
	a.purpose, a.schoolID, a.responsible = text(purpose), text(school), text(responsible)
	a.verification, a.recordType, a.costing = text(verification), text(recordType), text(costing)
	a.salesforceID, a.plannedDate = text(salesforce), *planned
	return &a, nil
}

// readCompletionForm is what the view and complete() read from the post
// (_complete_with_purpose, _submit_accountability, _completion_payload,
// completion_day, the reservation's format), in their order.
func (s *Service) readCompletionForm(pl *completionPlan, form url.Values) error {
	for _, field := range handedOnFields {
		if form.Has(field) {
			return handOn("the drawer posted " + field)
		}
	}
	if pyStrip(form.Get("netsuite_id")) != "" || form.Get("visiting_register") == "1" {
		return handOn("an accountability, or a register's visiting schools")
	}
	if posted := pyStrip(form.Get("purpose_type")); posted != "" && posted != pl.a.purpose {
		return handOn("a purpose given at completion")
	}
	delivered, err := s.completedOn(form.Get("actual_delivery_date"))
	if err != nil {
		return err
	}
	if !sameDay(delivered, pl.a.plannedDate) {
		return handOn("done on another day than planned: the work and its money move")
	}
	pl.delivered = delivered
	counts := make([]int, 0, 3)
	for _, field := range []string{"teachers_attended", "leaders_attended", "other_participants"} {
		n, err := attendance(form, field)
		if err != nil {
			return err
		}
		counts = append(counts, n)
	}
	pl.teachers, pl.leaders, pl.others = counts[0], counts[1], counts[2]
	pl.outcome, pl.observations, pl.notes = posted(form, "actual_outcome"), posted(form, "actual_observations"),
		posted(form, "follow_up_note")
	pl.raw = pyStrip(form.Get("salesforce_id"))
	pl.payload = completionPayload(pl, form)
	return s.judgeSalesforceID(pl)
}

// completedOn is completion_day, or today when the drawer sent none. A day
// in another form, or a future one, is the view's notice: handed on.
func (s *Service) completedOn(raw string) (time.Time, error) {
	now := s.now().In(s.kampala)
	today := time.Date(now.Year(), now.Month(), now.Day(), 0, 0, 0, 0, time.UTC)
	raw = pyStrip(raw)
	if raw == "" {
		return today, nil
	}
	if !isoDate.MatchString(raw) {
		return time.Time{}, handOn("a completed day in another form")
	}
	day, err := time.Parse(time.DateOnly, raw)
	if err != nil {
		return time.Time{}, handOn("not a day")
	}
	if day.After(today) {
		return time.Time{}, handOn("a future completed day")
	}
	return day, nil
}

// attendance is `int(x) if x else 0` for a count Go can read as Python does.
func attendance(form url.Values, field string) (int, error) {
	raw := form.Get(field)
	if raw == "" {
		return 0, nil
	}
	if !attendanceCount.MatchString(raw) || len(raw) > maxAttendanceDigits {
		return 0, handOn(field + " in another form")
	}
	n, err := strconv.Atoi(raw)
	if err != nil {
		return 0, handOn(field + " in another form")
	}
	return n, nil
}

// posted is the field, stripped, when the drawer sent it; nil otherwise
// (complete() leaves an absent field as it was).
func posted(form url.Values, field string) *string {
	if !form.Has(field) {
		return nil
	}
	value := pyStrip(form.Get(field))
	return &value
}

// completionPayload is _completion_payload for 183.1's case, with the view's
// paired visit: what complete() is given and the audit row records.
func completionPayload(pl *completionPlan, form url.Values) map[string]any {
	payload := map[string]any{
		"ssaCollected":           false,
		"actualDeliveryDate":     pl.delivered.Format(time.DateOnly),
		"salesforceId":           pl.raw,
		"trainingSalesforceId":   pl.raw,
		"visitSalesforceId":      pyStrip(form.Get("visit_salesforce_id")),
		"teachersAttended":       pl.teachers,
		"leadersAttended":        pl.leaders,
		"otherParticipants":      pl.others,
		"attendedSchoolIds":      []any{},
		"visitingSchoolIds":      nil,
		"followUpOfActivityId":   pyStrip(form.Get("follow_up_of_activity_id")),
		"paired_school_visit_id": nil,
	}
	for key, value := range map[string]*string{
		"actualOutcome": pl.outcome, "actualObservations": pl.observations, "followUpNote": pl.notes,
	} {
		if value != nil {
			payload[key] = *value
		}
	}
	return payload
}

// judgeSalesforceID is normalize_salesforce_id and is_valid_new_entry for a
// visit. A training's TS- ID on a visit is the view's own notice
// (_refuse_a_training_id_on_a_visit): handed on, as is a value Go cannot
// normalise exactly as Python does (anything outside ASCII).
func (s *Service) judgeSalesforceID(pl *completionPlan) error {
	if len(pl.raw) > maxSalesforceRaw {
		return handOn("a Salesforce ID longer than its reference keeps")
	}
	normalized, ok := normalizeSalesforceID(pl.raw)
	if !ok {
		return handOn("a Salesforce ID outside ASCII")
	}
	if strings.HasPrefix(normalized, trainingSalesforcePart) {
		return handOn("a training's ID entered on a visit")
	}
	if !slices.ContainsFunc(salesforceVisitForms, func(form *regexp.Regexp) bool { return form.MatchString(normalized) }) {
		return refuse("%s", salesforceFormsRefusal)
	}
	pl.normalized = normalized
	return nil
}

// normalizeSalesforceID is normalize_salesforce_id for an ASCII value: the
// control characters dropped, upper-cased, every whitespace removed. ok is
// false for a value with any other character.
func normalizeSalesforceID(raw string) (string, bool) {
	var out strings.Builder
	for _, r := range raw {
		switch {
		case r > unicode.MaxASCII:
			return "", false
		case r < 0x20 || r == 0x7f || r == ' ':
			continue
		default:
			out.WriteRune(unicode.ToUpper(r))
		}
	}
	return out.String(), true
}

// writeCompletion is the reservation and the hand-in, in one transaction,
// with the reservation's audit row (inside the existing view's transaction).
func (s *Service) writeCompletion(ctx context.Context, pl *completionPlan) error {
	tx, err := s.db.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite, IsoLevel: pgx.ReadCommitted})
	if err != nil {
		return fmt.Errorf("activities: opening the completion: %w", err)
	}
	defer func() { _ = tx.Rollback(ctx) }()
	var answer string
	err = tx.QueryRow(ctx, `SELECT gateway_completion.hand_in_school_visit($1, $2, $3, $4, $5, $6, $7, $8, $9, $10,
  $11, $12, $13, $14)`,
		pl.a.id, pl.delivered, pl.raw, pl.normalized, pl.teachers, pl.leaders, pl.others,
		pl.outcome, pl.observations, pl.notes, pl.p.UserID, pl.now, cuid.New(), cuid.New()).Scan(&answer)
	var pgErr *pgconn.PgError
	if errors.As(err, &pgErr) && pgErr.Code == uniqueViolation {
		return refuse("%s", salesforceTakenRefusal)
	}
	if err != nil {
		return fmt.Errorf("activities: handing the visit in: %w", err)
	}
	if holder, held := strings.CutPrefix(answer, "held:"); held {
		message, err := takenBy(ctx, tx, holder)
		if err != nil {
			return err
		}
		return refuse("%s", message)
	}
	if answer != "" {
		return handOn("the hand-in met " + answer)
	}
	if err := s.appendSalesforceRow(ctx, tx, pl); err != nil {
		return err
	}
	if err := tx.Commit(ctx); err != nil {
		return fmt.Errorf("activities: committing the completion: %w", err)
	}
	return nil
}

// takenBy is _duplicate_message: the work that already holds the ID, named.
func takenBy(ctx context.Context, q Querier, holderID string) (string, error) {
	var activityType string
	var snapshot, schoolName, schoolCode, clusterName *string
	var planned *time.Time
	err := q.QueryRow(ctx, `
SELECT a.activity_type, a.activity_name_snapshot, s.name, s.school_id, c.name, a.planned_date
FROM activity a LEFT JOIN school s ON s.id = a.school_id LEFT JOIN cluster c ON c.id = a.cluster_id
WHERE a.id = $1`, holderID).Scan(&activityType, &snapshot, &schoolName, &schoolCode, &clusterName, &planned)
	if errors.Is(err, pgx.ErrNoRows) {
		return salesforceTakenRefusal, nil
	}
	if err != nil {
		return "", fmt.Errorf("activities: reading the ID's holder: %w", err)
	}
	name := text(snapshot)
	if name == "" {
		name = myplan.TypeLabel(activityType)
	}
	where := "another activity"
	switch {
	case schoolName != nil:
		where = fmt.Sprintf("%s (%s)", *schoolName, text(schoolCode))
	case clusterName != nil:
		where = *clusterName
	}
	when := ""
	if planned != nil {
		when = " on " + planned.Format("2 Jan 2006")
	}
	return fmt.Sprintf("This Salesforce Activity ID is already used by the %s at %s%s. Check the ID in "+
		"Salesforce and enter the correct record.", name, where, when), nil
}

// appendSalesforceRow is the reservation's `activity.salesforce_id_entered`
// row, with the stamps log() adds.
func (s *Service) appendSalesforceRow(ctx context.Context, tx pgx.Tx, pl *completionPlan) error {
	cover, err := coverageStamp(ctx, tx, pl.p.UserID, s.now())
	if err != nil {
		return err
	}
	role := pl.p.ActiveRole
	_, err = audit.Append(ctx, tx, audit.Entry{
		Action: salesforceAuditAction, SubjectKind: audit.Text("Activity"), SubjectID: audit.Text(pl.a.id),
		ActorID: audit.Text(pl.p.UserID), ActorRole: &role, Success: true,
		Payload: withStamps(map[string]any{
			"normalized_value": pl.normalized, "entry_source": staffSelfEntry, "released_from_activity_id": nil,
		}, cover),
		IPAddress: nilIfEmpty(pl.origin.IP), UserAgent: nilIfEmpty(pl.origin.UserAgent),
		CorrelationID: nilIfEmpty(pl.origin.CorrelationID),
	}, s.now())
	if err != nil {
		return fmt.Errorf("activities: writing the reservation's audit row: %w", err)
	}
	return nil
}

// afterCompletion is what follows the commit, in the existing order: the
// hand-in's notices (_handed_in, _resolve_overdue_reminder, the
// announcement), the view's complete_activity row, then the ledger's mark
// (on commit). None of it can undo the completion.
func (s *Service) afterCompletion(ctx context.Context, pl *completionPlan) {
	if follower, ok := s.pricing.(CompletionFollower); ok {
		if err := follower.HandedIn(ctx, pl.a.id, pl.p.UserID, pl.p.ActiveRole); err != nil {
			s.logger.Warn("activities: the hand-in's notices were not sent", "activity", pl.a.id, "err", err)
		}
	}
	if err := s.appendCompleteRow(ctx, pl); err != nil {
		s.logger.Warn("activities: the completion audit row was not written", "activity", pl.a.id, "err", err)
	}
	if in(rules.LedgerCreditedTypes, pl.a.activityType) {
		if err := s.markOwnerYears(ctx, pl.a.responsible, pl.a.plannedDate); err != nil {
			s.logger.Warn("activities: the target ledger was not marked", "activity", pl.a.id, "err", err)
		}
	}
}

// appendCompleteRow is the view's `complete_activity` row (my_plan_views
// 1750), with the stamps log() adds.
func (s *Service) appendCompleteRow(ctx context.Context, pl *completionPlan) error {
	tx, err := s.db.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite})
	if err != nil {
		return err
	}
	defer func() { _ = tx.Rollback(ctx) }()
	cover, err := coverageStamp(ctx, tx, pl.p.UserID, s.now())
	if err != nil {
		return err
	}
	role := pl.p.ActiveRole
	if _, err := audit.Append(ctx, tx, audit.Entry{
		Action: completeAuditAction, SubjectKind: audit.Text("Activity"), SubjectID: audit.Text(pl.a.id),
		ActorID: audit.Text(pl.p.UserID), ActorRole: &role, Success: true,
		Payload:   withStamps(pl.payload, cover),
		IPAddress: nilIfEmpty(pl.origin.IP), UserAgent: nilIfEmpty(pl.origin.UserAgent),
		CorrelationID: nilIfEmpty(pl.origin.CorrelationID),
	}, s.now()); err != nil {
		return err
	}
	return tx.Commit(ctx)
}
