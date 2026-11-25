package staffactivity

import (
	"context"
	"errors"
	"math"
	"net/url"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pagegate"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/workbook"
)

// exportRefusal is staff_activity_export_view's answer to a role the page
// is granted some other way, which reads nobody's log.
const exportRefusal = "The Staff Activity Log is for Programme Leads and the Country Director."

// exportHeaders are the export's columns, in the view's order.
var exportHeaders = []string{"Staff", "Role", "Supervisor", "Program Lead", "Region", "Logins", "First active",
	"Last active", "Overall active time (minutes)", "Last page", "Last meaningful action", "Meaningful actions",
	"Failed actions", "Schools acted on", "Status", "Usage status", "Open follow-ups"}

// Export is staff_activity_export_view: the log the page shows for its
// filters, one row a person, as staff-activity-<start>-<end>. ok is false
// when the log is not Go's for the reader (a Programme Lead's team log).
func (s *Service) Export(ctx context.Context, p auth.Principal, query url.Values) (string, []workbook.Sheet, bool, error) {
	doors, granted := rules.Doors[p.ActiveRole]
	if !granted || !doors.Page {
		return "", nil, true, pagegate.ErrNotAvailable
	}
	if p.ActiveRole != rules.Roles.CountryDirector && p.ActiveRole != rules.Roles.Admin {
		if p.ActiveRole == rules.Dashboard.Role {
			return "", nil, false, nil
		}
		return "", nil, true, workbook.Refusal(exportRefusal)
	}
	l, _, err := s.log(ctx, p, query)
	if errors.Is(err, errPassOn) {
		return "", nil, false, nil
	}
	if err != nil {
		return "", nil, true, err
	}
	rows := make([][]workbook.Cell, 0, len(l.people))
	for _, x := range l.people {
		lead := ""
		if x.lead != nil {
			lead = x.lead.name
		}
		status, _ := label(rules.StatusOptions, x.status)
		if status == "" {
			status = "Offline"
		}
		rows = append(rows, []workbook.Cell{
			workbook.Text(x.name), workbook.Text(x.title), workbook.Text(x.supervisor), workbook.Text(lead),
			workbook.Text(x.region), workbook.Int(int64(x.logins)), workbook.Text(clock(x.firstActive, l.today)),
			workbook.Text(clock(x.lastActive, l.today)), workbook.Int(int64(math.RoundToEven(float64(x.seconds) / 60))),
			workbook.Text(x.lastPage), workbook.Text(x.lastAction), workbook.Int(int64(x.actions)),
			workbook.Int(int64(x.failed)), workbook.Int(int64(x.schools)), workbook.Text(status),
			workbook.Text(x.usageLabel), workbook.Int(int64(x.openFollowUps)),
		})
	}
	stem := "staff-activity-" + l.period.start.Format("20060102") + "-" + l.period.end.Format("20060102")
	return stem, []workbook.Sheet{{Title: "Staff activity", Headers: exportHeaders, Rows: rows}}, true, nil
}
