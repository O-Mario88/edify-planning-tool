// Package leavetracker is the Team Leave & Coverage Tracker
// (/leave/tracker): each person's PTO and sick balance, who is away and who
// covers them, the cover handovers running now, and a four-week
// availability preview, as the existing page draws them
// (apps.frontend.views.leave_views.leave_tracker_view over
// apps.hr.leave_services, and pages/leave/leave_tracker.html) and the app's
// feed reads them; and the Team Availability Heatmap
// (/leave/team-availability, team_availability_view and
// pages/leave/team_availability.html) over the same heatmap.
//
// The existing page creates a person's balances for the year the first time
// it lists them. Go never writes on a read: while any listed person still
// lacks a balance, the page is passed on to the existing application.
//
// The doors, strips, roles, default balances and limits are exported to
// rules.json by `manage.py export_leave_tracker_rules`;
// apps/hr/test_leave_tracker_rules_export.py fails when the two differ.
package leavetracker

import (
	"context"
	_ "embed"
	"encoding/json"
	"errors"
	"fmt"
	"net/url"
	"slices"
	"strconv"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/closedschools"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/decisionlog"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/hrregister"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pagegate"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// Path is the page.
const Path = "/leave/tracker"

// noteChars is |truncatechars:120 on a handover note.
const noteChars = 120

//go:embed rules.json
var rulesJSON []byte

var rules = func() (r struct {
	Roles map[string]struct {
		Page              bool               `json:"page"`
		Strip             *decisionlog.Strip `json:"strip"`
		Availability      bool               `json:"availability"`
		AvailabilityStrip *decisionlog.Strip `json:"availability_strip"`
	} `json:"roles"`
	LeadRoles            []string       `json:"lead_roles"`
	HeatmapEveryoneRoles []string       `json:"heatmap_everyone_roles"`
	DefaultBalances      map[string]int `json:"default_balances"`
	HeatmapLimit         int            `json:"heatmap_limit"`
	PageSize             int            `json:"page_size"`
}) {
	if err := json.Unmarshal(rulesJSON, &r); err != nil || len(r.Roles) == 0 || r.PageSize == 0 || r.HeatmapLimit == 0 {
		panic(fmt.Sprintf("leavetracker: the embedded rules are unreadable: %v", err))
	}
	return r
}()

var zone = func() *time.Location {
	z, err := time.LoadLocation("Africa/Kampala")
	if err != nil {
		panic(fmt.Sprintf("leavetracker: loading the zone: %v", err))
	}
	return z
}()

// Service answers the tracker from the existing database.
type Service struct {
	db  schooldirectory.Querier
	now func() time.Time
}

// NewService is the tracker over db.
func NewService(db schooldirectory.Querier, now func() time.Time) *Service {
	return &Service{db: db, now: now}
}

// member is one row of the team table.
type member struct {
	id, name, role, title  string
	pto, sick              int
	onLeave                bool
	cover                  string
	nextStart, nextCharged string
	hasNext                bool
}

// coverage is one cover handover running now.
type coverage struct {
	covering, original, notes string
	ends                      time.Time
}

// Build answers Path.
func (s *Service) Build(ctx context.Context, p auth.Principal, path string, query url.Values) (*screensv1.GetPageResponse, bool, error) {
	if path == AvailabilityPath {
		return s.availability(ctx, p, query)
	}
	if path != Path {
		return nil, false, nil
	}
	role, ok := rules.Roles[p.ActiveRole]
	if !ok || !role.Page {
		return nil, true, pagegate.ErrNotAvailable
	}
	now := s.now()
	local := now.In(zone)
	today := local.Format(time.DateOnly)
	lead := slices.Contains(rules.LeadRoles, p.ActiveRole)
	var supervisees []string
	if lead {
		var err error
		if supervisees, err = s.supervisees(ctx, p.UserID); err != nil {
			return nil, true, err
		}
	}
	team, ids, err := s.team(ctx, p, lead, supervisees, strings.TrimSpace(query.Get("q")))
	if err != nil {
		return nil, true, err
	}
	complete, err := s.balancesComplete(ctx, ids, local.Year())
	if err != nil {
		return nil, true, err
	}
	if !complete {
		return nil, false, nil
	}
	if err := s.fill(ctx, team, ids, local.Year(), today); err != nil {
		return nil, true, err
	}
	covers, err := s.coverages(ctx, p, lead, supervisees, now)
	if err != nil {
		return nil, true, err
	}
	heat, err := s.heatmap(ctx, p, slices.Contains(rules.HeatmapEveryoneRoles, p.ActiveRole), local)
	if err != nil {
		return nil, true, err
	}
	return page(role.Strip, team, covers, heat, local.Year(), query), true, nil
}

// supervisees is everyone a People record of the reader supervises.
func (s *Service) supervisees(ctx context.Context, userID string) ([]string, error) {
	rows, err := s.db.Query(ctx, `SELECT a.supervisee_id FROM staff_supervisor_assignment a
JOIN staff_profile sv ON sv.id = a.supervisor_id WHERE sv.user_id = $1`, userID)
	if err != nil {
		return nil, fmt.Errorf("leavetracker: reading the lead's team: %w", err)
	}
	out, err := pgx.CollectRows(rows, pgx.RowTo[string])
	if err != nil {
		return nil, fmt.Errorf("leavetracker: reading the lead's team: %w", err)
	}
	return out, nil
}

// team is the people the reader tracks: a lead's supervisees, everyone else
// the People records in their reach; narrowed by the search; in the order
// the database returns them (the existing page sets none).
func (s *Service) team(ctx context.Context, p auth.Principal, lead bool, supervisees []string, q string) ([]member, []string, error) {
	args := []any{}
	var where string
	if lead {
		args = append(args, supervisees)
		where = "sp.id = ANY($1)"
	} else {
		w, a, _, err := hrregister.PeopleReachProfiles(ctx, s.db, p, args)
		if err != nil {
			return nil, nil, fmt.Errorf("leavetracker: resolving the reader's reach: %w", err)
		}
		where, args = w, a
	}
	if q != "" {
		args = append(args, "%"+strings.NewReplacer(`\`, `\\`, "%", `\%`, "_", `\_`).Replace(q)+"%")
		n := "$" + strconv.Itoa(len(args))
		where += ` AND (UPPER(u.name::text) LIKE UPPER(` + n + `) OR UPPER(u.email::text) LIKE UPPER(` + n + `) OR UPPER(sp.title::text) LIKE UPPER(` + n + `))`
	}
	rows, err := s.db.Query(ctx, `SELECT sp.id, COALESCE(u.name, ''), COALESCE(u.active_role, 'None'), COALESCE(NULLIF(sp.title, ''), 'Staff')
FROM staff_profile sp INNER JOIN "user" u ON (sp.user_id = u.id)
WHERE sp.deleted_at IS NULL AND `+where, args...)
	if err != nil {
		return nil, nil, fmt.Errorf("leavetracker: reading the team: %w", err)
	}
	team, err := pgx.CollectRows(rows, func(r pgx.CollectableRow) (member, error) {
		var m member
		return m, r.Scan(&m.id, &m.name, &m.role, &m.title)
	})
	if err != nil {
		return nil, nil, fmt.Errorf("leavetracker: reading the team: %w", err)
	}
	ids := make([]string, len(team))
	for i, m := range team {
		ids[i] = m.id
	}
	return team, ids, nil
}

// balancesComplete is whether every listed person has a balance of every
// leave type for the year: bulk_initialize_balances_for_staff would write
// nothing.
func (s *Service) balancesComplete(ctx context.Context, ids []string, year int) (bool, error) {
	if len(ids) == 0 {
		return true, nil
	}
	var policies, missing int
	err := s.db.QueryRow(ctx, `SELECT (SELECT count(*) FROM leave_type_policy),
  (SELECT count(*) FROM unnest($1::varchar[]) AS st(id) CROSS JOIN leave_type_policy p
   WHERE NOT EXISTS (SELECT 1 FROM leave_balance b WHERE b.staff_id = st.id AND b.leave_type = p.leave_type AND b.year = $2))`,
		ids, year).Scan(&policies, &missing)
	if err != nil {
		return false, fmt.Errorf("leavetracker: checking the balances: %w", err)
	}
	return policies > 0 && missing == 0, nil
}

// fill reads each person's balances, the leave they are on today and the
// next leave booked.
func (s *Service) fill(ctx context.Context, team []member, ids []string, year int, today string) error {
	if len(ids) == 0 {
		return nil
	}
	at := map[string]int{}
	for i, m := range team {
		at[m.id] = i
		team[i].pto, team[i].sick = rules.DefaultBalances["personal_time_off"], rules.DefaultBalances["sick_leave"]
	}
	rows, err := s.db.Query(ctx, `SELECT staff_id, leave_type, remaining FROM leave_balance
WHERE staff_id = ANY($1) AND year = $2 AND leave_type IN ('personal_time_off', 'sick_leave')`, ids, year)
	if err != nil {
		return fmt.Errorf("leavetracker: reading the balances: %w", err)
	}
	for rows.Next() {
		var id, kind string
		var left int
		if err := rows.Scan(&id, &kind, &left); err != nil {
			rows.Close()
			return fmt.Errorf("leavetracker: reading the balances: %w", err)
		}
		if kind == "personal_time_off" {
			team[at[id]].pto = left
		} else {
			team[at[id]].sick = left
		}
	}
	rows.Close()
	rows, err = s.db.Query(ctx, `SELECT DISTINCT ON (l.staff_id) l.staff_id, COALESCE(u.name, ''), l.covering_staff_id IS NOT NULL
FROM leave l LEFT JOIN staff_profile c ON c.id = l.covering_staff_id LEFT JOIN "user" u ON u.id = c.user_id
WHERE l.staff_id = ANY($1) AND l.status = 'approved' AND l.start_date <= $2 AND l.end_date >= $2
ORDER BY l.staff_id, l.start_date`, ids, today)
	if err != nil {
		return fmt.Errorf("leavetracker: reading today's leave: %w", err)
	}
	for rows.Next() {
		var id, cover string
		var covered bool
		if err := rows.Scan(&id, &cover, &covered); err != nil {
			rows.Close()
			return fmt.Errorf("leavetracker: reading today's leave: %w", err)
		}
		if !covered {
			cover = "None"
		}
		team[at[id]].onLeave, team[at[id]].cover = true, cover
	}
	rows.Close()
	rows, err = s.db.Query(ctx, `SELECT DISTINCT ON (staff_id) staff_id, start_date, COALESCE(days_charged::text, 'None')
FROM leave WHERE staff_id = ANY($1) AND status = 'approved' AND start_date > $2 ORDER BY staff_id, start_date`, ids, today)
	if err != nil {
		return fmt.Errorf("leavetracker: reading the next leave: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var id, start, charged string
		if err := rows.Scan(&id, &start, &charged); err != nil {
			return fmt.Errorf("leavetracker: reading the next leave: %w", err)
		}
		m := &team[at[id]]
		m.hasNext, m.nextStart, m.nextCharged = true, start, charged
	}
	return rows.Err()
}

// coverages is every cover handover running now; a lead's are their own and
// their team's, and a lead with no People record has none.
func (s *Service) coverages(ctx context.Context, p auth.Principal, lead bool, supervisees []string, now time.Time) ([]coverage, error) {
	args := []any{now}
	where := ""
	if lead {
		var profile string
		err := s.db.QueryRow(ctx, `SELECT id FROM staff_profile WHERE user_id = $1`, p.UserID).Scan(&profile)
		if errors.Is(err, pgx.ErrNoRows) {
			return nil, nil
		}
		if err != nil {
			return nil, fmt.Errorf("leavetracker: reading the lead's People record: %w", err)
		}
		args = append(args, append([]string{profile}, supervisees...))
		where = " AND (t.original_staff_id = ANY($2) OR t.covering_staff_id = ANY($2))"
	}
	rows, err := s.db.Query(ctx, `SELECT COALESCE(cu.name, ''), COALESCE(ou.name, ''), COALESCE(NULLIF(l.coverage_notes, ''), 'No instructions provided'), t.end_datetime
FROM temporary_coverage_assignment t
JOIN staff_profile c ON c.id = t.covering_staff_id JOIN "user" cu ON cu.id = c.user_id
JOIN staff_profile o ON o.id = t.original_staff_id JOIN "user" ou ON ou.id = o.user_id
LEFT JOIN leave l ON l.id = t.leave_request_id
WHERE t.status = 'active' AND t.start_datetime <= $1 AND t.end_datetime >= $1`+where+` ORDER BY t.start_datetime`, args...)
	if err != nil {
		return nil, fmt.Errorf("leavetracker: reading the coverages: %w", err)
	}
	out, err := pgx.CollectRows(rows, func(r pgx.CollectableRow) (coverage, error) {
		var c coverage
		return c, r.Scan(&c.covering, &c.original, &c.notes, &c.ends)
	})
	if err != nil {
		return nil, fmt.Errorf("leavetracker: reading the coverages: %w", err)
	}
	return out, nil
}

// initials is |slice:":2"|upper.
func initials(name string) string {
	r := []rune(name)
	return strings.ToUpper(string(r[:min(2, len(r))]))
}

// truncate is |truncatechars:n.
func truncate(s string, n int) string {
	r := []rune(s)
	if len(r) <= n {
		return s
	}
	return string(r[:n-1]) + "…"
}

func text(t string) *screensv1.PagePanelItem {
	return &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Text{Text: t}}
}

func panel(title string, items ...*screensv1.PagePanelItem) *screensv1.PageBlock {
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{Title: title, Items: items}}}
}

// page is pages/leave/leave_tracker.html as the feed reads it.
func page(strip *decisionlog.Strip, team []member, covers []coverage, heat []HeatRow, year int, query url.Values) *screensv1.GetPageResponse {
	header := &screensv1.PageHeader{Eyebrow: "Time & Availability", Title: "Team Leave & Coverage Tracker",
		Description: "Monitor leave balances, active coverage handovers, and department availability"}
	blocks := []*screensv1.PageBlock{}
	if strip != nil {
		tabs := &screensv1.PageLinkTabs{Label: strip.Label, Scrolls: strip.Scrolls}
		for _, t := range strip.Tabs {
			tabs.Tabs = append(tabs.Tabs, &screensv1.PageLinkTab{Label: t.Label, Href: t.Href, Active: t.Active})
		}
		blocks = append(blocks, &screensv1.PageBlock{Kind: &screensv1.PageBlock_LinkTabs{LinkTabs: tabs}})
	}
	if len(covers) > 0 {
		blocks = append(blocks, &screensv1.PageBlock{Kind: &screensv1.PageBlock_Section{Section: "Active Delegated Coverages"}})
		for _, c := range covers {
			blocks = append(blocks, panel("", text("Active Coverage"), text("Expires: "+c.ends.In(zone).Format("02 Jan")),
				text(initials(c.covering)), text(initials(c.original)), text("Covering: "+c.covering), text("Acting for: "+c.original),
				text("Handover Instructions"), text(closedschools.Collapse(truncate(c.notes, noteChars)))))
		}
	}
	blocks = append(blocks, panel("Team Resource Cockpit", text("Active Year: "+strconv.Itoa(year))))
	blocks = append(blocks, teamTable(team, query)...)
	return &screensv1.GetPageResponse{Header: header, Blocks: append(blocks, heatPanel(heat)), WebPath: Path}
}

// teamTable is the Team Resource Cockpit's table and its pager.
func teamTable(team []member, query url.Values) []*screensv1.PageBlock {
	t := &screensv1.PageTable{}
	for _, c := range []string{"Team Member", "Role & Title", "Remaining PTO", "Remaining Sick", "Status", "Active Cover", "Next Leave Scheduled"} {
		t.Columns = append(t.Columns, &screensv1.PageColumn{Label: c, Numeric: c == "Next Leave Scheduled"})
	}
	size := rules.PageSize
	number, pages := closedschools.PageOf(query.Get("team_page"), len(team), size)
	badge := func(s string) *screensv1.PageCell { return &screensv1.PageCell{Text: s, Tone: "primary", Badge: true} }
	for _, m := range team[min((number-1)*size, len(team)):min(number*size, len(team))] {
		status, cover := "Active", "—"
		if m.onLeave {
			status, cover = "On Leave", m.cover
		}
		next := "None scheduled"
		if m.hasNext {
			next = m.nextStart + " (" + m.nextCharged + " working days)"
		}
		t.Rows = append(t.Rows, &screensv1.PageRow{Cells: []*screensv1.PageCell{
			{Text: closedschools.Collapse(initials(m.name) + " " + m.name)}, {Text: closedschools.Collapse(m.title + " " + m.role)},
			badge(strconv.Itoa(m.pto) + " days"), badge(strconv.Itoa(m.sick) + " days"), badge(status),
			{Text: closedschools.Collapse(cover)}, {Text: closedschools.Collapse(next)},
		}})
	}
	if len(team) == 0 {
		t.Rows = []*screensv1.PageRow{{Cells: []*screensv1.PageCell{{Text: "No team members found."}}}}
	}
	blocks := []*screensv1.PageBlock{{Kind: &screensv1.PageBlock_Table{Table: t}}}
	if pages > 1 {
		blocks = append(blocks, closedschools.PagerPanel("team_page", number, pages, len(team), size, query, nil))
	}
	return blocks
}
