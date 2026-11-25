package planningmonitor

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"strings"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgconn"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/activities"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/cuid"
)

// cexWritten is what the Lead's notice reads off the record.
type cexWritten struct {
	id, status, assignedBy, subject, periodLabel string
	reminders                                    int
	created                                      bool
}

// write is send_follow_up's transaction: the open follow-up on the same
// condition reminded, or a new one created.
func (in *cexSend) write(ctx context.Context, tx pgx.Tx) (cexWritten, error) {
	var w cexWritten
	var history, instructions []byte
	var activity, partner, cceo string
	err := tx.QueryRow(ctx, `SELECT id, status, instruction_history, history, reminder_count, assigned_by_name, activity_label,
		partner_name, cceo_name, period_label FROM planning_oversight_follow_up
		WHERE condition_key = $1 AND status = ANY($2) ORDER BY id LIMIT 1 FOR UPDATE`, in.key, rules.CountryExecution.FollowUps.OpenStates).
		Scan(&w.id, &w.status, &instructions, &history, &w.reminders, &w.assignedBy, &activity, &partner, &cceo, &w.periodLabel)
	if errors.Is(err, pgx.ErrNoRows) {
		return in.create(ctx, tx)
	}
	if err != nil {
		return w, fmt.Errorf("planningmonitor: the open follow-up: %w", err)
	}
	w.subject = cexSubject(activity, partner, cceo)
	instr, hist := []any{}, []any{}
	_ = json.Unmarshal(instructions, &instr)
	_ = json.Unmarshal(history, &hist)
	instrJSON, _ := json.Marshal(append(instr, in.entry))
	histJSON, _ := json.Marshal(append(hist, in.historyLine("reminded")))
	w.reminders++
	returned := w.status == "returned_for_clarification"
	if returned {
		w.status = "sent_to_pl"
	}
	if _, err := tx.Exec(ctx, `UPDATE planning_oversight_follow_up SET instruction = $2, instruction_history = $3::jsonb,
		reminder_count = $4, last_reminder_at = $5, priority = $6, due_date = $7, remaining_value = $8, live_remaining = $8,
		live_checked_at = $5, days_overdue = $9, status = $10, returned_reason = CASE WHEN $11 THEN '' ELSE returned_reason END,
		history = $12::jsonb, updated_at = $5 WHERE id = $1`, w.id, in.instruction, string(instrJSON), w.reminders, in.now,
		in.priority, in.due, in.open, in.oldest, w.status, returned, string(histJSON)); err != nil {
		return w, fmt.Errorf("planningmonitor: reminding on the follow-up: %w", err)
	}
	return w, nil
}

func cexSubject(activity, partner, cceo string) string {
	for _, s := range []string{activity, partner, cceo} {
		if s != "" {
			return s
		}
	}
	return "your team"
}

