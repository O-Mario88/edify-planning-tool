package actionsweep

// send_action: one urgent condition delegated to the person who must clear
// it, as the TeamAction its sweep later closes, with the recipient's notice,
// the school's system message and the audit row (_announce), all in the
// caller's transaction.

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgconn"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/activities"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/audit"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/cuid"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/partneroversight"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/workflowmsg"
)

// SendError is send_action's ActionError: a refusal in the sender's words.
type SendError struct{ Message string }

func (e *SendError) Error() string { return e.Message }

func refuse(format string, args ...any) error {
	return &SendError{Message: fmt.Sprintf(format, args...)}
}

// Ask is send_action's arguments, the issue already resolved.
type Ask struct {
	IssueType, ConditionKey, Severity, Detail string
	RelatedActivityID, RelatedSSAID           string
	SchoolID, FY                              string
	MonthOfFY                                 *int
	// Recipient is the user held responsible; RecipientRole the role the
	// action names them in ("" reads their account's active role).
	Recipient, RecipientRole string
	SenderID, SenderRole     string
	SenderName               string
	Note                     string
	Origin                   activities.Origin
}

// Sent is the action written, its recipient's name as their account holds
// it ("" for none), and who its notices reached.
type Sent struct {
	ID, RecipientName string
	Told              []string
}

// Send writes ask as send_action does, in tx. A refusal is a *SendError.
func Send(ctx context.Context, tx pgx.Tx, push activities.NoticePush, logger *slog.Logger, now, today time.Time, ask Ask) (Sent, error) {
	if ask.ConditionKey == "" {
		return Sent{}, refuse("This issue has no condition key and cannot be tracked.")
	}
	playbook, ok := rules.Playbook[ask.IssueType]
	if !ok {
		return Sent{}, refuse("'%s' has no defined follow-up action, so it cannot be delegated. Register it in ISSUE_PLAYBOOK first.", ask.IssueType)
	}
	if ask.IssueType == "core_assessment_missing" {
		// sendable_issue_keys withholds this ask only while no catalogue item
		// can schedule a core assessment; Go does not read that gap yet.
		return Sent{}, ErrSendHandOn
	}
	if ask.Recipient == "" {
		return Sent{}, refuse("This school has no assigned staff member, so there is nobody to hold responsible. Assign the school first.")
	}
	var existing struct {
		recipient string
		created   time.Time
	}
	err := tx.QueryRow(ctx, `SELECT recipient_id, created_at FROM team_action WHERE condition_key = $1 AND state = ANY($2)
ORDER BY id LIMIT 1`, ask.ConditionKey, rules.ActiveStates).Scan(&existing.recipient, &existing.created)
	switch {
	case err == nil:
		name, err := nameOf(ctx, tx, existing.recipient)
		if err != nil {
			return Sent{}, err
		}
		return Sent{}, refuse("Already sent to %s on %s. It is tracked under Actions Sent.", name, dayMonth(existing.created.UTC()))
	case !errors.Is(err, pgx.ErrNoRows):
		return Sent{}, fmt.Errorf("actionsweep: the active action: %w", err)
	}
	var schoolName, schoolCode string
	if err := tx.QueryRow(ctx, `SELECT COALESCE(name, ''), COALESCE(school_id, '') FROM school WHERE id = $1`, ask.SchoolID).
		Scan(&schoolName, &schoolCode); err != nil {
		return Sent{}, fmt.Errorf("actionsweep: the school: %w", err)
	}
	role := ask.RecipientRole
	if role == "" {
		if err := tx.QueryRow(ctx, `SELECT COALESCE(active_role, '') FROM "user" WHERE id = $1`, ask.Recipient).Scan(&role); err != nil &&
			!errors.Is(err, pgx.ErrNoRows) {
			return Sent{}, fmt.Errorf("actionsweep: the recipient's role: %w", err)
		}
	}
	var previous *string
	if err := tx.QueryRow(ctx, `SELECT id FROM team_action WHERE condition_key = $1 AND NOT (state = ANY($2))
ORDER BY created_at DESC LIMIT 1`, ask.ConditionKey, rules.ActiveStates).Scan(&previous); err != nil && !errors.Is(err, pgx.ErrNoRows) {
		return Sent{}, fmt.Errorf("actionsweep: the last closed action: %w", err)
	}
	severity := first(ask.Severity, "critical")
	priority := first(rules.PriorityFor[severity], "normal")
	days, ok := rules.DefaultDueDays[severity]
	if !ok {
		days = 5
	}
	due := today.AddDate(0, 0, days)
	route := strings.NewReplacer("{school_ref}", first(schoolCode, ask.SchoolID), "{school_pk}", ask.SchoolID).Replace(playbook.Route)
	id := cuid.New()
	insert, err := tx.Begin(ctx)
	if err != nil {
		return Sent{}, fmt.Errorf("actionsweep: opening the action: %w", err)
	}
	_, err = insert.Exec(ctx, `INSERT INTO team_action (created_at, updated_at, id, condition_key, issue_type, severity, school_id, fy,
  month_of_fy, related_ssa_id, related_activity_id, sender_id, sender_role, recipient_id, recipient_role, requested_action,
  workflow_route, message, priority, due_date, state, detected_at, blocked_reason, resolved_by_system, manual_resolution_reason,
  returned_reason, reminder_count, supersedes_id)
VALUES ($1, $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17, $18, $19, 'open', $1, '', false, '', '', 0, $20)`,
		now, id, ask.ConditionKey, ask.IssueType, severity, ask.SchoolID, ask.FY, ask.MonthOfFY, nilIfEmpty(ask.RelatedSSAID),
		nilIfEmpty(ask.RelatedActivityID), ask.SenderID, ask.SenderRole, ask.Recipient, role, playbook.Action, route,
		strings.TrimSpace(ask.Note), priority, due, previous)
	var pgErr *pgconn.PgError
	if errors.As(err, &pgErr) && pgErr.Code == "23505" {
		_ = insert.Rollback(ctx)
		return Sent{}, refuse("Someone else just sent this same issue. It is tracked under Actions Sent.")
	}
	if err == nil {
		err = insert.Commit(ctx)
	}
	if err != nil {
		_ = insert.Rollback(ctx)
		return Sent{}, fmt.Errorf("actionsweep: writing the action: %w", err)
	}
	sent := Sent{ID: id}
	if err := tx.QueryRow(ctx, `SELECT COALESCE(name, '') FROM "user" WHERE id = $1`, ask.Recipient).Scan(&sent.RecipientName); err != nil &&
		!errors.Is(err, pgx.ErrNoRows) {
		return Sent{}, fmt.Errorf("actionsweep: the recipient's name: %w", err)
	}
	why := first(ask.Detail, playbook.Why)
	body := fmt.Sprintf("%s asked you to %s at %s. %s Due %s.", first(ask.SenderName, "A colleague"),
		strings.ToLower(playbook.Action), schoolName, why, dayMonth(due))
	if _, _, err := activities.NotifyFromPerson(ctx, tx, push, now, activities.PersonNotice{Recipient: ask.Recipient,
		ContextType: actionContext, ContextID: id, Event: "school_action_assigned", Sender: ask.SenderID,
		Fields: map[string]any{"recipient_role": role, "title": "Action required: " + schoolName, "body": body,
			"category": "planning", "target_route": route, "action_label": playbook.Action, "action_required": true,
			"priority": priority, "status": "unread", "source_event_id": id, "read_at": nil}}); err != nil &&
		!errors.Is(err, activities.ErrPhoneCopy) {
		return Sent{}, err
	}
	sent.Told = append(sent.Told, ask.Recipient)
	message := body
	if note := strings.TrimSpace(ask.Note); note != "" {
		message += "\n\n" + note
	}
	sent.Told = append(sent.Told, workflowmsg.Post(ctx, tx, push, logger, now, workflowmsg.Message{
		ContextType: "School", ContextID: ask.SchoolID, Label: workflowmsg.FallbackLabel("School", ask.SchoolID),
		Subject: "Urgent action: " + schoolName, Body: message, Recipients: []string{ask.Recipient}, Category: "planning",
		Priority: priority, Sender: ask.SenderID,
	})...)
	cover, err := audit.CoverageStamp(ctx, tx, ask.SenderID, now)
	if err != nil {
		return Sent{}, err
	}
	if _, err := audit.Append(ctx, tx, audit.Entry{Action: "school_action.sent", SubjectKind: audit.Text(actionContext),
		SubjectID: audit.Text(id), ActorID: audit.Text(ask.SenderID), ActorRole: audit.Text(ask.SenderRole), Success: true,
		IPAddress: audit.Text(ask.Origin.IP), UserAgent: audit.Text(ask.Origin.UserAgent), CorrelationID: audit.Text(ask.Origin.CorrelationID),
		Payload: audit.WithStamps(map[string]any{"condition_key": ask.ConditionKey, "issue_type": ask.IssueType, "school_id": ask.SchoolID,
			"recipient_id": ask.Recipient, "due_date": due.Format("2006-01-02")}, cover)}, now); err != nil {
		return Sent{}, fmt.Errorf("actionsweep: auditing the send: %w", err)
	}
	return sent, nil
}

