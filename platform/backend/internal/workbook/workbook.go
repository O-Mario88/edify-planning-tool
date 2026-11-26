// Package workbook writes the existing application's styled .xlsx exports
// (apps.core.excel.workbook_response and table_download) with the standard
// library alone: the navy heading row, banded and ruled body rows, each
// column's number format and width, the frozen heading, the filter, no grid
// lines, and the Budget's sectioned ledger rows. The rows are the caller's:
// each export hands over what its own page shows.
package workbook

import (
	"archive/zip"
	"bytes"
	"encoding/csv"
	"fmt"
	"io"
	"math"
	"net/http"
	"strconv"
	"strings"
	"time"
)

// ContentType is XLSX_CONTENT_TYPE.
const ContentType = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

// The Work Plan export's palette (HEADER_FILL, HEADER_RULE, ROW_RULE, BAND)
// and the Budget ledger's (LEDGER_BAND, LEDGER_INK, LEDGER_SUBTOTAL).
const (
	headerFill     = "102A43"
	headerRule     = "1677FF"
	rowRule        = "D9E2EC"
	band           = "F7FAFC"
	ledgerBand     = "DCE6EC"
	ledgerInk      = "17232B"
	ledgerSubtotal = "E5EAED"
	captionInk     = "52606D"
	paper          = "FFFFFF"
	headerHeight   = 28
	ledgerHeight   = 22
	dateFormat     = "yyyy-mm-dd"
	dateTimeFormat = "yyyy-mm-dd h:mm:ss"
)

// Ledger row styles (LEDGER_STYLES).
const (
	RowTitle    = "title"
	RowCaption  = "caption"
	RowBand     = "band"
	RowColumns  = "columns"
	RowSubtotal = "subtotal"
	RowTotal    = "total"
)

type cellKind int

const (
	kindEmpty cellKind = iota
	kindText
	kindNumber
	kindDate
	kindDateTime
)

// Cell is one value as Python hands it to openpyxl.
type Cell struct {
	kind cellKind
	text string
	num  float64
	// float is a Python float (str() writes 3.0), not an int.
	float bool
	when  time.Time
}

// Text is a str cell, kept as the text it is.
func Text(s string) Cell { return Cell{kind: kindText, text: s} }

// Int is an int cell.
func Int(n int64) Cell { return Cell{kind: kindNumber, num: float64(n)} }

// Number is a float cell (a Decimal's figure reads the same in a workbook).
func Number(f float64) Cell { return Cell{kind: kindNumber, num: f, float: true} }

// Date is a datetime.date cell (shown yyyy-mm-dd).
func Date(t time.Time) Cell { return Cell{kind: kindDate, when: t} }

// DateTime is a naive datetime.datetime cell (shown yyyy-mm-dd h:mm:ss).
func DateTime(t time.Time) Cell { return Cell{kind: kindDateTime, when: t} }

// Empty is None.
func Empty() Cell { return Cell{} }

// Sheet is one sheet spec: {title, headers, rows, widths?, number_formats?,
// row_styles?, filter?, freeze?, align?}.
type Sheet struct {
	Title   string
	Headers []string
	Rows    [][]Cell
	// Widths are the columns' widths; none gives _widths_for(headers).
	Widths []float64
	// NumberFormats maps a 1-based column to an Excel format.
	NumberFormats map[int]string
	// RowStyles maps a 1-based row to a ledger style.
	RowStyles map[int]string
	// Align maps a 1-based column to "center" or "right".
	Align map[int]string
	// NoFilter is filter=False.
	NoFilter bool
	// NoFreeze is freeze=None; Freeze names another cell than A2.
	NoFreeze bool
	Freeze   string
	// Plain is openpyxl's write-only sheet as a view writes one by hand: the
	// values alone, no heading style, bands, widths, frozen row, filter or
	// hidden grid.
	Plain bool
	// HeadingOnly is a sheet styled by style_header alone: its body rows
	// carry no bands or rules, only the number formats and bold cells below.
	HeadingOnly bool
	// FilterHeading filters the heading row alone when no row follows it
	// (auto_filter.ref = sheet.dimensions on a sheet a view builds by hand).
	FilterHeading bool
	// FormatThrough is the last row the NumberFormats reach; 0 is every row.
	FormatThrough int
	// Bold maps a 1-based row to the 1-based columns set Font(bold=True,
	// size=10).
	Bold map[int][]int
}

