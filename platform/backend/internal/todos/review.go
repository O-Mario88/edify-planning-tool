package todos

import (
	"context"
	"time"

	"github.com/jackc/pgx/v5"
)

// review is an hr_performance_review row.
type review struct {
	id, staffID, reviewType, stage, status string
	due                                    *time.Time
}

// reviewee is one person the reader reviews.
type reviewee struct {
	staffID string
	name    *string
}

// reviewerTodos is hr.review_todos.reviewer_todos over
// performance_engine.team_review_rows: priorities waiting on the reviewer
// and reviews past their due date. A conversation the open window asks for
// (hold_needed, read from conversation_progress) passes the reader on.
func reviewerTodos(ctx context.Context, s *Service, r *reader) ([]todo, error) {
	var reviewable []string
	for reviewee, reviewers := range rules.Lead.ReviewerRoles {
		if contains(reviewers, r.role) {
			reviewable = append(reviewable, reviewee)
		}
	}
	if len(reviewable) == 0 || r.p.StaffProfileID == "" {
		return nil, nil
	}
	rows, err := s.db.Query(ctx, `SELECT sp.id, u.name FROM staff_profile sp JOIN "user" u ON u.id = sp.user_id
WHERE sp.id IN (SELECT supervisee_id FROM staff_supervisor_assignment WHERE supervisor_id = $1)
  AND u.active_role = ANY($2) AND sp.deleted_at IS NULL AND NOT (sp.id = $1) AND u.deleted_at IS NULL
ORDER BY u.name ASC`, r.p.StaffProfileID, reviewable)
	if err != nil {
		return nil, err
	}
	people, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (reviewee, error) {
		var p reviewee
		return p, row.Scan(&p.staffID, &p.name)
	})
	if err != nil || len(people) == 0 {
		return nil, err
	}
	ids := make([]string, len(people))
	for i, p := range people {
		ids[i] = p.staffID
	}
	window := "none"
	if err := s.db.QueryRow(ctx, `SELECT COALESCE((SELECT active_window FROM hr_performance_cycle WHERE fy = $1 ORDER BY id ASC LIMIT 1), 'none')`,
		r.fy).Scan(&window); err != nil {
		return nil, err
	}
	rows, err = s.db.Query(ctx, `SELECT id, staff_id, review_type, stage, status, due_date FROM hr_performance_review
WHERE staff_id = ANY($1) AND fy = $2 ORDER BY due_date ASC, created_at ASC`, ids, r.fy)
	if err != nil {
		return nil, err
	}
	reviews, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (review, error) {
		var v review
		err := row.Scan(&v.id, &v.staffID, &v.reviewType, &v.stage, &v.status, &v.due)
		if v.due != nil {
			v.due = dateOf(*v.due)
		}
		return v, err
	})
	if err != nil {
		return nil, err
	}
	return reviewRows(r, people, reviews, window)
}

// reviewRows turns team_review_rows into reviewer_todos' rows.
func reviewRows(r *reader, people []reviewee, reviews []review, window string) ([]todo, error) {
	byStaff := map[string][]review{}
	annual := map[string]review{}
	for _, v := range reviews {
		byStaff[v.staffID] = append(byStaff[v.staffID], v)
		if _, ok := annual[v.staffID]; !ok && v.reviewType == rules.TargetReviewType {
			annual[v.staffID] = v
		}
	}
	var out []todo
	for _, p := range people {
		name := pyStr(p.name)
		v, hasAnnual := annual[p.staffID]
		if hasAnnual && contains(rules.Lead.ConversationWindows, window) &&
			!contains(rules.Lead.ReviewStagesBeforeConversation, v.stage) {
			return nil, errPassOn
		}
		var overdue []review
		for _, late := range byStaff[p.staffID] {
			if late.due != nil && late.due.Before(r.today) && !contains(rules.Lead.ReviewDoneStages, late.stage) &&
				!contains(rules.Lead.ReviewClosedStatuses, late.status) {
				overdue = append(overdue, late)
			}
		}
		annualOverdue := false
		for _, late := range overdue {
			annualOverdue = annualOverdue || (hasAnnual && late.id == v.id)
		}
		waiting := hasAnnual && v.stage == rules.Lead.ReviewStageManagerReview
		if waiting {
			var due *time.Time
			if annualOverdue {
				due = v.due
			}
			out = append(out, reviewRow(r, "Review "+name+"'s priorities", p.staffID, name, due, annualOverdue))
		}
		for _, late := range overdue {
			if hasAnnual && late.id == v.id && waiting {
				continue
			}
			out = append(out, reviewRow(r, "Complete "+name+"'s overdue performance review", p.staffID, name, late.due, true))
		}
	}
	return out, nil
}

func reviewRow(r *reader, title, staffID, name string, due *time.Time, overdue bool) todo {
	t := todo{Title: title, Category: rules.Lead.ReviewCategory, Priority: "medium", StatusKey: "waiting_me",
		Actionable: true, Linked: name, ActionLabel: "Open conversation",
		ActionURL: "/performance-conversation?staff=" + staffID, Shape: "/performance-conversation?staff={id}", Due: due}
	if overdue {
		t.Priority, t.StatusKey = "high", "overdue"
	}
	if t.Due == nil {
		today := r.today
		t.Due = &today
	}
	return t
}
