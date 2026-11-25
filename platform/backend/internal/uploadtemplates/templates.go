// Package uploadtemplates serves the files an upload reads: the SSA scores
// template, the learning results template and the strategic priorities
// import template, each behind its view's own doors (export_upload_template_rules).
package uploadtemplates

import (
	"bytes"
	"context"
	_ "embed"
	"encoding/csv"
	"encoding/json"
	"fmt"
	"net/url"
	"strconv"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pagegate"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/workbook"
)

//go:embed rules.json
var rulesJSON []byte

type door struct {
	SSAPage          bool `json:"ssa_page"`
	SSAUpload        bool `json:"ssa_upload"`
	EvidencePage     bool `json:"evidence_page"`
	TargetsPage      bool `json:"targets_page"`
	PrioritiesImport bool `json:"priorities_import"`
}

var rules = func() (r struct {
	Doors            map[string]door `json:"doors"`
	SSARefusal       string          `json:"ssa_refusal"`
	SSAInterventions []string        `json:"ssa_interventions"`
	LearningColumns  []string        `json:"learning_columns"`
	PriorityTemplate string          `json:"priority_template"`
}) {
	if err := json.Unmarshal(rulesJSON, &r); err != nil {
		panic(fmt.Sprintf("uploadtemplates: rules.json: %v", err))
	}
	if len(r.Doors) == 0 || len(r.SSAInterventions) == 0 || len(r.LearningColumns) == 0 || r.PriorityTemplate == "" {
		panic("uploadtemplates: rules.json lacks its doors or columns")
	}
	return r
}()

// targetsRefusal is the target distribution views' _permission refusal.
const targetsRefusal = "Target distribution access denied."

// File is one template download, as the quick export serves a file.
type File func(ctx context.Context, p auth.Principal, query url.Values) (string, []byte, bool, error)

// Files are the templates by the path each is downloaded from.
func Files(now func() time.Time) map[string]File {
	return map[string]File{
		"/ssa/upload/template": func(_ context.Context, p auth.Principal, _ url.Values) (string, []byte, bool, error) {
			d := rules.Doors[p.ActiveRole]
			switch {
			case !d.SSAPage:
				return "", nil, true, pagegate.ErrNotAvailable
			case !d.SSAUpload:
				return "", nil, true, workbook.Refusal(rules.SSARefusal)
			}
			body, err := ssaTemplate(now())
			return "ssa_upload_template.csv", body, true, err
		},
		"/ia/school-evidence/learning/template.csv": func(_ context.Context, p auth.Principal, _ url.Values) (string, []byte, bool, error) {
			if !rules.Doors[p.ActiveRole].EvidencePage {
				return "", nil, true, pagegate.ErrNotAvailable
			}
			body, err := learningTemplate(now())
			return "learning_results_template.csv", body, true, err
		},
		"/target-distribution/import/template": func(_ context.Context, p auth.Principal, _ url.Values) (string, []byte, bool, error) {
			d := rules.Doors[p.ActiveRole]
			switch {
			case !d.TargetsPage:
				return "", nil, true, pagegate.ErrNotAvailable
			case !d.PrioritiesImport:
				return "", nil, true, workbook.Refusal(targetsRefusal)
			}
			return "edify-priority-import.csv", []byte(rules.PriorityTemplate), true, nil
		},
	}
}

func writeRows(rows ...[]string) ([]byte, error) {
	var buf bytes.Buffer
	w := csv.NewWriter(&buf)
	w.UseCRLF = true
	for _, row := range rows {
		cells := make([]workbook.Cell, len(row))
		for i, v := range row {
			cells[i] = workbook.Text(v)
		}
		if err := w.Write(workbook.SafeCSVRow(cells)); err != nil {
			return nil, err
		}
	}
	w.Flush()
	return buf.Bytes(), w.Error()
}

// ssaTemplate is ssa_template_download_view: the columns, then a baseline
// row for last year and a row for the running year.
func ssaTemplate(now time.Time) ([]byte, error) {
	current := schooldirectory.OperationalFY(now)
	n, _ := strconv.Atoi(current)
	prev := strconv.Itoa(n - 1)
	headers := []string{"School ID", "Assessment Date", "SSA Year"}
	before := []string{"SCH-0001", prev + "-06-15", prev}
	after := []string{"SCH-0001", current + "-07-01", current}
	for _, label := range rules.SSAInterventions {
		headers = append(headers, label+" (0-10)")
		before = append(before, "6.0")
		after = append(after, "7.5")
	}
	return writeRows(headers, before, after)
}

// learningTemplate is learning_template_csv: the columns and one sample.
func learningTemplate(now time.Time) ([]byte, error) {
	n, _ := strconv.Atoi(schooldirectory.OperationalFY(now))
	day := strconv.Itoa(n-1) + "-11-15"
	return writeRows(rules.LearningColumns,
		[]string{"SCH-0001", "onetest", day, "P6", "Literacy", "42", "54.5", "100", "18", "", ""})
}
