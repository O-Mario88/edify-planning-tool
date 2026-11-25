package planningoversight

import (
	"net/url"
	"testing"
)

func TestPlanExportReadsTheFormatAndFiltersAsTheView(t *testing.T) {
	for query, want := range map[string]bool{
		"": false, "format=csv": false, "format=XLSX": true, "format=excel": true,
		"from_month=10": true, "period_type=fy&format=csv": false,
	} {
		q, _ := url.ParseQuery(query)
		if got := wantsExcel(q); got != want {
			t.Errorf("wantsExcel(%q) = %v, want %v", query, got, want)
		}
	}
	for query, want := range map[string]bool{
		"": false, "status=completed": false, "activity_type=planned": false, "activity_type=all": false,
		"activity_type=school_visit": true, "district_id=d1": true, "risk=any": true, "context=x": true,
		"district_id=%20": false,
	} {
		q, _ := url.ParseQuery(query)
		if got := hasAdvancedFilter(q); got != want {
			t.Errorf("hasAdvancedFilter(%q) = %v, want %v", query, got, want)
		}
	}
}