// create is PlanningOversightFollowUp.objects.create for execution, with
// its first history line.
func (in *cexSend) create(ctx context.Context, tx pgx.Tx) (cexWritten, error) {
	d := in.f.snap.data
	c := in.f.snap.tree.country
	win := in.fs.period.window()
	cceoName, partnerName, activityLabel, stage := "", "", "", in.issue.Stage
	if o := d.owners[in.fs.cceo]; in.fs.cceo != "" && o != nil {
		cceoName = o.name
	}
	if in.fs.partner != "" {
		partnerName = d.partnerName[in.fs.partner]
	}
	if in.fs.activityID != "" && len(in.f.records) > 0 {
		r := in.f.records[0]
		if r.due != nil {
			label := rules.CountryOversight.Page.TableWords.Types[r.activityType]
			if label == "" {
				label = r.activityType
			}
			activityLabel = fmt.Sprintf("%s · due %d %s", label, r.due.Day(), r.due.Format("Jan 2006"))
		}
		if stage == "" {
			stage = r.stage
		}
	}
	null := func(s string) any {
		if s == "" {
			return nil
		}
		return s
	}
	snapshot, _ := json.Marshal(map[string]any{"due": c.n("due"), "started": c.n("started"), "executed": c.n("executed"),
		"verified": c.n("verified"), "closed": c.n("closed"), "overdue": c.n("overdue"), "open": in.open,
		"as_of": d.today.Format("2006-01-02")})
	schools, _ := json.Marshal(in.schoolIDs)
	if in.schoolIDs == nil {
		schools = []byte("[]")
	}
	instr, _ := json.Marshal([]any{in.entry})
	hist, _ := json.Marshal([]any{in.historyLine("sent")})
	w := cexWritten{id: cuid.New(), status: "sent_to_pl", assignedBy: in.sender.Name, subject: cexSubject(activityLabel, partnerName, cceoName),
		periodLabel: win.label(), created: true}
	_, err := tx.Exec(ctx, `INSERT INTO planning_oversight_follow_up (created_at, updated_at, id, fy, period_type, period_start,
		period_end, period_label, country, region_id, region_name, program_lead_staff_id, program_lead_user_id, program_lead_name,
		cceo_staff_id, cceo_name, school_id, school_name, condition_key, issue_type, metric_key, required_value, planned_value,
		remaining_value, affected_school_ids, affected_count, snapshot, resolution_rule, live_remaining, live_checked_at, priority,
		instruction, instruction_history, assigned_by_id, assigned_by_role, assigned_by_name, assigned_at, due_date, status,
		acknowledged_at, action_linked_at, linked_team_action_ids, linked_note, resolved_at, resolved_by_system, resolution_note,
		closed_by_id, returned_reason, returned_at, reminder_count, last_reminder_at, history, activity_id, activity_label,
		blocker_owner, days_overdue, module, partner_id, partner_name, stage)
		VALUES ($1, $1, $2, $3, $4, $5, $6, $7, $8, NULL, '', $9, $10, $11, $12, $13, NULL, '', $14, $15, $16, $17, $18, $19,
		$20::jsonb, $21, $22::jsonb, $23, $19, $1, $24, $25, $26::jsonb, $27, $28, $29, $1, $30, 'sent_to_pl', NULL, NULL, '[]'::jsonb,
		'', NULL, false, '', '', '', NULL, 0, NULL, $31::jsonb, $32, $33, $34, $35, 'execution', $36, $37, $38)`,
		in.now, w.id, in.fs.period.fy, win.period, win.start, win.end, win.label(), in.country, in.lead.staffID, in.lead.userID,
		in.lead.name, null(in.fs.cceo), cceoName, in.key, in.issue.Key, in.issue.Figure, c.n("due"), c.n("verified"), in.open,
		string(schools), len(in.schoolIDs), string(snapshot), in.issue.ResolutionRule, in.priority, in.instruction, string(instr),
		in.sender.UserID, in.sender.ActiveRole, in.sender.Name, in.due, string(hist), null(in.fs.activityID), activityLabel,
		in.issue.Owner, in.oldest, null(in.fs.partner), partnerName, stage)
	var pg *pgconn.PgError
	if errors.As(err, &pg) && pg.Code == "23505" {
		return w, cexRefuse("Someone has just sent this same follow-up. It is on the list.")
	}
	if err != nil {
		return w, fmt.Errorf("planningmonitor: creating the follow-up: %w", err)
	}
	return w, nil
}

// notify is _notify_lead then _audit: the Lead's notice about the record
// (a reminder on the same notice when it is one), then the audit row.
func (in *cexSend) notify(ctx context.Context, tx pgx.Tx, deps CEXSendDeps, w cexWritten) error {
	who := w.assignedBy
	if who == "" {
		who = "The Country Director"
	}
	verb, title := "asked you to follow up", "Follow up: "+in.issue.Label
	if !w.created {
		verb, title = "reminded you to follow up", "Reminder: "+in.issue.Label
	}
	body := fmt.Sprintf("%s %s with %s on the %s (%s open, %s). Due %d %s. “%s”", who, verb, w.subject,
		strings.ToLower(in.issue.Label), cpoFmt(in.open), w.periodLabel, in.due.Day(), in.due.Format("Jan"), in.instruction)
	priority := "normal"
	if in.priority == "high" || in.priority == "critical" {
		priority = "high"
	}
	_, _, err := activities.NotifyFromPerson(ctx, tx, deps.Push, in.now, activities.PersonNotice{Recipient: in.lead.userID,
		ContextType: cexFollowUpContext, ContextID: w.id, Event: cexFollowUpEvent, Sender: in.sender.UserID,
		Fields: map[string]any{"recipient_role": "Program Lead", "title": title, "body": body, "category": "planning",
			"target_route": in.teamOversightLink(w.id), "action_label": "Follow up", "action_required": true, "priority": priority,
			"status": "unread", "source_event_id": w.id, "read_at": nil, "resolved_at": nil}})
	if errors.Is(err, activities.ErrPhoneCopy) && deps.Logger != nil {
		deps.Logger.WarnContext(ctx, "planningmonitor: the follow-up's phone copy", "follow_up", w.id, "err", err)
	} else if err != nil {
		return err
	}
	if w.created {
		return in.auditRow(ctx, tx, "sent", w.id, w.status, map[string]any{"module": "execution", "open": in.open,
			"due": in.due.Format("2006-01-02"), "priority": in.priority, "stage": in.stageOf()})
	}
	return in.auditRow(ctx, tx, "reminded", w.id, w.status, map[string]any{"module": "execution", "reminder_count": w.reminders})
}

func (in *cexSend) stageOf() string {
	if in.issue.Stage != "" || in.fs.activityID == "" || len(in.f.records) == 0 {
		return in.issue.Stage
	}
	return in.f.records[0].stage
}
