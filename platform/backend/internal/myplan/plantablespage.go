package myplan

import (
	"fmt"
	"strconv"
	"strings"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
)

// The tables as partials/my_plan/school_visits.html, cluster_meetings.html
// and core_school_visits.html draw them, read by the feed.

func columns(labels ...string) []*screensv1.PageColumn {
	out := make([]*screensv1.PageColumn, len(labels))
	for i, l := range labels {
		out[i] = &screensv1.PageColumn{Label: l, Numeric: l == "Cost" || l == "Actions"}
	}
	return out
}

func orDefault(s, fallback string) string {
	if s == "" {
		return fallback
	}
	return s
}

// badge is a cell drawn as one pill of tone.
func badge(text, tone string) *screensv1.PageCell {
	return &screensv1.PageCell{Text: text, Tone: tone, Badge: true}
}

// budgetColour is the loop's budget_status_color for its words.
func budgetColour(status string) string {
	switch status {
	case "Cost Setup Required", "Awaiting PL Approval", "Awaiting CD Approval":
		return "amber"
	case "Request Returned":
		return "red"
	case "Approved", "Disbursed":
		return "green"
	case "No Budget":
		return "slate"
	}
	return "blue"
}

// verificationColour is verification_label's colour for its words.
func verificationColour(words string) string {
	switch words {
	case "PL Approved", "Verified":
		return "green"
	case "Returned":
		return "red"
	}
	return "purple"
}

// focusCell is the intervention pill, "—" without one.
func focusCell(r *planRow) *screensv1.PageCell {
	if r.focus != "" && r.focus != dash {
		return badge(r.focus, "primary")
	}
	return &screensv1.PageCell{Text: dash}
}

// tailCells are every table's last five: Budget status, Verification,
// Salesforce ID, Status and Actions.
func tailCells(r *planRow) []*screensv1.PageCell {
	sf := &screensv1.PageCell{Text: "Not in SF"}
	if r.salesforceID != "" {
		sf = &screensv1.PageCell{Text: r.salesforceID}
	}
	return []*screensv1.PageCell{
		badge(orDefault(r.budgetStatus, dash), budgetColour(r.budgetStatus)),
		badge(orDefault(r.verification, dash), verificationColour(r.verification)),
		sf,
		badge(orDefault(r.statusLabel, dash), orDefault(r.tone, "slate")),
		r.actions(),
	}
}

// pageRow is a table row with its tint and tick box.
func pageRow(r *planRow, name string, cells []*screensv1.PageCell) *screensv1.PageRow {
	out := &screensv1.PageRow{Cells: cells, Tone: r.rowState}
	if out.Tone == "" && r.dayOff != nil {
		out.Tone = "dayoff"
	}
	if r.canPick {
		label := "Select " + orDefault(str(r.activityTypeLabel), "activity")
		if name != "" {
			label += " at " + name
		}
		if d := date(r.a.plannedDate); d != nil {
			label += " on " + shownDay(d)
		}
		out.PickId, out.PickLabel = r.a.id, label
	}
	return out
}

func schoolCells(r *planRow, district, activityDefault string) []*screensv1.PageCell {
	name := &screensv1.PageCell{Text: orDefault(r.schoolName, dash)}
	if r.schoolID.truthy() {
		name.Href = "/schools/" + r.schoolID.value
	}
	return []*screensv1.PageCell{
		{Text: orDefault(r.schoolID.value, dash)}, name,
		{Text: orDefault(district, dash)}, {Text: orDefault(r.districtType, dash)},
		{Text: orDefault(str(r.activityTypeLabel), activityDefault)},
		{Text: planned(r.row) + r.dayOffFlag()}, {Text: completed(r.row)},
		{Text: orDefault(r.owner, "Staff")}, {Text: orDefault(r.purpose, dash)},
		focusCell(r), {Text: cost(r.row, true)},
	}
}

