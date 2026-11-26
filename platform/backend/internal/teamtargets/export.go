package teamtargets

import (
	"bytes"
	"context"
	"encoding/csv"
	"fmt"
	"math"
	"net/url"
	"slices"
	"strconv"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pagegate"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/targets"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/workbook"
)

// exportRefusal is require_export_permission's refusal.
const exportRefusal = "Your role does not include data export."

// Export is team_targets_export_view: each team member's priorities by
// month, quarter and year, target, valid achieved and share, under a line
// naming the year, the moment and the supervisor, as team-targets-fy<fy>.csv.
// handled is false where the page itself is handed on (it would write).
func (s *Service) Export(ctx context.Context, p auth.Principal, query url.Values) (string, []byte, bool, error) {
	if !slices.Contains(rules.PageRoles, p.ActiveRole) {
		return "", nil, true, pagegate.ErrNotAvailable
	}
	if !slices.Contains(rules.ExportRoles, p.ActiveRole) {
		return "", nil, true, workbook.Refusal(exportRefusal)
	}
	now := s.now()
	l := now.In(kampala)
	today := time.Date(l.Year(), l.Month(), l.Day(), 0, 0, 0, 0, time.UTC)
	operational := strconv.Itoa(l.Year())
	if l.Month() >= time.October {
		operational = strconv.Itoa(l.Year() + 1)
	}
	d, err := read(ctx, s.db, p, readQuery(Query(query)), today, operational)
	if err != nil {
		return "", nil, true, err
	}
	if w, err := wouldWrite(ctx, s.db, p.UserID, d.fy, d.current, d.t); err != nil || w {
		return "", nil, err != nil, err
	}
	var buf bytes.Buffer
	w := csv.NewWriter(&buf)
	w.UseCRLF = true
	write := func(cells ...workbook.Cell) error { return w.Write(workbook.SafeCSVRow(cells)) }
	txt := workbook.Text
	if err := write(txt("Team Targets — FY "+d.fy), txt("Generated "+now.UTC().Format("02 Jan 2006 15:04")),
		txt("Supervisor: "+p.Name)); err != nil {
		return "", nil, true, err
	}
	if err := write(txt("Staff"), txt("Performance Priority"), txt("Period"), txt("Target"), txt("Valid Achieved"), txt("%")); err != nil {
		return "", nil, true, err
	}
	line := func(name, area, period string, target, achieved int) error {
		share := txt("")
		if target != 0 {
			share = workbook.Int(int64(math.RoundToEven(float64(achieved) / float64(target) * 100)))
		}
		return write(txt(name), txt(area), txt(period), workbook.Int(int64(target)), workbook.Int(int64(achieved)), share)
	}
	for _, r := range d.t.rows {
		for _, a := range r.MetricAreas {
			t, ach := r.Targets[a.Key], r.Achieved[a.Key]
			for m := 1; m <= 12; m++ {
				if err := line(r.member.Name, a.Label, targets.MonthLabel(d.fy, m), t[m-1], ach[m-1]); err != nil {
					return "", nil, true, err
				}
			}
			for q := 0; q < 4; q++ {
				tq, aq := 0, 0
				for m := q*3 + 1; m <= q*3+3; m++ {
					tq += t[m-1]
					aq += ach[m-1]
				}
				if err := line(r.member.Name, a.Label, fmt.Sprintf("Q%d", q+1), tq, aq); err != nil {
					return "", nil, true, err
				}
			}
			ty, ay := 0, 0
			for m := 0; m < 12; m++ {
				ty += t[m]
				ay += ach[m]
			}
			if err := line(r.member.Name, a.Label, "FY Cumulative", ty, ay); err != nil {
				return "", nil, true, err
			}
		}
	}
	w.Flush()
	return "team-targets-fy" + d.fy + ".csv", buf.Bytes(), true, w.Error()
}
