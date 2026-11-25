package clusterpage

import "testing"

// A contact cell that starts like a formula is quoted, but a phone number's
// leading + or - is not (clusters.services._spreadsheet_text).
func TestContactCellsAreQuotedAsTheExistingExportQuotesThem(t *testing.T) {
	for in, want := range map[string]string{
		"+256 772 000 111": "+256 772 000 111", "(0414) 123-456": "(0414) 123-456", "-1": "-1",
		"+call me": "'+call me", "=HYPERLINK(1)": "'=HYPERLINK(1)", "@home": "'@home", "  =x": "'  =x",
		"Plot 4": "Plot 4", "": "", "   ": "   ",
	} {
		if got := contactText(in); got != want {
			t.Errorf("%q: %q, want %q", in, got, want)
		}
	}
	if _, ok := NewService(nil, nil).SchoolsExportRoute("/clusters/c1/schools/export"); !ok {
		t.Error("the export is not routed")
	}
	if _, ok := NewService(nil, nil).SchoolsExportRoute("/clusters/c1/profile"); ok {
		t.Error("the profile is routed as the export")
	}
}
