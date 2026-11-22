package exports

import (
	"archive/zip"
	"bytes"
	"encoding/csv"
	"encoding/xml"
	"fmt"
	"io"
	"strings"
	"time"
)

// Format identifies the output file format of an export job.
type Format string

const (
	FormatCSV  Format = "csv"
	FormatXLSX Format = "xlsx"
	FormatPDF  Format = "pdf"
)

// ParseFormat normalizes and validates an export format (empty defaults to csv).
func ParseFormat(raw string) (Format, error) {
	switch strings.ToLower(strings.TrimSpace(raw)) {
	case "", "csv":
		return FormatCSV, nil
	case "xlsx", "excel":
		return FormatXLSX, nil
	case "pdf":
		return FormatPDF, nil
	default:
		return "", fmt.Errorf("exports: unsupported format %q (supported: csv, xlsx, pdf)", raw)
	}
}

// ContentType returns the HTTP MIME type for format.
func (f Format) ContentType() string {
	switch f {
	case FormatXLSX:
		return "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
	case FormatPDF:
		return "application/pdf"
	default:
		return "text/csv; charset=utf-8"
	}
}

// Extension returns the file extension without leading dot.
func (f Format) Extension() string {
	switch f {
	case FormatXLSX:
		return "xlsx"
	case FormatPDF:
		return "pdf"
	default:
		return "csv"
	}
}

// convertCSVPayload transforms a canonical CSV byte payload into the requested
// output format (CSV passthrough, genuine OOXML .xlsx workbook, or valid
// multi-page tabular PDF 1.4 report) using zero external dependencies.
func convertCSVPayload(kind string, format Format, generatedAt time.Time, csvBytes []byte) ([]byte, error) {
	if format == FormatCSV || format == "" {
		return csvBytes, nil
	}
	records, err := csv.NewReader(bytes.NewReader(csvBytes)).ReadAll()
	if err != nil {
		return nil, fmt.Errorf("exports: decode csv for %s: %w", format, err)
	}
	var headers []string
	var rows [][]string
	if len(records) > 0 {
		headers = records[0]
		rows = records[1:]
	}
	title := strings.ReplaceAll(strings.ToUpper(kind), "_", " ")
	switch format {
	case FormatXLSX:
		return BuildXLSX(title, headers, rows)
	case FormatPDF:
		subtitle := fmt.Sprintf("Generated %s UTC  |  %d row(s)", generatedAt.UTC().Format("2006-01-02 15:04"), len(rows))
		return BuildPDF("Edify Planning & Monitoring — "+title, subtitle, headers, rows)
	default:
		return csvBytes, nil
	}
}

