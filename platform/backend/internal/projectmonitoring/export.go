package projectmonitoring

import (
	"context"
	"fmt"
	"net/url"
	"regexp"
	"sort"
	"strings"
	"unicode"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pagegate"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/rbac"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/workbook"
)

// The project table's workbook (oversight_views.special_project_export_view
// with apps.projects.school_table.sheets), for what this page draws: projects
// that have no work yet. Projects with work, a filter on the work, an export
// kind other than the whole table and a reader the page is not drawn for are
// handed on.

// exportColumns are school_table.EXPORT_COLUMNS.
var exportColumns = []string{"Project Name", "School ID", "School Name", "District", "District Type", "Training",
	"Purpose of Assignment", "SSA Intervention", "Previous SSA Score", "Current SSA Score", "SSA Improvement", "Status",
	"Activity Date", "Enrolled On", "Planning Stage", "Planned By", "Execution", "Activity Status", "Activity Cost (UGX)"}

// summaryColumns are school_table._SUMMARY.
var summaryColumns = []string{"Project ID", "Project Code", "Project Name", "Coordinator", "Status", "Partners",
	"Total Schools", "Schools Planned", "Schools Awaiting Partner", "Schools Delivered", "Trainings Scheduled",
	"Trainings Completed", "Visits Scheduled", "Visits Completed", "Other Scheduled", "Other Completed",
	"Staff Delivered", "Partner Delivered"}

// exportFormats are _FORMATS at their columns once District Type is in.
var exportFormats = map[int]string{9: "0.0#", 10: "0.0#", 11: "[Color10]+0.0#;[Red]-0.0#;0.0#", 13: "d mmm yyyy",
	14: "d mmm yyyy", 19: "#,##0"}

// exportQueryKeys are the query the export reads that Go answers as the
// whole table; a period, a status or a kind narrows work Go does not draw.
var exportQueryKeys = []string{"fy", "stage", "project_status", "format", "activity_type"}

// notInScope is the view's Http404 for a project the reader does not see.
type notInScope struct{}

func (notInScope) Error() string  { return "Special project not found or not in scope." }
func (notInScope) NotFound() bool { return true }

// Export answers /projects/export (projectID "") and /projects/<id>/export.
func (s *Service) Export(ctx context.Context, p auth.Principal, projectID string, query url.Values) (string, []workbook.Sheet, bool, error) {
	doors, ok := rules.Doors[p.ActiveRole]
	if !ok || !doors.Page || p.InActingAppointment {
		return "", nil, false, nil
	}
	if !rbac.Grants(p.ActiveRole, "data.export") {
		// require_export_permission.
		return "", nil, true, pagegate.ErrNotAvailable
	}
	for key := range query {
		if !in(exportQueryKeys, key) && !rowFilterKey(key) {
			return "", nil, false, nil
		}
	}
	if status := strings.TrimSpace(query.Get("project_status")); status != "" && status != "schools" {
		return "", nil, false, nil
	}
	if kind := strings.ToLower(strings.TrimSpace(query.Get("activity_type"))); kind != "" && kind != "all" {
		return "", nil, false, nil
	}
	now := s.now()
	fy := strings.TrimSpace(query.Get("fy"))
	if fy == "" {
		fy = schooldirectory.OperationalFY(now)
	}
	v := view{doors: doors, fy: fy, picks: map[string]string{}, l: lensFor(p)}
	if stage := strings.TrimSpace(query.Get("stage")); stage != "" {
		for _, f := range rules.StageFilters {
			if f[0] == stage {
				v.stage = stage
			}
		}
	}
	for _, f := range rules.RowFilters {
		if value := strings.TrimSpace(query.Get(f[0])); value != "" {
			v.picks[f[0]] = value
		}
	}
	scope, err := schooldirectory.ResolveScope(ctx, s.db, p, now)
	if err != nil {
		return "", nil, true, err
	}
	projects, err := projectsFor(ctx, s.db, v.l, scope)
	if err != nil {
		return "", nil, true, err
	}
	ids := make([]string, len(projects))
	for i, pr := range projects {
		ids[i] = pr.ID
	}
	if busy, err := hasWork(ctx, s.db, ids, v.l.staffID); err != nil || busy {
		return "", nil, err != nil, err
	}
	rows := []projectRow{}
	if len(projects) > 0 {
		if rows, err = s.projectRows(ctx, v, projects, ids); err != nil {
			return "", nil, true, err
		}
	}
	single := projectID != "" && projectID != "all" && projectID != "export"
	if single {
		kept := []projectRow{}
		for _, r := range rows {
			if r.p.ID == projectID {
				kept = append(kept, r)
			}
		}
		if len(kept) == 0 {
			return "", nil, true, notInScope{}
		}
		rows = kept
	}
	sheets, err := s.exportSheets(ctx, rows)
	if err != nil {
		return "", nil, true, err
	}
	return exportStem(rows, fy, single), sheets, true, nil
}

// exportTarget is the export's two paths: every project, or one.
var exportTarget = regexp.MustCompile(`^/projects/(?:([A-Za-z0-9_-]{1,64})/)?export$`)

// ExportRoute names Export for the quick export's targets.
func ExportRoute(s *Service) func(string) (func(context.Context, auth.Principal, url.Values) (string, []workbook.Sheet, bool, error), bool) {
	return func(target string) (func(context.Context, auth.Principal, url.Values) (string, []workbook.Sheet, bool, error), bool) {
		m := exportTarget.FindStringSubmatch(target)
		if m == nil {
			return nil, false
		}
		return func(ctx context.Context, p auth.Principal, q url.Values) (string, []workbook.Sheet, bool, error) {
			return s.Export(ctx, p, m[1], q)
		}, true
	}
}

