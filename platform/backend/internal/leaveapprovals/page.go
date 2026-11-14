// Package leaveapprovals is Leave Approvals (/leave/approvals): the leave
// requests the reader may decide, the queue's figures, the chosen request's
// impact, conflicts and possible cover, and the latest decisions, as the
// existing page draws them (apps.frontend.views.leave_views
// .leave_approvals_view over apps.hr.leave_services, and
// pages/leave/leave_approvals.html with partials/leave/impact_panel.html) and
// the app's feed reads them. Deciding stays with the existing application.
//
// A reader working in an acting appointment, and a chosen request that
// carries a supporting document, are passed on to the existing page.
//
// The doors, strips, figure labels and statuses are exported to rules.json
// by `manage.py export_leave_approvals_rules`;
// apps/hr/test_leave_approvals_rules_export.py fails when the two differ.
package leaveapprovals

import (
	"context"
	_ "embed"
	"encoding/json"
	"fmt"
	"net/url"
	"slices"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/calendarpage"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/decisionlog"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/leavetracker"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pagegate"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// Path is the page.
const Path = "/leave/approvals"

// The page's fixed counts: the latest decisions it lists, the holidays it
// names, the people of the availability card and its weeks.
const (
	recentLimit   = 10
	holidayLimit  = 5
	heatPeople    = 5
	heatWeeks     = 3
	balanceAlert  = 5
	lookbackDays  = 7
	defaultStatus = "pending"
)

//go:embed rules.json
var rulesJSON []byte

var rules = func() (r struct {
	Roles map[string]struct {
		Page  bool               `json:"page"`
		Strip *decisionlog.Strip `json:"strip"`
	} `json:"roles"`
	HeatmapEveryoneRoles []string `json:"heatmap_everyone_roles"`
	MetricLabels         []string `json:"metric_labels"`
	FundRequestStatuses  []string `json:"fund_request_statuses"`
	PageSize             int      `json:"page_size"`
}) {
	if err := json.Unmarshal(rulesJSON, &r); err != nil || len(r.Roles) == 0 || len(r.MetricLabels) != 6 || r.PageSize == 0 {
		panic(fmt.Sprintf("leaveapprovals: the embedded rules are unreadable: %v", err))
	}
	return r
}()

var zone = func() *time.Location {
	z, err := time.LoadLocation("Africa/Kampala")
	if err != nil {
		panic(fmt.Sprintf("leaveapprovals: loading the zone: %v", err))
	}
	return z
}()

// typeOptions and statusOptions are the filter bar's own choices.
var (
	typeOptions = [][2]string{{"personal_time_off", "Personal Time Off"}, {"sick_leave", "Sick Leave"}, {"maternity_leave", "Maternity Leave"},
		{"paternity_leave", "Paternity Leave"}, {"bereavement_leave", "Bereavement Leave"}}
	statusOptions = [][2]string{{"pending", "Pending Approval"}, {"approved", "Approved"}, {"rejected", "Rejected"},
		{"returned", "Returned"}, {"hr_review", "HR Escalated"}}
)

// Service answers the page from the existing database.
type Service struct {
	db  schooldirectory.Querier
	now func() time.Time
}

// NewService is the page over db.
func NewService(db schooldirectory.Querier, now func() time.Time) *Service {
	return &Service{db: db, now: now}
}

// decision is one of the latest decisions.
type decision struct {
	at                                  *time.Time
	staff, status, kind, start, end, by string
	days                                int
}

// figures is the queue's six figures.
type figures struct {
	pending, approved, previous, covered, conflicts, away, alerts int
}

// selected is the chosen request and what its panel reads.
type selected struct {
	leave      leave
	impact     impact
	conflicts  []conflict
	cover      []candidate
	heat       []leavetracker.HeatRow
	hasProfile bool
}

const leaveColumns = `l.id, l.staff_id, sp.user_id, COALESCE(u.name, ''), COALESCE(u.email, ''), COALESCE(u.active_role, 'None'), sp.country,
  l.type, l.start_date, l.end_date, l.status, COALESCE(l.coverage_status, ''), l.days, l.days_charged, COALESCE(l.reason, ''),
  COALESCE(l.attachment, '') <> '', COALESCE(l.covering_staff_id, ''), COALESCE(cu.name, ''), COALESCE(cu.active_role, 'None'), l.created_at
FROM leave l INNER JOIN staff_profile sp ON (l.staff_id = sp.id) INNER JOIN "user" u ON (sp.user_id = u.id)
LEFT OUTER JOIN staff_profile cs ON (l.covering_staff_id = cs.id) LEFT OUTER JOIN "user" cu ON (cs.user_id = cu.id)`

func (s *Service) leaves(ctx context.Context, where, order string, args ...any) ([]leave, error) {
	rows, err := s.db.Query(ctx, `SELECT `+leaveColumns+` WHERE `+where+` ORDER BY `+order, args...)
	if err != nil {
		return nil, fmt.Errorf("leaveapprovals: reading the leave: %w", err)
	}
	return pgx.CollectRows(rows, func(r pgx.CollectableRow) (leave, error) {
		var l leave
		return l, r.Scan(&l.id, &l.staffID, &l.staffUser, &l.staffName, &l.staffEmail, &l.staffRole, &l.staffCountry,
			&l.kind, &l.start, &l.end, &l.status, &l.coverageStatus, &l.days, &l.charged, &l.reason,
			&l.hasAttachment, &l.coverID, &l.coverName, &l.coverRole, &l.created)
	})
}

func likeArg(q string) string {
	return "%" + strings.NewReplacer(`\`, `\\`, "%", `\%`, "_", `\_`).Replace(q) + "%"
}

// Build answers Path.
func (s *Service) Build(ctx context.Context, p auth.Principal, path string, query url.Values) (*screensv1.GetPageResponse, bool, error) {
	if path != Path {
		return nil, false, nil
	}
	role, ok := rules.Roles[p.ActiveRole]
	if !ok || !role.Page {
		return nil, true, pagegate.ErrNotAvailable
	}
	if p.InActingAppointment {
		return nil, false, nil
	}
	now := s.now()
	rev, err := loadReviewer(ctx, s.db, p, now)
	if err != nil {
		return nil, true, err
	}
	q, kind, status := strings.TrimSpace(query.Get("q")), strings.TrimSpace(query.Get("type")), strings.TrimSpace(query.Get("status"))
	where, args := "l.status = $1", []any{status}
	if status == "" {
		args[0] = defaultStatus
	}
	if kind != "" {
		args = append(args, kind)
		where += fmt.Sprintf(" AND l.type = $%d", len(args))
	}
	if q != "" {
		args = append(args, likeArg(q))
		where += fmt.Sprintf(" AND (UPPER(u.name::text) LIKE UPPER($%[1]d) OR UPPER(l.reason::text) LIKE UPPER($%[1]d))", len(args))
	}
	listed, err := s.leaves(ctx, where, "l.created_at DESC", args...)
	if err != nil {
		return nil, true, err
	}
	queue := []leave{}
	for _, l := range listed {
		if rev.authorized(l) {
			queue = append(queue, l)
		}
	}
	f, err := s.figures(ctx, rev, now)
	if err != nil {
		return nil, true, err
	}
	recent, err := s.recent(ctx)
	if err != nil {
		return nil, true, err
	}
	var chosen *selected
	if len(queue) > 0 {
		pick := queue[0]
		for _, l := range queue {
			if want := query.Get("id"); want != "" && l.id == want {
				pick = l
				break
			}
		}
		if pick.hasAttachment {
			return nil, false, nil
		}
		if chosen, err = s.choose(ctx, p, rev, pick, now); err != nil {
			return nil, true, err
		}
	}
	holidays, err := calendarpage.Upcoming(ctx, s.db, now.In(zone), holidayLimit)
	if err != nil {
		return nil, true, err
	}
	return page(role.Strip, q, kind, status, f, queue, chosen, holidays, recent, query), true, nil
}

// choose reads the chosen request's impact, conflicts, cover and the
// reader's availability card.
func (s *Service) choose(ctx context.Context, p auth.Principal, rev reviewer, l leave, now time.Time) (*selected, error) {
	c := &selected{leave: l, hasProfile: rev.hasProfileRow}
	var err error
	if c.impact, err = analyze(ctx, s.db, l); err != nil {
		return nil, err
	}
	if c.conflicts, err = detect(ctx, s.db, l, true); err != nil {
		return nil, err
	}
	if c.cover, err = eligibleCover(ctx, s.db, l); err != nil {
		return nil, err
	}
	if rev.hasProfileRow {
		everyone := slices.Contains(rules.HeatmapEveryoneRoles, p.ActiveRole)
		if c.heat, err = leavetracker.Heatmap(ctx, s.db, p, everyone, 0, 4, now.In(zone)); err != nil {
			return nil, err
		}
	}
	return c, nil
}

// figures is the six figures over every pending request the reader may
// decide, whatever the filters.
func (s *Service) figures(ctx context.Context, rev reviewer, now time.Time) (figures, error) {
	var f figures
	pending, err := s.leaves(ctx, "l.status = 'pending'", "l.created_at ASC")
	if err != nil {
		return f, err
	}
	for _, l := range pending {
		if !rev.authorized(l) {
			continue
		}
		f.pending++
		if l.coverID != "" && (l.coverageStatus == "Accepted" || l.coverageStatus == "Approved") {
			f.covered++
		}
		found, err := detect(ctx, s.db, l, false)
		if err != nil {
			return f, err
		}
		if slices.ContainsFunc(found, func(c conflict) bool { return c.critical }) {
			f.conflicts++
		}
	}
	week := now.AddDate(0, 0, -lookbackDays)
	if err := s.db.QueryRow(ctx, `SELECT count(*) FILTER (WHERE reviewed_at >= $1), count(*) FILTER (WHERE reviewed_at >= $2 AND reviewed_at < $1)
FROM leave WHERE status = 'approved' AND reviewed_by_user_id = $3`, week, week.AddDate(0, 0, -lookbackDays), rev.userID).Scan(&f.approved, &f.previous); err != nil {
		return f, fmt.Errorf("leaveapprovals: counting the decisions: %w", err)
	}
	local := now.In(zone)
	today := time.Date(local.Year(), local.Month(), local.Day(), 0, 0, 0, 0, time.UTC)
	monday := today.AddDate(0, 0, -((int(today.Weekday()) + 6) % 7))
	away, err := s.leaves(ctx, "l.status = 'approved' AND l.start_date <= $1 AND l.end_date >= $2", "l.id",
		monday.AddDate(0, 0, 6).Format(time.DateOnly), monday.Format(time.DateOnly))
	if err != nil {
		return f, err
	}
	for _, l := range away {
		if rev.authorized(l) {
			f.away++
		}
	}
	alerts := `SELECT count(*) FROM leave_balance b JOIN staff_profile sp ON sp.id = b.staff_id
WHERE b.leave_type = 'personal_time_off' AND b.remaining < $1 AND b.year = $2`
	alertArgs := []any{balanceAlert, local.Year()}
	switch {
	case !rev.hasProfileRow:
		return f, nil
	case rev.role == "cd" || rev.role == "rvp":
		if rev.country == nil {
			alerts += " AND sp.country IS NULL"
		} else {
			alerts += " AND sp.country = $3"
			alertArgs = append(alertArgs, *rev.country)
		}
	default:
		alerts += " AND b.staff_id IN (SELECT supervisee_id FROM staff_supervisor_assignment WHERE supervisor_id = $3)"
		alertArgs = append(alertArgs, rev.profile)
	}
	if err := s.db.QueryRow(ctx, alerts, alertArgs...).Scan(&f.alerts); err != nil {
		return f, fmt.Errorf("leaveapprovals: counting the balance alerts: %w", err)
	}
	return f, nil
}

// recent is the latest decisions, whoever made them.
func (s *Service) recent(ctx context.Context) ([]decision, error) {
	rows, err := s.db.Query(ctx, `SELECT l.reviewed_at, COALESCE(u.name, ''), l.status, l.type, l.start_date, l.end_date, COALESCE(NULLIF(l.days_charged, 0), l.days),
  COALESCE((SELECT r.name FROM "user" r WHERE r.id = l.reviewed_by_user_id), 'System')
FROM leave l INNER JOIN staff_profile sp ON (l.staff_id = sp.id) INNER JOIN "user" u ON (sp.user_id = u.id)
WHERE l.reviewed_by_user_id IS NOT NULL ORDER BY l.reviewed_at DESC LIMIT $1`, recentLimit)
	if err != nil {
		return nil, fmt.Errorf("leaveapprovals: reading the latest decisions: %w", err)
	}
	return pgx.CollectRows(rows, func(r pgx.CollectableRow) (decision, error) {
		var d decision
		return d, r.Scan(&d.at, &d.staff, &d.status, &d.kind, &d.start, &d.end, &d.days, &d.by)
	})
}
