package myplan

import (
	"context"
	"fmt"
	"strings"
	"time"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schoolprofile"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/visitgate"
)

// Home's "What needs you now" (apps.my_plan.past_due_service and
// partials/dashboards/what_needs_you_now.html) for an officer: their own
// past-due plans in three tables, as the feed reads them.

// PastDue is an officer's past-due work, each table in order.
type PastDue struct {
	Visits, Trainings, Meetings []*pastDueRow
	// Paged is a table longer than one page: the existing page draws its
	// pager, which Go does not, so the caller passes the page on.
	Paged bool
	// Lead is a Programme Lead's: their own and their team's, Scope ("",
	// "all", "own" or "team") naming whose plans the tables hold.
	Lead                   bool
	Scope                  string
	count, owned, teamWork int
}

// Total is past_due_total_count: every past-due plan, whoever's.
func (p PastDue) Total() int { return p.count }

type pastDueRow struct {
	a                                    *activity
	typeLabel, owner, planned            string
	schoolID, schoolName                 string
	clusterID, clusterName, clusterDistr string
	placeURL, purpose, focus, expected   string
	cost, salesforce, status, gap        string
	plannedDay                           *time.Time
	// isOwn is the reader's own work; ownerFirst addresses its officer.
	isOwn        bool
	ownerFirst   string
	reminderSent bool
}

// pastWhere is the past-due rule over activity a: planned before today, or
// undated and scheduled for a local day before it.
const pastWhere = `(a.planned_date < $2 OR (a.planned_date IS NULL AND ` + localDay + ` < $2))`

// staffPlanWhere is staff_my_plan_q over owners $1.
const staffPlanWhere = `a.responsible_staff_id = ANY($1) AND a.delivery_type IS DISTINCT FROM 'partner'
AND NOT COALESCE(a.status = ANY($3), false)`

// ReadPastDue is get_past_due_dashboard_context for an officer: their own
// live past-due work, then their past work a status calls done that still
// misses its Salesforce ID or form (_incomplete_past_work), each in order.
func ReadPastDue(ctx context.Context, db schooldirectory.Querier, owners []string, now time.Time) (PastDue, error) {
	if len(owners) == 0 {
		return PastDue{}, nil
	}
	today := now.In(kampala).Format(time.DateOnly)
	order := ` ORDER BY a.planned_date ASC, a.scheduled_date ASC, a.id ASC`
	live, err := idsWhere(ctx, db, `SELECT a.id FROM activity a WHERE a.deleted_at IS NULL
AND NOT COALESCE(a.status = ANY($4), false) AND `+pastWhere+` AND `+staffPlanWhere+order,
		owners, today, rules.Plan.PartnerOnlyStatuses, rules.PastDue.TerminalStatuses)
	if err != nil {
		return PastDue{}, err
	}
	done, err := idsWhere(ctx, db, `SELECT a.id FROM activity a WHERE a.deleted_at IS NULL
AND a.status = ANY($4) AND `+pastWhere+` AND `+staffPlanWhere+order,
		owners, today, rules.Plan.PartnerOnlyStatuses, rules.Plan.OfficerCompletedStatuses)
	if err != nil {
		return PastDue{}, err
	}
	ids := append(live, done...)
	if len(ids) == 0 {
		return PastDue{}, nil
	}
	acts, err := readActivities(ctx, db, ids)
	if err != nil {
		return PastDue{}, err
	}
	kinds, err := evidenceKinds(ctx, db, acts)
	if err != nil {
		return PastDue{}, err
	}
	marks := completions(acts, now.In(kampala), kinds)
	byID := map[string]*activity{}
	for _, a := range acts {
		byID[a.id] = a
	}
	// _incomplete_past_work: only the done work that is not complete.
	var listed []*activity
	for _, id := range ids {
		a := byID[id]
		if a == nil {
			continue
		}
		if in(rules.Plan.OfficerCompletedStatuses, a.status) && officerComplete(marks[a.id]) {
			continue
		}
		listed = append(listed, a)
	}
	var out PastDue
	var visits, trainings, meetings []*activity
	for _, a := range listed {
		switch {
		case in(rules.PastDue.TrainingTypes, a.activityType):
			trainings = append(trainings, a)
		case in(rules.PastDue.MeetingTypes, a.activityType):
			meetings = append(meetings, a)
		default:
			// VISIT_TYPES, and every type no table names.
			visits = append(visits, a)
		}
	}
	size := rules.PastDue.PageSize
	if len(visits) > size || len(trainings) > size || len(meetings) > size {
		return PastDue{Paged: true}, nil
	}
	rows, err := pastDueRows(ctx, db, listed, marks, owners)
	if err != nil {
		return PastDue{}, err
	}
	pick := func(as []*activity) []*pastDueRow {
		res := make([]*pastDueRow, 0, len(as))
		for _, a := range as {
			res = append(res, rows[a.id])
		}
		return res
	}
	out.Visits, out.Trainings, out.Meetings = pick(visits), pick(trainings), pick(meetings)
	out.count = len(listed)
	return out, nil
}

