package clusterpage

import (
	"bytes"
	"context"
	"encoding/csv"
	"net/url"
	"strings"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/workbook"
)

// exportRefusal is require_export_permission's refusal.
const exportRefusal = "Your role does not include data export."

var listHeaders = []string{"Cluster Name", "District", "Sub-county", "Schools", "Avg SSA", "Risk", "Last Meeting", "Last Training"}

// ListExport is cluster_list_view's ?export=csv|xlsx: every card the
// page's filters keep, as clusters_export.csv (a CSV for both).
func (s *Service) ListExport(ctx context.Context, p auth.Principal, query url.Values) (string, []byte, bool, error) {
	if e := strings.TrimSpace(query.Get("export")); e != "csv" && e != "xlsx" {
		return "", nil, false, nil
	}
	doors, ok := rules.Doors[p.ActiveRole]
	if !ok || !doors.Page {
		return "", nil, true, ErrNotAvailable
	}
	if !doors.DataExport {
		return "", nil, true, workbook.Refusal(exportRefusal)
	}
	l, err := s.list(ctx, p, query)
	if err != nil {
		return "", nil, true, err
	}
	var buf bytes.Buffer
	w := csv.NewWriter(&buf)
	w.UseCRLF = true
	text := func(v ...string) []workbook.Cell {
		out := make([]workbook.Cell, len(v))
		for i, s := range v {
			out[i] = workbook.Text(s)
		}
		return out
	}
	if err := w.Write(workbook.SafeCSVRow(text(listHeaders...))); err != nil {
		return "", nil, true, err
	}
	day := func(c card, meeting bool) string {
		t := c.lastTraining
		if meeting {
			t = c.lastMeeting
		}
		if t == nil {
			return "Never"
		}
		return t.Format("02 Jan 2006")
	}
	for _, c := range l.cards {
		avg := workbook.Empty()
		if c.avgSSA != nil {
			avg = workbook.Number(*c.avgSSA)
		}
		row := []workbook.Cell{workbook.Text(c.Name), workbook.Text(c.districtLine()), workbook.Text(c.subCountyLine()),
			workbook.Int(int64(c.schools)), avg, workbook.Text(c.risk()), workbook.Text(day(c, true)), workbook.Text(day(c, false))}
		if err := w.Write(workbook.SafeCSVRow(row)); err != nil {
			return "", nil, true, err
		}
	}
	w.Flush()
	return "clusters_export.csv", buf.Bytes(), true, w.Error()
}
