package staffactivity

// The follow-up saves (create_follow_up, transition) and the notices that
// follow their commit, written by Go when the existing application is
// absent. Every step is written to the follow-up's own history and to the
// audit chain; the notices go through the one notice writer and are closed
// when the follow-up is.

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"log/slog"
	"net/url"
	"slices"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/activities"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/audit"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/cuid"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pageaccess"
)

// FollowUps draws and saves the Staff Activity follow-ups.
type FollowUps struct {
	DB     *pgxpool.Pool
	Push   activities.NoticePush
	Live   activities.NoticePublisher
	Logger *slog.Logger
	Now    func() time.Time
}

func (f FollowUps) now() time.Time {
	if f.Now != nil {
		return f.Now()
	}
	return time.Now()
}

func (f FollowUps) reads() *Service { return NewService(f.DB, f.now) }

// Drawer is Service.FollowUpDrawer.
func (f FollowUps) Drawer(ctx context.Context, p auth.Principal, rawPath string) (*screensv1.PageDrawer, bool, error) {
	return f.reads().FollowUpDrawer(ctx, p, rawPath)
}

// pythonISO is datetime.isoformat() of an aware UTC moment.
func pythonISO(t time.Time) string {
	t = t.UTC()
	if t.Nanosecond()/int(time.Microsecond) == 0 {
		return t.Format("2006-01-02T15:04:05") + "+00:00"
	}
	return t.Format("2006-01-02T15:04:05.000000") + "+00:00"
}

// entry is _entry: one line of the follow-up's history.
func entry(p *auth.Principal, name, status, note string, now time.Time) map[string]any {
	var by any
	byName := "Platform"
	if p != nil {
		by, byName = p.UserID, name
	}
	return map[string]any{"at": pythonISO(now), "by": by, "by_name": byName, "status": status, "note": runes(note, historyNoteMax)}
}

func followUpAudit(ctx context.Context, tx pgx.Tx, action string, f *followUp, p auth.Principal, note string, now time.Time) error {
	_, err := audit.Append(ctx, tx, audit.Entry{Action: action, SubjectKind: audit.Text(followUpContext), SubjectID: audit.Text(f.id),
		ActorID: audit.Text(p.UserID), ActorRole: audit.Text(p.ActiveRole), Success: true, Payload: map[string]any{
			"subject_id": f.subject.id, "assignee_id": f.assignee.id, "trigger": f.trigger, "status": f.status, "route": f.route,
			"note": runes(note, auditNoteMax),
		}}, now)
	if err != nil {
		return fmt.Errorf("staffactivity: auditing %s: %w", action, err)
	}
	return nil
}

func (f FollowUps) write(ctx context.Context, do func(pgx.Tx) error) error {
	tx, err := f.DB.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite})
	if err != nil {
		return fmt.Errorf("staffactivity: opening the follow-up's save: %w", err)
	}
	defer func() { _ = tx.Rollback(ctx) }()
	if err := do(tx); err != nil {
		return err
	}
	if err := tx.Commit(ctx); err != nil {
		return fmt.Errorf("staffactivity: committing the follow-up: %w", err)
	}
	return nil
}

