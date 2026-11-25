package teamtargets

import (
	"context"
	"fmt"
	"slices"
	"strconv"
	"strings"
	"time"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/feeddom"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/targets"
)

// MatrixDrawer is team_targets_matrix_view over PLTeamTargetsService.matrix:
// each member's agreed priorities (one, when an area is asked) by month,
// quarter and year. A team with approved milestone allocations, which the
// unfiltered matrix lists too, is handed on.
func MatrixDrawer(ctx context.Context, db schooldirectory.Querier, p auth.Principal, q map[string]string, now time.Time) (*screensv1.PageDrawer, error) {
	if !slices.Contains(rules.PageRoles, p.ActiveRole) {
		return nil, &RefusedError{Refusal}
	}
	month := 0
	if raw := strings.TrimSpace(q["month"]); raw != "" {
		n, err := strconv.Atoi(raw)
		if err != nil || n < 1 || n > 12 {
			return nil, &RefusedError{"Invalid month."}
		}
		month = n
	}
	l := now.In(kampala)
	today := time.Date(l.Year(), l.Month(), l.Day(), 0, 0, 0, 0, time.UTC)
	per := periodOf(query{fy: strings.TrimSpace(q["fy"]), month: month}, today, fyOf(nil, now))
	scope, err := schooldirectory.ResolveScope(ctx, db, p, now)
	if err != nil {
		return nil, err
	}
	team, err := supervisedUsers(ctx, db, p, scope)
	if err != nil {
		return nil, err
	}
	people := make([]targets.Person, len(team))
	for i, m := range team {
		people[i] = targets.Person{UserID: m.UserID, StaffID: m.StaffID}
	}
	roster, err := targets.Prepare(ctx, db, people, per.fy, nil)
	if err != nil {
		return nil, err
	}
	area := strings.TrimSpace(q["area"])
	label := ""
	if area != "" {
		for _, a := range roster.AgreedAreas(people) {
			if a.Key == area {
				label = a.Label
			}
		}
		if label == "" {
			return nil, &RefusedError{"Invalid target area."}
		}
	} else {
		d := &data{t: team2(team)}
		d.fy = per.fy
		if has, err := d.assignedMilestones(ctx, db); err != nil || has {
			return nil, handOnOr(err)
		}
	}
	quarter := targets.QuarterOfMonth(per.month)
	heads := matrixHeads(per.fy, per.month)
	body := el("tbody", "divide-y divide-slate-50 font-semibold text-slate-700")
	drawn := 0
	for i, pr := range people {
		areas := roster.Areas(pr)
		if area != "" {
			areas = slices.DeleteFunc(slices.Clone(areas), func(a targets.Area) bool { return a.Key != area })
		}
		// _targets_from and _achievements_from over the person's own areas.
		tgs, ach := roster.Targets(pr), roster.Achieved(pr)
		for _, a := range areas {
			tr := el("tr", "hover:bg-slate-50/50", el("td", "py-1.5 px-3 edify-frozen-cell whitespace-nowrap", team[i].Name+" ",
				el("span", "text-slate-500 font-medium", "· "+a.Label)))
			for _, h := range heads {
				t, got := 0, 0
				for _, m := range h.months {
					t += tgs[a.Key][m-1]
					got += ach[a.Key][m-1]
				}
				pct := "—"
				if t != 0 {
					pct = strconv.Itoa(pyRound(float64(got)/float64(t)*100)) + "%"
				}
				tr.Add(el("td", "py-1.5 text-center tabular-nums", strconv.Itoa(t)), el("td", "py-1.5 text-center tabular-nums", strconv.Itoa(got)),
					el("td", "py-1.5 text-center tabular-nums", pct))
			}
			body.Add(tr)
			drawn++
		}
	}
	if drawn == 0 {
		body.Add(el("tr", "", el("td", "px-4 py-8 text-center text-slate-500", "No agreed measurable priorities in this team scope.").Attr("colspan", "19")))
	}
	top := el("tr", "", el("th", "py-2 px-3 text-left edify-frozen-cell", "Staff · performance priority"))
	measures := el("tr", "", el("th", "py-1 px-3 edify-frozen-cell"))
	for _, h := range heads {
		sub := h.sub
		if h.key == quarter {
			sub += " · Current quarter"
		}
		top.Add(el("th", "py-2 px-2 text-center", " ", el("span", "block", h.label), " ", el("span", "block", sub), " ").Attr("colspan", "3"))
		measures.Add(el("th", "py-1 text-center", "Tgt"), el("th", "py-1 text-center", "Ach"), el("th", "py-1 text-center", "%"))
	}
	table := el("table", "w-full min-w-[900px] edify-text-caption", el("thead", "", top, measures), body)
	items := []*screensv1.DrawerItem{}
	for _, b := range feeddom.Walk(el("div", "", el("div", "overflow-x-auto", table)), nil) {
		items = append(items, &screensv1.DrawerItem{Kind: &screensv1.DrawerItem_Block{Block: b}})
	}
	items = append(items, text("Quarter and FY values are sums of monthly targets and validated achievements, never entered directly."))
	title := "Team target matrix"
	if label != "" {
		title = "Team progress for " + label
	}
	return &screensv1.PageDrawer{Title: title, HasRequired: true, CancelLabel: "Cancel", Items: items}, nil
}

// matrixHead is one of matrix()'s heads, with its months.
type matrixHead struct {
	key, label, sub string
	months          []int
}

func matrixHeads(fy string, month int) []matrixHead {
	first, _, _ := strings.Cut(targets.MonthLabel(fy, month), " ")
	out := []matrixHead{{"month", first, "Monthly", []int{month}}}
	for _, q := range []string{"Q1", "Q2", "Q3", "Q4"} {
		out = append(out, matrixHead{q, q, targets.QuarterLabel(fy, q), targets.MonthsOfQuarter(q)})
	}
	return append(out, matrixHead{"fy", targetsFYLabel(fy), "Full Year", []int{1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12}})
}

func team2(members []Member) team {
	t := team{}
	for _, m := range members {
		t.rows = append(t.rows, &row{member: m})
	}
	return t
}

// assignedMilestones is whether the team holds any approved milestone
// allocation this year (team_milestone_targets).
func (d *data) assignedMilestones(ctx context.Context, db schooldirectory.Querier) (bool, error) {
	ids := d.t.staffIDs()
	if len(ids) == 0 {
		return false, nil
	}
	var found bool
	err := db.QueryRow(ctx, `SELECT EXISTS (SELECT 1 FROM hr_milestone_allocation a JOIN hr_priority_milestone m ON m.id = a.milestone_id
		JOIN hr_strategic_priority sp ON sp.id = m.priority_id WHERE a.status = 'approved' AND a.employee_id = ANY($1) AND sp.fy = $2)`,
		ids, d.fy).Scan(&found)
	if err != nil {
		return false, fmt.Errorf("teamtargets: the team's milestones: %w", err)
	}
	return found, nil
}