// BuildXLSX produces a standards-compliant OpenXML (.xlsx) workbook readable
// by Microsoft Excel, Google Sheets, LibreOffice, and openpyxl.
func BuildXLSX(sheetName string, headers []string, rows [][]string) ([]byte, error) {
	sheetName = sanitizeSheetName(sheetName)
	var buf bytes.Buffer
	zw := zip.NewWriter(&buf)

	addFile := func(name, content string) error {
		w, err := zw.Create(name)
		if err != nil {
			return err
		}
		_, err = io.WriteString(w, content)
		return err
	}

	if err := addFile("[Content_Types].xml", `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
  <Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
  <Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>
</Types>`); err != nil {
		return nil, err
	}

	if err := addFile("_rels/.rels", `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>`); err != nil {
		return nil, err
	}

	if err := addFile("xl/_rels/workbook.xml.rels", `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>`); err != nil {
		return nil, err
	}

	if err := addFile("xl/workbook.xml", fmt.Sprintf(`<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets><sheet name="%s" sheetId="1" r:id="rId1"/></sheets>
</workbook>`, xmlEscape(sheetName))); err != nil {
		return nil, err
	}

	if err := addFile("xl/styles.xml", `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <fonts count="2">
    <font><sz val="11"/><name val="Calibri"/></font>
    <font><b/><sz val="11"/><color rgb="FFFFFFFF"/><name val="Calibri"/></font>
  </fonts>
  <fills count="3">
    <fill><patternFill patternType="none"/></fill>
    <fill><patternFill patternType="gray125"/></fill>
    <fill><patternFill patternType="solid"><fgColor rgb="FF005B8C"/><bgColor indexed="64"/></patternFill></fill>
  </fills>
  <borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>
  <cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
  <cellXfs count="2">
    <xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>
    <xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyFont="1" applyFill="1"/>
  </cellXfs>
</styleSheet>`); err != nil {
		return nil, err
	}

	var ws strings.Builder
	ws.WriteString(`<?xml version="1.0" encoding="UTF-8" standalone="yes"?>`)
	ws.WriteString(`<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>`)
	writeRow := func(rowNum int, cells []string, style int) {
		fmt.Fprintf(&ws, `<row r="%d">`, rowNum)
		for idx, val := range cells {
			ref := fmt.Sprintf("%s%d", xlsxColRef(idx), rowNum)
			if style > 0 {
				fmt.Fprintf(&ws, `<c r="%s" t="inlineStr" s="%d"><is><t>%s</t></is></c>`, ref, style, xmlEscape(val))
			} else {
				fmt.Fprintf(&ws, `<c r="%s" t="inlineStr"><is><t>%s</t></is></c>`, ref, xmlEscape(val))
			}
		}
		ws.WriteString(`</row>`)
	}
	rowIdx := 1
	if len(headers) > 0 {
		writeRow(rowIdx, headers, 1)
		rowIdx++
	}
	for _, r := range rows {
		writeRow(rowIdx, r, 0)
		rowIdx++
	}
	ws.WriteString(`</sheetData></worksheet>`)
	if err := addFile("xl/worksheets/sheet1.xml", ws.String()); err != nil {
		return nil, err
	}
	if err := zw.Close(); err != nil {
		return nil, err
	}
	return buf.Bytes(), nil
}

func sanitizeSheetName(name string) string {
	repl := strings.NewReplacer(":", " ", "\\", " ", "/", " ", "?", " ", "*", " ", "[", "(", "]", ")")
	out := strings.TrimSpace(repl.Replace(name))
	if out == "" {
		return "Edify Export"
	}
	if len(out) > 31 {
		return out[:31]
	}
	return out
}

func xlsxColRef(idx int) string {
	var chars []byte
	for {
		chars = append([]byte{byte('A' + (idx % 26))}, chars...)
		idx = idx/26 - 1
		if idx < 0 {
			break
		}
	}
	return string(chars)
}

func xmlEscape(s string) string {
	var b bytes.Buffer
	_ = xml.EscapeText(&b, []byte(s))
	return b.String()
}

