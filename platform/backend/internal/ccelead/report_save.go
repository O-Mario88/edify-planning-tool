package ccelead

// The Regional Lead's monthly CCE report (apps.cce_leadership.services):
// started for a month, written and submitted with the month's figures
// frozen, and acknowledged or returned by the RVP. Each check is the
// existing one, in its order and words.

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"math"
	"slices"
	"sort"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/cuid"
)

const (
	reportContext        = "RegionalCceReport"
	eventReportSubmitted = "cce_report_submitted"
	eventReportReviewed  = "cce_report_reviewed"
	reportDraft          = "draft"
	reportSubmitted      = "submitted"
	reportAcknowledged   = "acknowledged"
	reportReturned       = "returned"
	// settingsZone is settings.TIME_ZONE, the day a moment falls on.
	settingsZone = "Africa/Nairobi"
)

// Report is one RegionalCceReport.
type Report struct {
	ID, Author, FY, Status, ReviewNote string
	Period                             time.Time
	Countries                          []string
	Sections                           map[string]string
	Metrics                            map[string]any
	Submitted                          *time.Time
}

// ReportSections are REPORT_SECTIONS: field, label, hint.
func ReportSections() [][3]string {
	out := make([][3]string, 0, len(rules.Saves.ReportSections))
	for _, s := range rules.Saves.ReportSections {
		out = append(out, s)
	}
	return out
}

// ReportStatusLabel is get_status_display.
func ReportStatusLabel(status string) string {
	if l, ok := rules.ReportStatuses[status]; ok {
		return l
	}
	return status
}

func reportSelect() string {
	cols := []string{"r.id", "r.author_id", "r.fy", "r.status", "r.review_note", "r.period", "r.countries", "r.metrics", "r.submitted_at"}
	for _, s := range rules.Saves.ReportSections {
		cols = append(cols, "r."+s[0])
	}
	return "SELECT " + strings.Join(cols, ", ") + " FROM cce_regional_report r"
}

func scanReport(row pgx.Row) (Report, error) {
	var r Report
	var metrics []byte
	sections := make([]string, len(rules.Saves.ReportSections))
	dest := []any{&r.ID, &r.Author, &r.FY, &r.Status, &r.ReviewNote, &r.Period, &r.Countries, &metrics, &r.Submitted}
	for i := range sections {
		dest = append(dest, &sections[i])
	}
	if err := row.Scan(dest...); err != nil {
		return r, err
	}
	r.Sections = map[string]string{}
	for i, s := range rules.Saves.ReportSections {
		r.Sections[s[0]] = sections[i]
	}
	if len(metrics) > 0 {
		if err := json.Unmarshal(metrics, &r.Metrics); err != nil {
			return r, fmt.Errorf("ccelead: reading the report's figures: %w", err)
		}
	}
	return r, nil
}

// oneReport is reports_visible_to(...).filter(id=).first().
func (c Coaching) oneReport(ctx context.Context, q pgx.Tx, p auth.Principal, id string, lock bool) (*Report, error) {
	where, args, err := visible(ctx, c.DB, p, c.now())
	if err != nil {
		return nil, err
	}
	sql := reportSelect() + " WHERE " + where + fmt.Sprintf(" AND r.id = $%d", len(args)+1)
	if lock {
		sql += " FOR UPDATE"
	}
	var row pgx.Row
	if q != nil {
		row = q.QueryRow(ctx, sql, append(args, id)...)
	} else {
		row = c.DB.QueryRow(ctx, sql, append(args, id)...)
	}
	r, err := scanReport(row)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, nil
	}
	if err != nil {
		return nil, fmt.Errorf("ccelead: reading the report: %w", err)
	}
	return &r, nil
}

// ReportVisible is the report drawer's reading.
func (c Coaching) ReportVisible(ctx context.Context, p auth.Principal, id string) (*Report, error) {
	return c.oneReport(ctx, nil, p, id, false)
}

func monthStart(d time.Time) time.Time {
	return time.Date(d.Year(), d.Month(), 1, 0, 0, 0, 0, time.UTC)
}

func nextMonth(d time.Time) time.Time { return monthStart(d).AddDate(0, 1, 0) }

