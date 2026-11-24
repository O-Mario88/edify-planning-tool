package debriefs

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"slices"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/activities"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/audit"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/cuid"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/partnerassigned"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/realtime"
)

// The Daily Debrief's save (debrief_views.field_debrief_submit_view, through
// DailyDebriefFlowService.save_draft and submit), with Django absent.

// DailyFormKey is the page form's key (submit.go dailyForm).
const DailyFormKey = "daily-debrief-form"

// Refusal is a save the existing service refuses, in its words.
type Refusal struct{ Message string }

func (r *Refusal) Error() string { return r.Message }

func refuse(msg string) error { return &Refusal{Message: msg} }

// SubmittedMessage is the view's word once a debrief is submitted.
const SubmittedMessage = "Debrief submitted successfully. Your Program Lead, Country Director and HR can now review it."

// DailyForm is the form's fields; Autosave is intent=autosave.
type DailyForm struct {
	ActivityIDs                                      []string
	WentWell, NotWell, Challenges, Advice, OtherWork string
	Autosave                                         bool
}

// saver is what a save needs beyond the page's reads.
type saver struct {
	pool   *pgxpool.Pool
	push   activities.NoticePush
	live   activities.NoticePublisher
	logger *slog.Logger
}

// WithSaves lets the service save the Daily Debrief.
func (s *Service) WithSaves(pool *pgxpool.Pool, push activities.NoticePush, live activities.NoticePublisher, logger *slog.Logger) *Service {
	s.saves = &saver{pool: pool, push: push, live: live, logger: logger}
	return s
}

// Saves reports whether the service saves the Daily Debrief.
func (s *Service) Saves() bool { return s.saves != nil }

// ActivityIDs reads the form's work: a checklist joined by commas, or the one
// box's "on" for the day's only activity.
func ActivityIDs(raw string) []string {
	var ids []string
	for _, id := range strings.Split(raw, ",") {
		if id = strings.TrimSpace(id); id != "" {
			ids = append(ids, id)
		}
	}
	return ids
}

func nullable(v string) any {
	if v = strings.TrimSpace(v); v == "" {
		return nil
	}
	return v
}

// operationalFY is get_operational_fy at now (UTC): October opens the next.
func operationalFY(now time.Time) string {
	now = now.UTC()
	if now.Month() >= time.October {
		return fmt.Sprint(now.Year() + 1)
	}
	return fmt.Sprint(now.Year())
}

// SaveDaily is save_draft (Autosave) or submit for the reader's day.
func (s *Service) SaveDaily(ctx context.Context, p auth.Principal, f DailyForm, origin activities.Origin) (string, error) {
	if s.saves == nil {
		return "", errors.New("debriefs: no saves")
	}
	if !slices.Contains(rules.SubmitterRoles, p.ActiveRole) {
		return "", refuse("Your role cannot submit a Daily Debrief.")
	}
	now := s.now()
	today := day(now.In(zone))
	work, err := s.dailyWork(ctx, p, today, "")
	if err != nil {
		return "", err
	}
	allowed := map[string]dailyWork{}
	for _, w := range work {
		allowed[w.id] = w
	}
	ids := []string{}
	for _, id := range f.ActivityIDs {
		if id == "on" && len(work) == 1 {
			id = work[0].id
		}
		ids = append(ids, id)
	}
	for _, id := range ids {
		if _, ok := allowed[id]; !ok {
			return "", refuse("An activity outside today's plan cannot be selected.")
		}
	}
	existing, err := s.dailyDebrief(ctx, p, today)
	if err != nil {
		return "", err
	}
	if existing != nil && !slices.Contains(rules.DailyEditableStatuses, existing.status) {
		return "", refuse("Today's Daily Debrief is already submitted. Ask your Program Lead to return it if a correction is needed.")
	}
	id, err := s.upsertDaily(ctx, p, existing, ids, f, today, now)
	if err != nil {
		return "", err
	}
	if f.Autosave {
		return "", nil
	}
	return SubmittedMessage, s.submitDaily(ctx, p, id, existing, ids, f, today, origin)
}

