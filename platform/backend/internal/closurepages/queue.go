package closurepages

import (
	"context"
	"fmt"
	"slices"
	"strconv"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/calendarpage"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pagegate"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// The Closure Readiness Workspace (closure_views.closure_readiness_queue_view
// over ClosureEligibilityService.with_facts, pages/closure/
// readiness_queue.html) as the existing feed reads it: the reader's work
// past its doing, newest first, each sorted by its closure facts into Ready,
// Finance Pending, Accountability Pending, Analytics Pending or Blocked. The
// facts are read, never written, as the view reads them.

// QueuePath is the workspace's path.
const QueuePath = "/activities/closure"

func links(ls ...*screensv1.PageLink) *screensv1.PagePanelItem {
	return &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Links{Links: &screensv1.PageLinks{Links: ls}}}
}

// closureItem is one activity in the queue with its closure facts.
type closureItem struct {
	id, kind, status, delivery, payment, salesforce, recordType string
	schoolID, schoolName                                        string
	owner                                                       *string
	evidence, costLines, netsuite, cleared, moved, unaccounted  bool
	publish                                                     string
}

// closureFacts are ClosureEligibilityService.facts' checks the queue sorts by.
type closureFacts struct {
	executed, evidence, salesforce, verified          bool
	financeRequired, accountsCleared, netsuiteEntered bool
	published                                         bool
}

func (a closureItem) facts() closureFacts {
	q := rules.Queue
	partner := a.delivery == "partner"
	f := closureFacts{
		executed:        !slices.Contains(q.NotExecuted, a.status),
		verified:        slices.Contains(q.IAVerified, a.status),
		salesforce:      a.salesforce != "" || slices.Contains(q.NoSalesforceType, a.recordType),
		financeRequired: a.costLines || partner,
		evidence:        !partner || a.evidence,
		published:       a.publish == "published",
		accountsCleared: true,
		netsuiteEntered: true,
	}
	if f.financeRequired {
		if partner {
			f.accountsCleared = a.payment == "paid"
		} else {
			f.accountsCleared = a.netsuite || a.cleared
			f.netsuiteEntered = a.netsuite || (a.moved && !a.unaccounted)
		}
	}
	return f
}

// coreMet is _core_requirements_met.
func (f closureFacts) coreMet() bool {
	return f.executed && f.evidence && f.salesforce && f.verified &&
		(!f.financeRequired || (f.accountsCleared && f.netsuiteEntered))
}

// queueTab is one tab of the workspace.
type queueTab struct {
	label, pill, empty, link string
	items                    []closureItem
}

// tabOf is the view's sort: ready, then finance, accountability and
// analytics in turn, else blocked.
func tabOf(f closureFacts) int {
	switch {
	case f.coreMet():
		return 0
	case f.financeRequired && !f.accountsCleared:
		return 1
	case f.financeRequired && !f.netsuiteEntered:
		return 2
	case !f.published:
		return 3
	}
	return 4
}

func (s *Service) queue(ctx context.Context, p auth.Principal) (*screensv1.GetPageResponse, bool, error) {
	if r, ok := rules.Roles[p.ActiveRole]; !ok || !r.Queue {
		return nil, true, pagegate.ErrNotAvailable
	}
	scope, err := schooldirectory.ResolveScope(ctx, s.db, p, s.now())
	if err != nil {
		return nil, true, err
	}
	items, err := s.readQueue(ctx, scope, p)
	if err != nil {
		return nil, true, err
	}
	tabs := []*queueTab{
		{label: "Ready to Close", pill: "Ready", empty: "No activities currently ready to close.", link: "Open Workspace"},
		{label: "Finance Pending", pill: "Awaiting Accountant Payout", empty: "No items waiting for finance clearance.", link: "Workspace"},
		{label: "Accountability Pending", pill: "NetSuite ID Required", empty: "No items waiting for NetSuite IDs.", link: "Workspace"},
		{label: "Analytics Pending", pill: "Awaiting Publish", empty: "No items pending analytics integration.", link: "Workspace"},
		{label: "Blocked", pill: "Blocker Present", empty: "No blocked closure items.", link: "Workspace"},
	}
	for _, a := range items {
		t := tabs[tabOf(a.facts())]
		t.items = append(t.items, a)
	}
	opens := rules.Roles[p.ActiveRole].OpenSchool
	segments := &screensv1.PageSegments{Caption: "Finance"}
	var all []*screensv1.PagePanelItem
	for i, t := range tabs {
		items := t.panelItems(i == 0, opens)
		all = append(all, items...)
		segments.Segments = append(segments.Segments, &screensv1.PageSegment{
			Label: t.label + " (" + strconv.Itoa(len(t.items)) + ")", Blocks: []*screensv1.PageBlock{panel(items...)}})
	}
	h := &screensv1.PageHeader{Eyebrow: "Finance", Title: "Closure Readiness Workspace",
		Description: "Controlled activity closure pipeline. Monitor readiness checks, clear pending analytics publishing, resolve blockers, and lock historic audit files.",
		Badges:      []*screensv1.PageBadge{}, Actions: []*screensv1.PageAction{
			{Key: "view_completed_archive", Label: "View Completed Archive", Primary: true, Enabled: true, Href: CompletedPath},
			{Key: "blocked_closures", Label: "Blocked Closures", Enabled: true, Href: BlockedPath + "/"},
		}}
	// The feed reads the tabs' rows twice: in the switch, then as one panel.
	return &screensv1.GetPageResponse{Header: h, Tabs: []*screensv1.PageTab{}, Dialogs: []*screensv1.PageDialog{},
		Blocks: []*screensv1.PageBlock{
			{Kind: &screensv1.PageBlock_Segments{Segments: segments}},
			panel(all...),
		}, WebPath: QueuePath}, true, nil
}