// MonthOptions is _month_options: this month and the five before it.
func (c Coaching) MonthOptions() []Choice {
	cursor := monthStart(c.today())
	out := make([]Choice, 0, 6)
	for range 6 {
		out = append(out, Choice{cursor.Format("2006-01"), cursor.Format("January 2006")})
		cursor = monthStart(cursor.AddDate(0, 0, -1))
	}
	return out
}

// DefaultReportMonth is report_new_drawer's default: last month while its
// owed report is not started, else this month.
func (c Coaching) DefaultReportMonth(ctx context.Context, p auth.Principal) (string, error) {
	current := monthStart(c.today())
	previous := monthStart(current.AddDate(0, 0, -1))
	var exists bool
	if err := c.DB.QueryRow(ctx, `SELECT EXISTS (SELECT 1 FROM cce_regional_report WHERE author_id = $1 AND period = $2)`,
		p.UserID, previous).Scan(&exists); err != nil {
		return "", fmt.Errorf("ccelead: reading last month's report: %w", err)
	}
	if !exists && !previous.Before(reportingStarts) {
		return previous.Format("2006-01"), nil
	}
	return current.Format("2006-01"), nil
}

// StartReport is start_report; the period it opened.
func (c Coaching) StartReport(ctx context.Context, p auth.Principal, raw string) (time.Time, error) {
	if !IsRegionalLead(p) {
		return time.Time{}, forbidden(leadRecordsOnly)
	}
	if len(raw) == 7 {
		raw += "-01"
	}
	day, err := parseDay(raw, "the month")
	if err != nil {
		return time.Time{}, err
	}
	if day == nil {
		return time.Time{}, badRequest("Choose the month the report covers.")
	}
	period := monthStart(*day)
	if period.After(monthStart(c.today())) {
		return time.Time{}, badRequest("A monthly report covers the current month or an earlier one.")
	}
	reach, err := c.LeadReach(ctx, p)
	if err != nil {
		return time.Time{}, err
	}
	countries := reach.Countries
	if countries == nil {
		countries = []string{}
	}
	now := c.now().UTC().Truncate(time.Microsecond)
	err = c.write(ctx, func(tx pgx.Tx) error {
		var id string
		err := tx.QueryRow(ctx, `INSERT INTO cce_regional_report (id, created_at, updated_at, author_id, period, fy, countries, status,
  executive_summary, training_programmes, cce_impact, curriculum_development, programme_initiatives, partnerships, support_needed,
  metrics, submitted_at, reviewed_by_id, reviewed_at, review_note)
VALUES ($1, $2, $2, $3, $4, $5, $6, 'draft', '', '', '', '', '', '', '', '{}'::jsonb, NULL, NULL, NULL, '')
ON CONFLICT (author_id, period) DO NOTHING RETURNING id`, cuid.New(), now, p.UserID, period, operationalFY(period), countries).Scan(&id)
		if errors.Is(err, pgx.ErrNoRows) {
			return nil // get_or_create found it
		}
		if err != nil {
			return fmt.Errorf("ccelead: starting the report: %w", err)
		}
		return coachingAuditAs(ctx, tx, "cce.report_started", reportContext, id, p, map[string]any{"period": period.Format(time.DateOnly)}, now)
	})
	return period, err
}

