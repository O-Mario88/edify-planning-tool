package iapages

import (
	"context"
	"net/url"
	"strconv"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pagegate"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/rbac"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/workbook"
)

// analyticsExportRefusal is the view's render_access_denied for a role
// without data export.
const analyticsExportRefusal = "Your role does not include data export."

// analyticsExportHeaders are EXPORT_HEADER.
var analyticsExportHeaders = []string{"Decided at", "Activity ID", "School ID", "School Name", "Activity Type", "Submitted by",
	"Partner", "Decision", "Return reasons", "Verifier", "Turnaround (hours)"}

// AnalyticsExport is ia_verification_analytics_export_view: the decisions
// behind the analytics for the same window, verification-decisions-<n>d.
func (s *Service) AnalyticsExport(ctx context.Context, p auth.Principal, query url.Values) (string, []workbook.Sheet, bool, error) {
	role, ok := rules.Pages[AnalyticsPath].Roles[p.ActiveRole]
	if !ok || !role.Page {
		return "", nil, true, pagegate.ErrNotAvailable
	}
	if !rbac.Grants(p.ActiveRole, "data.export") {
		return "", nil, true, workbook.Refusal(analyticsExportRefusal)
	}
	window := analyticsWindow(query.Get("window"))
	data, err := s.verificationAnalytics(ctx, p, window)
	if err != nil {
		return "", nil, true, err
	}
	rows := make([][]workbook.Cell, 0, len(data.lines))
	for _, l := range data.lines {
		turnaround := workbook.Text("")
		if l.turnaround != nil {
			turnaround = workbook.Number(*l.turnaround)
		}
		rows = append(rows, []workbook.Cell{
			workbook.Text(l.decidedAt), workbook.Text(l.activityID), workbook.Text(l.schoolCode), workbook.Text(l.school),
			workbook.Text(l.activityType), workbook.Text(l.submitter), workbook.Text(l.partner), workbook.Text(l.decision),
			workbook.Text(l.reasons), workbook.Text(l.verifier), turnaround,
		})
	}
	return "verification-decisions-" + strconv.Itoa(window) + "d",
		[]workbook.Sheet{{Title: "Verification decisions", Headers: analyticsExportHeaders, Rows: rows}}, true, nil
}
