package planningmonitor

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net/url"
	"strconv"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgconn"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/activities"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/audit"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/cuid"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/realtime"
)

// Follow Up with PL as send_follow_up writes it, for either stage
// (country_oversight.followups for planning, country_execution.followups
// for execution): the open follow-up on the same condition reminded, or a
// new one created, then the Lead's notice and the audit row.

// fuAsk is one send's record.
type fuAsk struct {
	module, key                                     string
	issueKey, issueLabel, metricKey, resolutionRule string
	stage, blockerOwner                             string
	required, planned, remaining, affected          int
	schoolIDs                                       []string
	daysOverdue                                     *int
	snapshot, entry                                 map[string]any
	cceo, cceoName, school, schoolName              string
	partner, partnerName, activity, activityLabel   string
	fy, country                                     string
	w                                               cpoWindow
	lead                                            cexFollowLead
	sender                                          auth.Principal
	origin                                          activities.Origin
	now, due                                        time.Time
	instruction, priority                           string
	sentAudit                                       map[string]any
	remindAudit                                     func(reminders int) map[string]any
}

// fuWritten is what the Lead's notice reads off the record.
type fuWritten struct {
	id, status, assignedBy, periodLabel string
	cceoName, schoolName, partnerName   string
	activityLabel                       string
	required, reminders                 int
	created                             bool
}

func (a *fuAsk) write(ctx context.Context, tx pgx.Tx) (fuWritten, error) {
	var w fuWritten
	var history, instructions []byte
	err := tx.QueryRow(ctx, `SELECT id, status, instruction_history, history, reminder_count, assigned_by_name, activity_label,
		partner_name, cceo_name, school_name, period_label FROM planning_oversight_follow_up
		WHERE condition_key = $1 AND status = ANY($2) ORDER BY id LIMIT 1 FOR UPDATE`, a.key, rules.CountryExecution.FollowUps.OpenStates).
		Scan(&w.id, &w.status, &instructions, &history, &w.reminders, &w.assignedBy, &w.activityLabel, &w.partnerName, &w.cceoName,
			&w.schoolName, &w.periodLabel)
	if errors.Is(err, pgx.ErrNoRows) {
		return a.create(ctx, tx)
	}
	if err != nil {
		return w, fmt.Errorf("planningmonitor: the open follow-up: %w", err)
	}
	instr, hist := []any{}, []any{}
	_ = json.Unmarshal(instructions, &instr)
	_ = json.Unmarshal(history, &hist)
	instrJSON, _ := json.Marshal(append(instr, a.entry))
	histJSON, _ := json.Marshal(append(hist, a.historyLine("reminded")))
	w.reminders++
	returned := w.status == "returned_for_clarification"
	if returned {
		w.status = "sent_to_pl"
	}
	w.required = a.required
	sets := `instruction = $2, instruction_history = $3::jsonb, reminder_count = $4, last_reminder_at = $5, priority = $6,
		due_date = $7, remaining_value = $8, live_remaining = $8, live_checked_at = $5, status = $9,
		returned_reason = CASE WHEN $10 THEN '' ELSE returned_reason END, history = $11::jsonb, updated_at = $5`
	args := []any{w.id, a.instruction, string(instrJSON), w.reminders, a.now, a.priority, a.due, a.remaining, w.status, returned,
		string(histJSON)}
	if a.module == "execution" {
		sets += `, days_overdue = $12`
		args = append(args, a.daysOverdue)
	} else {
		schools, _ := json.Marshal(a.schoolIDs)
		sets += `, required_value = $12, planned_value = $13, affected_school_ids = $14::jsonb, affected_count = $15`
		args = append(args, a.required, a.planned, string(schools), a.affected)
	}
	if _, err := tx.Exec(ctx, `UPDATE planning_oversight_follow_up SET `+sets+` WHERE id = $1`, args...); err != nil {
		return w, fmt.Errorf("planningmonitor: reminding on the follow-up: %w", err)
	}
	return w, nil
}