// UpdateReport is update_report; the report as saved.
func (c Coaching) UpdateReport(ctx context.Context, p auth.Principal, id string, data map[string]string, submit bool) (*Report, error) {
	if !IsRegionalLead(p) {
		return nil, forbidden(leadRecordsOnly)
	}
	now := c.now().UTC().Truncate(time.Microsecond)
	var saved *Report
	err := c.write(ctx, func(tx pgx.Tx) error {
		r, err := c.oneReport(ctx, tx, p, id, true)
		if err != nil {
			return err
		}
		if r == nil {
			return missing("Report not found.")
		}
		if r.Status != reportDraft && r.Status != reportReturned {
			return forbidden("This report is with the RVP. It can be edited again if they return it.")
		}
		for _, s := range rules.Saves.ReportSections {
			if v, ok := data[s[0]]; ok {
				r.Sections[s[0]] = strings.TrimSpace(v)
			}
		}
		sets := []string{"updated_at = $2"}
		args := []any{id, now}
		add := func(col string, v any) {
			args = append(args, v)
			sets = append(sets, fmt.Sprintf("%s = $%d", col, len(args)))
		}
		for _, s := range rules.Saves.ReportSections {
			add(s[0], r.Sections[s[0]])
		}
		if submit {
			if r.Sections["executive_summary"] == "" {
				return badRequest("Write the executive summary before submitting the report.")
			}
			metrics, err := c.ReportMetrics(ctx, p, r.Period)
			if err != nil {
				return err
			}
			raw, err := json.Marshal(metrics)
			if err != nil {
				return fmt.Errorf("ccelead: writing the report's figures: %w", err)
			}
			add("metrics", string(raw))
			sets[len(sets)-1] += "::jsonb"
			r.Status, r.Metrics, r.Submitted = reportSubmitted, metrics, &now
			add("status", reportSubmitted)
			add("submitted_at", now)
			sets = append(sets, "reviewed_at = NULL", "reviewed_by_id = NULL")
		}
		if len(r.Countries) == 0 {
			reach, err := c.LeadReach(ctx, p)
			if err != nil {
				return err
			}
			r.Countries = reach.Countries
			if r.Countries == nil {
				r.Countries = []string{}
			}
			add("countries", r.Countries)
		}
		if _, err := tx.Exec(ctx, `UPDATE cce_regional_report SET `+strings.Join(sets, ", ")+` WHERE id = $1`, args...); err != nil {
			return fmt.Errorf("ccelead: saving the report: %w", err)
		}
		action := "cce.report_saved"
		if submit {
			action = "cce.report_submitted"
		}
		saved = r
		return coachingAuditAs(ctx, tx, action, reportContext, id, p, map[string]any{
			"period": r.Period.Format(time.DateOnly), "status": r.Status}, now)
	})
	if err != nil {
		return nil, err
	}
	if submit {
		author := p.Name
		if author == "" {
			author = "A Regional Lead"
		}
		rvps, err := c.rvpsFor(ctx, saved.Countries)
		if err != nil && c.Logger != nil {
			c.Logger.WarnContext(ctx, "ccelead: the RVPs were not read", "report", id, "err", err)
		}
		c.leadershipNotice(ctx, id, eventReportSubmitted, fmt.Sprintf("%s CCE report from %s", saved.Period.Format("January 2006"), author),
			saved.Sections["executive_summary"], "high", ReportsURL, "Review Report", now, rvps...)
	}
	return saved, nil
}

// rvpsFor is _rvps_for: the RVPs whose regions reach the countries, else
// those with no region, else every RVP.
func (c Coaching) rvpsFor(ctx context.Context, countries []string) ([]string, error) {
	rows, err := c.DB.Query(ctx, `SELECT u.id, COALESCE(array_agg(g.country) FILTER (WHERE g.id IS NOT NULL), '{}'),
  bool_or(a.id IS NOT NULL)
FROM "user" u
LEFT JOIN staff_profile sp ON sp.user_id = u.id
LEFT JOIN staff_geography_assignment a ON a.staff_id = sp.id AND a.region_id IS NOT NULL
LEFT JOIN region g ON g.id = a.region_id
WHERE u.deleted_at IS NULL AND u.status = 'active' AND u.roles @> ARRAY['RegionalVicePresident']::varchar[]
GROUP BY u.id ORDER BY u.id`)
	if err != nil {
		return nil, fmt.Errorf("ccelead: reading the RVPs: %w", err)
	}
	defer rows.Close()
	var all, matching, unassigned []string
	for rows.Next() {
		var id string
		var theirs []string
		var assigned *bool
		if err := rows.Scan(&id, &theirs, &assigned); err != nil {
			return nil, err
		}
		all = append(all, id)
		if assigned == nil || !*assigned {
			unassigned = append(unassigned, id)
			continue
		}
		for _, country := range theirs {
			if slices.Contains(countries, country) {
				matching = append(matching, id)
				break
			}
		}
	}
	if err := rows.Err(); err != nil {
		return nil, err
	}
	switch {
	case len(matching) > 0:
		return matching, nil
	case len(unassigned) > 0:
		return unassigned, nil
	}
	return all, nil
}

