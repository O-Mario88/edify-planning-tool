// Package todaypage is the standalone Today page (/today,
// apps.frontend.views.today_views.today_page) for a reader whose day is at a
// desk and whose Today lives there (the Admin; field roles and Impact
// Assessment are sent to their dashboards, which Go hands on): the tally of
// what was cleared from Today and snoozed, then "Waiting on you", the
// reader's actionable To-Dos less those they snoozed, each with the Actions
// menu today_actions.decorate gives it (a decision's drawer, an activity's
// next form, the row's own link) as the feed reads that menu.
//
// Handed on: a reader with exceptions (critical or blocked rows, drawn as a
// list of their own), with identical To-Dos the page groups, with a money
// row (its amount) or a row whose description Go does not write yet, a reader who verifies SSA (the next SSA leads the list)
// and every save (the decisions and snoozes stay with the existing
// application, or todosnooze).
//
// The rules are exported to rules.json by `manage.py export_today_rules`;
// apps/command_center/test_today_rules_export.py fails when the two differ.
package todaypage

import (
	"context"
	_ "embed"
	"encoding/json"
	"fmt"
	"net/url"
	"regexp"
	"strconv"
	"strings"
	"time"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/feeddom"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pagegate"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/todos"
)

// Path is the page.
const Path = "/today"

// deskDescription is the header's words for a reader who is not a
// Programme Lead.
const deskDescription = "Your prepared day: the route, the next action, what waits on you, and what needs attention. " +
	"Everything else stays in the background."

type operation struct {
	Key        string `json:"key"`
	Label      string `json:"label"`
	Tone       string `json:"tone"`
	NeedsForm  bool   `json:"needs_form"`
	Drawer     string `json:"drawer"`
	KeepsQuery bool   `json:"keeps_query"`
}

type adapter struct {
	Pattern     string      `json:"pattern"`
	Kind        string      `json:"kind"`
	URLContains string      `json:"url_contains"`
	Operations  []operation `json:"operations"`
	re          *regexp.Regexp
}

//go:embed rules.json
var rulesJSON []byte

var rules = func() (r struct {
	Roles map[string]struct {
		Page        bool   `json:"page"`
		Home        string `json:"home"`
		Desk        bool   `json:"desk"`
		VerifiesSSA bool   `json:"verifies_ssa"`
	} `json:"roles"`
	WaitingLimit   int         `json:"waiting_limit"`
	ExceptionLimit int         `json:"exception_limit"`
	GroupMin       int         `json:"group_min"`
	SnoozeChoices  [][2]string `json:"snooze_choices"`
	Adapters       []adapter   `json:"adapters"`
	ActivityDrawer string      `json:"activity_drawer"`
	activityDrawer *regexp.Regexp
}) {
	if err := json.Unmarshal(rulesJSON, &r); err != nil || len(r.Roles) == 0 || r.WaitingLimit <= 0 || len(r.Adapters) == 0 {
		panic(fmt.Sprintf("todaypage: the embedded rules are unreadable: %v", err))
	}
	for i := range r.Adapters {
		r.Adapters[i].re = regexp.MustCompile(r.Adapters[i].Pattern)
	}
	r.activityDrawer = regexp.MustCompile(r.ActivityDrawer)
	return r
}()

var zone = func() *time.Location {
	z, err := time.LoadLocation("Africa/Nairobi")
	if err != nil {
		panic("todaypage: " + err.Error())
	}
	return z
}()

// moneyKinds are the decisions whose row shows an amount, which Go hands on.
var moneyKinds = map[string]bool{"weekly_fund_approval": true, "weekly_receipt": true, "monthly_receipt": true}

// Service builds the page.
type Service struct {
	db    schooldirectory.Querier
	now   func() time.Time
	todos *todos.Service
}

// NewService wires the service to the database it reads.
func NewService(db schooldirectory.Querier, now func() time.Time) *Service {
	return &Service{db: db, now: now, todos: todos.NewService(db, now)}
}

