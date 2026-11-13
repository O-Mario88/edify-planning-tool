package todos

import (
	"fmt"
	"sort"
	"strconv"
	"strings"
	"time"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
)

// todo is one row of the queue, as far as the page draws it: the builders'
// description, status words and due label are not drawn (the due column and
// the priority pill are hidden on a phone, and the feed reads what a phone
// shows).
type todo struct {
	Title, Category, Priority string
	StatusKey                 string
	Actionable                bool
	Linked                    string
	ActionLabel, ActionURL    string
	// Shape is the link's shape in rules.OpenLinks, which says whether the
	// reader's role may follow it; "" with no link.
	Shape string
	// Due is the row's _due_sort; nil is date.max.
	Due *time.Time
}

// queue is get_todos' answer: the rows a reader may follow, sorted, and
// their counts.
type queue struct {
	Rows                                          []todo
	Critical, DueToday, WaitingMe, Overdue, Total int
	Categories                                    [][2]string // (name, count), by name
}

// buildQueue is the end of _get_todos: rows whose link the role may not
// open are someone else's work; the rest sorted by priority, then due day
// (a stable sort, so equal rows keep their builders' order), and counted.
func buildQueue(role string, rows []todo) (queue, error) {
	kept := make([]todo, 0, len(rows))
	for _, t := range rows {
		if t.ActionURL != "" {
			gate, ok := rules.OpenLinks[t.Shape]
			if !ok {
				return queue{}, fmt.Errorf("todos: no gate for the link shape %q", t.Shape)
			}
			if !gate[role] {
				continue
			}
		}
		kept = append(kept, t)
	}
	order := func(p string) int {
		if n, ok := rules.PriorityOrder[p]; ok {
			return n
		}
		return 9
	}
	sort.SliceStable(kept, func(i, j int) bool {
		a, b := kept[i], kept[j]
		if order(a.Priority) != order(b.Priority) {
			return order(a.Priority) < order(b.Priority)
		}
		return dueBefore(a.Due, b.Due)
	})
	q := queue{Rows: kept, Total: len(kept)}
	cats := map[string]int{}
	for _, t := range kept {
		if t.Priority == "critical" {
			q.Critical++
		}
		switch t.StatusKey {
		case "due_today":
			q.DueToday++
		case "overdue":
			q.Overdue++
		}
		if t.Actionable && t.StatusKey != "blocked" {
			q.WaitingMe++
		}
		cats[t.Category]++
	}
	for name, n := range cats {
		q.Categories = append(q.Categories, [2]string{name, strconv.Itoa(n)})
	}
	sort.Slice(q.Categories, func(i, j int) bool { return q.Categories[i][0] < q.Categories[j][0] })
	return q, nil
}

// dueBefore orders two due days, no day (date.max) last.
func dueBefore(a, b *time.Time) bool {
	switch {
	case a == nil:
		return false
	case b == nil:
		return true
	}
	return a.Before(*b)
}

// collapse is the feed's text(): whitespace runs as one space, trimmed.
func collapse(s string) string { return strings.Join(strings.Fields(s), " ") }

// contextLine is todo_groups.context_line: a row's second line without the
// place its title already names.
func contextLine(title, linked string) string {
	place, rest, _ := strings.Cut(linked, "·")
	if p := strings.TrimSpace(place); p != "" && strings.Contains(title, p) {
		return strings.TrimSpace(rest)
	}
	return linked
}

// entry is group_identical's: a row on its own, or identical ones together.
type entry struct {
	rows  []todo // one row, or the group's rows
	group bool
}

// groupIdentical is todo_groups.group_identical: GroupMin or more rows with
// the same title, category and priority are one entry, where the first of
// them stood.
func groupIdentical(rows []todo) []entry {
	key := func(t todo) [3]string { return [3]string{t.Title, t.Category, t.Priority} }
	counts := map[[3]string]int{}
	for _, t := range rows {
		counts[key(t)]++
	}
	var out []entry
	at := map[[3]string]int{}
	for _, t := range rows {
		k := key(t)
		if counts[k] < rules.GroupMin {
			out = append(out, entry{rows: []todo{t}})
			continue
		}
		i, ok := at[k]
		if !ok {
			i = len(out)
			at[k] = i
			out = append(out, entry{group: true})
		}
		out[i].rows = append(out[i].rows, t)
	}
	return out
}

// listItem is partials/todos/row.html as the feed reads it.
func listItem(t todo) *screensv1.PageListItem {
	var lines []string
	if s := collapse(t.Title); s != "" {
		lines = append(lines, s)
	}
	if sub := contextLine(t.Title, t.Linked); sub != "" {
		if s := collapse(sub); s != "" {
			lines = append(lines, s)
		}
	}
	item := &screensv1.PageListItem{Lines: []string{}, Badges: []*screensv1.PageBadge{},
		Actions: []*screensv1.PageAction{}, Tone: categoryTone(t.Category)}
	if len(lines) > 0 {
		item.Title, item.Lines = lines[0], lines[1:]
	}
	if label := collapse(t.ActionLabel); t.ActionURL != "" && label != "" {
		item.Actions = append(item.Actions, &screensv1.PageAction{Key: "button", Label: label,
			Primary: t.Actionable, Enabled: true, Href: t.ActionURL})
	}
	return item
}

// categoryTone is the colour of the row's icon square for its category.
func categoryTone(category string) string {
	if tone, ok := rules.CategoryTones[category]; ok && category != "" {
		return tone
	}
	return rules.CategoryTones[""]
}

