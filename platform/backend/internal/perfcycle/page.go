// Package perfcycle is the Performance Cycle Console (/hr/performance-cycle):
// the year's cycle readiness, its window controls and the annual agreements
// of the people the reader may see, as the existing page draws it
// (apps.frontend.views.hr_views.hr_performance_console_view,
// apps.hr.performance_engine.quarterly_readiness and
// pages/hr/performance_console.html) and the app's feed reads it. Opening
// the cycle, the windows and every agreement decision stay with the
// existing application.
//
// The doors, windows, stage words and page size are exported to rules.json
// by `manage.py export_performance_cycle_rules`;
// apps/hr/test_performance_cycle_rules_export.py fails when the two differ.
package perfcycle

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
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/hrregister"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pagegate"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// Path is the page.
const Path = "/hr/performance-cycle"

const pageParam = "review_rows_page"

// reminderDays is quarterly_readiness's notice: with this many days to the
// quarter's end the read notifies HR, so that day's page is the existing
// application's to answer.
const reminderDays = 7

//go:embed rules.json
var rulesJSON []byte

var rules = func() (r struct {
	PageRoles             []string          `json:"page_roles"`
	ConsoleRoles          []string          `json:"console_roles"`
	Windows               [][2]string       `json:"windows"`
	StageLabels           map[string]string `json:"stage_labels"`
	ReviewType            string            `json:"review_type"`
	ActiveOnboardingState string            `json:"active_onboarding_state"`
	PageSize              int               `json:"page_size"`
}) {
	if err := json.Unmarshal(rulesJSON, &r); err != nil || len(r.PageRoles) == 0 || len(r.ConsoleRoles) == 0 || len(r.Windows) == 0 || r.PageSize == 0 {
		panic(fmt.Sprintf("perfcycle: the embedded rules are unreadable: %v", err))
	}
	return r
}()

var zone = func() *time.Location {
	z, err := time.LoadLocation("Africa/Kampala")
	if err != nil {
		panic(fmt.Sprintf("perfcycle: loading the zone: %v", err))
	}
	return z
}()

// Service answers the console from the existing database.
type Service struct {
	db  schooldirectory.Querier
	now func() time.Time
}

// NewService is the console over db.
func NewService(db schooldirectory.Querier, now func() time.Time) *Service {
	return &Service{db: db, now: now}
}

// readiness is quarterly_readiness's report.
type readiness struct {
	quarter                                    string
	daysLeft, inCycle, noPriorities, noManager int
}

// agreement is one annual agreement's row.
type agreement struct{ staff, name, stage string }

// quarterEnd is the quarter today falls in (October starts Q1) and the day
// it ends.
func quarterEnd(today time.Time) (string, time.Time) {
	var q string
	var m time.Month
	d := 31
	switch mo := today.Month(); {
	case mo >= 10:
		q, m = "Q1", time.December
	case mo <= 3:
		q, m = "Q2", time.March
	case mo <= 6:
		q, m, d = "Q3", time.June, 30
	default:
		q, m, d = "Q4", time.September, 30
	}
	year := today.Year()
	if m < today.Month() || (m == today.Month() && d < today.Day()) {
		year++
	}
	return q, time.Date(year, m, d, 0, 0, 0, 0, time.UTC)
}

