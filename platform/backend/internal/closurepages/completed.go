package closurepages

import (
	"context"
	"fmt"
	"net/url"
	"time"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/calendarpage"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pagegate"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/tablepager"
)

// The Completed Activities ledger (closure_views.completed_activities_view in
// the analytics workspace, partials/analytics/panels/completed_work.html):
// the closed activities in the reader's reach, most recently changed first.

// CompletedPath is the ledger.
const CompletedPath = "/completed-activities"

const (
	completedPageParam = "completed_work_closed_page"
	completedPageSize  = 50
	completedEmpty     = "No activities found in completed archive ledger."
)

// closedActivity is one row of the ledger.
type closedActivity struct {
	id, kind, owner, netsuite string
	schoolID, schoolName      string
	ownerSet, iaVerified      bool
	planned                   *time.Time
}

// readClosed is the view's queryset: live closed activities in the reach,
// latest updated first (the id settling a tie), with the closure checklist's IA flag and the
// snapshot's NetSuite id.
func (s *Service) readClosed(ctx context.Context, scope schooldirectory.Scope, p auth.Principal) ([]closedActivity, error) {
	reach, args := reachOf(scope, p, "a")
	rows, err := s.db.Query(ctx, `
SELECT a.id, a.activity_type, COALESCE(a.responsible_staff_id, ''), a.responsible_staff_id IS NOT NULL,
  COALESCE(sc.id, ''), COALESCE(sc.name, ''), COALESCE(ck.ia_verified, false), COALESCE(sn.netsuite_expense_id, ''),
  a.planned_date
FROM activity a
LEFT JOIN school sc ON sc.id = a.school_id
LEFT JOIN closure_checklist ck ON ck.activity_id = a.id
LEFT JOIN completed_activity_snapshot sn ON sn.activity_id = a.id
WHERE a.status = 'closed' AND `+reach+`
ORDER BY a.updated_at DESC, a.id`, args...)
	if err != nil {
		return nil, fmt.Errorf("closurepages: reading the closed activities: %w", err)
	}
	defer rows.Close()
	out := []closedActivity{}
	for rows.Next() {
		var c closedActivity
		if err := rows.Scan(&c.id, &c.kind, &c.owner, &c.ownerSet, &c.schoolID, &c.schoolName, &c.iaVerified, &c.netsuite,
			&c.planned); err != nil {
			return nil, fmt.Errorf("closurepages: reading a closed activity: %w", err)
		}
		out = append(out, c)
	}
	return out, rows.Err()
}

// completed draws the ledger.
func (s *Service) completed(ctx context.Context, p auth.Principal, query url.Values) (*screensv1.GetPageResponse, bool, error) {
	d, ok := rules.Roles[p.ActiveRole]
	if !ok {
		return nil, false, nil
	}
	if !d.Completed {
		return nil, true, pagegate.ErrNotAvailable
	}
	scope, err := schooldirectory.ResolveScope(ctx, s.db, p, s.now())
	if err != nil {
		return nil, true, err
	}
	list, err := s.readClosed(ctx, scope, p)
	if err != nil {
		return nil, true, err
	}
	blocks := workspaceFrame("Completed Activities ledger", d.CompletedStrip, frame{
		question:  "Which activities have fully cleared evidence and finance, and can be relied on for reporting?",
		evidence:  "Locked closure snapshots and IA status",
		freshness: "Live permanent ledger",
	})
	blocks = append(blocks, completedTable(list, d, query)...)
	return workspacePage("Completed Activities ledger", blocks, CompletedPath), true, nil
}

// completedTable is the ledger's table, fifty a page, and its pager.
func completedTable(list []closedActivity, d role, query url.Values) []*screensv1.PageBlock {
	t := &screensv1.PageTable{Columns: []*screensv1.PageColumn{{Label: "Activity ID"}, {Label: "School ID"},
		{Label: "School / Cluster"}, {Label: "Owner"}, {Label: "Activity Type"}, {Label: "Planned Date"},
		{Label: "PL Status"}, {Label: "NetSuite ID"}, {Label: "Actions", Numeric: true}}}
	if len(list) == 0 {
		t.Rows = []*screensv1.PageRow{{Cells: []*screensv1.PageCell{{Text: completedEmpty}}}}
		t.EmptyMessage = completedEmpty
	}
	page := tablepager.Paginate(len(list), completedPageSize, query, completedPageParam)
	for _, c := range list[page.Start:page.End] {
		short := c.id
		if len([]rune(short)) > 8 {
			short = string([]rune(short)[:8])
		}
		code, school := "—", &screensv1.PageCell{Text: "Cluster-wide"}
		if c.schoolID != "" {
			code, school.Text = "", c.schoolName
			if d.OpenSchool {
				school.Href = "/schools/" + c.schoolID
			}
		}
		// A missing holder prints as Python's None.
		owner := c.owner
		if !c.ownerSet {
			owner = "None"
		}
		planned := ""
		if c.planned != nil {
			planned = c.planned.Format("Jan 02, 2006")
		}
		verified := "Not Verified"
		if c.iaVerified {
			verified = "Verified"
		}
		netsuite := c.netsuite
		if netsuite == "" {
			netsuite = "—"
		}
		t.Rows = append(t.Rows, &screensv1.PageRow{Cells: []*screensv1.PageCell{
			{Text: "#" + short}, {Text: code}, school, {Text: owner},
			{Text: calendarpage.ActivityTypeLabel(c.kind), Tone: "primary", Badge: true}, {Text: planned},
			{Text: verified}, {Text: netsuite},
			{Actions: []*screensv1.PageAction{{Key: "button", Label: "View Record", Primary: true, Enabled: true,
				Href: "/completed-activities/" + c.id + "/"}}},
		}})
	}
	blocks := []*screensv1.PageBlock{{Kind: &screensv1.PageBlock_Table{Table: t}}}
	if pager := tablepager.Panel(len(list), completedPageSize, query, completedPageParam); pager != nil {
		blocks = append(blocks, pager)
	}
	return blocks
}
