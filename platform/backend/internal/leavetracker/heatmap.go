package leavetracker

import (
	"context"
	"errors"
	"fmt"
	"strconv"
	"time"

	"github.com/jackc/pgx/v5"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// highWorkload is "act_count >= 5": a week this full is High Workload.
const highWorkload = 5

// HeatWeek is one person's week: its first and last day, what it is, the
// field work booked in it and the visits stranded by an absence.
type HeatWeek struct {
	Start, End time.Time
	Status     string
	Activities int
	Stranded   int
}

// HeatRow is one person across the weeks.
type HeatRow struct {
	StaffID, Name, Role string
	Weeks               []HeatWeek
}

// Heatmap is TeamAvailabilityService.get_4week_heatmap: the people a lead's
// People record supervises (everyone, for a reader who reads everyone or has
// no People record), by name, at most limit of them (0: no limit), across
// weekCount weeks from the Monday of today's week.
func Heatmap(ctx context.Context, db schooldirectory.Querier, p auth.Principal, everyone bool, limit, weekCount int, local time.Time) ([]HeatRow, error) {
	today := time.Date(local.Year(), local.Month(), local.Day(), 0, 0, 0, 0, time.UTC)
	monday := today.AddDate(0, 0, -((int(today.Weekday()) + 6) % 7))
	weeks := [][2]time.Time{}
	for i := range max(1, weekCount) {
		start := monday.AddDate(0, 0, 7*i)
		weeks = append(weeks, [2]time.Time{start, start.AddDate(0, 0, 6)})
	}
	first, last := weeks[0][0], weeks[len(weeks)-1][1]
	var profile string
	err := db.QueryRow(ctx, `SELECT id FROM staff_profile WHERE user_id = $1`, p.UserID).Scan(&profile)
	if err != nil && !errors.Is(err, pgx.ErrNoRows) {
		return nil, fmt.Errorf("leavetracker: reading the reader's People record: %w", err)
	}
	args := []any{}
	where := ""
	if profile != "" && !everyone {
		args = append(args, profile)
		where = " AND sp.id IN (SELECT supervisee_id FROM staff_supervisor_assignment WHERE supervisor_id = $1)"
	}
	bound := ""
	if limit > 0 {
		bound = " LIMIT " + strconv.Itoa(limit)
	}
	rows, err := db.Query(ctx, `SELECT sp.id, COALESCE(sp.user_id, ''), COALESCE(u.name, ''), COALESCE(u.active_role, 'None')
FROM staff_profile sp INNER JOIN "user" u ON u.id = sp.user_id WHERE sp.deleted_at IS NULL`+where+` ORDER BY u.name ASC`+bound, args...)
	if err != nil {
		return nil, fmt.Errorf("leavetracker: reading the heatmap's people: %w", err)
	}
	type person struct{ id, user, name, role string }
	people, err := pgx.CollectRows(rows, func(r pgx.CollectableRow) (person, error) {
		var x person
		return x, r.Scan(&x.id, &x.user, &x.name, &x.role)
	})
	if err != nil {
		return nil, fmt.Errorf("leavetracker: reading the heatmap's people: %w", err)
	}
	if len(people) == 0 {
		return nil, nil
	}
	ids, owners := []string{}, []string{}
	for _, x := range people {
		ids = append(ids, x.id)
		owners = append(owners, x.id, x.user)
	}
	leaves, err := spans(ctx, db, `SELECT staff_id, start_date, end_date FROM leave
WHERE staff_id = ANY($1) AND status = 'approved' AND start_date <= $2 AND end_date >= $3`, ids, last.Format(time.DateOnly), first.Format(time.DateOnly))
	if err != nil {
		return nil, err
	}
	blocks, err := spans(ctx, db, `SELECT block_type, start_date::text, end_date::text FROM calendar_block
WHERE block_type IN ('STAFF_CONFERENCE', 'BLACKOUT_DATE') AND is_active AND start_date <= $1::date AND end_date >= $2::date`,
		last.Format(time.DateOnly), first.Format(time.DateOnly))
	if err != nil {
		return nil, err
	}
	windowStart := time.Date(first.Year(), first.Month(), first.Day(), 0, 0, 0, 0, local.Location())
	windowEnd := time.Date(last.Year(), last.Month(), last.Day()+1, 0, 0, 0, 0, local.Location())
	rows, err = db.Query(ctx, `SELECT responsible_staff_id, scheduled_date FROM activity
WHERE deleted_at IS NULL AND responsible_staff_id = ANY($1) AND scheduled_date >= $2 AND scheduled_date < $3 AND NOT (status IN ('cancelled', 'completed'))`,
		owners, windowStart, windowEnd)
	if err != nil {
		return nil, fmt.Errorf("leavetracker: reading the booked work: %w", err)
	}
	booked := map[string][]time.Time{}
	for rows.Next() {
		var who string
		var at *time.Time
		if err := rows.Scan(&who, &at); err != nil {
			rows.Close()
			return nil, fmt.Errorf("leavetracker: reading the booked work: %w", err)
		}
		if at != nil {
			booked[who] = append(booked[who], *at)
		}
	}
	rows.Close()
	out := []HeatRow{}
	for _, x := range people {
		row := HeatRow{StaffID: x.id, Name: x.name, Role: x.role}
		dates := append(append([]time.Time{}, booked[x.id]...), booked[x.user]...)
		for _, w := range weeks {
			startText, endText := w[0].Format(time.DateOnly), w[1].Format(time.DateOnly)
			overlaps := func(list [][3]string, kind string) bool {
				for _, s := range list {
					if (kind == "" || s[0] == kind) && s[1] <= endText && s[2] >= startText {
						return true
					}
				}
				return false
			}
			mine := [][3]string{}
			for _, s := range leaves {
				if s[0] == x.id {
					mine = append(mine, s)
				}
			}
			onLeave, inConf, blocked := overlaps(mine, ""), overlaps(blocks, "STAFF_CONFERENCE"), overlaps(blocks, "BLACKOUT_DATE")
			count := 0
			for _, d := range dates {
				day := d.In(local.Location()).Format(time.DateOnly)
				if day >= startText && day <= endText {
					count++
				}
			}
			week := HeatWeek{Start: w[0], End: w[1], Status: "Available", Activities: count}
			switch {
			case onLeave:
				week.Status = "On Leave"
			case inConf:
				week.Status = "Conference Week"
			case blocked:
				week.Status = "Blocked"
			case count >= highWorkload:
				week.Status = "High Workload"
			}
			if onLeave || inConf {
				week.Stranded = count
			}
			row.Weeks = append(row.Weeks, week)
		}
		out = append(out, row)
	}
	return out, nil
}

// spans reads (key, start, end) rows.
func spans(ctx context.Context, db schooldirectory.Querier, sql string, args ...any) ([][3]string, error) {
	rows, err := db.Query(ctx, sql, args...)
	if err != nil {
		return nil, fmt.Errorf("leavetracker: reading the absences: %w", err)
	}
	defer rows.Close()
	out := [][3]string{}
	for rows.Next() {
		var s [3]string
		if err := rows.Scan(&s[0], &s[1], &s[2]); err != nil {
			return nil, fmt.Errorf("leavetracker: reading the absences: %w", err)
		}
		out = append(out, s)
	}
	return out, rows.Err()
}

// heatmap is the tracker's preview.
func (s *Service) heatmap(ctx context.Context, p auth.Principal, everyone bool, local time.Time) ([]HeatRow, error) {
	return Heatmap(ctx, s.db, p, everyone, rules.HeatmapLimit, 4, local)
}

// heatPanel is the Team Availability Matrix card as the feed reads it: each
// person's profile link, their role beside the first week's count, then the
// other weeks' counts (a blocked week draws a lock, which it does not read).
func heatPanel(heat []HeatRow) *screensv1.PageBlock {
	items := []*screensv1.PagePanelItem{}
	for _, r := range heat {
		items = append(items, &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Links{Links: &screensv1.PageLinks{Links: []*screensv1.PageLink{
			{Text: r.Name, Href: "/staff/" + r.StaffID}}}}})
		for i, w := range r.Weeks {
			value := strconv.Itoa(w.Activities)
			if w.Status == "Blocked" {
				value = ""
			}
			if i == 0 {
				items = append(items, &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Rows{Rows: &screensv1.PageDataRows{Rows: []*screensv1.PageDataRow{
					{Label: r.Role, Value: value}}}}})
				continue
			}
			if value != "" {
				items = append(items, text(value))
			}
		}
	}
	return panel("Team Availability Matrix (Heatmap)", items...)
}
