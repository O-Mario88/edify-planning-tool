package calendarpage

import (
	"context"
	"fmt"
	"time"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schoolprofile"
)

// activity is one row of the month's work, with what deciding whether it
// carries a tick box and whether it opens reads.
type activity struct {
	id, status, kind, name              string
	planned, scheduled, end             *time.Time
	schoolID, clusterID, districtID     string
	schoolName, clusterName, district   string
	hasSchool, hasCluster, hasDistrict  bool
	venue, delivery, staffID, monitorID string
	schoolOwner                         string
	clusterLead, clusterDistrict        string
	clusterRegion                       string
	clusterLive                         bool
	inCountry                           bool
}

// title is activity_name_snapshot or get_activity_type_display().
func (a *activity) title() string {
	if a.name != "" {
		return a.name
	}
	if label, ok := typeLabels[a.kind]; ok {
		return label
	}
	return a.kind
}

// place is where the calendar says the work is.
func (a *activity) place() string {
	switch {
	case a.schoolID != "":
		return a.schoolName
	case a.clusterID != "":
		return a.clusterName
	case a.kind == rules.ProgrammeEventType:
		if a.venue != "" {
			return a.venue
		}
		if a.districtID != "" {
			return a.district
		}
		return "Programme event"
	}
	return "Edify activity"
}

// start is the day it is on: its scheduled instant's local day, else its
// planned date.
func (a *activity) start() *time.Time {
	if a.scheduled != nil {
		d := localDay(*a.scheduled)
		return &d
	}
	return a.planned
}

// filter is the page's status and type filters.
type filter struct {
	status, kind string
	projects     []string
	byProject    bool
}

// readActivities is the view's month queryset: the work dated in the month
// (its scheduled instant's local day, else its planned date) or still
// running into it, with the status and type filters, in the view's order.
func readActivities(ctx context.Context, db schooldirectory.Querier, scope schooldirectory.Scope, start, end time.Time, f filter) ([]*activity, error) {
	args := []any{rules.TimeZone, start, end}
	arg := func(v any) string {
		args = append(args, v)
		return fmt.Sprintf("$%d", len(args))
	}
	where := ""
	if f.status == "cancelled" {
		where += " AND a.status = ANY(" + arg(rules.StatusFamilies["cancelled"]) + ")"
	} else {
		where += " AND NOT (a.status = ANY(" + arg(rules.HiddenStatuses) + "))"
		where += " AND NOT (a.status = ANY(" + arg(rules.OfficerCompletedStatuses) + "))"
		if f.status != "" {
			where += " AND a.status = ANY(" + arg(rules.StatusFamilies[f.status]) + ")"
		}
	}
	if f.kind != "" {
		where += " AND a.activity_type = " + arg(f.kind)
	}
	if f.byProject {
		where += " AND a.project_id = ANY(" + arg(f.projects) + ")"
	}
	inCountry := "false"
	if scope.CountryScope && scope.Country != "" {
		args = append(args, scope.CountryIDs())
		inCountry = schoolprofile.ActivityInCountry(len(args))
	}
	rows, err := db.Query(ctx, `
SELECT a.id, a.status, a.activity_type, COALESCE(a.activity_name_snapshot, ''),
  a.planned_date, a.scheduled_date, a.end_date,
  COALESCE(a.school_id, ''), COALESCE(a.cluster_id, ''), COALESCE(a.event_district_id, ''),
  COALESCE(s.name, ''), COALESCE(cl.name, ''), COALESCE(d.name, ''),
  s.id IS NOT NULL, cl.id IS NOT NULL, d.id IS NOT NULL,
  a.venue, a.delivery_type, COALESCE(a.responsible_staff_id, ''), COALESCE(a.monitored_by_staff_id, ''),
  COALESCE(s.account_owner_id, ''), COALESCE(cl.responsible_staff_id, ''), COALESCE(cl.district_id, ''),
  COALESCE(cl.region_id, ''), cl.id IS NOT NULL AND cl.deleted_at IS NULL, `+inCountry+`
FROM activity a
LEFT JOIN school s ON s.id = a.school_id
LEFT JOIN cluster cl ON cl.id = a.cluster_id
LEFT JOIN district d ON d.id = a.event_district_id
WHERE a.deleted_at IS NULL AND (
  (a.scheduled_date AT TIME ZONE $1)::date BETWEEN $2 AND $3
  OR (a.scheduled_date IS NULL AND a.planned_date BETWEEN $2 AND $3)
  OR (a.end_date >= $2 AND ((a.scheduled_date AT TIME ZONE $1)::date <= $3
      OR (a.scheduled_date IS NULL AND a.planned_date <= $3))))`+where+`
ORDER BY a.planned_date ASC, a.scheduled_date ASC, a.created_at ASC`, args...)
	if err != nil {
		return nil, fmt.Errorf("calendarpage: reading the month's work: %w", err)
	}
	return pgx.CollectRows(rows, func(row pgx.CollectableRow) (*activity, error) {
		a := &activity{}
		err := row.Scan(&a.id, &a.status, &a.kind, &a.name, &a.planned, &a.scheduled, &a.end,
			&a.schoolID, &a.clusterID, &a.districtID, &a.schoolName, &a.clusterName, &a.district,
			&a.hasSchool, &a.hasCluster, &a.hasDistrict, &a.venue, &a.delivery, &a.staffID, &a.monitorID,
			&a.schoolOwner, &a.clusterLead, &a.clusterDistrict, &a.clusterRegion, &a.clusterLive, &a.inCountry)
		if err != nil {
			return nil, fmt.Errorf("calendarpage: reading the month's work: %w", err)
		}
		return a, nil
	})
}

