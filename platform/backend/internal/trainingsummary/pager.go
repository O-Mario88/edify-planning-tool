package trainingsummary

import (
	"fmt"
	"net/url"
	"slices"
	"strconv"
	"strings"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/clusterpage"
)

// paginate is the {% paginate rows param %} tag over total rows: the window
// shown ([start, end)) and components/table_pager.html as the feed reads it,
// nil with one page.
func paginate(total int, query url.Values, param string) ([2]int, *screensv1.PagePager) {
	size := rules.Coverage.TablePageSize
	pages := max(1, (total+size-1)/size)
	number := 1
	if raw := query.Get(param); raw != "" {
		if n, ok := clusterpage.PyInt(raw); ok {
			number = max(1, n)
		}
	}
	number = min(number, pages)
	start := (number - 1) * size
	end := min(start+size, total)
	if pages <= 1 {
		return [2]int{start, end}, nil
	}
	return [2]int{start, end}, pager(number, pages, total, end-start, pagerQuery(query, param), param)
}

// pagerQuery is {% pager_query param %}: every other non-blank value, then "&".
func pagerQuery(query url.Values, param string) string {
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

// window is pagination.make_pagination_window(current, pages, window_size=1):
// the page numbers the pager shows, 0 for a gap.
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

func pager(number, pages, total, shown int, base, param string) *screensv1.PagePager {
	size := rules.Coverage.TablePageSize
	first := (number-1)*size + 1
	p := &screensv1.PagePager{Summary: fmt.Sprintf("Showing %d–%d of %d", first, first+shown-1, total)}
	href := func(page int) string { return "?" + base + param + "=" + strconv.Itoa(page) }
	if number > 1 {
		p.Pages = append(p.Pages, &screensv1.PagePagerPage{Label: "Prev", Href: href(number - 1)})
	}
	for _, n := range window(number, pages) {
		switch {
		case n == 0:
			p.Pages = append(p.Pages, &screensv1.PagePagerPage{Label: "…"})
		case n == number:
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
