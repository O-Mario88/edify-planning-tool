package workbook

import (
	"archive/zip"
	"bytes"
	"io"
	"net/http/httptest"
	"strings"
	"testing"
	"time"
)

// Formula-shaped text gets the apostrophe spreadsheets read as text, but a
// plain signed number and a lone sign stay as they are (spreadsheet_text).
func TestSpreadsheetTextNeutralisesFormulas(t *testing.T) {
	for in, want := range map[string]string{
		"=HYPERLINK(1)": "'=HYPERLINK(1)", "+1 call": "'+1 call", "@me": "'@me", "-5": "-5", "-1,200": "-1,200",
		"-": "-", "+": "+", "-1.5": "-1.5", "-1.": "'-1.", "Alpha": "Alpha", "": "",
	} {
		if got := SpreadsheetText(in); got != want {
			t.Errorf("%q: %q, want %q", in, got, want)
		}
	}
}

// A sheet title loses Excel's forbidden characters and is cut at 31, and a
// heading's width is its length plus six, between 14 and 42.
func TestSheetTitlesAndWidthsAreTheExistingOnes(t *testing.T) {
	if got := SheetTitle("Plan: Q1/2026 [draft]"); got != "Plan  Q1 2026  draft" {
		t.Errorf("title: %q", got)
	}
	if got := SheetTitle(" ?* "); got != "Export" {
		t.Errorf("empty title: %q", got)
	}
	if got := SheetTitle(strings.Repeat("x", 40)); len(got) != 31 {
		t.Errorf("long title: %d", len(got))
	}
	got := WidthsFor([]string{"ID", "Cost (UGX)", strings.Repeat("h", 50)})
	if got[0] != 14 || got[1] != 16 || got[2] != 42 {
		t.Errorf("widths: %v", got)
	}
}

// Two sheets of one title are told apart as openpyxl tells them apart.
func TestTheWorkbookHoldsEachSheetUnderItsOwnTitle(t *testing.T) {
	var buf bytes.Buffer
	err := Write(&buf, []Sheet{
		{Title: "Plan", Headers: []string{"School", "Day"}, Rows: [][]Cell{{Text("A & B"), Date(time.Date(2026, 11, 3, 0, 0, 0, 0, time.UTC))}}},
		{Title: "Plan", Headers: []string{"Only"}},
	})
	if err != nil {
		t.Fatal(err)
	}
	book := readPart(t, buf.Bytes(), "xl/workbook.xml")
	if !strings.Contains(book, `name="Plan"`) || !strings.Contains(book, `name="Plan1"`) {
		t.Errorf("workbook: %s", book)
	}
	sheet := readPart(t, buf.Bytes(), "xl/worksheets/sheet1.xml")
	for _, want := range []string{"A &amp; B", "<v>46329</v>", `<autoFilter ref="A1:B2"/>`, `topLeftCell="A2"`, `showGridLines="0"`} {
		if !strings.Contains(sheet, want) {
			t.Errorf("the sheet lacks %s: %s", want, sheet)
		}
	}
	if strings.Contains(readPart(t, buf.Bytes(), "xl/worksheets/sheet2.xml"), "autoFilter") {
		t.Error("a sheet of headings alone has a filter")
	}
}

// A link asking for format=csv gets the first sheet as CSV, formulas
// neutralised; any other gets the workbook.
func TestDownloadAnswersTheFormatTheLinkAsks(t *testing.T) {
	sheets := []Sheet{{Title: "Plan", Headers: []string{"School", "Cost"}, Rows: [][]Cell{{Text("=x"), Int(12000)}, {Text("B"), Number(1.5)}, {Text("C"), Number(3)}}}}
	rec := httptest.NewRecorder()
	if err := Download(rec, httptest.NewRequest("GET", "/x?format=csv", nil), "plan", sheets); err != nil {
		t.Fatal(err)
	}
	if got := rec.Body.String(); got != "School,Cost\r\n'=x,12000\r\nB,1.5\r\nC,3.0\r\n" {
		t.Errorf("csv: %q", got)
	}
	if got := rec.Header().Get("Content-Disposition"); got != `attachment; filename="plan.csv"` {
		t.Errorf("csv name: %q", got)
	}
	rec = httptest.NewRecorder()
	if err := Download(rec, httptest.NewRequest("GET", "/x", nil), "plan", sheets); err != nil {
		t.Fatal(err)
	}
	if rec.Header().Get("Content-Type") != ContentType || rec.Header().Get("Content-Disposition") != `attachment; filename="plan.xlsx"` {
		t.Errorf("workbook headers: %v", rec.Header())
	}
}

func readPart(t *testing.T, raw []byte, name string) string {
	t.Helper()
	zr, err := zip.NewReader(bytes.NewReader(raw), int64(len(raw)))
	if err != nil {
		t.Fatal(err)
	}
	for _, f := range zr.File {
		if f.Name == name {
			rc, err := f.Open()
			if err != nil {
				t.Fatal(err)
			}
			body, _ := io.ReadAll(rc)
			_ = rc.Close()
			return string(body)
		}
	}
	t.Fatalf("no part %s", name)
	return ""
}
