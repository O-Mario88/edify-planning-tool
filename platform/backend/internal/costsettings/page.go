package costsettings

import (
	"net/url"
	"sort"
	"strconv"
	"strings"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/clusterpage"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/costing"
)

// covered is one row of activity_cost_coverage.
type covered struct {
	name, activityType, delivery, intervention, profile string
	components                                          []string
	ready                                               bool
}

// coverageOf is activity_cost_coverage over a published card: each
// activity priced as one staff day in a primary district for one
// participant, with the costs linked to it. ok is false when an activity
// carries a costing profile the engine does not know (the existing page
// refuses the request).
func coverageOf(items []item, card pricedCard) ([]covered, bool) {
	out := make([]covered, 0, len(items))
	for _, it := range items {
		a := costing.Activity{
			ActivityType: it.workflowKind, DeliveryType: "staff", DistrictType: "primary",
			ExpectedParticipants: intp(1), Days: 1,
		}
		if it.profile != "" {
			resolved, known := rules.CostingProfiles[it.profile]
			if !known {
				return nil, false
			}
			a.ActivityType, a.CostingKind = resolved[0], resolved[1]
		}
		for _, r := range card.order {
			if r.itemID != nil && *r.itemID == it.id {
				a.LinkedRates = append(a.LinkedRates, [2]string{r.key, r.label})
			}
		}
		cost := costing.CostForActivity(a, card.rates)
		c := covered{
			name:         it.name,
			activityType: display(rules.ActivityTypes, &it.activityType),
			delivery:     display(rules.DeliveryMethods, &it.delivery),
			intervention: "Administrative / inherited",
			profile:      pyTitle(strings.ReplaceAll(it.profile, "_", " ")),
			components:   []string{},
			ready:        !cost.CostMissing,
		}
		if it.hasPrimary {
			c.intervention = display(rules.Interventions, it.primaryIntervention)
		}
		for _, line := range cost.Lines {
			// The existing page asks whether the full label is listed and
			// lists the label without its rate basis.
			if !contains(c.components, line.Label) {
				c.components = append(c.components, strings.SplitN(line.Label, " [Rate basis:", 2)[0])
			}
		}
		out = append(out, c)
	}
	return out, true
}

func contains(list []string, s string) bool {
	for _, x := range list {
		if x == s {
			return true
		}
	}
	return false
}

func intp(n int) *int { return &n }

type view struct {
	path, fy string
	years    []string
	role     role
	card     catalogue
	rates    []rate
	coverage []covered
	reviews  []review
	query    url.Values
}

func (v view) header() *screensv1.PageHeader {
	h := &screensv1.PageHeader{
		Eyebrow:     "Finance",
		Title:       titles[v.path],
		Description: "FY" + v.fy + " approved cost items for activity budgeting",
	}
	if v.role.Manage {
		h.Actions = []*screensv1.PageAction{{
			Key: "add_new_cost", Label: "Add new cost", Enabled: true,
			Href: "/cost-settings/add?fy=" + v.fy, Drawer: true,
		}}
	}
	return h
}

func panel(title, subtitle string, items ...*screensv1.PagePanelItem) *screensv1.PageBlock {
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{Title: title, Subtitle: subtitle, Items: items}}}
}

func text(s string) *screensv1.PagePanelItem {
	return &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Text{Text: s}}
}

func heading(s string) *screensv1.PagePanelItem {
	return &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Heading{Heading: s}}
}

func columns(labels ...string) []*screensv1.PageColumn {
	out := make([]*screensv1.PageColumn, len(labels))
	for i, l := range labels {
		numeric := strings.HasPrefix(l, "#")
		out[i] = &screensv1.PageColumn{Label: strings.TrimPrefix(l, "#"), Numeric: numeric}
	}
	return out
}

func cell(s string) *screensv1.PageCell { return &screensv1.PageCell{Text: collapse(s)} }

func table(cols []*screensv1.PageColumn, rows []*screensv1.PageRow) *screensv1.PageBlock {
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Table{Table: &screensv1.PageTable{Columns: cols, Rows: rows}}}
}