// Build answers Path. A role the page lets in but whose controls these are
// not is sent to the dashboard, as render_access_denied sends the feed.
func (s *Service) Build(ctx context.Context, p auth.Principal, path string, query url.Values) (*screensv1.GetPageResponse, bool, error) {
	if path != Path {
		return nil, false, nil
	}
	if !slices.Contains(rules.PageRoles, p.ActiveRole) {
		return nil, true, pagegate.ErrNotAvailable
	}
	if !slices.Contains(rules.ConsoleRoles, p.ActiveRole) {
		// render_access_denied: the feed is sent to the dashboard.
		return &screensv1.GetPageResponse{Redirect: "/dashboard"}, true, nil
	}
	now := s.now().In(zone)
	today := time.Date(now.Year(), now.Month(), now.Day(), 0, 0, 0, 0, time.UTC)
	q, end := quarterEnd(today)
	r := readiness{quarter: q, daysLeft: int(end.Sub(today).Hours() / 24)}
	if r.daysLeft == reminderDays {
		return nil, false, nil
	}
	fy := query.Get("fy")
	if fy == "" {
		fy = schooldirectory.OperationalFY(s.now())
	}
	if err := s.db.QueryRow(ctx, `
WITH staff AS (SELECT id FROM staff_profile WHERE deleted_at IS NULL AND onboarding_state = $1)
SELECT (SELECT count(*) FROM staff),
  (SELECT count(*) FROM staff WHERE id NOT IN (SELECT staff_id FROM hr_performance_review WHERE fy = $2 AND review_type = $3)),
  (SELECT count(*) FROM staff WHERE id NOT IN (SELECT l.supervisee_id FROM staff_supervisor_assignment l
     JOIN staff_profile sp ON sp.id = l.supervisee_id WHERE sp.deleted_at IS NULL))`,
		rules.ActiveOnboardingState, fy, rules.ReviewType).Scan(&r.inCycle, &r.noPriorities, &r.noManager); err != nil {
		return nil, true, fmt.Errorf("perfcycle: reading the cycle's readiness: %w", err)
	}
	var window string
	open := true
	err := s.db.QueryRow(ctx, `SELECT active_window FROM hr_performance_cycle WHERE fy = $1`, fy).Scan(&window)
	if errors.Is(err, pgx.ErrNoRows) {
		open, window = false, "none"
	} else if err != nil {
		return nil, true, fmt.Errorf("perfcycle: reading the cycle: %w", err)
	}
	reach, args, _, err := hrregister.PeopleReachProfiles(ctx, s.db, p, []any{fy, rules.ReviewType})
	if err != nil {
		return nil, true, fmt.Errorf("perfcycle: reading the people reach: %w", err)
	}
	rows, err := s.db.Query(ctx, `
SELECT r.staff_id, COALESCE(u.name, '—'), r.stage FROM hr_performance_review r
JOIN staff_profile rp ON rp.id = r.staff_id LEFT JOIN "user" u ON u.id = rp.user_id
WHERE r.fy = $1 AND r.review_type = $2 AND r.staff_id IN (
  SELECT sp.id FROM staff_profile sp JOIN "user" pu ON pu.id = sp.user_id
  WHERE sp.deleted_at IS NULL AND pu.deleted_at IS NULL AND `+reach+`)
ORDER BY u.name`, args...)
	if err != nil {
		return nil, true, fmt.Errorf("perfcycle: reading the agreements: %w", err)
	}
	list, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (agreement, error) {
		var a agreement
		return a, row.Scan(&a.staff, &a.name, &a.stage)
	})
	if err != nil {
		return nil, true, fmt.Errorf("perfcycle: reading the agreements: %w", err)
	}
	return page(fy, open, window, r, list, query), true, nil
}

func text(t string) *screensv1.PagePanelItem {
	return &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Text{Text: t}}
}

func figure(label string, n int, note string) *screensv1.PageBlock {
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{Items: []*screensv1.PagePanelItem{
		{Kind: &screensv1.PagePanelItem_Rows{Rows: &screensv1.PageDataRows{Rows: []*screensv1.PageDataRow{{Label: label, Value: strconv.Itoa(n)}}}}},
		text(note),
	}}}}
}

// stageLabel is the console's word for a stage, else the stage in title
// case.
func stageLabel(stage string) string {
	if l, ok := rules.StageLabels[stage]; ok {
		return l
	}
	words := strings.Fields(strings.ReplaceAll(stage, "_", " "))
	for i, w := range words {
		words[i] = strings.ToUpper(w[:1]) + strings.ToLower(w[1:])
	}
	return strings.Join(words, " ")
}

