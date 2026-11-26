package workplan

import (
	"context"
	"fmt"
	"net/url"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/myplan"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/rbac"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/workbook"
)

// ExportPath is the Work Plan's Export (work_plan_views.work_plan_export).
const ExportPath = "/work-plan/export.xlsx"

const exportRefusal = "You do not have permission to export."

// exportHeaders are the export's columns: the Detailed Activity Plan's, in
// its order, then the planning detail the page leaves to the record.
var exportHeaders = []string{"Activity Date", "Activity", "School ID", "School Name", "District", "District Type", "Cluster Name",
	"Activity Purpose", "SSA Intervention", "Previous SSA Score", "Delivery Mode", "Person Responsible", "Cost (UGX)",
	"Planned Period", "Status", "Activity Title", "Number of Schools", "Number of Participants", "Venue"}

var exportWidths = []float64{20, 16, 12, 34, 18, 20, 26, 26, 26, 14, 20, 28, 18, 18, 14, 38, 18, 21, 28}

// Export is work_plan_export: the page's scoped rows and the visible fields
// as the Work Plan sheet, and the Plan Summary roll-up beside it. handled is
// false for a role the page is not drawn for.
func (s *Service) Export(ctx context.Context, p auth.Principal, query url.Values) (string, []workbook.Sheet, bool, error) {
	door, ok := rules.Doors[p.ActiveRole]
	if !ok || !door.Page {
		return "", nil, false, nil
	}
	if !rbac.Grants(p.ActiveRole, "data.export") {
		return "", nil, true, workbook.Refusal(exportRefusal)
	}
	passed := url.Values{}
	for key, values := range query {
		if !in(rules.QueryKeysNotPassed, key) {
			passed[key] = values
		}
	}
	v, err := s.read(ctx, p, door, passed)
	if err != nil {
		return "", nil, true, err
	}
	detail, err := s.exportDetail(ctx, v)
	if err != nil {
		return "", nil, true, err
	}
	return "Edify_Work_Plan_FY_" + v.s.fy, []workbook.Sheet{detail, v.exportSummary()}, true, nil
}

// planningDetail is what the export reads of each activity that the page
// does not: its title, schools, participants and venue.
type planningDetail struct {
	name, venue        string
	schools, attending int64
}

func (s *Service) exportDetail(ctx context.Context, v *view) (workbook.Sheet, error) {
	ids := make([]string, 0, len(v.rows))
	for _, r := range v.rows {
		ids = append(ids, r.a.id)
	}
	details := map[string]planningDetail{}
	rows, err := s.db.Query(ctx, `SELECT a.id, COALESCE(a.planned_school_count, 0), COALESCE(a.expected_participants, 0),
  COALESCE(NULLIF(a.venue, ''), CASE WHEN a.school_id IS NOT NULL THEN NULLIF(s.name, '') END,
           CASE WHEN a.cluster_id IS NOT NULL THEN NULLIF(c.name, '') END,
           CASE WHEN a.event_district_id IS NOT NULL THEN NULLIF(d.name, '') END, '')
FROM activity a LEFT JOIN school s ON s.id = a.school_id LEFT JOIN cluster c ON c.id = a.cluster_id
LEFT JOIN district d ON d.id = a.event_district_id WHERE a.id = ANY($1)`, ids)
	if err != nil {
		return workbook.Sheet{}, fmt.Errorf("workplan: reading the export's planning detail: %w", err)
	}
	for rows.Next() {
		var id string
		var d planningDetail
		if err := rows.Scan(&id, &d.schools, &d.attending, &d.venue); err != nil {
			rows.Close()
			return workbook.Sheet{}, err
		}
		details[id] = d
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return workbook.Sheet{}, err
	}
	marks, err := myplan.DistrictTypeLabels(ctx, s.db, ids)
	if err != nil {
		return workbook.Sheet{}, err
	}
	txt := workbook.Text
	out := make([][]workbook.Cell, 0, len(v.rows))
	period := v.s.periodLabel()
	for _, r := range v.rows {
		d := details[r.a.id]
		name := str(r.a.nameSnapshot)
		if name == "" {
			name = typeDisplay(r.a)
		}
		out = append(out, []workbook.Cell{txt(r.dateLabel), txt(r.word), txt(r.schoolCode), txt(r.schoolName), txt(r.district),
			txt(marks[r.a.id]), txt(r.cluster), txt(r.purpose), txt(r.focus), txt(r.score), txt(r.mode), txt(r.responsible),
			workbook.Int(r.cost), txt(period), txt(r.status), txt(name), workbook.Int(d.schools), workbook.Int(d.attending),
			txt(d.venue)})
	}
	return workbook.Sheet{Title: "Work Plan", Headers: exportHeaders, Rows: out, Widths: exportWidths,
		NumberFormats: map[int]string{13: "#,##0"}, FilterHeading: true}, nil
}

