package targetdistribution

import (
	"fmt"
	"math/big"
	"net/url"
	"slices"
	"strconv"
	"strings"
	"unicode"
	"unicode/utf8"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/allocations"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/feeddom"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schoolprofile"
)

// pageSize is TABLE_PAGE_SIZE.
const pageSize = 50

// selection is the master table's filters as the view reads them.
type selection struct {
	q, tab, priority, portfolio, status, page string
	// query is the ask as it came, for the pager's links.
	query url.Values
	// role is the reader's door: who confirms and who distributes.
	role door
}

// selectionOf reads the ask; any key the view does not read is handed on.
func selectionOf(query url.Values) (selection, error) {
	known := []string{"fy", "q", "carry_q", "tab", "priority", "portfolio", "status", "page"}
	for key, values := range query {
		if !slices.Contains(known, key) && strings.Join(values, "") != "" {
			return selection{}, fmt.Errorf("the query %q: %w", key, errPassOn)
		}
	}
	first := func(key string) string { return query.Get(key) }
	q := first("q")
	if q == "" {
		q = first("carry_q")
	}
	tab := first("tab")
	if tab == "" {
		tab = "all"
	}
	sel := selection{q: strings.TrimSpace(q), tab: strings.TrimSpace(tab), priority: strings.TrimSpace(first("priority")),
		portfolio: strings.TrimSpace(first("portfolio")), status: strings.TrimSpace(first("status")), page: first("page"), query: query}
	// The search is matched case-folded; Go folds only ASCII as Python does.
	if strings.IndexFunc(sel.q, func(r rune) bool { return r > unicode.MaxASCII }) >= 0 {
		return selection{}, fmt.Errorf("a search beyond ASCII: %w", errPassOn)
	}
	return sel, nil
}

// figure is floatformat:"-2"|intcomma.
func figure(r *big.Rat) string {
	return intcomma(allocations.FloatFormat(r, -2))
}

// intcomma puts thousands commas in a number's whole part.
func intcomma(s string) string {
	whole, rest := s, ""
	if i := strings.IndexByte(s, '.'); i >= 0 {
		whole, rest = s[:i], s[i:]
	}
	sign := ""
	if strings.HasPrefix(whole, "-") {
		sign, whole = "-", whole[1:]
	}
	for i := len(whole) - 3; i > 0; i -= 3 {
		whole = whole[:i] + "," + whole[i:]
	}
	return sign + whole + rest
}

// orDash is a figure, or "—" for none.
func orDash(r *big.Rat) string {
	if r == nil {
		return "—"
	}
	return figure(r)
}

// truncate is truncatechars:n.
func truncate(s string, n int) string {
	if utf8.RuneCountInString(s) <= n {
		return s
	}
	return string([]rune(s)[:n-1]) + "…"
}

func plural(n int, word, suffix string) string {
	if n == 1 {
		return word
	}
	return word + suffix
}

func text(s string) *screensv1.PagePanelItem {
	return &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Text{Text: s}}
}

func linksItem(ls ...*screensv1.PageLink) *screensv1.PagePanelItem {
	return &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Links{Links: &screensv1.PageLinks{Links: ls}}}
}

func panel(title string, items ...*screensv1.PagePanelItem) *screensv1.PageBlock {
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{Title: title, Items: items}}}
}

// metric is one KPI as components/context_metrics.html draws it, read by the
// feed: the brief of the line under the figure, the whole line when the
// brief differs.
func metric(label, value, helper string) *screensv1.PageMetric {
	m := &screensv1.PageMetric{Label: label, Value: value, Helper: schoolprofile.BriefHelper(helper)}
	if m.Helper != helper {
		m.Note = helper
	}
	return m
}

func strip(metrics ...*screensv1.PageMetric) *screensv1.PageBlock {
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Strip{Strip: &screensv1.PageStrip{Title: "Performance overview", Metrics: metrics}}}
}

