package activities

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"math"
	"net/url"
	"regexp"
	"slices"
	"strconv"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgconn"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/audit"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/cuid"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// The SSA drawer on a visit (my_plan_views.ssa_evidence_upload_action and
// apps.ssa.services.upload) for an officer's own staff school visit: eight
// scores keyed pending, dated by the visit, the school's readiness
// recomputed. Scores keyed on a visit a lead already approved, which are
// confirmed as they are keyed, are handed on.

const (
	ssaNotNumeric     = "Error: Score must be numeric"
	ssaNeedsAll       = "Error: All 8 scores must be provided if manual entry is selected."
	ssaOtherSchool    = "These scores belong to a visit at another school. Record them on that school's visit."
	ssaAlreadyKept    = "The SSA scores recorded on this visit are already confirmed. Ask Impact Assessment to return them if they need correcting."
	ssaYearConstraint = "uniq_live_ssa_school_fy"
	ssaScoreCount     = 8
)

var (
	// ssaFields are the drawer's fields Go takes: the eight scores and notes.
	ssaOtherFields = []string{"csrfmiddlewaretoken", "notes"}
	// pyFloatForm is what Python's float() reads that Go's ParseFloat reads
	// the same way: a sign, digits with an optional point, an exponent.
	pyFloatForm = regexp.MustCompile(`^[+-]?([0-9]+(\.[0-9]*)?|\.[0-9]+)([eE][+-]?[0-9]+)?$`)
	// ssaApprovedStatuses are completion_columns.APPROVED_STATUSES: a lead's
	// approval confirms the scores keyed on the visit as they are keyed.
	ssaApprovedStatuses = []string{"ia_verified", "accountant_confirmed", "closed"}
)

type visitScore struct {
	intervention string
	score        float64
}

// visitScoresOf is the view's score loop: none, or all eight in the
// canonical order; a refusal in the view's own words otherwise.
func visitScoresOf(form url.Values) ([]visitScore, string, error) {
	var scores []visitScore
	for _, code := range rules.order {
		raw := pyStrip(form.Get("score_" + code))
		if raw == "" {
			continue
		}
		if !pyFloatForm.MatchString(raw) {
			lower := strings.ToLower(raw)
			if strings.Contains(lower, "inf") || strings.Contains(lower, "nan") || strings.Contains(raw, "_") {
				return nil, "", handOn("a score in a form Go does not read as Python does")
			}
			return nil, ssaNotNumeric, nil
		}
		value, err := strconv.ParseFloat(raw, 64)
		if err != nil || math.IsInf(value, 0) {
			return nil, "", handOn("a score Go does not read as Python does")
		}
		scores = append(scores, visitScore{intervention: code, score: value})
	}
	if len(scores) > 0 && len(scores) < ssaScoreCount {
		return nil, ssaNeedsAll, nil
	}
	return scores, "", nil
}

// scoreRangeRefusal is upload's 0 to 10 rule, for the first score outside it.
func scoreRangeRefusal(scores []visitScore) string {
	for _, s := range scores {
		if s.score < 0 || s.score > 10 {
			return fmt.Sprintf("Score for %s must be between 0 and 10", s.intervention)
		}
	}
	return ""
}

// ssaQuarter is get_quarter_for_date on the assessment's calendar day.
func ssaQuarter(day time.Time) string {
	switch m := day.Month(); {
	case m >= time.October:
		return "Q1"
	case m <= time.March:
		return "Q2"
	case m <= time.June:
		return "Q3"
	}
	return "Q4"
}

// ssaAverage is round(mean, 1), Python's rounding of the exact float.
func ssaAverage(scores []visitScore) float64 {
	sum := 0.0
	for _, s := range scores {
		sum += s.score
	}
	rounded, _ := strconv.ParseFloat(strconv.FormatFloat(sum/float64(len(scores)), 'f', 1, 64), 64)
	return rounded
}

func ssaSequenceRefusal(fy string) string {
	n, _ := strconv.Atoi(fy)
	return fmt.Sprintf("Cannot upload SSA for the current FY (%s) — the previous FY (%d) SSA for this school exists but is not verified. Verify it first.", fy, n-1)
}

func ssaDuplicateMessage(fy string) string {
	return fmt.Sprintf("SSA already exists for this school for FY%s. The record was not added.", fy)
}

// ssaVisitDay is visit_assessment_date: the delivery day, else the day work
// started in the platform's zone, else the planned day.
func ssaVisitDay(delivered, started *time.Time, planned time.Time, zone *time.Location) time.Time {
	switch {
	case delivered != nil:
		return *delivered
	case started != nil:
		local := started.In(zone)
		return time.Date(local.Year(), local.Month(), local.Day(), 0, 0, 0, 0, time.UTC)
	}
	return planned
}

// ssaVisit is what the save reads of the visit beyond the completion read.
type ssaVisit struct {
	delivered, started *time.Time
	schoolCode         string
}

