package closedschools

import (
	"fmt"
	"net/url"
	"slices"
	"sort"
	"strconv"
	"strings"
	"time"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schoolprofile"
)

// pageParam is the table's own page in the query ({% paginate rows
// "closed_page" %}).
const pageParam = "closed_page"

// closure is one row of the archive: a closure and its school.
type closure struct {
	// SchoolID is the school's record id, SchoolCode its official School ID.
	SchoolID, SchoolCode, SchoolName string
	District, Owner                  string
	Effective                        time.Time
	Type, ReasonCategory, Reason     string
	Enrollment                       *int64
}

// figures are the three above the table, over every matching closure.
type figures struct {
	Closed, Active, EnrollmentRemoved int64
}

// impact is closure_analytics.country_summary for the operational year, as
// the page shows it. Budget is a whole number in digits.
type impact struct {
	Districts, Schools, Activities, Partners int64
	Budget, FY                               string
}

// view is everything the page is drawn from.
type view struct {
	doors       Doors
	summaryOnly bool
	// q is the search as the view reads it (stripped); query the page's
	// whole query, which the pager's links carry.
	q       string
	query   url.Values
	figures figures
	impact  *impact
	rows    []closure
}

// header is the page header as the feed reads it: "Clear search" is offered
// while a search is on.
func header(q string) *screensv1.PageHeader {
	h := &screensv1.PageHeader{
		Eyebrow:     "School lifecycle",
		Title:       "Closed Schools",
		Description: "Schools that have stopped operating. Their records, history and finance remain intact and readable here.",
	}
	if q != "" {
		label := collapse("Clear search“" + truncateChars(q, 24) + "”")
		h.Actions = append(h.Actions, &screensv1.PageAction{Key: slug(label), Label: label, Enabled: true, Href: Path})
	}
	return h
}

// fyLabel is ssa.year_comparison.fy_label: "FY 2025/26" for the year that
// ends in 2026.
func fyLabel(fy int) string {
	end := strconv.Itoa(fy)
	return fmt.Sprintf("FY %d/%s", fy-1, end[max(len(end)-2, 0):])
}

func strips(v view) []*screensv1.PageBlock {
	out := []*screensv1.PageBlock{schoolprofile.Strip("Performance overview", []schoolprofile.StripFigure{
		{Label: "Closed schools", Value: comma(v.figures.Closed)},
		{Label: "Still active", Value: comma(v.figures.Active)},
		{Label: "Enrolment removed", Value: comma(v.figures.EnrollmentRemoved), Helper: "Learners, at the moment each school closed"},
	})}
	if i := v.impact; i != nil {
		out = append(out, schoolprofile.Strip("Closure Impact", []schoolprofile.StripFigure{
			{Label: "Districts affected", Value: comma(i.Districts), Helper: comma(i.Schools) + " schools closed in " + i.FY},
			{Label: "Budget released", Value: "UGX " + thousands(i.Budget), Helper: "Planned money given back by the closures"},
			{Label: "Activities cancelled", Value: comma(i.Activities), Helper: "Planned work at the closed schools"},
			{Label: "Partner work withdrawn", Value: comma(i.Partners), Helper: "Hand-overs taken back from Partners"},
		}))
	}
	return out
}

func cell(text, href string) *screensv1.PageCell {
	return &screensv1.PageCell{Text: collapse(text), Href: href}
}

func orDash(text string) string {
	if text == "" {
		return "—"
	}
	return text
}

// row is one closure as the table writes it.
func row(c closure, d Doors) *screensv1.PageRow {
	profile := ""
	if d.Profiles && c.SchoolName != "" && strip(c.SchoolID) != "" {
		profile = "/schools/" + pyQuote(strip(c.SchoolID))
	}
	enrolment := "Not recorded"
	if c.Enrollment != nil && *c.Enrollment != 0 {
		enrolment = comma(*c.Enrollment)
	}
	return &screensv1.PageRow{Cells: []*screensv1.PageCell{
		// The School ID is filled in by the page's script, so the feed reads none.
		cell("", ""),
		cell(c.SchoolName+" "+c.SchoolCode, profile),
		cell(orDash(c.District), ""),
		cell(orDash(c.Owner), ""),
		cell(c.Effective.Format("2 Jan 2006"), ""),
		cell(display(rules.ClosureTypes, c.Type), ""),
		cell(display(rules.ClosureReasons, c.ReasonCategory)+" "+truncateChars(c.Reason, 90), ""),
		cell(enrolment, ""),
		cell("View", "/schools/"+c.SchoolCode),
	}}
}

// pageOf is {% paginate %} and paginate_rows: the page asked for (anything
// that is not a number is the first), held within the pages there are.
func pageOf(requested string, total int) (number, pages int) {
	pages = max(1, (total+rules.PageSize-1)/rules.PageSize)
	number = 1
	if requested != "" {
		if n, ok := pyInt(requested); ok {
			number = max(1, n)
		}
	}
	return min(number, pages), pages
}