// pyFloat is a float as the template prints it (str()).
func pyFloat(f float64) string { return allocations.Repr(f) }

// share is round(float(part / whole * 100), 1).
func share(part, whole *big.Rat) float64 {
	return pyRound1(new(big.Rat).Mul(new(big.Rat).Quo(part, whole), big.NewRat(100, 1)))
}

// masterBlocks is the view below the rail for a year with a master.
func (ws *workspace) masterBlocks(role door, sel selection) ([]*screensv1.PageBlock, error) {
	k := ws.k
	complete := k.fieldCascade > 0 && k.locked == k.fieldCascade
	blocks := []*screensv1.PageBlock{ws.command(complete)}

	distribution := "0"
	if k.distributable.Sign() != 0 {
		// max(0, min(100, …)): the first of equal figures, so 0 and 100 are whole.
		switch p := share(k.allocated, k.distributable); {
		case p <= 0:
		case p >= 100:
			distribution = "100"
		default:
			distribution = pyFloat(p)
		}
	}
	blocks = append(blocks, strip(metric("Remaining to distribute", figure(k.left),
		fmt.Sprintf("%d of %d milestones locked · %s%% allocated", k.locked, k.fieldCascade, distribution))))

	action, err := ws.action(role)
	if err != nil {
		return nil, err
	}
	blocks = append(blocks, action, ws.workflow(complete), ws.insights(complete))
	if role.Director && !ws.published {
		items := []*screensv1.PagePanelItem{text("Publication is the control point"),
			text("Once every source figure is confirmed, publish and lock the Uganda master so IA can distribute the approved field priorities.")}
		if k.needsConfirmation > 0 {
			items = append(items, text(fmt.Sprintf("%d %s remaining", k.needsConfirmation, plural(k.needsConfirmation, "confirmation", "s"))))
		}
		blocks = append(blocks, panel("", items...))
	}
	table, err := ws.table(sel)
	if err != nil {
		return nil, err
	}
	return append(blocks, table...), nil
}

// command is the distribution command's heading and its line.
func (ws *workspace) command(complete bool) *screensv1.PageBlock {
	k := ws.k
	title := "Move every field target to its next accountable owner."
	switch {
	case complete:
		title = "Uganda’s annual distribution is fully approved and locked."
	case !ws.published:
		title = "The master is waiting for final confirmation and publication."
	case k.left.Sign() == 0:
		title = "Every additive figure balances. Complete the remaining approvals."
	}
	copy := "Work the queue in order. Each milestone must reconcile to zero before it can lock for the financial year."
	switch {
	case !ws.published:
		copy = fmt.Sprintf("%d source %s must be resolved before IA can begin distribution.", k.needsConfirmation,
			plural(k.needsConfirmation, "figure", "s"))
	case complete:
		copy = fmt.Sprintf("All %d field-cascade milestones have a zero balance and an approved annual owner.", k.fieldCascade)
	}
	return panel(title, text("Distribution command"), text(copy))
}

// action is the command's button as the feed reads it. A button the page
// draws with its icon is not read; its line under it is.
func (ws *workspace) action(role door) (*screensv1.PageBlock, error) {
	rows := []*row{}
	for _, g := range ws.groups {
		rows = append(rows, g.rows...)
	}
	if role.Distributor {
		if !ws.published {
			return panel("", text("Awaiting publication"), text("Country Director confirmation is the current dependency.")), nil
		}
		var next, first *row
		for _, r := range rows {
			if r.method != fieldCascade || r.needsConfirmation {
				continue
			}
			if first == nil {
				first = r
			}
			if next == nil && r.status != "Distributed" {
				next = r
			}
		}
		if next == nil {
			next = first
		}
		if next == nil {
			return nil, fmt.Errorf("a published master with nothing to distribute: %w", errPassOn)
		}
		return panel("", text("Next: "+truncate(next.title, 54))), nil
	}
	if role.Director && !ws.published {
		for _, r := range rows {
			if r.needsConfirmation {
				return panel("", text("Continue confirmation"), text("Next: "+truncate(r.title, 54))), nil
			}
		}
	}
	return panel("", linksItem(&screensv1.PageLink{Text: "Review governed master", Href: "#master-milestones-title"}),
		text("Inspect source figures, ownership and allocation state.")), nil
}