// ErrSendHandOn is an ask Go does not make yet; the caller forwards it.
var ErrSendHandOn = errors.New("actionsweep: this send is Django's")

// dayMonth is strftime("%-d %b").
func dayMonth(t time.Time) string { return t.Format("2 Jan") }

func first(values ...string) string {
	for _, v := range values {
		if v != "" {
			return v
		}
	}
	return ""
}

func nilIfEmpty(s string) any {
	if s == "" {
		return nil
	}
	return s
}

// PartnerDelegate is Send as Partner Oversight's send to the managing CCEO
// calls it.
func PartnerDelegate(push activities.NoticePush, logger *slog.Logger) partneroversight.Delegate {
	return func(ctx context.Context, tx pgx.Tx, now, today time.Time, d partneroversight.Delegation) (string, []string, string, error) {
		sent, err := Send(ctx, tx, push, logger, now, today, Ask{IssueType: d.IssueType, ConditionKey: d.ConditionKey,
			Severity: d.Severity, Detail: d.Detail, RelatedActivityID: d.RelatedActivityID, SchoolID: d.SchoolID, FY: d.FY,
			MonthOfFY: d.MonthOfFY, Recipient: d.Recipient, SenderID: d.SenderID, SenderRole: d.SenderRole,
			SenderName: d.SenderName, Note: d.Note, Origin: d.Origin})
		var refusal *SendError
		switch {
		case errors.As(err, &refusal):
			return "", nil, refusal.Message, nil
		case errors.Is(err, ErrSendHandOn):
			return "", nil, "", partneroversight.ErrDetailHandOn
		case err != nil:
			return "", nil, "", err
		}
		return sent.RecipientName, sent.Told, "", nil
	}
}
