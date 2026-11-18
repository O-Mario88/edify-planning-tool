// Package schoolimport previews a country's school list before anything is
// imported (docs/migration/80 §8 Phase 2, §27): it reads a CSV or XLSX file,
// places each row in the country's own geography (the registry, §25), and
// says which rows are ready, which name a school already held, which repeat
// another row, and which are rejected and why. It writes nothing: a preview
// is a dry run.
//
// A school keeps the School ID the file gives it; a national school ID
// (EMIS and the like) is read into its own field and never replaces it.
package schoolimport

import (
	"archive/zip"
	"bytes"
	"encoding/csv"
	"encoding/xml"
	"errors"
	"fmt"
	"io"
	"path"
	"strconv"
	"strings"
)

const (
	// MostBytes is the largest file read (the gateway takes requests up to
	// 1 MiB, the file with them).
	MostBytes = 900 << 10
	// MostRows is the most data rows a file may hold.
	MostRows = 10_000
	// mostCells is the most columns a row may hold.
	mostCells = 200
	// mostUnpacked is the most an XLSX part may expand to, so a small file
	// cannot unpack into a huge one.
	mostUnpacked = 40 << 20
)

// ErrFile is a file that cannot be read as a school list; its message says
// why, for the person who uploaded it.
type ErrFile string

func (e ErrFile) Error() string { return string(e) }

// Sheet is a file's header row and its data rows, each with the line it
// was on.
type Sheet struct {
	Headers []string
	Rows    []Row
}

// Row is one data row: its line in the file (the header is line 1) and its
// cells.
type Row struct {
	Line  int
	Cells []string
}

// Read reads a school list from a .csv or .xlsx file named name.
func Read(name string, content []byte) (Sheet, error) {
	if len(content) == 0 {
		return Sheet{}, ErrFile("The file is empty.")
	}
	if len(content) > MostBytes {
		return Sheet{}, ErrFile(fmt.Sprintf("The file is larger than %d KB.", MostBytes>>10))
	}
	var records [][]string
	var err error
	switch strings.ToLower(path.Ext(strings.TrimSpace(name))) {
	case ".csv":
		records, err = readCSV(content)
	case ".xlsx":
		records, err = readXLSX(content)
	default:
		return Sheet{}, ErrFile("Upload a .csv or .xlsx file.")
	}
	if err != nil {
		return Sheet{}, err
	}
	if len(records) == 0 {
		return Sheet{}, ErrFile("The file is empty: no header row was found.")
	}
	if len(records)-1 > MostRows {
		return Sheet{}, ErrFile(fmt.Sprintf("The file has more than %d rows.", MostRows))
	}
	out := Sheet{Headers: records[0], Rows: make([]Row, 0, len(records)-1)}
	for i, cells := range records[1:] {
		if len(cells) > mostCells {
			return Sheet{}, ErrFile(fmt.Sprintf("Line %d has more than %d columns.", i+2, mostCells))
		}
		out.Rows = append(out.Rows, Row{Line: i + 2, Cells: cells})
	}
	return out, nil
}

func readCSV(content []byte) ([][]string, error) {
	r := csv.NewReader(bytes.NewReader(bytes.TrimPrefix(content, []byte("\uFEFF"))))
	r.FieldsPerRecord = -1
	r.LazyQuotes = true
	var out [][]string
	for {
		record, err := r.Read()
		if errors.Is(err, io.EOF) {
			return out, nil
		}
		if err != nil {
			return nil, ErrFile("The CSV file could not be read: " + err.Error())
		}
		if len(out) > MostRows+1 {
			return nil, ErrFile(fmt.Sprintf("The file has more than %d rows.", MostRows))
		}
		out = append(out, record)
	}
}

// The parts of an XLSX file the first worksheet is read from.
type (
	xlsxWorkbook struct {
		Sheets []struct {
			RelID string `xml:"http://schemas.openxmlformats.org/officeDocument/2006/relationships id,attr"`
		} `xml:"sheets>sheet"`
	}
	xlsxRels struct {
		Rels []struct {
			ID     string `xml:"Id,attr"`
			Target string `xml:"Target,attr"`
		} `xml:"Relationship"`
	}
	xlsxStrings struct {
		Items []xlsxText `xml:"si"`
	}
	xlsxText struct {
		T    string `xml:"t"`
		Runs []struct {
			T string `xml:"t"`
		} `xml:"r"`
	}
	xlsxSheet struct {
		Rows []struct {
			R     int `xml:"r,attr"`
			Cells []struct {
				Ref    string   `xml:"r,attr"`
				Type   string   `xml:"t,attr"`
				Value  string   `xml:"v"`
				Inline xlsxText `xml:"is"`
			} `xml:"c"`
		} `xml:"sheetData>row"`
	}
)

