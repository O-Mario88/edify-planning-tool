package partneroversight

// The hand-over drawer's save (oversight_views.partner_oversight_send_
// action_view, through partner_oversight_actions): remind the Partner, nudge
// the Impact Assessment or Accountant queue, send a TeamAction to the
// managing CCEO, or escalate one level up. The feed saves a drawer through
// its first form, so the intent and risk are that form's, as the drawer
// draws them; only the note is the reader's.

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/activities"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/audit"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/escalations"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pageaccess"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/realtime"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/workflowmsg"
)

// SendError is a save refused in the reader's words.
type SendError struct{ Message string }

func (e *SendError) Error() string { return e.Message }

func refused(format string, args ...any) error {
	return &SendError{Message: fmt.Sprintf(format, args...)}
}

// SendDeps are what a send's notices need, and the TeamAction send.
type SendDeps struct {
	Push   activities.NoticePush
	Live   activities.NoticePublisher
	Logger *slog.Logger
	// Delegate is send_action (internal/actionsweep, which reads this
	// package, so it is given rather than called).
	Delegate Delegate
}

// Delegation is send_action's arguments for a CCEO-addressed risk.
type Delegation struct {
	IssueType, ConditionKey, Severity, Detail string
	RelatedActivityID, SchoolID, FY           string
	MonthOfFY                                 *int
	Recipient                                 string
	SenderID, SenderRole, SenderName, Note    string
	Origin                                    activities.Origin
}

// Delegate writes d in tx: the recipient's name as their account holds it,
// who was told, a refusal in the sender's words, or an error
// (ErrDetailHandOn for an ask Go does not make).
type Delegate func(ctx context.Context, tx pgx.Tx, now, today time.Time, d Delegation) (name string, told []string, refusal string, err error)

const (
	assignmentContext = "PartnerAssignment"
	// The feed's words for a drawer it cannot save.
	drawerUnavailable = "This drawer is not available."
	drawerUnsaved     = "This drawer cannot be saved here."
)

// Send saves the hand-over drawer for assignmentID with the reader's note
// and answers the confirmation. A refusal is a *SendError; ErrDetailHandOn
// is a save Go does not make.
func (s *Service) Send(ctx context.Context, pool *pgxpool.Pool, deps SendDeps, p auth.Principal, assignmentID, note string,
	origin activities.Origin) (string, error) {
	if !pageaccess.CanOpen(p.ActiveRole, false, DetailPath) {
		return "", refused(drawerUnavailable)
	}
	role, ok := rules.Roles[p.ActiveRole]
	if !ok || p.Acting != nil || p.InActingAppointment || (p.Country != nil && p.Country.FromRegistry()) {
		return "", ErrDetailHandOn
	}
	assignmentID = strings.TrimSpace(assignmentID)
	if assignmentID == "" {
		return "", refused(drawerUnavailable)
	}
	now := s.now()
	local := now.In(zone)
	today := time.Date(local.Year(), local.Month(), local.Day(), 0, 0, 0, 0, time.UTC)
	it, err := s.itemInScope(ctx, p, role.Lens, assignmentID, now)
	if err != nil {
		return "", err
	}
	if it == nil {
		// The drawer answers 404 ("Not available"), which the feed reads as
		// no drawer at all.
		return "", refused(drawerUnavailable)
	}
	if role.Lens != "team" {
		// A reader who only reads: the drawer offers no form.
		return "", refused(drawerUnsaved)
	}
	risks := risksWithWords(it, today)
	intent, risk := firstForm(risks)
	if intent == "" {
		label, err := escalations.NewService(s.db, s.now).AddresseeLabel(ctx, p.UserID, p.ActiveRole)
		if err != nil {
			return "", err
		}
		if label == "" {
			return "", refused(drawerUnsaved)
		}
		intent = "escalate"
	}
	note = strings.TrimSpace(note)
	tx, err := pool.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite})
	if err != nil {
		return "", fmt.Errorf("partneroversight: opening the send: %w", err)
	}
	defer func() { _ = tx.Rollback(ctx) }()
	a := sendArgs{tx: tx, deps: deps, p: p, it: it, risks: risks, riskKey: risk, note: note, now: now, today: today, origin: origin}
	var answer string
	var told []string
	event := "school_action_assigned"
	switch intent {
	case "nudge_queue":
		event = "partner_oversight_nudge." + risk
		answer, told, err = a.nudgeQueue(ctx)
	case "remind_partner":
		event = "partner_reminder." + risk
		answer, told, err = a.remindPartner(ctx)
	case "send_to_cceo":
		answer, told, err = a.sendToCCEO(ctx)
	default:
		answer, told, err = a.escalate(ctx)
	}
	if err != nil {
		return "", err
	}
	if err := tx.Commit(ctx); err != nil {
		return "", fmt.Errorf("partneroversight: committing the send: %w", err)
	}
	if deps.Live != nil {
		for _, id := range told {
			deps.Live.Publish(realtime.Event{Type: "notification." + event, EntityType: assignmentContext, EntityID: assignmentID,
				TargetUserID: id, ActorUserID: p.UserID})
		}
	}
	return answer, nil
}

