package partneroversight

import (
	"net/url"
	"strconv"
	"strings"
	"time"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
)

// The page with partner work in it (partner_oversight_view over
// partials/oversight/partner_workspace.html), as the feed reads it.

const (
	noWork        = "No partner work in this period"
	noSchoolsRow  = "No schools assigned to this Partner for the selected team and filters."
	noWorkRow     = "No work for the selected team and filters."
	noCoreRow     = "No Core Schools assigned to this Partner for the selected team and filters."
	tablePageSize = 50
)

// partnerTab is one Partner's tab: the organisation and its work.
type partnerTab struct {
	key, label string
	count      int
	// followUp is the Country Director Analytics' recommendation when the
	// Partner needs following up (partners_needing_follow_up).
	followUp string
}

// target is _partner_visit_target's figures.
type target struct{ target, core, beyond, held int }

// workView is what the page draws for a reader with partner work.
type workView struct {
	w          workspace
	today      time.Time
	leads      []leadTab
	partners   []partnerTab
	partner    string
	partnerTab *partnerTab
	members    []memberTab
	typed      []*item
	shown      []*item
	tab        string
	tableItems []*item
	years      []string
	target     *target
	// trainings are the group trainings the Partner facilitates that the
	// team member and status shown hold.
	trainings []*training
	// selectable is a Schools table with a row that can be withdrawn: its
	// tick boxes and the Withdraw selected bar.
	selectable bool
}

type memberTab struct {
	key, label string
	count      int
}

// workTables is workspace_tables' tables for the open tab: their title,
// rows, kind ("assignment" or "activity") and columns ("school" or "").
type workTable struct {
	title, kind, columns string
	items                []*item
}

func tablesFor(items []*item) []workTable {
	activities := []*item{}
	for _, i := range items {
		if i.activityID != "" {
			activities = append(activities, i)
		}
	}
	pick := func(from []*item, keep func(*item) bool) []*item {
		out := []*item{}
		for _, i := range from {
			if keep(i) {
				out = append(out, i)
			}
		}
		return out
	}
	tables := []workTable{}
	if core := pick(items, (*item).isCoreSchoolWork); len(core) > 0 {
		tables = append(tables, workTable{"Core Schools assigned", "core", "core", core})
	}
	return append(tables, []workTable{
		{"Schools assigned", "assignment", "school", pick(items, func(i *item) bool {
			return i.assignmentID != "" && i.schoolID != "" && !i.isCoreSchoolWork()
		})},
		{"Visits", "activity", "", pick(activities, func(i *item) bool { return i.workTab() == "visits" })},
		{"Trainings", "activity", "", pick(activities, func(i *item) bool { return i.workTab() == "trainings" })},
		{"Cluster work assigned", "assignment", "", pick(items, func(i *item) bool { return i.assignmentID != "" && i.clusterID != "" })},
		{"Cluster sessions", "activity", "", pick(activities, func(i *item) bool { return i.workTab() == "clusters" })},
	}...)
}

var tableTab = map[string]string{"Core Schools assigned": "core", "Schools assigned": "schools", "Visits": "visits", "Trainings": "trainings",
	"Cluster work assigned": "clusters", "Cluster sessions": "clusters"}

// workTabOpen is work_tabs' open tab: the one asked for if it is a tab, else
// the first holding anything. Core schools is a tab only for a Partner who
// holds a Core school.
func workTabOpen(tables []workTable, requested string, core, trainings int) string {
	counts := map[string]int{"core": core, "clusters": trainings}
	for _, t := range tables {
		counts[tableTab[t.title]] += len(t.items)
	}
	keys := []string{"schools", "visits", "trainings", "clusters"}
	if core > 0 {
		keys = []string{"schools", "core", "visits", "trainings", "clusters"}
	}
	for _, k := range keys {
		if k == requested {
			return k
		}
	}
	for _, k := range keys {
		if counts[k] > 0 {
			return k
		}
	}
	return keys[0]
}

