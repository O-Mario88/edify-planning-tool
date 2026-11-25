package debriefs

// The weekly_debrief_reports job (apps.debriefs.weekly_report_service.
// WeeklyDebriefReportService.generate_pl_report for every Programme Lead):
// the just-closed Monday-to-Sunday week of the lead's and their team's
// submitted daily debriefs consolidated into one insight cluster per theme
// (weekly_themes.json is the existing THEMES, verbatim), each with its
// mentions, unique staff, schools, districts and activities, a confidence and
// a trend against last week's finalized report; stored as the week's draft
// (regenerated in place) or, over a finalized one, as a new version.

import (
	"context"
	_ "embed"
	"encoding/json"
	"errors"
	"fmt"
	"regexp"
	"sort"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/cuid"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

//go:embed weekly_themes.json
var weeklyThemesJSON []byte

type weeklyTheme struct {
	key, label, kind string
	patterns         []*regexp.Regexp
}

var weeklyThemes = func() []weeklyTheme {
	var raw [][]any
	if err := json.Unmarshal(weeklyThemesJSON, &raw); err != nil {
		panic(err)
	}
	out := make([]weeklyTheme, 0, len(raw))
	for _, r := range raw {
		t := weeklyTheme{key: r[0].(string), label: r[1].(string), kind: r[2].(string)}
		for _, p := range r[3].([]any) {
			t.patterns = append(t.patterns, regexp.MustCompile("(?i)"+p.(string)))
		}
		out = append(out, t)
	}
	return out
}()

// classifyText is classify_text: every theme the text matches.
func classifyText(text string) []weeklyTheme {
	if text == "" {
		return nil
	}
	var out []weeklyTheme
	for _, t := range weeklyThemes {
		for _, p := range t.patterns {
			if p.MatchString(text) {
				out = append(out, t)
				break
			}
		}
	}
	return out
}

// weekDebrief is one submitted daily debrief of the week.
type weekDebrief struct {
	id, by, day                                    string
	schools, activities                            []string
	challenges, notWell, wentWell, recommendations *string
}

// WeeklyReports is the job; it says how many reports it generated.
func WeeklyReports(ctx context.Context, tx pgx.Tx, now time.Time, kampala *time.Location) (int, error) {
	local := now.In(kampala)
	anchor := time.Date(local.Year(), local.Month(), local.Day(), 0, 0, 0, 0, time.UTC).AddDate(0, 0, -7)
	start := anchor.AddDate(0, 0, -((int(anchor.Weekday()) + 6) % 7))
	end := start.AddDate(0, 0, 6)
	rows, err := tx.Query(ctx, `SELECT id, COALESCE(name, '') FROM "user" WHERE active_role = 'Program Lead' AND is_active
ORDER BY created_at DESC`)
	if err != nil {
		return 0, fmt.Errorf("debriefs: reading the Programme Leads: %w", err)
	}
	type lead struct{ id, name string }
	var leads []lead
	for rows.Next() {
		var l lead
		if err := rows.Scan(&l.id, &l.name); err != nil {
			rows.Close()
			return 0, err
		}
		leads = append(leads, l)
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return 0, err
	}
	fy := schooldirectory.OperationalFY(local)
	for _, l := range leads {
		if err := plReport(ctx, tx, l.id, l.name, start, end, fy, now); err != nil {
			return 0, err
		}
	}
	return len(leads), nil
}

// plReport is generate_pl_report for one lead.
func plReport(ctx context.Context, tx pgx.Tx, userID, name string, start, end time.Time, fy string, now time.Time) error {
	members := [][2]string{{userID, name}}
	rows, err := tx.Query(ctx, `SELECT u.id, COALESCE(u.name, '') FROM staff_profile sp JOIN "user" u ON u.id = sp.user_id
WHERE sp.deleted_at IS NULL AND sp.id IN (SELECT supervisee_id FROM staff_supervisor_assignment
  WHERE supervisor_id = (SELECT id FROM staff_profile WHERE user_id = $1 AND deleted_at IS NULL ORDER BY id LIMIT 1))`, userID)
	if err != nil {
		return fmt.Errorf("debriefs: reading the lead's team: %w", err)
	}
	for rows.Next() {
		var m [2]string
		if err := rows.Scan(&m[0], &m[1]); err != nil {
			rows.Close()
			return err
		}
		members = append(members, m)
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return err
	}
	ids := make([]string, 0, len(members))
	for _, m := range members {
		ids = append(ids, m[0])
	}
	debriefs, err := weekDebriefs(ctx, tx, ids, start, end)
	if err != nil {
		return err
	}
	clusters, err := consolidate(ctx, tx, debriefs)
	if err != nil {
		return err
	}
	if err := trend(ctx, tx, clusters, userID, start); err != nil {
		return err
	}
	submitted := map[string]bool{}
	schools, acts, days := map[string]bool{}, map[string]bool{}, map[string]bool{}
	sources := make([]string, 0, len(debriefs))
	for _, d := range debriefs {
		submitted[d.by] = true
		for _, s := range d.schools {
			schools[s] = true
		}
		for _, a := range d.activities {
			acts[a] = true
		}
		days[d.by+"|"+d.day] = true
		sources = append(sources, d.id)
	}
	team := make([]map[string]any, 0, len(members))
	for _, m := range members {
		team = append(team, map[string]any{"user_id": m[0], "name": m[1], "submitted": submitted[m[0]]})
	}
	snapshot := map[string]any{
		"week_start": start.Format(time.DateOnly),
		"week_end":   end.Format(time.DateOnly),
		"team":       team,
		"totals": map[string]any{
			"members": len(members), "reporting": len(submitted), "debriefs": len(debriefs),
			"activities_worked": len(acts), "schools_supported": len(schools), "person_days": len(days),
		},
		"clusters":           clusters,
		"source_debrief_ids": sources,
	}
	return storeReport(ctx, tx, "pl_team", userID, start, end, snapshot, userID, fy, now)
}

// weekDebriefs is _week_debriefs: submitted daily debriefs of the week (by
// their Kampala day), never a restricted incident, in date order; each
// debrief's day as the existing code prints it (the UTC date).
func weekDebriefs(ctx context.Context, tx pgx.Tx, users []string, start, end time.Time) ([]weekDebrief, error) {
	rows, err := tx.Query(ctx, `SELECT id, submitted_by_user_id, (date AT TIME ZONE 'UTC')::date::text,
  COALESCE(linked_school_ids, '{}'), COALESCE(linked_activity_ids, '{}'),
  challenges_faced, what_did_not_go_well, what_went_well, recommendations
FROM daily_debrief
WHERE submitted_by_user_id = ANY($1) AND kind = 'daily' AND (date AT TIME ZONE 'Africa/Kampala')::date BETWEEN $2 AND $3
  AND deleted_at IS NULL AND NOT is_restricted_incident AND status <> 'draft'
ORDER BY date`, users, start.Format(time.DateOnly), end.Format(time.DateOnly))
	if err != nil {
		return nil, fmt.Errorf("debriefs: reading the week's debriefs: %w", err)
	}
	defer rows.Close()
	var out []weekDebrief
	for rows.Next() {
		var d weekDebrief
		if err := rows.Scan(&d.id, &d.by, &d.day, &d.schools, &d.activities, &d.challenges, &d.notWell, &d.wentWell,
			&d.recommendations); err != nil {
			return nil, err
		}
		out = append(out, d)
	}
	return out, rows.Err()
}

type cluster struct {
	theme, label, kind        string
	mentions, lowHits         int
	staff, schools, districts map[string]bool
	activities, dates         map[string]bool
	sources                   []map[string]any
}

// consolidate is _consolidate.
func consolidate(ctx context.Context, tx pgx.Tx, debriefs []weekDebrief) ([]map[string]any, error) {
	var schoolIDs []string
	for _, d := range debriefs {
		schoolIDs = append(schoolIDs, d.schools...)
	}
	districts := map[string]string{}
	if len(schoolIDs) > 0 {
		rows, err := tx.Query(ctx, `SELECT s.id, d.name FROM school s LEFT JOIN district d ON d.id = s.district_id
WHERE s.id = ANY($1) AND s.deleted_at IS NULL`, schoolIDs)
		if err != nil {
			return nil, fmt.Errorf("debriefs: reading the schools' districts: %w", err)
		}
		for rows.Next() {
			var id string
			var name *string
			if err := rows.Scan(&id, &name); err != nil {
				rows.Close()
				return nil, err
			}
			if name != nil && *name != "" {
				districts[id] = *name
			}
		}
		rows.Close()
		if err := rows.Err(); err != nil {
			return nil, err
		}
	}
	byTheme := map[string]*cluster{}
	var order []*cluster
	fields := []struct {
		text func(weekDebrief) *string
		kind string
	}{
		{func(d weekDebrief) *string { return d.challenges }, "challenge"},
		{func(d weekDebrief) *string { return d.notWell }, "challenge"},
		{func(d weekDebrief) *string { return d.wentWell }, "positive"},
		{func(d weekDebrief) *string { return d.recommendations }, "suggestion"},
	}
	for _, d := range debriefs {
		for _, f := range fields {
			text := f.text(d)
			if text == nil || *text == "" {
				continue
			}
			for _, t := range classifyText(*text) {
				mismatched := (f.kind == "positive") != (t.kind == "positive")
				c, ok := byTheme[t.key]
				if !ok {
					c = &cluster{theme: t.key, label: t.label, kind: t.kind, staff: map[string]bool{}, schools: map[string]bool{},
						districts: map[string]bool{}, activities: map[string]bool{}, dates: map[string]bool{}}
					byTheme[t.key] = c
					order = append(order, c)
				}
				c.mentions++
				c.staff[d.by] = true
				for _, s := range d.schools {
					c.schools[s] = true
					if name, ok := districts[s]; ok {
						c.districts[name] = true
					}
				}
				for _, a := range d.activities {
					c.activities[a] = true
				}
				c.dates[d.day] = true
				if mismatched {
					c.lowHits++
				}
				if len(c.sources) < 5 {
					c.sources = append(c.sources, map[string]any{"debrief_id": d.id, "excerpt": firstRunes(strings.TrimSpace(*text), 180)})
				}
			}
		}
	}
	kindRank := map[string]int{"challenge": 0, "suggestion": 1, "positive": 2}
	sort.SliceStable(order, func(i, j int) bool {
		a, b := order[i], order[j]
		if kindRank[a.kind] != kindRank[b.kind] {
			return kindRank[a.kind] < kindRank[b.kind]
		}
		if len(a.staff) != len(b.staff) {
			return len(a.staff) > len(b.staff)
		}
		return a.mentions > b.mentions
	})
	out := make([]map[string]any, 0, len(order))
	for _, c := range order {
		unique := len(c.staff)
		confidence := "medium"
		switch {
		case c.lowHits >= c.mentions:
			confidence = "low"
		case unique >= 2:
			confidence = "high"
		}
		severity := "info"
		if c.kind == "challenge" {
			severity = "medium"
			if unique >= 3 {
				severity = "high"
			}
		}
		sources := c.sources
		if sources == nil {
			sources = []map[string]any{}
		}
		out = append(out, map[string]any{
			"theme": c.theme, "label": c.label, "kind": c.kind, "mentions": c.mentions, "unique_staff": unique,
			"schools_affected": len(c.schools), "school_ids": sortedKeys(c.schools),
			"districts_affected": sortedKeys(c.districts), "activities_affected": len(c.activities),
			"dates": sortedKeys(c.dates), "confidence": confidence, "sources": sources, "severity": severity,
		})
	}
	return out, nil
}

// trend is _trend against the lead's finalized report of the week before.
func trend(ctx context.Context, tx pgx.Tx, clusters []map[string]any, leadID string, start time.Time) error {
	var raw []byte
	err := tx.QueryRow(ctx, `SELECT snapshot FROM weekly_debrief_report WHERE scope_kind = 'pl_team' AND scope_id = $1
  AND week_start = $2 AND status = 'finalized' ORDER BY version DESC LIMIT 1`, leadID,
		start.AddDate(0, 0, -7).Format(time.DateOnly)).Scan(&raw)
	if err != nil && !errors.Is(err, pgx.ErrNoRows) {
		return fmt.Errorf("debriefs: reading last week's report: %w", err)
	}
	previous := map[string]float64{}
	seen := map[string]bool{}
	if len(raw) > 0 {
		var snap struct {
			Clusters []map[string]any `json:"clusters"`
		}
		if err := json.Unmarshal(raw, &snap); err != nil {
			return err
		}
		for _, c := range snap.Clusters {
			theme, _ := c["theme"].(string)
			seen[theme] = true
			n, _ := c["unique_staff"].(float64)
			previous[theme] = n
		}
	}
	for _, c := range clusters {
		theme := c["theme"].(string)
		n := float64(c["unique_staff"].(int))
		switch {
		case !seen[theme]:
			c["trend"] = "new"
		case n > previous[theme]:
			c["trend"] = "worsening"
		case n < previous[theme]:
			c["trend"] = "improving"
		default:
			c["trend"] = "repeated"
		}
	}
	return nil
}

// storeReport is _store: the week's draft regenerated in place; over a
// finalized (or signed) report, a new version superseding it.
func storeReport(ctx context.Context, tx pgx.Tx, scopeKind, scopeID string, start, end time.Time, snapshot map[string]any,
	by, fy string, now time.Time) error {
	raw, err := json.Marshal(snapshot)
	if err != nil {
		return err
	}
	var id, status string
	var version int
	err = tx.QueryRow(ctx, `SELECT id, status, version FROM weekly_debrief_report WHERE scope_kind = $1 AND scope_id = $2
  AND week_start = $3 AND status <> 'superseded' ORDER BY version DESC LIMIT 1`, scopeKind, scopeID,
		start.Format(time.DateOnly)).Scan(&id, &status, &version)
	switch {
	case err == nil && status == "draft":
		_, err = tx.Exec(ctx, `UPDATE weekly_debrief_report SET snapshot = $2, generated_by_user_id = $3, updated_at = $4
WHERE id = $1`, id, raw, by, now)
		return wrapStore(err)
	case err == nil:
		if _, err := tx.Exec(ctx, `UPDATE weekly_debrief_report SET status = 'superseded', updated_at = $2 WHERE id = $1`,
			id, now); err != nil {
			return wrapStore(err)
		}
		version++
	case errors.Is(err, pgx.ErrNoRows):
		version = 1
	default:
		return wrapStore(err)
	}
	_, err = tx.Exec(ctx, `INSERT INTO weekly_debrief_report (id, created_at, updated_at, fy, scope_kind, scope_id, week_start,
  week_end, status, version, snapshot, generated_by_user_id)
VALUES ($1, $2, $2, $3, $4, $5, $6, $7, 'draft', $8, $9, $10)`, cuid.New(), now, fy, scopeKind, scopeID,
		start.Format(time.DateOnly), end.Format(time.DateOnly), version, raw, by)
	return wrapStore(err)
}

func wrapStore(err error) error {
	if err != nil {
		return fmt.Errorf("debriefs: storing the weekly report: %w", err)
	}
	return nil
}

func sortedKeys(set map[string]bool) []string {
	out := make([]string, 0, len(set))
	for k := range set {
		out = append(out, k)
	}
	sort.Strings(out)
	return out
}

func firstRunes(s string, n int) string {
	r := []rune(s)
	if len(r) > n {
		r = r[:n]
	}
	return string(r)
}
