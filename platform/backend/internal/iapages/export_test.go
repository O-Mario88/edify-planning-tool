package iapages

import (
	"net/url"
	"testing"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
)

func TestTheExportKeepsTheQueuesFiltersWithoutItsPageForAReaderWhoMayExport(t *testing.T) {
	ia := auth.Principal{Account: auth.Account{ActiveRole: "ImpactAssessment"}}
	got := exportActions(ia, ReturnedPath, url.Values{"page": {"2"}, "school": {"Gulu"}, "fy": {""}})
	if len(got) != 1 || got[0].GetLabel() != "Export" || !got[0].GetDownload() || got[0].GetHref() != "/ia/returned/?export=xlsx&school=Gulu" {
		t.Fatalf("export: %v", got)
	}
	if got := exportActions(auth.Principal{Account: auth.Account{ActiveRole: "CCEO"}}, ReturnedPath, nil); got != nil {
		t.Fatalf("a reader who may not export is offered %v", got)
	}
}
