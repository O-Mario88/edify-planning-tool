// Package hrtoday is HR Today (/hr-today): the exception queue HR triages
// from, worked out from current workflow state, as the existing page draws
// it (apps.frontend.views.hr_today_views.hr_today_page over
// apps.hr.hr_exceptions, and pages/hr/hr_today.html) and the app's feed
// reads it. Nothing is stored; an item leaves the moment its cause clears.
//
// The doors, the registers each role may open, the queues' words, the review
// chain and the windows are exported to rules.json by
// `manage.py export_hr_today_rules`; apps/hr/test_hr_today_rules_export.py
// fails when the two differ.
package hrtoday

import (
	"context"
	_ "embed"
	"encoding/json"
	"fmt"
	"net/url"
	"slices"
	"sort"
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
const Path = "/hr-today"

//go:embed rules.json
var rulesJSON []byte

var rules = func() (r struct {
	Roles map[string]struct {
		Page  bool     `json:"page"`
		Opens []string `json:"opens"`
	} `json:"roles"`
	Groups []struct {
		Key, Label, Helper string
	} `json:"groups"`
	GoverningRoles         []string            `json:"governing_roles"`
	ReviewerRoleFor        map[string][]string `json:"reviewer_role_for"`
	LiveStates             []string            `json:"live_states"`
	PolicyAwaitingStatuses []string            `json:"policy_awaiting_statuses"`
	LeaveDecisionDays      int                 `json:"leave_decision_days"`
	ReviewOverdueDays      int                 `json:"review_overdue_days"`
	DeadlineHorizonDays    int                 `json:"deadline_horizon_days"`
	VisiblePerQueue        int                 `json:"visible_per_queue"`
	FoldFrom               int                 `json:"fold_from"`
}) {
	if err := json.Unmarshal(rulesJSON, &r); err != nil || len(r.Roles) == 0 || len(r.Groups) != 4 || r.VisiblePerQueue == 0 {
		panic(fmt.Sprintf("hrtoday: the embedded rules are unreadable: %v", err))
	}
	return r
}()

var zone = func() *time.Location {
	z, err := time.LoadLocation("Africa/Kampala")
	if err != nil {
		panic(fmt.Sprintf("hrtoday: loading the zone: %v", err))
	}
	return z
}()

// Service answers the page from the existing database.
type Service struct {
	db  schooldirectory.Querier
	now func() time.Time
}

// NewService is the page over db.
func NewService(db schooldirectory.Querier, now func() time.Time) *Service {
	return &Service{db: db, now: now}
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
	now := s.now()
	local := now.In(zone)
	today := time.Date(local.Year(), local.Month(), local.Day(), 0, 0, 0, 0, time.UTC)
	reach, args, _, err := hrregister.PeopleReachProfiles(ctx, s.db, p, nil)
	if err != nil {
		return nil, true, fmt.Errorf("hrtoday: resolving the reader's reach: %w", err)
	}
	scoped := "sp.deleted_at IS NULL AND u.deleted_at IS NULL AND " + reach
	rows, err := s.db.Query(ctx, `SELECT sp.id FROM staff_profile sp INNER JOIN "user" u ON (sp.user_id = u.id) WHERE `+scoped, args...)
	if err != nil {
		return nil, true, fmt.Errorf("hrtoday: reading the scope: %w", err)
	}
	ids, err := pgx.CollectRows(rows, pgx.RowTo[string])
	if err != nil {
		return nil, true, fmt.Errorf("hrtoday: reading the scope: %w", err)
	}
	fy := schooldirectory.OperationalFY(now)
	items, err := s.exceptions(ctx, p, builder{db: s.db, ids: ids, scoped: scoped, args: args, today: today, fy: fy}, now)
	if err != nil {
		return nil, true, err
	}
	label, none, err := hrregister.PeopleReachLabel(ctx, s.db, p)
	if err != nil {
		return nil, true, err
	}
	warning := ""
	switch {
	case none:
		warning = "Your account has no People record, so there is no country or team to report on. Ask an administrator to create your staff profile."
	case len(ids) == 0:
		warning = "No staff records match " + label + "."
	}
	return page(role.Opens, items, warning, query), true, nil
}

// exceptions is build_hr_exceptions: every builder in its order, the closed
// conversations unlinked, worst first.
func (s *Service) exceptions(ctx context.Context, p auth.Principal, b builder, now time.Time) ([]exception, error) {
	items := []exception{}
	add := func(found []exception, err error) error {
		items = append(items, found...)
		return err
	}
	if len(b.ids) > 0 {
		for _, run := range []func(context.Context) ([]exception, error){
			b.escalatedLeave, b.pdAwaitingHR,
			func(ctx context.Context) ([]exception, error) { return b.probation(ctx, true) },
			b.leaveOverdue, b.reviewsOverdue, b.leaveWithoutCover, b.compliance,
			func(ctx context.Context) ([]exception, error) { return b.probation(ctx, false) },
			b.withoutSupervisor, b.agreements, b.departed,
		} {
			if err := add(run(ctx)); err != nil {
				return nil, err
			}
		}
	}
	if slices.Contains(rules.GoverningRoles, p.ActiveRole) {
		if err := add(policiesAwaiting(ctx, s.db)); err != nil {
			return nil, err
		}
		if err := add(usersWithoutRecord(ctx, s.db)); err != nil {
			return nil, err
		}
		if err := add(policyReviews(ctx, s.db, b.today)); err != nil {
			return nil, err
		}
	}
	if err := unlinkConversations(ctx, s.db, p, b.fy, now, items); err != nil {
		return nil, err
	}
	sort.SliceStable(items, func(i, j int) bool {
		a, c := items[i], items[j]
		sa, sc := severityOrder[a.severity], severityOrder[c.severity]
		if sa != sc {
			return sa < sc
		}
		if a.sortA != c.sortA {
			return a.sortA < c.sortA
		}
		return a.sortB < c.sortB
	})
	return items, nil
}

// row is a queue row: one exception, or several alike folded into one.
type row struct {
	exception
	people []exception
}

// fold is _fold_identical: from FOLD_FROM alike rows (what, why, when and how
// serious), one row naming everyone it concerns, in the first one's place.
func fold(items []exception) []row {
	type key struct{ title, detail, due, severity string }
	order, alike := []key{}, map[key][]exception{}
	for _, x := range items {
		k := key{x.title, x.detail, x.due, x.severity}
		if _, seen := alike[k]; !seen {
			order = append(order, k)
		}
		alike[k] = append(alike[k], x)
	}
	out := []row{}
	for _, k := range order {
		same := alike[k]
		if len(same) < rules.FoldFrom {
			for _, x := range same {
				out = append(out, row{exception: x})
			}
			continue
		}
		out = append(out, row{exception: same[0], people: same})
	}
	return out
}

// opens is the template's |can_open over the registers the role may open.
func opens(allowed []string, link string) bool {
	if link == "" {
		return false
	}
	for _, prefix := range allowed {
		if strings.HasPrefix(link, prefix) {
			return true
		}
	}
	return false
}

// page is pages/hr/hr_today.html as the feed reads it.
func page(allowed []string, items []exception, warning string, query url.Values) *screensv1.GetPageResponse {
	header := &screensv1.PageHeader{Eyebrow: "People", Title: "HR Today",
		Description: "Everything open that needs a person, worked out from live records — not a task list anyone maintains. An item disappears the moment the thing that caused it is resolved."}
	blocks := []*screensv1.PageBlock{}
	if warning != "" {
		blocks = append(blocks, &screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{
			Items: []*screensv1.PagePanelItem{{Kind: &screensv1.PagePanelItem_Text{Text: warning}}}}}})
	}
	byGroup := map[string][]exception{}
	for _, x := range items {
		byGroup[x.group] = append(byGroup[x.group], x)
	}
	metrics := []*screensv1.PageMetric{}
	for _, g := range rules.Groups {
		metrics = append(metrics, &screensv1.PageMetric{Label: g.Label, Value: strconv.Itoa(len(byGroup[g.Key])), Note: g.Helper, Href: "#queue-" + g.Key})
	}
	blocks = append(blocks, &screensv1.PageBlock{Kind: &screensv1.PageBlock_Strip{Strip: &screensv1.PageStrip{Title: "Performance overview", Metrics: metrics}}})
	for i, g := range rules.Groups {
		blocks = append(blocks, queue(allowed, g.Label, byGroup[g.Key], i+1, query)...)
	}
	return &screensv1.GetPageResponse{Header: header, Blocks: blocks, WebPath: Path}
}