// meetingPurpose is the Purpose (Meeting Topic) cell: the meeting's kind,
// and its purpose when that says more than the type, else the purpose.
func meetingPurpose(r *planRow) string {
	kind := str(r.x.meetingKind)
	if kind == "" {
		return orDefault(r.purpose, "Cluster Meeting")
	}
	label, ok := rules.Tables.MeetingKindLabels[kind]
	if !ok {
		label = kind
	}
	if r.purpose != "" && r.purpose != str(r.activityTypeLabel) {
		label += " · " + r.purpose
	}
	return label
}

func meetingCells(r *planRow) []*screensv1.PageCell {
	people := dash
	if r.expected != nil && *r.expected != 0 {
		people = strconv.Itoa(*r.expected)
	}
	amount := int64(0)
	if r.budgetTotal != nil {
		amount = *r.budgetTotal
	}
	return []*screensv1.PageCell{
		{Text: r.clusterName, Href: "/clusters/" + r.clusterID},
		{Text: r.clusterDistrict()}, {Text: orDefault(r.districtType, dash)},
		{Text: planned(r.row) + r.dayOffFlag()}, {Text: completed(r.row)},
		{Text: orDefault(r.owner, "Staff")}, {Text: meetingPurpose(r)},
		focusCell(r), {Text: people}, {Text: money(amount)},
	}
}

// people is the Participants cell: the head count, "—" for none.
func people(r *planRow) string {
	if r.expected != nil && *r.expected != 0 {
		return strconv.Itoa(*r.expected)
	}
	return dash
}

// shownName is the School / Cluster cell's words: the school's name unless
// it is "Unknown School", else the cluster's, else the School ID.
func shownName(r *planRow, cluster bool) string {
	switch {
	case r.schoolName != "" && r.schoolName != "Unknown School":
		return r.schoolName
	case cluster && r.clusterName != "":
		return r.clusterName
	}
	return r.schoolID.value
}

// trainingTableCells are cluster_trainings.html's cells up to the Cost.
func trainingTableCells(r *planRow) []*screensv1.PageCell {
	var name *screensv1.PageCell
	switch {
	case r.placeURL != "":
		name = &screensv1.PageCell{Text: shownName(r, true), Href: r.placeURL}
	case r.schoolID.truthy():
		name = &screensv1.PageCell{Text: shownName(r, false), Href: "/schools/" + r.schoolID.value}
	case r.schoolName != "" && r.schoolName != "Unknown School":
		name = &screensv1.PageCell{Text: r.schoolName}
	default:
		// {% cluster_link row.cluster_name row.cluster_id empty="—" %}: no
		// cluster here, so the name alone.
		name = &screensv1.PageCell{Text: orDefault(r.clusterName, dash)}
	}
	var from *screensv1.PageCell
	switch {
	case r.isClusterInvited && r.clusterID != "":
		from = &screensv1.PageCell{Text: orDefault(r.clusterName, dash) + " Invited", Href: "/clusters/" + r.clusterID}
	case r.isClusterInvited:
		from = &screensv1.PageCell{Text: orDefault(r.clusterName, dash) + " Invited"}
	// row.delivery_type == "in-school": the row carries no delivery_type,
	// so only the type decides.
	case strings.Contains(r.a.activityType, "in_school"):
		from = &screensv1.PageCell{Text: "School Visit"}
	case r.clusterID != "":
		from = &screensv1.PageCell{Text: orDefault(r.clusterName, dash), Href: "/clusters/" + r.clusterID}
	default:
		from = &screensv1.PageCell{Text: orDefault(r.clusterName, dash)}
	}
	return []*screensv1.PageCell{
		{Text: orDefault(r.schoolID.value, dash)}, name,
		{Text: orDefault(r.districtShown, dash)}, {Text: orDefault(r.districtType, dash)},
		from, {Text: orDefault(r.owner, "Staff")}, {Text: orDefault(r.trainingName, "Not yet named")},
		{Text: planned(r.row) + r.dayOffFlag()}, {Text: completed(r.row)},
		focusCell(r), {Text: people(r)}, {Text: orDefault(r.trainingMode, dash)}, {Text: cost(r.row, true)},
	}
}