// blocks is the page as the feed reads it; ok is false when a table has
// more pages than the pager draws without a gap.
func (v view) blocks() ([]*screensv1.PageBlock, bool) {
	year := &screensv1.PageFilter{Name: "fy", Label: "Fiscal year", Value: v.fy}
	for _, y := range v.years {
		year.Options = append(year.Options, &screensv1.PageFilterOption{Value: y, Label: "FY" + y})
	}
	out := []*screensv1.PageBlock{
		{Kind: &screensv1.PageBlock_Filters{Filters: &screensv1.PageFilters{Filters: []*screensv1.PageFilter{year}}}},
		panel("Country operational cost",
			"Prices the planned activities in budgets and weekly requests. This is the cost submitted to the RVP for approval.",
			heading("Minimum viable cost"),
			text("Shown to staff while planning. The same planned quantities are automatically priced at country operational rates for funding. Unset minimum rates are flagged, never assumed.")),
	}
	if len(v.reviews) > 0 {
		out = append(out,
			panel("Cost review requests", "", text("Current approved/estimated amount remains unchanged until a governed correction is approved.")),
			table(columns("Activity", "Reason", "#Current", "#Proposed", "Status"), v.reviewRows()))
	}
	c := v.card
	out = append(out, panel("", "",
		text(collapse("Published Country Operational Rate Card: "+display(rules.KindLabels, &c.kind)+" · "+c.country+" FY"+c.fy+" v"+strconv.Itoa(c.version))),
		text("Version "+strconv.Itoa(c.version)+" · "+strconv.Itoa(len(v.rates))+" reusable rates · "+strconv.Itoa(len(v.coverage))+" governed activities covered"),
	))

	ordered := v.orderedRates()
	number, pages := pageOf(v.query.Get(ratesPageParam), len(ordered))
	if pages > 7 {
		return nil, false
	}
	start := (number - 1) * rules.TablePageSize
	rateRows := []*screensv1.PageRow{}
	for _, r := range ordered[start:min(start+rules.TablePageSize, len(ordered))] {
		rateRows = append(rateRows, v.rateRow(r))
	}
	out = append(out, table(columns("Item", "#Country operational (UGX)", "#Minimum viable (UGX)", ""), rateRows))
	if pages > 1 {
		out = append(out, v.pager(ratesPageParam, number, pages, len(ordered), len(rateRows)))
	}

	out = append(out, panel("All approved budget activities", "Activity coverage", text(strconv.Itoa(len(v.coverage))+" activities")))
	number, pages = pageOf(v.query.Get(coveragePageParam), len(v.coverage))
	if pages > 7 {
		return nil, false
	}
	start = (number - 1) * rules.TablePageSize
	coverRows := []*screensv1.PageRow{}
	for _, a := range v.coverage[start:min(start+rules.TablePageSize, len(v.coverage))] {
		status := "Needs rate setup"
		if a.ready {
			status = "Ready"
		}
		name := cell(a.name)
		name.Strong = true
		coverRows = append(coverRows, &screensv1.PageRow{Cells: []*screensv1.PageCell{
			name, cell(a.activityType), cell(a.delivery), cell(a.intervention),
			cell(a.profile + " " + strings.Join(a.components, ", ")), cell(status),
		}})
	}
	out = append(out, table(columns("Activity", "Type", "Delivery", "Intervention", "Cost recipe", "Status"), coverRows))
	if pages > 1 {
		out = append(out, v.pager(coveragePageParam, number, pages, len(v.coverage), len(coverRows)))
	}
	return out, true
}

func (v view) reviewRows() []*screensv1.PageRow {
	rows := []*screensv1.PageRow{}
	for _, r := range v.reviews {
		current := r.current
		reason := r.reason
		rows = append(rows, &screensv1.PageRow{Cells: []*screensv1.PageCell{
			cell(r.activity), cell(display(rules.ReviewReasons, &reason)),
			cell("UGX " + currency(&current)), cell("UGX " + currency(r.proposed)), cell(pyTitle(r.status)),
		}})
	}
	return rows
}