// Create is follow_up_create_view and create_follow_up.
func (f FollowUps) Create(ctx context.Context, p auth.Principal, personID string, values map[string]string) error {
	s := f.reads()
	v, err := s.scope(ctx, p)
	if err != nil {
		return err
	}
	// person_detail first: a reader with no scope, or a person outside it,
	// is refused before anything is checked.
	if v == nil {
		return &Refused{Message: "This person is not in your scope."}
	}
	x, chosen, err := s.personFor(ctx, p, v, personID, values["period"], values["on"])
	if err != nil {
		return err
	}
	due, dueOK := isoDate(trimmed(values["due_date"]))
	trigger, priority := values["trigger"], values["priority"]
	note := trimmed(values["note"])
	switch {
	case !v.canFollowUp:
		return &FollowUpError{"Only a Programme Lead or the Country Director can send a follow-up."}
	case !v.holds(personID):
		return &FollowUpError{"You can follow up only with people in your scope."}
	case personID == v.selfID:
		return &FollowUpError{"A follow-up is about someone else, not yourself."}
	case !hasChoice(rules.Person.FollowUpTriggers, trigger):
		return &FollowUpError{"Choose what the follow-up is about."}
	case !hasChoice(priorities, priority):
		return &FollowUpError{"Choose a priority."}
	case note == "":
		return &FollowUpError{"Write a note for the person receiving it."}
	case !dueOK:
		return &FollowUpError{"Choose a due date."}
	case due.Before(dateOf(s.now())):
		return &FollowUpError{"The due date cannot be in the past."}
	}
	subject, err := s.account(ctx, personID)
	if err != nil {
		return err
	}
	assignee, route, err := s.recipient(ctx, p, subject)
	if err != nil {
		return err
	}
	sender, err := s.account(ctx, p.UserID)
	if err != nil {
		return err
	}
	var same string
	err = f.DB.QueryRow(ctx, `SELECT status FROM staff_usage_follow_up WHERE subject_id = $1 AND trigger = $2 AND status = ANY($3)
ORDER BY created_at DESC LIMIT 1`, personID, trigger, openStatuses()).Scan(&same)
	if err == nil {
		return &FollowUpError{fmt.Sprintf("A follow-up about this is already open (%s).", choice(rules.Person.FollowUpStatuses, same))}
	}
	if !errors.Is(err, pgx.ErrNoRows) {
		return fmt.Errorf("staffactivity: reading the person's open follow-ups: %w", err)
	}
	now := f.now()
	row := &followUp{id: cuid.New(), route: route, periodKey: chosen.key, trigger: trigger, note: runes(note, noteMax),
		priority: priority, status: statusSent, subject: subject, assignee: assignee, createdBy: sender, due: due}
	snapshot, err := json.Marshal(map[string]any{
		"period": chosen.label, "logins": x.logins, "active": minutes(float64(x.seconds)), "actions": x.actions,
		"schools": x.schools, "failed": x.failed, "usage": x.usageLabel,
	})
	if err != nil {
		return fmt.Errorf("staffactivity: writing the snapshot: %w", err)
	}
	history, err := json.Marshal([]any{entry(&p, sender.named(), statusSent, note, now)})
	if err != nil {
		return fmt.Errorf("staffactivity: writing the history: %w", err)
	}
	err = f.write(ctx, func(tx pgx.Tx) error {
		if _, err := tx.Exec(ctx, `INSERT INTO staff_usage_follow_up (id, created_at, updated_at, subject_id, assignee_id,
  created_by_id, route, period_key, period_start, period_end, trigger, snapshot, note, priority, due_date, status, resolution,
  resolved_at, resolved_by_id, history)
VALUES ($1, $2, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11::jsonb, $12, $13, $14, $15, '', NULL, NULL, $16::jsonb)`,
			row.id, now, subject.id, assignee.id, p.UserID, route, chosen.key, chosen.start, chosen.end, trigger, string(snapshot),
			row.note, priority, due, statusSent, string(history)); err != nil {
			return fmt.Errorf("staffactivity: writing the follow-up: %w", err)
		}
		return followUpAudit(ctx, tx, "staff_activity.follow_up_sent", row, p, note, now)
	})
	if err != nil {
		return err
	}
	f.notifyAssignee(ctx, row)
	return nil
}

func hasChoice(pairs [][2]string, value string) bool {
	return slices.ContainsFunc(pairs, func(c [2]string) bool { return c[0] == value })
}