// groupTableCells are group_trainings.html's cells up to the Cost.
func groupTableCells(r *planRow) []*screensv1.PageCell {
	name := &screensv1.PageCell{Text: r.clusterName}
	if r.clusterID != "" {
		name.Href = "/clusters/" + r.clusterID
	}
	training := r.trainingName
	for _, v := range []string{str(r.x.activityName), r.purpose, "Group Training"} {
		if training == "" {
			training = v
		}
	}
	return []*screensv1.PageCell{
		name, {Text: r.clusterDistrict()}, {Text: orDefault(r.districtType, dash)},
		{Text: planned(r.row) + r.dayOffFlag()}, {Text: completed(r.row)},
		{Text: orDefault(r.owner, "Staff")}, {Text: training},
		focusCell(r), {Text: people(r)}, {Text: cost(r.row, false)},
	}
}

// planTablesBlocks are the four always-drawn tables, then the Core tables
// when there is Core work, in the page's order.
func planTablesBlocks(t PlanTablesResult, p Period, clusters []clusterPlanRow) []*screensv1.PageBlock {
	words := p.Words()
	visitColumns := []string{"School ID", "School Name", "District", "District Type", "Activity", "Planned Date",
		"Completed Date", "Executor", "Purpose of Visit", "Focus Intervention", "Cost", "Budget status",
		"Verification", "Salesforce ID", "Status", "Actions"}
	full := func(title string, cols []string, rows []*screensv1.PageRow) *screensv1.PageBlock {
		return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Table{Table: &screensv1.PageTable{
			Title: title + " " + words, Columns: columns(cols...), Rows: rows, Count: strconv.Itoa(len(rows)),
		}}}
	}
	var blocks []*screensv1.PageBlock
	if len(t.visits) == 0 {
		blocks = append(blocks, emptyTable(PlanTables[0], p))
	} else {
		var rows []*screensv1.PageRow
		for _, r := range t.visits {
			rows = append(rows, pageRow(r, r.schoolName, append(schoolCells(r, r.districtShown, "School Visit"), tailCells(r)...)))
		}
		blocks = append(blocks, full(PlanTables[0].Title, visitColumns, rows))
	}
	if len(t.trainings) == 0 {
		blocks = append(blocks, emptyTable(PlanTables[1], p))
	} else {
		var rows []*screensv1.PageRow
		for _, r := range t.trainings {
			rows = append(rows, pageRow(r, r.clusterName, append(trainingTableCells(r), tailCells(r)...)))
		}
		blocks = append(blocks, full(PlanTables[1].Title, []string{"School ID", "School / Cluster", "District",
			"District Type", "Cluster Planned From", "Executor", "Training Name", "Planned Date", "Completed Date",
			"SSA Intervention", "Participants", "Mode of Delivery", "Cost", "Budget status", "Verification",
			"Salesforce ID", "Status", "Actions"}, rows))
	}
	if len(t.group) == 0 {
		blocks = append(blocks, emptyTable(PlanTables[2], p))
	} else {
		var rows []*screensv1.PageRow
		for _, r := range t.group {
			rows = append(rows, pageRow(r, r.clusterName, append(groupTableCells(r), tailCells(r)...)))
		}
		blocks = append(blocks, full(PlanTables[2].Title, []string{"Cluster Name", "District", "District Type",
			"Planned Date", "Completed Date", "Executor", "Training", "SSA Intervention", "Participants", "Cost",
			"Budget status", "Verification", "Salesforce ID", "Status", "Actions"}, rows))
	}
	if len(t.meetings) == 0 {
		blocks = append(blocks, emptyTable(PlanTables[3], p))
	} else {
		var rows []*screensv1.PageRow
		for _, r := range t.meetings {
			rows = append(rows, pageRow(r, r.clusterName, append(meetingCells(r), tailCells(r)...)))
		}
		blocks = append(blocks, full(PlanTables[3].Title, []string{"Cluster Name", "District", "District Type",
			"Planned Date", "Completed Date", "Executor", "Purpose (Meeting Topic)", "SSA Intervention",
			"Participants", "Cost", "Budget status", "Verification", "Salesforce ID", "Status", "Actions"}, rows))
	}
	if cb := clusterPlanningBlock(clusters); cb != nil {
		blocks = append(blocks, cb)
	}
	if len(t.core) > 0 || len(t.coreTrainings) > 0 {
		blocks = append(blocks, coreBlocks(t, words, visitColumns)...)
	}
	return append(blocks, programmeBlocks(t)...)
}

