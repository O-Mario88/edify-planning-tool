package budgetpage

import (
	"errors"
	"testing"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pagegate"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/workbook"
)

func TestExportGateAsksThePageThenDataExport(t *testing.T) {
	if err := ExportGate("ClusterLeader"); !errors.Is(err, pagegate.ErrNotAvailable) {
		t.Errorf("a role without the Budget page: %v", err)
	}
	var refusal workbook.Refusal
	if err := ExportGate("CCEO"); !errors.As(err, &refusal) || string(refusal) != ExportRefusal {
		t.Errorf("an officer opens the Budget but may not export it: %v", err)
	}
	if err := ExportGate("CountryDirector"); err != nil {
		t.Errorf("the Director exports: %v", err)
	}
}