// Transition is follow_up_transition_view and transition.
func (f FollowUps) Transition(ctx context.Context, p auth.Principal, id, action, note string) error {
	s := f.reads()
	row, actions, err := s.openFollowUp(ctx, p, id, "This follow-up is not yours to change.", false)
	if err != nil {
		return err
	}
	if !slices.ContainsFunc(actions, func(a StepAction) bool { return a.Key == action }) {
		return &FollowUpError{"That step is not open to you on this follow-up."}
	}
	st, _ := stepFor(action)
	note = trimmed(note)
	if st.noteRequired && note == "" {
		return &FollowUpError{"Add a note for this step."}
	}
	reader, err := s.account(ctx, p.UserID)
	if err != nil {
		return err
	}
	now := f.now()
	line, err := json.Marshal(entry(&p, reader.named(), st.to, note, now))
	if err != nil {
		return fmt.Errorf("staffactivity: writing the history: %w", err)
	}
	resolves := slices.Contains(resolvedStatuses, st.to) && st.to != statusClosed
	err = f.write(ctx, func(tx pgx.Tx) error {
		var status string
		if err := tx.QueryRow(ctx, `SELECT status FROM staff_usage_follow_up WHERE id = $1 FOR UPDATE`, id).Scan(&status); err != nil {
			return fmt.Errorf("staffactivity: locking the follow-up: %w", err)
		}
		if status != row.status {
			return &FollowUpError{"Someone else has just changed this follow-up; reload it."}
		}
		sql := `UPDATE staff_usage_follow_up SET status = $2, history = COALESCE(history, '[]'::jsonb) || jsonb_build_array($3::jsonb),
  updated_at = $4 WHERE id = $1`
		args := []any{id, st.to, string(line), now}
		if resolves {
			sql = `UPDATE staff_usage_follow_up SET status = $2, history = COALESCE(history, '[]'::jsonb) || jsonb_build_array($3::jsonb),
  updated_at = $4, resolved_at = $4, resolved_by_id = $5, resolution = $6 WHERE id = $1`
			args = append(args, p.UserID, runes(note, noteMax))
		}
		if _, err := tx.Exec(ctx, sql, args...); err != nil {
			return fmt.Errorf("staffactivity: moving the follow-up: %w", err)
		}
		row.status = st.to
		event := "staff_activity.follow_up_" + action
		if st.to == statusResolvedManager {
			event = "staff_activity.follow_up_resolved"
		}
		return followUpAudit(ctx, tx, event, row, p, note, now)
	})
	if err != nil {
		return err
	}
	f.afterTransition(ctx, row, action)
	return nil
}

// afterTransition is _after_transition, after the commit.
func (f FollowUps) afterTransition(ctx context.Context, row *followUp, action string) {
	if !row.isOpen() {
		err := f.write(ctx, func(tx pgx.Tx) error {
			for _, event := range []string{followUpEvent, followUpEscalatedEvent} {
				if _, err := tx.Exec(ctx, `SELECT gateway_notifications.resolve_condition($1, $2, $3, $4)`,
					event, followUpContext, row.id, f.now()); err != nil {
					return err
				}
			}
			return nil
		})
		if err != nil && f.Logger != nil {
			f.Logger.WarnContext(ctx, "staffactivity: the follow-up's notices were not closed", "follow_up", row.id, "err", err)
		}
		return
	}
	switch action {
	case "resend":
		f.notifyAssignee(ctx, row)
	case "escalate":
		f.notifyDirectors(ctx, row)
	case "return":
		f.notify(ctx, row, []string{row.createdBy.id}, followUpEvent, "normal", "Follow-up returned for clarification",
			fmt.Sprintf("%s asked for clarification about %s.", row.assignee.named(), strings.ToLower(row.triggerLabel())), row.assignee.id)
	}
}

// notify is _notify: never failing the step that is already saved.
func (f FollowUps) notify(ctx context.Context, row *followUp, to []string, event, priority, title, body, sender string) {
	var recipients []activities.NoticeTo
	for _, id := range to {
		if id != "" {
			recipients = append(recipients, activities.NoticeTo{UserID: id, Route: followUpPrefix + row.id, Label: "Open Follow-up"})
		}
	}
	if len(recipients) == 0 {
		return
	}
	err := activities.SendNotices(ctx, f.DB, f.Push, f.Live, f.Logger, f.now(), row.id, "", activities.Origin{}, activities.Notice{
		Title: title, Body: body, Event: event, Category: followUpCategory, ContextType: followUpContext, Priority: priority,
		Sender: sender,
	}, recipients)
	if err != nil && f.Logger != nil {
		f.Logger.WarnContext(ctx, "staffactivity: follow-up notification failed", "follow_up", row.id, "err", err)
	}
}

