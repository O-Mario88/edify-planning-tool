package extrawork

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"regexp"
	"slices"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/activities"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/audit"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/cuid"
)

// Extra Assigned Work's saves (apps.hr.extra_work through
// extra_work_views), with Django absent.

// Refusal is a save the existing service refuses, in its words.
type Refusal struct{ Message string }

func (r *Refusal) Error() string { return r.Message }

func refuse(msg string) error { return &Refusal{Message: msg} }

// SavedMessage is htmx_saved.SAVED_MESSAGE, what every save answers.
const SavedMessage = "Saved. Press Refresh to see it on the page."

// assignerRoles is ASSIGNER_ROLES.
var assignerRoles = []string{"CountryDirector", "Program Lead"}

// categories are ExtraAssignment.CATEGORIES' values.
var categories = []string{"priority_linked", "operational_support", "strategic", "emergency", "cross_team",
	"special_project", "leadership", "non_scoreable_support"}

// ActionPath is extra_work_action's route.
var ActionPath = regexp.MustCompile(`^/extra-work/([A-Za-z0-9_-]{1,30})/(acknowledge|start|submit|return|verify|cancel)/?$`)

// AssignPath is the assign drawer's path, which its save is posted to.
const AssignPath = "/extra-work/assign-drawer"

type saver struct {
	pool   *pgxpool.Pool
	push   activities.NoticePush
	live   activities.NoticePublisher
	logger *slog.Logger
}

// WithSaves lets the service make Extra Assigned Work's saves.
func (s *Service) WithSaves(pool *pgxpool.Pool, push activities.NoticePush, live activities.NoticePublisher, logger *slog.Logger) *Service {
	s.saves = &saver{pool: pool, push: push, live: live, logger: logger}
	return s
}

// Saves reports whether Go makes the saves (the page then offers them).
func (s *Service) Saves() bool { return s.saves != nil }

// operationalFY is get_operational_fy at now (UTC).
func operationalFY(now time.Time) string {
	now = now.UTC()
	if now.Month() >= time.October {
		return fmt.Sprint(now.Year() + 1)
	}
	return fmt.Sprint(now.Year())
}

// orDefault is `value or default` on a trimmed form value.
func orDefault(v, fallback string) string {
	if v = strings.TrimSpace(v); v != "" {
		return v
	}
	return fallback
}

