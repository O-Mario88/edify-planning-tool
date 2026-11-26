package partneroversight

import (
	"net/url"
	"testing"
)

func TestTheExportIsAWorkbookOnlyWhenTheLinkAsksForOne(t *testing.T) {
	for raw, want := range map[string]bool{"format=xlsx": true, "format=Excel": true, "format=csv": false, "": false} {
		q, _ := url.ParseQuery(raw)
		if got := wantsExcel(q); got != want {
			t.Fatalf("%q: %v", raw, got)
		}
	}
	if len(exportHeader) != 23 || !budgetSchoolList("client_visits") || budgetSchoolList("visits") {
		t.Fatal("the export's columns and its five school lists")
	}
}
