package closedschools

import (
	"fmt"
	"net/url"
	"sort"
	"strconv"
	"strings"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
)

// What a page drawn like the archive (internal/programmeschools) shares with
// it: the feed's reading of text, the "Clear search" button, and the shared
// table pager ({% paginate %} and components/table_pager.html) as the feed
// reads it under a card with no heading.

// SchoolCode is what the web writes for a {% school_code %} tag after a page
// renders (apps/core/school_identity_middleware.py, which the feed now runs
// too): the school's School ID, or "ID unavailable" for a school without one
// or a reference that matches no school.
func SchoolCode(code string) string {
	if code == "" {
		return "ID unavailable"
	}
	return code
}

// Collapse is the feed's reading of a text: its whitespace run together.
func Collapse(text string) string { return collapse(text) }

// StripSpace is Python's str.strip().
func StripSpace(text string) string { return strip(text) }

// Comma is |intcomma for a whole number.
func Comma(n int64) string { return comma(n) }

// LikeContains is Django's icontains pattern: the value escaped and wrapped.
func LikeContains(value string) string { return likeContains(value) }

// ClearSearch is the header's "Clear search" button while a search is on:
// the search cut to 24 characters as |truncatechars cuts it, between
// quotation marks, and a link back to the page without it.
func ClearSearch(q, href string) *screensv1.PageAction {
	label := collapse("Clear search“" + truncateChars(q, 24) + "”")
	return &screensv1.PageAction{Key: slug(label), Label: label, Enabled: true, Href: href}
}

// PageOf is {% paginate %} and paginate_rows: the page asked for (anything
// that is not a number is the first), held within the pages there are.
func PageOf(requested string, total, size int) (number, pages int) {
	pages = max(1, (total+size-1)/size)
	number = 1
	if requested != "" {
		if n, ok := pyInt(requested); ok {
			number = max(1, n)
		}
	}
	return min(number, pages), pages
}

// carriedQuery is {% pager_query %}: every other value of the page's query,
// as the feed passes it on (in key order, the keys it never passes left
// out).
func carriedQuery(param string, query url.Values, notPassed []string) string {
	keys := []string{}
	for key := range query {
		if key != param && !in(notPassed, key) {
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

// PagerPanel is components/table_pager.html as the feed reads it under a
// card with no heading. Such a card is not read as a table card, so the feed
// reads its table on its own and the pager as a plain panel: the summary
// line, the current page and each gap as text, and the runs of page links
// between them (Prev and Next with their arrows as captions). param is the
// table's page parameter and size its page size.
func PagerPanel(param string, number, pages, total, size int, query url.Values, notPassed []string) *screensv1.PageBlock {
	first := (number-1)*size + 1
	last := min(number*size, total)
	text := func(t string) *screensv1.PagePanelItem {
		return &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Text{Text: t}}
	}
	items := []*screensv1.PagePanelItem{text(fmt.Sprintf("Showing %d–%d of %d", first, last, total))}
	base := "?" + carriedQuery(param, query, notPassed) + param + "="
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