func (v *workView) blocks() []*screensv1.PageBlock {
	w := v.w
	blocks := []*screensv1.PageBlock{v.filters()}
	if len(v.leads) > 0 {
		blocks = append(blocks, v.leadPanel())
	}
	if len(v.partners) > 0 {
		blocks = append(blocks, v.partnerPanel())
	}
	blocks = append(blocks, v.memberTabs(), v.tiles())
	switch {
	case v.partnerTab == nil:
		blocks = append(blocks, &screensv1.PageBlock{Kind: &screensv1.PageBlock_Empty{Empty: emptyWork}})
	case v.tab == "clusters":
		blocks = append(blocks, v.cardParts()...)
	default:
		blocks = append(blocks, &screensv1.PageBlock{Kind: &screensv1.PageBlock_Table{Table: v.card()}})
	}
	if w.role.EngagementRegister {
		blocks = append(blocks, register(w)...)
	}
	return blocks
}

func (v *workView) query() string {
	p := v.w.period
	return "&period=" + p.kind + "&fy=" + p.fy + "&week=" + p.week + "&month=" + strconv.Itoa(p.month) + "&quarter=" + p.quarter
}

// filters is the period bar with the Status filter, each phase counting the
// Partner's rows it would show.
func (v *workView) filters() *screensv1.PageBlock {
	block := filters(v.w)
	f := block.GetFilters()
	for _, sel := range f.Filters {
		if sel.Name != "status" {
			continue
		}
		for _, o := range sel.Options {
			if o.Value == "" {
				continue
			}
			n := 0
			for _, i := range v.typed {
				if i.deliveryPhase() == o.Value {
					n++
				}
			}
			o.Label = title_(o.Value) + " (" + strconv.Itoa(n) + ")"
		}
	}
	if v.partner != "" {
		f.Hidden["partner"] = v.partner
	}
	return block
}

func (v *workView) partnerPanel() *screensv1.PageBlock {
	links := []*screensv1.PageLink{}
	for _, t := range v.partners {
		href := "?partner=" + t.key
		if v.w.programLead != "" {
			href += "&program_lead=" + v.w.programLead
		}
		caption := strconv.Itoa(t.count)
		if t.followUp != "" {
			caption += " · " + t.followUp
		}
		links = append(links, &screensv1.PageLink{Text: t.label, Href: href + v.query(), Caption: caption})
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{
		Badges: []*screensv1.PageBadge{},
		Items: []*screensv1.PagePanelItem{
			{Kind: &screensv1.PagePanelItem_Text{Text: "Partners"}},
			{Kind: &screensv1.PagePanelItem_Links{Links: &screensv1.PageLinks{Links: links}}},
		},
	}}}
}

func (v *workView) memberTabs() *screensv1.PageBlock {
	w, p := v.w, v.w.period
	tabs := []*screensv1.PageLinkTab{}
	for _, m := range v.members {
		href := "?program_lead=" + w.programLead + "&partner=" + v.partner + "&member=" + m.key + "&work=" + v.tab +
			"&period=" + p.kind + "&fy=" + p.fy + "&month=" + strconv.Itoa(p.month) + "&quarter=" + p.quarter + "&week=" + p.week
		tabs = append(tabs, &screensv1.PageLinkTab{Label: m.label + " " + strconv.Itoa(m.count), Href: href, Active: m.key == w.member})
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_LinkTabs{LinkTabs: &screensv1.PageLinkTabs{Tabs: tabs, Scrolls: true}}}
}

// summary is partner_oversight_service.summarize's figures the page draws.
type summary struct {
	awaiting, visits, trainings, meetings, overdue, completed        int
	activePartners, schools, scheduled, returned, inProgress, atRisk int
	payments                                                         int
	budget                                                           int64
}

