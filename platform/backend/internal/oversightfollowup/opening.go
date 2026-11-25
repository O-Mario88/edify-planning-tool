// Package oversightfollowup draws what Team Oversight shows for a link to a
// planning follow-up.
package oversightfollowup

import (
	"net/url"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
)

// Opening is the placeholder team_planning.html draws above every lens when
// the page is opened from a follow-up (`{% if request.GET.followup %}`, the
// last value as Django reads it): the follow-up itself loads later from
// /planning-follow-ups/<id>, which the feed does not load, so it reads the
// placeholder's caption as a panel. Nil when there is no follow-up.
func Opening(query url.Values) *screensv1.PageBlock {
	values := query["followup"]
	if len(values) == 0 || values[len(values)-1] == "" {
		return nil
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{
		Items: []*screensv1.PagePanelItem{{Kind: &screensv1.PagePanelItem_Text{Text: "Opening the follow-up…"}}},
	}}}
}

// Above puts the placeholder, when there is one, above the page's blocks.
func Above(query url.Values, page *screensv1.GetPageResponse) *screensv1.GetPageResponse {
	if b := Opening(query); b != nil && page != nil {
		page.Blocks = append([]*screensv1.PageBlock{b}, page.Blocks...)
	}
	return page
}
