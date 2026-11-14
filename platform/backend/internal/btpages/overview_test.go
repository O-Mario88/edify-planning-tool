package btpages

import (
	"testing"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/btportfolio"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/loans/ledger"
)

func TestFiguresAreWrittenAsTheRegistryWritesThem(t *testing.T) {
	if ugx(ledger.Shillings(68_500_000)) != "UGX 68,500,000" || ugx(0) != "UGX 0" || ugx(150) != "UGX 2" {
		t.Errorf("ugx: %q %q %q", ugx(ledger.Shillings(68_500_000)), ugx(0), ugx(150))
	}
	if ratio(0, 10) != "0%" || ratio(1, 8) != "12.5%" || ratio(1, 0) != "No data" || ratio(10, 10) != "100%" {
		t.Errorf("ratio: %q %q %q %q", ratio(0, 10), ratio(1, 8), ratio(1, 0), ratio(10, 10))
	}
}

func TestTheYearIsReadOrPassedOn(t *testing.T) {
	now := time.Date(2026, 11, 14, 0, 0, 0, 0, time.UTC)
	if fy, ok := fyOf(btportfolio.Filters{}, now); !ok || fy != "2027" {
		t.Errorf("default: %q", fy)
	}
	if _, ok := fyOf(btportfolio.Filters{"fy": "abc"}, now); ok {
		t.Error("a year the existing page cannot read is passed on")
	}
}
