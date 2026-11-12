package closedschools

// PyStrip is Python's str.strip() (see strip), for My Plan (internal/myplan),
// whose period filters are read the same way; PyInt is beside it
// (export_decisionlog.go).
func PyStrip(text string) string { return strip(text) }

// PyCollapse is the feed's reading of a text: its whitespace run together
// (see collapse).
func PyCollapse(text string) string { return collapse(text) }
