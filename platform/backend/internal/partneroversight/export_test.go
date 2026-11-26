package partneroversight

import (
	"net/url"
	"testing"
)

func TestTheExportIsAWorkbookOnlyWhenTheLinkAsksForOne(t *testing.T) {
	for raw, want := range map[string]bool{"format=xlsx": true, "format=Excel": true, "format=csv": false, "": false,
		// The Export drawer's period fields ask for the workbook, even empty.
		"period_type=fy": true, "start_date=": true, "from_month=11&to_month=1": true, "format=csv&period_type=fy": false,
		"period=month&month=3": false} {
		q, _ := url.ParseQuery(raw)
		if got := wantsExcel(q); got != want {
			t.Fatalf("%q: %v", raw, got)
		}
	}
	if len(exportHeader) != 23 || !budgetSchoolList("client_visits") || budgetSchoolList("visits") {
		t.Fatal("the export's columns and its five school lists")
	}
}