// window is make_pagination_window(current, pages, window_size=1); 0 is the
// gap.
func window(current, pages int) []int {
	out := []int{}
	if pages <= 7 {
		for p := 1; p <= pages; p++ {
			out = append(out, p)
		}
		return out
	}
	out = append(out, 1)
	if current-1 > 2 {
		out = append(out, 0, current-1)
	} else {
		for p := 2; p < current; p++ {
			out = append(out, p)
		}
	}
	if current != 1 {
		out = append(out, current)
	}
	if current+1 < pages-1 {
		out = append(out, current+1, 0)
	} else {
		for p := current + 1; p < pages; p++ {
			out = append(out, p)
		}
	}
	if !slices.Contains(out, pages) {
		out = append(out, pages)
	}
	return out
}

// carried is {% pager_query %}: every other value of the page's query, as
// the feed passes it on (in key order, the keys it never passes left out).
func carried(query url.Values) string {
	keys := []string{}
	for key := range query {
		if key != pageParam && !in(rules.QueryKeysNotPassed, key) {
			keys = append(keys, key)
		}
	}
	sort.Strings(keys)
	parts := []string{}
	for _, key := range keys {
		for _, value := range query[key] {
			if value != "" {
				parts = append(parts, url.QueryEscape(key)+"="+url.QueryEscape(value))
			}
		}
	}
	if len(parts) == 0 {
		return ""
	}
	return strings.Join(parts, "&") + "&"
}

// pager is components/table_pager.html as the feed reads it. The archive's
// card has no heading, so the feed reads its table on its own and the pager
// under it as a plain panel: the summary line, the current page and each gap
// as text, and the runs of page links between them (Prev and Next with their
// arrows as captions).
func pager(number, pages, total int, query url.Values) *screensv1.PageBlock {
	first := (number-1)*rules.PageSize + 1
	last := min(number*rules.PageSize, total)
	text := func(t string) *screensv1.PagePanelItem {
		return &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Text{Text: t}}
	}
	items := []*screensv1.PagePanelItem{text(fmt.Sprintf("Showing %d–%d of %d", first, last, total))}
	base := "?" + carried(query) + pageParam + "="
	link := func(label, caption string, page int) {
		l := &screensv1.PageLink{Text: label, Href: base + strconv.Itoa(page), Caption: caption}
		if n := len(items); n > 0 && items[n-1].GetLinks() != nil {
			items[n-1].GetLinks().Links = append(items[n-1].GetLinks().Links, l)
			return
		}
		items = append(items, &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Links{Links: &screensv1.PageLinks{Links: []*screensv1.PageLink{l}}}})
	}
	if number > 1 {
		link("Prev", "‹", number-1)
	}
	for _, n := range window(number, pages) {
		switch {
		case n == 0:
			items = append(items, text("…"))
		case n == number:
			items = append(items, text(strconv.Itoa(n)))
		default:
			link(strconv.Itoa(n), "", n)
		}
	}
	if number < pages {
		link("Next", "›", number+1)
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{Items: items}}}
}

var columns = []string{"School ID", "School", "District", "Former owner", "Closed", "Type", "Reason", "Enrolment", ""}

// table is the archive's table, one page of its rows, and past one page the
// pager under it.
func table(v view) []*screensv1.PageBlock {
	t := &screensv1.PageTable{}
	for _, label := range columns {
		t.Columns = append(t.Columns, &screensv1.PageColumn{Label: label})
	}
	number, pages := pageOf(v.query.Get(pageParam), len(v.rows))
	for _, c := range v.rows[(number-1)*rules.PageSize : min(number*rules.PageSize, len(v.rows))] {
		t.Rows = append(t.Rows, row(c, v.doors))
	}
	out := []*screensv1.PageBlock{{Kind: &screensv1.PageBlock_Table{Table: t}}}
	if pages > 1 {
		out = append(out, pager(number, pages, len(v.rows), v.query))
	}
	return out
}

// emptyMessage is what the page says in the table's place: a reader of
// figures only is told so, a search that matched nothing is not an empty
// archive.
func emptyMessage(v view) string {
	switch {
	case v.summaryOnly:
		return "Your role reads the archive's figures and the year's closure impact above; the closed schools themselves are listed for the country and team roles."
	case v.q != "":
		return "No closed school name contains that text. Clear the search to see the whole archive."
	}
	return "When a school stops operating and is closed from its profile, it moves here — with its enrolment, history and finance intact."
}

// page is the whole answer.
func page(v view) *screensv1.GetPageResponse {
	if v.summaryOnly {
		// A summary-only reader reads the figures, never a school.
		v.rows = nil
	}
	blocks := strips(v)
	if len(v.rows) > 0 {
		blocks = append(blocks, table(v)...)
	} else {
		blocks = append(blocks, &screensv1.PageBlock{Kind: &screensv1.PageBlock_Empty{Empty: emptyMessage(v)}})
	}
	return &screensv1.GetPageResponse{Header: header(v.q), Blocks: blocks, WebPath: Path}
}
