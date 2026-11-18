// Package closurepages is the closure workspace's pages in Go, as the
// existing feed reads them: the Blocked Closures directory
// (/activities/closure/blocked: closure_views.blocked_closure_view,
// pages/closure/blocked_closure.html) and the Analytics Publishing Status
// page (/analytics/publishing). Resolving a blocker is the existing
// application's.
package closurepages

import (
	"context"
	"fmt"
	"net/url"
	"strings"
	"time"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/calendarpage"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/debriefs"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pagegate"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schoolprofile"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/tablepager"
)

// BlockedPath is the directory.
const BlockedPath = "/activities/closure/blocked"

const (
	blockedPageParam = "blockers_page"
	blockedPageSize  = 50
	perfect          = "Perfect compliance! No activities blocked for closure."
)

// Service builds the pages.
type Service struct {
	db  schooldirectory.Querier
	now func() time.Time
}

// NewService is the pages over db.
func NewService(db schooldirectory.Querier, now func() time.Time) *Service {
	return &Service{db: db, now: now}
}

// blocker is one ClosureBlocker with its activity.
type blocker struct {
	activityID, kind, reason, role, owner string
	created                               time.Time
}

// nextAction is the template's next step for a reason.
func nextAction(reason string) string {
	switch {
	case strings.Contains(reason, "Evidence"):
		return "CCEO must upload field visit stamp or attendance sheet."
	case strings.Contains(reason, "IA"):
		return "IA auditor must verify the checklist details."
	case strings.Contains(reason, "NetSuite"):
		return "Accountant must enter NetSuite Expense ID."
	}
	return "Reconcile outstanding disbursements."
}

// reachOf is closure_views._in_scope over activities aliased as alias: a
// country reader every live activity, anyone else the work they hold under
// either id and the work at their schools. Deleted activities are out, as
// Activity's manager leaves them.
func reachOf(scope schooldirectory.Scope, p auth.Principal, alias string) (string, []any) {
	reach := alias + ".deleted_at IS NULL"
	if scope.CountryScope {
		return reach, []any{}
	}
	staff := []string{}
	for _, id := range []string{scope.StaffID, p.UserID, p.StaffProfileID} {
		if id != "" && !contains(staff, id) {
			staff = append(staff, id)
		}
	}
	return reach + " AND (" + alias + ".responsible_staff_id = ANY($1) OR " + alias + ".school_id = ANY($2))",
		[]any{staff, scope.SchoolIDs}
}

// readBlockers is the view's queryset: the blockers of the activities in the
// reader's reach (reachOf), longest blocked first, then by activity and
// blocker (owner, 2026-11-18).
func (s *Service) readBlockers(ctx context.Context, scope schooldirectory.Scope, p auth.Principal) ([]blocker, error) {
	reach, args := reachOf(scope, p, "u0")
	rows, err := s.db.Query(ctx, `
SELECT b.activity_id, a.activity_type, b.blocking_reason, b.responsible_role, COALESCE(a.responsible_staff_id, ''), b.created_at
FROM closure_blocker b
INNER JOIN activity a ON a.id = b.activity_id
WHERE b.activity_id IN (SELECT u0.id FROM activity u0 WHERE `+reach+`)
ORDER BY b.created_at, b.activity_id, b.id`, args...)
	if err != nil {
		return nil, fmt.Errorf("closurepages: reading the blockers: %w", err)
	}
	defer rows.Close()
	out := []blocker{}
	for rows.Next() {
		var b blocker
		if err := rows.Scan(&b.activityID, &b.kind, &b.reason, &b.role, &b.owner, &b.created); err != nil {
			return nil, fmt.Errorf("closurepages: reading a blocker: %w", err)
		}
		out = append(out, b)
	}
	return out, rows.Err()
}

func contains(list []string, v string) bool {
	for _, x := range list {
		if x == v {
			return true
		}
	}
	return false
}

// Build answers the pages; every other path is not its own.
func (s *Service) Build(ctx context.Context, p auth.Principal, path string, query url.Values) (*screensv1.GetPageResponse, bool, error) {
	if path == PublishingPath {
		return s.publishing(ctx, p, query)
	}
	if path == CompletedPath {
		return s.completed(ctx, p, query)
	}
	if path != BlockedPath {
		return nil, false, nil
	}
	if !schoolprofile.MayPlan(p.ActiveRole) {
		return nil, true, pagegate.ErrNotAvailable
	}
	now := s.now()
	scope, err := schooldirectory.ResolveScope(ctx, s.db, p, now)
	if err != nil {
		return nil, true, err
	}
	list, err := s.readBlockers(ctx, scope, p)
	if err != nil {
		return nil, true, err
	}
	header := &screensv1.PageHeader{Eyebrow: "Finance", Title: "Blocked Closures Directory",
		Description: "Review activities that are stuck and cannot close because of missing quality or accountability checks.",
		Badges:      []*screensv1.PageBadge{}, Actions: []*screensv1.PageAction{}}
	return &screensv1.GetPageResponse{Header: header, Blocks: blockedBlocks(list, query, now), WebPath: BlockedPath}, true, nil
}

// blockedBlocks is the blockers' table, fifty a page, and its pager.
func blockedBlocks(list []blocker, query url.Values, now time.Time) []*screensv1.PageBlock {
	t := &screensv1.PageTable{Columns: []*screensv1.PageColumn{{Label: "Activity ID"}, {Label: "Blocked Reason"},
		{Label: "Responsible Role"}, {Label: "Owner / Staff"}, {Label: "Days Blocked"}, {Label: "Next Action"},
		{Label: "Actions", Numeric: true}}}
	if len(list) == 0 {
		// The empty state sits in a row; the feed reads it both as that row
		// and as the table's empty message.
		t.Rows = []*screensv1.PageRow{{Cells: []*screensv1.PageCell{{Text: perfect}}}}
		t.EmptyMessage = perfect
	}
	page := tablepager.Paginate(len(list), blockedPageSize, query, blockedPageParam)
	for _, b := range list[page.Start:page.End] {
		short := b.activityID
		if len([]rune(short)) > 8 {
			short = string([]rune(short)[:8])
		}
		owner := b.owner
		if owner == "" {
			owner = "Unassigned"
		}
		t.Rows = append(t.Rows, &screensv1.PageRow{Cells: []*screensv1.PageCell{
			{Text: "#" + short + " " + calendarpage.ActivityTypeLabel(b.kind)},
			{Text: b.reason, Tone: "primary", Badge: true}, {Text: b.role}, {Text: owner},
			{Text: debriefs.Timesince(b.created, now)}, {Text: nextAction(b.reason)},
			{Actions: []*screensv1.PageAction{{Key: "button", Label: "Resolve Blocker", Primary: true, Enabled: true,
				Href: "/activities/" + b.activityID + "/closure/"}}},
		}})
	}
	blocks := []*screensv1.PageBlock{{Kind: &screensv1.PageBlock_Table{Table: t}}}
	if pager := tablepager.Panel(len(list), blockedPageSize, query, blockedPageParam); pager != nil {
		blocks = append(blocks, pager)
	}
	return blocks
}