// Assign is create_assignment from the assign drawer (the reviewer is the
// assigner; the view sends none).
func (s *Service) Assign(ctx context.Context, p auth.Principal, v map[string]string, origin activities.Origin) error {
	if s.saves == nil {
		return errors.New("extrawork: no saves")
	}
	if !slices.Contains(assignerRoles, p.ActiveRole) {
		return refuse("Only the Country Director or a Program Lead may assign extra work.")
	}
	assigneeID := strings.TrimSpace(v["assignee_id"])
	var assigneeRole string
	err := s.db.QueryRow(ctx, `SELECT COALESCE(active_role, '') FROM "user" WHERE id = $1 AND is_active`, assigneeID).Scan(&assigneeRole)
	if errors.Is(err, pgx.ErrNoRows) || assigneeID == "" {
		return refuse("Choose an active staff member to assign.")
	}
	if err != nil {
		return fmt.Errorf("extrawork: reading the assignee: %w", err)
	}
	if assigneeID == p.UserID {
		return refuse("You cannot assign extra work to yourself.")
	}
	if p.ActiveRole == "CountryDirector" {
		if assigneeRole != "Program Lead" && assigneeRole != "CCEO" {
			return refuse("The CD assigns extra work to Program Leads and CCEOs.")
		}
	} else {
		if assigneeRole != "CCEO" {
			return refuse("A Program Lead assigns extra work only to CCEOs.")
		}
		var supervises bool
		if err := s.db.QueryRow(ctx, `SELECT EXISTS (SELECT 1 FROM staff_supervisor_assignment ssa
JOIN staff_profile sv ON sv.id = ssa.supervisee_id WHERE ssa.supervisor_id = $1 AND sv.user_id = $2)`,
			p.StaffProfileID, assigneeID).Scan(&supervises); err != nil {
			return fmt.Errorf("extrawork: reading the team: %w", err)
		}
		if !supervises {
			return refuse("A Program Lead may assign extra work only to CCEOs they currently supervise.")
		}
	}
	title, instruction := strings.TrimSpace(v["title"]), strings.TrimSpace(v["instruction"])
	if title == "" {
		return refuse("Give the assignment a title.")
	}
	if instruction == "" {
		return refuse("Write the detailed instruction — the assignee acts on it.")
	}
	rawDue := strings.TrimSpace(v["due_date"])
	if rawDue == "" {
		return refuse("Set a due date.")
	}
	due, err := time.Parse(time.DateOnly, rawDue)
	if err != nil {
		return refuse("Set a due date.")
	}
	category := strings.TrimSpace(v["category"])
	if !slices.Contains(categories, category) {
		return refuse("Choose an assignment category.")
	}
	var lead string
	_ = s.db.QueryRow(ctx, `SELECT COALESCE(sup.user_id, '') FROM staff_supervisor_assignment ssa
JOIN staff_profile sv ON sv.id = ssa.supervisee_id JOIN staff_profile sup ON sup.id = ssa.supervisor_id
WHERE sv.user_id = $1 ORDER BY ssa.id LIMIT 1`, assigneeID).Scan(&lead)
	urgency := orDefault(v["urgency"], "normal")
	now := s.now()
	id := cuid.New()
	tx, err := s.saves.pool.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite})
	if err != nil {
		return fmt.Errorf("extrawork: opening the assignment: %w", err)
	}
	defer func() { _ = tx.Rollback(ctx) }()
	if _, err := tx.Exec(ctx, `INSERT INTO hr_extra_assignment (
  id, created_at, updated_at, fy, title, instruction, reason, category, linked_priority_id, linked_milestone_id,
  linked_activity_id, assigner_id, assigner_role, assignee_id, assignee_role, supervising_pl_id, country, due_date,
  expected_output, output_unit, evidence_required, reviewer_id, complexity, urgency, status, outcome, evidence_note,
  evidence_uri, return_reason, return_count, verified_by, cancel_reason)
VALUES ($1, $2, $2, $3, $4, $5, $6, $7, NULL, $8, '', $9, $10, $11, $12, $13, 'Uganda', $14, $15, '', $16, $9, $17, $18,
  'assigned', '', '', '', '', 0, '', '')`,
		id, now, operationalFY(now), title, instruction, strings.TrimSpace(v["reason"]), category,
		nilIfEmpty(strings.TrimSpace(v["linked_milestone_id"])), p.UserID, p.ActiveRole, assigneeID, assigneeRole, lead, due,
		strings.TrimSpace(v["expected_output"]), v["evidence_required"] == "on", orDefault(v["complexity"], "medium"), urgency); err != nil {
		return fmt.Errorf("extrawork: writing the assignment: %w", err)
	}
	if err := tx.Commit(ctx); err != nil {
		return fmt.Errorf("extrawork: committing the assignment: %w", err)
	}
	priority := "normal"
	if urgency != "normal" {
		priority = "high"
	}
	s.tell(ctx, p, id, origin, "extra_work_assigned", "Extra work assigned to you",
		title+" — due "+due.Format("2 Jan 2006")+". Review and start it.", priority, assigneeID)
	if p.ActiveRole == "CountryDirector" && assigneeRole == "CCEO" && lead != "" {
		s.tell(ctx, p, id, origin, "extra_work_assigned_fyi", "Extra work assigned on your team",
			"The Country Director assigned “"+title+"” to a CCEO you supervise. You can monitor it; the CD owns it.", "normal", lead)
	}
	s.audit(ctx, p, id, "extra_work.assigned", map[string]any{"title": title}, origin)
	return nil
}

func nilIfEmpty(v string) any {
	if v == "" {
		return nil
	}
	return v
}

// assignmentRow is what a transition reads under the row's lock.
type assignmentRow struct {
	title, assigner, assignee, reviewer, lead, status, fy, complexity string
	evidenceRequired                                                  bool
	due                                                               time.Time
	started                                                           *time.Time
	startDate                                                         *time.Time
}

// Act is extra_work_action: one transition by its role's person.
func (s *Service) Act(ctx context.Context, p auth.Principal, id, action string, v map[string]string, origin activities.Origin) error {
	if s.saves == nil {
		return errors.New("extrawork: no saves")
	}
	tx, err := s.saves.pool.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite})
	if err != nil {
		return fmt.Errorf("extrawork: opening the transition: %w", err)
	}
	defer func() { _ = tx.Rollback(ctx) }()
	var a assignmentRow
	err = tx.QueryRow(ctx, `SELECT title, assigner_id, assignee_id, reviewer_id, COALESCE(supervising_pl_id, ''), status, fy,
  COALESCE(complexity, ''), evidence_required, due_date, started_at, start_date
  FROM hr_extra_assignment WHERE id = $1 FOR UPDATE`, id).Scan(&a.title, &a.assigner, &a.assignee, &a.reviewer, &a.lead,
		&a.status, &a.fy, &a.complexity, &a.evidenceRequired, &a.due, &a.started, &a.startDate)
	if errors.Is(err, pgx.ErrNoRows) {
		return refuse("Assignment not found.")
	}
	if err != nil {
		return fmt.Errorf("extrawork: reading the assignment: %w", err)
	}
	if refusal := a.gate(p.UserID, action); refusal != nil {
		return refusal
	}
	now := s.now()
	after, err := s.transition(ctx, tx, a, id, action, v, now, p.UserID)
	if err != nil {
		return err
	}
	if err := tx.Commit(ctx); err != nil {
		return fmt.Errorf("extrawork: committing the transition: %w", err)
	}
	if after != nil {
		after(ctx, p, origin)
	}
	return nil
}

