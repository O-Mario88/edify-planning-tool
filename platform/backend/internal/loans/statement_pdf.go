package loans

import (
	"bytes"
	"fmt"
	"strings"
)

// A small PDF writer for school statements: A4 pages of plain text in the
// two standard fonts every PDF reader has (Helvetica for words, Courier for
// figures so amounts line up exactly). No dependency, no embedded fonts.

const (
	pdfWidth, pdfHeight = 595, 842 // A4 in points
	pdfMargin           = 42
	pdfLeading          = 13
	courierAdvance      = 0.6 // Courier: every glyph is 600/1000 em
)

type pdfLine struct {
	font  string // "F1" Helvetica, "F2" Helvetica-Bold, "F3" Courier
	size  float64
	text  string
	gap   float64 // extra space before the line
	right bool    // a Courier line set flush right
}

type pdfDoc struct{ lines []pdfLine }

func (d *pdfDoc) title(text string) { d.lines = append(d.lines, pdfLine{"F2", 15, text, 0, false}) }

func (d *pdfDoc) heading(text string) { d.lines = append(d.lines, pdfLine{"F2", 11, text, 10, false}) }

func (d *pdfDoc) text(text string) { d.lines = append(d.lines, pdfLine{"F1", 9.5, text, 0, false}) }

func (d *pdfDoc) mono(text string) { d.lines = append(d.lines, pdfLine{"F3", 8, text, 0, false}) }

// pdfText keeps what Helvetica's standard encoding can show and escapes the
// rest of PDF's string syntax.
func pdfText(raw string) string {
	var b strings.Builder
	for _, r := range raw {
		switch {
		case r == '(' || r == ')' || r == '\\':
			b.WriteByte('\\')
			b.WriteRune(r)
		case r == '—' || r == '–' || r == '−':
			b.WriteByte('-')
		case r == '·':
			b.WriteByte('|')
		case r < 32:
		case r < 127:
			b.WriteRune(r)
		default:
			b.WriteByte('?')
		}
	}
	return b.String()
}

// wrap breaks text into lines of at most width characters.
func wrap(text string, width int) []string {
	var out []string
	for _, paragraph := range strings.Split(text, "\n") {
		words, current := strings.Fields(paragraph), ""
		for _, word := range words {
			if current != "" && len(current)+1+len(word) > width {
				out = append(out, current)
				current = ""
			}
			if current != "" {
				current += " "
			}
			current += word
		}
		out = append(out, current)
	}
	return out
}

// bytes lays the lines out on pages, with a footer on each.
func (d *pdfDoc) bytes(footer string) []byte {
	var pages [][]string
	var stream []string
	y := float64(pdfHeight - pdfMargin)
	flush := func() {
		stream = append(stream, fmt.Sprintf("BT /F1 7.5 Tf %d %d Td (%s) Tj ET", pdfMargin, pdfMargin-16,
			pdfText(fmt.Sprintf("%s | page %d", footer, len(pages)+1))))
		pages = append(pages, stream)
		stream, y = nil, float64(pdfHeight-pdfMargin)
	}
	for _, l := range d.lines {
		step := l.gap + max(l.size*1.35, pdfLeading-2)
		if y-step < pdfMargin {
			flush()
		}
		y -= step
		x := float64(pdfMargin)
		if l.right {
			x = pdfWidth - pdfMargin - float64(len(l.text))*l.size*courierAdvance
		}
		stream = append(stream, fmt.Sprintf("BT /%s %.1f Tf %.1f %.1f Td (%s) Tj ET", l.font, l.size, x, y, pdfText(l.text)))
	}
	flush()

	var out bytes.Buffer
	var offsets []int
	object := func(body string) {
		offsets = append(offsets, out.Len())
		fmt.Fprintf(&out, "%d 0 obj\n%s\nendobj\n", len(offsets), body)
	}
	out.WriteString("%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
	// 1 catalog, 2 page tree, 3-5 fonts, then a page and its content per page.
	kids := make([]string, len(pages))
	for i := range pages {
		kids[i] = fmt.Sprintf("%d 0 R", 6+i*2)
	}
	object("<< /Type /Catalog /Pages 2 0 R >>")
	object(fmt.Sprintf("<< /Type /Pages /Kids [%s] /Count %d >>", strings.Join(kids, " "), len(pages)))
	object("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
	object("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>")
	object("<< /Type /Font /Subtype /Type1 /BaseFont /Courier /Encoding /WinAnsiEncoding >>")
	for i, page := range pages {
		object(fmt.Sprintf("<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %d %d] /Resources << /Font << /F1 3 0 R /F2 4 0 R /F3 5 0 R >> >> /Contents %d 0 R >>",
			pdfWidth, pdfHeight, 7+i*2))
		content := strings.Join(page, "\n")
		object(fmt.Sprintf("<< /Length %d >>\nstream\n%s\nendstream", len(content), content))
	}
	start := out.Len()
	fmt.Fprintf(&out, "xref\n0 %d\n0000000000 65535 f \n", len(offsets)+1)
	for _, offset := range offsets {
		fmt.Fprintf(&out, "%010d 00000 n \n", offset)
	}
	fmt.Fprintf(&out, "trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n", len(offsets)+1, start)
	return out.Bytes()
}

// columns sets cells in fixed-width Courier columns; widths below zero are
// right-aligned (figures).
func columns(widths []int, cells ...string) string {
	var b strings.Builder
	for i, cell := range cells {
		width := widths[i]
		align := "%-*s"
		if width < 0 {
			width, align = -width, "%*s"
		}
		if len(cell) > width {
			cell = cell[:width-1] + "."
		}
		fmt.Fprintf(&b, align+" ", width, cell)
	}
	return strings.TrimRight(b.String(), " ")
}
