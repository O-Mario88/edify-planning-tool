package activities

// Completing an officer's own staff In-school Training pair, the training
// and its school visit together, from My Plan's Complete drawer, with the
// existing application absent (my_plan_views.complete_activity_action for a
// pair → start_in_school_training_pair, _record_completion_ssa on the visit,
// complete_in_school_training_pair: complete(training) then complete(visit)).
// Both halves are handed in in one transaction, as the existing pair's
// atomic block holds them. A pair whose visit collects the SSA, done on
// another day than planned, or anything else unusual is handed on.

import (
	"context"
	"errors"
	"fmt"
	"net/url"
	"regexp"
	"slices"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgconn"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/audit"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/cuid"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/myplan"
)

const (
	inSchoolTrainingType  = "in_school_training"
	pairAuditAction       = "complete_in_school_training_pair"
	trainingRecordTypeKey = "TRAINING"
)

// pairHandedOnFields take a pair's completion out of Go's case.
var pairHandedOnFields = []string{"training_salesforce_id", "feedback_finding", "school_improvements",
	"attended_school_ids", "visiting_school_ids", "training_course_id"}

// completedPair is the pair as its completion reads it.
type completedPair struct {
	training, visit completedVisit
	name            string // the training's name, the drawer's subtitle
}

// readPairHalf reads one half: an activity at a school, staff's, outside a
// cluster, project, partner's hands or a monitor, not a OneTest visit.
func readPairHalf(ctx context.Context, q Querier, id string) (*completedVisit, string, error) {
	var a completedVisit
	var purpose, school, responsible, verification, recordType, costing, salesforce, name *string
	var planned *time.Time
	err := q.QueryRow(ctx, `
SELECT a.id, a.activity_type, a.status, a.purpose_type, a.school_id, a.responsible_staff_id, a.planned_date,
       a.ia_verification_status, a.salesforce_record_type_snapshot, a.costing_profile_snapshot,
       a.salesforce_activity_id, a.ssa_collection_expected, a.activity_name_snapshot,
       (a.cluster_id IS NOT NULL OR a.project_id IS NOT NULL OR a.assigned_partner_id IS NOT NULL
        OR a.delivery_type IS DISTINCT FROM 'staff' OR a.monitored_by_staff_id IS NOT NULL OR a.end_date IS NOT NULL
        OR EXISTS (SELECT 1 FROM activity_catalogue_item c WHERE c.id = a.catalogue_item_id
                   AND c.costing_profile = 'ONETEST'))
FROM activity a WHERE a.id = $1 AND a.deleted_at IS NULL`, id).Scan(
		&a.id, &a.activityType, &a.status, &purpose, &school, &responsible, &planned,
		&verification, &recordType, &costing, &salesforce, &a.collectsSSA, &name, &a.other)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, "", nil
	}
	if err != nil {
		return nil, "", fmt.Errorf("activities: reading a half of the pair: %w", err)
	}
	if school == nil || planned == nil {
		return nil, "", nil
	}
	a.purpose, a.schoolID, a.responsible = text(purpose), text(school), text(responsible)
	a.verification, a.recordType, a.costing = text(verification), text(recordType), text(costing)
	a.salesforceID, a.plannedDate = text(salesforce), *planned
	return &a, text(name), nil
}

// readCompletedPair resolves the pair from either half (in_school_training_pair).
func readCompletedPair(ctx context.Context, q Querier, id string) (*completedPair, error) {
	var trainingID, visitID string
	err := q.QueryRow(ctx, `
SELECT t.id, v.id FROM activity t JOIN activity v ON v.id = t.paired_school_visit_id
WHERE (t.id = $1 OR v.id = $1) AND t.activity_type = $2 AND v.activity_type = $3
  AND t.deleted_at IS NULL AND v.deleted_at IS NULL
ORDER BY t.id LIMIT 1`, id, inSchoolTrainingType, plainSchoolVisit).Scan(&trainingID, &visitID)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, nil
	}
	if err != nil {
		return nil, fmt.Errorf("activities: reading the pair: %w", err)
	}
	training, name, err := readPairHalf(ctx, q, trainingID)
	if err != nil {
		return nil, err
	}
	visit, _, err := readPairHalf(ctx, q, visitID)
	if err != nil || training == nil || visit == nil {
		return nil, err
	}
	if name == "" {
		name = myplan.TypeLabel(inSchoolTrainingType)
	}
	return &completedPair{training: *training, visit: *visit, name: name}, nil
}

