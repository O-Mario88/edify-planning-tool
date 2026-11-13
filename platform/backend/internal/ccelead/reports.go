package ccelead

import (
	"context"
	"fmt"
	"strconv"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// ReportsPath is the monthly CCE reports.
const ReportsPath = "/cce-leadership/reports"

// reportLimit is how many reports the register reads.
const reportLimit = 240

// The roles the reports turn on (apps.cce_leadership.services).
const (
	regionalLead = "RegionalProgramLead"
	rvpRole      = "RegionalVicePresident"
	adminRole    = "Admin"
)

type report struct {
	id, author, status  string
	period              time.Time
	countries           []string
	submitted, reviewed *time.Time
	reviewer            *string
}

// visible is reports_visible_to as a WHERE clause on cce_regional_report
// `r`: every report for Admin; a Regional Lead's own; for an RVP every report
// sent (not a draft), of the countries their regions hold when they are
// assigned regions; nothing for anyone else.
func visible(ctx context.Context, db schooldirectory.Querier, p auth.Principal, now time.Time) (string, []any, error) {
	switch p.ActiveRole {
	case adminRole:
		return "TRUE", nil, nil
	case regionalLead:
		return "r.author_id = $1", []any{p.UserID}, nil
	case rvpRole:
		scope, err := schooldirectory.ResolveScope(ctx, db, p, now)
		if err != nil {
			return "", nil, fmt.Errorf("ccelead: resolving the RVP's scope: %w", err)
		}
		if !(scope.SummaryOnly && len(scope.RegionIDs) > 0) {
			return "r.status <> 'draft'", nil, nil
		}
		return `r.status <> 'draft' AND r.countries && ARRAY(
  SELECT DISTINCT g.country FROM region g WHERE g.id = ANY($1) AND g.country <> '')::varchar[]`, []any{scope.RegionIDs}, nil
	}
	return "FALSE", nil, nil
}

// day is _day: "%-d %b %Y" of the moment as stored (UTC).
func day(t *time.Time) string {
	if t == nil {
		return ""
	}
	return t.UTC().Format("2 Jan 2006")
}

func names(ctx context.Context, db schooldirectory.Querier, ids []string) (map[string]string, error) {
	out := map[string]string{}
	rows, err := db.Query(ctx, `SELECT id, name FROM "user" WHERE id = ANY($1) AND deleted_at IS NULL`, ids)
	if err != nil {
		return nil, fmt.Errorf("ccelead: reading names: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var id, name string
		if err := rows.Scan(&id, &name); err != nil {
			return nil, fmt.Errorf("ccelead: reading names: %w", err)
		}
		out[id] = name
	}
	return out, rows.Err()
}

func dash(v string) string {
	if v == "" {
		return "—"
	}
	return v
}

// reports is reports_view.
func reports(ctx context.Context, db schooldirectory.Querier, p auth.Principal, now time.Time) (register, error) {
	where, args, err := visible(ctx, db, p, now)
	if err != nil {
		return register{}, err
	}
	rows, err := db.Query(ctx, fmt.Sprintf(`
SELECT r.id, r.author_id, r.status, r.period, r.countries, r.submitted_at, r.reviewed_at, r.reviewed_by_id
FROM cce_regional_report r WHERE %s ORDER BY r.period DESC, r.created_at DESC LIMIT %d`, where, reportLimit), args...)
	if err != nil {
		return register{}, fmt.Errorf("ccelead: reading the reports: %w", err)
	}
	list, err := pgx.CollectRows(rows, func(r pgx.CollectableRow) (report, error) {
		var x report
		err := r.Scan(&x.id, &x.author, &x.status, &x.period, &x.countries, &x.submitted, &x.reviewed, &x.reviewer)
		return x, err
	})
	if err != nil {
		return register{}, fmt.Errorf("ccelead: reading the reports: %w", err)
	}
	lead := p.ActiveRole == regionalLead
	ids := []string{}
	for _, x := range list {
		if !lead {
			ids = append(ids, x.author)
		}
		if x.reviewer != nil {
			ids = append(ids, *x.reviewer)
		}
	}
	who, err := names(ctx, db, ids)
	if err != nil {
		return register{}, err
	}
	reg := register{
		path: ReportsPath, eyebrow: "Collaboration and reporting", registerTitle: "Reports",
		title: "Regional CCE Reports",
		description: "The Regional Lead's monthly report to the RVP and the VP of CCE: an executive summary with the region's " +
			"figures for training programmes, CCE impact, curriculum development and programme initiatives.",
		emptyTitle: "No reports yet",
		emptyBody:  "Reports appear here when a Regional Lead in your region submits one.",
		columns:    []string{"Month"},
	}
	if lead {
		reg.title = "Monthly CCE Reports"
		reg.emptyBody = "Start this month's report; the region's figures are added when you submit it."
		reg.actions = []action{{label: "Start a monthly report", drawer: ReportsPath + "/new"}}
	} else {
		reg.columns = append(reg.columns, "Regional Lead")
	}
	reg.columns = append(reg.columns, "Countries", "Status", "Submitted", "Review")
	counts := map[string]int{}
	for _, x := range list {
		counts[x.status]++
		cells := []string{x.period.Format("January 2006")}
		if !lead {
			cells = append(cells, dash(who[x.author]))
		}
		review := ""
		if x.reviewed != nil {
			name, ok := who[deref(x.reviewer)]
			if !ok {
				name = "RVP"
			}
			review = name + " · " + day(x.reviewed)
		}
		status, ok := rules.ReportStatuses[x.status]
		if !ok {
			status = x.status
		}
		cells = append(cells, dash(strings.Join(x.countries, ", ")), dash(status), dash(day(x.submitted)), dash(review))
		label := "Open"
		switch {
		case lead && (x.status == "draft" || x.status == "returned"):
			label = "Write"
		case !lead && x.status == "submitted":
			label = "Review"
		}
		reg.rows = append(reg.rows, cells)
		reg.rowActions = append(reg.rowActions, []action{{label: label, drawer: ReportsPath + "/" + x.id}})
	}
	awaiting := "for you to acknowledge or return"
	if lead {
		awaiting = "with the RVP"
	}
	tone := func(n int, on string) string {
		if n > 0 {
			return on
		}
		return "info"
	}
	reg.metrics = []metric{
		{"Report Drafts", strconv.Itoa(counts["draft"]), "being written", "info"},
		{"Reports Awaiting Review", strconv.Itoa(counts["submitted"]), awaiting, tone(counts["submitted"], "warning")},
		{"Reports Returned", strconv.Itoa(counts["returned"]), "to revise and resubmit", tone(counts["returned"], "danger")},
		{"Reports Acknowledged", strconv.Itoa(counts["acknowledged"]), "closed", "success"},
	}
	if lead {
		notice, err := overdue(ctx, db, p, now)
		if err != nil {
			return register{}, err
		}
		reg.notice = notice
	}
	return reg, nil
}

// overdue is report_state's notice: last month's report is due by the tenth
// of this month, and once that day has passed with it unstarted, a draft or
// returned, the register says so (months before reporting started were
// never owed).
func overdue(ctx context.Context, db schooldirectory.Querier, p auth.Principal, now time.Time) (string, error) {
	local := now.In(zone)
	today := time.Date(local.Year(), local.Month(), local.Day(), 0, 0, 0, 0, time.UTC)
	current := time.Date(today.Year(), today.Month(), 1, 0, 0, 0, 0, time.UTC)
	previous := current.AddDate(0, -1, 0)
	dueBy := time.Date(current.Year(), current.Month(), 10, 0, 0, 0, 0, time.UTC)
	if previous.Before(reportingStarts) || !today.After(dueBy) {
		return "", nil
	}
	var status *string
	err := db.QueryRow(ctx, `SELECT status FROM cce_regional_report WHERE author_id = $1 AND period = $2::date`,
		p.UserID, previous.Format(time.DateOnly)).Scan(&status)
	if err != nil && err != pgx.ErrNoRows {
		return "", fmt.Errorf("ccelead: reading last month's report: %w", err)
	}
	if status != nil && *status != "draft" && *status != "returned" {
		return "", nil
	}
	return fmt.Sprintf("The %s report was due by %d %s. Start it or finish it and submit it.",
		previous.Format("January 2006"), dueBy.Day(), dueBy.Format("January")), nil
}

func deref(s *string) string {
	if s == nil {
		return ""
	}
	return *s
}