func readSSAVisit(ctx context.Context, q Querier, activityID string) (ssaVisit, error) {
	var v ssaVisit
	err := q.QueryRow(ctx, `SELECT a.actual_delivery_date, a.execution_started_at, s.school_id
  FROM activity a JOIN school s ON s.id = a.school_id WHERE a.id = $1`, activityID).Scan(&v.delivered, &v.started, &v.schoolCode)
	if err != nil {
		return v, fmt.Errorf("activities: reading the visit's day: %w", err)
	}
	return v, nil
}

// KeyVisitSSA keeps the drawer's scores, or refuses them in the existing
// words, or hands the save on (ErrHandOn).
func (s *Service) KeyVisitSSA(ctx context.Context, p auth.Principal, activityID string, form url.Values, origin Origin) (Answer, error) {
	for name, values := range form {
		if !strings.HasPrefix(name, "score_") && !slices.Contains(ssaOtherFields, name) &&
			slices.ContainsFunc(values, func(v string) bool { return strings.TrimSpace(v) != "" }) {
			return Answer{}, handOn("the drawer posted " + name)
		}
	}
	if p.InActingAppointment || p.StaffProfileID == "" || p.ActiveRole != officerRole || slices.Contains(p.Roles, programmeLeadRole) {
		return Answer{}, handOn("not an officer keying their own visit's SSA")
	}
	a, err := readCompletedVisit(ctx, s.db, strings.TrimSpace(activityID))
	if err != nil {
		return Answer{}, err
	}
	switch {
	case a == nil:
		return Answer{}, handOn("not a staff school visit with a school and a day")
	case a.other:
		return Answer{}, handOn("a visit in a cluster, a project, a pair or a partner's hands")
	case a.responsible != p.StaffProfileID:
		return Answer{}, handOn("someone else's visit")
	case slices.Contains(ssaApprovedStatuses, a.status):
		return Answer{}, handOn("a visit its lead approved: the scores are confirmed as they are keyed")
	}
	now := s.now()
	if err := s.ownVisitSchool(ctx, p, a.schoolID, now); err != nil {
		return Answer{}, err
	}
	scores, refusal, err := visitScoresOf(form)
	if err != nil {
		return Answer{}, err
	}
	if refusal != "" {
		return Answer{}, refuse("%s", refusal)
	}
	if len(scores) > 0 {
		if err := s.keyScores(ctx, p, a, scores, now, origin); err != nil {
			return Answer{}, err
		}
	}
	if err := s.auditSSAUpload(ctx, p, a.id, pyStrip(form.Get("notes")), origin); err != nil {
		s.logger.Warn("activities: the SSA upload's audit row was not written", "activity", a.id, "err", err)
	}
	return Answer{ActivityID: a.id, Message: rules.Move.SavedMessage}, nil
}

// keyScores is apps.ssa.services.upload for the visit's scores.
func (s *Service) keyScores(ctx context.Context, p auth.Principal, a *completedVisit, scores []visitScore, now time.Time, origin Origin) error {
	if refusal := scoreRangeRefusal(scores); refusal != "" {
		return refuse("%s", refusal)
	}
	v, err := readSSAVisit(ctx, s.db, a.id)
	if err != nil {
		return err
	}
	day := ssaVisitDay(v.delivered, v.started, a.plannedDate, s.kampala)
	fy := schooldirectory.OperationalFY(day)
	operational := schooldirectory.OperationalFY(now)
	if fy == operational {
		blocked, err := previousYearUnverified(ctx, s.db, a.schoolID, fy)
		if err != nil {
			return err
		}
		if blocked {
			return refuse("%s", ssaSequenceRefusal(fy))
		}
	}
	// The assessment is the day's local midnight (_parse_date, make_aware).
	assessed := time.Date(day.Year(), day.Month(), day.Day(), 0, 0, 0, 0, s.kampala)
	average := ssaAverage(scores)
	rows := make([]map[string]any, len(scores))
	byIntervention := map[string]any{}
	for i, sc := range scores {
		rows[i] = map[string]any{"id": cuid.New(), "intervention": sc.intervention, "score": sc.score}
		byIntervention[sc.intervention] = sc.score
	}
	payload, err := json.Marshal(rows)
	if err != nil {
		return fmt.Errorf("activities: encoding the scores: %w", err)
	}
	tx, err := s.db.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite, IsoLevel: pgx.ReadCommitted})
	if err != nil {
		return fmt.Errorf("activities: opening the SSA: %w", err)
	}
	defer func() { _ = tx.Rollback(ctx) }()
	var answer string
	err = tx.QueryRow(ctx, `SELECT gateway_ssa_entry.key_visit_ssa($1, $2, $3, $4, $5, $6, $7, $8, $9::jsonb, $10, $11)`,
		a.schoolID, a.id, cuid.New(), assessed, fy, ssaQuarter(day), average, p.UserID, string(payload), now, operational).Scan(&answer)
	var pgErr *pgconn.PgError
	if errors.As(err, &pgErr) && pgErr.Code == uniqueViolation && pgErr.ConstraintName == ssaYearConstraint {
		return refuse("%s", ssaDuplicateMessage(fy))
	}
	if err != nil {
		return fmt.Errorf("activities: keying the SSA: %w", err)
	}
	record, wasCreated := strings.CutPrefix(answer, "created:")
	if !wasCreated {
		var ok bool
		if record, ok = strings.CutPrefix(answer, "rekeyed:"); !ok {
			switch answer {
			case "other_school":
				return refuse("%s", ssaOtherSchool)
			case "confirmed":
				return refuse("%s", ssaAlreadyKept)
			case "year":
				return refuse("%s", ssaDuplicateMessage(fy))
			}
			return handOn("the SSA met " + answer)
		}
	}
	if err := tx.Commit(ctx); err != nil {
		return fmt.Errorf("activities: committing the SSA: %w", err)
	}
	action, data := "ssa_rekeyed", map[string]any{"schoolId": a.schoolID, "sourceActivityId": a.id}
	if wasCreated {
		action, data = "ssa_create", map[string]any{
			"schoolId": a.schoolID, "fy": fy, "dateOfSsa": day.Format(time.DateOnly), "averageScore": average,
			"scores": byIntervention, "source": "staff_keyed", "channel": "", "sourceActivityId": a.id,
		}
	}
	if err := s.auditSSARecord(ctx, p, action, record, data, origin); err != nil {
		s.logger.Warn("activities: the SSA's audit row was not written", "record", record, "err", err)
	}
	// ledger_sync: a saved SSA marks its collector's ledger for its year.
	if err := s.markOwnerYears(ctx, p.UserID, day); err != nil {
		s.logger.Warn("activities: the target ledger was not marked", "record", record, "err", err)
	}
	return nil
}