// panelItems are a tab's rows as the feed reads them: the id and type; the
// school (a link for those who open schools) or Cluster-wide, with the
// owner on the Ready tab; the state; the workspace link. Or the empty line.
func (t *queueTab) panelItems(ready, opens bool) []*screensv1.PagePanelItem {
	if len(t.items) == 0 {
		return []*screensv1.PagePanelItem{text(t.empty)}
	}
	var out []*screensv1.PagePanelItem
	for _, a := range t.items {
		short := a.id[:min(8, len(a.id))]
		out = append(out, text("#"+short+" • "+calendarpage.ActivityTypeLabel(a.kind)))
		out = append(out, a.placeItem(ready, opens))
		out = append(out, text(t.pill), links(&screensv1.PageLink{Text: t.link, Href: "/activities/" + a.id + "/closure/"}))
	}
	return out
}

func (a closureItem) placeItem(ready, opens bool) *screensv1.PagePanelItem {
	place := "Cluster-wide"
	if a.schoolID != "" {
		place = a.schoolName
	}
	if ready {
		owner := "None"
		if a.owner != nil {
			owner = *a.owner
		}
		item := text(place + " • Owner: " + owner)
		if a.schoolID != "" && opens {
			item.TextLinks = []*screensv1.PageLink{{Text: a.schoolName, Href: "/schools/" + a.schoolID}}
		}
		return item
	}
	if a.schoolID != "" && opens {
		return links(&screensv1.PageLink{Text: a.schoolName, Href: "/schools/" + a.schoolID})
	}
	return text(place)
}

// readQueue is the view's queryset: the reader's live work (reachOf) past
// its doing and not closed, called-off work only while money it was paid
// is out, newest first, to the queue's limit, with every closure fact.
func (s *Service) readQueue(ctx context.Context, scope schooldirectory.Scope, p auth.Principal) ([]closureItem, error) {
	q := rules.Queue
	reach, args := reachOf(scope, p, "a")
	arg := func(v any) string { args = append(args, v); return "$" + strconv.Itoa(len(args)) }
	moved := `SELECT 1 FROM advance_request r WHERE r.activity_id = a.id AND r.status = ANY(` + arg(q.MovedAdvance) + `)`
	sql := `
SELECT a.id, a.activity_type, a.status, COALESCE(a.delivery_type, ''), COALESCE(a.payment_status, ''),
  COALESCE(a.salesforce_activity_id, ''), UPPER(COALESCE(a.salesforce_record_type_snapshot, '')),
  COALESCE(sc.id, ''), COALESCE(sc.name, ''), a.responsible_staff_id,
  EXISTS (SELECT 1 FROM evidence_record e WHERE e.activity_id = a.id AND NOT e.quarantined),
  EXISTS (SELECT 1 FROM activity_schedule_cost_line l WHERE l.activity_id = a.id),
  EXISTS (SELECT 1 FROM netsuite_expense_record n WHERE n.activity_id = a.id),
  EXISTS (SELECT 1 FROM advance_request r WHERE r.activity_id = a.id AND r.status = ANY(` + arg(q.ClearedAdvance) + `)),
  EXISTS (` + moved + `),
  EXISTS (` + moved + ` AND (r.accountability_netsuite_id IS NULL OR r.accountability_netsuite_id = '')),
  COALESCE((SELECT pr.status FROM analytics_publish_record pr WHERE pr.activity_id = a.id LIMIT 1), '')
FROM activity a LEFT JOIN school sc ON sc.id = a.school_id
WHERE ` + reach + ` AND a.status <> ALL(` + arg(q.NotStarted) + `) AND a.status <> 'closed'
  AND NOT (a.status = ANY(` + arg(q.CalledOff) + `) AND NOT EXISTS (` + moved + `))
ORDER BY a.updated_at DESC, a.id DESC
LIMIT ` + arg(q.Limit)
	rows, err := s.db.Query(ctx, sql, args...)
	if err != nil {
		return nil, fmt.Errorf("closurepages: reading the closure queue: %w", err)
	}
	defer rows.Close()
	out := []closureItem{}
	for rows.Next() {
		var a closureItem
		if err := rows.Scan(&a.id, &a.kind, &a.status, &a.delivery, &a.payment, &a.salesforce, &a.recordType,
			&a.schoolID, &a.schoolName, &a.owner, &a.evidence, &a.costLines, &a.netsuite, &a.cleared,
			&a.moved, &a.unaccounted, &a.publish); err != nil {
			return nil, fmt.Errorf("closurepages: reading a queued activity: %w", err)
		}
		out = append(out, a)
	}
	return out, rows.Err()
}