// ReviewReport is review_report; the report's new status.
func (c Coaching) ReviewReport(ctx context.Context, p auth.Principal, id, decision, note string) (*Report, error) {
	if p.ActiveRole != rvpRole && p.ActiveRole != adminRole {
		return nil, forbidden("The RVP reviews the Regional Lead's monthly report.")
	}
	note = strings.TrimSpace(note)
	if decision != "acknowledge" && decision != "return" {
		return nil, badRequest("Choose whether to acknowledge the report or return it.")
	}
	if decision == "return" && note == "" {
		return nil, badRequest("Say what the report needs before returning it.")
	}
	now := c.now().UTC().Truncate(time.Microsecond)
	var r *Report
	err := c.write(ctx, func(tx pgx.Tx) error {
		var err error
		if r, err = c.oneReport(ctx, tx, p, id, true); err != nil {
			return err
		}
		if r == nil {
			return missing("Report not found.")
		}
		if r.Status != reportSubmitted {
			return badRequest("Only a submitted report waits for a review.")
		}
		r.Status, r.ReviewNote = reportAcknowledged, note
		if decision == "return" {
			r.Status = reportReturned
		}
		if _, err := tx.Exec(ctx, `UPDATE cce_regional_report SET status = $2, reviewed_by_id = $3, reviewed_at = $4, review_note = $5,
  updated_at = $4 WHERE id = $1`, id, r.Status, p.UserID, now, note); err != nil {
			return fmt.Errorf("ccelead: reviewing the report: %w", err)
		}
		return coachingAuditAs(ctx, tx, "cce.report_"+r.Status, reportContext, id, p, map[string]any{"note": note}, now)
	})
	if err != nil {
		return nil, err
	}
	month := r.Period.Format("January 2006")
	title, priority, body := "Your "+month+" CCE report was acknowledged", "normal", note
	if r.Status == reportReturned {
		title, priority = "Your "+month+" CCE report was returned", "high"
	}
	if body == "" {
		body = "The RVP acknowledged your monthly report."
	}
	c.leadershipNotice(ctx, id, eventReportReviewed, title, body, priority, ReportsURL, "Open Monthly Report", now, r.Author)
	return r, nil
}

// pyRoundInt is Python's round(x) of a float.
func pyRoundInt(x float64) int { return int(math.RoundToEven(x)) }

