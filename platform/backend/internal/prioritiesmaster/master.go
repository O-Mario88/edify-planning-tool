package prioritiesmaster

import (
	"context"
	"fmt"
	"math/big"
	"strings"
	"time"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/allocations"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

type priority struct {
	id, title string
	rows      []*milestone
}

type milestone struct {
	id, title, sourceText, targetSourceText, unit, method, measurement string
	target, recurrence                                                 *string
	due                                                                *time.Time
	needsConfirmation                                                  bool
	activities                                                         []string
	components                                                         []string
	plan                                                               *allocations.Progress
	mine, team, share                                                  *holding
}

// holding is one of the reader's allocations of a milestone: its figure as
// stored, and whether it is still a draft.
type holding struct {
	value string
	draft bool
}

type master struct {
	groups []*priority
	total  int
}

// readMaster is the view's reading of the year's master for the reader, or
// nil when the year has none.
func readMaster(ctx context.Context, db schooldirectory.Querier, p auth.Principal, role door, fy string, today time.Time) (*master, error) {
	rows, err := db.Query(ctx, `
SELECT id, title FROM hr_strategic_priority
WHERE fy = $1 AND level = 'country' AND country_id = $2 AND cycle_id IS NOT NULL ORDER BY sequence`, fy, country)
	if err != nil {
		return nil, fmt.Errorf("prioritiesmaster: reading the master's priorities: %w", err)
	}
	m := &master{}
	byID := map[string]*priority{}
	ids := []string{}
	for rows.Next() {
		pr := &priority{}
		if err := rows.Scan(&pr.id, &pr.title); err != nil {
			rows.Close()
			return nil, fmt.Errorf("prioritiesmaster: reading a priority: %w", err)
		}
		m.groups = append(m.groups, pr)
		byID[pr.id] = pr
		ids = append(ids, pr.id)
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, fmt.Errorf("prioritiesmaster: reading the master's priorities: %w", err)
	}
	if len(m.groups) == 0 {
		return nil, nil
	}
	mrows, err := db.Query(ctx, `
SELECT m.id, m.priority_id, m.title, coalesce(m.source_text, ''), coalesce(m.target_source_text, ''), coalesce(m.target_unit, ''),
       coalesce(m.allocation_method, ''), coalesce(m.measurement_type, ''), m.target_value::text, m.recurrence_per_month::text,
       m.due_date, m.needs_confirmation
FROM hr_priority_milestone m JOIN hr_strategic_priority sp ON sp.id = m.priority_id
WHERE m.priority_id = ANY($1)
ORDER BY sp.level, sp.sequence, sp.title, m.source_order`, ids)
	if err != nil {
		return nil, fmt.Errorf("prioritiesmaster: reading the master's milestones: %w", err)
	}
	all := []*milestone{}
	mids := []string{}
	for mrows.Next() {
		ms := &milestone{}
		var pid string
		if err := mrows.Scan(&ms.id, &pid, &ms.title, &ms.sourceText, &ms.targetSourceText, &ms.unit, &ms.method, &ms.measurement,
			&ms.target, &ms.recurrence, &ms.due, &ms.needsConfirmation); err != nil {
			mrows.Close()
			return nil, fmt.Errorf("prioritiesmaster: reading a milestone: %w", err)
		}
		byID[pid].rows = append(byID[pid].rows, ms)
		all = append(all, ms)
		mids = append(mids, ms.id)
	}
	mrows.Close()
	if err := mrows.Err(); err != nil {
		return nil, fmt.Errorf("prioritiesmaster: reading the master's milestones: %w", err)
	}
	m.total = len(all)
	if m.total == 0 {
		return nil, fmt.Errorf("a master without milestones: %w", errPassOn)
	}
	byMilestone := map[string]*milestone{}
	targets := map[string]*big.Rat{}
	for _, ms := range all {
		byMilestone[ms.id] = ms
		if ms.target != nil {
			targets[ms.id], _ = new(big.Rat).SetString(*ms.target)
		}
	}
	if err := readActivities(ctx, db, mids, byMilestone); err != nil {
		return nil, err
	}
	if err := readComponents(ctx, db, mids, byMilestone); err != nil {
		return nil, err
	}
	if role.Scoped {
		if err := readHoldings(ctx, db, p.StaffProfileID, mids, byMilestone); err != nil {
			return nil, err
		}
	}
	plan, err := allocations.MasterPlanProgress(ctx, db, mids, fy, targets, today)
	if err != nil {
		return nil, err
	}
	for _, ms := range all {
		ms.plan = plan[ms.id]
	}
	return m, nil
}

// readActivities is each milestone's active rules' catalogue names, in the
// order the rules come (they carry none of their own; read as the view's
// select_related reads them).
func readActivities(ctx context.Context, db schooldirectory.Querier, ids []string, by map[string]*milestone) error {
	rows, err := db.Query(ctx, `
SELECT r.milestone_id, coalesce(c.display_name, '')
FROM hr_milestone_activity_rule r LEFT OUTER JOIN activity_catalogue_item c ON c.id = r.catalogue_item_id
WHERE r.active AND r.milestone_id = ANY($1)`, ids)
	if err != nil {
		return fmt.Errorf("prioritiesmaster: reading the activity rules: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var mid, name string
		if err := rows.Scan(&mid, &name); err != nil {
			return fmt.Errorf("prioritiesmaster: reading an activity rule: %w", err)
		}
		if name != "" {
			by[mid].activities = append(by[mid].activities, name)
		}
	}
	return rows.Err()
}

// readComponents is each milestone's target components, by their sequence,
// as "label — target".
func readComponents(ctx context.Context, db schooldirectory.Querier, ids []string, by map[string]*milestone) error {
	rows, err := db.Query(ctx, `
SELECT milestone_id, coalesce(label, ''), target_value::float8 FROM hr_milestone_target_component
WHERE milestone_id = ANY($1) ORDER BY sequence`, ids)
	if err != nil {
		return fmt.Errorf("prioritiesmaster: reading the target components: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var mid, label string
		var target *float64
		if err := rows.Scan(&mid, &label, &target); err != nil {
			return fmt.Errorf("prioritiesmaster: reading a target component: %w", err)
		}
		figure := ""
		if target != nil {
			figure = allocations.FloatFormatFloat(*target, 0)
		}
		by[mid].components = append(by[mid].components, label+" — "+figure)
	}
	return rows.Err()
}

// readHoldings is the reader's live (draft or approved) allocations: the
// team target a Programme Lead received, their own share, and the figure the
// target column shows (their own over their team's).
func readHoldings(ctx context.Context, db schooldirectory.Querier, staffID string, ids []string, by map[string]*milestone) error {
	if staffID == "" {
		return nil
	}
	rows, err := db.Query(ctx, `
SELECT milestone_id, coalesce(allocated_to_type, ''), coalesce(employee_id, ''), allocated_target::text, status
FROM hr_milestone_allocation
WHERE milestone_id = ANY($1) AND status IN ('draft', 'approved')
  AND (employee_id = $2 OR (team_id = $2 AND allocated_to_type = 'team'))`, ids, staffID)
	if err != nil {
		return fmt.Errorf("prioritiesmaster: reading the reader's allocations: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var mid, kind, employee, value, status string
		if err := rows.Scan(&mid, &kind, &employee, &value, &status); err != nil {
			return fmt.Errorf("prioritiesmaster: reading an allocation: %w", err)
		}
		ms := by[mid]
		h := &holding{value: value, draft: status == "draft"}
		switch {
		case kind == "team":
			ms.team = h
		case employee == staffID:
			ms.share = h
		}
		if ms.mine != nil && kind == "team" {
			continue
		}
		ms.mine = h
	}
	return rows.Err()
}

// targetDisplay is the country's figure as the view words it.
func (ms *milestone) targetDisplay() string {
	switch {
	case ms.recurrence != nil && isTruthy(*ms.recurrence):
		unit := ms.unit
		if unit == "" {
			unit = "times"
		}
		return number(*ms.recurrence, "") + " " + unit + " per month"
	case ms.measurement == "percentage" && ms.target != nil:
		return number(*ms.target, "") + "%"
	case ms.measurement == "date":
		if ms.due != nil {
			return fmt.Sprintf("by %d %s", ms.due.Day(), ms.due.Format("Jan 2006"))
		}
		if ms.targetSourceText != "" {
			return ms.targetSourceText
		}
		return "—"
	case ms.target != nil:
		return number(*ms.target, ms.unit)
	}
	tail := ""
	if i := strings.LastIndex(ms.targetSourceText, "—"); i >= 0 {
		tail = strings.TrimSpace(ms.targetSourceText[i+len("—"):])
	}
	if strings.ToUpper(tail) == "NA" || strings.HasSuffix(strings.TrimRight(ms.sourceText, " \t\n\r\f\v"), "NA") {
		return "NA"
	}
	if (ms.measurement == "manual_assessment" || ms.measurement == "qualitative") && tail != "" {
		return tail
	}
	return "—"
}

// isTruthy is a stored number's truth in Python: not zero.
func isTruthy(s string) bool {
	r, ok := new(big.Rat).SetString(s)
	return ok && r.Sign() != 0
}

// held is a holding's cell: its figure (with "%" for a rate) and "draft",
// or "—".
func (ms *milestone) held(h *holding) string {
	if h == nil {
		return "—"
	}
	out := number(h.value, ms.unit)
	if ms.measurement == "percentage" {
		out += "%"
	}
	if h.draft {
		out += " draft"
	}
	return out
}

// blocks are the table and its footnote.
func (m *master) blocks(role door) []*screensv1.PageBlock {
	heads := []string{"Priorities", "Milestones", "Activities"}
	switch {
	case role.Lead:
		heads = append(heads, "Team received", "My share")
	case role.Scoped:
		heads = append(heads, "My Target")
	default:
		heads = append(heads, "Uganda's Targets")
	}
	heads = append(heads, "Progress")
	cols := []*screensv1.PageColumn{}
	for _, h := range heads {
		cols = append(cols, &screensv1.PageColumn{Label: h})
	}
	t := &screensv1.PageTable{Columns: cols}
	for _, g := range m.groups {
		for i, ms := range g.rows {
			cells := []*screensv1.PageCell{}
			if i == 0 {
				// The priority spans its group's rows: the feed reads it on
				// the first alone.
				word := "milestones"
				if len(g.rows) == 1 {
					word = "milestone"
				}
				cells = append(cells, &screensv1.PageCell{Text: fmt.Sprintf("%s %d %s", g.title, len(g.rows), word)})
			}
			name := ms.sourceText
			if name == "" {
				name = ms.title
			}
			if ms.needsConfirmation {
				name += " Confirm source"
			}
			if ms.method == "non_scoreable" {
				name += " Not scored"
			}
			if len(ms.components) > 0 {
				name += " Components: " + strings.Join(ms.components, " · ")
			}
			activities := "—"
			if len(ms.activities) > 0 {
				activities = strings.Join(ms.activities, ", ")
			}
			cells = append(cells, &screensv1.PageCell{Text: name}, &screensv1.PageCell{Text: activities})
			switch {
			case role.Lead:
				cells = append(cells, &screensv1.PageCell{Text: ms.held(ms.team)}, &screensv1.PageCell{Text: ms.held(ms.share)})
			case role.Scoped:
				cells = append(cells, &screensv1.PageCell{Text: ms.held(ms.mine)})
			default:
				cells = append(cells, &screensv1.PageCell{Text: ms.targetDisplay()})
			}
			cells = append(cells, &screensv1.PageCell{Text: allocations.MeterValue(ms.plan)})
			t.Rows = append(t.Rows, &screensv1.PageRow{Cells: cells})
		}
	}
	note := fmt.Sprintf("%d milestones across %d priority groups · source text shown exactly as approved", m.total, len(m.groups))
	switch {
	case role.Lead:
		note += " · team and share figures come from your allocations; distribute the team target on the My Team tab"
	case role.Scoped:
		note += " · your figures come from your approved allocations"
	}
	return []*screensv1.PageBlock{
		{Kind: &screensv1.PageBlock_Table{Table: t}},
		{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{Items: []*screensv1.PagePanelItem{
			{Kind: &screensv1.PagePanelItem_Text{Text: note + "."}}}}}},
	}
}