// gate is _get_for: who may take each action.
func (a assignmentRow) gate(userID, action string) error {
	switch action {
	case "acknowledge", "start", "submit":
		if a.assignee != userID {
			return refuse("This assignment is not yours.")
		}
	case "return", "verify":
		if a.reviewer != userID {
			return refuse("You are not the reviewer of this assignment.")
		}
	case "cancel":
		if a.assigner != userID {
			return refuse("You did not assign this work.")
		}
	}
	return nil
}

type afterward func(ctx context.Context, p auth.Principal, origin activities.Origin)

func (s *Service) transition(ctx context.Context, tx pgx.Tx, a assignmentRow, id, action string, v map[string]string,
	now time.Time, actor string) (afterward, error) {
	exec := func(sql string, args ...any) error {
		if _, err := tx.Exec(ctx, sql, append([]any{id, now}, args...)...); err != nil {
			return fmt.Errorf("extrawork: saving the %s: %w", action, err)
		}
		return nil
	}
	switch action {
	case "acknowledge":
		if a.status != "assigned" {
			return nil, refuse("Only a newly assigned task can be acknowledged.")
		}
		return nil, exec(`UPDATE hr_extra_assignment SET status = 'acknowledged', acknowledged_at = $2, updated_at = $2 WHERE id = $1`)
	case "start":
		if !slices.Contains([]string{"assigned", "acknowledged", "returned"}, a.status) {
			return nil, refuse("This assignment cannot be started from its current state.")
		}
		today := now.In(zone)
		return nil, exec(`UPDATE hr_extra_assignment SET status = 'in_progress', started_at = COALESCE(started_at, $2),
  start_date = COALESCE(start_date, $3::date), updated_at = $2 WHERE id = $1`, today.Format(time.DateOnly))
	case "submit":
		if !slices.Contains([]string{"assigned", "acknowledged", "in_progress", "returned"}, a.status) {
			return nil, refuse("This assignment cannot be submitted from its current state.")
		}
		outcome := strings.TrimSpace(v["outcome"])
		if outcome == "" {
			return nil, refuse("Describe the outcome — what was actually delivered.")
		}
		note, uri := strings.TrimSpace(v["evidence_note"]), strings.TrimSpace(v["evidence_uri"])
		if a.evidenceRequired && note == "" && uri == "" {
			return nil, refuse("This assignment requires evidence — add the evidence note or link.")
		}
		if err := exec(`UPDATE hr_extra_assignment SET outcome = $3, evidence_note = $4, evidence_uri = $5, status = 'submitted',
  submitted_at = $2, updated_at = $2 WHERE id = $1`, outcome, note, uri); err != nil {
			return nil, err
		}
		return func(ctx context.Context, p auth.Principal, origin activities.Origin) {
			s.tell(ctx, p, id, origin, "extra_work_submitted", "Extra work submitted for review",
				"“"+a.title+"” was submitted — review and verify or return it.", "high", a.reviewer)
			s.audit(ctx, p, id, "extra_work.submitted", map[string]any{"outcome": cut(outcome, 200)}, origin)
		}, nil
	case "return":
		if a.status != "submitted" {
			return nil, refuse("Only submitted work can be returned.")
		}
		reason := strings.TrimSpace(v["reason"])
		if reason == "" {
			return nil, refuse("Say what must be corrected.")
		}
		if err := exec(`UPDATE hr_extra_assignment SET status = 'returned', return_reason = $3, return_count = return_count + 1,
  updated_at = $2 WHERE id = $1`, reason); err != nil {
			return nil, err
		}
		return func(ctx context.Context, p auth.Principal, origin activities.Origin) {
			s.tell(ctx, p, id, origin, "extra_work_returned", "Extra work returned for correction",
				"“"+a.title+"”: "+cut(reason, 180), "high", a.assignee)
			s.audit(ctx, p, id, "extra_work.returned", map[string]any{"reason": cut(reason, 200)}, origin)
		}, nil
	case "verify":
		return s.verify(ctx, tx, a, id, v, now, actor)
	case "cancel":
		if a.status == "verified" || a.status == "cancelled" {
			return nil, refuse("Finished work cannot be cancelled.")
		}
		reason := strings.TrimSpace(orDefault(v["reason"], "Cancelled by assigner"))
		if err := exec(`UPDATE hr_extra_assignment SET status = 'cancelled', cancelled_at = $2, cancel_reason = $3,
  updated_at = $2 WHERE id = $1`, reason); err != nil {
			return nil, err
		}
		return func(ctx context.Context, p auth.Principal, origin activities.Origin) {
			s.tell(ctx, p, id, origin, "extra_work_cancelled", "Extra work cancelled",
				"“"+a.title+"” was cancelled by the assigner.", "normal", a.assignee)
			s.audit(ctx, p, id, "extra_work.cancelled", map[string]any{"reason": cut(reason, 200)}, origin)
		}, nil
	}
	return nil, refuse("Unknown action")
}