// outOfCase says why the pair is not Go's case ("" when it is).
func (pr *completedPair) outOfCase(p auth.Principal) string {
	t, v := &pr.training, &pr.visit
	startedOrStartable := func(status string) bool { return status == startedStatus || in(startableStatuses, status) }
	switch {
	case t.other || v.other:
		return "a half in a cluster, a project, a partner's hands, monitored, multi-day or a OneTest visit"
	case t.schoolID != v.schoolID:
		return "a pair at two schools"
	case !ownsVisit(p, t.responsible) || !ownsVisit(p, v.responsible):
		return "someone else's pair"
	case !startedOrStartable(t.status) || !startedOrStartable(v.status):
		return "a pair in status " + t.status + "/" + v.status
	case t.verification == confirmedVerification || v.verification == confirmedVerification:
		return "a pair IA has confirmed"
	case t.salesforceID != "" || v.salesforceID != "":
		return "a pair holding a Salesforce ID"
	case !in([]string{"", trainingRecordTypeKey}, strings.ToUpper(t.recordType)) ||
		!in(visitRecordTypes, strings.ToUpper(v.recordType)) || v.costing == onetestCostingProfile:
		return "a pair kept under another Salesforce record type"
	case v.collectsSSA || v.purpose == ssaSupportPurpose:
		return "a pair whose visit collects the SSA"
	case !sameDay(t.plannedDate, v.plannedDate):
		return "a pair planned on two days"
	}
	return ""
}

// pairInCase reads the pair id names and decides whether Go completes it.
func (s *Service) pairInCase(ctx context.Context, p auth.Principal, id string) (*completedPair, error) {
	if !officerOwn(p) {
		if !s.completesOwnVisit(p) {
			return nil, handOn("not an officer completing their own pair")
		}
		// A lead completes their own visit in Go; their pairs are handed on.
		pr, err := readCompletedPair(ctx, s.db, id)
		if err != nil || pr == nil {
			return nil, err
		}
		return nil, handOn("a lead's own pair")
	}
	pr, err := readCompletedPair(ctx, s.db, id)
	if err != nil || pr == nil {
		return nil, err
	}
	if why := pr.outOfCase(p); why != "" {
		return nil, handOn(why)
	}
	if err := s.ownVisitSchool(ctx, p, pr.training.schoolID, s.now()); err != nil {
		return nil, err
	}
	ownerUID, err := fundingOwner(ctx, s.db, pr.training.responsible, p.UserID)
	if err != nil {
		return nil, err
	}
	for _, half := range []string{pr.training.id, pr.visit.id} {
		why, err := moveNotices(ctx, s.db, half, ownerUID)
		if err != nil {
			return nil, err
		}
		if why != "" {
			return nil, handOn(why)
		}
	}
	return pr, nil
}

// pairCompletion is a pair's completion, decided before its transaction.
type pairCompletion struct {
	completionPlan        // the training half, and what both share
	pair                  *completedPair
	visitRaw, visitNormed string
}

// completePair is Complete for a pair.
func (s *Service) completePair(ctx context.Context, p auth.Principal, pr *completedPair, form url.Values, origin Origin) (CompleteAnswer, error) {
	pp := &pairCompletion{pair: pr}
	pp.completionPlan = completionPlan{p: p, a: pr.training, origin: origin, now: s.now(), sessions: true}
	if err := s.readPairForm(ctx, pp, form); err != nil {
		return CompleteAnswer{}, err
	}
	if err := s.writePairCompletion(ctx, pp); err != nil {
		return CompleteAnswer{}, err
	}
	s.afterPairCompletion(ctx, pp)
	return CompleteAnswer{ActivityID: pr.training.id, Status: handedInStatus, Message: rules.Move.SavedMessage}, nil
}