func summarize(items []*item) summary {
	w := rules.Work
	var s summary
	partners, schools := map[string]bool{}, map[string]bool{}
	visits, trainings, meetings := map[string]bool{}, map[string]bool{}, map[string]bool{}
	for _, i := range items {
		if i.stage == stageAwaiting {
			s.awaiting++
		}
		if i.isScheduled() {
			s.scheduled++
			if in(w.PlannedStatuses, i.activityStatus) {
				switch {
				case in(w.VisitTypes, i.activityType):
					visits[i.activityID] = true
				case in(w.TrainingTypes, i.activityType):
					trainings[i.activityID] = true
				case in(w.ClusterMeetingTypes, i.activityType):
					meetings[i.activityID] = true
				}
			}
			if i.plannedCost != nil {
				s.budget += *i.plannedCost
			}
			if (i.paymentStatus == "" || i.paymentStatus == "none" || i.paymentStatus == "pending") &&
				in(w.Complete, i.activityStatus) && i.iaStatus == "confirmed" {
				s.payments++
			}
		}
		if i.isReturned() {
			s.returned++
		}
		for _, r := range i.risks {
			if r == "partner_schedule_overdue" || r == "partner_delivery_overdue" {
				s.overdue++
				break
			}
		}
		if len(i.risks) > 0 {
			s.atRisk++
		}
		if i.partnerID != "" && !i.isReturned() {
			partners[i.partnerID] = true
		}
		if i.schoolID != "" && !i.isReturned() {
			schools[i.schoolID] = true
		}
		switch i.deliveryPhase() {
		case "in_progress":
			s.inProgress++
		case "completed":
			s.completed++
		}
	}
	s.visits, s.trainings, s.meetings = len(visits), len(trainings), len(meetings)
	s.activePartners, s.schools = len(partners), len(schools)
	return s
}

// tiles is _partner_kpis over the rows shown, as the strip draws them.
func (v *workView) tiles() *screensv1.PageBlock {
	s := summarize(v.shown)
	helper := intcomma(int64(s.schools)) + " schools assigned"
	first := &screensv1.PageMetric{Label: rules.ZeroTiles[0].Label, Value: intcomma(int64(s.activePartners)), Helper: helper, Tone: "neutral"}
	if t := v.target; t != nil {
		first.Note = helper + " · Partner target " + intcomma(int64(t.target)) + " visits (" + intcomma(int64(t.core)) +
			" Core + " + intcomma(int64(t.beyond)) + " beyond staff capacity), " + intcomma(int64(t.held)) + " with a Partner"
	}
	attention := "neutral"
	if s.atRisk > 0 {
		attention = "danger"
	}
	metrics := []*screensv1.PageMetric{
		first,
		{Label: rules.ZeroTiles[1].Label, Value: intcomma(int64(s.awaiting)), Note: rules.ZeroTiles[1].Note},
		{Label: rules.ZeroTiles[2].Label, Value: intcomma(int64(s.scheduled)), Helper: intcomma(int64(s.inProgress)) + " in progress", Tone: "neutral"},
		{Label: rules.ZeroTiles[3].Label, Value: intcomma(int64(s.atRisk)), Helper: intcomma(int64(s.returned)) + " returned to staff", Tone: attention},
		{Label: rules.ZeroTiles[4].Label, Value: "UGX " + intcomma(s.budget), Note: rules.ZeroTiles[4].Note},
		{Label: rules.ZeroTiles[5].Label, Value: intcomma(int64(s.payments)), Note: rules.ZeroTiles[5].Note},
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Strip{Strip: &screensv1.PageStrip{Title: tilesTitle, Metrics: metrics}}}
}