// BuildPDF produces a standards-compliant multi-page landscape PDF 1.4 tabular
// report using built-in Helvetica fonts and exact xref offsets.
func BuildPDF(title, subtitle string, headers []string, rows [][]string) ([]byte, error) {
	const (
		pageW       = 792 // Letter landscape width (11in * 72pt)
		pageH       = 612 // Letter landscape height (8.5in * 72pt)
		marginX     = 36
		rowsPerPage = 34
	)

	colCount := len(headers)
	if colCount == 0 && len(rows) > 0 {
		colCount = len(rows[0])
	}
	if colCount == 0 {
		colCount = 1
	}
	availW := pageW - 2*marginX
	colW := availW / colCount
	maxChars := max(8, (colW/5)-1)

	totalPages := 1
	if len(rows) > 0 {
		totalPages = (len(rows) + rowsPerPage - 1) / rowsPerPage
	}

	var pageStreams []string
	for p := 0; p < totalPages; p++ {
		var s strings.Builder
		// Brand header bar
		s.WriteString("0 0.357 0.549 rg\n")
		fmt.Fprintf(&s, "%d %d %d 28 re f\n", marginX, pageH-58, availW)
		s.WriteString("1 1 1 rg\n")
		fmt.Fprintf(&s, "BT /F2 12 Tf %d %d Td (%s) Tj ET\n", marginX+10, pageH-48, pdfEscape(truncateASCII(title, 95)))

		// Subtitle & page number
		s.WriteString("0.25 0.3 0.36 rg\n")
		fmt.Fprintf(&s, "BT /F1 8 Tf %d %d Td (%s  |  Page %d of %d) Tj ET\n",
			marginX, pageH-72, pdfEscape(truncateASCII(subtitle, 90)), p+1, totalPages)

		// Column header strip
		headerY := pageH - 94
		s.WriteString("0.92 0.95 0.98 rg\n")
		fmt.Fprintf(&s, "%d %d %d 16 re f\n", marginX, headerY-4, availW)
		s.WriteString("0.08 0.14 0.22 rg\n")
		for ci, h := range headers {
			x := marginX + ci*colW + 3
			fmt.Fprintf(&s, "BT /F2 7.5 Tf %d %d Td (%s) Tj ET\n", x, headerY, pdfEscape(truncateASCII(h, maxChars)))
		}

		// Data rows
		start := p * rowsPerPage
		end := min(len(rows), start+rowsPerPage)
		y := headerY - 18
		for ri := start; ri < end; ri++ {
			if (ri-start)%2 == 1 {
				s.WriteString("0.97 0.98 0.99 rg\n")
				fmt.Fprintf(&s, "%d %d %d 13 re f\n", marginX, y-3, availW)
			}
			s.WriteString("0.1 0.14 0.2 rg\n")
			row := rows[ri]
			for ci := 0; ci < colCount && ci < len(row); ci++ {
				x := marginX + ci*colW + 3
				fmt.Fprintf(&s, "BT /F1 7.5 Tf %d %d Td (%s) Tj ET\n", x, y, pdfEscape(truncateASCII(row[ci], maxChars)))
			}
			y -= 13
		}
		if len(rows) == 0 {
			s.WriteString("0.35 0.4 0.45 rg\n")
			fmt.Fprintf(&s, "BT /F1 9 Tf %d %d Td (No matching records for the selected filters.) Tj ET\n", marginX+4, headerY-24)
		}
		pageStreams = append(pageStreams, s.String())
	}

	// Assemble PDF objects:
	// 1: Catalog, 2: Pages, 3: Helvetica, 4: Helvetica-Bold,
	// then pairs (pageObj, contentObj) for each page.
	var out bytes.Buffer
	out.WriteString("%PDF-1.4\n%\xE2\xE3\xCF\xD3\n")
	offsets := []int{0}
	writeObj := func(id int, body string) {
		offsets = append(offsets, out.Len())
		fmt.Fprintf(&out, "%d 0 obj\n%s\nendobj\n", id, body)
	}

	var kids []string
	for i := range pageStreams {
		kids = append(kids, fmt.Sprintf("%d 0 R", 5+i*2))
	}
	writeObj(1, `<< /Type /Catalog /Pages 2 0 R >>`)
	writeObj(2, fmt.Sprintf(`<< /Type /Pages /Kids [%s] /Count %d >>`, strings.Join(kids, " "), len(pageStreams)))
	writeObj(3, `<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>`)
	writeObj(4, `<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>`)
	for i, stream := range pageStreams {
		pageObj := 5 + i*2
		contentObj := pageObj + 1
		writeObj(pageObj, fmt.Sprintf(`<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %d %d] /Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> /Contents %d 0 R >>`,
			pageW, pageH, contentObj))
		writeObj(contentObj, fmt.Sprintf("<< /Length %d >>\nstream\n%sendstream", len(stream), stream))
	}

	xrefPos := out.Len()
	fmt.Fprintf(&out, "xref\n0 %d\n0000000000 65535 f \n", len(offsets))
	for _, off := range offsets[1:] {
		fmt.Fprintf(&out, "%010d 00000 n \n", off)
	}
	fmt.Fprintf(&out, "trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n", len(offsets), xrefPos)
	return out.Bytes(), nil
}

func truncateASCII(s string, maxLen int) string {
	var b strings.Builder
	for _, r := range s {
		if r >= 32 && r <= 126 {
			b.WriteRune(r)
		} else if r == '\n' || r == '\r' || r == '\t' {
			b.WriteByte(' ')
		}
	}
	out := strings.TrimSpace(b.String())
	if len(out) > maxLen && maxLen > 3 {
		return out[:maxLen-3] + "..."
	}
	return out
}

func pdfEscape(s string) string {
	repl := strings.NewReplacer(`\`, `\\`, `(`, `\(`, `)`, `\)`)
	return repl.Replace(s)
}
