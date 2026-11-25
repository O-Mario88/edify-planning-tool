package teamtargets

import (
	"context"
	"fmt"
	"regexp"
	"slices"
	"strings"
	"time"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/feeddom"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// isoDay is the one form of date.fromisoformat Go reads; Python reads more
// (week dates, basic forms), which Go hands on.
var isoDay = regexp.MustCompile(`^\d{4}-\d{2}-\d{2}$`)

// dayRow is one activity of the day's drawer.
type dayRow struct{ where, staff, what, status string }

// DayDrawer is team_targets_day_view (PLTeamTargetsService.day_detail): the
// team's staff work planned on one day, split into valid completed, completed
// without an Activity SF ID, and planned (returned work left out).
func DayDrawer(ctx context.Context, db schooldirectory.Querier, p auth.Principal, q map[string]string, now time.Time) (*screensv1.PageDrawer, error) {
	if !slices.Contains(rules.PageRoles, p.ActiveRole) {
		return nil, &RefusedError{Refusal}
	}
	raw := strings.TrimSpace(q["date"])
	day, err := time.Parse(time.DateOnly, raw)
	switch {
	case err == nil:
	case raw == "" || isoDay.MatchString(raw) || !strings.ContainsAny(raw, "0123456789"):
		return nil, &RefusedError{"Invalid date."}
	default:
		return nil, ErrHandOn
	}
	ids, names, err := teamIDs(ctx, db, p, now)
	if err != nil {
		return nil, err
	}
	var completed, pendingSF, planned []dayRow
	if len(ids) > 0 {
		if completed, pendingSF, planned, err = readDay(ctx, db, ids, names, day); err != nil {
			return nil, err
		}
	}
	items := []*screensv1.DrawerItem{}
	section := func(title string, rows []dayRow, status bool) {
		if len(rows) == 0 {
			return
		}
		items = append(items, &screensv1.DrawerItem{Kind: &screensv1.DrawerItem_Heading{Heading: fmt.Sprintf("%s (%d)", title, len(rows))}})
		for _, r := range rows {
			// The row's two lines are parts drawn apart; the status pill
			// follows after a space.
			line := feeddom.JoinParts(r.where, r.staff+" · "+r.what)
			if status {
				line += " " + r.status
			}
			items = append(items, text(line))
		}
	}
	section("Valid completed", completed, true)
	section("Completed — Activity SF ID missing", pendingSF, false)
	section("Planned / scheduled", planned, true)
	if len(items) == 0 {
		items = append(items, text("Nothing planned or completed by the team on this day."))
	}
	return &screensv1.PageDrawer{Title: "Team activity on " + day.Format("Monday, 02 January 2006"), HasRequired: true,
		CancelLabel: "Cancel", Items: items}, nil
}

// readDay is day_detail's activities, newest first (Activity's ordering).
func readDay(ctx context.Context, db schooldirectory.Querier, ids []string, names map[string]string, day time.Time) (completed, pendingSF, planned []dayRow, err error) {
	rows, err := db.Query(ctx, `SELECT COALESCE(a.responsible_staff_id, ''), COALESCE(a.activity_type, ''), a.status,
		COALESCE(btrim(a.salesforce_activity_id), '') <> '', COALESCE(s.name, ''), COALESCE(c.name, ''), a.school_id IS NOT NULL, a.cluster_id IS NOT NULL
		FROM activity a LEFT JOIN school s ON s.id = a.school_id LEFT JOIN cluster c ON c.id = a.cluster_id
		WHERE a.responsible_staff_id = ANY($1) AND a.planned_date = $2::date AND a.deleted_at IS NULL AND a.delivery_type IS DISTINCT FROM 'partner'
		ORDER BY a.created_at DESC, a.id`, ids, day)
	if err != nil {
		return nil, nil, nil, fmt.Errorf("teamtargets: the day's activities: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var who, kind, status, school, cluster string
		var sf, hasSchool, hasCluster bool
		if err := rows.Scan(&who, &kind, &status, &sf, &school, &cluster, &hasSchool, &hasCluster); err != nil {
			return nil, nil, nil, err
		}
		r := dayRow{staff: names[who], what: rules.ActivityTypes[kind], status: pyTitle(strings.ReplaceAll(status, "_", " ")), where: "—"}
		if r.staff == "" {
			r.staff = "—"
		}
		if r.what == "" {
			r.what = kind
		}
		switch {
		case hasSchool:
			r.where = school
		case hasCluster:
			r.where = cluster
		}
		switch {
		case slices.Contains(rules.CompletedStatuses, status) && sf:
			completed = append(completed, r)
		case slices.Contains(rules.CompletedStatuses, status):
			pendingSF = append(pendingSF, r)
		case !slices.Contains(rules.ReturnedStatuses, status):
			planned = append(planned, r)
		}
	}
	return completed, pendingSF, planned, rows.Err()
}

// pyTitle is str.title: each run of letters starts upper-case, the rest
// lower-case.
func pyTitle(s string) string {
	var b strings.Builder
	prevLetter := false
	for _, r := range s {
		letter := r >= 'a' && r <= 'z' || r >= 'A' && r <= 'Z' || r > 0x7f && strings.ToUpper(string(r)) != strings.ToLower(string(r))
		switch {
		case letter && !prevLetter:
			b.WriteString(strings.ToUpper(string(r)))
		case letter:
			b.WriteString(strings.ToLower(string(r)))
		default:
			b.WriteRune(r)
		}
		prevLetter = letter
	}
	return b.String()
}