// projectIDs is the special-projects lens (project_scope=special): every
// project for a country reader, a coordinator's own, else those covering
// the reader's schools; one of them when ?project= names it.
func projectIDs(ctx context.Context, db schooldirectory.Querier, scope schooldirectory.Scope, role, staffID, selected string) ([]string, error) {
	var sql string
	var args []any
	switch {
	case scope.CountryScope:
		sql = `SELECT id FROM project WHERE deleted_at IS NULL`
	case role == rules.CoordinatorRole && staffID != "":
		sql, args = `SELECT id FROM project WHERE deleted_at IS NULL AND manager_staff_id = $1`, []any{staffID}
	case len(scope.SchoolIDs) > 0:
		sql = `SELECT DISTINCT p.id FROM project p JOIN project_school_assignment psa ON psa.project_id = p.id
WHERE p.deleted_at IS NULL AND psa.school_id = ANY($1)`
		args = []any{scope.SchoolIDs}
	default:
		return []string{}, nil
	}
	rows, err := db.Query(ctx, sql, args...)
	if err != nil {
		return nil, fmt.Errorf("calendarpage: reading the projects: %w", err)
	}
	ids, err := pgx.CollectRows(rows, pgx.RowTo[string])
	if err != nil {
		return nil, fmt.Errorf("calendarpage: reading the projects: %w", err)
	}
	if in(ids, selected) {
		return []string{selected}, nil
	}
	return ids, nil
}

// leave is one Leave row the month overlaps.
type leave struct {
	staffID, status, kind, start, end string
	name                              *string
}

// readLeave is the view's leave queryset: approved and pending leave the
// month overlaps (its dates are ISO text), of the staff given, or of
// everyone when all is set.
func readLeave(ctx context.Context, db schooldirectory.Querier, start, end time.Time, staff []string, all bool) ([]leave, error) {
	if !all && len(staff) == 0 {
		return nil, nil
	}
	args := []any{end.Format(time.DateOnly), start.Format(time.DateOnly)}
	where := ""
	if !all {
		args = append(args, staff)
		where = " AND l.staff_id = ANY($3)"
	}
	rows, err := db.Query(ctx, `
SELECT l.staff_id, l.status, l.type, l.start_date, l.end_date, u.name
FROM leave l JOIN staff_profile sp ON sp.id = l.staff_id JOIN "user" u ON u.id = sp.user_id
WHERE l.status IN ('approved', 'pending') AND l.start_date <= $1 AND l.end_date >= $2`+where, args...)
	if err != nil {
		return nil, fmt.Errorf("calendarpage: reading leave: %w", err)
	}
	return pgx.CollectRows(rows, func(row pgx.CollectableRow) (leave, error) {
		var l leave
		err := row.Scan(&l.staffID, &l.status, &l.kind, &l.start, &l.end, &l.name)
		return l, err
	})
}

// orgEvent is an organization event (CalendarBlock ORG_EVENT).
type orgEvent struct {
	title, description string
	start, end         time.Time
}

// readEvents is the view's organization events: active ORG_EVENT blocks the
// month overlaps, of the reader's country unless they are the Admin, by
// start and title.
func readEvents(ctx context.Context, db schooldirectory.Querier, start, end time.Time, country string) ([]orgEvent, error) {
	args := []any{start, end}
	where := ""
	if country != "" {
		args = append(args, country)
		where = " AND country = $3"
	}
	rows, err := db.Query(ctx, `
SELECT title, COALESCE(description, ''), start_date, end_date FROM calendar_block
WHERE is_active AND block_type = 'ORG_EVENT' AND start_date <= $2 AND end_date >= $1`+where+`
ORDER BY start_date ASC, title ASC`, args...)
	if err != nil {
		return nil, fmt.Errorf("calendarpage: reading the organization events: %w", err)
	}
	return pgx.CollectRows(rows, func(row pgx.CollectableRow) (orgEvent, error) {
		var e orgEvent
		err := row.Scan(&e.title, &e.description, &e.start, &e.end)
		return e, err
	})
}

// viewerCountry is StaffProfile.objects.filter(user=user) .values_list(
// "country").first(): the reader's live profile's country, by id.
func viewerCountry(ctx context.Context, db schooldirectory.Querier, userID string) (string, error) {
	var country string
	err := db.QueryRow(ctx, `SELECT country FROM staff_profile WHERE user_id = $1 AND deleted_at IS NULL ORDER BY id LIMIT 1`,
		userID).Scan(&country)
	if err == pgx.ErrNoRows {
		return "", nil
	}
	if err != nil {
		return "", fmt.Errorf("calendarpage: reading the reader's country: %w", err)
	}
	return country, nil
}

// isPartner is scoping.resolve_partner_ids for a member of staff: an active
// partner organisation signed in as this account.
func isPartner(ctx context.Context, db schooldirectory.Querier, userID string) (bool, error) {
	var yes bool
	err := db.QueryRow(ctx, `SELECT EXISTS (SELECT 1 FROM partner WHERE user_id = $1 AND active_status)`, userID).Scan(&yes)
	if err != nil {
		return false, fmt.Errorf("calendarpage: reading whether the reader is a partner: %w", err)
	}
	return yes, nil
}
