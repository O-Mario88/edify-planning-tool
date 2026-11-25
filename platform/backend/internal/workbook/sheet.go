package workbook

import (
	"fmt"
	"strconv"
	"strings"
)

// sheetXML is one sheet as workbook_response lays it out: the heading row,
// the body (style_body), the ledger rows (style_ledger_rows), the frozen
// heading, the filter over the sheet's dimensions, the widths, no grid lines.
func sheetXML(sheet Sheet, st *styles) string {
	headers := len(sheet.Headers) > 0
	grid := [][]Cell{}
	if headers {
		grid = append(grid, stringsCells(sheet.Headers))
	}
	grid = append(grid, sheet.Rows...)
	width := 0
	for _, row := range grid {
		width = max(width, len(row))
	}
	height := len(grid)

	var b strings.Builder
	b.WriteString(`<?xml version="1.0" encoding="UTF-8" standalone="yes"?>`)
	b.WriteString(`<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">`)
	if width > 0 && height > 0 {
		fmt.Fprintf(&b, `<dimension ref="A1:%s"/>`, cellRef(width, height))
	}
	b.WriteString(`<sheetViews><sheetView showGridLines="0" workbookViewId="0">`)
	if freeze := freezeCell(sheet, headers); freeze != "" {
		b.WriteString(paneXML(freeze))
	}
	b.WriteString(`</sheetView></sheetViews><sheetFormatPr defaultRowHeight="15"/>`)
	widths := sheet.Widths
	if len(widths) == 0 {
		widths = WidthsFor(sheet.Headers)
	}
	if len(widths) > 0 {
		b.WriteString(`<cols>`)
		for i, w := range widths {
			fmt.Fprintf(&b, `<col min="%d" max="%d" width="%s" customWidth="1"/>`, i+1, i+1, strconv.FormatFloat(w, 'f', -1, 64))
		}
		b.WriteString(`</cols>`)
	}
	b.WriteString(`<sheetData>`)
	for r := 1; r <= height; r++ {
		row := grid[r-1]
		name := sheet.RowStyles[r]
		switch {
		case name == RowBand || name == RowTitle || name == RowTotal:
			fmt.Fprintf(&b, `<row r="%d" ht="%d" customHeight="1">`, r, ledgerHeight)
		case r == 1 && headers:
			fmt.Fprintf(&b, `<row r="%d" ht="%d" customHeight="1">`, r, headerHeight)
		default:
			fmt.Fprintf(&b, `<row r="%d">`, r)
		}
		for c := 1; c <= width; c++ {
			cell := Empty()
			if c <= len(row) {
				cell = row[c-1]
			}
			xf := st.index(cellStyle(sheet, headers, r, c, cell))
			b.WriteString(cellXML(cellRef(c, r), cell, xf))
		}
		b.WriteString(`</row>`)
	}
	b.WriteString(`</sheetData>`)
	if headers && height > 1 && !sheet.NoFilter {
		fmt.Fprintf(&b, `<autoFilter ref="A1:%s"/>`, cellRef(width, height))
	}
	b.WriteString(`<pageMargins left="0.75" right="0.75" top="1" bottom="1" header="0.5" footer="0.5"/></worksheet>`)
	return b.String()
}

// freezeCell is sheet.freeze_panes: A2 under a heading unless the spec says
// otherwise; none without a heading.
func freezeCell(sheet Sheet, headers bool) string {
	if !headers || sheet.NoFreeze {
		return ""
	}
	if sheet.Freeze != "" {
		return sheet.Freeze
	}
	return "A2"
}

func paneXML(cell string) string {
	col, row := splitRef(cell)
	if col <= 1 && row <= 1 {
		return ""
	}
	var attrs []string
	pane := "bottomLeft"
	switch {
	case col > 1 && row > 1:
		pane = "bottomRight"
	case col > 1:
		pane = "topRight"
	}
	if col > 1 {
		attrs = append(attrs, fmt.Sprintf(`xSplit="%d"`, col-1))
	}
	if row > 1 {
		attrs = append(attrs, fmt.Sprintf(`ySplit="%d"`, row-1))
	}
	return fmt.Sprintf(`<pane %s topLeftCell="%s" activePane="%s" state="frozen"/><selection pane="%s" activeCell="%s" sqref="%s"/>`,
		strings.Join(attrs, " "), cell, pane, pane, cell, cell)
}