func (a *fuAsk) create(ctx context.Context, tx pgx.Tx) (fuWritten, error) {
	null := func(s string) any {
		if s == "" {
			return nil
		}
		return s
	}
	snapshot, _ := json.Marshal(a.snapshot)
	schools := []byte("[]")
	if a.schoolIDs != nil {
		schools, _ = json.Marshal(a.schoolIDs)
	}
	instr, _ := json.Marshal([]any{a.entry})
	hist, _ := json.Marshal([]any{a.historyLine("sent")})
	w := fuWritten{id: cuid.New(), status: "sent_to_pl", assignedBy: a.sender.Name, periodLabel: a.w.label(), cceoName: a.cceoName,
		schoolName: a.schoolName, partnerName: a.partnerName, activityLabel: a.activityLabel, required: a.required, created: true}
	_, err := tx.Exec(ctx, `INSERT INTO planning_oversight_follow_up (created_at, updated_at, id, fy, period_type, period_start,
		period_end, period_label, country, region_id, region_name, program_lead_staff_id, program_lead_user_id, program_lead_name,
		cceo_staff_id, cceo_name, school_id, school_name, condition_key, issue_type, metric_key, required_value, planned_value,
		remaining_value, affected_school_ids, affected_count, snapshot, resolution_rule, live_remaining, live_checked_at, priority,
		instruction, instruction_history, assigned_by_id, assigned_by_role, assigned_by_name, assigned_at, due_date, status,
		acknowledged_at, action_linked_at, linked_team_action_ids, linked_note, resolved_at, resolved_by_system, resolution_note,
		closed_by_id, returned_reason, returned_at, reminder_count, last_reminder_at, history, activity_id, activity_label,
		blocker_owner, days_overdue, module, partner_id, partner_name, stage)
		VALUES ($1, $1, $2, $3, $4, $5, $6, $7, $8, NULL, '', $9, $10, $11, $12, $13, $14, $15, $16, $17, $18, $19, $20, $21,
		$22::jsonb, $23, $24::jsonb, $25, $21, $1, $26, $27, $28::jsonb, $29, $30, $31, $1, $32, 'sent_to_pl', NULL, NULL,
		'[]'::jsonb, '', NULL, false, '', '', '', NULL, 0, NULL, $33::jsonb, $34, $35, $36, $37, $38, $39, $40, $41)`,
		a.now, w.id, a.fy, a.w.period, a.w.start, a.w.end, a.w.label(), a.country, a.lead.staffID, a.lead.userID, a.lead.name,
		null(a.cceo), a.cceoName, null(a.school), a.schoolName, a.key, a.issueKey, a.metricKey, a.required, a.planned, a.remaining,
		string(schools), a.affected, string(snapshot), a.resolutionRule, a.priority, a.instruction, string(instr), a.sender.UserID,
		a.sender.ActiveRole, a.sender.Name, a.due, string(hist), null(a.activity), a.activityLabel, a.blockerOwner, a.daysOverdue,
		a.module, null(a.partner), a.partnerName, a.stage)
	var pg *pgconn.PgError
	if errors.As(err, &pg) && pg.Code == "23505" {
		return w, cexRefuse("Someone has just sent this same follow-up. It is on the list.")
	}
	if err != nil {
		return w, fmt.Errorf("planningmonitor: creating the follow-up: %w", err)
	}
	return w, nil
}

// body is _lead_body for the stage.
func (a *fuAsk) body(w fuWritten) string {
	who := w.assignedBy
	if who == "" {
		who = "The Country Director"
	}
	verb := "asked you to follow up"
	if !w.created {
		verb = "reminded you to follow up"
	}
	first := func(parts ...string) string {
		for _, p := range parts {
			if p != "" {
				return p
			}
		}
		return "your team"
	}
	due := fmt.Sprintf("Due %d %s. “%s”", a.due.Day(), a.due.Format("Jan"), a.instruction)
	if a.module == "execution" {
		return fmt.Sprintf("%s %s with %s on the %s (%s open, %s). %s", who, verb, first(w.activityLabel, w.partnerName, w.cceoName),
			strings.ToLower(a.issueLabel), cpoFmt(a.remaining), w.periodLabel, due)
	}
	return fmt.Sprintf("%s %s with %s on the %s (%s of %s remaining, %s). %s", who, verb, first(w.cceoName, w.schoolName),
		strings.ToLower(a.issueLabel), cpoFmt(a.remaining), cpoFmt(w.required), w.periodLabel, due)
}

// notify is _notify_lead then _audit.
func (a *fuAsk) notify(ctx context.Context, tx pgx.Tx, deps CEXSendDeps, w fuWritten) error {
	title := "Follow up: " + a.issueLabel
	if !w.created {
		title = "Reminder: " + a.issueLabel
	}
	priority := "normal"
	if a.priority == "high" || a.priority == "critical" {
		priority = "high"
	}
	_, _, err := activities.NotifyFromPerson(ctx, tx, deps.Push, a.now, activities.PersonNotice{Recipient: a.lead.userID,
		ContextType: cexFollowUpContext, ContextID: w.id, Event: cexFollowUpEvent, Sender: a.sender.UserID,
		Fields: map[string]any{"recipient_role": "Program Lead", "title": title, "body": a.body(w), "category": "planning",
			"target_route": a.teamOversightLink(w.id), "action_label": "Follow up", "action_required": true, "priority": priority,
			"status": "unread", "source_event_id": w.id, "read_at": nil, "resolved_at": nil}})
	if errors.Is(err, activities.ErrPhoneCopy) && deps.Logger != nil {
		deps.Logger.WarnContext(ctx, "planningmonitor: the follow-up's phone copy", "follow_up", w.id, "err", err)
	} else if err != nil {
		return err
	}
	if w.created {
		return a.auditRow(ctx, tx, "sent", w.id, w.status, a.sentAudit)
	}
	return a.auditRow(ctx, tx, "reminded", w.id, w.status, a.remindAudit(w.reminders))
}