// firstForm is the drawer's first form: the first risk with a send, as
// intent and risk; "" when no risk offers one.
func firstForm(risks []partnerRisk) (string, string) {
	s := rules.Work.Sends
	for _, r := range risks {
		switch {
		case s.RoleQueues[r.role] != "":
			return "nudge_queue", r.key
		case in(s.PartnerAddressed, r.key):
			return "remind_partner", r.key
		case in(s.CCEOAddressed, r.key):
			return "send_to_cceo", r.key
		}
	}
	return "", ""
}

type sendArgs struct {
	tx         pgx.Tx
	deps       SendDeps
	p          auth.Principal
	it         *item
	risks      []partnerRisk
	riskKey    string
	note       string
	now, today time.Time
	origin     activities.Origin
}

// riskOn is _risk_on.
func (a sendArgs) riskOn() (partnerRisk, error) {
	for _, r := range a.risks {
		if r.key == a.riskKey {
			return r, nil
		}
	}
	return partnerRisk{}, refused("That condition is no longer true of this assignment, so there is nothing to send.")
}

func (a sendArgs) withNote(body string) string {
	if a.note != "" {
		return body + "\n\n" + a.note
	}
	return body
}

func (a sendArgs) audit(ctx context.Context, action string, payload map[string]any) error {
	cover, err := audit.CoverageStamp(ctx, a.tx, a.p.UserID, a.now)
	if err != nil {
		return err
	}
	payload = audit.WithStamps(payload, cover)
	if _, err := audit.Append(ctx, a.tx, audit.Entry{Action: action, SubjectKind: audit.Text(assignmentContext),
		SubjectID: audit.Text(a.it.assignmentID), ActorID: audit.Text(a.p.UserID), ActorRole: audit.Text(a.p.ActiveRole), Success: true,
		IPAddress: audit.Text(a.origin.IP), UserAgent: audit.Text(a.origin.UserAgent), CorrelationID: audit.Text(a.origin.CorrelationID),
		Payload: payload}, a.now); err != nil {
		return fmt.Errorf("partneroversight: auditing the send: %w", err)
	}
	return nil
}

func (a sendArgs) post(ctx context.Context, subject, body, priority string, recipients []string) []string {
	return workflowmsg.Post(ctx, a.tx, a.deps.Push, a.deps.Logger, a.now, workflowmsg.Message{
		ContextType: assignmentContext, ContextID: a.it.assignmentID,
		Label: workflowmsg.FallbackLabel(assignmentContext, a.it.assignmentID), Subject: subject, Body: body,
		Recipients: recipients, Category: "planning", Priority: priority, Sender: a.p.UserID,
	})
}

// remindPartner is remind_partner.
func (a sendArgs) remindPartner(ctx context.Context) (string, []string, error) {
	if !in(rules.Work.Sends.PartnerAddressed, a.riskKey) {
		return "", nil, refused("'%s' is not something the partner can resolve. Send it to the managing CCEO instead.", a.riskKey)
	}
	risk, err := a.riskOn()
	if err != nil {
		return "", nil, err
	}
	var name string
	var user *string
	err = a.tx.QueryRow(ctx, `SELECT COALESCE(name, ''), user_id FROM partner WHERE id = $1`, a.it.partnerID).Scan(&name, &user)
	if errors.Is(err, pgx.ErrNoRows) {
		return "", nil, refused("That partner record no longer exists.")
	}
	if err != nil {
		return "", nil, fmt.Errorf("partneroversight: the partner: %w", err)
	}
	if user == nil || *user == "" {
		return "", nil, refused("%s has no login account on the system, so a reminder cannot reach them here. Contact them directly.", name)
	}
	body := a.withNote(fmt.Sprintf("%s asked about %s: %s %s.", first(a.p.Name, "A Program Lead"),
		first(a.it.schoolName, "an assigned school"), risk.reason, risk.action))
	priority := "high"
	if risk.severity == "warning" {
		priority = "normal"
	}
	if _, _, err := activities.NotifyFromPerson(ctx, a.tx, a.deps.Push, a.now, activities.PersonNotice{Recipient: *user,
		ContextType: assignmentContext, ContextID: a.it.assignmentID, Event: "partner_reminder." + a.riskKey,
		Fields: map[string]any{"recipient_role": "Partner", "title": "Reminder: " + first(a.it.schoolName, "assigned school"),
			"body": body, "category": "planning", "target_route": "/partner/assignments", "action_label": risk.action,
			"action_required": true, "priority": priority, "status": "unread", "read_at": nil}}); err != nil &&
		!errors.Is(err, activities.ErrPhoneCopy) {
		return "", nil, err
	}
	told := append([]string{*user}, a.post(ctx, first(a.it.schoolName, "Assignment")+" — "+risk.action, body, "normal",
		[]string{*user})...)
	if err := a.audit(ctx, "partner_oversight.reminder_sent", map[string]any{"risk": a.riskKey, "partner_id": orNil(a.it.partnerID),
		"school_id": orNil(a.it.schoolID), "recipient_id": *user}); err != nil {
		return "", nil, err
	}
	return fmt.Sprintf("Reminder sent to %s.", first(a.it.partnerName, "the partner")), told, nil
}