// Build answers /today, or reports false for any other path or a reading
// it hands on.
func (s *Service) Build(ctx context.Context, p auth.Principal, path string, _ url.Values) (*screensv1.GetPageResponse, bool, error) {
	if path != Path {
		return nil, false, nil
	}
	role, known := rules.Roles[p.ActiveRole]
	if !known || !role.Page {
		return nil, true, pagegate.ErrNotAvailable
	}
	if role.Home != Path || !role.Desk || role.VerifiesSSA {
		return nil, false, nil
	}
	q, served, err := s.todos.HomeQueue(ctx, p)
	if err != nil || !served {
		return nil, served, err
	}
	today := s.now().In(zone)
	day := time.Date(today.Year(), today.Month(), today.Day(), 0, 0, 0, 0, time.UTC)
	snoozed, err := s.snoozed(ctx, p.UserID, day)
	if err != nil {
		return nil, true, err
	}
	var cleared int
	if err := s.db.QueryRow(ctx, `SELECT COUNT(*) FROM command_center_today_action
WHERE user_id = $1 AND (created_at AT TIME ZONE 'Africa/Nairobi')::date = $2::date`, p.UserID, day).Scan(&cleared); err != nil {
		return nil, true, fmt.Errorf("todaypage: counting what was cleared today: %w", err)
	}
	var waiting []todos.Row
	for _, row := range q.Rows {
		if snoozed[row.ID] {
			continue
		}
		if row.Priority == "critical" || row.StatusKey == "blocked" {
			return nil, false, nil // an exception, drawn as a list of its own
		}
		if row.Actionable {
			waiting = append(waiting, row)
		}
	}
	waiting, grouped := limit(waiting)
	if grouped {
		return nil, false, nil
	}
	table := &screensv1.PageTable{Columns: []*screensv1.PageColumn{{Label: "Item"}, {Label: "Kind"}, {Label: "Status"},
		{Label: "Due"}, {Label: "Actions", Numeric: true}}}
	for _, row := range waiting {
		if !row.Described {
			return nil, false, nil // its description is not written in Go
		}
		cells, money := rowCells(row)
		if money {
			return nil, false, nil
		}
		table.Rows = append(table.Rows, &screensv1.PageRow{Cells: cells})
	}
	if len(waiting) == 0 {
		table.Rows = []*screensv1.PageRow{{Cells: []*screensv1.PageCell{{Text: "Nothing waits on you right now."}}}}
	}
	tally := feeddom.El("div", "flex", " ", feeddom.El("span", "", "Cleared from Today: ", feeddom.El("strong", "", strconv.Itoa(cleared))), " ")
	if len(snoozed) > 0 {
		tally.Add(feeddom.El("span", "", strconv.Itoa(len(snoozed))+" snoozed"))
	}
	tally.Add(" ")
	blocks := feeddom.Walk(feeddom.El("div", "", tally), nil)
	blocks = append(blocks, &screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{Title: "Waiting on you"}}},
		&screensv1.PageBlock{Kind: &screensv1.PageBlock_Table{Table: table}})
	header := &screensv1.PageHeader{Eyebrow: today.Format("Monday, 02 January 2006"), Title: "Today", Description: deskDescription}
	return &screensv1.GetPageResponse{Header: header, Blocks: blocks, WebPath: Path}, true, nil
}

// snoozed is today_actions.snoozed_ids: the rows the reader put aside
// until a day still to come.
func (s *Service) snoozed(ctx context.Context, userID string, day time.Time) (map[string]bool, error) {
	rows, err := s.db.Query(ctx, `SELECT todo_id FROM command_center_todo_snooze WHERE user_id = $1 AND until > $2::date`, userID, day)
	if err != nil {
		return nil, fmt.Errorf("todaypage: reading the snoozes: %w", err)
	}
	defer rows.Close()
	out := map[string]bool{}
	for rows.Next() {
		var id string
		if err := rows.Scan(&id); err != nil {
			return nil, fmt.Errorf("todaypage: reading the snoozes: %w", err)
		}
		out[id] = true
	}
	return out, rows.Err()
}