// notifyAssignee is _notify_assignee.
func (f FollowUps) notifyAssignee(ctx context.Context, row *followUp) {
	trigger := strings.ToLower(row.triggerLabel())
	due := row.due.Format("02 Jan")
	title := "Your manager followed up with you"
	body := fmt.Sprintf("%s followed up about %s. Due %s.", row.createdBy.named(), trigger, due)
	if row.route == routeDirector {
		title = "Follow up with " + row.subject.named()
		body = fmt.Sprintf("%s asked you to follow up with %s about %s. Due %s.", row.createdBy.named(), row.subject.named(), trigger, due)
	}
	priority := "normal"
	if row.priority == priorityHigh {
		priority = priorityHigh
	}
	f.notify(ctx, row, []string{row.assignee.id}, followUpEvent, priority, title, body, row.createdBy.id)
}

// notifyDirectors is _notify_directors: every Country Director
// (role_recipients), whatever their country.
func (f FollowUps) notifyDirectors(ctx context.Context, row *followUp) {
	var directors []string
	rows, err := f.DB.Query(ctx, `SELECT id FROM "user" WHERE roles @> ARRAY[$1]::varchar[] AND is_active AND deleted_at IS NULL`,
		rules.Roles.CountryDirector)
	if err == nil {
		for rows.Next() {
			var id string
			if err = rows.Scan(&id); err != nil {
				break
			}
			directors = append(directors, id)
		}
		rows.Close()
		if err == nil {
			err = rows.Err()
		}
	}
	if err != nil {
		if f.Logger != nil {
			f.Logger.WarnContext(ctx, "staffactivity: the Country Directors were not read", "follow_up", row.id, "err", err)
		}
		return
	}
	f.notify(ctx, row, directors, followUpEscalatedEvent, "normal", "Follow-up escalated: "+row.subject.named(),
		fmt.Sprintf("%s escalated a follow-up about %s.", row.createdBy.named(), strings.ToLower(row.triggerLabel())), "")
}

// Save is the follow-up saves for SaveDrawer: the Follow up drawer (its own
// path or the form's /send), one follow-up's step (the drawer with its step
// chosen, the page with the step's form, or the step's own path). served is
// false for any other path and for a case Go hands on.
func (f FollowUps) Save(ctx context.Context, p auth.Principal, rawPath, form string, values map[string]string) (*screensv1.SaveDrawerResponse, bool, error) {
	path, rawQuery, _ := strings.Cut(rawPath, "?")
	query, _ := url.ParseQuery(rawQuery)
	var err error
	switch {
	case followUpNewPath.MatchString(path), followUpSendPath.MatchString(path):
		if !rules.Doors[p.ActiveRole].Page {
			return nil, false, nil
		}
		id := followUpNewPath.FindStringSubmatch(path)
		if id == nil {
			id = followUpSendPath.FindStringSubmatch(path)
		}
		own := map[string]string{}
		for k, v := range values {
			own[k] = v
		}
		for _, key := range []string{"period", "on"} {
			if own[key] == "" {
				own[key] = query.Get(key)
			}
		}
		err = f.Create(ctx, p, id[1], own)
	case followUpOnePath.MatchString(path), followUpStepPath.MatchString(path):
		var id, action string
		if m := followUpStepPath.FindStringSubmatch(path); m != nil {
			id, action = m[1], m[2]
		} else {
			id = followUpOnePath.FindStringSubmatch(path)[1]
			action = form
			if action == "" {
				action = values[stepField]
			}
			if action == "" {
				// One step open: the drawer offers no choice.
				row, actions, err := f.reads().openFollowUp(ctx, p, id, "This follow-up is not yours to change.", false)
				if err == nil && row != nil && len(actions) == 1 {
					action = actions[0].Key
				}
			}
		}
		if !pageaccess.CanOpen(p.ActiveRole, false, followUpPrefix+id) {
			return nil, false, nil
		}
		err = f.Transition(ctx, p, id, action, values["note"])
	default:
		return nil, false, nil
	}
	var refusal *FollowUpError
	switch {
	case err == nil:
		return &screensv1.SaveDrawerResponse{Saved: true}, true, nil
	case errors.Is(err, errPassOn):
		return nil, false, nil
	case errors.As(err, &refusal):
		return &screensv1.SaveDrawerResponse{Error: refusal.Message}, true, nil
	}
	return nil, true, err
}

