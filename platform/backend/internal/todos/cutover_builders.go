package todos

import (
	"context"
	"fmt"
	"strconv"
	"time"

	"github.com/jackc/pgx/v5"
)

// Native Go implementations replacing passOnIf guards across officer, lead,
// director, and admin queues for the Uganda Go cutover (Batch 9).

// schoolActionTodos replaces schoolActionGuard (_school_action_todos).
func schoolActionTodos(ctx context.Context, s *Service, r *reader) ([]todo, error) {
	if r.p.UserID == "" {
		return nil, nil
	}
	rows, err := s.db.Query(ctx, `
SELECT a.id, COALESCE(a.requested_action, ''), COALESCE(a.workflow_route, '/actions/mine'),
       COALESCE(a.priority, 'medium'), a.due_date, a.state,
       COALESCE(sc.name, 'School'), COALESCE(u.name, '')
FROM team_action a
LEFT JOIN school sc ON sc.id = a.school_id
LEFT JOIN "user" u ON u.id = a.sender_id
WHERE a.recipient_id = $1 AND a.state = ANY($2)
ORDER BY a.due_date ASC NULLS LAST, a.created_at ASC
LIMIT 25`, r.p.UserID, rules.TeamActionActiveStates)
	if err != nil {
		return nil, err
	}
	return pgx.CollectRows(rows, func(row pgx.CollectableRow) (todo, error) {
		var id, reqAction, route, prio, state, schoolName, senderName string
		var dueDate *time.Time
		err := row.Scan(&id, &reqAction, &route, &prio, &dueDate, &state, &schoolName, &senderName)
		if err != nil {
			return todo{}, err
		}
		statusKey, statusLabel, statusTone := "waiting_me", "Waiting on Me", "info"
		var due *time.Time
		if dueDate != nil {
			d := dateOf(*dueDate)
			due = d
			switch {
			case d.Before(r.today):
				statusKey, statusLabel, statusTone = "overdue", "Overdue", "danger"
			case d.Equal(r.today):
				statusKey, statusLabel, statusTone = "due_today", "Due Today", "warning"
			}
		} else if state == "blocked" {
			statusKey, statusLabel, statusTone = "blocked", "Blocked", "danger"
		}
		if reqAction == "" {
			reqAction = "Resolve school action"
		}
		if route == "" {
			route = "/actions/mine"
		}
		desc := schoolName
		if senderName != "" {
			desc = "From " + senderName + " · " + schoolName
		}
		t := todo{
			ID: "team-action-" + id, Title: reqAction, Description: desc, Described: true,
			Category: "Execution", Priority: prio,
			StatusKey: statusKey, StatusLabel: statusLabel, StatusTone: statusTone,
			Linked: schoolName, ActionLabel: "Open", ActionURL: route, Shape: "/actions/mine",
			Actionable: true, Due: due,
		}
		return withDue(t, r.today), nil
	})
}

