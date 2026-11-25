// Package budgetexport is budget_export_view: the Budget as a workbook, the
// planned activities whose days fall in the drawer's period (else the
// page's year) and their budget, read from the lines the Budget page sums.
package budgetexport

import (
	"context"
	"net/url"
	"strconv"
	"strings"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/budgetpage"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/myplan"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/workbook"
)

// Export answers /budget/export.
func Export(db schooldirectory.Querier, now func() time.Time) func(context.Context, auth.Principal, url.Values) (string, []workbook.Sheet, bool, error) {
	return func(ctx context.Context, p auth.Principal, query url.Values) (string, []workbook.Sheet, bool, error) {
		if err := budgetpage.ExportGate(p.ActiveRole); err != nil {
			return "", nil, true, err
		}
		at := now()
		fy := last(query, "fy")
		if fy == "" {
			fy = schooldirectory.OperationalFY(at)
		}
		fyN, err := strconv.Atoi(fy)
		if err != nil || len(fy) != 4 {
			return "", nil, false, nil
		}
		start, end, _ := myplan.DrawerPeriod(query, fyN)
		kind := myplan.ReadExportKind(query)
		status := strings.ToLower(last(query, "status"))
		lines, ok, err := budgetpage.ExportLines(ctx, db, p, query, start, end, at)
		if err != nil || !ok {
			return "", nil, ok, err
		}
		kept := []budgetpage.ExportLine{}
		for _, l := range lines {
			if !myplan.KeepsKind(kind, l.ActivityType, l.Mode == "online") {
				continue
			}
			if status != "" && status != "all" && !myplan.KeepsStatus(status, l.Status) {
				continue
			}
			kept = append(kept, l)
		}
		stem := "budget-" + start.Format(time.DateOnly) + "-to-" + end.Format(time.DateOnly)
		if budgetpage.IsSchoolList(kind) {
			ids := make([]string, 0, len(kept))
			for _, l := range kept {
				ids = append(ids, l.ActivityID)
			}
			sheets, ported, err := myplan.TableSheets(ctx, db, p.Country, ids, kind, at, false)
			if err != nil || !ported {
				return "", nil, ported, err
			}
			return stem + "-" + strings.ReplaceAll(kind, "_", "-"), sheets, true, nil
		}
		day := func(t time.Time) string { return strconv.Itoa(t.Day()) + " " + t.Format("Jan 2006") }
		period := "Period: " + day(start) + " – " + day(end)
		if kind != "all" {
			period += " · " + budgetpage.ExportKindLabel(kind)
			stem += "-" + strings.ReplaceAll(kind, "_", "-")
		}
		if status != "" && status != "all" {
			period += " · " + budgetpage.ExportStatusLabel(status)
			stem += "-" + status
		}
		sheets, err := budgetpage.ExportBook(ctx, db, kept, period)
		if err != nil {
			return "", nil, true, err
		}
		return stem, sheets, true, nil
	}
}

func last(q url.Values, key string) string {
	vs := q[key]
	if len(vs) == 0 {
		return ""
	}
	return strings.TrimSpace(vs[len(vs)-1])
}
