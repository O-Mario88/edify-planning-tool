package uploads

import (
	"bytes"
	"strings"
	"testing"
	"time"
)

func TestSSATemplateAndRoundTripParser(t *testing.T) {
	now := time.Date(2026, 11, 22, 12, 0, 0, 0, time.UTC)
	tpl := SSATemplateCSV(now)
	if !strings.Contains(string(tpl), "School ID,Assessment Date,SSA Year") {
		t.Fatalf("unexpected template header: %s", string(tpl))
	}
	rows, errs, err := ParseSSACSV(bytes.NewReader(tpl), now)
	if err != nil {
		t.Fatalf("ParseSSACSV failed on own template: %v", err)
	}
	if len(errs) != 0 || len(rows) != 1 {
		t.Fatalf("expected 1 valid row and 0 errors, got rows=%d errs=%v", len(rows), errs)
	}
	if rows[0].fy != "2027" || rows[0].avg != 7.5 || len(rows[0].scores) != 8 {
		t.Fatalf("unexpected parsed row: %+v", rows[0])
	}
}

func TestParseSSACSVRejectsOutOfRangeAndDuplicates(t *testing.T) {
	now := time.Date(2026, 11, 22, 12, 0, 0, 0, time.UTC)
	csvData := strings.Join([]string{
		"School ID,Assessment Date,SSA Year,School Leadership (0-10),Teaching & Learning (0-10)",
		"UG-001,2026-10-15,current,8.0,6.0",
		"UG-001,2026-10-15,current,7.0,7.0",
		"UG-002,2026-10-15,last,12.5,5.0",
		"UG-003,not-a-date,2027,5.0,5.0",
	}, "\n")
	rows, errs, err := ParseSSACSV(strings.NewReader(csvData), now)
	if err != nil {
		t.Fatalf("unexpected fatal error: %v", err)
	}
	if len(rows) != 1 {
		t.Fatalf("expected exactly 1 valid row, got %d", len(rows))
	}
	if rows[0].avg != 7.0 || rows[0].fy != "2027" {
		t.Fatalf("unexpected valid row: %+v", rows[0])
	}
	if len(errs) != 3 {
		t.Fatalf("expected 3 row errors (duplicate, >10 score, bad date), got %d: %+v", len(errs), errs)
	}
}
