package teamtargets

import (
	"context"
	"slices"
	"strconv"
	"time"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/allocations"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/mytargets"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pagegate"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/targets"
)

// kampala is where the platform's days are counted.
var kampala = func() *time.Location {
	if l, err := time.LoadLocation("Africa/Kampala"); err == nil {
		return l
	}
	return time.FixedZone("EAT", 3*3600)
}()

// maxPartners is TABLE_PAGE_SIZE: more Partners page, which Go does not draw yet.
const maxPartners = 50

// Page is team_targets_view as the feed reads it, or ErrHandOn.
func Page(ctx context.Context, db schooldirectory.Querier, p auth.Principal, raw map[string]string, now time.Time) (*screensv1.GetPageResponse, error) {
	if !slices.Contains(rules.PageRoles, p.ActiveRole) {
		return nil, pagegate.ErrNotAvailable
	}
	l := now.In(kampala)
	today := time.Date(l.Year(), l.Month(), l.Day(), 0, 0, 0, 0, time.UTC)
	operational := strconv.Itoa(l.Year())
	if l.Month() >= time.October {
		operational = strconv.Itoa(l.Year() + 1)
	}
	d, err := read(ctx, db, p, readQuery(raw), today, operational)
	if err != nil {
		return nil, err
	}
	if d.ranked || d.groupByLead {
		return nil, ErrHandOn // the ranked and Lead-grouped orders are not drawn yet
	}
	if len(d.t.rows) > 0 && len(d.t.areas) > 0 {
		return nil, ErrHandOn // the member matrix is not drawn yet
	}
	if w, err := wouldWrite(ctx, db, p.UserID, d.fy, d.current, d.t); err != nil || w {
		return nil, handOnOr(err)
	}
	if a, err := d.assigned(ctx, db); err != nil || a {
		return nil, handOnOr(err)
	}
	blocks, err := d.blocks(ctx, db, p, now)
	if err != nil {
		return nil, err
	}
	return &screensv1.GetPageResponse{Header: &screensv1.PageHeader{Title: "Planning Oversight",
		Description: "Track validated team performance across the selected month, quarters, and full fiscal year."}, Blocks: blocks}, nil
}

func handOnOr(err error) error {
	if err != nil {
		return err
	}
	return ErrHandOn
}

// blocks draws the workspace.
func (d *data) blocks(ctx context.Context, db schooldirectory.Querier, p auth.Principal, now time.Time) ([]*screensv1.PageBlock, error) {
	strategic, err := mytargets.StrategicPriorityBlocks(ctx, db, d.fy, d.t.staffIDs(), "the selected supervised-team target ledger")
	if err != nil {
		return nil, err
	}
	contract, err := allocations.Read(ctx, db, p, d.fy, now, d.today)
	if err != nil {
		return nil, err
	}
	sfPct, sfMissing, err := d.sfCompliance(ctx, db)
	if err != nil {
		return nil, err
	}
	_ = sfPct
	c, err := d.corePackages(ctx, db)
	if err != nil {
		return nil, err
	}
	signals, err := d.attention(ctx, db, c)
	if err != nil {
		return nil, err
	}
	plans, planCount, _, err := d.recoveryPlans(ctx, db, p.UserID)
	if err != nil {
		return nil, err
	}
	awaiting, returned, err := d.validation(ctx, db)
	if err != nil {
		return nil, err
	}
	partners, err := d.partners(ctx, db)
	if err != nil {
		return nil, err
	}
	if len(partners) > maxPartners {
		return nil, ErrHandOn
	}
	teamPct, _, _ := d.t.weighted([]int{d.month})
	quarterPct, _, _ := d.t.raw(targets.MonthsOfQuarter(targets.QuarterOfMonth(d.month)))
	fyPct, _, _ := d.t.weighted([]int{1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12})
	onTrack := len(d.t.where("On Track", "Complete", "Exceeded"))
	rate := 0
	if len(d.t.rows) > 0 {
		rate = pyRound(float64(onTrack) / float64(len(d.t.rows)) * 100)
	}
	atRisk := len(d.t.where("High Risk", "Critical"))
	out := []*screensv1.PageBlock{d.filtersBlock()}
	out = append(out, strategic...)
	out = append(out, allocations.SummaryBlocks(contract)...)
	out = append(out, stripBlock(teamPct, rate, atRisk, quarterPct, fyPct, planCount))
	body := el("div", "tt-dashboard",
		d.commandGrid(d.emptyMatrix(), d.supportStaff(), plans, awaiting, sfMissing, returned),
		d.signals(signals), d.insights(d.keyProgress(), d.trend(), teamPct), d.lower(partners, d.districtsBehind()),
		dataNote(now.In(kampala)), d.projectSection(), d.milestoneSection())
	return feedWalk(body, out), nil
}
