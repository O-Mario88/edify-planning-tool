package iapages

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

// LearningPath is the IA Learning & Findings workspace (/ia/learning/).
const LearningPath = "/ia/learning/"

var learningRoles = map[string]bool{
	"CountryDirector":  true,
	"ImpactAssessment": true,
	"Admin":            true,
}

func (s *Service) learning(ctx context.Context, p auth.Principal, _ url.Values) (*screensv1.GetPageResponse, bool, error) {
	if !learningRoles[p.ActiveRole] {
		return nil, true, pagegate.ErrNotAvailable
	}

	var totalFindings, openFindings, pendingConclusions, verifiedConclusions int
	if err := s.db.QueryRow(ctx, `SELECT
		(SELECT COUNT(*) FROM impact_finding),
		(SELECT COUNT(*) FROM impact_finding WHERE status NOT IN ('published', 'archived', 'closed')),
		(SELECT COUNT(*) FROM bt_loan_impact_assessment WHERE ia_status <> 'verified'),
		(SELECT COUNT(*) FROM bt_loan_impact_assessment WHERE ia_status = 'verified')`).
		Scan(&totalFindings, &openFindings, &pendingConclusions, &verifiedConclusions); err != nil {
		return nil, true, fmt.Errorf("iapages: learning counts: %w", err)
	}

	rows, err := s.db.Query(ctx, `
SELECT a.id, COALESCE(s.name, 'School'), COALESCE(a.classification, '—'), COALESCE(a.ia_status, 'pending'), a.due_date
FROM bt_loan_impact_assessment a
LEFT JOIN bt_mfi_loan l ON l.id = a.loan_id
LEFT JOIN school s ON s.id = l.school_id
ORDER BY a.due_date ASC NULLS LAST, a.updated_at DESC
LIMIT 30`)
	if err != nil {
		return nil, true, fmt.Errorf("iapages: learning conclusions: %w", err)
	}
	defer rows.Close()

	tbl := &screensv1.PageTable{
		Columns: []*screensv1.PageColumn{
			{Label: "School"},
			{Label: "Classification"},
			{Label: "IA status"},
			{Label: "Due date"},
		},
	}
	for rows.Next() {
		var id, schoolName, classification, status string
		var due *time.Time
		if err := rows.Scan(&id, &schoolName, &classification, &status, &due); err != nil {
			return nil, true, fmt.Errorf("iapages: scanning learning conclusion: %w", err)
		}
		dueText := "—"
		if due != nil {
			dueText = due.Format("02 Jan 2006")
		}
		tbl.Rows = append(tbl.Rows, &screensv1.PageRow{
			Cells: []*screensv1.PageCell{
				{Text: schoolName},
				{Text: classification},
				{Text: status},
				{Text: dueText},
			},
		})
	}
	if err := rows.Err(); err != nil {
		return nil, true, fmt.Errorf("iapages: learning conclusions rows: %w", err)
	}

	tabs := &screensv1.PageLinkTabs{
		Scrolls: true,
		Tabs: []*screensv1.PageLinkTab{
			{Label: "Learning", Href: LearningPath, Active: true},
			{Label: "Lending Evidence", Href: LendingPath},
			{Label: "Impact Reports", Href: ReportsPath},
			{Label: "Stories", Href: StoriesPath},
		},
	}

	blocks := []*screensv1.PageBlock{
		{Kind: &screensv1.PageBlock_LinkTabs{LinkTabs: tabs}},
		{Kind: &screensv1.PageBlock_Strip{Strip: &screensv1.PageStrip{
			Title: "Impact learning overview",
			Metrics: []*screensv1.PageMetric{
				{Label: "Total findings", Value: strconv.Itoa(totalFindings), Note: "Recorded impact findings"},
				{Label: "Open findings", Value: strconv.Itoa(openFindings), Note: "In review or draft"},
				{Label: "Pending conclusions", Value: strconv.Itoa(pendingConclusions), Note: "Loan impact awaiting IA"},
				{Label: "Verified conclusions", Value: strconv.Itoa(verifiedConclusions), Note: "IA signed off"},
			},
		}}},
	}
	if len(tbl.Rows) == 0 {
		blocks = append(blocks, &screensv1.PageBlock{Kind: &screensv1.PageBlock_Empty{
			Empty: "No loan impact conclusions are recorded yet.",
		}})
	} else {
		blocks = append(blocks, &screensv1.PageBlock{Kind: &screensv1.PageBlock_Table{Table: tbl}})
	}

	return &screensv1.GetPageResponse{
		Header: &screensv1.PageHeader{
			Eyebrow:     "Impact Assessment",
			Title:       "Impact Learning & Findings",
			Description: "Governed impact findings and loan impact conclusions awaiting verification.",
		},
		WebPath: LearningPath,
		Blocks:  blocks,
	}, true, nil
}
