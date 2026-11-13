// Package pageheader builds the buttons of a page's header band as the
// feed reads them (apps/mobile_feed/page_blocks.py _header): every button of
// the controls slot, and beside it whatever is drawn as an action button
// (Planning's Export, Plan Field Event and Recent changes). Each page package
// decides which buttons its reader is offered; this package only gives them
// the feed's shape.
package pageheader

import (
	"net/url"
	"regexp"
	"slices"
	"strings"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
)

var notWord = regexp.MustCompile(`[^a-z0-9]+`)

// Key is the feed's key for a button: its label, lower case, every run of
// other characters one underscore, none at either end (_slug).
func Key(label string) string {
	return strings.Trim(notWord.ReplaceAllString(strings.ToLower(label), "_"), "_")
}

// Drawer is a button that opens its drawer (hx-get into #drawer-container).
func Drawer(label, href string, primary bool) *screensv1.PageAction {
	return &screensv1.PageAction{Key: Key(label), Label: label, Primary: primary, Enabled: true, Href: href, Drawer: true}
}

// Link is a link drawn as a button that opens another page.
func Link(label, href string) *screensv1.PageAction {
	return &screensv1.PageAction{Key: Key(label), Label: label, Enabled: true, Href: href}
}

// Download is a link drawn as a button that downloads a file (an export).
func Download(label, href string) *screensv1.PageAction {
	return &screensv1.PageAction{Key: Key(label), Label: label, Enabled: true, Href: href, Download: true}
}

// QueryHref is a link the page writes as a query alone ({% querystring
// key=value %}) as the feed gives it: on the page's path, with the page's
// own parameters (none the feed holds back) and key set to value.
func QueryHref(path string, query url.Values, notPassed []string, key, value string) string {
	out := url.Values{}
	for name, values := range query {
		if !slices.Contains(notPassed, name) {
			out[name] = slices.Clone(values)
		}
	}
	out.Set(key, value)
	return Href(path, out)
}

// Href is a header link as the feed gives it (_resolved): its parameters in
// name order, a name's values in their order, none blank, and no "?" when
// none is left.
func Href(path string, query url.Values) string {
	out := url.Values{}
	for name, values := range query {
		for _, v := range values {
			if v != "" {
				out.Add(name, v)
			}
		}
	}
	if len(out) == 0 {
		return path
	}
	return path + "?" + out.Encode()
}