// PastDueScopes are the whose-plans a Lead's tables open on (PAST_DUE_SCOPES).
var PastDueScopes = []string{"all", "own", "team"}

// ReadTeamPastDue is get_past_due_dashboard_context for a Programme Lead:
// their own and their team's live past-due work, the tables narrowed to
// scope ("own", "team"; "all" or "" for both).
func ReadTeamPastDue(ctx context.Context, db schooldirectory.Querier, own, team []string, now time.Time, scope string) (PastDue, error) {
	if !in(PastDueScopes, scope) {
		scope = ""
	}
	out := PastDue{Lead: true, Scope: scope}
	ids := append([]string{}, own...)
	for _, id := range team {
		if !in(ids, id) {
			ids = append(ids, id)
		}
	}
	if len(ids) == 0 {
		return out, nil
	}
	today := now.In(kampala).Format(time.DateOnly)
	found, err := idsWhere(ctx, db, `SELECT a.id FROM activity a WHERE a.deleted_at IS NULL
AND NOT COALESCE(a.status = ANY($4), false) AND `+pastWhere+` AND `+staffPlanWhere+`
ORDER BY a.planned_date ASC, a.scheduled_date ASC, a.id ASC`,
		ids, today, rules.Plan.PartnerOnlyStatuses, rules.PastDue.TerminalStatuses)
	if err != nil || len(found) == 0 {
		return out, err
	}
	acts, err := readActivities(ctx, db, found)
	if err != nil {
		return PastDue{}, err
	}
	extras, err := readPastDueExtras(ctx, db, found)
	if err != nil {
		return PastDue{}, err
	}
	byID := map[string]*activity{}
	for _, a := range acts {
		byID[a.id] = a
	}
	var listed []*activity
	var tables [3][]*activity
	for _, id := range found {
		a := byID[id]
		if a == nil {
			continue
		}
		mineToo := in(own, str(a.staffID)) || (!isSet(a.staffID) && in(own, str(extras[id].monitored)))
		out.count++
		if mineToo {
			out.owned++
		} else {
			out.teamWork++
		}
		if (scope == "own" && !mineToo) || (scope == "team" && mineToo) {
			continue
		}
		listed = append(listed, a)
		tables[tableIndex(a.activityType)] = append(tables[tableIndex(a.activityType)], a)
	}
	for _, t := range tables {
		if len(t) > rules.PastDue.PageSize {
			return PastDue{Paged: true}, nil
		}
	}
	kinds, err := evidenceKinds(ctx, db, listed)
	if err != nil {
		return PastDue{}, err
	}
	marks := completions(listed, now.In(kampala), kinds)
	rows, err := pastDueRows(ctx, db, listed, marks, own)
	if err != nil {
		return PastDue{}, err
	}
	reminded, err := idsWhere(ctx, db, `SELECT DISTINCT context_id FROM notification WHERE context_type = 'activity'
AND context_id = ANY($1) AND source_event_type = 'pl_activity_overdue_reminder' AND resolved_at IS NULL`, found)
	if err != nil {
		return PastDue{}, err
	}
	pick := func(as []*activity) []*pastDueRow {
		res := make([]*pastDueRow, 0, len(as))
		for _, a := range as {
			r := rows[a.id]
			r.reminderSent = in(reminded, a.id)
			res = append(res, r)
		}
		return res
	}
	out.Visits, out.Trainings, out.Meetings = pick(tables[0]), pick(tables[1]), pick(tables[2])
	return out, nil
}

// officerComplete is completion_columns.is_complete for a status that says
// done: the Salesforce ID and the form both in.
func officerComplete(c completion) bool { return c.salesforce != "" && c.evidenceOK }

// pastDueExtra is what _build_rows reads beyond My Plan's own loader.
type pastDueExtra struct {
	monitored, project, clusterDistrict *string
}

