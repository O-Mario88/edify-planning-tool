package teamperformance

import (
	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/feeddom"
)

// The page is written as the templates write it and read into blocks by
// the feed's own rules: internal/feeddom, shared with the other pages Go
// builds from card templates.

type node = feeddom.Node

func el(tag, class string, children ...any) *node { return feeddom.El(tag, class, children...) }

func preBlock(b *screensv1.PageBlock) *node { return feeddom.PreBlock(b) }

func walk(n *node, out []*screensv1.PageBlock) []*screensv1.PageBlock { return feeddom.Walk(n, out) }

func chartOf(holder *node) *screensv1.PageChart { return feeddom.ChartOf(holder) }

func readPanel(n *node) *screensv1.PagePanel { return feeddom.ReadPanel(n) }

func panelItems(n *node, skip map[*node]bool, out []*screensv1.PagePanelItem) []*screensv1.PagePanelItem {
	return feeddom.PanelItems(n, skip, out)
}

func plainText(item *screensv1.PagePanelItem) (string, bool) { return feeddom.PlainText(item) }