// queue is one queue's section: its heading and count line, then its worst
// rows and what was left out.
func queue(allowed []string, label string, items []exception, n int, query url.Values) []*screensv1.PageBlock {
	if len(items) == 0 {
		return []*screensv1.PageBlock{{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{Title: label, Subtitle: "Nothing open."}}}}
	}
	rows := fold(items)
	shownRows := rows[:min(rules.VisiblePerQueue, len(rows))]
	shown := 0
	for _, r := range shownRows {
		shown += max(1, len(r.people))
	}
	overflow := max(0, len(items)-shown)
	line := strconv.Itoa(len(items)) + " open"
	switch {
	case overflow > 0:
		line += " — showing the " + strconv.Itoa(len(shownRows)) + " most urgent"
	case len(rows) < len(items):
		line += " — the same exception for several people is one row"
	}
	blocks := []*screensv1.PageBlock{{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{Title: label,
		Items: []*screensv1.PagePanelItem{{Kind: &screensv1.PagePanelItem_Text{Text: line}}}}}}}
	t := &screensv1.PageTable{Columns: []*screensv1.PageColumn{{Label: "What"}, {Label: "Who"}, {Label: "When"}, {Label: "Action", Numeric: true}}}
	param := "group_items_page" + strconv.Itoa(n)
	number, pages := closedschools.PageOf(query.Get(param), len(shownRows), 50)
	for _, r := range shownRows[(number-1)*50 : min(number*50, len(shownRows))] {
		t.Rows = append(t.Rows, queueRow(allowed, r))
	}
	blocks = append(blocks, &screensv1.PageBlock{Kind: &screensv1.PageBlock_Table{Table: t}})
	if pages > 1 {
		blocks = append(blocks, closedschools.PagerPanel(param, number, pages, len(shownRows), 50, query, nil))
	}
	if overflow > 0 {
		blocks = append(blocks, &screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{
			Items: []*screensv1.PagePanelItem{{Kind: &screensv1.PagePanelItem_Text{Text: strconv.Itoa(overflow) +
				" more in this queue. Clear these first — each one links straight to the record."}}}}}})
	}
	return blocks
}