func readPastDueExtras(ctx context.Context, db schooldirectory.Querier, ids []string) (map[string]pastDueExtra, error) {
	rows, err := db.Query(ctx, `SELECT a.id, a.monitored_by_staff_id, a.project_id, cd.name
FROM activity a LEFT JOIN cluster c ON c.id = a.cluster_id LEFT JOIN district cd ON cd.id = c.district_id
WHERE a.id = ANY($1)`, ids)
	if err != nil {
		return nil, fmt.Errorf("myplan: past due: %w", err)
	}
	defer rows.Close()
	out := map[string]pastDueExtra{}
	for rows.Next() {
		var id string
		var e pastDueExtra
		if err := rows.Scan(&id, &e.monitored, &e.project, &e.clusterDistrict); err != nil {
			return nil, fmt.Errorf("myplan: past due: %w", err)
		}
		out[id] = e
	}
	return out, rows.Err()
}

// pastDueNames is _build_rows' users_map: each person on the rows by both
// ids, from their profile's account, else from a bare account.
func pastDueNames(ctx context.Context, db schooldirectory.Querier, people []string) (map[string]string, error) {
	out := map[string]string{}
	if len(people) == 0 {
		return out, nil
	}
	rows, err := db.Query(ctx, `SELECT sp.id, sp.user_id, COALESCE(u.name, '') FROM staff_profile sp
LEFT JOIN "user" u ON u.id = sp.user_id WHERE sp.id = ANY($1) OR sp.user_id = ANY($1)`, people)
	if err != nil {
		return nil, fmt.Errorf("myplan: past due names: %w", err)
	}
	for rows.Next() {
		var id string
		var user *string
		var name string
		if err := rows.Scan(&id, &user, &name); err != nil {
			rows.Close()
			return nil, fmt.Errorf("myplan: past due names: %w", err)
		}
		if name != "" && isSet(user) {
			out[id] = name
			out[*user] = name
		}
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, fmt.Errorf("myplan: past due names: %w", err)
	}
	var unresolved []string
	for _, p := range people {
		if _, ok := out[p]; !ok {
			unresolved = append(unresolved, p)
		}
	}
	if len(unresolved) == 0 {
		return out, nil
	}
	urows, err := db.Query(ctx, `SELECT id, COALESCE(name, '') FROM "user" WHERE id = ANY($1)`, unresolved)
	if err != nil {
		return nil, fmt.Errorf("myplan: past due names: %w", err)
	}
	defer urows.Close()
	for urows.Next() {
		var id, name string
		if err := urows.Scan(&id, &name); err != nil {
			return nil, fmt.Errorf("myplan: past due names: %w", err)
		}
		out[id] = name
	}
	return out, urows.Err()
}

// pastDueRows is _build_rows for an officer's own rows.
func pastDueRows(ctx context.Context, db schooldirectory.Querier, acts []*activity, marks map[string]completion, owners []string) (map[string]*pastDueRow, error) {
	ids := make([]string, 0, len(acts))
	for _, a := range acts {
		ids = append(ids, a.id)
	}
	extras, err := readPastDueExtras(ctx, db, ids)
	if err != nil {
		return nil, err
	}
	seen := map[string]bool{}
	var people []string
	for _, a := range acts {
		for _, p := range []*string{a.staffID, extras[a.id].monitored} {
			if isSet(p) && !seen[*p] {
				seen[*p] = true
				people = append(people, *p)
			}
		}
	}
	names, err := pastDueNames(ctx, db, people)
	if err != nil {
		return nil, err
	}
	amounts, err := minimumAmounts(ctx, db, ids)
	if err != nil {
		return nil, err
	}
	outside, err := visitgate.ProjectsOutsideSSA(ctx, db, schoolprofile.GateRules())
	if err != nil {
		return nil, err
	}
	out := map[string]*pastDueRow{}
	for _, a := range acts {
		e := extras[a.id]
		r := &pastDueRow{a: a, typeLabel: typeLabel(a.activityType)}
		r.owner = names[str(a.staffID)]
		if r.owner == "" {
			if name, ok := names[str(e.monitored)]; ok && isSet(e.monitored) {
				r.owner = name
			} else {
				r.owner = "Staff"
			}
		}
		r.isOwn = in(owners, str(a.staffID)) || (!isSet(a.staffID) && in(owners, str(e.monitored)))
		r.ownerFirst = "Team Member"
		if f := strings.Fields(r.owner); len(f) > 0 {
			r.ownerFirst = f[0]
		}
		r.plannedDay = date(a.plannedDate)
		if r.plannedDay == nil {
			r.plannedDay = day(a.scheduledDate)
		}
		r.planned = "Unscheduled"
		if r.plannedDay != nil {
			r.planned = shownDay(r.plannedDay)
		}
		r.fillPlace(e)
		r.purpose = str(a.purposeText)
		if r.purpose == "" {
			r.purpose = r.typeLabel
		}
		switch {
		case isSet(a.focus):
			r.focus = *a.focus
			if l, ok := rules.Rows.FocusInterventionLabels[*a.focus]; ok {
				r.focus = l
			}
		case isSet(e.project) && in(outside, *e.project):
			r.focus = "General"
		default:
			r.focus = dash
		}
		r.expected = dash
		if a.expected != nil && *a.expected != 0 {
			r.expected = fmt.Sprint(*a.expected)
		}
		cost := int64(0)
		if v := amounts[a.id]; v != nil {
			cost = *v
		}
		r.cost = money(cost)
		c := marks[a.id]
		r.salesforce = c.salesforce
		r.gap = completionGap(in(rules.Plan.OfficerCompletedStatuses, a.status), c)
		switch {
		case r.gap != "":
			r.status = r.gap
		case in(rules.PastDue.ReturnedStatuses, a.status):
			r.status = "Returned"
		case a.status == "in_progress":
			r.status = "In Progress"
		default:
			r.status = "Past Due"
		}
		out[a.id] = r
	}
	return out, nil
}