// Download writes table_download: the workbook as <stem>.xlsx, or the first
// sheet as <stem>.csv when the link asks for format=csv.
func Download(w http.ResponseWriter, r *http.Request, stem string, sheets []Sheet) error {
	if strings.EqualFold(strings.TrimSpace(r.URL.Query().Get("format")), "csv") {
		return writeCSV(w, stem, sheets)
	}
	return Response(w, stem+".xlsx", sheets)
}

// Response writes workbook_response: the styled workbook as a download.
func Response(w http.ResponseWriter, filename string, sheets []Sheet) error {
	var buf bytes.Buffer
	if err := Write(&buf, sheets); err != nil {
		return err
	}
	w.Header().Set("Content-Type", ContentType)
	w.Header().Set("Content-Disposition", `attachment; filename="`+filename+`"`)
	_, err := w.Write(buf.Bytes())
	return err
}

func writeCSV(w http.ResponseWriter, stem string, sheets []Sheet) error {
	w.Header().Set("Content-Type", "text/csv; charset=utf-8")
	w.Header().Set("Content-Disposition", `attachment; filename="`+stem+`.csv"`)
	body, err := FirstSheetCSV(sheets)
	if err != nil {
		return err
	}
	_, err = w.Write(body)
	return err
}

// FirstSheetCSV is table_download's CSV: the first sheet's heading and rows.
func FirstSheetCSV(sheets []Sheet) ([]byte, error) {
	var buf bytes.Buffer
	cw := csv.NewWriter(&buf)
	cw.UseCRLF = true
	if len(sheets) > 0 {
		sheet := sheets[0]
		if len(sheet.Headers) > 0 {
			if err := cw.Write(safeRow(stringsCells(sheet.Headers))); err != nil {
				return nil, err
			}
		}
		for _, row := range sheet.Rows {
			if err := cw.Write(safeRow(row)); err != nil {
				return nil, err
			}
		}
	}
	cw.Flush()
	return buf.Bytes(), cw.Error()
}

func stringsCells(values []string) []Cell {
	out := make([]Cell, len(values))
	for i, v := range values {
		out[i] = Text(v)
	}
	return out
}

// SafeCSVRow is safe_csv_writer's row: each value as csv.writer writes it,
// formula-shaped text given a leading apostrophe.
func SafeCSVRow(row []Cell) []string { return safeRow(row) }

// DateValue is the cell's day when it holds a date.
func (c Cell) DateValue() (time.Time, bool) { return c.when, c.kind == kindDate }

// safeRow is _SafeCsvWriter.writerow: each value as csv.writer writes it,
// formula-shaped text given a leading apostrophe (spreadsheet_text).
func safeRow(row []Cell) []string {
	out := make([]string, len(row))
	for i, c := range row {
		switch c.kind {
		case kindText:
			out[i] = SpreadsheetText(c.text)
		case kindNumber:
			out[i] = pyNumber(c.num, c.float)
		case kindDate:
			out[i] = c.when.Format(time.DateOnly)
		case kindDateTime:
			out[i] = c.when.Format("2006-01-02 15:04:05")
		}
	}
	return out
}

// pyNumber is str() of the number: an int's digits, a float's repr
// ("3.0", "12.5", "1e+16").
func pyNumber(f float64, float bool) string {
	abs := math.Abs(f)
	switch {
	case !float:
		return strconv.FormatInt(int64(f), 10)
	case f == math.Trunc(f) && abs < 1e16:
		return strconv.FormatFloat(f, 'f', 1, 64)
	case abs >= 1e-4 && abs < 1e16:
		return strconv.FormatFloat(f, 'f', -1, 64)
	}
	return strconv.FormatFloat(f, 'g', -1, 64)
}

// SpreadsheetText is spreadsheet_text: text that starts like a formula is
// written with a leading apostrophe, but a plain signed number and a lone
// "-" or "+".
func SpreadsheetText(value string) string {
	if value == "" || value == "-" || value == "+" || !strings.ContainsRune("=+-@\t\r", rune(value[0])) {
		return value
	}
	if plainNumber(value) {
		return value
	}
	return "'" + value
}

func plainNumber(text string) bool {
	i := 0
	if i < len(text) && (text[i] == '+' || text[i] == '-') {
		i++
	}
	if i >= len(text) || text[i] < '0' || text[i] > '9' {
		return false
	}
	for i < len(text) && (text[i] >= '0' && text[i] <= '9' || text[i] == ',') {
		i++
	}
	if i < len(text) && text[i] == '.' {
		i++
		start := i
		for i < len(text) && text[i] >= '0' && text[i] <= '9' {
			i++
		}
		if i == start {
			return false
		}
	}
	return i == len(text)
}