// card is the Partner's card as one table: the open tab's one table under
// the Partner's name, its summary chips the subtitle.
func (v *workView) card() *screensv1.PageTable {
	s := summarize(v.shown)
	overdue := strconv.Itoa(s.overdue)
	subtitle := strconv.Itoa(s.awaiting) + " awaiting scheduling " + strconv.Itoa(s.visits) + " visits scheduled " +
		strconv.Itoa(s.trainings) + " trainings scheduled " + strconv.Itoa(s.meetings) + " meetings scheduled " +
		overdue + " overdue " + strconv.Itoa(s.completed) + " completed"
	var table workTable
	for _, t := range tablesFor(v.tableItems) {
		if tableTab[t.title] == v.tab {
			table = t
			break
		}
	}
	out := &screensv1.PageTable{Title: v.partnerTab.label, Subtitle: subtitle}
	if len(v.years) > 1 {
		out.Footnote = "Read for " + horizonLabel(v.years) + ": work a Partner dates into the next financial year stays here, on its date."
	}
	switch table.columns {
	case "core":
		for _, l := range []string{"School ID", "School Name", "Staff Name", "Core support", "Purpose of Assignment",
			"Planned date", "Completed date", "Cost", "Salesforce ID", "Evidence", "Status", "Actions"} {
			out.Columns = append(out.Columns, &screensv1.PageColumn{Label: l, Numeric: l == "Cost"})
		}
	case "school":
		for _, l := range []string{"School ID", "School Name", "Staff Name", "Training", "Purpose of Assignment",
			"SSA Intervention", "Salesforce ID", "Evidence", "Status", "Activity date", "Completed date", "Actions"} {
			out.Columns = append(out.Columns, &screensv1.PageColumn{Label: l})
		}
	default:
		first, dated := "School", "Activity date"
		if table.kind == "activity" {
			first, dated = "School / cluster", "Scheduled"
		} else if table.title == "Cluster work assigned" {
			first = "Cluster"
		}
		for _, l := range []string{first, "Staff member", "Activity / purpose", "Salesforce ID", "Evidence", "Status",
			dated, "Completed date", "Actions"} {
			out.Columns = append(out.Columns, &screensv1.PageColumn{Label: l})
		}
	}
	selectable := false
	for _, i := range table.items {
		if i.withdrawalLabel != "" {
			selectable = true
		}
	}
	v.selectable = (table.columns == "school" || table.columns == "core") && selectable
	for _, i := range table.items {
		var row *screensv1.PageRow
		switch table.columns {
		case "school", "core":
			if table.columns == "core" {
				row = v.coreRow(i)
			} else {
				row = v.schoolRow(i)
			}
			if selectable && i.withdrawalLabel != "" {
				row.PickId = i.assignmentID
			}
		default:
			row = v.workRow(i, table.kind)
		}
		out.Rows = append(out.Rows, row)
	}
	if len(table.items) == 0 {
		empty := noWorkRow
		switch table.columns {
		case "school":
			empty = noSchoolsRow
		case "core":
			empty = noCoreRow
		}
		out.Rows = []*screensv1.PageRow{{Cells: []*screensv1.PageCell{{Text: empty}}}}
	}
	return out
}

func orDash(s string) string {
	if s == "" {
		return "—"
	}
	return s
}

func jMY(t *time.Time) string {
	if t == nil {
		return ""
	}
	return strconv.Itoa(t.Day()) + " " + t.Month().String()[:3] + " " + strconv.Itoa(t.Year())
}

func (v *workView) schoolHref(i *item) string {
	code := strings.TrimSpace(i.schoolCode)
	if !v.w.role.SchoolProfiles || i.schoolName == "" || code == "" {
		return ""
	}
	return "/schools/" + url.PathEscape(code)
}

func (v *workView) clusterHref(i *item) string {
	id := strings.TrimSpace(i.clusterID)
	if !v.w.role.ClusterProfiles || i.clusterName == "" || id == "" {
		return ""
	}
	return "/clusters/" + url.PathEscape(id)
}

func (v *workView) statusCell(i *item) *screensv1.PageCell {
	text := i.completionGap
	if text == "" {
		text = i.statusLabel()
	}
	if i.isOverdue(v.today) {
		text += " Overdue"
	}
	return &screensv1.PageCell{Text: text}
}

func completionCells(i *item) []*screensv1.PageCell {
	sf := i.salesforceID
	if sf == "" {
		sf = "Not in SF"
	}
	evidence := i.evidenceLabel
	if evidence == "" {
		evidence = "No Evidence Uploaded"
	}
	return []*screensv1.PageCell{{Text: sf}, {Text: evidence}}
}

// actions is the row's Actions cell for work with a hand-over: Resolve
// Exception on a hand-back the reader decides, else View and the withdrawal
// the record permits as one menu, else View alone.
func (v *workView) actions(i *item) *screensv1.PageCell {
	if i.canReview {
		menu := []*screensv1.PageAction{
			{Key: "menu", Label: "View", Enabled: true, Href: "/partner-oversight/detail?assignment_id=" + i.assignmentID, Drawer: true},
		}
		if i.withdrawalLabel != "" {
			menu = append(menu, &screensv1.PageAction{Key: "menu", Label: i.withdrawalLabel, Enabled: true,
				Href: "/partner-oversight/withdraw?assignment_id=" + i.assignmentID, Drawer: true})
		}
		return &screensv1.PageCell{Actions: append(menu, reviewItems(i)...)}
	}
	if i.awaitsStaffDecision() && v.w.role.ResolvesReturns && !i.projectLocked {
		return &screensv1.PageCell{Text: "Resolve Exception"}
	}
	if i.withdrawalLabel == "" {
		return &screensv1.PageCell{Text: "View"}
	}
	return &screensv1.PageCell{Actions: []*screensv1.PageAction{
		{Key: "menu", Label: "View", Enabled: true, Href: "/partner-oversight/detail?assignment_id=" + i.assignmentID, Drawer: true},
		{Key: "menu", Label: i.withdrawalLabel, Enabled: true, Href: "/partner-oversight/withdraw?assignment_id=" + i.assignmentID, Drawer: true},
	}}
}