// rowKeys are the chips a row answers to (its x-show), "all" aside.
func rowKeys(category, priority string) map[string]string {
	keys := map[string]string{}
	if category != "all" {
		keys["cat"] = category
	}
	if priority != "all" {
		keys["prio"] = priority
	}
	return keys
}

// groupItem is a <details class="todo-group"> as the feed reads it.
func groupItem(e entry) *screensv1.PageListItem {
	first, n := e.rows[0], len(e.rows)
	linked := []string{}
	for _, t := range e.rows[:min(3, n)] {
		linked = append(linked, t.Linked)
	}
	caption := strconv.Itoa(n) + " · " + strings.Join(linked, ", ")
	if n > 3 {
		caption += " and " + strconv.Itoa(n-3) + " more"
	}
	spans := []string{}
	for _, s := range []string{collapse(first.Title), collapse(caption)} {
		if s != "" {
			spans = append(spans, s)
		}
	}
	item := &screensv1.PageListItem{Lines: []string{}, Badges: []*screensv1.PageBadge{}, Actions: []*screensv1.PageAction{},
		Count: strconv.Itoa(n), Keys: rowKeys(first.Category, first.Priority)}
	if len(spans) > 0 {
		item.Title, item.Lines = spans[0], spans[1:]
	}
	for _, t := range e.rows {
		item.Children = append(item.Children, listItem(t))
	}
	return item
}

var priorityChips = [][2]string{{"all", "All"}, {"critical", "Critical"}, {"high", "High"}, {"medium", "Medium"}, {"low", "Low"}}

// page is pages/todos/index.html as the feed reads it.
func page(q queue) *screensv1.GetPageResponse {
	open := strconv.Itoa(q.Total) + " open"
	header := &screensv1.PageHeader{Eyebrow: "My work", Title: "Action queue",
		Description: "Start with the highest-priority task; workflow state closes it automatically.",
		Badges:      []*screensv1.PageBadge{{Text: open, Tone: "plain"}}, Actions: []*screensv1.PageAction{}}
	if q.Total > 0 {
		header.Actions = append(header.Actions, &screensv1.PageAction{Key: "primary-action",
			Label: collapse("Do next: " + q.Rows[0].Title), Primary: true, Enabled: true, Href: q.Rows[0].ActionURL})
	}
	var blocks []*screensv1.PageBlock
	if q.Total > 0 {
		next := &screensv1.PageList{Title: "Do next", Count: open}
		for _, t := range q.Rows[:min(3, q.Total)] {
			item := listItem(t)
			item.Keys = map[string]string{}
			next.Items = append(next.Items, item)
		}
		blocks = append(blocks, &screensv1.PageBlock{Kind: &screensv1.PageBlock_List{List: next}})
	}
	metric := func(label string, n int, note string) *screensv1.PageMetric {
		return &screensv1.PageMetric{Label: label, Value: strconv.Itoa(n), Note: note}
	}
	blocks = append(blocks, &screensv1.PageBlock{Kind: &screensv1.PageBlock_Strip{Strip: &screensv1.PageStrip{
		Title: "Work requiring attention", Metrics: []*screensv1.PageMetric{
			metric("Critical", q.Critical, "Highest-priority work"),
			metric("Due today", q.DueToday, "Complete before day end"),
			metric("Overdue", q.Overdue, "Past the required date"),
			metric("Waiting on me", q.WaitingMe, "Your decision is next"),
		}}}})
	if q.Total == 0 {
		blocks = append(blocks, &screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{
			Badges: []*screensv1.PageBadge{}, Items: []*screensv1.PagePanelItem{
				{Kind: &screensv1.PagePanelItem_Text{Text: "You're all caught up"}},
				{Kind: &screensv1.PagePanelItem_Text{Text: "No actions require you right now. New To-Dos appear " +
					"automatically as work moves through the pipeline."}},
			}}}})
		return &screensv1.GetPageResponse{Header: header, Blocks: blocks, WebPath: Path}
	}
	cat := &screensv1.PageChips{Name: "cat", Label: "Category", Value: "all",
		Chips: []*screensv1.PageChip{{Value: "all", Label: "All Categories"}}}
	for _, c := range q.Categories {
		label := collapse(c[0])
		if label == "" {
			label = collapse(c[0] + " " + c[1])
		}
		cat.Chips = append(cat.Chips, &screensv1.PageChip{Value: c[0], Label: label, Count: c[1]})
	}
	prio := &screensv1.PageChips{Name: "prio", Label: "Priority", Value: "all"}
	for _, c := range priorityChips {
		prio.Chips = append(prio.Chips, &screensv1.PageChip{Value: c[0], Label: c[1]})
	}
	list := &screensv1.PageList{}
	for _, e := range groupIdentical(q.Rows) {
		if e.group {
			list.Items = append(list.Items, groupItem(e))
			continue
		}
		item := listItem(e.rows[0])
		item.Keys = rowKeys(e.rows[0].Category, e.rows[0].Priority)
		list.Items = append(list.Items, item)
	}
	blocks = append(blocks,
		&screensv1.PageBlock{Kind: &screensv1.PageBlock_Chips{Chips: cat}},
		&screensv1.PageBlock{Kind: &screensv1.PageBlock_Chips{Chips: prio}},
		&screensv1.PageBlock{Kind: &screensv1.PageBlock_List{List: list}})
	return &screensv1.GetPageResponse{Header: header, Blocks: blocks, WebPath: Path}
}
