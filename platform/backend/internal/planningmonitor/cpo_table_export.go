package planningmonitor

import (
	"context"
	"net/url"
	"regexp"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/myplan"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pageaccess"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pagegate"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/workbook"
)

// A consolidated table as a workbook (country_oversight_views
// .table_export_view with tables.sheet): every row, every column, the
// workbook-only ones included; `all` is the tables Impact Assessment asked
// for in one workbook, a sheet each.

// cpoWorkbookTables are tables.WORKBOOK.
var cpoWorkbookTables = []string{"plans", "all-visits", "partners", "projects", "project-partners", "project-activities", "not-planned"}

// cpoFigureFormats are _FIGURE_FORMATS, by a column's kind.
var cpoFigureFormats = map[string]string{"score": "0.0#", "change": "[Color10]+0.0#;[Red]-0.0#;0.0#", "money": "#,##0"}

var cpoTableExportTarget = regexp.MustCompile(`^/country-planning-oversight/table-export/([a-z-]{1,40})$`)

// tableNotFound is the view's Http404.
type tableNotFound struct{}

func (tableNotFound) Error() string  { return "Not found." }
func (tableNotFound) NotFound() bool { return true }

// CountryTableExportRoute names the export for its target, or none.
func CountryTableExportRoute(db schooldirectory.Querier, now func() time.Time) func(string) (func(context.Context, auth.Principal, url.Values) (string, []workbook.Sheet, bool, error), bool) {
	return func(target string) (func(context.Context, auth.Principal, url.Values) (string, []workbook.Sheet, bool, error), bool) {
		m := cpoTableExportTarget.FindStringSubmatch(target)
		if m == nil {
			return nil, false
		}
		return func(ctx context.Context, p auth.Principal, query url.Values) (string, []workbook.Sheet, bool, error) {
			return countryTableExport(ctx, db, p, m[1], query, now())
		}, true
	}
}

func countryTableExport(ctx context.Context, db schooldirectory.Querier, p auth.Principal, key string, query url.Values,
	now time.Time) (string, []workbook.Sheet, bool, error) {
	if !pageaccess.CanOpen(p.ActiveRole, false, cpoPath+"table-export/"+key) {
		return "", nil, true, pagegate.ErrNotAvailable
	}
	keys := []string{key}
	if key == "all" {
		keys = cpoWorkbookTables
	}
	for _, k := range keys {
		if _, ok := cpoSpec(k); !ok {
			return "", nil, true, tableNotFound{}
		}
	}
	scope, err := schooldirectory.ResolveScope(ctx, db, p, now)
	if err != nil {
		return "", nil, true, err
	}
	if scope.SummaryOnly {
		return "", nil, true, tableNotFound{}
	}
	for _, k := range keys {
		if !tablesDrawn[k] {
			return "", nil, false, nil
		}
	}
	q := map[string]string{}
	for k, v := range query {
		if len(v) > 0 {
			q[k] = v[len(v)-1]
		}
	}
	l := now.In(cpoLocation)
	today := date(l.Year(), l.Month(), l.Day())
	f, e := cpoReadFilters(q, today), cpoReadExtra(q)
	snap, err := buildCPOSnapshot(ctx, db, scope, f, today)
	if err != nil {
		return "", nil, true, err
	}
	places, err := loadPlaces(ctx, db, snap)
	if err != nil {
		return "", nil, true, err
	}
	sheets := []workbook.Sheet{}
	for _, k := range keys {
		t, ok, err := buildTable(ctx, db, snap, places, k, e)
		if err != nil || !ok {
			return "", nil, err != nil, err
		}
		sheet, err := cpoSheet(ctx, db, t)
		if err != nil {
			return "", nil, true, err
		}
		sheets = append(sheets, sheet)
	}
	return "country-" + key + "-" + f.fy + "-" + today.Format(time.DateOnly), sheets, true, nil
}

// cpoSheet is tables.sheet: the whole table, details included, a date
// column's empty day saying its note or the column's own blank.
func cpoSheet(ctx context.Context, db schooldirectory.Querier, t cpoTable) (workbook.Sheet, error) {
	columns := t.spec.Columns
	for _, c := range columns {
		if c.Key != "district_type" {
			continue
		}
		ids := []string{}
		for _, r := range t.rows {
			if id, _ := r["_activity"].(string); id != "" {
				ids = append(ids, id)
			}
		}
		labels, err := myplan.DistrictTypeLabels(ctx, db, ids)
		if err != nil {
			return workbook.Sheet{}, err
		}
		for _, r := range t.rows {
			id, _ := r["_activity"].(string)
			r["district_type"] = labels[id]
		}
		break
	}
	headers := make([]string, len(columns))
	formats := map[int]string{}
	for i, c := range columns {
		headers[i] = c.Label
		switch {
		case c.IsDate:
			formats[i+1] = "d mmm yyyy"
		case cpoFigureFormats[c.Kind] != "":
			formats[i+1] = cpoFigureFormats[c.Kind]
		}
	}
	rows := make([][]workbook.Cell, 0, len(t.rows))
	for _, r := range t.rows {
		cells := make([]workbook.Cell, len(columns))
		for i, c := range columns {
			cells[i] = cpoCell(c, r)
		}
		rows = append(rows, cells)
	}
	return workbook.Sheet{Title: t.spec.Title, Headers: headers, Rows: rows, NumberFormats: formats}, nil
}

// cpoCell is sheet's cell: the value, or _blank for none.
func cpoCell(c cpoColumn, r cpoRow) workbook.Cell {
	blank := func() workbook.Cell {
		if !c.IsDate {
			return workbook.Text("")
		}
		if note, _ := r[c.Key+"_note"].(string); note != "" {
			return workbook.Text(note)
		}
		return workbook.Text(c.Blank)
	}
	switch v := r[c.Key].(type) {
	case nil:
		return blank()
	case time.Time:
		return workbook.Date(v)
	case *time.Time:
		if v == nil {
			return blank()
		}
		return workbook.Date(*v)
	case string:
		return workbook.Text(v)
	case int:
		return workbook.Int(int64(v))
	case int64:
		return workbook.Int(v)
	case float64:
		return workbook.Number(v)
	case *float64:
		if v == nil {
			return blank()
		}
		return workbook.Number(*v)
	case *int:
		if v == nil {
			return blank()
		}
		return workbook.Int(int64(*v))
	case bool:
		if v {
			return workbook.Text("True")
		}
		return workbook.Text("False")
	}
	return workbook.Text("")
}