func queueRow(allowed []string, r row) *screensv1.PageRow {
	what := &screensv1.PageCell{Text: closedschools.Collapse(r.title + " " + r.detail)}
	who := &screensv1.PageCell{Text: "—"}
	action := &screensv1.PageCell{Text: "—"}
	switch {
	case len(r.people) > 0:
		names := []string{strconv.Itoa(len(r.people)) + " people"}
		for _, x := range r.people {
			name := x.person
			if name == "" {
				name = "Unnamed"
			}
			names = append(names, name)
			if who.Href == "" && opens(allowed, x.url) {
				who.Href = x.url
			}
		}
		who.Text = closedschools.Collapse(strings.Join(names, " "))
	default:
		if r.person != "" {
			who.Text = closedschools.Collapse(r.person)
		}
		if opens(allowed, r.url) {
			action = &screensv1.PageCell{Text: "Open", Href: r.url}
		}
	}
	when := r.due
	if when == "" {
		when = r.severity
	}
	tone := "neutral"
	switch r.severity {
	case "critical":
		tone = "danger"
	case "high":
		tone = "warning"
	}
	return &screensv1.PageRow{Cells: []*screensv1.PageCell{what, who, {Text: djangoTitle(when), Tone: tone}, action}}
}

// djangoTitle is |title: str.title(), then a capital after a digit lowered
// ("2Nd" back to "2nd").
func djangoTitle(s string) string {
	r := []rune(pyTitle(s))
	for i := 1; i < len(r); i++ {
		if r[i-1] >= '0' && r[i-1] <= '9' && r[i] >= 'A' && r[i] <= 'Z' {
			r[i] += 'a' - 'A'
		}
	}
	return string(r)
}