// nudgeQueue is nudge_role_queue through notify_role_queue.
func (a sendArgs) nudgeQueue(ctx context.Context) (string, []string, error) {
	risk, err := a.riskOn()
	if err != nil {
		return "", nil, err
	}
	queues := rules.Work.Sends.RoleQueues
	label, ok := queues[risk.role]
	if !ok {
		return "", nil, refused("'%s' is not something %s can resolve.", a.riskKey, first(queues[risk.role], "a queue"))
	}
	where := first(a.it.schoolName, "a partner assignment")
	body := a.withNote(fmt.Sprintf("%s asked about %s at %s: %s", first(a.p.Name, "A supervisor"),
		first(a.it.partnerName, "a partner"), where, risk.reason))
	subject := risk.action + " — " + where
	route := first(risk.route, "/partner-oversight/")
	priority := "normal"
	if risk.severity == "critical" {
		priority = "high"
	}
	event := "partner_oversight_nudge." + a.riskKey
	holders, err := a.queueHolders(ctx, risk.role)
	if err != nil {
		return "", nil, err
	}
	if len(holders) == 0 {
		return "", nil, refused("There is no active %s on the system, so this cannot be asked of anyone here.", label)
	}
	for _, id := range holders {
		if _, _, err := activities.NotifyFromPerson(ctx, a.tx, a.deps.Push, a.now, activities.PersonNotice{Recipient: id,
			ContextType: assignmentContext, ContextID: a.it.assignmentID, Event: event, Sender: a.p.UserID,
			Fields: map[string]any{"recipient_role": risk.role, "title": subject, "body": body, "category": "planning",
				"target_route": route, "action_label": risk.action, "action_required": true, "priority": priority,
				"status": "unread", "read_at": nil}}); err != nil && !errors.Is(err, activities.ErrPhoneCopy) {
			return "", nil, err
		}
	}
	told := append(append([]string{}, holders...), a.post(ctx, subject, body, priority, holders)...)
	if err := a.audit(ctx, "oversight.role_queue_nudged", map[string]any{"role": risk.role, "event": event,
		"recipients": len(holders)}); err != nil {
		return "", nil, err
	}
	return fmt.Sprintf("Sent to %d colleague(s) in that queue.", len(holders)), told, nil
}

// queueHolders is notify_role_queue's holders: every active holder of the
// role, Impact Assessment's in the sender's country when the sender has one.
func (a sendArgs) queueHolders(ctx context.Context, role string) ([]string, error) {
	query := `SELECT u.id FROM "user" u WHERE u.roles @> ARRAY[$1::varchar] AND u.status = 'active' AND u.deleted_at IS NULL`
	args := []any{role}
	if role == "ImpactAssessment" {
		var country *string
		if err := a.tx.QueryRow(ctx, `SELECT country FROM staff_profile WHERE user_id = $1`, a.p.UserID).Scan(&country); err != nil &&
			!errors.Is(err, pgx.ErrNoRows) {
			return nil, fmt.Errorf("partneroversight: the sender's country: %w", err)
		}
		if c := strings.TrimSpace(deref(country)); c != "" {
			query += ` AND EXISTS (SELECT 1 FROM staff_profile sp WHERE sp.user_id = u.id AND sp.country = $2)`
			args = append(args, c)
		}
	}
	rows, err := a.tx.Query(ctx, query+` ORDER BY u.created_at DESC`, args...)
	if err != nil {
		return nil, fmt.Errorf("partneroversight: the queue's holders: %w", err)
	}
	return pgx.CollectRows(rows, pgx.RowTo[string])
}