// upsertDaily is _upsert: the day's one row, its work links and the schools
// they name, committed on their own (the existing view keeps a draft even
// when the submission is then refused).
func (s *Service) upsertDaily(ctx context.Context, p auth.Principal, existing *dailyDebrief, ids []string, f DailyForm,
	today, now time.Time) (string, error) {
	tx, err := s.saves.pool.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite})
	if err != nil {
		return "", fmt.Errorf("debriefs: opening the debrief: %w", err)
	}
	defer func() { _ = tx.Rollback(ctx) }()
	fields := []any{nullable(f.WentWell), nullable(f.NotWell), nullable(f.Challenges), nullable(f.Advice), nullable(f.OtherWork)}
	var id string
	if existing != nil {
		id = existing.id
		if _, err := tx.Exec(ctx, `UPDATE daily_debrief SET what_went_well = $2, what_did_not_go_well = $3, challenges_faced = $4,
  recommendations = $5, other_work_description = $6, linked_activity_ids = $7, updated_at = $8 WHERE id = $1`,
			append(append([]any{id}, fields...), ids, now)...); err != nil {
			return "", fmt.Errorf("debriefs: updating the debrief: %w", err)
		}
	} else {
		id = cuid.New()
		var partner any
		debriefType := "staff"
		if slices.Contains(rules.PartnerRoles, p.ActiveRole) {
			debriefType = "partner"
			partners, err := partnerassigned.PartnerIDs(ctx, s.db, p)
			if err != nil {
				return "", err
			}
			if len(partners) > 0 {
				partner = partners[0]
			}
		}
		midnight := time.Date(today.Year(), today.Month(), today.Day(), 0, 0, 0, 0, zone)
		if _, err := tx.Exec(ctx, `INSERT INTO daily_debrief (
  id, created_at, updated_at, fy, date, submitted_by_user_id, submitted_by_role, staff_id, partner_id, debrief_type, kind,
  status, title, linked_activity_ids, submitted_at, what_went_well, what_did_not_go_well, challenges_faced, recommendations,
  other_work_description, blockers, linked_school_ids, linked_cluster_ids, linked_partner_ids, linked_project_ids,
  intervention_tags, is_restricted_incident, potential_mscs_flag, potential_champion_flag, potential_partner_success_flag,
  recommendation_status, risk_level, source, environment)
VALUES ($1, $2, $2, $3, $4, $5, $6, $7, $8, $9, 'daily', 'draft', $10, $11, $2, $12, $13, $14, $15, $16,
  '{}', '{}', '{}', '{}', '{}', '{}', false, false, false, false, 'none', 'none', 'manual_upload', 'production')`,
			id, now, operationalFY(now), midnight, p.UserID, p.ActiveRole, nilIfEmpty(p.StaffProfileID), partner, debriefType,
			"Daily Debrief — "+today.Format("2 Jan 2006"), ids, fields[0], fields[1], fields[2], fields[3], fields[4]); err != nil {
			return "", fmt.Errorf("debriefs: writing the debrief: %w", err)
		}
	}
	if _, err := tx.Exec(ctx, `SELECT gateway_debriefs.unlink_work($1, $2)`, id, ids); err != nil {
		return "", fmt.Errorf("debriefs: unlinking work: %w", err)
	}
	rows, err := tx.Query(ctx, `SELECT a.id, a.school_id FROM activity a WHERE a.id = ANY($2)
   AND NOT EXISTS (SELECT 1 FROM daily_debrief_activity_link l WHERE l.debrief_id = $1 AND l.activity_id = a.id)`, id, ids)
	if err != nil {
		return "", fmt.Errorf("debriefs: reading the new work: %w", err)
	}
	type newLink struct {
		activity string
		school   *string
	}
	fresh, err := pgx.CollectRows(rows, func(r pgx.CollectableRow) (newLink, error) {
		var l newLink
		return l, r.Scan(&l.activity, &l.school)
	})
	if err != nil {
		return "", fmt.Errorf("debriefs: reading the new work: %w", err)
	}
	for _, l := range fresh {
		if _, err := tx.Exec(ctx, `INSERT INTO daily_debrief_activity_link (id, created_at, updated_at, debrief_id, activity_id, school_id)
VALUES ($1, $2, $2, $3, $4, $5)`, cuid.New(), now, id, l.activity, l.school); err != nil {
			return "", fmt.Errorf("debriefs: linking work: %w", err)
		}
	}
	if _, err := tx.Exec(ctx, `UPDATE daily_debrief SET linked_school_ids = COALESCE((SELECT array_agg(DISTINCT l.school_id)
  FROM daily_debrief_activity_link l WHERE l.debrief_id = $1 AND l.school_id IS NOT NULL), '{}') WHERE id = $1`, id); err != nil {
		return "", fmt.Errorf("debriefs: naming the schools: %w", err)
	}
	if err := tx.Commit(ctx); err != nil {
		return "", fmt.Errorf("debriefs: committing the debrief: %w", err)
	}
	return id, nil
}