// resolveAutomatically is _resolve_automatically: the follow-up, still in
// the status it was read in, is resolved by activity, audited with no actor,
// its notices closed and its sender told.
func (f FollowUps) resolveAutomatically(ctx context.Context, row *followUp, reason string) error {
	now := f.now()
	line, err := json.Marshal(entry(nil, "", statusResolvedActivity, reason, now))
	if err != nil {
		return fmt.Errorf("staffactivity: writing the history: %w", err)
	}
	updated := false
	err = f.write(ctx, func(tx pgx.Tx) error {
		tag, err := tx.Exec(ctx, `UPDATE staff_usage_follow_up SET status = $3, resolved_at = $4, resolution = $5,
  history = COALESCE(history, '[]'::jsonb) || jsonb_build_array($6::jsonb), updated_at = $4 WHERE id = $1 AND status = $2`,
			row.id, row.status, statusResolvedActivity, now, reason, string(line))
		if err != nil {
			return fmt.Errorf("staffactivity: resolving the follow-up: %w", err)
		}
		if tag.RowsAffected() == 0 {
			return nil
		}
		updated = true
		row.status = statusResolvedActivity
		_, err = audit.Append(ctx, tx, audit.Entry{Action: "staff_activity.follow_up_auto_resolved", SubjectKind: audit.Text(followUpContext),
			SubjectID: audit.Text(row.id), Success: true, Payload: map[string]any{
				"subject_id": row.subject.id, "assignee_id": row.assignee.id, "trigger": row.trigger, "status": row.status,
				"route": row.route, "note": runes(reason, auditNoteMax),
			}}, now)
		if err != nil {
			return fmt.Errorf("staffactivity: auditing the resolution: %w", err)
		}
		return nil
	})
	if err != nil || !updated {
		return err
	}
	// _after_auto_resolution, after the commit.
	f.afterTransition(ctx, row, "")
	f.notify(ctx, row, []string{row.createdBy.id}, "staff_activity.follow_up_resolved", "normal", "Follow-up resolved",
		fmt.Sprintf("%s: %s — %s", row.subject.named(), strings.ToLower(row.triggerLabel()), reason), "")
	return nil
}

// ResolveOnSignIn is resolve_by_activity(user, "login"), which the existing
// sign-in runs once it is recorded: a sign-in answers the person's open "no
// login" follow-ups. It never fails the sign-in.
func (f FollowUps) ResolveOnSignIn(ctx context.Context, userID string) {
	if err := f.resolveByActivity(ctx, userID, "login", ""); err != nil && f.Logger != nil {
		f.Logger.WarnContext(ctx, "staffactivity: follow-up resolution failed", "user", userID, "err", err)
	}
}

func (f FollowUps) resolveByActivity(ctx context.Context, userID, kind, module string) error {
	var triggers []string
	for trigger, need := range autoResolve {
		if need == kind || (kind == "action" && module != "" && need == module) {
			triggers = append(triggers, trigger)
		}
	}
	if len(triggers) == 0 || userID == "" {
		return nil
	}
	found, err := f.DB.Query(ctx, followUpSelect+` WHERE f.subject_id = $1 AND f.trigger = ANY($2) AND f.status = ANY($3)
  AND f.status <> $4 ORDER BY f.created_at DESC`, userID, triggers, openStatuses(), statusEscalated)
	if err != nil {
		return fmt.Errorf("staffactivity: reading the person's follow-ups: %w", err)
	}
	var rows []*followUp
	for found.Next() {
		row, err := scanFollowUp(found)
		if err != nil {
			found.Close()
			return err
		}
		rows = append(rows, row)
	}
	found.Close()
	if err := found.Err(); err != nil {
		return err
	}
	reason := autoReason(kind)
	if kind == "action" && module != "" {
		reason = autoReason(module)
	}
	for _, row := range rows {
		if err := f.resolveAutomatically(ctx, row, reason); err != nil {
			return err
		}
	}
	return nil
}
