package planningoversight

import (
	"fmt"
	"net/url"
	"slices"
	"sort"
	"strconv"
	"strings"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/clusterpage"
)

// The four tables page fifty rows at a time ({% paginate group.items
// group.page_param|add:"-cv" %} and components/table_pager.html). The one
// panel the team lens draws is always the first group, g1_page.

// streamPageKeys are each table's page key suffixes, in table order.
var streamPageKeys = [4]string{"-cv", "-kv", "-cm", "-pt"}

const panelPageParam = "g1_page"

// pageOf is {% paginate %} over total rows: the page asked for, clamped to
// the pages there are, and its window [start, end).
func pageOf(query url.Values, param string, total int) (number, pages, start, end int) {
	pages = max(1, (total+tablePageSize-1)/tablePageSize)
	number = 1
	if raw := query.Get(param); raw != "" {
		if n, ok := clusterpage.PyInt(raw); ok {
			number = max(1, n)
		}
	}
	number = min(number, pages)
	start = (number - 1) * tablePageSize
	return number, pages, start, min(start+tablePageSize, total)
}

// carried is {% pager_query param %}: every query value the page was
// opened with except the table's own page, in key order (the order the
// gateway hands the existing application its query in).
func carried(query url.Values, param string) string {
	keys := []string{}
	for key, values := range query {
		if key != param && len(values) > 0 && values[0] != "" {
			keys = append(keys, key)
		}
	}
	sort.Strings(keys)
	out := strings.Builder{}
	for _, key := range keys {
		out.WriteString(url.QueryEscape(key) + "=" + url.QueryEscape(query.Get(key)) + "&")
	}
	return out.String()
}

// pager is components/table_pager.html as the feed reads it.
func pager(number, pages, total, shown int, query url.Values, param string) *screensv1.PagePager {
	first := (number-1)*tablePageSize + 1
	p := &screensv1.PagePager{Summary: fmt.Sprintf("Showing %d–%d of %d", first, first+shown-1, total)}
	href := func(page int) string { return "?" + carried(query, param) + param + "=" + strconv.Itoa(page) }
	if number > 1 {
		p.Pages = append(p.Pages, &screensv1.PagePagerPage{Label: "Prev", Href: href(number - 1)})
	}
	for _, n := range pageWindow(number, pages) {
		switch n {
		case 0:
			p.Pages = append(p.Pages, &screensv1.PagePagerPage{Label: "…"})
		case number:
			p.Pages = append(p.Pages, &screensv1.PagePagerPage{Label: strconv.Itoa(n), Current: true})
		default:
			p.Pages = append(p.Pages, &screensv1.PagePagerPage{Label: strconv.Itoa(n), Href: href(n)})
		}
	}
	if number < pages {
		p.Pages = append(p.Pages, &screensv1.PagePagerPage{Label: "Next", Href: href(number + 1)})
	}
	return p
}

// pageWindow is pagination.make_pagination_window(current, pages,
// window_size=1): the page numbers shown, 0 for a gap.
func pageWindow(current, pages int) []int {
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