// page is pages/hr/performance_console.html as the feed reads it.
func page(fy string, open bool, window string, r readiness, list []agreement, query url.Values) *screensv1.GetPageResponse {
	header := &screensv1.PageHeader{Eyebrow: "People & Culture", Title: "Performance Cycle Console",
		Description: "HR controls the whole cycle here — open it, activate a conversation window (which freezes every snapshot), approve agreements, and return or reopen records. Every action is audited."}
	state := "Not opened"
	if open {
		state = "Open"
	}
	windowWord, formWord := window, "form open"
	if window == "none" {
		windowWord, formWord = "None", "form locked"
	}
	blocks := []*screensv1.PageBlock{
		{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{Items: []*screensv1.PagePanelItem{
			text("Cycle"), text(state), text(r.quarter + " · " + strconv.Itoa(r.daysLeft) + " days to quarter end")}}}},
		figure("Staff in cycle", r.inCycle, "active employees"),
		figure("Missing priorities", r.noPriorities, "without an agreement"),
		figure("Missing managers", r.noManager, "no reporting line"),
		{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{Items: []*screensv1.PagePanelItem{
			text("Active window"), text(windowWord), text(formWord)}}}},
		controls(fy, open, window),
		{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{Title: "Agreements in scope (" + strconv.Itoa(len(list)) + ")"}}},
	}
	t := &screensv1.PageTable{Columns: []*screensv1.PageColumn{{Label: "Employee"}, {Label: "Stage"}, {Label: "Actions", Numeric: true}}}
	number, pages := closedschools.PageOf(query.Get(pageParam), len(list), rules.PageSize)
	for _, a := range list[min((number-1)*rules.PageSize, len(list)):min(number*rules.PageSize, len(list))] {
		// The row's menu holds forms and in-page buttons the feed does not
		// read; only the conversation link reaches the app.
		t.Rows = append(t.Rows, &screensv1.PageRow{Cells: []*screensv1.PageCell{
			{Text: closedschools.Collapse(a.name)}, {Text: stageLabel(a.stage)},
			{Actions: []*screensv1.PageAction{{Key: "menu", Label: "Open conversation", Enabled: true, Href: "/performance-conversation?staff=" + a.staff}}},
		}})
	}
	if len(list) == 0 {
		t.Rows = []*screensv1.PageRow{{Cells: []*screensv1.PageCell{{Text: "No agreements yet — open the cycle to draft them."}}}}
	}
	blocks = append(blocks, &screensv1.PageBlock{Kind: &screensv1.PageBlock_Table{Table: t}})
	if pages > 1 {
		blocks = append(blocks, closedschools.PagerPanel(pageParam, number, pages, len(list), rules.PageSize, query, nil))
	}
	return &screensv1.GetPageResponse{Header: header, Blocks: blocks, WebPath: Path}
}

// controls is the cycle controls card: the Open button's words before the
// cycle exists (its form asks nothing); once it does, the window form read
// as itself while no window is open, and, with a Close form beside it, the
// card's words.
func controls(fy string, open bool, window string) *screensv1.PageBlock {
	if !open {
		return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{Items: []*screensv1.PagePanelItem{
			text("Open FY" + fy + " cycle & draft agreements")}}}}
	}
	if window != "none" {
		labels := ""
		for _, w := range rules.Windows {
			labels += w[1]
		}
		return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{Items: []*screensv1.PagePanelItem{
			text("Activate window " + labels + " Deadline Activate & freeze snapshots Close window")}}}}
	}
	options := []*screensv1.DrawerOption{}
	for _, w := range rules.Windows {
		options = append(options, &screensv1.DrawerOption{Value: w[0], Label: w[1]})
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Form{Form: &screensv1.PageForm{
		Items: []*screensv1.PageFormItem{
			{Kind: &screensv1.PageFormItem_Field{Field: &screensv1.DrawerField{Name: "window", Label: "Window", Kind: "select", Value: rules.Windows[0][0], Options: options}}},
			{Kind: &screensv1.PageFormItem_Field{Field: &screensv1.DrawerField{Name: "deadline", Label: "Deadline", Kind: "date"}}},
		},
		SubmitLabel: "Activate & freeze snapshots",
		Key:         "activate_window",
	}}}
}