func fact(label, value string) *screensv1.PageFact {
	return &screensv1.PageFact{Label: label, Value: value}
}

// standing is the details' read-only facts on where the work stands.
func standing(i *item) []*screensv1.PageFact {
	out := []*screensv1.PageFact{}
	if i.activityID != "" {
		out = append(out, fact("Execution", i.executionStatus()), fact("IA", i.iaStatusLabel()),
			fact("Salesforce", i.salesforceLabel()), fact("Payment", i.paymentLabel()))
	}
	if i.returnReason != "" {
		out = append(out, fact("Returned", pyTitle(strings.ReplaceAll(i.returnReasonCategory, "_", " "))+" — "+i.returnReason))
	}
	if i.isReturned() && i.resolution != "" {
		out = append(out, fact("Decision", resolutionLabel(i.resolution)))
	}
	if f := projectFact(i); f != nil {
		out = append(out, f)
	}
	return out
}

// projectFact is the details' Special Project line.
func projectFact(i *item) *screensv1.PageFact {
	if i.projectName == "" {
		return nil
	}
	value := i.projectName
	if i.projectLocked {
		value += " — withdrawals and reassignments are its Project Coordinator's"
	}
	return fact("Special Project", value)
}

// resolutionLabel is get_resolution_display: the decision in words, the
// stored value where it names no choice.
func resolutionLabel(value string) string {
	if l, ok := rules.Work.ResolutionLabels[value]; ok {
		return l
	}
	return value
}

func (v *workView) schoolRow(i *item) *screensv1.PageRow {
	cells := []*screensv1.PageCell{
		{Text: orDash(i.schoolCode)},
		{Text: i.schoolName, Href: v.schoolHref(i)},
		{Text: orDefault(i.cceoName, "Unassigned")},
		{Text: orDash(i.trainingName)},
		{Text: orDash(i.purposeLabel)},
		{Text: orDash(i.interventionLabel)},
	}
	cells = append(cells, completionCells(i)...)
	dated := "—"
	if d := i.activityDate(); d != nil {
		dated = jMY(d)
	} else if i.stage == stageAwaiting {
		dated = "Awaiting scheduling"
	}
	cells = append(cells, v.statusCell(i), &screensv1.PageCell{Text: dated},
		&screensv1.PageCell{Text: orDash(jMY(i.completedOn))}, v.actions(i))
	details := []*screensv1.PageFact{}
	if i.assignmentDate != nil {
		details = append(details, fact("Assigned", jMY(i.assignmentDate)))
	}
	if i.fieldOfficer != "" {
		details = append(details, fact("Partner officer", i.fieldOfficer))
	}
	if i.district != "" {
		details = append(details, fact("District", i.district))
	}
	if i.schoolClusterName != "" {
		details = append(details, fact("Cluster", i.schoolClusterName))
	}
	details = append(details, standing(i)...)
	return &screensv1.PageRow{Cells: cells, Details: details, DetailBlocks: []*screensv1.PageBlock{}}
}

