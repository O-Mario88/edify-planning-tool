package planningmonitor

import "testing"

func TestCoverageFiguresAreTallyFieldsOrItsProperties(t *testing.T) {
	headers := rules.CountryOversight.Page.CoverageExport.HierarchyHeaders
	if got, want := 5+len(coverageFigures)+1, len(headers); got != want {
		t.Fatalf("%d hierarchy cells for %d headings", got, want)
	}
	for _, name := range coverageFigures {
		if _, derived := coverageDerived[name]; derived {
			continue
		}
		if _, ok := cpoIdx[name]; !ok {
			t.Errorf("%s is neither a tally field nor a derived figure", name)
		}
	}
	if got := len(rules.CountryOversight.Page.CoverageExport.SchoolHeaders); got != 22 {
		t.Errorf("the school sheet writes 22 cells, its headings are %d", got)
	}
}
