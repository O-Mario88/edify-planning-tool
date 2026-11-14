package iapages

import (
	"net/url"
	"slices"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pageheader"
)

// exportActions are a queue's header buttons: its Export for a reader who
// may export (partials/ia/export_button.html), the queue as filtered on
// screen without its page ({% querystring export='xlsx' page=None %}),
// read by the feed as a download.
func exportActions(p auth.Principal, path string, query url.Values) []*screensv1.PageAction {
	if !slices.Contains(rules.ExportRoles, p.ActiveRole) {
		return nil
	}
	kept := url.Values{}
	for name, values := range query {
		if name != "page" {
			kept[name] = values
		}
	}
	return []*screensv1.PageAction{pageheader.Download("Export", pageheader.QueryHref(path, kept, rules.QueryKeysNotPassed, "export", "xlsx"))}
}
