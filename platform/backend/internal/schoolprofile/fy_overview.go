package schoolprofile

import (
	"context"
	"fmt"
	"math"
	"strconv"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pagegate"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// The Fiscal Year Overview (extended_views.fy_overview_view,
// pages/fy/index.html): the operating schools, how many schools have an SSA
// this operational year, and how much of the work in the plan is done.

const fyOverviewPath = "/fy"

// fyFigures are the view's counts.
type fyFigures struct {
	schools, ssaDone, activities, completed int
}

// rate is round(completed / max(activities, 1) * 100), Python's round.
func (f fyFigures) rate() int {
	return int(math.RoundToEven(float64(f.completed) / float64(max(f.activities, 1)) * 100))
}

// readFYFigures is the view's four counts.
func (s *Service) readFYFigures(ctx context.Context, fy string) (fyFigures, error) {
	var f fyFigures
	err := s.db.QueryRow(ctx, `
SELECT
  (SELECT count(*) FROM school s WHERE s.deleted_at IS NULL AND s.operational_status = ANY($2)),
  (SELECT count(DISTINCT r.school_id) FROM ssa_record r WHERE r.fy = $1 AND r.deleted_at IS NULL),
  (SELECT count(*) FROM activity a WHERE a.deleted_at IS NULL AND NOT (a.status = ANY($3))),
  (SELECT count(*) FROM activity a WHERE a.deleted_at IS NULL AND a.status = ANY($4))`,
		fy, rules.Engine.Scope.OperatingStatuses, rules.Engine.NotInPlanStatuses, rules.Engine.CompletedWorkStatuses).
		Scan(&f.schools, &f.ssaDone, &f.activities, &f.completed)
	if err != nil {
		return f, fmt.Errorf("schoolprofile: reading the year's figures: %w", err)
	}
	return f, nil
}

// fyOverview draws /fy for a reader of planning.
func (sp *ScopePages) fyOverview(ctx context.Context, p auth.Principal) (*screensv1.GetPageResponse, bool, error) {
	if !rules.Doors[p.ActiveRole].OpenDistrict {
		return nil, true, pagegate.ErrNotAvailable
	}
	fy := schooldirectory.OperationalFY(sp.s.now())
	f, err := sp.s.readFYFigures(ctx, fy)
	if err != nil {
		return nil, true, err
	}
	rate := strconv.Itoa(f.rate()) + "%"
	metric := func(label, value string) *screensv1.PageMetric {
		return &screensv1.PageMetric{Label: label, Value: value}
	}
	strip := &screensv1.PageStrip{Title: "Performance overview", Metrics: []*screensv1.PageMetric{
		metric("Total Schools", strconv.Itoa(f.schools)), metric("SSA Done", strconv.Itoa(f.ssaDone)),
		metric("SSA Pending", strconv.Itoa(f.schools-f.ssaDone)), metric("Activity Rate", rate)}}
	summary := &screensv1.PagePanel{Title: "FY" + fy + " Summary", Badges: []*screensv1.PageBadge{},
		Items: []*screensv1.PagePanelItem{{Kind: &screensv1.PagePanelItem_Text{Text: fmt.Sprintf(
			"%d total activities · %d completed · %s completion rate", f.activities, f.completed, rate)}}}}
	header := &screensv1.PageHeader{Eyebrow: "Finance", Title: "Fiscal Year Overview",
		Description: "Edify Operations · Fiscal Year Overview", Badges: []*screensv1.PageBadge{}, Actions: []*screensv1.PageAction{}}
	return &screensv1.GetPageResponse{Header: header, Blocks: []*screensv1.PageBlock{
		{Kind: &screensv1.PageBlock_Strip{Strip: strip}}, {Kind: &screensv1.PageBlock_Panel{Panel: summary}}},
		WebPath: fyOverviewPath}, true, nil
}
