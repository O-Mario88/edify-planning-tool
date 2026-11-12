package schoolprofile

import screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"

// PairedItems is the page reader's pairing (page_blocks._paired): a label
// line followed by its figure read as one data row, consecutive rows
// sharing a list. Escalations' opened rows are read through it.
func PairedItems(items []*screensv1.PagePanelItem) []*screensv1.PagePanelItem {
	return pairedItems(items)
}