// unitCostValue is _finish_summary_rows' unit cost as the number the export
// writes: the average of the recorded cost, rounded half up to the cent.
func unitCostValue(cost int64, count int) float64 {
	if count == 0 {
		return 0
	}
	cents := cost * 100
	q, r := cents/int64(count), cents%int64(count)
	if 2*r >= int64(count) {
		q++
	}
	return float64(q) / 100
}

// exportSummary is the Plan Summary sheet: one line per executor and
// activity type, School then Non-School, their subtotals and the grand
// total, then the scope, the period and what the unit cost is.
func (v *view) exportSummary() workbook.Sheet {
	txt := workbook.Text
	empty := workbook.Text("")
	rows := [][]workbook.Cell{}
	bold := map[int][]int{}
	labels := [2]string{rules.SchoolGroupLabel, rules.NonSchoolGroupLabel}
	for gi := range 2 {
		rows = append(rows, []workbook.Cell{txt(labels[gi]), empty, empty, empty})
		bold[len(rows)+1] = []int{1}
		for _, bk := range v.summary[gi] {
			unit := workbook.Text("Cost setup required")
			switch {
			case bk.unitNote != "":
				unit = txt(bk.unitDisplay + " " + bk.unitNote)
			case bk.missing == 0:
				unit = workbook.Number(unitCostValue(bk.cost, bk.count))
			}
			rows = append(rows, []workbook.Cell{txt(bk.label), workbook.Int(int64(bk.count)), unit, workbook.Int(bk.cost)})
		}
		rows = append(rows, []workbook.Cell{txt(labels[gi] + " subtotal"), workbook.Int(int64(v.totals[gi].count)), empty,
			workbook.Int(v.totals[gi].cost)})
		bold[len(rows)+1] = []int{1, 2, 4}
	}
	rows = append(rows, []workbook.Cell{txt("Grand total"), workbook.Int(int64(v.totals[0].count + v.totals[1].count)), empty,
		workbook.Int(v.totals[0].cost + v.totals[1].cost)})
	bold[len(rows)+1] = []int{1, 2, 4}
	through := len(rows) + 1
	rows = append(rows, nil, []workbook.Cell{txt("Scope"), txt(v.scopeLabel())}, []workbook.Cell{txt("Period"), txt(v.s.periodLabel())},
		[]workbook.Cell{txt("Unit cost"), txt("Average recorded cost per activity; rounded where needed.")})
	if v.missingTotal > 0 {
		rows = append(rows, []workbook.Cell{txt("Cost setup required"), workbook.Int(int64(v.missingTotal)),
			txt("Totals include recorded costs only; no rates estimated.")})
	}
	return workbook.Sheet{Title: "Plan Summary", Headers: []string{"Activity", "Number of Activities", "Unit Cost (UGX)", "Total Cost (UGX)"},
		Rows: rows, Widths: []float64{36, 22, 20, 22}, NoFilter: true, HeadingOnly: true, FormatThrough: through, Bold: bold,
		NumberFormats: map[int]string{2: "#,##0", 3: "#,##0.##", 4: "#,##0"}}
}