// plReviewTodos replaces plReviewGuard (_pl_review_todos).
func plReviewTodos(ctx context.Context, s *Service, r *reader) ([]todo, error) {
	if r.role != leadRole && r.role != adminRole {
		return nil, nil
	}
	var sql string
	var args []any
	if r.role == adminRole {
		sql = `
SELECT a.id, COALESCE(a.activity_type, ''), COALESCE(sc.name, ''), COALESCE(c.name, '')
FROM activity a
LEFT JOIN school sc ON sc.id = a.school_id
LEFT JOIN cluster c ON c.id = a.cluster_id
WHERE a.deleted_at IS NULL AND a.status = ANY($1)
ORDER BY a.updated_at ASC LIMIT 10`
		args = []any{rules.Lead.LeadReviewableStatuses}
	} else {
		team, err := s.supervisees(ctx, r)
		if err != nil || len(team) == 0 {
			return nil, err
		}
		sql = `
SELECT a.id, COALESCE(a.activity_type, ''), COALESCE(sc.name, ''), COALESCE(c.name, '')
FROM activity a
LEFT JOIN school sc ON sc.id = a.school_id
LEFT JOIN cluster c ON c.id = a.cluster_id
WHERE a.deleted_at IS NULL AND a.status = ANY($1)
  AND (a.responsible_staff_id = ANY($2) OR a.monitored_by_staff_id = ANY($2))
ORDER BY a.updated_at ASC LIMIT 10`
		args = []any{rules.Lead.LeadReviewableStatuses, team}
	}
	rows, err := s.db.Query(ctx, sql, args...)
	if err != nil {
		return nil, err
	}
	return pgx.CollectRows(rows, func(row pgx.CollectableRow) (todo, error) {
		var id, atype, schoolName, clusterName string
		if err := row.Scan(&id, &atype, &schoolName, &clusterName); err != nil {
			return todo{}, err
		}
		where := schoolName
		if where == "" {
			where = clusterName
		}
		if where == "" {
			where = "the field"
		}
		label := rules.ActivityTypeLabels[atype]
		if label == "" {
			label = "Activity"
		}
		return todo{
			ID: "plrev-" + id, Title: "Review Completion",
			Description: label + " at " + where + " is waiting on your confirmation", Described: true,
			Category: "Execution", Priority: "high",
			StatusKey: "waiting_me", StatusLabel: "Waiting on Me", StatusTone: "info",
			DueLabel: "—", DueTone: "neutral",
			Linked: where + " · completion", ActionLabel: "Review",
			ActionURL: "/pl/review-queue", Shape: "/pl/review-queue", Actionable: true,
		}, nil
	})
}

// partnerInvoiceTodos replaces partnerInvoiceGuard (_partner_invoice_todos).
func partnerInvoiceTodos(ctx context.Context, s *Service, r *reader) ([]todo, error) {
	if r.role != leadRole && r.role != "Accountant" && r.role != adminRole {
		return nil, nil
	}
	status, title, actionLabel, url := "confirmed_by_pl", "Process Partner Payment", "Pay", "/accounts/partner-payments"
	if r.role == leadRole {
		status, title, actionLabel, url = "submitted_to_pl", "Confirm Partner Invoice Against the Plan", "Confirm", "/fund-approvals"
	}
	var sql string
	var args []any
	if r.role == leadRole {
		team, err := s.supervisees(ctx, r)
		if err != nil || len(team) == 0 {
			return nil, err
		}
		sql = `
SELECT DISTINCT pi.id, COALESCE(p.name, 'Partner'), pi.created_at
FROM partner_invoice pi
LEFT JOIN partner p ON p.id = pi.partner_id
JOIN partner_invoice_item item ON item.invoice_id = pi.id
JOIN activity a ON a.id = item.activity_id
WHERE pi.status = $1
  AND (a.responsible_staff_id = ANY($2)
       OR (a.responsible_staff_id IS NULL AND a.monitored_by_staff_id = ANY($2)))
ORDER BY pi.created_at ASC LIMIT 20`
		args = []any{status, team}
	} else {
		sql = `
SELECT pi.id, COALESCE(p.name, 'Partner'), pi.created_at
FROM partner_invoice pi
LEFT JOIN partner p ON p.id = pi.partner_id
WHERE pi.status = $1
ORDER BY pi.created_at ASC LIMIT 20`
		args = []any{status}
	}
	rows, err := s.db.Query(ctx, sql, args...)
	if err != nil {
		return nil, err
	}
	return pgx.CollectRows(rows, func(row pgx.CollectableRow) (todo, error) {
		var id, name string
		var created time.Time
		if err := row.Scan(&id, &name, &created); err != nil {
			return todo{}, err
		}
		return todo{
			ID: "partner-inv-" + id, Title: title,
			Description: name + " invoice awaiting action.", Described: true,
			Category: "Finance", Priority: "high",
			StatusKey: "waiting_me", StatusLabel: "Waiting on Me", StatusTone: "info",
			DueLabel: "—", DueTone: "neutral",
			Linked: name + " · invoice", ActionLabel: actionLabel,
			ActionURL: url, Shape: url, Actionable: true,
		}, nil
	})
}

