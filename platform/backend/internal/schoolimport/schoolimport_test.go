package schoolimport

import (
	"archive/zip"
	"bytes"
	"errors"
	"strings"
	"testing"
)

func xlsx(t *testing.T, parts map[string]string) []byte {
	t.Helper()
	var buf bytes.Buffer
	w := zip.NewWriter(&buf)
	for name, body := range parts {
		f, err := w.Create(name)
		if err != nil {
			t.Fatal(err)
		}
		if _, err := f.Write([]byte(body)); err != nil {
			t.Fatal(err)
		}
	}
	if err := w.Close(); err != nil {
		t.Fatal(err)
	}
	return buf.Bytes()
}

const workbook = `<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
 xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>
 <sheet name="Schools" sheetId="1" r:id="rId1"/></sheets></workbook>`

const rels = `<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
 <Relationship Id="rId1" Type="worksheet" Target="worksheets/sheet1.xml"/></Relationships>`

func TestReadingAFile(t *testing.T) {
	csvSheet, err := Read("schools.CSV", []byte("\uFEFFSchool ID,School Name\nS1,\"Hope, Primary\"\n"))
	if err != nil {
		t.Fatal(err)
	}
	if csvSheet.Headers[0] != "School ID" || len(csvSheet.Rows) != 1 || csvSheet.Rows[0].Line != 2 || csvSheet.Rows[0].Cells[1] != "Hope, Primary" {
		t.Errorf("the CSV: %+v", csvSheet)
	}

	// Shared and inline text, a number, a skipped column and a skipped row.
	content := xlsx(t, map[string]string{
		"xl/workbook.xml":            workbook,
		"xl/_rels/workbook.xml.rels": rels,
		"xl/sharedStrings.xml":       `<sst><si><t>School ID</t></si><si><r><t>School </t></r><r><t>Name</t></r></si><si><t>Hope</t></si></sst>`,
		"xl/worksheets/sheet1.xml": `<worksheet><sheetData>
 <row r="1"><c r="A1" t="s"><v>0</v></c><c r="C1" t="s"><v>1</v></c></row>
 <row r="3"><c r="A3"><v>1001</v></c><c r="C3" t="inlineStr"><is><t>Hope</t></is></c></row>
 </sheetData></worksheet>`,
	})
	sheet, err := Read("schools.xlsx", content)
	if err != nil {
		t.Fatal(err)
	}
	if strings.Join(sheet.Headers, "|") != "School ID||School Name" {
		t.Errorf("the XLSX headers: %q", sheet.Headers)
	}
	if len(sheet.Rows) != 2 || sheet.Rows[1].Line != 3 || strings.Join(sheet.Rows[1].Cells, "|") != "1001||Hope" {
		t.Errorf("the XLSX rows: %+v", sheet.Rows)
	}

	var refused ErrFile
	for name, bad := range map[string]struct {
		name    string
		content []byte
	}{
		"an empty file":            {"a.csv", nil},
		"another kind of file":     {"a.pdf", []byte("x")},
		"a file too large":         {"a.csv", bytes.Repeat([]byte("a"), MostBytes+1)},
		"not a zip":                {"a.xlsx", []byte("not a zip")},
		"a workbook with no sheet": {"a.xlsx", xlsx(t, map[string]string{"xl/workbook.xml": `<workbook/>`, "xl/_rels/workbook.xml.rels": rels})},
		"text the file does not hold": {"a.xlsx", xlsx(t, map[string]string{"xl/workbook.xml": workbook, "xl/_rels/workbook.xml.rels": rels,
			"xl/worksheets/sheet1.xml": `<worksheet><sheetData><row r="1"><c r="A1" t="s"><v>7</v></c></row></sheetData></worksheet>`})},
		"too many rows": {"a.csv", []byte("School ID\n" + strings.Repeat("x\n", MostRows+1))},
	} {
		if _, err := Read(bad.name, bad.content); !errors.As(err, &refused) {
			t.Errorf("%s: %v", name, err)
		}
	}
}

