package cpdlearning

import (
	"context"
	"fmt"
	"slices"
	"strconv"
	"time"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/fundworkspace"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/notificationjobs"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// queueRow is one row of HRPDDashboardService.supervisor_queue: a request
// at the supervisor stage this reader may decide now.
type queueRow struct {
	id, staffName, course, courseType, fy, dates, amount, conflict string
	exception, covering                                            bool
	waited                                                         *int
}

// courseTypes are PDCourseType's labels.
var courseTypes = map[string]string{"online": "Online", "in_person": "In Person", "hybrid": "Hybrid"}

// supervisorQueue is supervisor_queue: the requests waiting at the
// supervisor stage whose reviewer (supervisors_for) is the reader or someone
// they cover today, oldest first.
func supervisorQueue(ctx context.Context, db schooldirectory.Querier, profileID string, now time.Time) ([]queueRow, error) {
	if profileID == "" {
		return nil, nil
	}
	actingFor := []string{profileID}
	rows, err := db.Query(ctx, `SELECT original_staff_id FROM temporary_coverage_assignment
		WHERE covering_staff_id = $1 AND start_datetime <= $2 AND end_datetime >= $2 AND status = 'active'`, profileID, now)
	if err != nil {
		return nil, fmt.Errorf("cpdlearning: reading the reader's cover: %w", err)
	}
	for rows.Next() {
		var id string
		if err := rows.Scan(&id); err != nil {
			rows.Close()
			return nil, err
		}
		actingFor = append(actingFor, id)
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, err
	}
	rows, err = db.Query(ctx, `SELECT id, staff_id, staff_name, course_name, course_type, fy, start_date, end_date, currency,
		requested_amount_cents, is_exception, COALESCE(conflict_status, ''), submitted_at
		FROM pd_request WHERE status = $1 AND staff_id <> $2 ORDER BY submitted_at, created_at`, statusSupervisor, profileID)
	if err != nil {
		return nil, fmt.Errorf("cpdlearning: reading the supervisor queue: %w", err)
	}
	type waiting struct {
		row        queueRow
		staff      string
		submitted  *time.Time
		start, end *time.Time
	}
	found := []waiting{}
	for rows.Next() {
		var w waiting
		var kind, currency string
		var cents int64
		if err := rows.Scan(&w.row.id, &w.staff, &w.row.staffName, &w.row.course, &kind, &w.row.fy, &w.start, &w.end,
			&currency, &cents, &w.row.exception, &w.row.conflict, &w.submitted); err != nil {
			rows.Close()
			return nil, err
		}
		w.row.courseType = courseTypes[kind]
		if w.row.courseType == "" {
			w.row.courseType = kind
		}
		w.row.amount = money(currency, cents)
		w.row.dates = "—"
		if w.start != nil && w.end != nil {
			w.row.dates = dayMonthYear(*w.start) + " – " + dayMonthYear(*w.end)
		}
		found = append(found, w)
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, err
	}
	local := now.In(zone)
	today := time.Date(local.Year(), local.Month(), local.Day(), 0, 0, 0, 0, time.UTC)
	out := []queueRow{}
	reviewers := map[string]string{}
	for _, w := range found {
		reviewer, seen := reviewers[w.staff]
		if !seen {
			if reviewer, _, err = notificationjobs.PDSupervisorOf(ctx, db, w.staff); err != nil {
				return nil, err
			}
			reviewers[w.staff] = reviewer
		}
		if reviewer == "" || !slices.Contains(actingFor, reviewer) {
			continue
		}
		if w.submitted != nil {
			// req.submitted_at.date(): the stored moment's own (UTC) day.
			s := w.submitted.UTC()
			n := int(today.Sub(time.Date(s.Year(), s.Month(), s.Day(), 0, 0, 0, 0, time.UTC)).Hours() / 24)
			w.row.waited = &n
		}
		w.row.covering = reviewer != profileID
		out = append(out, w.row)
	}
	return out, nil
}

// dayMonthYear is "%-d %b %Y".
func dayMonthYear(t time.Time) string { return strconv.Itoa(t.Day()) + " " + t.Format("Jan 2006") }

// queueBlocks is supervisor_queue.html as the feed reads it: the count and
// the table, each row's Return drawer its one action (Approve posts in
// place). always draws the heading and empty state when nothing waits.
func queueBlocks(queue []queueRow, always bool) []*screensv1.PageBlock {
	if len(queue) == 0 {
		if !always {
			return nil
		}
		return []*screensv1.PageBlock{fundworkspace.Panel("Waiting for your approval",
			fundworkspace.Text("Nothing is waiting for your approval. A request an officer submits appears here before it goes to HR."))}
	}
	rows := []*screensv1.PageRow{}
	for _, r := range queue {
		officer := r.staffName
		if r.covering {
			officer += " · you are covering"
		}
		amount := r.amount
		if r.exception {
			amount += " · over allocation"
		}
		waiting := "—"
		switch {
		case r.conflict == "major_conflict":
			waiting = "Schedule conflict"
		case r.waited != nil:
			waiting = strconv.Itoa(*r.waited) + " day" + plural(*r.waited)
		}
		rows = append(rows, &screensv1.PageRow{Cells: []*screensv1.PageCell{
			cell(officer), cell(r.course + " " + r.courseType + " · FY " + r.fy), cell(r.dates), cell(amount), cell(waiting),
			{Actions: []*screensv1.PageAction{{Key: "menu", Label: "Return", Enabled: true,
				Href: PagePath + "/return?request_id=" + r.id, Drawer: true}}},
		}})
	}
	return []*screensv1.PageBlock{
		fundworkspace.Panel("Waiting for your approval", fundworkspace.Text(fmt.Sprintf("%d request%s", len(queue), plural(len(queue))))),
		table([]string{"Officer", "Course", "Dates", "Requested", "Waiting", ""}, map[int]bool{3: true, 5: true}, rows, ""),
	}
}