// fillPlace is the row's school, cluster, district and place link.
func (r *pastDueRow) fillPlace(e pastDueExtra) {
	a := r.a
	district := str(e.clusterDistrict)
	if !(a.hasCluster && district != "") && a.hasSchool {
		district = str(a.schoolDistrictName)
	}
	r.clusterDistr = orDefault(district, dash)
	switch {
	case a.hasSchool:
		r.schoolID, r.schoolName = str(a.schoolCode), str(a.schoolName)
	case a.hasCluster:
		r.schoolName = str(a.clusterName)
	default:
		r.schoolName = dash
	}
	switch {
	case a.hasCluster:
		r.clusterID, r.clusterName = str(a.clusterID), str(a.clusterName)
		r.placeURL = "/clusters/" + r.clusterID
	case a.hasSchool:
		r.clusterName = str(a.schoolName)
		r.placeURL = "/schools/" + str(a.schoolPK)
	default:
		r.clusterName = dash
	}
}

// PastDueBlocks are the section's blocks as the feed reads them: its head,
// the kind chips, then each table under its own heading.
func PastDueBlocks(p PastDue) []*screensv1.PageBlock {
	total := p.Total()
	head := &screensv1.PagePanel{Title: "What needs you now",
		Badges: []*screensv1.PageBadge{{Text: fmt.Sprintf("%d past due", total), Tone: "alert"}},
		Items:  []*screensv1.PagePanelItem{panelText("Past due plans requiring completion, rescheduling or cancellation")}}
	blocks := []*screensv1.PageBlock{{Kind: &screensv1.PageBlock_Panel{Panel: head}}}
	if p.Lead && total == 0 {
		// The backlog's fold, empty, is read into the section's panel.
		head.Items = append([]*screensv1.PagePanelItem{{Kind: &screensv1.PagePanelItem_Heading{
			Heading: "All overdue plans, any age 0"}}}, head.Items...)
	}
	if total == 0 {
		// The empty state is read into the section's own panel.
		head.Items = append(head.Items,
			&screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Heading{Heading: "No past due plans"}},
			panelText("All scheduled school visits, trainings, and cluster meetings are currently on track."))
		return blocks
	}
	if p.Lead {
		blocks = append(p.leadHead(), blocks...)
	}
	chips := &screensv1.PageChips{Name: "activeCategory", Label: "Which kind of plan", Value: "all", Chips: []*screensv1.PageChip{
		{Value: "all", Label: "All Categories"},
		{Value: "visits", Label: fmt.Sprintf("School Visits (%d)", len(p.Visits))},
		{Value: "trainings", Label: fmt.Sprintf("Trainings (%d)", len(p.Trainings))},
		{Value: "meetings", Label: fmt.Sprintf("Cluster Meetings (%d)", len(p.Meetings))},
	}}
	if p.Lead {
		blocks = append(blocks, p.scopeBlock())
	}
	blocks = append(blocks, &screensv1.PageBlock{Kind: &screensv1.PageBlock_Chips{Chips: chips}})
	blocks = append(blocks, pastDueTable("School Visits (Past Due)", "No past due school visits.", p.Visits,
		columns("School ID", "School Name", "Activity", "Planned Date", "Executor", "Purpose of Visit",
			"Focus Intervention", "Cost", "Salesforce ID", "Status", "Actions"), pastVisitCells)...)
	blocks = append(blocks, pastDueTable("Trainings (Past Due)", "No past due trainings.", p.Trainings,
		columns("School ID", "School / Cluster", "Cluster Planned From", "Executor", "Training Name", "Planned Date",
			"SSA Intervention", "Participants", "Cost", "Salesforce ID", "Status", "Actions"), pastTrainingCells)...)
	blocks = append(blocks, pastDueTable("Cluster Meetings (Past Due)", "No past due cluster meetings.", p.Meetings,
		columns("Cluster Name", "District", "Planned Date", "Executor", "Purpose (Meeting Topic)", "SSA Intervention",
			"Participants", "Cost", "Salesforce ID", "Status", "Actions"), pastMeetingCells)...)
	return blocks
}