// leaveTodos replaces leaveGuard (_leave_todos).
func leaveTodos(ctx context.Context, s *Service, r *reader) ([]todo, error) {
	if r.role != leadRole && r.role != cdRole && r.role != "HumanResources" && r.role != adminRole {
		return nil, nil
	}
	var sql string
	var args []any
	if r.role == leadRole {
		team, err := s.supervisees(ctx, r)
		if err != nil || len(team) == 0 {
			return nil, err
		}
		sql = `
SELECT l.id, l.status, COALESCE(l.type, 'leave'), COALESCE(l.days, 0), COALESCE(u.name, 'a staff member')
FROM leave l
JOIN staff_profile sp ON sp.id = l.staff_id
LEFT JOIN "user" u ON u.id = sp.user_id
WHERE l.status = 'pending' AND l.staff_id = ANY($1)
ORDER BY l.start_date ASC LIMIT 10`
		args = []any{team}
	} else {
		sql = `
SELECT l.id, l.status, COALESCE(l.type, 'leave'), COALESCE(l.days, 0), COALESCE(u.name, 'a staff member')
FROM leave l
LEFT JOIN staff_profile sp ON sp.id = l.staff_id
LEFT JOIN "user" u ON u.id = sp.user_id
WHERE l.status IN ('pending', 'hr_review')
ORDER BY l.start_date ASC LIMIT 10`
	}
	rows, err := s.db.Query(ctx, sql, args...)
	if err != nil {
		return nil, err
	}
	return pgx.CollectRows(rows, func(row pgx.CollectableRow) (todo, error) {
		var id, status, leaveType, who string
		var days int
		if err := row.Scan(&id, &status, &leaveType, &days, &who); err != nil {
			return todo{}, err
		}
		title := "Review Leave Request"
		if status == "hr_review" {
			title = "Escalated Leave Request"
		}
		daysStr := "—"
		if days > 0 {
			daysStr = strconv.Itoa(days)
		}
		return todo{
			ID: "leave-" + id, Title: title,
			Description: fmt.Sprintf("%s requested %s (%s days)", who, leaveType, daysStr), Described: true,
			Category: "Leave", Priority: "medium",
			StatusKey: "waiting_me", StatusLabel: "Waiting on Me", StatusTone: "info",
			DueLabel: "—", DueTone: "neutral",
			Linked: "Leave · " + who, ActionLabel: "Review",
			ActionURL: "/leave/approvals?id=" + id, Shape: "/leave/approvals", Actionable: true,
		}, nil
	})
}

// escalationTodos replaces escalationGuard (pl_escalation_todos & _escalation_todos).
func escalationTodos(ctx context.Context, s *Service, r *reader) ([]todo, error) {
	if r.role != leadRole && r.role != cdRole && r.role != adminRole && r.role != rvpRole {
		return nil, nil
	}
	addr := map[string]string{
		leadRole:  "pl",
		cdRole:    "cd",
		rvpRole:   "rvp",
		adminRole: "",
	}[r.role]
	rows, err := s.db.Query(ctx, `
SELECT id, COALESCE(raised_by_name, 'your officer'), COALESCE(subject, ''),
       COALESCE(requested_decision, ''), COALESCE(severity, 'normal'),
       COALESCE(category, ''), due_date, created_at
FROM leadership_escalation
WHERE status <> 'resolved' AND raised_by_user_id <> $1
  AND ($2 = '' OR addressed_role = $2 OR assigned_to_user_id = $1)
ORDER BY created_at ASC LIMIT 25`, r.p.UserID, addr)
	if err != nil {
		return nil, err
	}
	return pgx.CollectRows(rows, func(row pgx.CollectableRow) (todo, error) {
		var id, raiser, subject, reqDec, severity, category string
		var dueDate *time.Time
		var created time.Time
		if err := row.Scan(&id, &raiser, &subject, &reqDec, &severity, &category, &dueDate, &created); err != nil {
			return todo{}, err
		}
		due := dueDate
		if due == nil {
			d := dateOf(created.In(zone)).AddDate(0, 0, 5)
			due = &d
		}
		prio := "medium"
		switch severity {
		case "urgent", "critical":
			prio = "critical"
		case "high":
			prio = "high"
		}
		desc := subject
		if reqDec != "" {
			desc += " — asks: " + reqDec
		}
		t := todo{
			ID: "esc-decide-" + id, Title: "Decide escalation from " + raiser,
			Description: desc, Described: true,
			Category: "Leadership", Priority: prio,
			StatusKey: "waiting_me", StatusLabel: "Waiting on Me", StatusTone: "warning",
			Linked: "Escalation · " + category, ActionLabel: "Open",
			ActionURL: "/escalations", Shape: "/escalations", Actionable: true, Due: due,
		}
		return withDue(t, r.today), nil
	})
}

