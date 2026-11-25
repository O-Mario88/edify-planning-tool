package teamtargets

import (
	"context"
	"fmt"
	"slices"
	"sort"
	"strconv"
	"time"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/mytargets"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/targets"
)

// candidate is one row of get_page's Recovery focus: a behind member's
// area, with what holds it back.
type candidate struct {
	staff, area, reason, risk string
	gap                       int
}

// recoveryLimit is the queue's `recovery|slice:":8"`.
const recoveryLimit = 8

// recovery is get_page's recovery list: each behind member's two weakest
// metric areas with a target (a gap of nothing skipped), the blocker of
// each, ordered Critical, High Risk, Slightly Behind, then the widest gap.
func (d *data) recovery(ctx context.Context, db schooldirectory.Querier) ([]candidate, error) {
	keys := map[string]bool{}
	for _, a := range d.t.metricAreas {
		keys[a.Key] = true
	}
	left := 0
	if d.today.Before(d.end) {
		from := d.start
		if d.today.After(from) {
			from = d.today
		}
		left = d.roster.WorkingDays(from, d.end)
	}
	out := []candidate{}
	for _, r := range d.t.where("Slightly Behind", "High Risk", "Critical") {
		worst := []targets.AreaMonth{}
		for _, pa := range r.PerArea {
			if pa.Target != 0 && keys[pa.Key] {
				worst = append(worst, pa)
			}
		}
		sort.SliceStable(worst, func(i, j int) bool { return pctOrZero(worst[i].Pct) < pctOrZero(worst[j].Pct) })
		for _, pa := range worst[:min(2, len(worst))] {
			if pa.Gap <= 0 {
				continue
			}
			reason, err := d.blocker(ctx, db, r.member, pa, left)
			if err != nil {
				return nil, err
			}
			out = append(out, candidate{staff: r.member.Name, area: pa.Label, reason: reason, risk: r.Status, gap: pa.Gap})
		}
	}
	sort.SliceStable(out, func(i, j int) bool {
		if a, b := riskRank(out[i].risk), riskRank(out[j].risk); a != b {
			return a < b
		}
		return out[i].gap > out[j].gap
	})
	return out, nil
}

func pctOrZero(p *int) int {
	if p == nil {
		return 0
	}
	return *p
}

// riskRank is the recovery sort's {"Critical": 0, "High Risk": 1,
// "Slightly Behind": 2} with everything else after.
func riskRank(status string) int {
	if i := slices.Index([]string{"Critical", "High Risk", "Slightly Behind"}, status); i >= 0 {
		return i
	}
	return 3
}

// blocker is _blocker's wording: the first thing in the member's pipeline
// for the area's month that holds it back.
func (d *data) blocker(ctx context.Context, db schooldirectory.Querier, m Member, pa targets.AreaMonth, left int) (string, error) {
	ids := []string{m.UserID}
	if m.StaffID != "" {
		ids = append(ids, m.StaffID)
	}
	p, err := mytargets.CountPipeline(ctx, db, ids, m.UserID, d.fy, pa.Key, d.start, d.end)
	if err != nil {
		return "", err
	}
	switch {
	case p.PendingSF > 0:
		return fmt.Sprintf("%d completed missing Activity SF IDs", p.PendingSF), nil
	case p.Returned > 0:
		return fmt.Sprintf("%d returned item(s) need correction", p.Returned), nil
	case p.IAPending > 0:
		return fmt.Sprintf("%d awaiting IA verification", p.IAPending), nil
	case pa.Key == "mscs" && p.Scheduled == 0:
		return "No MSCS submitted this month", nil
	case p.Scheduled+p.Validated < pa.Target:
		if pa.Gap > left {
			return fmt.Sprintf("Gap of %d exceeds %d working days left", pa.Gap, left), nil
		}
		return fmt.Sprintf("Only %d scheduled toward %d", p.Scheduled, pa.Target), nil
	case p.Scheduled > 0:
		return fmt.Sprintf("%d scheduled but not yet executed", p.Scheduled), nil
	case p.Provisional > 0:
		return fmt.Sprintf("%d awaiting review", p.Provisional), nil
	}
	return "No activity planned yet this month", nil
}

// Recovery is team_targets_recovery_view: the reader's open catch-up plans
// and the team's behind members, read for the page as it opens (the view
// ignores the query). A reader with any catch-up plan open is handed on
// (each submitted plan carries the Approve and Return forms Go does not
// answer yet), as is a read during which get_page would write.
func Recovery(ctx context.Context, db schooldirectory.Querier, p auth.Principal, now time.Time) (*screensv1.PageDrawer, error) {
	if !slices.Contains(rules.PageRoles, p.ActiveRole) {
		return nil, &RefusedError{Refusal}
	}
	var open int
	if err := db.QueryRow(ctx, `SELECT count(*) FROM target_catchup_plan WHERE pl_user_id = $1 AND status <> 'closed'`,
		p.UserID).Scan(&open); err != nil {
		return nil, fmt.Errorf("teamtargets: the catch-up plans: %w", err)
	}
	if open > 0 {
		return nil, ErrHandOn
	}
	l := now.In(kampala)
	today := time.Date(l.Year(), l.Month(), l.Day(), 0, 0, 0, 0, time.UTC)
	operational := strconv.Itoa(l.Year())
	if l.Month() >= time.October {
		operational = strconv.Itoa(l.Year() + 1)
	}
	d, err := read(ctx, db, p, readQuery(map[string]string{}), today, operational)
	if err != nil {
		return nil, err
	}
	if w, err := wouldWrite(ctx, db, p.UserID, d.fy, d.current, d.t); err != nil || w {
		return nil, handOnOr(err)
	}
	found, err := d.recovery(ctx, db)
	if err != nil {
		return nil, err
	}
	items := []*screensv1.DrawerItem{text("No catch-up plans yet."), text("Create one from any behind row in Target Recovery Focus.")}
	if len(found) > 0 {
		items = append(items, &screensv1.DrawerItem{Kind: &screensv1.DrawerItem_Heading{Heading: "Currently behind — candidates for recovery"}})
		for _, c := range found[:min(recoveryLimit, len(found))] {
			// The feed reads the row's two lines as one run and the risk
			// pill after a space.
			items = append(items, text(fmt.Sprintf("%s · %sgap %d · %s %s", c.staff, c.area, c.gap, c.reason, c.risk)))
		}
	}
	return &screensv1.PageDrawer{Title: "Recovery approval queue", HasRequired: true, CancelLabel: "Cancel", Items: items}, nil
}