// programmeBlocks are programme_school_work.html's sections, one a
// programme school type with work, in PROGRAMME_SCHOOL_TYPES' order.
func programmeBlocks(t PlanTablesResult) []*screensv1.PageBlock {
	var blocks []*screensv1.PageBlock
	cols := columns("School ID", "School name", "District", "District Type", "Activity", "Planned date",
		"Completed date", "Salesforce ID", "Status", "Actions")
	cols[len(cols)-1].Numeric = false
	for _, kind := range rules.Rows.ProgrammeSchoolTypes {
		section := t.programme[kind]
		if len(section) == 0 {
			continue
		}
		var rows []*screensv1.PageRow
		for _, r := range section {
			code := r.schoolID.value
			if r.schoolID.null {
				code = "None"
			}
			when := "Awaiting schedule"
			if r.plannedBefore != nil || r.a.plannedDate != nil {
				when = planned(r.row)
			}
			sf := &screensv1.PageCell{Text: "Not in SF"}
			if r.salesforceID != "" {
				sf = &screensv1.PageCell{Text: r.salesforceID}
			}
			// place_url: the cluster's profile for work at a cluster, else the
			// school's (a session's row: the school it reached).
			place := r.placeURL
			tone := r.rowState
			if tone == "" && r.dayOff != nil {
				tone = "dayoff"
			}
			rows = append(rows, &screensv1.PageRow{Tone: tone, Cells: []*screensv1.PageCell{
				{Text: code}, {Text: r.schoolName, Href: place},
				{Text: orDefault(r.districtShown, dash)}, {Text: orDefault(r.districtType, dash)},
				{Text: str(r.activityTypeLabel)}, {Text: when + r.dayOffFlag()}, {Text: completed(r.row)},
				sf, {Text: r.statusLabel}, r.actions(),
			}})
		}
		blocks = append(blocks, &screensv1.PageBlock{Kind: &screensv1.PageBlock_Table{Table: &screensv1.PageTable{
			Title:   fmt.Sprintf("%s School Visits and Trainings Planned (%d)", rules.Tables.ProgrammeSchoolLabels[kind], len(rows)),
			Columns: cols, Rows: rows,
		}}})
	}
	return blocks
}