// readPairForm is what the view and the two completions read, in their
// order: the day, the SSA on the visit, the training's attendance and ID,
// then the visit's ID.
func (s *Service) readPairForm(ctx context.Context, pp *pairCompletion, form url.Values) error {
	for _, field := range pairHandedOnFields {
		if form.Has(field) {
			return handOn("the drawer posted " + field)
		}
	}
	if pyStrip(form.Get("netsuite_id")) != "" || pyStrip(form.Get("purpose_type")) != "" ||
		form.Get("visiting_register") == "1" || pyStrip(form.Get("follow_up_of_activity_id")) != "" {
		return handOn("an accountability, a purpose, a register or a follow-up on a pair")
	}
	delivered, err := s.completedOn(form.Get("actual_delivery_date"))
	if err != nil {
		return err
	}
	if !sameDay(delivered, pp.a.plannedDate) {
		return handOn("a pair done on another day than planned: both halves and their money move")
	}
	pp.delivered = delivered
	counts := make([]int, 0, 3)
	for _, field := range []string{"teachers_attended", "leaders_attended", "other_participants"} {
		n, err := attendance(form, field)
		if err != nil {
			return err
		}
		counts = append(counts, n)
	}
	if counts[2] != 0 {
		return handOn("other participants posted on a pair")
	}
	pp.teachers, pp.leaders = counts[0], counts[1]
	pp.outcome, pp.observations, pp.notes = posted(form, "actual_outcome"), posted(form, "actual_observations"),
		posted(form, "follow_up_note")
	pp.raw = pyStrip(form.Get("salesforce_id"))
	pp.visitRaw = pyStrip(form.Get("visit_salesforce_id"))
	// _record_completion_ssa on the pair's visit: scores marked collected are
	// all eight or the view's notice; none were taken otherwise.
	entered := slices.ContainsFunc(ssaScoreFields, func(field string) bool { return pyStrip(form.Get(field)) != "" })
	if form.Get("ssa_collected") == "yes" && entered {
		scores, refusal, err := completionScoresOf(form)
		if err != nil {
			return err
		}
		if refusal != "" {
			return &Refusal{Message: refusal, Notice: true}
		}
		k, err := s.prepareSSAKey(ctx, &pp.pair.visit, scores, pp.delivered, pp.now)
		if err != nil {
			return asNotice(err)
		}
		pp.ssaScores, pp.ssaKey = scores, k
	}
	pp.payload = completionPayload(&pp.completionPlan, form)
	pp.payload["ssaCollected"] = pp.ssaKey != nil
	pp.payload["visitSalesforceId"] = pp.visitRaw
	pp.payload["paired_school_visit_id"] = pp.pair.visit.id
	// complete(training): a training is completed with someone in the room,
	// then its TS- ID; complete(visit): the visit's ID.
	if pp.teachers <= 0 && pp.leaders <= 0 {
		return refuse("%s", trainingAttendanceAsked)
	}
	if err := s.judgeTrainingID(&pp.completionPlan); err != nil {
		return err
	}
	return pp.judgeVisitID()
}

// judgeVisitID is the visit's reservation format: a TS- ID here is only the
// wrong form, as the pair's view says nothing more of it.
func (pp *pairCompletion) judgeVisitID() error {
	if len(pp.visitRaw) > maxSalesforceRaw {
		return handOn("a Salesforce ID longer than its reference keeps")
	}
	normalized, ok := normalizeSalesforceID(pp.visitRaw)
	if !ok {
		return handOn("a Salesforce ID outside ASCII")
	}
	if !slices.ContainsFunc(salesforceVisitForms, func(form *regexp.Regexp) bool { return form.MatchString(normalized) }) {
		return refuse("%s", salesforceFormsRefusal)
	}
	pp.visitNormed = normalized
	return nil
}

// writePairCompletion is both halves' start, the visit's SSA, and both
// hand-ins, each with its reservation's row, in one transaction.
func (s *Service) writePairCompletion(ctx context.Context, pp *pairCompletion) error {
	tx, err := s.db.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite, IsoLevel: pgx.ReadCommitted})
	if err != nil {
		return fmt.Errorf("activities: opening the pair's completion: %w", err)
	}
	defer func() { _ = tx.Rollback(ctx) }()
	visit := &pp.pair.visit
	if visit.status != startedStatus {
		var started bool
		if err := tx.QueryRow(ctx, `SELECT gateway_completion.start_visit($1, $2)`, visit.id, pp.now).Scan(&started); err != nil {
			return fmt.Errorf("activities: starting the pair's visit: %w", err)
		}
		if !started {
			return handOn("the pair's visit could not be started")
		}
	}
	if pp.ssaKey != nil {
		if err := s.keySSAInTx(ctx, tx, pp.p, visit, pp.ssaKey, pp.now); err != nil {
			return asNotice(err)
		}
		if err := s.appendSSARowFor(ctx, tx, &pp.completionPlan, visit); err != nil {
			return err
		}
	}
	var answer string
	err = tx.QueryRow(ctx, `SELECT gateway_completion.hand_in_school_training($1, $2, $3, $4, $5, $6, $7, $8, $9,
  $10, $11, $12, $13)`,
		pp.a.id, pp.delivered, pp.raw, pp.normalized, pp.teachers, pp.leaders, pp.outcome, pp.observations, pp.notes,
		pp.p.UserID, pp.now, cuid.New(), cuid.New()).Scan(&answer)
	if err := handInAnswer(ctx, tx, err, answer, "the training"); err != nil {
		return err
	}
	if err := s.appendSalesforceRowFor(ctx, tx, pp.p, pp.origin, pp.a.id, pp.normalized); err != nil {
		return err
	}
	err = tx.QueryRow(ctx, `SELECT gateway_completion.hand_in_school_visit($1, $2, $3, $4, $5, $6, $7, $8, $9, $10,
  $11, $12, $13, $14)`,
		visit.id, pp.delivered, pp.visitRaw, pp.visitNormed, 0, 0, 0, pp.outcome, pp.observations, pp.notes,
		pp.p.UserID, pp.now, cuid.New(), cuid.New()).Scan(&answer)
	if err := handInAnswer(ctx, tx, err, answer, "the visit"); err != nil {
		return err
	}
	if err := s.appendSalesforceRowFor(ctx, tx, pp.p, pp.origin, visit.id, pp.visitNormed); err != nil {
		return err
	}
	if err := tx.Commit(ctx); err != nil {
		return fmt.Errorf("activities: committing the pair's completion: %w", err)
	}
	return nil
}