func (v *workView) workRow(i *item, kind string) *screensv1.PageRow {
	name, href := i.schoolName, v.schoolHref(i)
	if name == "" {
		name, href = i.clusterName, v.clusterHref(i)
	}
	cells := []*screensv1.PageCell{
		{Text: name, Href: href},
		{Text: orDefault(i.cceoName, "Unassigned")},
		{Text: pyTitle(strings.ReplaceAll(i.activityType, "_", " "))},
	}
	cells = append(cells, completionCells(i)...)
	dated := jMY(i.scheduledDate)
	if dated == "" {
		dated = "Awaiting scheduling"
		if kind == "activity" {
			dated = "Awaiting date"
		}
	}
	cells = append(cells, v.statusCell(i), &screensv1.PageCell{Text: dated}, &screensv1.PageCell{Text: orDash(jMY(i.completedOn))})
	switch {
	case i.assignmentID != "":
		cells = append(cells, v.actions(i))
	case i.canReview:
		menu := []*screensv1.PageAction{{Key: "menu", Label: "View activity", Enabled: true, Href: "/activities/" + i.activityID}}
		if i.withdrawalLabel != "" {
			menu = append(menu, &screensv1.PageAction{Key: "menu", Label: i.withdrawalLabel, Enabled: true,
				Href: "/partner-oversight/withdraw?activity_id=" + i.activityID, Drawer: true})
		}
		cells = append(cells, &screensv1.PageCell{Actions: append(menu, reviewItems(i)...)})
	case i.withdrawalLabel != "":
		cells = append(cells, &screensv1.PageCell{Actions: []*screensv1.PageAction{
			{Key: "menu", Label: "View activity", Enabled: true, Href: "/activities/" + i.activityID},
			{Key: "menu", Label: i.withdrawalLabel, Enabled: true, Href: "/partner-oversight/withdraw?activity_id=" + i.activityID, Drawer: true},
		}})
	default:
		// The record-action mark sits on the link's wrapper, not the cell:
		// the feed reads the lone link as the cell's text.
		cells = append(cells, &screensv1.PageCell{Text: "View activity", Href: "/activities/" + i.activityID})
	}
	details := []*screensv1.PageFact{}
	if i.schoolCode != "" {
		details = append(details, fact("School ID", i.schoolCode))
	}
	if i.assignmentDate != nil {
		details = append(details, fact("Assigned", jMY(i.assignmentDate)))
	}
	if i.fieldOfficer != "" {
		details = append(details, fact("Partner officer", i.fieldOfficer))
	}
	if i.district != "" {
		details = append(details, fact("District", i.district))
	}
	if i.clusterName != "" && i.schoolName != "" {
		f := fact("Cluster", i.clusterName)
		f.Href = v.clusterHref(i)
		details = append(details, f)
	}
	if i.targetIntervention != "" {
		details = append(details, fact("Target intervention", i.targetIntervention))
	}
	details = append(details, standing(i)...)
	return &screensv1.PageRow{Cells: cells, Details: details, DetailBlocks: []*screensv1.PageBlock{}}
}

func orDefault(s, d string) string {
	if s == "" {
		return d
	}
	return s
}

// intcomma is the figure with thousands separated by commas.
func intcomma(n int64) string {
	s := strconv.FormatInt(n, 10)
	neg := strings.HasPrefix(s, "-")
	s = strings.TrimPrefix(s, "-")
	for i := len(s) - 3; i > 0; i -= 3 {
		s = s[:i] + "," + s[i:]
	}
	if neg {
		return "-" + s
	}
	return s
}

// horizonLabel is fy_policy.horizon_label.
func horizonLabel(years []string) string {
	switch len(years) {
	case 0:
		return ""
	case 1:
		return "FY " + years[0]
	}
	return "FY " + years[0] + "–" + years[len(years)-1]
}