// ReportMetrics is report_metrics: the region's figures for one month.
func (c Coaching) ReportMetrics(ctx context.Context, p auth.Principal, period time.Time) (map[string]any, error) {
	reach, err := c.LeadReach(ctx, p)
	if err != nil {
		return nil, err
	}
	countries := reach.Countries
	if countries == nil {
		countries = []string{}
	}
	start, end := monthStart(period), nextMonth(period)
	delivered := `FROM activity a ` + activityPlaces + ` WHERE ` + inCountries + ` AND a.deleted_at IS NULL
  AND a.status = ANY($2) AND a.planned_date >= $3 AND a.planned_date < $4`
	args := []any{countries, rules.Saves.CompletedStatuses, start, end}
	var trainings, teachers, leaders int
	if err := c.DB.QueryRow(ctx, `SELECT COUNT(a.id), COALESCE(SUM(a.teachers_attended), 0), COALESCE(SUM(a.leaders_attended), 0) `+
		delivered+` AND a.activity_type = ANY($5)`, append(args, rules.Saves.TrainingTypes)...).Scan(&trainings, &teachers, &leaders); err != nil {
		return nil, fmt.Errorf("ccelead: counting the month's trainings: %w", err)
	}
	byCountry := map[string]int{}
	rows, err := c.DB.Query(ctx, `SELECT COALESCE(NULLIF(sr.country, ''), NULLIF(dr.country, ''), 'Unplaced') `+delivered+
		` AND a.activity_type = ANY($5)`, append(args, rules.Saves.TrainingTypes)...)
	if err != nil {
		return nil, fmt.Errorf("ccelead: placing the month's trainings: %w", err)
	}
	for rows.Next() {
		var country string
		if err := rows.Scan(&country); err != nil {
			rows.Close()
			return nil, err
		}
		byCountry[country]++
	}
	rows.Close()
	var followUps int
	if err := c.DB.QueryRow(ctx, `SELECT COUNT(a.id) `+delivered+` AND a.activity_type = ANY($5)`,
		append(args, rules.Saves.CoachingFollowUps)...).Scan(&followUps); err != nil {
		return nil, fmt.Errorf("ccelead: counting the month's follow-up visits: %w", err)
	}
	var verdicts, informed int
	if err := c.DB.QueryRow(ctx, `SELECT COUNT(a.id), COUNT(a.id) FILTER (WHERE a.ssa_alignment = ANY($4))
FROM activity a `+activityPlaces+` WHERE `+inCountries+` AND a.deleted_at IS NULL AND a.fy = $2 AND a.status = ANY($3)
  AND (a.ssa_alignment IS NULL OR a.ssa_alignment <> '')`, countries, operationalFY(start), rules.Saves.LivePlanStatuses,
		rules.Saves.InformedVerdicts).Scan(&verdicts, &informed); err != nil {
		return nil, fmt.Errorf("ccelead: reading the month's plan verdicts: %w", err)
	}
	var ssa int
	if err := c.DB.QueryRow(ctx, `SELECT COUNT(r.id) FROM ssa_record r JOIN school s ON s.id = r.school_id
JOIN region g ON g.id = s.region_id
WHERE r.deleted_at IS NULL AND r.verification_status = 'confirmed' AND g.country = ANY($1)
  AND (r.date_of_ssa AT TIME ZONE $4)::date >= $2 AND (r.date_of_ssa AT TIME ZONE $4)::date < $3`,
		countries, start, end, settingsZone).Scan(&ssa); err != nil {
		return nil, fmt.Errorf("ccelead: counting the month's SSA assessments: %w", err)
	}
	where := "e.author_id = $1 AND e.held_on >= $2 AND e.held_on < $3"
	own, err := c.engagementsWhere(ctx, where, []any{p.UserID, start, end})
	if err != nil {
		return nil, err
	}
	var coachingConversations, observed, reviews int
	var ratings []float64
	for _, e := range own {
		switch e.Kind {
		case kindPLCoaching:
			coachingConversations++
		case kindCDQuarterly:
			reviews++
		}
		if e.IsObservation() {
			observed++
			if avg := e.AverageRating(); avg != "" {
				var f float64
				_, _ = fmt.Sscan(avg, &f)
				ratings = append(ratings, f)
			}
		}
	}
	keys := make([]string, 0, len(byCountry))
	for k := range byCountry {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	sortedByCountry := map[string]any{}
	for _, k := range keys {
		sortedByCountry[k] = byCountry[k]
	}
	out := map[string]any{
		"period": start.Format(time.DateOnly), "countries": countries, "trainings_delivered": trainings,
		"teachers_trained": teachers, "leaders_trained": leaders, "trainings_by_country": sortedByCountry,
		"coaching_follow_up_visits": followUps, "ssa_confirmed": ssa, "ssa_informed_plans_pct": nil,
		"coaching_conversations": coachingConversations, "trainings_observed": observed, "average_observation_rating": nil,
		"country_reviews": reviews,
	}
	if verdicts > 0 {
		out["ssa_informed_plans_pct"] = pyRoundInt(float64(informed) * 100 / float64(verdicts))
	}
	if len(ratings) > 0 {
		var sum float64
		for _, r := range ratings {
			sum += r
		}
		out["average_observation_rating"] = pyRound1(sum / float64(len(ratings)))
	}
	return out, nil
}

// engagementsWhere reads every engagement a clause selects.
func (c Coaching) engagementsWhere(ctx context.Context, where string, args []any) ([]Engagement, error) {
	rows, err := c.DB.Query(ctx, engagementSelect()+" WHERE "+where, args...)
	if err != nil {
		return nil, fmt.Errorf("ccelead: reading the engagements: %w", err)
	}
	defer rows.Close()
	var out []Engagement
	for rows.Next() {
		e, err := scanEngagement(rows)
		if err != nil {
			return nil, err
		}
		out = append(out, e)
	}
	return out, rows.Err()
}