// pdTodos replaces pdGuard (_pd_todos).
func pdTodos(ctx context.Context, s *Service, r *reader) ([]todo, error) {
	if r.p.StaffProfileID == "" {
		return nil, nil
	}
	rows, err := s.db.Query(ctx, `
SELECT id, COALESCE(course_name, 'PD Request'), status, updated_at
FROM pd_request
WHERE staff_id = $1
  AND status IN ('returned', 'approved', 'enrollment_pending', 'in_progress', 'awaiting_certificate')
ORDER BY updated_at DESC LIMIT 15`, r.p.StaffProfileID)
	if err != nil {
		return nil, err
	}
	return pgx.CollectRows(rows, func(row pgx.CollectableRow) (todo, error) {
		var id, course, status string
		var updated time.Time
		if err := row.Scan(&id, &course, &status, &updated); err != nil {
			return todo{}, err
		}
		due := dateOf(updated.In(zone))
		return todo{
			ID: "pd-own-" + id, Title: "Act on PD Request",
			Description: "Action needed on “" + course + "”.", Described: true,
			Category: "Professional Development", Priority: "medium",
			StatusKey: "waiting_me", StatusLabel: "Waiting on Me", StatusTone: "warning",
			DueLabel: "—", DueTone: "neutral",
			Linked: course, ActionLabel: "Open",
			ActionURL: "/my-professional-development/request?id=" + id,
			Shape:     "/my-professional-development", Actionable: true, Due: due,
		}, nil
	})
}

// fieldDebriefTodos replaces fieldDebriefGuard (_field_debrief_todos).
func fieldDebriefTodos(ctx context.Context, s *Service, r *reader) ([]todo, error) {
	if r.p.UserID == "" {
		return nil, nil
	}
	rows, err := s.db.Query(ctx, `
SELECT a.id, COALESCE(NULLIF(a.action, ''), a.issue, 'Debrief action'), a.due_date
FROM daily_debrief_action a
JOIN daily_debrief d ON d.id = a.debrief_id
WHERE d.deleted_at IS NULL AND a.owner_user_id = $1 AND a.status NOT IN ('completed', 'closed', 'cancelled')
ORDER BY a.due_date ASC NULLS LAST LIMIT 15`, r.p.UserID)
	if err != nil {
		return nil, err
	}
	return pgx.CollectRows(rows, func(row pgx.CollectableRow) (todo, error) {
		var id, title string
		var dueDate *time.Time
		if err := row.Scan(&id, &title, &dueDate); err != nil {
			return todo{}, err
		}
		var due *time.Time
		if dueDate != nil {
			due = dateOf(*dueDate)
		}
		t := todo{
			ID: "debrief-act-" + id, Title: title,
			Category: "Field Debrief", Priority: "medium",
			StatusKey: "waiting_me", StatusLabel: "Waiting on Me", StatusTone: "info",
			Linked: "Field Debrief", ActionLabel: "Open",
			ActionURL: "/debriefs", Shape: "/debriefs", Actionable: true, Due: due,
		}
		return withDue(t, r.today), nil
	})
}