// coreBlocks are the Core School Visits and Core School Trainings tables.
func coreBlocks(t PlanTablesResult, words string, visitColumns []string) []*screensv1.PageBlock {
	var rows []*screensv1.PageRow
	done := 0
	for _, r := range t.core {
		if in(rules.Plan.CompletedWorkStatuses, r.a.status) {
			done++
		}
		rows = append(rows, pageRow(r, r.schoolName, append(schoolCells(r, r.schoolDistrict, "Core Visit"), tailCells(r)...)))
	}
	coreColumns := append([]string{}, visitColumns...)
	coreColumns[9] = "SSA Intervention"
	trainingsBlock := &screensv1.PageBlock{Kind: &screensv1.PageBlock_Table{Table: &screensv1.PageTable{
		Title: "Core School Trainings Planned for " + words, Subtitle: "0 0 completed",
		EmptyMessage: "No core school trainings planned for this period.",
		EmptyAction:  &screensv1.PageAction{Key: "empty", Label: "Open Core Schools", Enabled: true, Href: "/core-schools"},
	}}}
	if len(t.coreTrainings) > 0 {
		var tRows []*screensv1.PageRow
		tDone := 0
		for _, r := range t.coreTrainings {
			if in(rules.Plan.CompletedWorkStatuses, r.a.status) {
				tDone++
			}
			tRows = append(tRows, pageRow(r, r.clusterName, append(trainingTableCells(r), tailCells(r)...)))
		}
		trainingsBlock = &screensv1.PageBlock{Kind: &screensv1.PageBlock_Table{Table: &screensv1.PageTable{
			Title: "Core School Trainings Planned for " + words, Subtitle: fmt.Sprintf("%d %d completed", len(tRows), tDone),
			Columns: columns("School ID", "School / Cluster", "District", "District Type", "Cluster Planned From",
				"Executor", "Training Name", "Planned Date", "Completed Date", "SSA Intervention", "Participants",
				"Mode of Delivery", "Cost", "Budget status", "Verification", "Salesforce ID", "Status", "Actions"),
			Rows: tRows,
		}}}
	}
	return []*screensv1.PageBlock{
		&screensv1.PageBlock{Kind: &screensv1.PageBlock_Table{Table: &screensv1.PageTable{
			Title: "Core School Visits Planned for " + words, Subtitle: fmt.Sprintf("%d %d completed", len(rows), done),
			Columns: columns(coreColumns...), Rows: rows,
		}}},
		trainingsBlock,
	}
}

// dayOffFlag is day_off_flag.html as the feed reads it beside the planned
// day: " <label>: reschedule" (the include opens on a line break, which the
// feed reads as one space).
func (r *planRow) dayOffFlag() string {
	if r.dayOff == nil {
		return ""
	}
	return " " + r.dayOff.Label + ": reschedule"
}

// dayOffCard is attention.html's first card, "Reschedule — On a Public
// Holiday or Leave Day": the work on a day off, in the loop's order.
func dayOffCard(rows []*planRow) *screensv1.PageBlock {
	var out []*screensv1.PageRow
	for _, r := range rows {
		code := dash
		if r.schoolID.truthy() {
			code = filledCode(r.row)
		}
		place := &screensv1.PageCell{}
		switch {
		case r.schoolName != "" && r.schoolName != "Unknown School":
			place.Text = r.schoolName
			if r.schoolID.truthy() {
				place.Href = "/schools/" + r.schoolID.value
			}
		case r.clusterID != "":
			place.Text, place.Href = r.clusterName, "/clusters/"+r.clusterID
		default:
			place.Text = orDefault(r.clusterName, "General")
		}
		reschedule := &screensv1.PageAction{Key: "button", Label: "Reschedule", Primary: true, Enabled: true,
			Href: "/my-plan/" + r.a.id + "/reschedule-drawer", Drawer: true}
		action := &screensv1.PageCell{Actions: []*screensv1.PageAction{reschedule}}
		if str(r.a.delivery) != "staff" {
			// execution_role is "Partner" for any other delivery: "The
			// partner reschedules", which the feed does not read.
			action = &screensv1.PageCell{}
		}
		row := &screensv1.PageRow{Cells: []*screensv1.PageCell{
			{Text: code}, place, {Text: str(r.activityTypeLabel)}, {Text: r.dayOff.Summary}, action,
		}, Tone: "dayoff"}
		if r.canPick {
			label := "Select " + orDefault(str(r.activityTypeLabel), "activity")
			if r.schoolName != "" {
				label += " at " + r.schoolName
			}
			if d := date(r.a.plannedDate); d != nil {
				label += " on " + shownDay(d)
			}
			row.PickId, row.PickLabel = r.a.id, label
		}
		out = append(out, row)
	}
	cols := columns("School ID", "School / Cluster", "Type", "Day Off", "Action")
	cols[len(cols)-1].Numeric = true
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Table{Table: &screensv1.PageTable{
		Title: "Reschedule — On a Public Holiday or Leave Day", Columns: cols, Rows: out,
	}}}
}