// sendToCCEO is send_to_managing_cceo through send_action.
func (a sendArgs) sendToCCEO(ctx context.Context) (string, []string, error) {
	issue, ok := rules.Work.Sends.CCEOIssueKeys[a.riskKey]
	if !ok {
		return "", nil, refused("'%s' is not a condition the managing CCEO can clear.", a.riskKey)
	}
	risk, err := a.riskOn()
	if err != nil {
		return "", nil, err
	}
	if a.it.schoolID == "" {
		return "", nil, refused("This assignment has no school, so there is no school record to attach the ask to.")
	}
	var exists bool
	if err := a.tx.QueryRow(ctx, `SELECT EXISTS (SELECT 1 FROM school WHERE id = $1)`, a.it.schoolID).Scan(&exists); err != nil {
		return "", nil, fmt.Errorf("partneroversight: the school: %w", err)
	}
	if !exists {
		return "", nil, refused("The school on this assignment no longer exists.")
	}
	var cceoUser *string
	err = a.tx.QueryRow(ctx, `SELECT user_id FROM staff_profile WHERE id = $1
UNION ALL SELECT user_id FROM staff_profile WHERE user_id = $1 AND NOT EXISTS (SELECT 1 FROM staff_profile WHERE id = $1)
LIMIT 1`, a.it.cceoID).Scan(&cceoUser)
	if err != nil && !errors.Is(err, pgx.ErrNoRows) {
		return "", nil, fmt.Errorf("partneroversight: the managing CCEO: %w", err)
	}
	if a.it.cceoID == "" || cceoUser == nil || *cceoUser == "" {
		return "", nil, refused("This assignment records no managing CCEO, so there is nobody to hold responsible for it.")
	}
	if a.deps.Delegate == nil {
		return "", nil, ErrDetailHandOn
	}
	d := Delegation{IssueType: issue, ConditionKey: "partner_oversight|" + issue + "|assignment|" + a.it.assignmentID,
		Severity: risk.severity, Detail: risk.reason, SchoolID: a.it.schoolID, Recipient: *cceoUser, SenderID: a.p.UserID,
		SenderRole: a.p.ActiveRole, SenderName: a.p.Name, Note: a.note, Origin: a.origin}
	if a.it.act != nil {
		d.RelatedActivityID, d.FY, d.MonthOfFY = a.it.act.id, a.it.act.fy, a.it.act.plannedMonth
	}
	name, told, refusal, err := a.deps.Delegate(ctx, a.tx, a.now, a.today, d)
	switch {
	case err != nil:
		return "", nil, err
	case refusal != "":
		return "", nil, refused("%s", refusal)
	}
	return fmt.Sprintf("Sent to %s. Tracked under Actions Sent.", first(name, "the responsible staff member")), told, nil
}

// escalate is escalate_to_country_director through raise_escalation.
func (a sendArgs) escalate(ctx context.Context) (string, []string, error) {
	if a.note == "" {
		return "", nil, refused("An escalation needs a note saying what has already been tried.")
	}
	if a.it.schoolID == "" && a.it.clusterName == "" {
		return "", nil, refused("This assignment has no school to escalate against.")
	}
	scope := rules.Work.Sends.EscalationScope
	var already bool
	if err := a.tx.QueryRow(ctx, `SELECT EXISTS (SELECT 1 FROM leadership_escalation WHERE raised_by_user_id = $1 AND scope_type = $2
  AND scope_id = $3 AND status IS DISTINCT FROM 'resolved')`, a.p.UserID, scope, a.it.assignmentID).Scan(&already); err != nil {
		return "", nil, fmt.Errorf("partneroversight: the open escalation: %w", err)
	}
	if already {
		return "", nil, refused("Already escalated: this handover has an open escalation. Follow it on Escalations.")
	}
	partner := first(a.it.partnerName, "The partner")
	place := first(a.it.schoolName, a.it.clusterName, "the assigned school")
	owner, next := nextAction(a.it)
	raised, err := escalations.RaiseIn(ctx, a.tx, a.deps.Push, a.now, escalations.Raise{RaiserID: a.p.UserID,
		RaiserRole: a.p.ActiveRole, RaiserName: a.p.Name, Category: "partner_performance", Severity: "high",
		Subject: fmt.Sprintf("%s at %s: %s", partner, place, next),
		Detail: fmt.Sprintf("Partner-delivered work has stalled and asking has not moved it. %s (%s).\n\nWhat has been tried: %s",
			next, owner, a.note),
		RequestedDecision: fmt.Sprintf("Decide how %s's delivery at %s is recovered — a firm deadline, reassignment or a contract conversation.",
			partner, place),
		ScopeType: scope, ScopeID: a.it.assignmentID, ScopeName: partner + " · " + place, Origin: a.origin})
	var refusal *escalations.RaiseError
	switch {
	case errors.As(err, &refusal):
		return "", nil, refused("%s", refusal.Message)
	case err != nil:
		return "", nil, err
	}
	return fmt.Sprintf("Escalated to the %s. Follow it on Escalations.", raised.AddressedTo), nil, nil
}

func orNil(s string) any {
	if s == "" {
		return nil
	}
	return s
}

func deref(s *string) string {
	if s == nil {
		return ""
	}
	return *s
}
