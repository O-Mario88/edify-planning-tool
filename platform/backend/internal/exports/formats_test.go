package exports

import (
	"archive/zip"
	"bytes"
	"strings"
	"testing"
	"time"
)

func TestBuildXLSXProducesValidOOXMLArchive(t *testing.T) {
	data, err := BuildXLSX("school_directory",
		[]string{"edify_school_id", "school_name", "district"},
		[][]string{
			{"UG-0001", "Grace & Hope Academy", "Kampala"},
			{"UG-0002", "St. Paul's <Primary>", "Mukono"},
		},
	)
	if err != nil {
		t.Fatalf("BuildXLSX failed: %v", err)
	}
	zr, err := zip.NewReader(bytes.NewReader(data), int64(len(data)))
	if err != nil {
		t.Fatalf("XLSX is not a valid ZIP archive: %v", err)
	}
	seen := map[string]bool{}
	for _, f := range zr.File {
		seen[f.Name] = true
	}
	for _, want := range []string{"[Content_Types].xml", "_rels/.rels", "xl/workbook.xml", "xl/styles.xml", "xl/worksheets/sheet1.xml"} {
		if !seen[want] {
			t.Fatalf("missing OOXML entry %s (got %v)", want, seen)
		}
	}
}

func TestBuildPDFProducesValidMultiPagePDF14(t *testing.T) {
	rows := make([][]string, 45)
	for i := range rows {
		rows[i] = []string{"UG-0001", "Test School (Central)", "Kampala", "core"}
	}
	data, err := BuildPDF("Edify Schools Export", "FY 2027",
		[]string{"School ID", "School Name", "District", "Cohort"}, rows)
	if err != nil {
		t.Fatalf("BuildPDF failed: %v", err)
	}
	s := string(data)
	if !strings.HasPrefix(s, "%PDF-1.4\n") {
		t.Fatalf("missing PDF 1.4 header")
	}
	if !strings.Contains(s, "/Count 2") {
		t.Fatalf("expected 2 pages for 45 rows, got:\n%s", s[:min(len(s), 400)])
	}
	if !strings.HasSuffix(strings.TrimSpace(s), "%%EOF") {
		t.Fatalf("missing %%EOF trailer")
	}
}

func TestConvertCSVPayloadFormats(t *testing.T) {
	sample := []byte("edify_school_id,school_name\nUG-100,Hope Primary\n")
	now := time.Date(2026, 11, 22, 12, 0, 0, 0, time.UTC)

	xlsx, err := convertCSVPayload("school_directory", FormatXLSX, now, sample)
	if err != nil || len(xlsx) < 200 {
		t.Fatalf("xlsx convert failed: err=%v len=%d", err, len(xlsx))
	}
	pdf, err := convertCSVPayload("school_directory", FormatPDF, now, sample)
	if err != nil || !bytes.HasPrefix(pdf, []byte("%PDF-1.4")) {
		t.Fatalf("pdf convert failed: err=%v len=%d", err, len(pdf))
	}
}