// workflow is the four steps; a step done draws a tick, which the feed
// does not read, in place of its number.
func (ws *workspace) workflow(complete bool) *screensv1.PageBlock {
	k := ws.k
	items := []*screensv1.PagePanelItem{}
	step := func(done bool, n int, name, line string) {
		if !done {
			items = append(items, text(strconv.Itoa(n)))
		}
		items = append(items, text(name), text(line))
	}
	published := "Country Director gate"
	if ws.published {
		published = "Governed for FY" + ws.fy
	}
	step(k.needsConfirmation == 0, 1, "Source confirmed", fmt.Sprintf("%d unresolved", k.needsConfirmation))
	step(ws.published, 2, "Master published", published)
	step(complete, 3, "PL distribution", fmt.Sprintf("%d reconciled", k.balanced))
	step(complete, 4, "Annual targets locked", fmt.Sprintf("%d of %d", k.locked, k.fieldCascade))
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{Items: feeddom.Paired(items)}}}
}

// insights is the four KPIs under the command.
func (ws *workspace) insights(complete bool) *screensv1.PageBlock {
	k := ws.k
	delivery := "—"
	if k.verifiedPlan.Sign() != 0 {
		delivery = pyFloat(share(k.verifiedActual, k.verifiedPlan)) + "%"
	}
	mix := add(k.core, k.client)
	corePct, clientPct := "0", "0"
	if mix.Sign() != 0 {
		c := share(k.core, mix)
		corePct = pyFloat(c)
		clientPct = pyFloat(pyRound1(new(big.Rat).SetFloat64(100 - c)))
	}
	actionable := max(0, k.fieldCascade-k.locked)
	return strip(
		metric("Master scope", strconv.Itoa(k.milestones),
			fmt.Sprintf("milestones across %d groups Uganda additive target %s", k.groups, figure(k.total))),
		metric("Allocation health", figure(k.allocated),
			fmt.Sprintf("of %s distributable %d still actionable %s country/project owned", figure(k.distributable), actionable,
				figure(k.countryProject))),
		metric("Country delivery", delivery,
			fmt.Sprintf("%s verified of %s planned units %d of %d tracked milestones delivering", figure(k.verifiedActual),
				figure(k.verifiedPlan), k.delivering, k.tracking)),
		metric("Portfolio mix", figure(mix),
			fmt.Sprintf("Core %s · %s%% · Client %s · %s%%", figure(k.core), corePct, figure(k.client), clientPct)),
	)
}

// statusKey is a status as the filter names it.
func statusKey(status string) string { return strings.ReplaceAll(strings.ToLower(status), " ", "_") }

// matches is the view's filters on one row.
func (sel selection) matches(r *row) bool {
	switch {
	case sel.tab != "all" && r.method != sel.tab,
		sel.priority != "" && (!r.priority.hasCode || r.priority.code != sel.priority),
		sel.portfolio == "core" && r.core == nil,
		sel.portfolio == "client" && r.client == nil,
		sel.status != "" && statusKey(r.status) != sel.status:
		return false
	}
	if sel.q != "" {
		haystack := strings.ToLower(strings.Join([]string{r.priority.title, r.title, r.sourceText, r.activity}, " "))
		return strings.Contains(haystack, strings.ToLower(sel.q))
	}
	return true
}