// coreRow is partner_core_row.html: the package slot, the planned date, the
// cost, and one Actions menu (View, Withdraw school while the Partner has
// not dated it, Resolve Exception on a hand-back the reader decides).
func (v *workView) coreRow(i *item) *screensv1.PageRow {
	planned := "—"
	if d := i.activityDate(); d != nil {
		planned = jMY(d)
	} else if i.stage == stageAwaiting {
		planned = "Waiting for scheduling from partner"
	}
	cost := "Rate not set"
	if c := i.displayCost(); c != nil {
		cost = "UGX " + intcomma(*c)
	} else if i.isReturned() {
		cost = "—"
	}
	cells := []*screensv1.PageCell{
		{Text: orDash(i.schoolCode)},
		{Text: i.schoolName, Href: v.schoolHref(i)},
		{Text: orDefault(i.cceoName, "Unassigned")},
		{Text: orDash(i.coreSlotLabel)},
		{Text: orDash(i.purposeLabel)},
		{Text: planned},
		{Text: orDash(jMY(i.completedOn))},
		{Text: cost},
	}
	cells = append(cells, completionCells(i)...)
	actions := []*screensv1.PageAction{
		{Key: "menu", Label: "View", Enabled: true, Href: "/partner-oversight/detail?assignment_id=" + i.assignmentID, Drawer: true},
	}
	if i.canReview {
		actions = append(actions, &screensv1.PageAction{Key: "menu", Label: "Return", Enabled: true,
			Href: "/partner-oversight/return?activity_id=" + i.activityID, Drawer: true})
	}
	withdraw := v.w.role.WithdrawsPartnerWork && i.withdrawalLabel != "" && !i.projectLocked &&
		(i.stage == stageAwaiting || (i.withdrawalKind() == "recall_scheduled" && !i.partnerHasDated))
	if withdraw {
		actions = append(actions, &screensv1.PageAction{Key: "menu", Label: "Withdraw school", Enabled: true,
			Href: "/partner-oversight/withdraw?assignment_id=" + i.assignmentID, Drawer: true})
	}
	if i.awaitsStaffDecision() && v.w.role.ResolvesReturns && !i.projectLocked {
		actions = append(actions, &screensv1.PageAction{Key: "menu", Label: "Resolve Exception", Enabled: true,
			Href: "/partner-oversight/resolve?assignment_id=" + i.assignmentID, Drawer: true})
	}
	cells = append(cells, v.statusCell(i), &screensv1.PageCell{Actions: actions})
	details := []*screensv1.PageFact{}
	if i.assignmentDate != nil {
		details = append(details, fact("Assigned", jMY(i.assignmentDate)))
	}
	if i.trainingName != "" {
		details = append(details, fact("Training", i.trainingName))
	}
	if i.interventionLabel != "" {
		details = append(details, fact("SSA Intervention", i.interventionLabel))
	}
	if i.fieldOfficer != "" {
		details = append(details, fact("Partner officer", i.fieldOfficer))
	}
	if i.district != "" {
		details = append(details, fact("District", i.district))
	}
	if i.activityID != "" {
		details = append(details, fact("Execution", i.executionStatus()), fact("IA", i.iaStatusLabel()),
			fact("Payment", i.paymentLabel()))
	}
	if i.returnReason != "" {
		details = append(details, fact("Returned", pyTitle(strings.ReplaceAll(i.returnReasonCategory, "_", " "))+" — "+i.returnReason))
	}
	if i.isReturned() && i.resolution != "" {
		details = append(details, fact("Decision", resolutionLabel(i.resolution)))
	}
	if f := projectFact(i); f != nil {
		details = append(details, f)
	}
	return &screensv1.PageRow{Cells: cells, Details: details, DetailBlocks: []*screensv1.PageBlock{}}
}

// followUpWords are the card's follow-up line after the recommendation.
var followUpWords = map[string]string{
	"Quality Review":  " · on target, but its schools' SSA rose less than half a point",
	"Capacity Review": " · its schools' SSA rose, but its work is below target",
}