// historyLine is _history's entry.
func (a *fuAsk) historyLine(action string) map[string]any {
	by, name := any(a.sender.UserID), a.sender.Name
	if a.sender.UserID == "" {
		by = "system"
	}
	if name == "" {
		name = "System"
	}
	return map[string]any{"at": cexISO(a.now), "by": by, "name": name, "action": action, "note": a.instruction}
}

// teamOversightLink is team_oversight_link: where the Lead acts.
func (a *fuAsk) teamOversightLink(id string) string {
	v := []string{"followup=" + url.QueryEscape(id), "fy=" + url.QueryEscape(a.fy)}
	if a.w.period != "fy" {
		v = append(v, "period="+a.w.period)
		switch a.w.period {
		case "quarter":
			v = append(v, "quarter="+cexQuarterOf(a.w.start))
		case "month":
			v = append(v, "month="+strconv.Itoa(int(a.w.start.Month())))
		case "week":
			y, wk := a.w.start.ISOWeek()
			v = append(v, fmt.Sprintf("week=%04d-W%02d", y, wk))
		}
	}
	if a.cceo != "" {
		v = append(v, "owner="+url.QueryEscape(a.cceo))
	}
	return cexTeamOversight + "?" + strings.Join(v, "&")
}

// auditRow is _audit through log(): the actor with any cover they hold, and
// the request's address, browser and correlation id.
func (a *fuAsk) auditRow(ctx context.Context, tx pgx.Tx, action, id, status string, extra map[string]any) error {
	cover, err := audit.CoverageStamp(ctx, tx, a.sender.UserID, a.now)
	if err != nil {
		return err
	}
	optional := func(s string) any {
		if s == "" {
			return nil
		}
		return s
	}
	payload := map[string]any{"condition_key": a.key, "issue_type": a.issueKey, "program_lead": a.lead.staffID,
		"cceo": optional(a.cceo), "school": optional(a.school), "status": status}
	for k, v := range extra {
		payload[k] = v
	}
	role := a.sender.ActiveRole
	if _, err := audit.Append(ctx, tx, audit.Entry{Action: "planning_followup." + action, SubjectKind: audit.Text(cexFollowUpContext),
		SubjectID: audit.Text(id), ActorID: audit.Text(a.sender.UserID), ActorRole: &role, Success: true,
		Payload: audit.WithStamps(payload, cover), IPAddress: audit.Text(a.origin.IP), UserAgent: audit.Text(a.origin.UserAgent),
		CorrelationID: audit.Text(a.origin.CorrelationID)}, a.now); err != nil {
		return fmt.Errorf("planningmonitor: auditing the follow-up: %w", err)
	}
	return nil
}

// fuSend runs the ask's transaction and says what the drawer shows.
func fuSend(ctx context.Context, db interface {
	BeginTx(context.Context, pgx.TxOptions) (pgx.Tx, error)
}, deps CEXSendDeps, a *fuAsk) (string, error) {
	tx, err := db.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite})
	if err != nil {
		return "", fmt.Errorf("planningmonitor: opening the follow-up: %w", err)
	}
	defer func() { _ = tx.Rollback(ctx) }()
	w, err := a.write(ctx, tx)
	if err != nil {
		return "", err
	}
	if err := a.notify(ctx, tx, deps, w); err != nil {
		return "", err
	}
	if err := tx.Commit(ctx); err != nil {
		return "", fmt.Errorf("planningmonitor: committing the follow-up: %w", err)
	}
	if deps.Live != nil {
		deps.Live.Publish(realtime.Event{Type: "notification." + cexFollowUpEvent, EntityType: cexFollowUpContext, EntityID: w.id,
			TargetUserID: a.lead.userID, ActorUserID: a.sender.UserID})
	}
	if w.created {
		return "Sent to " + a.lead.name + ". It is on their To-Do.", nil
	}
	return fmt.Sprintf("Reminder %d sent to %s on the open follow-up.", w.reminders, a.lead.name), nil
}

// cexQuarterOf is get_quarter_for_date: the FY quarter (October opens Q1).
func cexQuarterOf(d time.Time) string {
	return "Q" + strconv.Itoa((int(d.Month())+2)%12/3+1)
}
