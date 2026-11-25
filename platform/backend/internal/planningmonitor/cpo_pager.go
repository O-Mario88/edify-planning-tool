package planningmonitor

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

// cpoPageOf is paginate_rows over total rows at the page the query asks
// for (int(request.GET.get(param) or 1), clamped): the page, the pages and
// its window [start, end).
func cpoPageOf(query url.Values, param string, total int) (number, pages, start, end int) {
	pages = max(1, (total+cpoRowsPerPage-1)/cpoRowsPerPage)
	number = 1
	if values := query[param]; len(values) > 0 && values[len(values)-1] != "" {
		if n, ok := clusterpage.PyInt(values[len(values)-1]); ok {
			number = n
		}
	}
	number = min(max(1, number), pages)
	start = (number - 1) * cpoRowsPerPage
	return number, pages, start, min(start+cpoRowsPerPage, total)
}

// cpoCarried is {% pager_query param %}: every query value but the page's
// own, in key order (the order the gateway hands the existing application
// its query in).
func cpoCarried(query url.Values, param string) string {
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

// cpoPager is components/table_pager.html as the feed reads it.
func cpoPager(number, pages, total, shown int, query url.Values, param string) *screensv1.PagePager {
	first := (number-1)*cpoRowsPerPage + 1
	p := &screensv1.PagePager{Summary: fmt.Sprintf("Showing %d–%d of %d", first, first+shown-1, total)}
	href := func(page int) string { return "?" + cpoCarried(query, param) + param + "=" + strconv.Itoa(page) }
	if number > 1 {
		p.Pages = append(p.Pages, &screensv1.PagePagerPage{Label: "Prev", Href: href(number - 1)})
	}
	for _, n := range cpoPageWindow(number, pages) {
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

// cpoPageWindow is the pager's page numbers, 0 for an ellipsis.
func cpoPageWindow(current, pages int) []int {
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
