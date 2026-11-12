package activities

// The fourth save Go owns: changing what a scheduled school visit is for
// from My Plan's Edit drawer (docs/migration/31), exactly 31.1's case: its
// goal and expected outcome, with its day, school, purpose and focus left as
// they are. The rules are the view (apps/frontend/views/my_plan_views.py
// edit_activity_action), the edit (apps/activities/editing.py edit) and the
// patch it ends in (apps/activities/services.py patch_activity) for that
// case, in their order (31.3). Such an edit moves no money, so nothing is
// asked of the pricing; anything that would move money or rewrite the SSA
// verdict (a new day, school, purpose or focus) is handed on.

import (
	"context"
	"errors"
	"fmt"
	"net/url"
	"slices"
	"sort"
	"strings"
	"time"
	"unicode"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/audit"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// The edit's own words (editing.py 328 and 393) and the action the view's
// error_fragment names before them (my_plan_views.py edit_activity_action).
const (
	editDateReason    = "Give the reason the date is changing."
	editPurposeReason = "Give the reason the purpose of this visit is changing."
	// EditErrorTitle is error_fragment's prefix for a refused edit.
	EditErrorTitle = "Activity not saved: "
)

// editKeys are the form names the view reads (edit_activity_action), each
// with the key the edit sees. scheduled_date (and end_date) count only when
// they carry a value; every other name counts whenever it is posted.
var editKeys = map[string]string{
	"scheduled_date": "scheduledDate", "end_date": "endDate",
	"activity_purpose_text": "activityPurposeText", "expected_outcome": "expectedOutcome",
	"focus_intervention": "focusIntervention", "facilitating_partner_id": "facilitatingPartnerId",
	"school_id": "schoolId", "project_id": "projectId", "training_course_id": "trainingCourseId",
	"purpose_type": "purposeType", "purpose_training_course_id": "purposeTrainingCourseId",
}

// editFormFields are the names an edit of 31.1's case may post: the
// drawer's fields for a visit to one client school. A posted project,
// training, facilitator, end date or invitation list names another case.
var editFormFields = map[string]bool{
	"csrfmiddlewaretoken": true, "reason": true, "scheduled_date": true, "school_id": true,
	"purpose_type": true, "purpose_training_course_id": true, "focus_intervention": true,
	"activity_purpose_text": true, "expected_outcome": true,
}

// EditRequest is the Edit drawer's fields as posted (activities.proto
// EditSchoolVisitRequest): Posted holds each form name the drawer sent, by
// name, stripped as the view strips it. A name absent was not posted.
type EditRequest struct {
	ActivityID string
	Posted     map[string]string
	Reason     string
}

// EditAnswer is the edited visit and the toast the web shows.
type EditAnswer struct {
	ActivityID, Status, Goal, Outcome, Message string
}

// EditRequestFromForm reads the drawer's form for the activity; false when
// Go does not take it (a field outside 31.1's case, or a name posted twice,
// which the view would read by its last value).
func EditRequestFromForm(activityID string, form url.Values) (EditRequest, bool) {
	posted := map[string]string{}
	for name, values := range form {
		if len(values) != 1 {
			return EditRequest{}, false
		}
		if !editFormFields[name] {
			return EditRequest{}, false
		}
		if name != "csrfmiddlewaretoken" && name != "reason" {
			posted[name] = pyStrip(values[0])
		}
	}
	if posted["purpose_training_course_id"] != "" {
		return EditRequest{}, false
	}
	return EditRequest{ActivityID: activityID, Posted: posted, Reason: pyStrip(form.Get("reason"))}, true
}

// pyStrip is Python's str.strip(): Go's spaces and the four separators
// (U+001C–U+001F) Python also counts as whitespace.
func pyStrip(s string) string {
	return strings.TrimFunc(s, func(r rune) bool { return unicode.IsSpace(r) || (r >= 0x1c && r <= 0x1f) })
}

// editedVisit is the visit as an edit reads it.
type editedVisit struct {
	moved
	focus, schoolCode string
}

// editPlan is everything decided before the transaction.
type editPlan struct {
	p      auth.Principal
	a      editedVisit
	req    EditRequest
	fields []string
	origin Origin
	now    time.Time
}

// Edit makes the edit, or refuses it in the existing words (with the view's
// failure row), or hands it on (ErrHandOn). A hand-on writes nothing.
func (s *Service) Edit(ctx context.Context, p auth.Principal, req EditRequest, origin Origin) (EditAnswer, error) {
	pl, err := s.prepareEdit(ctx, p, req, origin)
	var refusal *Refusal
	if errors.As(err, &refusal) && pl != nil {
		s.auditEdit(ctx, pl, false, refusal.Message)
	}
	if err != nil {
		return EditAnswer{}, err
	}
	wrote, err := s.writeEdit(ctx, pl)
	if err != nil {
		return EditAnswer{}, err
	}
	s.afterEdit(ctx, pl, wrote)
	return EditAnswer{ActivityID: pl.a.id, Status: pl.a.status, Goal: req.Posted["activity_purpose_text"],
		Outcome: req.Posted["expected_outcome"], Message: rules.Move.SavedMessage}, nil
}

// prepareEdit is the view and `editing.edit` up to its transaction (445).
// A refusal comes back with the plan, for the view's failure row.
func (s *Service) prepareEdit(ctx context.Context, p auth.Principal, req EditRequest, origin Origin) (*editPlan, error) {
	now := s.now()
	if p.InActingAppointment || p.StaffProfileID == "" || in(rules.Doors.Requesters, p.ActiveRole) {
		return nil, handOn("not the owner editing their own visit")
	}
	for name := range req.Posted {
		if !editFormFields[name] {
			return nil, handOn("a field outside the edit of a visit's words")
		}
	}
	if req.Posted["purpose_training_course_id"] != "" {
		return nil, handOn("a training named for the visit")
	}
	a, err := editVisit(ctx, s.db, strings.TrimSpace(req.ActivityID))
	if err != nil {
		return nil, err
	}
	if a == nil || a.responsible != p.StaffProfileID || !in(movableStatuses, a.status) ||
		!in(inScopePurposes, a.purpose) || rules.Purposes.ActivityTypes[a.purpose] != a.activityType {
		return nil, handOn("not a scheduled visit of the first save's kind, owned by the person")
	}
	sc, err := schoolByIDOrCode(ctx, s.db, a.schoolID)
	if err != nil {
		return nil, err
	}
	if sc == nil || sc.ID != a.schoolID || in(rules.Gate.CoreRuleTypes, sc.Type) {
		return nil, handOn("a Core school, or no school")
	}
	scope, err := schooldirectory.ResolveScope(ctx, s.db, p, now)
	if err != nil {
		return nil, handOn("no scope: " + err.Error())
	}
	owner, err := schoolOwner(ctx, s.db, sc.ID)
	if err != nil {
		return nil, err
	}
	if !slices.Contains(scope.OwnSchoolIDs, sc.ID) || owner != p.StaffProfileID {
		return nil, handOn("outside the person's own portfolio")
	}
	a.schoolCode = sc.Code
	pl := &editPlan{p: p, a: *a, req: req, fields: editedFields(req.Posted), origin: origin, now: now}
	return pl, s.judgeEdit(pl)
}

// judgeEdit is editing.edit's own reading of the form (275–443) for a visit
// that passed the gates: the refusals Go makes, and what it hands on.
func (s *Service) judgeEdit(pl *editPlan) error {
	posted, reason := pl.req.Posted, pl.req.Reason
	// The day (275–287): _parse_date, then the Kampala day against the plan's.
	dateMoves := false
	if raw := posted["scheduled_date"]; raw != "" {
		if !isoDate.MatchString(raw) {
			return handOn("a date in another form")
		}
		day, err := time.ParseInLocation(time.DateOnly, raw, s.kampala)
		if err != nil {
			return refuse("Invalid date: %s", raw)
		}
		dateMoves = !sameDay(day, pl.a.plannedDate)
	}
	// Another school (289–311): its own lookup and refusals are handed on.
	if wanted, ok := posted["school_id"]; ok && wanted != "" && wanted != pl.a.schoolID && wanted != pl.a.schoolCode {
		return handOn("another school")
	}
	// The day's reason (328), met before the purpose and the focus.
	if dateMoves && reason == "" {
		return refuse("%s", editDateReason)
	}
	if dateMoves {
		return handOn("a new day (the move's rules)")
	}
	purpose, purposePosted := posted["purpose_type"]
	purposeMoves := purposePosted && purpose != pl.a.purpose
	// The purpose's reason (393), when nothing before it refused.
	if purposeMoves && reason == "" {
		return refuse("%s", editPurposeReason)
	}
	if purposeMoves {
		return handOn("another purpose")
	}
	// A new focus re-judges the plan against the SSA (plan_alignment.rejudge).
	if focus, ok := posted["focus_intervention"]; ok && focus != pl.a.focus {
		return handOn("another focus intervention")
	}
	return nil
}

// editedFields is the view's audit payload "fields": the edit's keys for
// what was posted, sorted, the reason left out.
func editedFields(posted map[string]string) []string {
	fields := []string{}
	for name, value := range posted {
		key, ok := editKeys[name]
		if !ok || ((name == "scheduled_date" || name == "end_date") && value == "") {
			continue
		}
		fields = append(fields, key)
	}
	sort.Strings(fields)
	return fields
}

// editVisit reads the visit as movedVisit does, with its focus.
func editVisit(ctx context.Context, q Querier, id string) (*editedVisit, error) {
	a, err := movedVisit(ctx, q, id)
	if err != nil || a == nil {
		return nil, err
	}
	var focus *string
	if err := q.QueryRow(ctx, `SELECT focus_intervention FROM activity WHERE id = $1`, a.id).Scan(&focus); err != nil {
		return nil, fmt.Errorf("activities: reading the visit's focus: %w", err)
	}
	return &editedVisit{moved: *a, focus: text(focus)}, nil
}

// writeEdit is patch_activity's save (6820–6861) for the posted words: the
// activity's row locked, checked unchanged since it was read, and its goal
// and expected outcome written. It answers whether a row was saved: with
// neither posted, patch_activity saves nothing.
func (s *Service) writeEdit(ctx context.Context, pl *editPlan) (bool, error) {
	goal, hasGoal := pl.req.Posted["activity_purpose_text"]
	outcome, hasOutcome := pl.req.Posted["expected_outcome"]
	if !hasGoal && !hasOutcome {
		return false, nil
	}
	tx, err := s.db.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite, IsoLevel: pgx.ReadCommitted})
	if err != nil {
		return false, fmt.Errorf("activities: opening the edit: %w", err)
	}
	defer func() { _ = tx.Rollback(ctx) }()
	var status string
	var purpose, focus *string
	var planned *time.Time
	if err := tx.QueryRow(ctx, `SELECT status, purpose_type, focus_intervention, planned_date FROM activity
WHERE id = $1 AND deleted_at IS NULL FOR UPDATE`, pl.a.id).Scan(&status, &purpose, &focus, &planned); err != nil {
		return false, fmt.Errorf("activities: locking the visit: %w", err)
	}
	if status != pl.a.status || text(purpose) != pl.a.purpose || text(focus) != pl.a.focus ||
		planned == nil || !sameDay(*planned, pl.a.plannedDate) {
		return false, handOn("the visit changed before its lock")
	}
	set := []string{}
	args := []any{pl.a.id, s.now()}
	if hasGoal {
		args = append(args, goal)
		set = append(set, fmt.Sprintf("activity_purpose_text = $%d", len(args)))
	}
	if hasOutcome {
		args = append(args, outcome)
		set = append(set, fmt.Sprintf("expected_outcome = $%d", len(args)))
	}
	// #nosec G202 -- only the fixed column names above are joined.
	if _, err := tx.Exec(ctx, `UPDATE activity SET `+strings.Join(set, ", ")+`, updated_at = $2 WHERE id = $1`,
		args...); err != nil {
		return false, fmt.Errorf("activities: editing the visit: %w", err)
	}
	if err := tx.Commit(ctx); err != nil {
		return false, fmt.Errorf("activities: committing the edit: %w", err)
	}
	return true, nil
}