// followUpTodos replaces followUpGuard (apps.staff_activity.todos:follow_up_todos).
func followUpTodos(ctx context.Context, s *Service, r *reader) ([]todo, error) {
	if r.p.UserID == "" {
		return nil, nil
	}
	rows, err := s.db.Query(ctx, `
SELECT id, COALESCE(note, 'Staff activity follow-up'), due_date
FROM staff_usage_follow_up
WHERE assignee_id = $1 AND status IN ('open', 'pending')
ORDER BY due_date ASC NULLS LAST LIMIT 15`, r.p.UserID)
	if err != nil {
		return nil, err
	}
	return pgx.CollectRows(rows, func(row pgx.CollectableRow) (todo, error) {
		var id, note string
		var dueDate *time.Time
		if err := row.Scan(&id, &note, &dueDate); err != nil {
			return todo{}, err
		}
		var due *time.Time
		if dueDate != nil {
			due = dateOf(*dueDate)
		}
		t := todo{
			ID: "usage-fu-" + id, Title: "Respond to Staff Activity Follow-Up",
			Description: truncateRunes(note, 160), Described: true,
			Category: "Follow-up", Priority: "medium",
			StatusKey: "waiting_me", StatusLabel: "Waiting on Me", StatusTone: "warning",
			Linked: "Staff Activity", ActionLabel: "Open",
			ActionURL: "/staff-activity", Shape: "/staff-activity", Actionable: true, Due: due,
		}
		return withDue(t, r.today), nil
	})
}

// directorSSATodos replaces directorSSAGuard (collection_todos for CountryDirector).
func directorSSATodos(ctx context.Context, s *Service, r *reader) ([]todo, error) {
	var n int
	if err := s.db.QueryRow(ctx, `SELECT COUNT(*) FROM ssa_record
WHERE deleted_at IS NULL AND verification_status = $1`, rules.IA.CollectionRecordPending).Scan(&n); err != nil {
		return nil, err
	}
	if n == 0 {
		return nil, nil
	}
	return []todo{{
		ID: "cd-ssa-verify", Title: "Verify " + plural(n, "SSA record"),
		Category: "Baseline & Field Data", Priority: "medium",
		StatusKey: "waiting_me", StatusLabel: "Waiting on Me", StatusTone: "info",
		DueLabel: "—", DueTone: "neutral",
		Linked: plural(n, "record"), ActionLabel: "Open SSA Queue",
		ActionURL: "/ssa/verification/", Shape: "/ssa/verification/", Actionable: true,
	}}, nil
}

// myTargetTodos replaces myTargetGuard (_my_target_todos).
func myTargetTodos(ctx context.Context, s *Service, r *reader) ([]todo, error) {
	if r.p.StaffProfileID == "" && r.p.UserID == "" {
		return nil, nil
	}
	var pending int
	if err := s.db.QueryRow(ctx, `SELECT COUNT(*) FROM hr_performance_review
WHERE staff_id = $1 AND review_type = $2 AND NOT (stage = ANY($3))`,
		r.p.StaffProfileID, rules.TargetReviewType, rules.TargetReviewStagesNotAgreed).Scan(&pending); err != nil {
		return nil, err
	}
	if pending == 0 {
		return nil, nil
	}
	return []todo{{
		ID: "my-target-review", Title: "Review My Targets & Priorities",
		Category: "Performance", Priority: "medium",
		StatusKey: "waiting_me", StatusLabel: "Waiting on Me", StatusTone: "info",
		DueLabel: "—", DueTone: "neutral",
		Linked: "My Target", ActionLabel: "Open",
		ActionURL: "/my-targets", Shape: "/my-targets", Actionable: true,
	}}, nil
}

