package debriefs

// The field_debrief_recurring_issues job (apps.debriefs.insight_service.
// RecurringIssueDetectionService.scan): a challenge reported in three or more
// debriefs in 30 days about one school, one officer or one Partner becomes
// one open recurring-issue insight (its counts refreshed while it stays
// open), and the officer's Program Lead is told of a new one; the same
// challenge across three or more Program Lead teams is escalated to the
// Country Director, and across three or more countries to the Regional Vice
// President. Inside the caller's transaction.

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"slices"
	"time"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/activities"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/cuid"
)

const (
	recurringWindowDays   = 30 // WINDOW_DAYS
	recurringMinimum      = 3  // MIN_OCCURRENCES
	teamEscalationAt      = 3  // TEAM_ESCALATION_THRESHOLD
	countryEscalationAt   = 3  // COUNTRY_ESCALATION_THRESHOLD
	recurringEvent        = "field_debrief_recurring_issue"
	recurringEscalated    = "field_debrief_recurring_issue_escalated"
	recurringCategory     = "field_debrief"
	recurringInsightKind  = "field_debrief_insight"
	escalationTeam        = "team"
	escalationCountry     = "country"
	escalationRegion      = "region"
	recurringInsightsPath = "/debriefs"
)

// RecurringResult is what the scan reports: insights created and refreshed.
type RecurringResult struct{ Created, Updated int }

// recurringChallenge is one challenge row with its debrief.
type recurringChallenge struct {
	challengeType, debriefID string
	staffID, partnerID       *string
	schools                  []string
}

// group is one scope's debriefs for one challenge, in the order read.
type group struct {
	scope, scopeID, challenge string
	debriefs                  []recurringChallenge
}

// ScanRecurringIssues is RecurringIssueDetectionService.scan for today in
// Kampala.
func ScanRecurringIssues(ctx context.Context, tx pgx.Tx, now time.Time, kampala *time.Location,
	push activities.NoticePush, logger *slog.Logger) (RecurringResult, error) {
	var out RecurringResult
	local := now.In(kampala)
	today := time.Date(local.Year(), local.Month(), local.Day(), 0, 0, 0, 0, time.UTC)
	start := today.AddDate(0, 0, -recurringWindowDays)
	rows, err := readChallenges(ctx, tx, start, today, false)
	if err != nil {
		return out, err
	}
	var groups []*group
	index := map[[3]string]*group{}
	add := func(scope, id string, c recurringChallenge) {
		key := [3]string{scope, id, c.challengeType}
		g, ok := index[key]
		if !ok {
			g = &group{scope: scope, scopeID: id, challenge: c.challengeType}
			index[key] = g
			groups = append(groups, g)
		}
		g.debriefs = append(g.debriefs, c)
	}
	// Schools first, then officers, then Partners, as the scan walks them.
	for _, scope := range []string{"school", "staff", "partner"} {
		for _, c := range rows {
			switch scope {
			case "school":
				for _, school := range c.schools {
					add(scope, school, c)
				}
			case "staff":
				if c.staffID != nil && *c.staffID != "" {
					add(scope, *c.staffID, c)
				}
			case "partner":
				if c.partnerID != nil && *c.partnerID != "" {
					add(scope, *c.partnerID, c)
				}
			}
		}
	}
	notices := recurringNotices{push: push, logger: logger, now: now}
	for _, g := range groups {
		if len(g.debriefs) < recurringMinimum {
			continue
		}
		created, err := upsertInsight(ctx, tx, g, start, today, now)
		if err != nil {
			return out, err
		}
		if !created {
			out.Updated++
			continue
		}
		out.Created++
		if err := notices.tellProgramLead(ctx, tx, g.debriefs[0]); err != nil {
			return out, err
		}
	}
	return out, escalate(ctx, tx, start, today, now, notices)
}

