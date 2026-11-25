package planningmonitor

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"log/slog"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/activities"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/audit"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// The follow-up sweep (country_oversight.followups.sweep): every open
// follow-up's gap read again, its live figure kept, and the one whose gap
// cleared (a metric_zero rule reaching nothing) closed by the system.

// SweepDB is what the sweep needs of the database: reads, and a
// transaction for each follow-up's writes.
type SweepDB interface {
	schooldirectory.Querier
	BeginTx(context.Context, pgx.TxOptions) (pgx.Tx, error)
}

// sweptFollowUp is one open follow-up as refresh reads it.
type sweptFollowUp struct {
	id, module, issue, fy, period, country                          string
	start                                                           time.Time
	lead, leadUser, cceo, school, partner, activity, assignedBy     string
	key, cceoName, schoolName, leadName, activityLabel, partnerName string
}

// SweepFollowUps is sweep: each open follow-up, oldest first; one that
// cannot be read again is logged and the rest go on. It answers how many
// were checked and how many closed.
func SweepFollowUps(ctx context.Context, db SweepDB, push activities.NoticePush, now time.Time, logger *slog.Logger) (int, int, error) {
	if logger == nil {
		logger = slog.Default()
	}
	open, err := openFollowUps(ctx, db)
	if err != nil {
		return 0, 0, err
	}
	local := now.In(cpoLocation)
	today := time.Date(local.Year(), local.Month(), local.Day(), 0, 0, 0, 0, time.UTC)
	checked, resolved := 0, 0
	for _, f := range open {
		checked++
		closed, err := refreshFollowUp(ctx, db, push, f, now, today)
		if err != nil {
			logger.ErrorContext(ctx, "planningmonitor: could not refresh the follow-up", "follow_up", f.id, "err", err)
			continue
		}
		if closed {
			resolved++
		}
	}
	return checked, resolved, nil
}

func openFollowUps(ctx context.Context, db schooldirectory.Querier) ([]sweptFollowUp, error) {
	rows, err := db.Query(ctx, `SELECT id, COALESCE(module, 'planning'), COALESCE(issue_type, ''), COALESCE(fy, ''), COALESCE(period_type, ''),
  COALESCE(country, ''), period_start, COALESCE(program_lead_staff_id, ''), COALESCE(program_lead_user_id, ''), COALESCE(cceo_staff_id, ''),
  COALESCE(school_id, ''), COALESCE(partner_id, ''), COALESCE(activity_id, ''), COALESCE(assigned_by_id, ''), COALESCE(condition_key, ''),
  COALESCE(cceo_name, ''), COALESCE(school_name, ''), COALESCE(program_lead_name, ''), COALESCE(activity_label, ''), COALESCE(partner_name, '')
FROM planning_oversight_follow_up WHERE status = ANY($1) ORDER BY assigned_at, id`, rules.CountryExecution.FollowUps.OpenStates)
	if err != nil {
		return nil, fmt.Errorf("planningmonitor: the open follow-ups: %w", err)
	}
	defer rows.Close()
	out := []sweptFollowUp{}
	for rows.Next() {
		var f sweptFollowUp
		if err := rows.Scan(&f.id, &f.module, &f.issue, &f.fy, &f.period, &f.country, &f.start, &f.lead, &f.leadUser, &f.cceo,
			&f.school, &f.partner, &f.activity, &f.assignedBy, &f.key, &f.cceoName, &f.schoolName, &f.leadName, &f.activityLabel,
			&f.partnerName); err != nil {
			return nil, err
		}
		out = append(out, f)
	}
	return out, rows.Err()
}

// periodOf is Scope.window as the tab's selection.
func (f sweptFollowUp) periodFilters() cpoFilters {
	out := cpoFilters{fy: f.fy, period: "fy"}
	switch f.period {
	case "quarter":
		out.period, out.quarter = "quarter", quarterOfDay(f.start)
	case "month":
		out.period, out.month = "month", int(f.start.Month())
	case "week":
		y, w := f.start.ISOWeek()
		out.period, out.week = "week", fmt.Sprintf("%04d-W%02d", y, w)
	}
	return out
}

// sweepScope is _system_scope(country): the country unbounded when the
// follow-up names none.
func sweepScope(ctx context.Context, db schooldirectory.Querier, country string) (schooldirectory.Scope, error) {
	if strings.TrimSpace(country) == "" {
		return schooldirectory.Scope{Role: "CountryDirector", UserID: "system", CountryScope: true}, nil
	}
	return systemScopeOf(ctx, db, country)
}