// verify is verify: the reviewer, never the assignee; points only from the
// year's approved scoring policy.
func (s *Service) verify(ctx context.Context, tx pgx.Tx, a assignmentRow, id string, v map[string]string, now time.Time,
	actor string) (afterward, error) {
	if a.assignee == a.reviewer {
		return nil, refuse("The assignee can never verify their own extra work.")
	}
	if a.status != "submitted" {
		return nil, refuse("Only submitted work can be verified.")
	}
	today := now.In(zone).Format(time.DateOnly)
	var points *string
	if err := tx.QueryRow(ctx, `WITH policy AS (
  SELECT id, LEAST(
    CASE WHEN $4::date > $5::date
         THEN round(COALESCE((complexity_weights ->> $3)::numeric, 0) * overdue_multiplier, 2)
         ELSE COALESCE((complexity_weights ->> $3)::numeric, 0) END,
    max_contribution_points) AS points
    FROM hr_extra_work_scoring_policy WHERE fy = $6 AND status = 'approved' ORDER BY id LIMIT 1)
UPDATE hr_extra_assignment SET status = 'verified', verified_at = $2, verified_by = $7, completion_date = $4::date,
  contribution_points = (SELECT points FROM policy), scoring_policy_id = (SELECT id FROM policy), updated_at = $2
 WHERE id = $1 RETURNING contribution_points::text`,
		id, now, a.complexity, today, a.due.Format(time.DateOnly), a.fy, actor).Scan(&points); err != nil {
		return nil, fmt.Errorf("extrawork: verifying: %w", err)
	}
	body := "“" + a.title + "” is verified — it is tracked; scoring awaits the approved policy."
	if points != nil {
		body = "“" + a.title + "” is verified — " + *points + " performance point(s)."
	}
	note := cut(v["note"], 200)
	return func(ctx context.Context, p auth.Principal, origin activities.Origin) {
		s.tell(ctx, p, id, origin, "extra_work_verified", "Extra work verified", body, "normal", a.assignee, a.lead)
		pts := "None"
		if points != nil {
			pts = *points
		}
		s.audit(ctx, p, id, "extra_work.verified", map[string]any{"points": pts, "note": note}, origin)
	}, nil
}

func cut(v string, n int) string {
	r := []rune(v)
	if len(r) > n {
		return string(r[:n])
	}
	return v
}

// tell is _notify: one trigger to the people named (blanks dropped).
func (s *Service) tell(ctx context.Context, p auth.Principal, id string, origin activities.Origin, event, title, body, priority string,
	recipients ...string) {
	to := []activities.NoticeTo{}
	for _, r := range recipients {
		if r != "" {
			to = append(to, activities.NoticeTo{UserID: r, Route: "/dashboard", Label: "View Dashboard"})
		}
	}
	if len(to) == 0 {
		return
	}
	if err := activities.SendNotices(ctx, s.saves.pool, s.saves.push, s.saves.live, s.saves.logger, s.now(), id, p.UserID, origin,
		activities.Notice{Title: title, Body: body, Event: event, Category: "extra_work", ContextType: "extra_assignment", Priority: priority},
		to); err != nil {
		s.saves.logger.Warn("extrawork: a notice was not sent", "assignment", id, "err", err)
	}
}

// audit is _audit.
func (s *Service) audit(ctx context.Context, p auth.Principal, id, action string, payload map[string]any, origin activities.Origin) {
	tx, err := s.saves.pool.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite})
	if err != nil {
		return
	}
	defer func() { _ = tx.Rollback(ctx) }()
	if _, err := audit.Append(ctx, tx, audit.Entry{
		Action: action, SubjectKind: audit.Text("ExtraAssignment"), SubjectID: audit.Text(id),
		ActorID: audit.Text(p.UserID), ActorRole: audit.Text(p.ActiveRole), Success: true,
		IPAddress: audit.Text(origin.IP), UserAgent: audit.Text(origin.UserAgent), CorrelationID: audit.Text(origin.CorrelationID),
		Payload: payload,
	}, s.now()); err != nil {
		s.saves.logger.Warn("extrawork: the audit row was not written", "assignment", id, "err", err)
		return
	}
	_ = tx.Commit(ctx)
}
