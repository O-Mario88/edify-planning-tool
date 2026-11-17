package programmerollout

import (
	"fmt"
	"net/url"
	"slices"
	"strconv"
	"strings"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/clusterpage"
)

// weakPageParam is the weak-schools table's page ({% paginate ... "weak_page" %}).
const weakPageParam = "weak_page"

// panelPager is components/table_pager.html as the feed reads it apart from
// its table: the summary, then the controls in order, links side by side
// grouped, the current page and a gap as text.
func panelPager(number, pages, total, shown int, carried, param string) *screensv1.PageBlock {
	first := (number-1)*rules.PageSize + 1
	items := []*screensv1.PagePanelItem{panelText(fmt.Sprintf("Showing %d–%d of %d", first, first+shown-1, total), "")}
	var links *screensv1.PageLinks
	link := func(label, caption string, page int) {
		if links == nil {
			links = &screensv1.PageLinks{}
			items = append(items, &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Links{Links: links}})
		}
		links.Links = append(links.Links, &screensv1.PageLink{Text: label, Caption: caption, Href: "?" + carried + param + "=" + strconv.Itoa(page)})
	}
	if number > 1 {
		link("Prev", "‹", number-1)
	}
	for _, n := range pageWindow(number, pages) {
		switch n {
		case 0:
			items, links = append(items, panelText("…", "")), nil
		case number:
			items, links = append(items, panelText(strconv.Itoa(n), "")), nil
		default:
			link(strconv.Itoa(n), "", n)
		}
	}
	if number < pages {
		link("Next", "›", number+1)
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{Items: items}}}
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

func panelText(text, tone string) *screensv1.PagePanelItem {
	return &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Text{Text: text}, Tone: tone}
}

// carriedQuery is {% pager_query param %} when at most one other key is
// carried: Django keeps the request's own order, which url.Values does not,
// so more than one hands on (ok false).
func carriedQuery(query url.Values, param string) (string, bool) {
	parts := []string{}
	keys := 0
	for key, values := range query {
		if key == param {
			continue
		}
		carried := false
		for _, v := range values {
			if v != "" {
				parts = append(parts, url.QueryEscape(key)+"="+url.QueryEscape(v))
				carried = true
			}
		}
		if carried {
			keys++
		}
	}
	if keys > 1 {
		return "", false
	}
	if len(parts) == 0 {
		return "", true
	}
	return strings.Join(parts, "&") + "&", true
}

// pageOf is the {% paginate rows param %} tag over total rows: the page
// asked for, clamped to the pages there are, and the window [start, end).
func pageOf(query url.Values, param string, total int) (number, pages, start, end int) {
	pages = max(1, (total+rules.PageSize-1)/rules.PageSize)
	number = 1
	if raw := query.Get(param); raw != "" {
		if n, ok := clusterpage.PyInt(raw); ok {
			number = max(1, n)
		}
	}
	number = min(number, pages)
	start = (number - 1) * rules.PageSize
	return number, pages, start, min(start+rules.PageSize, total)
}