// leadHead is the backlog's fold ("All overdue plans, any age" and its
// count, read as a figure) before the section, and whose plans after its
// head: chips, or links once a link has named whose plans the tables hold.
func (p PastDue) leadHead() []*screensv1.PageBlock {
	fold := &screensv1.PagePanel{Items: []*screensv1.PagePanelItem{{Kind: &screensv1.PagePanelItem_Rows{Rows: &screensv1.PageDataRows{
		Rows: []*screensv1.PageDataRow{{Label: "All overdue plans, any age", Value: fmt.Sprint(p.count)}}}}}}}
	return []*screensv1.PageBlock{{Kind: &screensv1.PageBlock_Panel{Panel: fold}}}
}

// scopeBlock is a Lead's whose-plans rail: All, My Plans, Team Plans.
func (p PastDue) scopeBlock() *screensv1.PageBlock {
	tabs := [3][2]string{{"all", fmt.Sprintf("All (%d)", p.count)}, {"own", fmt.Sprintf("My Plans (%d)", p.owned)},
		{"team", fmt.Sprintf("Team Plans (%d)", p.teamWork)}}
	if p.Scope != "" {
		var links []*screensv1.PageLink
		for _, t := range tabs {
			links = append(links, &screensv1.PageLink{Text: t[1], Href: "?view=week&plans=" + t[0] + "#what-needs-you-now"})
		}
		return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{
			Items: []*screensv1.PagePanelItem{{Kind: &screensv1.PagePanelItem_Links{Links: &screensv1.PageLinks{Links: links}}}}}}}
	}
	chips := &screensv1.PageChips{Name: "activeScope", Label: "Whose plans", Value: "all"}
	for _, t := range tabs {
		chips.Chips = append(chips.Chips, &screensv1.PageChip{Value: t[0], Label: t[1]})
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Chips{Chips: chips}}
}

func panelText(t string) *screensv1.PagePanelItem {
	return &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Text{Text: t}}
}

// pastDueTable is one table's heading panel and the table, its rows the
// reader's own (each tinted overdue, each with its tick box).
func pastDueTable(title, empty string, rows []*pastDueRow, cols []*screensv1.PageColumn,
	cells func(*pastDueRow) ([]*screensv1.PageCell, string)) []*screensv1.PageBlock {
	head := &screensv1.PagePanel{Title: title,
		Badges: []*screensv1.PageBadge{{Text: fmt.Sprint(len(rows)), Tone: "alert"}},
		Items:  []*screensv1.PagePanelItem{panelText("Ordered by date")}}
	table := &screensv1.PageTable{Columns: cols}
	for _, r := range rows {
		cs, name := cells(r)
		cs = append(cs, r.tail()...)
		label := "Select " + orDefault(r.typeLabel, "activity")
		if name != "" {
			label += " at " + name
		}
		if r.plannedDay != nil {
			label += " on " + shownDay(r.plannedDay)
		}
		row := &screensv1.PageRow{Cells: cs, Tone: "overdue"}
		if r.isOwn {
			row.PickId, row.PickLabel = r.a.id, label
		}
		table.Rows = append(table.Rows, row)
	}
	if len(rows) == 0 {
		table.Rows = []*screensv1.PageRow{{Cells: []*screensv1.PageCell{{Text: empty}}}}
	}
	return []*screensv1.PageBlock{
		{Kind: &screensv1.PageBlock_Panel{Panel: head}},
		{Kind: &screensv1.PageBlock_Table{Table: table}},
	}
}