// orderedRates is the register's order: the registry's (activity rates,
// partner rates, session components, travel), then the costs added for one
// activity, each by label.
func (v view) orderedRates() []rate {
	order := map[string]int{}
	for i, key := range costing.CanonicalRateKeys() {
		order[key] = i
	}
	rank := func(key string) int {
		if i, ok := order[key]; ok {
			return i
		}
		return len(order)
	}
	out := append([]rate(nil), v.rates...)
	sort.SliceStable(out, func(i, j int) bool {
		ri, rj := rank(out[i].key), rank(out[j].key)
		if ri != rj {
			return ri < rj
		}
		return strings.ToLower(out[i].label) < strings.ToLower(out[j].label)
	})
	return out
}

func (v view) rateRow(r rate) *screensv1.PageRow {
	name := r.label + " " + r.unit
	if r.itemID != nil {
		linked := ""
		if r.itemName != nil {
			linked = *r.itemName
		}
		name += " · linked to " + linked
	}
	name += " Key: " + r.key + " · Ver: " + strconv.Itoa(r.version)
	minimum := "Not set"
	if r.minimum != nil {
		minimum = "UGX " + currency(r.minimum)
	}
	cost := r.unitCost
	action := &screensv1.PageCell{}
	if v.role.Manage {
		action.Actions = []*screensv1.PageAction{{
			Key: "button", Label: "Edit", Primary: true, Enabled: true,
			Href: "/cost-settings/row/" + r.key + "?mode=edit", Drawer: true,
		}}
	}
	return &screensv1.PageRow{Cells: []*screensv1.PageCell{cell(name), cell("UGX " + currency(&cost)), cell(minimum), action}}
}

// pageOf is {% paginate %}: a number from one up (the first for anything
// else), clamped to the pages there are.
func pageOf(requested string, total int) (number, pages int) {
	size := rules.TablePageSize
	pages = max(1, (total+size-1)/size)
	number = 1
	if n, ok := clusterpage.PyInt(requested); ok && requested != "" {
		number = max(1, n)
	}
	return min(number, pages), pages
}

// carried is {% pager_query %}: every query value but the table's own page,
// in the key order the gateway hands the existing application its query.
func (v view) carried(param string) string {
	keys := []string{}
	for key, values := range v.query {
		if key != param && len(values) > 0 && values[0] != "" {
			keys = append(keys, key)
		}
	}
	sort.Strings(keys)
	b := strings.Builder{}
	for _, key := range keys {
		b.WriteString(url.QueryEscape(key) + "=" + url.QueryEscape(v.query.Get(key)) + "&")
	}
	return b.String()
}

// pager is components/table_pager.html as the feed reads it when it stands
// apart from its table: the summary, then the controls in order, the links
// side by side grouped, the current page as its text. Seven pages or fewer
// show every number.
func (v view) pager(param string, number, pages, total, shown int) *screensv1.PageBlock {
	first := (number-1)*rules.TablePageSize + 1
	items := []*screensv1.PagePanelItem{text("Showing " + strconv.Itoa(first) + "–" + strconv.Itoa(first+shown-1) + " of " + strconv.Itoa(total))}
	var links *screensv1.PageLinks
	link := func(label, caption string, page int) {
		if links == nil {
			links = &screensv1.PageLinks{}
			items = append(items, &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Links{Links: links}})
		}
		links.Links = append(links.Links, &screensv1.PageLink{Text: label, Caption: caption, Href: "?" + v.carried(param) + param + "=" + strconv.Itoa(page)})
	}
	if number > 1 {
		link("Prev", "‹", number-1)
	}
	for n := 1; n <= pages; n++ {
		if n == number {
			items = append(items, text(strconv.Itoa(n)))
			links = nil
			continue
		}
		link(strconv.Itoa(n), "", n)
	}
	if number < pages {
		link("Next", "›", number+1)
	}
	return panel("", "", items...)
}