// A small country: two regions, a district in each named alike, and a
// sub-county; the region is required.
func place() *Place {
	p := &Place{
		Levels: []Level{
			{ID: "tR", Canonical: "region", Label: "Region", Number: 1, Required: true},
			{ID: "tD", Canonical: "district", Label: "District", Number: 3},
			{ID: "tS", Canonical: "sub_county", Label: "Sub-county", Number: 5},
		},
		units: []unit{
			{id: "central", typeID: "tR", name: "Central"},
			{id: "west", typeID: "tR", name: "Western"},
			{id: "subr", typeID: "tX", parentID: "central", name: "Buganda"},
			{id: "kla", typeID: "tD", parentID: "subr", name: "Kampala"},
			{id: "kla2", typeID: "tD", parentID: "west", name: "Kampala"},
			{id: "nak", typeID: "tS", parentID: "kla", name: "Nakawa"},
		},
		byID: map[string]unit{}, byName: map[string]map[string][]unit{},
		held:  map[string]bool{"S-HERE": true, "S-ABROAD": false},
		names: map[string]bool{"hope primary": true},
	}
	for _, u := range p.units {
		p.byID[u.id] = u
		if p.byName[u.typeID] == nil {
			p.byName[u.typeID] = map[string][]unit{}
		}
		p.byName[u.typeID][lookupKey(u.name)] = append(p.byName[u.typeID][lookupKey(u.name)], u)
	}
	return p
}

func TestPreviewingASchoolList(t *testing.T) {
	sheet := Sheet{
		Headers: []string{"School ID", "School Name", "Region", "District", "Sub County", "EMIS Number", "Current Partner Type"},
		Rows: []Row{
			{2, []string{"S1", "New School", "central", "KAMPALA", "Nakawa", "E1", "Core"}},
			{3, []string{"S-HERE", "Held School", "Central", "", "", "", ""}},
			{4, []string{"S1", "Again", "Central", "", "", "", ""}},
			{5, []string{"", "No ID", "Central", "", "", "", ""}},
			{6, []string{"S2", "Hope Primary", "Western", "Kampala", "Nakawa", "E1", "Unknown"}},
			{7, []string{"S3", "Nowhere", "Eastern", "", "", "", ""}},
			{8, []string{"S4", "Two Kampalas", "", "Kampala", "", "", ""}},
			{9, []string{"S-ABROAD", "Abroad", "Central", "", "", "", ""}},
			{10, []string{"", "", "", "", "", "", ""}},
		},
	}
	got, err := Preview(sheet, place())
	if err != nil {
		t.Fatal(err)
	}
	want := []struct {
		status, units, message string
	}{
		{Ready, "Central/Kampala/Nakawa", ""},
		{Existing, "Central", ""},
		{Duplicate, "Central", "already on line 2"},
		{Rejected, "Central", "Missing School ID"},
		{Ready, "Western/Kampala", "already has this name"},
		{Rejected, "", "Region 'Eastern' was not found"},
		{Rejected, "", "matches 2 units"},
		{Rejected, "Central", "another country"},
		{Skipped, "", ""},
	}
	for i, w := range want {
		r := got.Rows[i]
		if r.Status != w.status || strings.Join(r.Units, "/") != w.units ||
			(w.message != "" && !strings.Contains(strings.Join(r.Messages, "; "), w.message)) {
			t.Errorf("line %d: %s in %q, %q; want %s in %q with %q", r.Line, r.Status, r.Units, r.Messages, w.status, w.units, w.message)
		}
	}
	// The sub-county under the western Kampala is not there, the national ID
	// repeats, the type is unknown, and the School ID stays the file's.
	western := strings.Join(got.Rows[4].Messages, "; ")
	for _, m := range []string{"Sub-county 'Nakawa' was not found in Kampala", "National school ID E1 is also on line 2", "Client is assumed"} {
		if !strings.Contains(western, m) {
			t.Errorf("line 6 lacks %q: %s", m, western)
		}
	}
	if got.Rows[0].NationalID != "E1" || got.Rows[0].SchoolID != "S1" || got.Rows[0].SchoolType != "core" {
		t.Errorf("line 2: %+v", got.Rows[0])
	}
	if got.Counts[Ready] != 2 || got.Counts[Existing] != 1 || got.Counts[Duplicate] != 1 || got.Counts[Rejected] != 4 || got.Counts[Skipped] != 1 {
		t.Errorf("counts: %v", got.Counts)
	}
	if got.Columns[4].TakenAs != "Sub-county" || got.Columns[5].TakenAs != "national_id" {
		t.Errorf("columns: %+v", got.Columns)
	}
	if ids := SchoolIDs(sheet); strings.Join(ids, ",") != "S1,S-HERE,S2,S3,S4,S-ABROAD" {
		t.Errorf("School IDs: %v", ids)
	}

	if _, err := Preview(Sheet{Headers: []string{"School Name"}}, place()); err == nil {
		t.Error("a file with no School ID column: previewed")
	}
}
