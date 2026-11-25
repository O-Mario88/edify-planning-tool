package coreoversight

import (
	"archive/zip"
	"bytes"
	"io"
	"strings"
	"testing"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/myplan"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/workbook"
)

// A plan sheet's cells read back as table_export hands them to the
// workbook: a day as a date, an amount as a number, a count as a number,
// and what is not one of those as the text it is.
func TestPlanCellsReadBackToTheirValues(t *testing.T) {
	sheet := typedPlan(myplan.Sheet{Title: "Core School Trainings",
		Headers: []string{"School ID", "Planned Date", "Completed Date", "Participants", "Cost"},
		Rows: [][]string{
			{"1442", "5 Oct 2026", "—", "12", "UGX 40,000"},
			{"0007", "Unscheduled", "28 Nov 2026", "—", "UGX 40,000 (estimate)"},
		}})
	if sheet.NumberFormats[2] != "d mmm yyyy" || sheet.NumberFormats[3] != "d mmm yyyy" || sheet.NumberFormats[5] != `"UGX "#,##0` {
		t.Fatalf("formats: %v", sheet.NumberFormats)
	}
	var buf bytes.Buffer
	if err := workbook.Write(&buf, []workbook.Sheet{sheet}); err != nil {
		t.Fatal(err)
	}
	zr, _ := zip.NewReader(bytes.NewReader(buf.Bytes()), int64(buf.Len()))
	var xml string
	for _, f := range zr.File {
		if f.Name == "xl/worksheets/sheet1.xml" {
			rc, _ := f.Open()
			b, _ := io.ReadAll(rc)
			xml = string(b)
		}
	}
	for _, want := range []string{
		`<c r="A2" t="inlineStr"`, `<is><t xml:space="preserve">1442</t></is>`, // a School ID stays text
		`<c r="B2" s="`, `<v>46300</v>`, // 5 Oct 2026
		`<v>12</v>`, `<v>40000</v>`,
		`Unscheduled`, `UGX 40,000 (estimate)`, `<v>46354</v>`, // 28 Nov 2026
	} {
		if !strings.Contains(xml, want) {
			t.Errorf("the sheet lacks %s", want)
		}
	}
}