// afterEdit is what follows the commit, in the existing order: the ledger's
// mark and the live announcement (both on the save's commit, when a row was
// saved), then the view's edit_activity row. None of it can undo the edit.
func (s *Service) afterEdit(ctx context.Context, pl *editPlan, wrote bool) {
	if wrote && in(rules.LedgerCreditedTypes, pl.a.activityType) {
		if err := s.markOwnerYears(ctx, pl.a.responsible, pl.a.plannedDate); err != nil {
			s.logger.Warn("activities: the target ledger was not marked", "activity", pl.a.id, "err", err)
		}
	}
	if wrote {
		if teller, ok := s.pricing.(Announcer); ok {
			if err := teller.Announce(ctx, pl.a.id); err != nil {
				s.logger.Warn("activities: the edit was not announced", "activity", pl.a.id, "err", err)
			}
		}
	}
	s.auditEdit(ctx, pl, true, "")
}

// auditEdit is the view's `edit_activity` row (edit_activity_action: a
// refusal carries its words and no payload; an edit the fields, the reason
// and the activity), with the stamps log() adds.
func (s *Service) auditEdit(ctx context.Context, pl *editPlan, success bool, reason string) {
	if err := s.appendEditRow(ctx, pl, success, reason); err != nil {
		s.logger.Warn("activities: the edit audit row was not written", "activity", pl.a.id, "err", err)
	}
}

func (s *Service) appendEditRow(ctx context.Context, pl *editPlan, success bool, reason string) error {
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
	var payload any
	if success {
		fields := make([]any, len(pl.fields))
		for i, f := range pl.fields {
			fields[i] = f
		}
		payload = withStamps(map[string]any{
			"fields": fields, "reason": pl.req.Reason, "result_activity_id": pl.a.id,
		}, cover)
	} else if cover != nil {
		payload = withStamps(map[string]any{}, cover)
	}
	if _, err := audit.Append(ctx, tx, audit.Entry{
		Action: "edit_activity", SubjectKind: audit.Text("Activity"), SubjectID: audit.Text(pl.a.id),
		ActorID: audit.Text(pl.p.UserID), ActorRole: &role, Success: success, Reason: nilIfEmpty(reason),
		Payload: payload, IPAddress: nilIfEmpty(pl.origin.IP), UserAgent: nilIfEmpty(pl.origin.UserAgent),
		CorrelationID: nilIfEmpty(pl.origin.CorrelationID),
	}, s.now()); err != nil {
		return err
	}
	return tx.Commit(ctx)
}
