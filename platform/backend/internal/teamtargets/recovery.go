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
// (newest first, thirty at most) and the team's behind members, read for the
// page as it opens (the view ignores the query). A submitted plan's Approve
// and Return forms are read as their buttons' words, the first plan's
// Approve as the drawer's own button; the feed saves neither (their route is
// not one it saves), so a press is answered as unavailable either way. A
// read during which get_page would write is handed on.
func Recovery(ctx context.Context, db schooldirectory.Querier, p auth.Principal, now time.Time) (*screensv1.PageDrawer, error) {
	if !slices.Contains(rules.PageRoles, p.ActiveRole) {
		return nil, &RefusedError{Refusal}
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
	plans, err := openPlans(ctx, db, p.UserID)
	if err != nil {
		return nil, err
	}
	names := map[string]string{}
	for _, r := range d.t.rows {
		names[r.member.UserID] = r.member.Name
	}
	drawer := &screensv1.PageDrawer{Title: "Recovery approval queue", HasRequired: true, CancelLabel: "Cancel"}
	if len(plans) == 0 {
		drawer.Items = []*screensv1.DrawerItem{text("No catch-up plans yet."), text("Create one from any behind row in Target Recovery Focus.")}
	} else {
		drawer.Items = []*screensv1.DrawerItem{text("Approving a catch-up plan sends its activities into Planning.")}
		for _, c := range plans {
			staff := names[c.staff]
			if staff == "" {
				staff = "—"
			}
			line := fmt.Sprintf("%s · %s %s · %d proposed · %d school(s)", staff, c.area, targets.MonthLabel(c.fy, c.month), c.proposed, c.schools)
			if c.dated {
				line += " · dated (will be scheduled & costed)"
			}
			if c.note != "" {
				line += " " + c.note
			}
			if c.status == "returned" && c.returnReason != "" {
				line += " Returned: " + c.returnReason
			}
			label := rules.CatchUpStatuses[c.status]
			if label == "" {
				label = c.status
			}
			line += " " + label
			if c.status == "submitted" {
				line += " Approve Return"
				if !drawer.CanSubmit {
					drawer.SubmitLabel, drawer.CanSubmit = "Approve", true
				}
			}
			drawer.Items = append(drawer.Items, text(line))
		}
	}
	if len(found) > 0 {
		drawer.Items = append(drawer.Items, &screensv1.DrawerItem{Kind: &screensv1.DrawerItem_Heading{Heading: "Currently behind — candidates for recovery"}})
		for _, c := range found[:min(recoveryLimit, len(found))] {
			// The feed reads the row's two lines as one run and the risk
			// pill after a space.
			drawer.Items = append(drawer.Items, text(fmt.Sprintf("%s · %sgap %d · %s %s", c.staff, c.area, c.gap, c.reason, c.risk)))
		}
	}
	return drawer, nil
}

// catchUp is one CatchUpPlan as the queue shows it.
type catchUp struct {
	staff, area, fy, note, status, returnReason string
	month, proposed, schools                    int
	dated                                       bool
}

// planLimit is the queue's `[:30]`.
const planLimit = 30

// openPlans are the reader's catch-up plans not closed, newest first.
func openPlans(ctx context.Context, db schooldirectory.Querier, leadUserID string) ([]catchUp, error) {
	rows, err := db.Query(ctx, `SELECT p.staff_user_id, COALESCE(a.label, ''), p.fy, COALESCE(p.note, ''), p.status, COALESCE(p.return_reason, ''),
  p.month_of_fy, p.activities_proposed, jsonb_array_length(COALESCE(p.school_ids, '[]'::jsonb)),
  jsonb_array_length(COALESCE(p.planned_dates, '[]'::jsonb)) > 0
FROM target_catchup_plan p LEFT JOIN target_area a ON a.id = p.area_id
WHERE p.pl_user_id = $1 AND p.status <> 'closed' ORDER BY p.created_at DESC, p.id LIMIT $2`, leadUserID, planLimit)
	if err != nil {
		return nil, fmt.Errorf("teamtargets: the catch-up plans: %w", err)
	}
	defer rows.Close()
	out := []catchUp{}
	for rows.Next() {
		var c catchUp
		if err := rows.Scan(&c.staff, &c.area, &c.fy, &c.note, &c.status, &c.returnReason, &c.month, &c.proposed, &c.schools, &c.dated); err != nil {
			return nil, err
		}
		out = append(out, c)
	}
	return out, rows.Err()
}