// limit is todo_groups.limit_entries(waiting, WAITING_LIMIT), and whether a
// group of identical To-Dos would be among what it keeps.
func limit(rows []todos.Row) ([]todos.Row, bool) {
	key := func(r todos.Row) [3]string { return [3]string{r.Title, r.Category, r.Priority} }
	counts := map[[3]string]int{}
	for _, r := range rows {
		counts[key(r)]++
	}
	var out []todos.Row
	for _, r := range rows {
		if len(out) >= rules.WaitingLimit {
			break
		}
		if counts[key(r)] >= rules.GroupMin {
			return nil, true
		}
		out = append(out, r)
	}
	return out, false
}

// adapterFor is today_actions.adapter_for: the first adapter whose pattern
// the row's id matches (and whose link the row carries), with the record id.
func adapterFor(row todos.Row) (*adapter, string) {
	for i := range rules.Adapters {
		a := &rules.Adapters[i]
		m := a.re.FindStringSubmatch(row.ID)
		if m == nil {
			continue
		}
		if a.URLContains != "" && !strings.Contains(row.ActionURL, a.URLContains) {
			continue
		}
		return a, m[a.re.SubexpIndex("id")]
	}
	return nil, ""
}

// linkQuery is the coaching log's part of the row's link: its query's
// parameters in order, less "open", joined as parse_qs reads them.
func linkQuery(link string) string {
	u, err := url.Parse(link)
	if err != nil {
		return ""
	}
	var parts []string
	seen := map[string]bool{}
	for _, pair := range strings.Split(u.RawQuery, "&") {
		k, v, _ := strings.Cut(pair, "=")
		k, _ = url.QueryUnescape(strings.ReplaceAll(k, "+", " "))
		v, _ = url.QueryUnescape(strings.ReplaceAll(v, "+", " "))
		if k == "" || v == "" || k == "open" || seen[k] {
			continue
		}
		seen[k] = true
		parts = append(parts, k+"="+v)
	}
	return strings.Join(parts, "&")
}

func menuItem(label, href string, drawer bool) *screensv1.PageAction {
	return &screensv1.PageAction{Key: "menu", Label: label, Enabled: true, Href: href, Drawer: drawer}
}

// rowCells is partials/today/queue_row.html as the feed reads it, and
// whether the row is a money decision (handed on).
func rowCells(row todos.Row) ([]*screensv1.PageCell, bool) {
	a, record := adapterFor(row)
	var actions []*screensv1.PageAction
	operations := 0
	if a != nil {
		if moneyKinds[a.Kind] {
			return nil, true
		}
		for _, op := range a.Operations {
			operations++
			if op.Drawer == "" {
				continue // a one-press decision or a short form: no link to read
			}
			drawer := strings.ReplaceAll(op.Drawer, "{id}", record)
			if op.KeepsQuery {
				drawer += linkQuery(row.ActionURL)
			}
			actions = append(actions, menuItem(op.Label, drawer, true))
		}
	}
	if operations == 0 && rules.activityDrawer.MatchString(row.ActionURL) {
		label := row.ActionLabel
		if label == "" {
			label = "Open"
		}
		actions = append(actions, menuItem(label, row.ActionURL, true))
		operations = 1
	}
	open := row.ActionURL
	if open == "" {
		open = "/todos"
	}
	label := "Open"
	if operations == 0 && row.ActionLabel != "" {
		label = row.ActionLabel
	}
	actions = append(actions, menuItem(label, open, false))
	item := row.Title
	context := row.Linked
	if row.Description != "" {
		if context != "" {
			context += " · "
		}
		context += row.Description
	}
	if context != "" {
		item += " " + context
	}
	kind := row.Category
	if kind == "" {
		kind = "—"
	}
	status := row.StatusLabel
	if status == "" {
		status = "—"
	}
	if row.Priority == "critical" {
		status = "Critical " + status
	}
	due := row.DueLabel
	if due == "" || due == "—" {
		due = "—"
	}
	note := ""
	if len(rules.SnoozeChoices) > 0 {
		note = "Snooze"
	}
	return []*screensv1.PageCell{
		{Text: strings.Join(strings.Fields(item), " ")}, {Text: kind}, {Text: status}, {Text: due},
		{Text: note, Actions: actions},
	}, false
}