func rowFilterKey(key string) bool {
	for _, f := range rules.RowFilters {
		if f[0] == key {
			return true
		}
	}
	return false
}

// exportSheets is school_table.sheets for projects with no work: every
// school in one sheet, a line a project on the second.
func (s *Service) exportSheets(ctx context.Context, rows []projectRow) ([]workbook.Sheet, error) {
	schools := [][]workbook.Cell{}
	for _, pr := range rows {
		for _, r := range pr.rows {
			number := func(f *float64) workbook.Cell {
				if f == nil {
					return workbook.Text("")
				}
				return workbook.Number(*f)
			}
			schools = append(schools, []workbook.Cell{
				workbook.Text(r.ProjectName), workbook.Text(r.e.SchoolCode), workbook.Text(r.e.SchoolName),
				workbook.Text(r.e.District), workbook.Text(""), workbook.Text(""), workbook.Text(r.Purpose),
				workbook.Text(r.Intervention), number(r.Previous), number(r.Current), number(r.improvement()),
				workbook.Text(rules.RowStatusLabels["awaiting_coordinator"]), workbook.Text(""),
				workbook.Date(r.e.enrolledOn()), workbook.Text(rules.PlanLabels["not_planned"]), workbook.Text(""),
				workbook.Text(rules.ExecLabels["none"]), workbook.Text(""), workbook.Text(""),
			})
		}
	}
	ids := make([]string, len(rows))
	for i, r := range rows {
		ids[i] = r.p.ID
	}
	coordinators, partners, err := projectPeople(ctx, s, ids)
	if err != nil {
		return nil, err
	}
	summary := [][]workbook.Cell{}
	for _, pr := range rows {
		coordinator, ok := coordinators[pr.p.ID]
		if !ok {
			coordinator = "Not assigned"
		}
		names := "None"
		if list := partners[pr.p.ID]; len(list) > 0 {
			names = strings.Join(list, ", ")
		}
		line := []workbook.Cell{workbook.Text(pr.p.ID), workbook.Text(pr.p.Code), workbook.Text(pr.p.Name),
			workbook.Text(coordinator), workbook.Text(pr.p.statusLabel()), workbook.Text(names), workbook.Int(int64(pr.schools))}
		for range 11 {
			line = append(line, workbook.Int(0))
		}
		summary = append(summary, line)
	}
	return []workbook.Sheet{
		{Title: "Project Schools", Headers: exportColumns, Rows: schools, NumberFormats: exportFormats},
		{Title: "Project Summary", Headers: summaryColumns, Rows: summary},
	}, nil
}

// projectPeople is _coordinator_names and _partner_names: each project's
// manager's name (empty for a profile without an account, "Not assigned"
// for one that is gone) and its partners' names, sorted.
func projectPeople(ctx context.Context, s *Service, ids []string) (map[string]string, map[string][]string, error) {
	coordinators, partners := map[string]string{}, map[string][]string{}
	if len(ids) == 0 {
		return coordinators, partners, nil
	}
	rows, err := s.db.Query(ctx, `
SELECT p.id, CASE WHEN sp.id IS NULL THEN 'Not assigned' WHEN sp.user_id IS NULL THEN '' ELSE COALESCE(u.name, '') END
FROM project p LEFT JOIN staff_profile sp ON sp.id = p.manager_staff_id LEFT JOIN "user" u ON u.id = sp.user_id
WHERE p.id = ANY($1) AND COALESCE(p.manager_staff_id, '') <> ''`, ids)
	if err != nil {
		return nil, nil, fmt.Errorf("projectmonitoring: reading the coordinators: %w", err)
	}
	for rows.Next() {
		var id, name string
		if err := rows.Scan(&id, &name); err != nil {
			rows.Close()
			return nil, nil, fmt.Errorf("projectmonitoring: reading the coordinators: %w", err)
		}
		coordinators[id] = name
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, nil, fmt.Errorf("projectmonitoring: reading the coordinators: %w", err)
	}
	prows, err := s.db.Query(ctx, `SELECT a.project_id, pa.name FROM project_partner_assignment a JOIN partner pa ON pa.id = a.partner_id
WHERE a.project_id = ANY($1)`, ids)
	if err != nil {
		return nil, nil, fmt.Errorf("projectmonitoring: reading the project partners: %w", err)
	}
	defer prows.Close()
	for prows.Next() {
		var id, name string
		if err := prows.Scan(&id, &name); err != nil {
			return nil, nil, fmt.Errorf("projectmonitoring: reading the project partners: %w", err)
		}
		partners[id] = append(partners[id], name)
	}
	for _, list := range partners {
		sort.Strings(list)
	}
	return coordinators, partners, prows.Err()
}

// exportStem is school_table.filename_stem.
func exportStem(rows []projectRow, fy string, single bool) string {
	if single && len(rows) > 0 {
		code := rows[0].p.Code
		if code == "" {
			code = rows[0].p.ID
		}
		var b strings.Builder
		for _, r := range strings.ToLower(code) {
			if unicode.IsLetter(r) || unicode.IsDigit(r) || r == '-' || r == '_' {
				b.WriteRune(r)
			} else {
				b.WriteByte('-')
			}
		}
		return "project-" + b.String() + "-schools-FY" + fy
	}
	return "special-projects-schools-FY" + fy
}
