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
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/stafflogs"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/tablepager"
)

// The Analytics Publishing Status page (closure_views.
// analytics_publishing_status_view in the analytics workspace,
// partials/analytics/panels/publishing_status.html): every analytics publish
// record, failures first (owner, 2026-11-18), with its activity and school.

// PublishingPath is the page.
const PublishingPath = "/analytics/publishing"

const (
	publishingPageParam = "publishing_status_records_page"
	publishingPageSize  = 50
	publishingEmpty     = "No items found in analytics publishing queue."
	publishingSuccess   = "Success. Broadcast published to target reports."
)

// publishRecord is one AnalyticsPublishRecord with its activity.
type publishRecord struct {
	activityID, kind, status, message string
	schoolID, schoolName              string
	published                         *time.Time
}

// readPublishRecords is the view's queryset: failures first, then pending,
// then published, anything else last, oldest first within each.
func (s *Service) readPublishRecords(ctx context.Context) ([]publishRecord, error) {
	statuses, ranks := []string{}, []int{}
	for status, rank := range rules.PublishStatusRank {
		statuses, ranks = append(statuses, status), append(ranks, rank)
	}
	rows, err := s.db.Query(ctx, `
SELECT r.activity_id, a.activity_type, r.status, COALESCE(r.error_message, ''), COALESCE(sc.id, ''), COALESCE(sc.name, ''),
  r.published_at
FROM analytics_publish_record r
INNER JOIN activity a ON a.id = r.activity_id
LEFT JOIN school sc ON sc.id = a.school_id
LEFT JOIN unnest($1::varchar[], $2::int[]) AS rank(status, n) ON rank.status = r.status
ORDER BY COALESCE(rank.n, $3), r.created_at, r.activity_id, r.id`, statuses, ranks, rules.PublishStatusOtherRank)
	if err != nil {
		return nil, fmt.Errorf("closurepages: reading the publish records: %w", err)
	}
	defer rows.Close()
	out := []publishRecord{}
	for rows.Next() {
		var r publishRecord
		if err := rows.Scan(&r.activityID, &r.kind, &r.status, &r.message, &r.schoolID, &r.schoolName, &r.published); err != nil {
			return nil, fmt.Errorf("closurepages: reading a publish record: %w", err)
		}
		out = append(out, r)
	}
	return out, rows.Err()
}

// publishing draws the page.
func (s *Service) publishing(ctx context.Context, p auth.Principal, query url.Values) (*screensv1.GetPageResponse, bool, error) {
	d, ok := rules.Roles[p.ActiveRole]
	if !ok {
		return nil, false, nil
	}
	if !d.Publishing {
		return nil, true, pagegate.ErrNotAvailable
	}
	list, err := s.readPublishRecords(ctx)
	if err != nil {
		return nil, true, err
	}
	blocks := workspaceFrame("Analytics Publishing Status", d.PublishingStrip, frame{
		question:  "Which verified records have not reached official reporting systems, and what is blocking publication?",
		evidence:  "Analytics publishing queue and integration logs",
		freshness: "Live pipeline state",
	})
	blocks = append(blocks, publishingTable(list, d, query)...)
	return workspacePage("Analytics Publishing Status", blocks, PublishingPath), true, nil
}

// publishingTable is the records' table, fifty a page, and its pager. With
// none, the empty row, which the feed also reads as the table's empty message.
func publishingTable(list []publishRecord, d role, query url.Values) []*screensv1.PageBlock {
	t := &screensv1.PageTable{Columns: []*screensv1.PageColumn{{Label: "Activity ID"}, {Label: "School ID"},
		{Label: "School / Scope"}, {Label: "Activity Type"}, {Label: "Status"}, {Label: "Published Date"},
		{Label: "Logs / Errors"}}}
	if len(list) == 0 {
		t.Rows = []*screensv1.PageRow{{Cells: []*screensv1.PageCell{{Text: publishingEmpty}}}}
		t.EmptyMessage = publishingEmpty
	}
	page := tablepager.Paginate(len(list), publishingPageSize, query, publishingPageParam)
	for _, r := range list[page.Start:page.End] {
		short := r.activityID
		if len([]rune(short)) > 8 {
			short = string([]rune(short)[:8])
		}
		// The School ID is written in after the page is drawn; the feed reads
		// its place as empty.
		code, school := "—", &screensv1.PageCell{Text: "Cluster-wide"}
		if r.schoolID != "" {
			code, school.Text = "", r.schoolName
			if d.OpenSchool {
				school.Href = "/schools/" + r.schoolID
			}
		}
		published := "Pending"
		if r.published != nil {
			published = r.published.In(calendarpage.Location()).Format("Jan 02, 2006 15:04")
		}
		message := r.message
		if message == "" {
			message = publishingSuccess
		}
		t.Rows = append(t.Rows, &screensv1.PageRow{Cells: []*screensv1.PageCell{
			{Text: "#" + short}, {Text: code}, school, {Text: calendarpage.ActivityTypeLabel(r.kind), Tone: "primary", Badge: true},
			{Text: stafflogs.StatusLabel(r.status), Tone: "primary", Badge: true}, {Text: published}, {Text: message},
		}})
	}
	blocks := []*screensv1.PageBlock{{Kind: &screensv1.PageBlock_Table{Table: t}}}
	if pager := tablepager.Panel(len(list), publishingPageSize, query, publishingPageParam); pager != nil {
		blocks = append(blocks, pager)
	}
	return blocks
}
