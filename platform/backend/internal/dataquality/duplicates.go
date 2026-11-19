package dataquality

import (
	"context"
	"fmt"
	"net/url"

	"github.com/jackc/pgx/v5"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/closedschools"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pagegate"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/tablepager"
)

// DuplicatesPath is the Duplicate Review Queue
// (extended_views.duplicate_review_view over data_quality.open_issues,
// pages/admin/duplicate_review.html): the open duplicate risks at operating
// schools, newest first, fifty a page. Marking a school unique stays the
// existing page's.
const DuplicatesPath = "/data-quality/duplicates"

type duplicateRisk struct {
	code, schoolID, school, status, districtID, district, fix string
}

func (s *Service) duplicates(ctx context.Context, p auth.Principal, query url.Values) (*screensv1.GetPageResponse, bool, error) {
	role, ok := rules.Roles[p.ActiveRole]
	if !ok || !role.Duplicates {
		return nil, true, pagegate.ErrNotAvailable
	}
	rows, err := s.db.Query(ctx, `
SELECT COALESCE(s.school_id, 'None'), s.id, s.name, COALESCE(s.duplicate_status, 'None'),
  COALESCE(d.id, ''), COALESCE(d.name, ''), COALESCE(i.suggested_fix, 'None')
FROM data_quality_issue i JOIN school s ON s.id = i.school_id LEFT JOIN district d ON d.id = s.district_id
WHERE i.status = 'open' AND i.issue_type = 'duplicate_risk'
  AND s.deleted_at IS NULL AND s.operational_status = ANY($1)
ORDER BY i.created_at DESC`, rules.OperatingStatuses)
	if err != nil {
		return nil, true, fmt.Errorf("dataquality: reading the duplicate risks: %w", err)
	}
	risks, err := pgx.CollectRows(rows, func(r pgx.CollectableRow) (duplicateRisk, error) {
		var d duplicateRisk
		return d, r.Scan(&d.code, &d.schoolID, &d.school, &d.status, &d.districtID, &d.district, &d.fix)
	})
	if err != nil {
		return nil, true, fmt.Errorf("dataquality: reading the duplicate risks: %w", err)
	}
	t := &screensv1.PageTable{}
	for i, c := range []string{"School ID", "School Name", "District", "Suggested Fix", "Resolve"} {
		t.Columns = append(t.Columns, &screensv1.PageColumn{Label: c, Numeric: i == 4})
	}
	pg := tablepager.Paginate(len(risks), rules.PageSize, query, "issues_page")
	for _, d := range risks[pg.Start:pg.End] {
		name := &screensv1.PageCell{Text: closedschools.Collapse(d.school + " Status: " + d.status)}
		if role.SchoolProfiles {
			name.Href = "/schools/" + d.schoolID
		}
		district := &screensv1.PageCell{Text: closedschools.Collapse(d.district)}
		if role.DistrictProfiles && d.districtID != "" {
			district.Href = "/districts/" + d.districtID
		}
		t.Rows = append(t.Rows, &screensv1.PageRow{Cells: []*screensv1.PageCell{
			{Text: d.code}, name, district, {Text: closedschools.Collapse(d.fix)}, {Text: "Mark as Unique"},
		}})
	}
	if len(risks) == 0 {
		t.Rows = []*screensv1.PageRow{{Cells: []*screensv1.PageCell{{Text: "No active duplicate risks found in directory."}}}}
	}
	blocks := []*screensv1.PageBlock{{Kind: &screensv1.PageBlock_Table{Table: t}}}
	if panel := tablepager.Panel(len(risks), rules.PageSize, query, "issues_page"); panel != nil {
		blocks = append(blocks, panel)
	}
	return &screensv1.GetPageResponse{
		Header: &screensv1.PageHeader{Eyebrow: "Administration", BackLabel: "Back to Quality Center", BackHref: Path,
			Title: "Duplicate Review Queue", Description: "Resolve schools with potential name or location duplicate risks.",
			Badges: []*screensv1.PageBadge{}, Actions: []*screensv1.PageAction{}},
		Blocks: blocks, Tabs: []*screensv1.PageTab{}, Dialogs: []*screensv1.PageDialog{}, WebPath: DuplicatesPath,
	}, true, nil
}