// cardParts is the Partner's card where it holds more than one table (the
// Clusters tab), read part by part: its head (the Partner's name, the
// follow-up line and the status chips), the work tabs, each table under its
// heading, and the note on the years read.
func (v *workView) cardParts() []*screensv1.PageBlock {
	s := summarize(v.shown)
	subtitle := ""
	if f := v.partnerTab.followUp; f != "" {
		subtitle = "Needs follow-up: " + f + followUpWords[f]
	}
	chips := []*screensv1.PageLink{}
	for _, c := range []string{
		strconv.Itoa(s.awaiting) + " awaiting scheduling", strconv.Itoa(s.visits) + " visits scheduled",
		strconv.Itoa(s.trainings) + " trainings scheduled", strconv.Itoa(s.meetings) + " meetings scheduled",
		strconv.Itoa(s.overdue) + " overdue", strconv.Itoa(s.completed) + " completed",
	} {
		chips = append(chips, &screensv1.PageLink{Text: c})
	}
	out := []*screensv1.PageBlock{{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{
		Title: v.partnerTab.label, Subtitle: subtitle, Badges: []*screensv1.PageBadge{},
		Items: []*screensv1.PagePanelItem{{Kind: &screensv1.PagePanelItem_Links{Links: &screensv1.PageLinks{Links: chips}}}},
	}}}}

	tables := tablesFor(v.tableItems)
	counts := map[string]int{}
	core := false
	for _, t := range tables {
		counts[tableTab[t.title]] += len(t.items)
		core = core || t.columns == "core"
	}
	counts["clusters"] += len(v.trainings)
	w, p := v.w, v.w.period
	tabs := []*screensv1.PageLinkTab{}
	for _, t := range [][2]string{{"schools", "Schools assigned"}, {"core", "Core schools"}, {"visits", "Visits"},
		{"trainings", "Trainings"}, {"clusters", "Clusters to facilitate"}} {
		if t[0] == "core" && !core {
			continue
		}
		href := "?program_lead=" + w.programLead + "&partner=" + v.partner + "&member=" + w.member + "&work=" + t[0] +
			"&status=" + w.status + "&period=" + p.kind + "&fy=" + p.fy + "&month=" + strconv.Itoa(p.month) +
			"&quarter=" + p.quarter + "&week=" + p.week
		tabs = append(tabs, &screensv1.PageLinkTab{Label: t[1] + " " + strconv.Itoa(counts[t[0]]), Href: href, Active: t[0] == v.tab})
	}
	out = append(out, &screensv1.PageBlock{Kind: &screensv1.PageBlock_LinkTabs{LinkTabs: &screensv1.PageLinkTabs{Tabs: tabs, Scrolls: true}}})

	for _, t := range tables {
		if tableTab[t.title] != v.tab {
			continue
		}
		out = append(out, &screensv1.PageBlock{Kind: &screensv1.PageBlock_Section{Section: t.title + " (" + strconv.Itoa(len(t.items)) + ")"}})
		table := &screensv1.PageTable{}
		first := "School"
		if t.kind == "activity" {
			first = "School / cluster"
		} else if t.title == "Cluster work assigned" {
			first = "Cluster"
		}
		dated := "Activity date"
		if t.kind == "activity" {
			dated = "Scheduled"
		}
		for _, l := range []string{first, "Staff member", "Activity / purpose", "Salesforce ID", "Evidence", "Status",
			dated, "Completed date", "Actions"} {
			table.Columns = append(table.Columns, &screensv1.PageColumn{Label: l})
		}
		for _, i := range t.items {
			table.Rows = append(table.Rows, v.workRow(i, t.kind))
		}
		if len(t.items) == 0 {
			table.Rows = []*screensv1.PageRow{{Cells: []*screensv1.PageCell{{Text: noWorkRow}}}}
		}
		out = append(out, &screensv1.PageBlock{Kind: &screensv1.PageBlock_Table{Table: table}})
	}
	if len(v.years) > 1 {
		out = append(out, &screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{
			Badges: []*screensv1.PageBadge{},
			Items: []*screensv1.PagePanelItem{{Kind: &screensv1.PagePanelItem_Text{
				Text: "Read for " + horizonLabel(v.years) + ": work a Partner dates into the next financial year stays here, on its date."}}},
		}}})
	}
	// The group trainings the Partner facilitates follow the work tables.
	if len(v.trainings) > 0 {
		out = append(out, v.trainingsBlocks(v.trainings)...)
	}
	return out
}

// reviewItems are _partner_review_items.html: Verify & Confirm (SSA
// Support's own drawer, which also records the scores) and Return.
func reviewItems(i *item) []*screensv1.PageAction {
	verify := "/partner-oversight/verify?activity_id=" + i.activityID
	if i.reviewIsSSA {
		verify = "/activities/" + i.activityID + "/partner-ssa-complete"
	}
	return []*screensv1.PageAction{
		{Key: "menu", Label: "Verify & Confirm", Enabled: true, Href: verify, Drawer: true},
		{Key: "menu", Label: "Return", Enabled: true, Href: "/partner-oversight/return?activity_id=" + i.activityID, Drawer: true},
	}
}