func splitRef(ref string) (int, int) {
	col, i := 0, 0
	for i < len(ref) && ref[i] >= 'A' && ref[i] <= 'Z' {
		col = col*26 + int(ref[i]-'A'+1)
		i++
	}
	row, _ := strconv.Atoi(ref[i:])
	return col, row
}

func cellXML(ref string, cell Cell, xf int) string {
	style := ""
	if xf > 0 {
		style = fmt.Sprintf(` s="%d"`, xf)
	}
	switch {
	case cell.kind == kindText && cell.text == "":
		// openpyxl keeps no value for "": the cell is written empty.
	case cell.kind == kindText:
		return fmt.Sprintf(`<c r="%s" t="inlineStr"%s><is><t xml:space="preserve">%s</t></is></c>`, ref, style, escape(cell.text))
	case cell.kind == kindNumber:
		return fmt.Sprintf(`<c r="%s"%s><v>%s</v></c>`, ref, style, strconv.FormatFloat(cell.num, 'g', -1, 64))
	case cell.kind == kindDate:
		return fmt.Sprintf(`<c r="%s"%s><v>%s</v></c>`, ref, style, strconv.FormatFloat(excelSerial(cell.when, false), 'f', -1, 64))
	case cell.kind == kindDateTime:
		return fmt.Sprintf(`<c r="%s"%s><v>%s</v></c>`, ref, style, strconv.FormatFloat(excelSerial(cell.when, true), 'f', -1, 64))
	}
	if xf == 0 {
		return ""
	}
	return fmt.Sprintf(`<c r="%s"%s/>`, ref, style)
}

// cellStyle is what workbook_response leaves on the cell at row r, column c.
func cellStyle(sheet Sheet, headers bool, r, c int, cell Cell) xfKey {
	k := xfKey{}
	switch cell.kind {
	case kindDate:
		k.numFmt = dateFormat
	case kindDateTime:
		k.numFmt = dateTimeFormat
	}
	switch {
	case r == 1 && headers:
		// style_header.
		k.font = fontKey{bold: true, size: 10, color: paper}
		k.fill = headerFill
		k.vertical = "center"
		k.border = borderKey{style: "medium", color: headerRule}
	case r >= 2:
		// style_body.
		k.fill = paper
		if r%2 == 0 {
			k.fill = band
		}
		k.border = borderKey{style: "thin", color: rowRule}
		k.vertical, k.wrap = "top", true
		if format, ok := sheet.NumberFormats[c]; ok {
			k.numFmt = format
		}
	}
	name := sheet.RowStyles[r]
	if name != "" {
		k = ledgerStyle(k, name)
		if format, ok := sheet.NumberFormats[c]; ok {
			k.numFmt = format
		}
	}
	if h, ok := sheet.Align[c]; ok && name != RowTitle && name != RowCaption {
		// _aligned: the horizontal set, the vertical and wrap kept.
		if k.vertical == "" {
			k.vertical = "top"
		}
		k.horizontal = h
	}
	return k
}

// ledgerStyle is ledger_styles()[name] set over the cell.
func ledgerStyle(k xfKey, name string) xfKey {
	middle := func(k xfKey) xfKey { k.vertical, k.wrap, k.horizontal = "center", false, ""; return k }
	switch name {
	case RowTitle:
		k = middle(k)
		k.font, k.fill, k.border = fontKey{bold: true, size: 13, color: headerFill}, paper, borderKey{}
	case RowCaption:
		k = middle(k)
		k.font, k.fill, k.border = fontKey{size: 9, color: captionInk}, paper, borderKey{}
		k.wrapSet = true
	case RowBand:
		k = middle(k)
		k.font, k.fill, k.border = fontKey{bold: true, italic: true, size: 10, color: ledgerInk}, ledgerBand, borderKey{}
	case RowColumns:
		k = middle(k)
		k.font, k.fill, k.border = fontKey{bold: true, size: 10, color: ledgerInk}, ledgerBand, borderKey{}
	case RowSubtotal:
		k = middle(k)
		k.font, k.fill, k.border = fontKey{bold: true, size: 10}, ledgerSubtotal, borderKey{style: "thin", color: rowRule}
	case RowTotal:
		k = middle(k)
		k.font, k.fill, k.border = fontKey{bold: true, size: 11, color: ledgerInk}, ledgerBand, borderKey{}
	}
	return k
}