// readChallenges are the window's challenges on debriefs that are not
// removed or restricted, each debrief's day read in Kampala; withStaff keeps
// only those with an officer.
func readChallenges(ctx context.Context, tx pgx.Tx, start, end time.Time, withStaff bool) ([]recurringChallenge, error) {
	rows, err := tx.Query(ctx, `SELECT c.challenge_type, d.id, d.staff_id, d.partner_id, COALESCE(d.linked_school_ids, '{}')
FROM daily_debrief_challenge c JOIN daily_debrief d ON d.id = c.debrief_id
WHERE (d.date AT TIME ZONE 'Africa/Kampala')::date BETWEEN $1 AND $2
  AND d.deleted_at IS NULL AND NOT d.is_restricted_incident AND ($3 = false OR d.staff_id IS NOT NULL)
ORDER BY c.created_at, c.id`, start.Format(time.DateOnly), end.Format(time.DateOnly), withStaff)
	if err != nil {
		return nil, fmt.Errorf("debriefs: reading the window's challenges: %w", err)
	}
	defer rows.Close()
	var out []recurringChallenge
	for rows.Next() {
		var c recurringChallenge
		if err := rows.Scan(&c.challengeType, &c.debriefID, &c.staffID, &c.partnerID, &c.schools); err != nil {
			return nil, err
		}
		out = append(out, c)
	}
	return out, rows.Err()
}

func challengeLabel(key string) string { return label(rules.ChallengeTypes, key) }

// upsertInsight is _upsert: the scope's open insight refreshed, or a new
// one opened at team level. It says whether one was opened.
func upsertInsight(ctx context.Context, tx pgx.Tx, g *group, start, end, now time.Time) (bool, error) {
	ids := make([]string, 0, len(g.debriefs))
	for _, d := range g.debriefs {
		ids = append(ids, d.debriefID)
	}
	name := challengeLabel(g.challenge)
	description := fmt.Sprintf(`"%s" reported in %d debriefs over the last %d days.`, name, len(ids), recurringWindowDays)
	var existing string
	err := tx.QueryRow(ctx, `SELECT id FROM daily_debrief_insight WHERE scope = $1 AND scope_id = $2 AND challenge_type = $3
  AND status = 'open' ORDER BY id LIMIT 1`, g.scope, g.scopeID, g.challenge).Scan(&existing)
	if err == nil {
		_, err = tx.Exec(ctx, `UPDATE daily_debrief_insight SET occurrence_count = $2, debrief_ids = $3, window_start = $4,
  window_end = $5, description = $6 WHERE id = $1`, existing, len(ids), ids, start.Format(time.DateOnly),
			end.Format(time.DateOnly), description)
		if err != nil {
			return false, fmt.Errorf("debriefs: refreshing a recurring issue: %w", err)
		}
		return false, nil
	}
	if !errors.Is(err, pgx.ErrNoRows) {
		return false, fmt.Errorf("debriefs: reading the open recurring issue: %w", err)
	}
	title := fmt.Sprintf("Recurring issue: %s (%s)", name, g.scope)
	if _, err := tx.Exec(ctx, `INSERT INTO daily_debrief_insight (id, created_at, updated_at, scope, scope_id, challenge_type,
  title, description, occurrence_count, window_start, window_end, debrief_ids, escalation_level, status, notified_user_ids)
VALUES ($1, $2, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, 'open', '{}')`, cuid.New(), now, g.scope, g.scopeID,
		g.challenge, title, description, len(ids), start.Format(time.DateOnly), end.Format(time.DateOnly), ids,
		escalationTeam); err != nil {
		return false, fmt.Errorf("debriefs: opening a recurring issue: %w", err)
	}
	return true, nil
}

