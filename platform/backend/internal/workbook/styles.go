package workbook

import (
	"fmt"
	"strconv"
	"strings"
)

// The workbook's style table, built as cells ask for styles: fonts, fills,
// borders, number formats and the cell formats combining them.

type fontKey struct {
	bold, italic bool
	size         float64
	color        string
}

type borderKey struct{ style, color string }

type xfKey struct {
	numFmt               string
	font                 fontKey
	fill                 string
	border               borderKey
	horizontal, vertical string
	wrap                 bool
	// wrapSet writes wrapText="0" (the caption's wrap_text=False).
	wrapSet bool
}

type styles struct {
	fonts   []fontKey
	fills   []string
	borders []borderKey
	numFmts []string
	xfs     []xfKey
	xfIndex map[xfKey]int
}

// builtinFormats are the number formats Excel numbers itself.
var builtinFormats = map[string]int{"General": 0, "0": 1, "0.00": 2, "#,##0": 3, "#,##0.00": 4, "0%": 9, "0.00%": 10}

func newStyles() *styles {
	s := &styles{
		fonts:   []fontKey{{}},
		fills:   []string{"", "gray125"},
		borders: []borderKey{{}},
		xfIndex: map[xfKey]int{},
	}
	s.index(xfKey{})
	return s
}

func (s *styles) index(k xfKey) int {
	if i, ok := s.xfIndex[k]; ok {
		return i
	}
	s.xfs = append(s.xfs, k)
	s.xfIndex[k] = len(s.xfs) - 1
	return len(s.xfs) - 1
}

func indexOf[T comparable](list *[]T, v T) int {
	for i, x := range *list {
		if x == v {
			return i
		}
	}
	*list = append(*list, v)
	return len(*list) - 1
}

func (s *styles) numFmtID(code string) int {
	if code == "" {
		return 0
	}
	if id, ok := builtinFormats[code]; ok {
		return id
	}
	return 164 + indexOf(&s.numFmts, code)
}

func (s *styles) xml() string {
	type resolved struct{ numFmt, font, fill, border int }
	rows := make([]resolved, len(s.xfs))
	for i, k := range s.xfs {
		fill := 0
		if k.fill != "" {
			fill = indexOf(&s.fills, k.fill)
		}
		rows[i] = resolved{s.numFmtID(k.numFmt), indexOf(&s.fonts, k.font), fill, indexOf(&s.borders, k.border)}
	}
	var b strings.Builder
	b.WriteString(`<?xml version="1.0" encoding="UTF-8" standalone="yes"?><styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">`)
	if len(s.numFmts) > 0 {
		fmt.Fprintf(&b, `<numFmts count="%d">`, len(s.numFmts))
		for i, code := range s.numFmts {
			fmt.Fprintf(&b, `<numFmt numFmtId="%d" formatCode="%s"/>`, 164+i, escape(code))
		}
		b.WriteString(`</numFmts>`)
	}
	fmt.Fprintf(&b, `<fonts count="%d">`, len(s.fonts))
	for i, f := range s.fonts {
		if i == 0 {
			b.WriteString(`<font><name val="Calibri"/><family val="2"/><color theme="1"/><sz val="11"/><scheme val="minor"/></font>`)
			continue
		}
		b.WriteString(`<font>`)
		if f.bold {
			b.WriteString(`<b val="1"/>`)
		}
		if f.italic {
			b.WriteString(`<i val="1"/>`)
		}
		if f.color != "" {
			fmt.Fprintf(&b, `<color rgb="00%s"/>`, f.color)
		}
		if f.size != 0 {
			fmt.Fprintf(&b, `<sz val="%s"/>`, strconv.FormatFloat(f.size, 'f', -1, 64))
		}
		b.WriteString(`</font>`)
	}
	b.WriteString(`</fonts>`)
	fmt.Fprintf(&b, `<fills count="%d">`, len(s.fills))
	for _, fill := range s.fills {
		switch fill {
		case "":
			b.WriteString(`<fill><patternFill/></fill>`)
		case "gray125":
			b.WriteString(`<fill><patternFill patternType="gray125"/></fill>`)
		default:
			fmt.Fprintf(&b, `<fill><patternFill patternType="solid"><fgColor rgb="00%s"/><bgColor rgb="00000000"/></patternFill></fill>`, fill)
		}
	}
	b.WriteString(`</fills>`)
	fmt.Fprintf(&b, `<borders count="%d">`, len(s.borders))
	for _, border := range s.borders {
		if border.style == "" {
			b.WriteString(`<border><left/><right/><top/><bottom/><diagonal/></border>`)
			continue
		}
		fmt.Fprintf(&b, `<border><left/><right/><top/><bottom style="%s"><color rgb="00%s"/></bottom><diagonal/></border>`, border.style, border.color)
	}
	b.WriteString(`</borders><cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>`)
	fmt.Fprintf(&b, `<cellXfs count="%d">`, len(s.xfs))
	for i, k := range s.xfs {
		r := rows[i]
		fmt.Fprintf(&b, `<xf numFmtId="%d" fontId="%d" fillId="%d" borderId="%d" xfId="0"`, r.numFmt, r.font, r.fill, r.border)
		if r.numFmt != 0 {
			b.WriteString(` applyNumberFormat="1"`)
		}
		if r.font != 0 {
			b.WriteString(` applyFont="1"`)
		}
		if r.fill != 0 {
			b.WriteString(` applyFill="1"`)
		}
		if r.border != 0 {
			b.WriteString(` applyBorder="1"`)
		}
		if k.horizontal == "" && k.vertical == "" && !k.wrap && !k.wrapSet {
			b.WriteString(`/>`)
			continue
		}
		b.WriteString(` applyAlignment="1"><alignment`)
		if k.horizontal != "" {
			fmt.Fprintf(&b, ` horizontal="%s"`, k.horizontal)
		}
		if k.vertical != "" {
			fmt.Fprintf(&b, ` vertical="%s"`, k.vertical)
		}
		if k.wrap {
			b.WriteString(` wrapText="1"`)
		} else if k.wrapSet {
			b.WriteString(` wrapText="0"`)
		}
		b.WriteString(`/></xf>`)
	}
	b.WriteString(`</cellXfs><cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>`)
	return b.String()
}

const rootRels = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>`

func contentTypes(sheets int) string {
	var b strings.Builder
	b.WriteString(`<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">`)
	b.WriteString(`<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/>`)
	b.WriteString(`<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>`)
	b.WriteString(`<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>`)
	for i := 1; i <= sheets; i++ {
		fmt.Fprintf(&b, `<Override PartName="/xl/worksheets/sheet%d.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>`, i)
	}
	b.WriteString(`</Types>`)
	return b.String()
}

func workbookXML(titles []string) string {
	var b strings.Builder
	b.WriteString(`<?xml version="1.0" encoding="UTF-8" standalone="yes"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><bookViews><workbookView activeTab="0"/></bookViews><sheets>`)
	for i, title := range titles {
		fmt.Fprintf(&b, `<sheet name="%s" sheetId="%d" r:id="rId%d"/>`, escape(title), i+1, i+1)
	}
	b.WriteString(`</sheets></workbook>`)
	return b.String()
}

func workbookRels(sheets int) string {
	var b strings.Builder
	b.WriteString(`<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">`)
	for i := 1; i <= sheets; i++ {
		fmt.Fprintf(&b, `<Relationship Id="rId%d" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet%d.xml"/>`, i, i)
	}
	fmt.Fprintf(&b, `<Relationship Id="rId%d" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>`, sheets+1)
	b.WriteString(`</Relationships>`)
	return b.String()
}
