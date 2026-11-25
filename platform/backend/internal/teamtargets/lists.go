package teamtargets

import (
	"context"
	"fmt"
	"sort"
	"strconv"
	"strings"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/targets"
)

// riskOrder orders by risk: Critical, High Risk, Slightly Behind, the rest.
func riskOrder(status string) int {
	switch status {
	case "Critical":
		return 0
	case "High Risk":
		return 1
	case "Slightly Behind":
		return 2
	}
	return 3
}

// support is one "Staff requiring support" row.
type support struct{ userID, name, initials, district, status, tone, reason string }

func (d *data) supportStaff() []support {
	behind := d.t.where("Slightly Behind", "High Risk", "Critical")
	pct := func(r *row) int {
		if r.MonthPct == nil {
			return 0
		}
		return *r.MonthPct
	}
	sort.SliceStable(behind, func(i, j int) bool {
		if a, b := riskOrder(behind[i].Status), riskOrder(behind[j].Status); a != b {
			return a < b
		}
		return pct(behind[i]) < pct(behind[j])
	})
	keep := map[string]bool{}
	for _, a := range d.t.metricAreas {
		keep[a.Key] = true
	}
	out := []support{}
	for k, r := range behind {
		if k == 4 {
			break
		}
		var worst *targets.AreaMonth
		for i := range r.PerArea {
			a := &r.PerArea[i]
			if !keep[a.Key] || a.Gap <= 0 {
				continue
			}
			if worst == nil || areaPct(a) < areaPct(worst) {
				worst = a
			}
		}
		reason := "Performance is below expected pace"
		if worst != nil {
			reason = worst.Label + " is " + strconv.Itoa(worst.Gap) + " behind plan"
		}
		out = append(out, support{r.member.UserID, r.member.Name, r.initials, r.districtLabel, r.Status, r.Tone, reason})
	}
	return out
}

func areaPct(a *targets.AreaMonth) int {
	if a.Pct == nil {
		return 0
	}
	return *a.Pct
}

// plan is one active recovery plan.
type plan struct {
	staff, area, status, statusKey string
	due                            time.Time
}

// recoveryPlans are the Lead's active catch-up plans for the team this
// year (not returned, completed or closed), the newest four, and how many.
func (d *data) recoveryPlans(ctx context.Context, db schooldirectory.Querier, leadUserID string) ([]plan, int, int, error) {
	names := map[string]string{}
	ids := []string{}
	for _, r := range d.t.rows {
		names[r.member.UserID] = r.member.Name
		ids = append(ids, r.member.UserID)
	}
	rows, err := db.Query(ctx, `SELECT p.staff_user_id, COALESCE(a.label, ''), p.status, p.fy, p.month_of_fy FROM target_catchup_plan p
		LEFT JOIN target_area a ON a.id = p.area_id WHERE p.pl_user_id = $1 AND p.fy = $2 AND p.staff_user_id = ANY($3)
		AND p.status NOT IN ('returned', 'completed', 'closed') ORDER BY p.created_at DESC`, leadUserID, d.fy, ids)
	if err != nil {
		return nil, 0, 0, fmt.Errorf("teamtargets: the recovery plans: %w", err)
	}
	out, count := []plan{}, 0
	for rows.Next() {
		var p plan
		var staff, fy string
		var month int
		if err := rows.Scan(&staff, &p.area, &p.statusKey, &fy, &month); err != nil {
			rows.Close()
			return nil, 0, 0, err
		}
		count++
		if len(out) == 4 {
			continue
		}
		p.staff = names[staff]
		if p.staff == "" {
			p.staff = "Team member"
		}
		p.status = rules.CatchUpStatuses[p.statusKey]
		_, end := targets.MonthRange(fy, month)
		p.due = end.AddDate(0, 0, -1)
		out = append(out, p)
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, 0, 0, err
	}
	var submitted int
	if err := db.QueryRow(ctx, `SELECT count(*) FROM target_catchup_plan WHERE pl_user_id = $1 AND status = 'submitted'`, leadUserID).
		Scan(&submitted); err != nil {
		return nil, 0, 0, fmt.Errorf("teamtargets: the plans awaiting approval: %w", err)
	}
	return out, count, submitted, nil
}

// validation is the awaiting-IA and returned-by-IA counts of the team's
// staff work this year.
func (d *data) validation(ctx context.Context, db schooldirectory.Querier) (int, int, error) {
	ids := d.t.ids()
	if len(ids) == 0 {
		return 0, 0, nil
	}
	var awaiting, returned int
	err := db.QueryRow(ctx, `SELECT count(*) FILTER (WHERE status = 'awaiting_ia_verification'), count(*) FILTER (WHERE status = 'returned_by_ia')
		FROM activity WHERE responsible_staff_id = ANY($1) AND fy = $2 AND deleted_at IS NULL AND delivery_type IS DISTINCT FROM 'partner'`,
		ids, d.fy).Scan(&awaiting, &returned)
	if err != nil {
		return 0, 0, fmt.Errorf("teamtargets: the validation backlog: %w", err)
	}
	return awaiting, returned, nil
}

// trendPoint is one month of the team trend.
type trendPoint struct {
	month string
	pct   *int
}

func (d *data) trend() []trendPoint {
	out := []trendPoint{}
	for m := 1; m <= 12; m++ {
		pct, _, target := d.t.weighted([]int{m})
		label, _, _ := strings.Cut(targets.MonthLabel(d.fy, m), " ")
		if len([]rune(label)) > 3 {
			label = string([]rune(label)[:3])
		}
		p := trendPoint{month: label}
		if target != 0 {
			v := pct
			p.pct = &v
		}
		out = append(out, p)
	}
	return out
}