func (t xlsxText) text() string {
	if len(t.Runs) == 0 {
		return t.T
	}
	var b strings.Builder
	for _, r := range t.Runs {
		b.WriteString(r.T)
	}
	return b.String()
}

func readXLSX(content []byte) ([][]string, error) {
	archive, err := zip.NewReader(bytes.NewReader(content), int64(len(content)))
	if err != nil {
		return nil, ErrFile("The XLSX file could not be opened.")
	}
	parts := map[string]*zip.File{}
	for _, f := range archive.File {
		parts[f.Name] = f
	}
	part := func(name string, into any) error {
		f, ok := parts[name]
		if !ok {
			return ErrFile("The XLSX file is missing " + name + ".")
		}
		if f.UncompressedSize64 > mostUnpacked {
			return ErrFile("The XLSX file unpacks to more than is allowed.")
		}
		rc, err := f.Open()
		if err != nil {
			return ErrFile("The XLSX file could not be opened.")
		}
		defer func() { _ = rc.Close() }()
		if err := xml.NewDecoder(io.LimitReader(rc, mostUnpacked)).Decode(into); err != nil {
			return ErrFile("The XLSX file could not be read.")
		}
		return nil
	}
	var book xlsxWorkbook
	if err := part("xl/workbook.xml", &book); err != nil {
		return nil, err
	}
	var rels xlsxRels
	if err := part("xl/_rels/workbook.xml.rels", &rels); err != nil {
		return nil, err
	}
	if len(book.Sheets) == 0 {
		return nil, ErrFile("The XLSX file has no worksheet.")
	}
	target := ""
	for _, r := range rels.Rels {
		if r.ID == book.Sheets[0].RelID {
			target = r.Target
		}
	}
	if target == "" {
		return nil, ErrFile("The XLSX file's first worksheet could not be found.")
	}
	if strings.HasPrefix(target, "/") {
		target = strings.TrimPrefix(target, "/")
	} else {
		target = path.Join("xl", target)
	}
	var shared xlsxStrings
	if _, ok := parts["xl/sharedStrings.xml"]; ok {
		if err := part("xl/sharedStrings.xml", &shared); err != nil {
			return nil, err
		}
	}
	var sheet xlsxSheet
	if err := part(target, &sheet); err != nil {
		return nil, err
	}
	out := [][]string{}
	for i, row := range sheet.Rows {
		if len(out) > MostRows+1 {
			return nil, ErrFile(fmt.Sprintf("The file has more than %d rows.", MostRows))
		}
		// Rows left empty in the file are not written in it: keep the lines.
		line := row.R
		if line == 0 {
			line = i + 1
		}
		for len(out) < line-1 && len(out) <= MostRows+1 {
			out = append(out, []string{})
		}
		cells := []string{}
		for j, c := range row.Cells {
			col := j
			if c.Ref != "" {
				if n, ok := column(c.Ref); ok {
					col = n
				}
			}
			if col >= mostCells {
				return nil, ErrFile(fmt.Sprintf("Line %d has more than %d columns.", line, mostCells))
			}
			for len(cells) < col {
				cells = append(cells, "")
			}
			value := c.Value
			switch c.Type {
			case "s":
				n, err := strconv.Atoi(strings.TrimSpace(c.Value))
				if err != nil || n < 0 || n >= len(shared.Items) {
					return nil, ErrFile(fmt.Sprintf("Line %d refers to text the file does not hold.", line))
				}
				value = shared.Items[n].text()
			case "inlineStr":
				value = c.Inline.text()
			}
			cells = append(cells, value)
		}
		out = append(out, cells)
	}
	return out, nil
}

// column is the zero-based column of a cell reference such as "C12".
func column(ref string) (int, bool) {
	n := 0
	letters := 0
	for _, r := range ref {
		if r < 'A' || r > 'Z' {
			break
		}
		n = n*26 + int(r-'A'+1)
		letters++
	}
	if letters == 0 || letters > 3 {
		return 0, false
	}
	return n - 1, true
}