func (r *pastDueRow) executor() *screensv1.PageCell {
	if r.isOwn {
		return &screensv1.PageCell{Text: r.owner + " You"}
	}
	return &screensv1.PageCell{Text: r.owner}
}

func (r *pastDueRow) focusCell() *screensv1.PageCell {
	if r.focus != "" && r.focus != dash {
		return badge(r.focus, "primary")
	}
	return &screensv1.PageCell{Text: dash}
}

// tail is every table's last four: Cost, Salesforce ID, Status, Actions.
func (r *pastDueRow) tail() []*screensv1.PageCell {
	sf := &screensv1.PageCell{Text: "Not in SF"}
	if r.salesforce != "" {
		sf = &screensv1.PageCell{Text: r.salesforce}
	}
	id := r.a.id
	complete := "/my-plan/" + id + "/complete-drawer"
	if r.gap != "" {
		complete = "/activities/" + id + "/salesforce-id"
	}
	if !r.isOwn {
		// A team member's: the reminder to them, sent or to send, which the
		// feed reads as the button's words.
		words := "Send to " + r.ownerFirst
		if r.reminderSent {
			words = "Sent to " + r.ownerFirst
		}
		return []*screensv1.PageCell{{Text: r.cost}, sf, badge(r.status, "primary"), {Text: words}}
	}
	menu := func(key, label, href string, drawer bool) *screensv1.PageAction {
		return &screensv1.PageAction{Key: key, Label: label, Enabled: true, Href: href, Drawer: drawer}
	}
	return []*screensv1.PageCell{
		{Text: r.cost}, sf, badge(r.status, "primary"),
		{Actions: []*screensv1.PageAction{
			menu("menu", "Complete Activity", complete, true),
			menu("menu", "Reschedule Activity", "/my-plan/"+id+"/reschedule-drawer", true),
			menu("danger", "Cancel Activity", "/my-plan/"+id+"/cancel-drawer", true),
			menu("menu", "View Details", "/my-plan/"+id, true),
			menu("menu", "Discuss this activity", "/debriefs/submit?activity="+id, false),
		}},
	}
}

func pastVisitCells(r *pastDueRow) ([]*screensv1.PageCell, string) {
	name := &screensv1.PageCell{Text: orDefault(r.schoolName, dash)}
	if r.schoolID != "" {
		name.Href = "/schools/" + r.schoolID
	}
	return []*screensv1.PageCell{
		{Text: orDefault(r.schoolID, dash)}, name, {Text: r.typeLabel}, {Text: r.planned},
		r.executor(), {Text: orDefault(r.purpose, dash)}, r.focusCell(),
	}, r.schoolName
}

// placeName is {% firstof row.school_name row.cluster_name %}.
func (r *pastDueRow) placeName() string { return orDefault(r.schoolName, r.clusterName) }

// clusterLink is {% cluster_link name id empty=… %}.
func clusterLink(name, id, empty string) *screensv1.PageCell {
	if name == "" {
		return &screensv1.PageCell{Text: empty}
	}
	c := &screensv1.PageCell{Text: name}
	if strings.TrimSpace(id) != "" {
		c.Href = "/clusters/" + strings.TrimSpace(id)
	}
	return c
}

func pastTrainingCells(r *pastDueRow) ([]*screensv1.PageCell, string) {
	place := &screensv1.PageCell{Text: r.placeName(), Href: r.placeURL}
	return []*screensv1.PageCell{
		{Text: orDefault(r.schoolID, dash)}, place, clusterLink(r.clusterName, r.clusterID, dash),
		r.executor(), {Text: r.typeLabel}, {Text: r.planned}, r.focusCell(), {Text: r.expected},
	}, r.clusterName
}

func pastMeetingCells(r *pastDueRow) ([]*screensv1.PageCell, string) {
	name := clusterLink(r.clusterName, r.clusterID, "")
	return []*screensv1.PageCell{
		name, {Text: r.clusterDistr}, {Text: r.planned}, r.executor(),
		{Text: orDefault(r.purpose, "Cluster Meeting")}, r.focusCell(), {Text: r.expected},
	}, r.clusterName
}

// OwnerIDs is scoping.owner_ids: both ids a person's work is filed under.
func OwnerIDs(p auth.Principal) []string { return ownerIDs(p) }

// TypeLabel is an activity type's choice label, the value itself when it is
// not a choice.
func TypeLabel(value string) string { return typeLabel(value) }