// escalate is _scan_team_and_country_escalations.
func escalate(ctx context.Context, tx pgx.Tx, start, end, now time.Time, n recurringNotices) error {
	rows, err := readChallenges(ctx, tx, start, end, true)
	if err != nil {
		return err
	}
	supervisor, err := pairs(ctx, tx, `SELECT supervisee_id, supervisor_id FROM staff_supervisor_assignment`)
	if err != nil {
		return err
	}
	country, err := pairs(ctx, tx, `SELECT id, country FROM staff_profile WHERE deleted_at IS NULL`)
	if err != nil {
		return err
	}
	teams, countries := map[string]map[string]bool{}, map[string]map[string]bool{}
	var teamOrder, countryOrder []string
	note := func(into map[string]map[string]bool, order *[]string, challenge, value string) {
		if value == "" {
			return
		}
		if into[challenge] == nil {
			into[challenge] = map[string]bool{}
			*order = append(*order, challenge)
		}
		into[challenge][value] = true
	}
	for _, c := range rows {
		note(teams, &teamOrder, c.challengeType, supervisor[*c.staffID])
		note(countries, &countryOrder, c.challengeType, country[*c.staffID])
	}
	for _, challenge := range teamOrder {
		if len(teams[challenge]) < teamEscalationAt {
			continue
		}
		if err := escalateOne(ctx, tx, challenge, escalationCountry, len(teams[challenge]), start, end, now, n); err != nil {
			return err
		}
	}
	for _, challenge := range countryOrder {
		if len(countries[challenge]) < countryEscalationAt {
			continue
		}
		if err := escalateOne(ctx, tx, challenge, escalationRegion, len(countries[challenge]), start, end, now, n); err != nil {
			return err
		}
	}
	return nil
}

func pairs(ctx context.Context, tx pgx.Tx, sql string) (map[string]string, error) {
	rows, err := tx.Query(ctx, sql)
	if err != nil {
		return nil, fmt.Errorf("debriefs: reading the teams and countries: %w", err)
	}
	defer rows.Close()
	out := map[string]string{}
	for rows.Next() {
		var k string
		var v *string
		if err := rows.Scan(&k, &v); err != nil {
			return nil, err
		}
		if v != nil {
			out[k] = *v
		} else {
			out[k] = ""
		}
	}
	return out, rows.Err()
}

// escalateOne is one cross-team (country) or cross-country (region) insight
// and its notice to the role that answers it.
func escalateOne(ctx context.Context, tx pgx.Tx, challenge, level string, count int, start, end, now time.Time,
	n recurringNotices) error {
	name := challengeLabel(challenge)
	title, description, role := fmt.Sprintf("Cross-team recurring issue: %s", name),
		fmt.Sprintf(`"%s" reported across %d Program Lead teams.`, name, count), "CountryDirector"
	if level == escalationRegion {
		title, description, role = fmt.Sprintf("Regional recurring issue: %s", name),
			fmt.Sprintf(`"%s" reported across %d countries.`, name, count), "RegionalVicePresident"
	}
	var id, currentLevel, currentTitle, currentDescription string
	err := tx.QueryRow(ctx, `SELECT id, escalation_level, title, description FROM daily_debrief_insight
WHERE scope = $1 AND challenge_type = $2 AND status = 'open' ORDER BY id LIMIT 1`, level, challenge).
		Scan(&id, &currentLevel, &currentTitle, &currentDescription)
	switch {
	case errors.Is(err, pgx.ErrNoRows):
		id = cuid.New()
		if _, err := tx.Exec(ctx, `INSERT INTO daily_debrief_insight (id, created_at, updated_at, scope, scope_id,
  challenge_type, title, description, occurrence_count, window_start, window_end, debrief_ids, escalation_level, status,
  notified_user_ids)
VALUES ($1, $2, $2, $3, NULL, $4, $5, $6, $7, $8, $9, '{}', $3, 'open', '{}')`, id, now, level, challenge, title,
			description, count, start.Format(time.DateOnly), end.Format(time.DateOnly)); err != nil {
			return fmt.Errorf("debriefs: opening an escalated issue: %w", err)
		}
	case err != nil:
		return fmt.Errorf("debriefs: reading the escalated issue: %w", err)
	case level == escalationCountry && currentLevel == escalationCountry:
		return nil // already with the Country Director
	default:
		title, description = currentTitle, currentDescription
		sql := `UPDATE daily_debrief_insight SET occurrence_count = $2 WHERE id = $1`
		args := []any{id, count}
		if level == escalationCountry {
			sql = `UPDATE daily_debrief_insight SET occurrence_count = $2, escalation_level = $3 WHERE id = $1`
			args = append(args, escalationCountry)
		}
		if _, err := tx.Exec(ctx, sql, args...); err != nil {
			return fmt.Errorf("debriefs: refreshing an escalated issue: %w", err)
		}
	}
	return n.tellRole(ctx, tx, id, role, title, description)
}

