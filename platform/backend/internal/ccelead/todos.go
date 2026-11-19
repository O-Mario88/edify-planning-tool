package ccelead

import (
	"context"
	"fmt"
	"strconv"
	"time"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// The Regional Programme Lead's To-Dos (todo_service._cce_leadership_todos
// for the Regional Lead): last month's report when it is overdue, reports
// the RVP returned, slipped meetings of the rhythm, and feedback written but
// not shared.

const (
	// returnedLimit, rhythmLimit and draftLimit are how many of each the
	// queue lists.
	returnedLimit = 4
	rhythmLimit   = 5
	draftLimit    = 5
	// todoDescriptionLength is how much of a description a row keeps.
	todoDescriptionLength = 180
)

// Todo is one of the Regional Lead's rows, in todo_service's words.
type Todo struct {
	// ID is the row's key, as the existing builder writes it.
	ID                            string
	Title, Description, Priority  string
	StatusKey, StatusLabel        string
	StatusTone, DueLabel, DueTone string
	Linked, ActionLabel, URL      string
	// Due is the row's day (_due_sort); nil is today.
	Due *time.Time
}

// RegionalLeadTodos is _cce_leadership_todos for the Regional Lead p at now.
func RegionalLeadTodos(ctx context.Context, db schooldirectory.Querier, p auth.Principal, now time.Time) ([]Todo, error) {
	local := now.In(zone)
	today := time.Date(local.Year(), local.Month(), local.Day(), 0, 0, 0, 0, time.UTC)
	current := time.Date(today.Year(), today.Month(), 1, 0, 0, 0, 0, time.UTC)
	previous := current.AddDate(0, -1, 0)
	dueBy := time.Date(current.Year(), current.Month(), 10, 0, 0, 0, 0, time.UTC)
	var out []Todo
	// report_state: last month's report, overdue once the tenth has passed
	// with it unstarted, a draft or returned.
	var lastID, lastStatus *string
	err := db.QueryRow(ctx, `SELECT id, status FROM cce_regional_report WHERE author_id = $1 AND period = $2::date`,
		p.UserID, previous.Format(time.DateOnly)).Scan(&lastID, &lastStatus)
	if err != nil && err != pgx.ErrNoRows {
		return nil, fmt.Errorf("ccelead: reading last month's report: %w", err)
	}
	late := !previous.Before(reportingStarts) && today.After(dueBy) &&
		(lastStatus == nil || *lastStatus == "draft" || *lastStatus == "returned")
	if late {
		out = append(out, leadTodo("cce-report-due-"+previous.Format("2006-01"), "Submit the "+previous.Format("January")+" CCE report",
			"The monthly report to the RVP and the VP of CCE is past its due date.", "critical", ReportsPath,
			"Open reports", "Monthly report", &dueBy, true))
	}
	// Returned reports, newest period first, but not last month's when its
	// overdue row already stands for it.
	rows, err := db.Query(ctx, `SELECT id, period, COALESCE(review_note, '') FROM cce_regional_report
WHERE author_id = $1 AND status = 'returned' ORDER BY period DESC, created_at DESC LIMIT $2`, p.UserID, returnedLimit)
	if err != nil {
		return nil, fmt.Errorf("ccelead: reading the returned reports: %w", err)
	}
	type returned struct {
		id     string
		period time.Time
		note   string
	}
	back, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (returned, error) {
		var r returned
		return r, row.Scan(&r.id, &r.period, &r.note)
	})
	if err != nil {
		return nil, fmt.Errorf("ccelead: reading the returned reports: %w", err)
	}
	for _, r := range back {
		if late && lastID != nil && r.id == *lastID {
			continue
		}
		note := r.note
		if note == "" {
			note = "The RVP returned the report for revision."
		}
		out = append(out, leadTodo("cce-report-returned-"+r.id, "Revise the "+r.period.Format("January")+" CCE report", note, "high", ReportsPath,
			"Revise", "Monthly report", nil, false))
	}
	// The rhythm's overdue and missed meetings, worst first.
	reach, err := leadReach(ctx, db, p)
	if err != nil {
		return nil, err
	}
	rhythm, err := leadRhythm(ctx, db, p, today, reach)
	if err != nil {
		return nil, err
	}
	shown := 0
	for _, row := range rhythm {
		if shown == rhythmLimit {
			break
		}
		if row.state != "overdue" && row.state != "missed" {
			continue
		}
		shown++
		note := row.note
		if note == "" {
			note = row.expectation
		}
		out = append(out, leadTodo("cce-rhythm-"+row.kind+"-"+row.subject, row.label+" · "+row.subject, note, "high", EngagementsPath, "Log it",
			"Engagement rhythm", row.dueBy, true))
	}
	// Training feedback the lead wrote and has not shared.
	rows, err = db.Query(ctx, `SELECT id, COALESCE(subject, ''), COALESCE(country, '') FROM cce_regional_engagement
WHERE kind = 'training_observation' AND author_id = $1 AND feedback_shared_at IS NULL
ORDER BY held_on DESC, created_at DESC LIMIT $2`, p.UserID, draftLimit)
	if err != nil {
		return nil, fmt.Errorf("ccelead: reading the unshared feedback: %w", err)
	}
	drafts, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) ([3]string, error) {
		var d [3]string
		return d, row.Scan(&d[2], &d[0], &d[1])
	})
	if err != nil {
		return nil, fmt.Errorf("ccelead: reading the unshared feedback: %w", err)
	}
	for _, d := range drafts {
		linked := d[1]
		if linked == "" {
			linked = "Training observation"
		}
		out = append(out, leadTodo("cce-feedback-draft-"+d[2], "Share training feedback", d[0], "medium", EngagementsPath, "Open log", linked, nil, false))
	}
	return out, nil
}

// leadTodo is the builder's row(): overdue rows read Overdue in danger,
// others Waiting on Me; a dated row's due is "%-d %b".
func leadTodo(key, title, description, priority, url, action, linked string, due *time.Time, overdue bool) Todo {
	t := Todo{ID: key, Title: title, Description: firstRunes(description, todoDescriptionLength), Priority: priority,
		StatusKey: "waiting_me", StatusLabel: "Waiting on Me", StatusTone: "warning", DueLabel: "—", DueTone: "neutral",
		Linked: linked, ActionLabel: action, URL: url, Due: due}
	if due != nil {
		t.DueLabel, t.DueTone = strconv.Itoa(due.Day())+" "+due.Format("Jan"), "warning"
	}
	if overdue {
		t.StatusKey, t.StatusLabel, t.StatusTone, t.DueTone = "overdue", "Overdue", "danger", "danger"
	}
	return t
}

// firstRunes is Python's s[:n].
func firstRunes(s string, n int) string {
	runes := []rune(s)
	if len(runes) <= n {
		return s
	}
	return string(runes[:n])
}