// hrExceptionTodos replaces hrExceptionGuard (_hr_exception_todos).
func hrExceptionTodos(ctx context.Context, s *Service, r *reader) ([]todo, error) {
	var out []todo
	var escalatedLeave int
	if err := s.db.QueryRow(ctx, `SELECT COUNT(*) FROM leave WHERE status = 'hr_review'`).Scan(&escalatedLeave); err != nil {
		return nil, err
	}
	if escalatedLeave > 0 {
		out = append(out, todo{
			ID: "hr-exc-leave", Title: "Review " + plural(escalatedLeave, "escalated leave request"),
			Category: "HR", Priority: "high",
			StatusKey: "waiting_me", StatusLabel: "Waiting on Me", StatusTone: "warning",
			DueLabel: "—", DueTone: "neutral",
			Linked: "Leave Approvals", ActionLabel: "Review",
			ActionURL: "/leave/approvals", Shape: "/leave/approvals", Actionable: true,
		})
	}
	var policies int
	if err := s.db.QueryRow(ctx, `SELECT COUNT(*) FROM document_asset WHERE archived_at IS NULL AND status = ANY($1)`,
		rules.Admin.PolicyAwaitingPublicationStatuses).Scan(&policies); err != nil {
		return nil, err
	}
	if policies > 0 {
		out = append(out, todo{
			ID: "hr-exc-policy", Title: "Publish " + plural(policies, "HR policy"),
			Category: "HR", Priority: "medium",
			StatusKey: "waiting_me", StatusLabel: "Waiting on Me", StatusTone: "info",
			DueLabel: "—", DueTone: "neutral",
			Linked: "Policies & Documents", ActionLabel: "Open",
			ActionURL: "/policy-compliance", Shape: "/policy-compliance", Actionable: true,
		})
	}
	return out, nil
}

// accountantTodos replaces accountantGuard (_accountant_todos).
func accountantTodos(ctx context.Context, s *Service, _ *reader) ([]todo, error) {
	st := rules.Admin.AccountantQueueStatuses
	var out []todo
	var monthly, weekly, advances int
	if err := s.db.QueryRow(ctx, `SELECT
		(SELECT COUNT(*) FROM fund_request WHERE status = $1),
		(SELECT COUNT(*) FROM weekly_fund_request WHERE status = $2),
		(SELECT COUNT(*) FROM advance_request WHERE status = ANY($3) OR (returned_amount > 0 AND return_verified_at IS NULL))`,
		st["monthly_request"], st["weekly_request"],
		[]string{st["accountability"], st["reimbursement"], st["disbursed"]}).Scan(&monthly, &weekly, &advances); err != nil {
		return nil, err
	}
	if monthly > 0 {
		out = append(out, todo{
			ID: "acct-monthly", Title: "Process " + plural(monthly, "monthly fund request"),
			Category: "Finance", Priority: "high",
			StatusKey: "waiting_me", StatusLabel: "Waiting on Me", StatusTone: "info",
			DueLabel: "—", DueTone: "neutral",
			Linked: "Disbursements", ActionLabel: "Open",
			ActionURL: "/disbursements", Shape: "/disbursements", Actionable: true,
		})
	}
	if weekly > 0 {
		out = append(out, todo{
			ID: "acct-weekly", Title: "Process " + plural(weekly, "weekly fund request"),
			Category: "Finance", Priority: "high",
			StatusKey: "waiting_me", StatusLabel: "Waiting on Me", StatusTone: "info",
			DueLabel: "—", DueTone: "neutral",
			Linked: "Disbursements", ActionLabel: "Open",
			ActionURL: "/disbursements", Shape: "/disbursements", Actionable: true,
		})
	}
	if advances > 0 {
		out = append(out, todo{
			ID: "acct-advances", Title: "Settle " + plural(advances, "advance"),
			Category: "Finance", Priority: "medium",
			StatusKey: "waiting_me", StatusLabel: "Waiting on Me", StatusTone: "warning",
			DueLabel: "—", DueTone: "neutral",
			Linked: "Disbursements", ActionLabel: "Open",
			ActionURL: "/disbursements", Shape: "/disbursements", Actionable: true,
		})
	}
	return out, nil
}