// SheetTitle is _sheet_title: Excel's forbidden characters spaced out, at
// most 31 characters, "Export" when nothing is left.
func SheetTitle(title string) string {
	for _, bad := range "[]:*?/\\" {
		title = strings.ReplaceAll(title, string(bad), " ")
	}
	title = strings.TrimSpace(title)
	if title == "" {
		title = "Export"
	}
	if r := []rune(title); len(r) > 31 {
		title = string(r[:31])
	}
	return title
}

// WidthsFor is _widths_for: wide enough to read the heading, between 14
// and 42.
func WidthsFor(headers []string) []float64 {
	out := make([]float64, len(headers))
	for i, h := range headers {
		out[i] = float64(min(42, max(14, len([]rune(h))+6)))
	}
	return out
}

// Write writes the workbook.
func Write(w io.Writer, sheets []Sheet) error {
	if len(sheets) == 0 {
		sheets = []Sheet{{Title: "Export"}}
	}
	st := newStyles()
	parts := make([]string, len(sheets))
	titles := make([]string, len(sheets))
	for i, sheet := range sheets {
		titles[i] = uniqueTitle(SheetTitle(sheet.Title), titles[:i])
		parts[i] = sheetXML(sheet, st)
	}
	zw := zip.NewWriter(w)
	add := func(name, body string) error {
		f, err := zw.Create(name)
		if err != nil {
			return err
		}
		_, err = io.WriteString(f, body)
		return err
	}
	if err := add("[Content_Types].xml", contentTypes(len(sheets))); err != nil {
		return err
	}
	if err := add("_rels/.rels", rootRels); err != nil {
		return err
	}
	if err := add("xl/workbook.xml", workbookXML(titles)); err != nil {
		return err
	}
	if err := add("xl/_rels/workbook.xml.rels", workbookRels(len(sheets))); err != nil {
		return err
	}
	if err := add("xl/styles.xml", st.xml()); err != nil {
		return err
	}
	for i, part := range parts {
		if err := add(fmt.Sprintf("xl/worksheets/sheet%d.xml", i+1), part); err != nil {
			return err
		}
	}
	return zw.Close()
}

// uniqueTitle is openpyxl's create_sheet for a title already taken: the
// title with 1, 2 … added.
func uniqueTitle(title string, taken []string) string {
	has := func(t string) bool {
		for _, x := range taken {
			if strings.EqualFold(x, t) {
				return true
			}
		}
		return false
	}
	if !has(title) {
		return title
	}
	for n := 1; ; n++ {
		if candidate := fmt.Sprintf("%s%d", title, n); !has(candidate) {
			return candidate
		}
	}
}

// ColumnLetter is get_column_letter.
func ColumnLetter(column int) string {
	var out []byte
	for column > 0 {
		column--
		out = append([]byte{byte('A' + column%26)}, out...)
		column /= 26
	}
	return string(out)
}

func cellRef(column, row int) string { return ColumnLetter(column) + strconv.Itoa(row) }

// excelSerial is the date's serial number from 1899-12-30.
func excelSerial(t time.Time, withTime bool) float64 {
	base := time.Date(1899, 12, 30, 0, 0, 0, 0, time.UTC)
	day := time.Date(t.Year(), t.Month(), t.Day(), 0, 0, 0, 0, time.UTC)
	serial := day.Sub(base).Hours() / 24
	if withTime {
		seconds := t.Hour()*3600 + t.Minute()*60 + t.Second()
		serial += (float64(seconds) + float64(t.Nanosecond())/1e9) / 86400
	}
	return serial
}

func escape(s string) string {
	var b strings.Builder
	for _, r := range s {
		switch {
		case r == '&':
			b.WriteString("&amp;")
		case r == '<':
			b.WriteString("&lt;")
		case r == '>':
			b.WriteString("&gt;")
		case r == '"':
			b.WriteString("&quot;")
		case r == '\t' || r == '\n' || r == '\r':
			b.WriteRune(r)
		case r < 0x20 || r == 0xFFFE || r == 0xFFFF:
			// openpyxl refuses control characters; the existing exports never
			// carry them, so Go drops them rather than writing a broken file.
		default:
			b.WriteRune(r)
		}
	}
	return b.String()
}

// Refusal is an export's refusal in the existing words, shown to the
// reader as it is; any other error is the export failing.
type Refusal string

func (r Refusal) Error() string { return string(r) }

// BadRequest is a view's BadRequest: the request is refused with 400 in the
// existing words.
type BadRequest string

func (b BadRequest) Error() string { return string(b) }
