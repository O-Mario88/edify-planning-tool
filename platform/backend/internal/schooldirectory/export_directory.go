package schooldirectory

import (
	"bytes"
	"context"
	"encoding/csv"
	"fmt"
	"net/url"
	"strings"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pagegate"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/workbook"
)

// exportRefusal is require_export_permission's refusal.
const exportRefusal = "Your role does not include data export."

var directoryExportHeaders = []string{"School ID", "Name", "Type", "District", "Sub-county", "Region", "Enrollment",
	"Cluster Status", "SSA Status", "Planning Readiness"}

// Export is school_directory_context's export: every school the page's
// filters, gap and tab keep, by name, as schools_export.csv or (a plain
// sheet "Schools") schools_export.xlsx. handled is false for a region
// filter, which Go's directory does not read yet.
func (s *Service) Export(ctx context.Context, p auth.Principal, query url.Values) (string, []byte, bool, error) {
	format := strings.TrimSpace(query.Get("export"))
	if format != "csv" && format != "xlsx" {
		return "", nil, false, nil
	}
	access := rules.PageAccess[p.ActiveRole]
	if !access.Directory {
		return "", nil, true, pagegate.ErrNotAvailable
	}
	if !access.DataExport {
		return "", nil, true, workbook.Refusal(exportRefusal)
	}
	if strings.TrimSpace(query.Get("region")) != "" {
		return "", nil, false, nil
	}
	get := func(key string) string { return strings.TrimSpace(query.Get(key)) }
	req := &screensv1.GetSchoolDirectoryRequest{Q: get("q"), Fy: get("fy"), District: get("district"), SubCounty: get("sub_county"),
		SchoolType: get("school_type"), ClusterStatus: get("cluster_status"), ProjectStatus: get("project_status"),
		Tab: get("tab"), Gap: get("gap")}
	if req.Tab == "" {
		req.Tab = "all"
	}
	d, err := s.listingFor(ctx, p, req, s.now())
	if err != nil {
		return "", nil, true, err
	}
	rows, err := s.db.Query(ctx, `SELECT COALESCE(s.school_id, ''), COALESCE(s.name, ''), COALESCE(s.school_type, ''),
  COALESCE(d.name, ''), COALESCE(sc.name, ''), COALESCE(r.name, ''), COALESCE(s.enrollment, 0), COALESCE(s.cluster_status, ''),
  COALESCE(s.current_fy_ssa_status, ''), COALESCE(s.planning_readiness, '')
FROM school s LEFT JOIN district d ON d.id = s.district_id LEFT JOIN sub_county sc ON sc.id = s.sub_county_id
LEFT JOIN region r ON r.id = s.region_id WHERE `+d.listing.where()+` ORDER BY s.name, s.id`, d.listing.args...)
	if err != nil {
		return "", nil, true, fmt.Errorf("schooldirectory: reading the schools to export: %w", err)
	}
	defer rows.Close()
	var out [][]workbook.Cell
	for rows.Next() {
		var code, name, kind, district, subCounty, region, cluster, ssa, readiness string
		var enrollment int64
		if err := rows.Scan(&code, &name, &kind, &district, &subCounty, &region, &enrollment, &cluster, &ssa, &readiness); err != nil {
			return "", nil, true, err
		}
		// school.enrollment or "".
		enrolled := workbook.Text("")
		if enrollment != 0 {
			enrolled = workbook.Int(enrollment)
		}
		out = append(out, []workbook.Cell{workbook.Text(code), workbook.Text(name), workbook.Text(kind), workbook.Text(district),
			workbook.Text(subCounty), workbook.Text(region), enrolled, workbook.Text(cluster), workbook.Text(ssa), workbook.Text(readiness)})
	}
	if err := rows.Err(); err != nil {
		return "", nil, true, err
	}
	if format == "xlsx" {
		var buf bytes.Buffer
		err := workbook.Write(&buf, []workbook.Sheet{{Title: "Schools", Headers: directoryExportHeaders, Rows: out, Plain: true}})
		return "schools_export.xlsx", buf.Bytes(), true, err
	}
	var buf bytes.Buffer
	w := csv.NewWriter(&buf)
	w.UseCRLF = true
	head := make([]workbook.Cell, len(directoryExportHeaders))
	for i, h := range directoryExportHeaders {
		head[i] = workbook.Text(h)
	}
	if err := w.Write(workbook.SafeCSVRow(head)); err != nil {
		return "", nil, true, err
	}
	for _, r := range out {
		if err := w.Write(workbook.SafeCSVRow(r)); err != nil {
			return "", nil, true, err
		}
	}
	w.Flush()
	return "schools_export.csv", buf.Bytes(), true, w.Error()
}
