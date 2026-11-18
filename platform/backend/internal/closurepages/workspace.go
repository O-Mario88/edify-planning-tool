package closurepages

import (
	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/decisionlog"
)

// The analytics workspace (analytics_render.render_analytics_section,
// pages/analytics/workspace.html) as the feed reads a section drawn in it:
// the title line, the role's tab rail, the decision frame, the section's own
// blocks and the provisional note.

// frame is a section's decision frame; its confidence sits outside what
// the feed reads.
type frame struct{ question, evidence, freshness string }

func text(t string) *screensv1.PagePanelItem {
	return &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Text{Text: t}}
}

func panel(items ...*screensv1.PagePanelItem) *screensv1.PageBlock {
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{Badges: []*screensv1.PageBadge{}, Items: items}}}
}

// workspaceFrame is the blocks above a section's panel.
func workspaceFrame(title string, strip *decisionlog.Strip, f frame) []*screensv1.PageBlock {
	blocks := []*screensv1.PageBlock{panel(text(title + " · Edify"))}
	if strip != nil {
		tabs := &screensv1.PageLinkTabs{Label: strip.Label, Scrolls: strip.Scrolls}
		for _, t := range strip.Tabs {
			tabs.Tabs = append(tabs.Tabs, &screensv1.PageLinkTab{Label: t.Label, Href: t.Href, Active: t.Active})
		}
		blocks = append(blocks, &screensv1.PageBlock{Kind: &screensv1.PageBlock_LinkTabs{LinkTabs: tabs}})
	}
	return append(blocks, panel(
		&screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Heading{Heading: "Data context " + f.freshness}},
		text("Decision frame"), text(f.question), text("Evidence"), text(f.evidence),
		text("Freshness"), text(f.freshness), text("Confidence")))
}

// workspacePage closes a section's blocks with the provisional note, under
// the section's title.
func workspacePage(title string, blocks []*screensv1.PageBlock, path string) *screensv1.GetPageResponse {
	blocks = append(blocks, panel(text("All data is provisional and subject to verification.")))
	header := &screensv1.PageHeader{Title: title, Badges: []*screensv1.PageBadge{}, Actions: []*screensv1.PageAction{}}
	return &screensv1.GetPageResponse{Header: header, Blocks: blocks, WebPath: path}
}