// refreshFollowUp is refresh for either stage: the gap read again, then the
// follow-up's live figure, or its close.
func refreshFollowUp(ctx context.Context, db SweepDB, push activities.NoticePush, f sweptFollowUp, now, today time.Time) (bool, error) {
	sys, err := sweepScope(ctx, db, f.country)
	if err != nil {
		return false, err
	}
	roster, err := cexRosterOf(ctx, db, sys)
	if err != nil {
		return false, err
	}
	var remaining int
	var label, rule, note, route, about string
	extra := map[string]any{}
	p := f.periodFilters()
	if f.module == "execution" {
		issue, ok := cexIssueOf(f.issue)
		if !ok {
			return false, nil
		}
		fs := cexFollowScope{period: cexFilters{fy: p.fy, period: p.period, quarter: p.quarter, month: p.month, week: p.week},
			lead: f.lead, cceo: f.cceo, partner: f.partner, activityID: f.activity}
		figures, err := cexEvaluate(ctx, db, sys, fs, today)
		if err != nil {
			return false, err
		}
		if remaining, err = cexMetric(ctx, db, sys, issue, fs, figures, today); err != nil {
			return false, err
		}
		label, rule, note = issue.Label, issue.ResolutionRule, "The condition cleared."
		route = "/country-planning-oversight/?view=execution"
		about = firstOf(f.activityLabel, f.partnerName, f.cceoName, f.leadName)
		extra["module"] = "execution"
	} else {
		issue, ok := cpoIssueOf(f.issue)
		if !ok {
			return false, nil
		}
		figures, err := cpoEvaluate(ctx, db, sys, cpoFollowScope{filters: p, lead: f.lead, cceo: f.cceo, school: f.school}, roster, today)
		if err != nil {
			return false, err
		}
		_, _, remaining = issue.metricValues(figures.tally)
		label, rule, note = issue.Label, issue.ResolutionRule, "The gap reached zero."
		route = "/country-planning-oversight/"
		about = firstOf(f.cceoName, f.schoolName, f.leadName)
	}
	tx, err := db.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite})
	if err != nil {
		return false, fmt.Errorf("planningmonitor: opening the follow-up's refresh: %w", err)
	}
	defer func() { _ = tx.Rollback(ctx) }()
	if rule != "metric_zero" || remaining > 0 {
		if _, err := tx.Exec(ctx, `SELECT gateway_scheduler.keep_followup_figure($1, $2, $3)`, f.id, remaining, now); err != nil {
			return false, fmt.Errorf("planningmonitor: keeping the follow-up's figure: %w", err)
		}
		return false, tx.Commit(ctx)
	}
	if err := resolveFollowUp(ctx, tx, push, f, remaining, now, label, note, route, about, extra); err != nil {
		return false, err
	}
	return true, tx.Commit(ctx)
}

// resolveFollowUp is refresh's close: the follow-up resolved by the system
// with its history line, the Lead's notices resolved, the Director told,
// and the audit row.
func resolveFollowUp(ctx context.Context, tx pgx.Tx, push activities.NoticePush, f sweptFollowUp, remaining int, now time.Time,
	label, note, route, about string, extra map[string]any) error {
	line, err := json.Marshal([]map[string]any{{"at": cexISO(now), "by": "system", "name": "System", "action": "resolved", "note": note}})
	if err != nil {
		return err
	}
	// The follow-up closed with its history line, and the Lead's notices on
	// it resolved (_resolve_lead_notifications), by the owned function.
	if _, err := tx.Exec(ctx, `SELECT gateway_scheduler.close_followup($1, $2, $3, $4, $5::jsonb, $6)`, f.id, remaining, now,
		rules.CountryExecution.FollowUps.ResolvedAutomatically, string(line), cexFollowUpContext); err != nil {
		return fmt.Errorf("planningmonitor: closing the follow-up: %w", err)
	}
	if f.assignedBy != "" {
		_, _, err := activities.NotifyFromPerson(ctx, tx, push, now, activities.PersonNotice{Recipient: f.assignedBy,
			ContextType: cexFollowUpContext, ContextID: f.id, Event: "planning_followup_resolved",
			Fields: map[string]any{"title": "Follow-up resolved: " + label,
				"body":     "The " + strings.ToLower(label) + " for " + about + " has cleared, so the follow-up closed itself.",
				"category": "planning", "target_route": route, "priority": "normal", "status": "unread", "source_event_id": f.id,
				"read_at": nil}})
		if err != nil && !errors.Is(err, activities.ErrPhoneCopy) {
			return err
		}
	}
	optional := func(s string) any {
		if s == "" {
			return nil
		}
		return s
	}
	payload := map[string]any{"condition_key": f.key, "issue_type": f.issue, "program_lead": f.lead, "cceo": optional(f.cceo),
		"school": optional(f.school), "status": rules.CountryExecution.FollowUps.ResolvedAutomatically}
	for k, v := range extra {
		payload[k] = v
	}
	system := "system"
	if _, err := audit.Append(ctx, tx, audit.Entry{Action: "planning_followup.auto_resolved", SubjectKind: audit.Text(cexFollowUpContext),
		SubjectID: audit.Text(f.id), ActorID: audit.Text(system), ActorRole: &system, Success: true, Payload: payload}, now); err != nil {
		return fmt.Errorf("planningmonitor: auditing the follow-up's close: %w", err)
	}
	return nil
}

// firstOf is Python's `a or b or c`.
func firstOf(values ...string) string {
	for _, v := range values {
		if v != "" {
			return v
		}
	}
	return ""
}
