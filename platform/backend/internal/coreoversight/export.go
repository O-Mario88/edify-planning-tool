package coreoversight

import (
	"context"
	"errors"
	"net/url"
	"regexp"
	"strconv"
	"strings"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/myplan"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/rbac"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/workbook"
)

// Core School Oversight's two downloads (core_oversight_views
// .core_schools_oversight_view): ?format=csv, the schools the filters keep
// with their figures (_csv); and ?format=xlsx on the Core School Visits or
// Trainings tab, My Plan's sheet of that work (table_export
// .core_school_plans through table_download).

// exportRefusal is the view's render_access_denied for a role without data
// export.
const exportRefusal = "Your role does not include data export."

// csvHeaders are CSV_HEADERS.
var csvHeaders = []string{"School ID", "School", "Type", "District", "Sub-region", "Cluster", "CCEO", "Latest SSA",
	"Previous SSA", "SSA Change", "Trajectory", "Weakest Intervention", "Visits Done", "Visits Target",
	"Trainings Done", "Trainings Target", "Package", "Partner Hand-overs Assigned", "Partner Hand-overs Scheduled",
	"Partner Hand-overs Completed", "Sessions Invited", "Sessions Attended", "Attendance %", "Teacher Attendances",
	"Leader Attendances", "Enrolment Change", "Learning Change (pts)", "Champion Readiness", "Attention"}

// Export answers the page's file links; handled is false for a link that
// asks for no file, and for plan rows Go does not draw yet.
func (s *Service) Export(ctx context.Context, p auth.Principal, query url.Values) (string, []workbook.Sheet, bool, error) {
	format := query.Get("format")
	tab := choice(query, "tab", keysOf(rules.Tabs), "schools")
	if format != "csv" && (format != "xlsx" || !in(rules.PlanTabs, tab)) {
		return "", nil, false, nil
	}
	doors, ok := rules.Doors[p.ActiveRole]
	if !ok || !doors.Page || !rules.FeedOpensPage {
		return "", nil, false, nil
	}
	if !rbac.Grants(p.ActiveRole, "data.export") {
		return "", nil, true, workbook.Refusal(exportRefusal)
	}
	now := s.now()
	scope, err := schooldirectory.ResolveScope(ctx, s.db, p, now)
	if err != nil {
		return "", nil, true, err
	}
	years := yearOptions(now)
	fy := choice(query, "fy", years, schooldirectory.OperationalFY(now))
	found, err := read(ctx, s.db, scope, fy, false)
	if err != nil {
		return "", nil, true, err
	}
	shown := filtered(sortedBy(performance(found, fy, schooldirectory.OperationalFY(now)), "name"), query)
	if format == "csv" {
		return "core-school-oversight-fy" + fy, []workbook.Sheet{{Title: "Export", Headers: csvHeaders, Rows: csvRows(shown)}}, true, nil
	}
	schools := make([]myplan.CoreSchool, 0, len(shown))
	for _, r := range shown {
		schools = append(schools, myplan.CoreSchool{PK: r.id, Code: r.code})
	}
	visits, trainings, err := myplan.CoreSchoolPlans(ctx, s.db, p.Country, schools, fy, now)
	if errors.Is(err, myplan.ErrUnported) {
		return "", nil, false, nil
	}
	if err != nil {
		return "", nil, true, err
	}
	sheet := trainings
	if tab == "core_visits" {
		sheet = visits
	}
	return "core-school-oversight-" + strings.ReplaceAll(tab, "_", "-") + "-fy" + fy, []workbook.Sheet{typedPlan(sheet)}, true, nil
}

// csvRows are _csv's rows: each figure as str() writes it, nothing for none.
func csvRows(rows []*school) [][]workbook.Cell {
	dash := func(f *float64) workbook.Cell {
		if f == nil {
			return workbook.Text("")
		}
		return workbook.Text(floatStr(*f))
	}
	dashInt := func(n *int) workbook.Cell {
		if n == nil {
			return workbook.Text("")
		}
		return workbook.Text(strconv.Itoa(*n))
	}
	planned := func(r *school, n int) workbook.Cell {
		if !r.hasPlan {
			return workbook.Text("")
		}
		return workbook.Int(int64(n))
	}
	out := make([][]workbook.Cell, 0, len(rows))
	for _, r := range rows {
		out = append(out, []workbook.Cell{
			workbook.Text(r.code), workbook.Text(r.name), workbook.Text(r.typeLabel), workbook.Text(r.district),
			workbook.Text(r.subRegion), workbook.Text(r.cluster), workbook.Text(r.owner), dash(r.ssaNow), dash(r.ssaBefore),
			dash(r.ssaChange), workbook.Text(r.trajectoryLabel()), workbook.Text(r.weakestLabel),
			planned(r, r.visitsDone), planned(r, r.visitsTarget), planned(r, r.trainingsDone), planned(r, r.trainingsTarget),
			workbook.Text(r.packageLabel()), workbook.Int(int64(r.handoversAssigned)), workbook.Int(int64(r.handoversScheduled)),
			workbook.Int(int64(r.handoversCompleted)), workbook.Int(int64(r.invited)), workbook.Int(int64(r.attended)),
			dashInt(r.attendanceRate()), dashInt(r.teachers), dashInt(r.leaders), dashInt(r.enrolChange()), dash(r.learnChange()),
			workbook.Text(r.champion), workbook.Text(strings.Join(r.attention, "; ")),
		})
	}
	return out
}

// planMoney is a Cost cell as table_export.shown writes an amount.
var planMoney = regexp.MustCompile(`^UGX (\d{1,3}(?:,\d{3})*)$`)

// typedPlan is the sheet as table_export._framed hands it to the workbook:
// a date column's days as dates ("d mmm yyyy"), an amount as a number
// ('"UGX "#,##0'), the participants as a count; myplan draws the cells as
// table_export.shown writes them, which read back exactly.
func typedPlan(sheet myplan.Sheet) workbook.Sheet {
	formats := map[int]string{}
	for i, h := range sheet.Headers {
		switch {
		case strings.HasSuffix(strings.ToLower(h), "date"):
			formats[i+1] = "d mmm yyyy"
		case h == "Cost":
			formats[i+1] = `"UGX "#,##0`
		}
	}
	rows := make([][]workbook.Cell, 0, len(sheet.Rows))
	for _, r := range sheet.Rows {
		cells := make([]workbook.Cell, len(r))
		for i, v := range r {
			cells[i] = workbook.Text(v)
			switch formats[i+1] {
			case "d mmm yyyy":
				if t, err := time.Parse("2 Jan 2006", v); err == nil {
					cells[i] = workbook.Date(t)
				}
			case `"UGX "#,##0`:
				if m := planMoney.FindStringSubmatch(v); m != nil {
					n, _ := strconv.ParseInt(strings.ReplaceAll(m[1], ",", ""), 10, 64)
					cells[i] = workbook.Int(n)
				}
			}
			if sheet.Headers[i] == "Participants" {
				if n, err := strconv.Atoi(v); err == nil {
					cells[i] = workbook.Int(int64(n))
				}
			}
		}
		rows = append(rows, cells)
	}
	return workbook.Sheet{Title: sheet.Title, Headers: sheet.Headers, Rows: rows, NumberFormats: formats}
}