// recurringNotices are the scan's notices.
type recurringNotices struct {
	push   activities.NoticePush
	logger *slog.Logger
	now    time.Time
}

// tellProgramLead is _notify_pl: the Program Lead over the debrief's officer.
func (n recurringNotices) tellProgramLead(ctx context.Context, tx pgx.Tx, d recurringChallenge) error {
	if d.staffID == nil || *d.staffID == "" {
		return nil
	}
	var plUser *string
	err := tx.QueryRow(ctx, `SELECT pl.user_id FROM staff_profile sp
JOIN staff_supervisor_assignment a ON a.supervisee_id = sp.id
JOIN staff_profile pl ON pl.id = a.supervisor_id
WHERE sp.id = $1 AND sp.deleted_at IS NULL ORDER BY a.id LIMIT 1`, *d.staffID).Scan(&plUser)
	if errors.Is(err, pgx.ErrNoRows) || (err == nil && (plUser == nil || *plUser == "")) {
		return nil
	}
	if err != nil {
		return fmt.Errorf("debriefs: reading the officer's Program Lead: %w", err)
	}
	_, err = activities.NotifyInTx(ctx, tx, n.push, n.logger, n.now, d.debriefID, activities.Notice{
		Title: "A recurring field issue was detected on your team", Body: "Check Recurring Field Issues for details.",
		Event: recurringEvent, Category: recurringCategory, ContextType: recurringCategory, Priority: "normal",
	}, []activities.NoticeTo{{UserID: *plUser, Route: recurringInsightsPath + "/" + d.debriefID, Label: "Open Debrief"}})
	return err
}

// tellRole is _notify_role: every active holder of the role, remembered on
// the insight, then told.
func (n recurringNotices) tellRole(ctx context.Context, tx pgx.Tx, insightID, role, title, body string) error {
	rows, err := tx.Query(ctx, `SELECT id FROM "user" WHERE $1 = ANY(roles) AND status = 'active' AND deleted_at IS NULL
ORDER BY created_at DESC`, role)
	if err != nil {
		return fmt.Errorf("debriefs: reading who holds %s: %w", role, err)
	}
	var users []string
	for rows.Next() {
		var id string
		if err := rows.Scan(&id); err != nil {
			rows.Close()
			return err
		}
		users = append(users, id)
	}
	rows.Close()
	if err := rows.Err(); err != nil || len(users) == 0 {
		return err
	}
	var notified []string
	if err := tx.QueryRow(ctx, `SELECT COALESCE(notified_user_ids, '{}') FROM daily_debrief_insight WHERE id = $1`, insightID).
		Scan(&notified); err != nil {
		return fmt.Errorf("debriefs: reading who was told: %w", err)
	}
	union := slices.Clone(notified)
	for _, u := range users {
		if !slices.Contains(union, u) {
			union = append(union, u)
		}
	}
	slices.Sort(union)
	if _, err := tx.Exec(ctx, `UPDATE daily_debrief_insight SET notified_user_ids = $2 WHERE id = $1`, insightID, union); err != nil {
		return fmt.Errorf("debriefs: remembering who was told: %w", err)
	}
	to := make([]activities.NoticeTo, 0, len(users))
	for _, u := range users {
		to = append(to, activities.NoticeTo{UserID: u, Route: recurringInsightsPath, Label: "View Recurring Field Issues"})
	}
	_, err = activities.NotifyInTx(ctx, tx, n.push, n.logger, n.now, insightID, activities.Notice{
		Title: title, Body: body, Event: recurringEscalated, Category: recurringCategory,
		ContextType: recurringInsightKind, Priority: "high",
	}, to)
	return err
}
