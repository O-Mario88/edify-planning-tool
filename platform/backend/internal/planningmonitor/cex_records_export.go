package planningmonitor

import (
	"context"
	"net/url"
	"regexp"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pageaccess"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pagegate"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/workbook"
)

var cexRecordsExportTarget = regexp.MustCompile(`^/country-planning-oversight/execution/records-export/([a-z_-]{1,40})$`)

// CountryExecutionRecordsExportRoute names records_export_view for its
// target: one execution table as a workbook, every row and every column.
func CountryExecutionRecordsExportRoute(db schooldirectory.Querier, now func() time.Time) func(string) (func(context.Context, auth.Principal, url.Values) (string, []workbook.Sheet, bool, error), bool) {
	return func(target string) (func(context.Context, auth.Principal, url.Values) (string, []workbook.Sheet, bool, error), bool) {
		m := cexRecordsExportTarget.FindStringSubmatch(target)
		if m == nil {
			return nil, false
		}
		return func(ctx context.Context, p auth.Principal, query url.Values) (string, []workbook.Sheet, bool, error) {
			return cexRecordsExport(ctx, db, p, m[1], query, now())
		}, true
	}
}

func cexRecordsExport(ctx context.Context, db schooldirectory.Querier, p auth.Principal, key string, query url.Values,
	now time.Time) (string, []workbook.Sheet, bool, error) {
	if !pageaccess.CanOpen(p.ActiveRole, false, cexBase+"/records-export/"+key) {
		return "", nil, true, pagegate.ErrNotAvailable
	}
	spec, ok := cexRecordsSpec(key)
	if !ok {
		return "", nil, true, tableNotFound{}
	}
	scope, err := schooldirectory.ResolveScope(ctx, db, p, now)
	if err != nil {
		return "", nil, true, err
	}
	if scope.SummaryOnly {
		return "", nil, true, tableNotFound{}
	}
	q := map[string]string{}
	for k, v := range query {
		if len(v) > 0 {
			q[k] = v[len(v)-1]
		}
	}
	l := now.In(cpoLocation)
	today := date(l.Year(), l.Month(), l.Day())
	f := cexReadFilters(q, today)
	s, err := buildCEXSnapshot(ctx, db, scope, f, today)
	if err != nil {
		return "", nil, true, err
	}
	t, err := s.recordsTable(ctx, db, spec)
	if err != nil {
		return "", nil, true, err
	}
	sheet, err := cpoSheet(ctx, db, t)
	if err != nil {
		return "", nil, true, err
	}
	return "country-execution-" + key + "-" + f.fy + "-" + today.Format(time.DateOnly), []workbook.Sheet{sheet}, true, nil
}