// previousYearUnverified is upload's sequence rule: a previous year's record
// exists for the school and none of it is confirmed.
func previousYearUnverified(ctx context.Context, q Querier, schoolID, fy string) (bool, error) {
	n, err := strconv.Atoi(fy)
	if err != nil {
		return false, fmt.Errorf("activities: reading the SSA's year: %w", err)
	}
	var anyRecord, confirmed bool
	err = q.QueryRow(ctx, `SELECT
  EXISTS (SELECT 1 FROM ssa_record WHERE school_id = $1 AND fy = $2 AND deleted_at IS NULL),
  EXISTS (SELECT 1 FROM ssa_record WHERE school_id = $1 AND fy = $2 AND deleted_at IS NULL AND verification_status = 'confirmed')`,
		schoolID, strconv.Itoa(n-1)).Scan(&anyRecord, &confirmed)
	if err != nil {
		return false, fmt.Errorf("activities: reading the previous year's SSA: %w", err)
	}
	return anyRecord && !confirmed, nil
}

func (s *Service) auditSSARecord(ctx context.Context, p auth.Principal, action, recordID string, payload map[string]any, origin Origin) error {
	return s.appendAudit(ctx, p, audit.Entry{
		Action: action, SubjectKind: audit.Text("SsaRecord"), SubjectID: audit.Text(recordID),
		ActorID: audit.Text(p.UserID), ActorRole: audit.Text(p.ActiveRole), Success: true,
	}, payload, origin)
}

func (s *Service) auditSSAUpload(ctx context.Context, p auth.Principal, activityID, notes string, origin Origin) error {
	return s.appendAudit(ctx, p, audit.Entry{
		Action: "upload_ssa", SubjectKind: audit.Text("Activity"), SubjectID: audit.Text(activityID),
		ActorID: audit.Text(p.UserID), ActorRole: audit.Text(p.ActiveRole), Success: true,
		Reason: audit.Text("SSA scores or form uploaded"),
	}, map[string]any{"notes": notes}, origin)
}

// appendAudit writes one audit row with the actor's coverage stamps.
func (s *Service) appendAudit(ctx context.Context, p auth.Principal, entry audit.Entry, payload map[string]any, origin Origin) error {
	tx, err := s.db.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite})
	if err != nil {
		return err
	}
	defer func() { _ = tx.Rollback(ctx) }()
	cover, err := coverageStamp(ctx, tx, p.UserID, s.now())
	if err != nil {
		return err
	}
	entry.Payload = withStamps(payload, cover)
	entry.IPAddress, entry.UserAgent, entry.CorrelationID = nilIfEmpty(origin.IP), nilIfEmpty(origin.UserAgent), nilIfEmpty(origin.CorrelationID)
	if _, err := audit.Append(ctx, tx, entry, s.now()); err != nil {
		return err
	}
	return tx.Commit(ctx)
}