func nilIfEmpty(v string) any {
	if v == "" {
		return nil
	}
	return v
}

// submitDaily is submit after its upsert: the checks, the status, the
// routing to the supervising Programme Lead (or, for a partner, each linked
// activity's officer) and the domain event.
func (s *Service) submitDaily(ctx context.Context, p auth.Principal, id string, existing *dailyDebrief, ids []string, f DailyForm,
	today time.Time, origin activities.Origin) error {
	if len(ids) == 0 && strings.TrimSpace(f.OtherWork) == "" {
		return refuse("Select at least one activity you worked on, or describe other authorized work.")
	}
	if strings.TrimSpace(f.WentWell) == "" && strings.TrimSpace(f.NotWell) == "" && strings.TrimSpace(f.Challenges) == "" &&
		strings.TrimSpace(f.Advice) == "" {
		return refuse("Answer at least one of the reflection questions.")
	}
	status := "submitted"
	if existing != nil && (existing.status == "clarification_requested" || existing.status == "returned") {
		status = "updated"
	}
	now := s.now()
	recipients, err := s.dailyRecipients(ctx, p, id)
	if err != nil {
		return err
	}
	tx, err := s.saves.pool.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite})
	if err != nil {
		return fmt.Errorf("debriefs: opening the submission: %w", err)
	}
	defer func() { _ = tx.Rollback(ctx) }()
	var title, role string
	if err := tx.QueryRow(ctx, `UPDATE daily_debrief SET status = $2, submitted_at = $3 WHERE id = $1 RETURNING title, submitted_by_role`,
		id, status, now).Scan(&title, &role); err != nil {
		return fmt.Errorf("debriefs: submitting the debrief: %w", err)
	}
	for _, r := range recipients {
		if _, err := tx.Exec(ctx, `INSERT INTO daily_debrief_recipient (id, created_at, updated_at, debrief_id, recipient_user_id,
  recipient_role, routing_reason, action_required) VALUES ($1, $2, $2, $3, $4, $5, $6, true)`,
			cuid.New(), now, id, r.userID, r.role, r.reason); err != nil {
			return fmt.Errorf("debriefs: routing the debrief: %w", err)
		}
	}
	if err := tx.Commit(ctx); err != nil {
		return fmt.Errorf("debriefs: committing the submission: %w", err)
	}
	for _, r := range recipients {
		if err := activities.SendNotices(ctx, s.saves.pool, s.saves.push, s.saves.live, s.saves.logger, s.now(), id, p.UserID, origin,
			activities.Notice{Title: "Field Debrief: " + title, Body: role + " debrief — " + r.reason + ".",
				Event: "field_debrief_routed", Category: "field_debrief", ContextType: "field_debrief", Priority: "normal"},
			[]activities.NoticeTo{{UserID: r.userID, Route: "/debriefs/" + id, Label: "Open Debrief"}}); err != nil {
			s.saves.logger.Warn("debriefs: a routed notice was not sent", "debrief", id, "err", err)
		}
	}
	if err := s.emitSubmitted(ctx, p, id, today, origin); err != nil {
		s.saves.logger.Warn("debriefs: the submission's domain event was not written", "debrief", id, "err", err)
	}
	return nil
}

