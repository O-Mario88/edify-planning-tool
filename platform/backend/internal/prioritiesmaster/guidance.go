package prioritiesmaster

import (
	"context"
	"fmt"
	"net/url"
	"strconv"
	"time"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pagegate"
)

// GuidancePath is the Programme Lead "Team Guidance" workspace (/priorities/guidance).
const GuidancePath = "/priorities/guidance"

var guidanceRoles = map[string]bool{
	"Program Lead":     true,
	"ImpactAssessment": true,
	"Admin":            true,
}

func (s *Service) buildGuidance(ctx context.Context, p auth.Principal, _ url.Values) (*screensv1.GetPageResponse, bool, error) {
	if !guidanceRoles[p.ActiveRole] {
		return nil, true, pagegate.ErrNotAvailable
	}

	var sql string
	var args []any
	if p.ActiveRole == "Program Lead" {
		sql = `
SELECT g.id, COALESCE(g.title, 'Guidance'), COALESCE(u.name, 'Programme Lead'),
       g.issued_at, g.review_on,
       (SELECT COUNT(*) FROM cce_team_guidance_receipt r WHERE r.guidance_id = g.id),
       (SELECT COUNT(*) FROM cce_team_guidance_receipt r WHERE r.guidance_id = g.id AND r.acknowledged_at IS NOT NULL)
FROM cce_team_guidance g
LEFT JOIN "user" u ON u.id = g.author_id
WHERE g.withdrawn_at IS NULL AND g.author_id = $1
ORDER BY g.created_at DESC
LIMIT 40`
		args = []any{p.UserID}
	} else {
		sql = `
SELECT g.id, COALESCE(g.title, 'Guidance'), COALESCE(u.name, 'Programme Lead'),
       g.issued_at, g.review_on,
       (SELECT COUNT(*) FROM cce_team_guidance_receipt r WHERE r.guidance_id = g.id),
       (SELECT COUNT(*) FROM cce_team_guidance_receipt r WHERE r.guidance_id = g.id AND r.acknowledged_at IS NOT NULL)
FROM cce_team_guidance g
LEFT JOIN "user" u ON u.id = g.author_id
WHERE g.withdrawn_at IS NULL
ORDER BY g.created_at DESC
LIMIT 40`
	}

	rows, err := s.db.Query(ctx, sql, args...)
	if err != nil {
		return nil, true, fmt.Errorf("prioritiesmaster: reading team guidance: %w", err)
	}
	defer rows.Close()

	tbl := &screensv1.PageTable{
		Columns: []*screensv1.PageColumn{
			{Label: "Title"},
			{Label: "Author"},
			{Label: "Status"},
			{Label: "Review on"},
			{Label: "Acknowledgements"},
		},
	}
	var issuedCount, draftCount, pendingAcks int
	for rows.Next() {
		var id, title, author string
		var issuedAt, reviewOn *time.Time
		var totalRec, ackedRec int
		if err := rows.Scan(&id, &title, &author, &issuedAt, &reviewOn, &totalRec, &ackedRec); err != nil {
			return nil, true, fmt.Errorf("prioritiesmaster: scanning guidance row: %w", err)
		}
		status := "Draft"
		if issuedAt != nil {
			status = "Issued"
			issuedCount++
		} else {
			draftCount++
		}
		pendingAcks += totalRec - ackedRec
		reviewText := "—"
		if reviewOn != nil {
			reviewText = reviewOn.Format("02 Jan 2006")
		}
		tbl.Rows = append(tbl.Rows, &screensv1.PageRow{
			Cells: []*screensv1.PageCell{
				{Text: title},
				{Text: author},
				{Text: status},
				{Text: reviewText},
				{Text: fmt.Sprintf("%d / %d", ackedRec, totalRec)},
			},
		})
	}
	if err := rows.Err(); err != nil {
		return nil, true, fmt.Errorf("prioritiesmaster: guidance rows: %w", err)
	}

	tabs := &screensv1.PageLinkTabs{
		Scrolls: true,
		Tabs: []*screensv1.PageLinkTab{
			{Label: "Priority Setting", Href: StrategicPath},
			{Label: "Target Distribution", Href: Path},
			{Label: "My Team", Href: "/target-distribution/team"},
			{Label: "Team Guidance", Href: GuidancePath, Active: true},
		},
	}

	blocks := []*screensv1.PageBlock{
		{Kind: &screensv1.PageBlock_LinkTabs{LinkTabs: tabs}},
		{Kind: &screensv1.PageBlock_Strip{Strip: &screensv1.PageStrip{
			Title: "Team guidance overview",
			Metrics: []*screensv1.PageMetric{
				{Label: "Issued", Value: strconv.Itoa(issuedCount), Note: "Active guidance notes"},
				{Label: "Drafts", Value: strconv.Itoa(draftCount), Note: "Awaiting issue"},
				{Label: "Pending acks", Value: strconv.Itoa(pendingAcks), Note: "Officers yet to confirm"},
			},
		}}},
	}
	if len(tbl.Rows) == 0 {
		blocks = append(blocks, &screensv1.PageBlock{Kind: &screensv1.PageBlock_Empty{
			Empty: "No active team guidance notes have been authored yet.",
		}})
	} else {
		blocks = append(blocks, &screensv1.PageBlock{Kind: &screensv1.PageBlock_Table{Table: tbl}})
	}

	return &screensv1.GetPageResponse{
		Header: &screensv1.PageHeader{
			Eyebrow:     "Strategy",
			Title:       "Team Guidance",
			Description: "Priority guidance issued to field officers and acknowledgement status.",
		},
		WebPath: GuidancePath,
		Blocks:  blocks,
	}, true, nil
}
