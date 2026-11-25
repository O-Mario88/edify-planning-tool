package teamtargets

import (
	"context"
	"fmt"
	"slices"
	"strings"
	"time"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// Refusal is require_page_permission("team_targets")'s answer, and
// RefusedError carries a drawer's own refusal.
const Refusal = "Access Denied: Your active role does not have permission to view Team Targets."

// RefusedError is a drawer the view refuses, with its words.
type RefusedError struct{ Message string }

func (e *RefusedError) Error() string { return e.Message }

func text(s string) *screensv1.DrawerItem {
	return &screensv1.DrawerItem{Kind: &screensv1.DrawerItem_Text{Text: s}}
}

// backlogRow is one activity of a backlog drawer.
type backlogRow struct{ where, staff, what, date string }

// teamIDs are every id the reader's team's work is recorded under, and
// each id's person.
func teamIDs(ctx context.Context, db schooldirectory.Querier, p auth.Principal, now time.Time) ([]string, map[string]string, error) {
	scope, err := schooldirectory.ResolveScope(ctx, db, p, now)
	if err != nil {
		return nil, nil, err
	}
	team, err := supervisedUsers(ctx, db, p, scope)
	if err != nil {
		return nil, nil, err
	}
	ids, names := []string{}, map[string]string{}
	for _, m := range team {
		for _, id := range []string{m.UserID, m.StaffID} {
			if id != "" {
				ids = append(ids, id)
				names[id] = m.Name
			}
		}
	}
	return ids, names, nil
}

func readBacklog(ctx context.Context, db schooldirectory.Querier, where string, args []any, names map[string]string) ([]backlogRow, error) {
	rows, err := db.Query(ctx, `SELECT COALESCE(a.responsible_staff_id, ''), COALESCE(a.activity_type, ''), COALESCE(s.name, ''),
		COALESCE(c.name, ''), a.school_id IS NOT NULL, a.cluster_id IS NOT NULL, a.planned_date
		FROM activity a LEFT JOIN school s ON s.id = a.school_id LEFT JOIN cluster c ON c.id = a.cluster_id
		WHERE `+where+` AND a.deleted_at IS NULL AND a.delivery_type IS DISTINCT FROM 'partner'
		ORDER BY a.planned_date NULLS LAST, a.created_at DESC, a.id LIMIT 100`, args...)
	if err != nil {
		return nil, fmt.Errorf("teamtargets: the backlog: %w", err)
	}
	defer rows.Close()
	out := []backlogRow{}
	for rows.Next() {
		var who, kind, school, cluster string
		var hasSchool, hasCluster bool
		var day *time.Time
		if err := rows.Scan(&who, &kind, &school, &cluster, &hasSchool, &hasCluster, &day); err != nil {
			return nil, err
		}
		r := backlogRow{staff: names[who], what: rules.ActivityTypes[kind]}
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
		default:
			r.where = "—"
		}
		if day != nil {
			r.date = day.Format("02 Jan 2006")
		}
		out = append(out, r)
	}
	return out, rows.Err()
}

func backlogItems(rows []backlogRow, badge, helper, empty string) []*screensv1.DrawerItem {
	if len(rows) == 0 {
		return []*screensv1.DrawerItem{text(empty)}
	}
	items := []*screensv1.DrawerItem{}
	for _, r := range rows {
		items = append(items, text(strings.Join(strings.Fields(r.where+" "+r.staff+" · "+r.what+" · "+r.date+" "+badge), " ")))
	}
	return append(items, text(helper))
}

func fyOf(q map[string]string, now time.Time) string {
	if fy := strings.TrimSpace(q["fy"]); fy != "" {
		return fy
	}
	l := now.In(kampala)
	if l.Month() >= time.October {
		return fmt.Sprint(l.Year() + 1)
	}
	return fmt.Sprint(l.Year())
}

// SFIDBacklog is team_targets_sfid_backlog_view: the team's completed staff
// work owed an Activity SF ID and without one, the earliest 100.
func SFIDBacklog(ctx context.Context, db schooldirectory.Querier, p auth.Principal, q map[string]string, now time.Time) (*screensv1.PageDrawer, error) {
	if !slices.Contains(rules.PageRoles, p.ActiveRole) {
		return nil, &RefusedError{Refusal}
	}
	ids, names, err := teamIDs(ctx, db, p, now)
	if err != nil {
		return nil, err
	}
	rows := []backlogRow{}
	if len(ids) > 0 {
		if rows, err = readBacklog(ctx, db, `a.responsible_staff_id = ANY($1) AND a.fy = $2 AND a.activity_type = ANY($3)
			AND a.status = ANY($4) AND (a.salesforce_activity_id IS NULL OR a.salesforce_activity_id = '')`,
			[]any{ids, fyOf(q, now), rules.SFRequiredTypes, rules.CompletedStatuses}, names); err != nil {
			return nil, err
		}
	}
	return &screensv1.PageDrawer{Title: "Activity SF ID backlog", HasRequired: true, CancelLabel: "Cancel",
		Items: backlogItems(rows, "Not credited",
			"The responsible CCEO enters the Activity SF ID (program proof, not the NetSuite code) from My Plan; credit lands in the month the work happened.",
			"No SF ID backlog — every completed activity is credited.")}, nil
}

// ValidationBacklog is team_targets_validation_backlog_view: the team's
// staff work in one validation state, the earliest 100.
func ValidationBacklog(ctx context.Context, db schooldirectory.Querier, p auth.Principal, q map[string]string, now time.Time) (*screensv1.PageDrawer, error) {
	if !slices.Contains(rules.PageRoles, p.ActiveRole) {
		return nil, &RefusedError{Refusal}
	}
	status := strings.TrimSpace(q["status"])
	copy, ok := rules.Backlogs[status]
	if !ok {
		return nil, &RefusedError{"Unknown validation backlog."}
	}
	ids, names, err := teamIDs(ctx, db, p, now)
	if err != nil {
		return nil, err
	}
	rows := []backlogRow{}
	if len(ids) > 0 {
		if rows, err = readBacklog(ctx, db, `a.responsible_staff_id = ANY($1) AND a.fy = $2 AND a.status = $3`,
			[]any{ids, fyOf(q, now), status}, names); err != nil {
			return nil, err
		}
	}
	return &screensv1.PageDrawer{Title: copy.Title, HasRequired: true, CancelLabel: "Cancel",
		Items: backlogItems(rows, copy.Badge, copy.Helper, copy.Empty)}, nil
}