// table is the master milestones: the heading, the filters, the method
// tabs, the active filters, the table and its pager.
func (ws *workspace) table(sel selection) ([]*screensv1.PageBlock, error) {
	rows := []*row{}
	for _, g := range ws.groups {
		for _, r := range g.rows {
			if sel.matches(r) {
				rows = append(rows, r)
			}
		}
	}
	blocks := []*screensv1.PageBlock{panel("Master milestones",
		text(fmt.Sprintf("%d database-backed records · Every row below is fetched from the governed FY%s master.", len(rows), ws.fy)))}

	groups := &screensv1.PageFilter{Name: "priority", Label: "Priority group", Value: sel.priority,
		Options: []*screensv1.PageFilterOption{{Value: "", Label: "All groups"}}}
	for _, g := range ws.groups {
		groups.Options = append(groups.Options, &screensv1.PageFilterOption{Value: g.code, Label: g.title})
	}
	options := func(name, label, value string, pairs ...[2]string) *screensv1.PageFilter {
		f := &screensv1.PageFilter{Name: name, Label: label, Value: value}
		for _, p := range pairs {
			f.Options = append(f.Options, &screensv1.PageFilterOption{Value: p[0], Label: p[1]})
		}
		return f
	}
	blocks = append(blocks, &screensv1.PageBlock{Kind: &screensv1.PageBlock_Filters{Filters: &screensv1.PageFilters{
		Filters: []*screensv1.PageFilter{groups,
			options("portfolio", "Portfolio", sel.portfolio, [2]string{"", "All portfolios"}, [2]string{"core", "Core targets"},
				[2]string{"client", "Client targets"}),
			options("status", "Status", sel.status, [2]string{"", "All statuses"}, [2]string{"published", "Published"},
				[2]string{"balance_open", "Balance open"}, [2]string{"ready_to_approve", "Ready to approve"},
				[2]string{"distributed", "Distributed"}, [2]string{"needs_confirmation", "Needs confirmation"})},
		Hidden: map[string]string{"fy": ws.fy, "tab": sel.tab, "carry_q": sel.q},
	}}})

	tabs := &screensv1.PageLinkTabs{}
	for _, t := range [][2]string{{"all", "All milestones"}, {fieldCascade, "Field cascade"}, {specialist, "Project / specialist"},
		{countryOwned, "Country owned"}, {nonScoreable, "Non-scoreable"}} {
		tabs.Tabs = append(tabs.Tabs, &screensv1.PageLinkTab{Label: t[1], Href: "?fy=" + ws.fy + "&tab=" + t[0], Active: sel.tab == t[0]})
	}
	blocks = append(blocks, &screensv1.PageBlock{Kind: &screensv1.PageBlock_LinkTabs{LinkTabs: tabs}})

	if chips := sel.chips(ws.fy); chips != nil {
		blocks = append(blocks, chips)
	}
	pageRows, first, pager, err := paginate(rows, sel)
	if err != nil {
		return nil, err
	}
	return append(blocks, ws.tableBlock(pageRows, first, sel), pager), nil
}

// chips are the active filters, or nil with none.
func (sel selection) chips(fy string) *screensv1.PageBlock {
	items := []*screensv1.PagePanelItem{text("Active filters")}
	if sel.q != "" {
		items = append(items, text("Search: "+truncate(sel.q, 32)))
	}
	if sel.priority != "" {
		items = append(items, text("Priority group"))
	}
	if sel.portfolio != "" {
		items = append(items, text(pyTitle(sel.portfolio)+" portfolio"))
	}
	if sel.status != "" {
		items = append(items, text(pyTitle(sel.status)))
	}
	if len(items) == 1 {
		return nil
	}
	items = append(items, linksItem(&screensv1.PageLink{Text: "Clear all", Href: "?fy=" + fy + "&tab=" + sel.tab}))
	return panel("", items...)
}

// pyTitle is Python's str.title().
func pyTitle(s string) string {
	var b strings.Builder
	prev := false
	for _, r := range s {
		if unicode.IsLetter(r) {
			if prev {
				b.WriteRune(unicode.ToLower(r))
			} else {
				b.WriteRune(unicode.ToTitle(r))
			}
			prev = true
			continue
		}
		b.WriteRune(r)
		prev = false
	}
	return b.String()
}