// handInAnswer reads a hand-in function's answer: ” handed in, a held ID
// refused in the existing words, anything else handed on.
func handInAnswer(ctx context.Context, tx pgx.Tx, err error, answer, half string) error {
	var pgErr *pgconn.PgError
	if errors.As(err, &pgErr) && pgErr.Code == uniqueViolation {
		return refuse("%s", salesforceTakenRefusal)
	}
	if err != nil {
		return fmt.Errorf("activities: handing %s in: %w", half, err)
	}
	if holder, held := strings.CutPrefix(answer, "held:"); held {
		message, err := takenBy(ctx, tx, holder)
		if err != nil {
			return err
		}
		return refuse("%s", message)
	}
	if answer != "" {
		return handOn(half + "'s hand-in met " + answer)
	}
	return nil
}

// afterPairCompletion is what follows the commit, in the existing order:
// each half's hand-in notices, the view's pair row, then the ledger marks.
func (s *Service) afterPairCompletion(ctx context.Context, pp *pairCompletion) {
	if follower, ok := s.pricing.(CompletionFollower); ok {
		for _, half := range []string{pp.a.id, pp.pair.visit.id} {
			if err := follower.HandedIn(ctx, half, pp.p.UserID, pp.p.ActiveRole); err != nil {
				s.logger.Warn("activities: the hand-in's notices were not sent", "activity", half, "err", err)
			}
		}
	}
	if err := s.appendPairRow(ctx, pp); err != nil {
		s.logger.Warn("activities: the pair's completion audit row was not written", "activity", pp.a.id, "err", err)
	}
	if err := s.markOwnerYears(ctx, pp.a.responsible, pp.a.plannedDate); err != nil {
		s.logger.Warn("activities: the target ledger was not marked", "activity", pp.a.id, "err", err)
	}
	if pp.ssaKey != nil {
		if err := s.markOwnerYears(ctx, pp.p.UserID, pp.ssaKey.day); err != nil {
			s.logger.Warn("activities: the SSA's ledger was not marked", "activity", pp.pair.visit.id, "err", err)
		}
	}
}

// appendPairRow is the view's `complete_in_school_training_pair` row.
func (s *Service) appendPairRow(ctx context.Context, pp *pairCompletion) error {
	tx, err := s.db.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite})
	if err != nil {
		return err
	}
	defer func() { _ = tx.Rollback(ctx) }()
	cover, err := coverageStamp(ctx, tx, pp.p.UserID, s.now())
	if err != nil {
		return err
	}
	role := pp.p.ActiveRole
	if _, err := audit.Append(ctx, tx, audit.Entry{
		Action: pairAuditAction, SubjectKind: audit.Text("Activity"), SubjectID: audit.Text(pp.a.id),
		ActorID: audit.Text(pp.p.UserID), ActorRole: &role, Success: true,
		Payload:   withStamps(pp.payload, cover),
		IPAddress: nilIfEmpty(pp.origin.IP), UserAgent: nilIfEmpty(pp.origin.UserAgent),
		CorrelationID: nilIfEmpty(pp.origin.CorrelationID),
	}, s.now()); err != nil {
		return err
	}
	return tx.Commit(ctx)
}
