// Package tablepager is the existing application's shared table pager: the
// {% paginate rows param %} tag (apps/core/templatetags/table_pagination.py
// over apps.core.pagination.paginate_rows) and components/table_pager.html
// as the app's feed reads it.
package tablepager

import (
	"fmt"
	"net/url"
	"slices"
	"strconv"
	"strings"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pynum"
)

// windowSize is the pages either side of the current one the pager shows
// (paginate_rows: make_pagination_window(window_size=1)).
const windowSize = 1

// Page is one page of a table: the rows shown ([Start, End)) and the pager,
// nil when every row fits on one page.
type Page struct {
	Start, End int
	Pager      *screensv1.PagePager
}

// Paginate is {% paginate %} over total rows, size a page, the page asked
// for in query[param]. A page that is not a number is the first; one out of
// range clamps to the nearest real page.
func Paginate(total, size int, query url.Values, param string) Page {
	size = max(1, size)
	pages := max(1, (total+size-1)/size)
	number := 1
	if n, ok := pynum.Int(query.Get(param)); ok {
		number = n
	}
	number = min(max(1, number), pages)
	start := (number - 1) * size
	out := Page{Start: start, End: min(start+size, total)}
	if pages > 1 {
		out.Pager = pager(number, pages, total, out, carried(query, param), param)
	}
	return out
}

// carried is {% pager_query param %}: every other non-blank value, then "&".
// The existing pager keeps the request's own order; the page's query reaches
// Go as a map, so the keys are written in key order.
func carried(query url.Values, param string) string {
	keys := make([]string, 0, len(query))
	for key := range query {
		keys = append(keys, key)
	}
	slices.Sort(keys)
	parts := []string{}
	for _, key := range keys {
		for _, value := range query[key] {
			if value != "" && key != param {
				parts = append(parts, url.QueryEscape(key)+"="+url.QueryEscape(value))
			}
		}
	}
	if len(parts) == 0 {
		return ""
	}
	return strings.Join(parts, "&") + "&"
}

// window is make_pagination_window: the page numbers the pager shows, 0 for
// a gap.
func window(current, pages int) []int {
	if pages <= 7 {
		out := make([]int, 0, pages)
		for p := 1; p <= pages; p++ {
			out = append(out, p)
		}
		return out
	}
	out := []int{1}
	if current-windowSize > 2 {
		out = append(out, 0)
		for p := current - windowSize; p < current; p++ {
			out = append(out, p)
		}
	} else {
		for p := 2; p < current; p++ {
			out = append(out, p)
		}
	}
	if current != 1 {
		out = append(out, current)
	}
	if current+windowSize < pages-1 {
		for p := current + 1; p <= current+windowSize; p++ {
			out = append(out, p)
		}
		out = append(out, 0)
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

func pager(number, pages, total int, shown Page, base, param string) *screensv1.PagePager {
	p := &screensv1.PagePager{Summary: fmt.Sprintf("Showing %d–%d of %d", shown.Start+1, shown.End, total)}
	href := func(page int) string { return "?" + base + param + "=" + strconv.Itoa(page) }
	if number > 1 {
		p.Pages = append(p.Pages, &screensv1.PagePagerPage{Label: "Prev", Href: href(number - 1)})
	}
	for _, n := range window(number, pages) {
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