type recipient struct{ userID, role, reason string }

// dailyRecipients is _route for a daily debrief (no risk, no support asked).
func (s *Service) dailyRecipients(ctx context.Context, p auth.Principal, id string) ([]recipient, error) {
	var out []recipient
	var lead string
	err := s.db.QueryRow(ctx, `SELECT COALESCE(sup.user_id, '') FROM staff_supervisor_assignment ssa
JOIN staff_profile sup ON sup.id = ssa.supervisor_id WHERE ssa.supervisee_id = $1 ORDER BY ssa.id LIMIT 1`,
		p.StaffProfileID).Scan(&lead)
	if err != nil && !errors.Is(err, pgx.ErrNoRows) {
		return nil, fmt.Errorf("debriefs: reading the supervising lead: %w", err)
	}
	switch {
	case lead != "" && lead != p.UserID:
		out = append(out, recipient{lead, "Program Lead", "Supervising Program Lead"})
	case slices.Contains(rules.PartnerRoles, p.ActiveRole):
		rows, err := s.db.Query(ctx, `SELECT COALESCE(a.responsible_staff_id, '') FROM daily_debrief_activity_link l
JOIN activity a ON a.id = l.activity_id WHERE l.debrief_id = $1 ORDER BY l.created_at, l.id`, id)
		if err != nil {
			return nil, fmt.Errorf("debriefs: reading the managing officers: %w", err)
		}
		owners, err := pgx.CollectRows(rows, pgx.RowTo[string])
		if err != nil {
			return nil, err
		}
		for _, o := range owners {
			if o != "" {
				out = append(out, recipient{o, "CCEO", "Managing CCEO"})
			}
		}
	}
	seen := map[string]bool{}
	kept := out[:0]
	for _, r := range out {
		key := r.userID + "|" + r.reason
		if seen[key] {
			continue
		}
		seen[key] = true
		kept = append(kept, r)
	}
	return kept, nil
}

// emitSubmitted is domain_events.emit("field_debrief.submitted"): its audit
// row, and a word to the submitter's open pages.
func (s *Service) emitSubmitted(ctx context.Context, p auth.Principal, id string, today time.Time, origin activities.Origin) error {
	tx, err := s.saves.pool.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite})
	if err != nil {
		return err
	}
	defer func() { _ = tx.Rollback(ctx) }()
	if _, err := audit.Append(ctx, tx, audit.Entry{
		Action: "field_debrief.submitted", SubjectKind: audit.Text("daily_debrief"), SubjectID: audit.Text(id),
		ActorID: audit.Text(p.UserID), ActorRole: audit.Text(p.ActiveRole), Success: true,
		IPAddress: audit.Text(origin.IP), UserAgent: audit.Text(origin.UserAgent), CorrelationID: audit.Text(origin.CorrelationID),
		Payload: map[string]any{"date": today.Format(time.DateOnly), "kind": "daily"},
	}, s.now()); err != nil {
		return err
	}
	if err := tx.Commit(ctx); err != nil {
		return err
	}
	if s.saves.live != nil {
		s.saves.live.Publish(realtime.Event{Type: "field_debrief.submitted", EntityType: "daily_debrief", EntityID: id,
			TargetUserID: p.UserID, ActorUserID: p.UserID})
	}
	return nil
}
