package myplan

import (
	"context"
	"fmt"
	"time"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/calendarpage"
	registry "github.com/O-Mario88/edify-planning-tool/platform/backend/internal/country"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// Piece 3b: My Plan's own School Visits, Cluster Meetings and Core School
// Visits tables, for a plan whose listed work is finished (delivered,
// approved, closed) or off the plan (asked for by a Status of a left-out
// state). Work still to be delivered (its day-off marks), work sent back or
// handed in (the attention cards), work with money moving, SSA visits
// awaiting scores, Core package slots and programme work are still the
// existing application's: a page listing any of them is passed. Piece 3e
// added the Trainings and Group Trainings tables (the cluster expansion);
// a session reaching a Core School and a Core School's training are still
// passed.

// planTablePageSize is how many rows a table pages by (TABLE_PAGE_SIZE).
const planTablePageSize = 50

// Which of the plan's tables a row is in.
const (
	tableSchoolVisits = iota
	tableMeetings
	tableCoreVisits
	tableProgrammeSchool
	tableTrainings
)

// programmePageSize is how many rows a programme school section pages by.
const programmePageSize = 20

// statusOptions are the Status select's values other than "all"
// (partials/my_plan/filters.html).
var statusOptions = []string{"scheduled", "upcoming", "under_way", "overdue", "completed", "submitted", "returned_for_correction"}

// extra is what a row of these tables reads beyond 3a's activity.
type extra struct {
	evidence, payment, meetingKind *string
	clusterDistrict, eventDistrict *string
	endDate                        *time.Time
	reviewNote, schoolSSAStatus    *string
	activityName                   *string
	// advances are the advances on its cost lines (_advances_of).
	advances []advance
}

// planRow is one row of My Plan's own tables.
type planRow struct {
	*row
	x                       extra
	table                   int
	tone                    string
	rowState, districtShown string
	canPick, showsComplete  bool
	// dayOff is the day-off mark of work still waiting for its day.
	dayOff *calendarpage.DayOffMark
	// inTable is whether the row is in one of the tables (a row in none
	// reaches only the day-off card, with no tick box).
	inTable bool
	// next is compute_next_action's answer for the row.
	next nextAction
}

// PlanTablesResult is what the tables of a served page hold.
type PlanTablesResult struct {
	visits, meetings, core []*planRow
	// trainings are the Trainings table (each session once a school it
	// reached), group the Group Trainings table (each session once).
	trainings, group []*planRow
	// programme are the programme schools' sections, by type.
	programme map[string][]*planRow
	// statusShown is the Status select's value when the Core slots overwrite
	// it ("all"), else "".
	statusShown string
	// overwritten is whether they did.
	overwritten bool
	// dayOff are the rows on a day off, in the loop's order (the
	// Reschedule card); returned, waiting and finance the other cards'.
	dayOff, returned, waiting, finance []*planRow
}

// readExtras reads the columns these rows need beyond 3a's, and each
// activity's advances (compute_next_action).
func readExtras(ctx context.Context, db schooldirectory.Querier, ids []string, lines costLines) (map[string]*extra, error) {
	out := map[string]*extra{}
	rows, err := db.Query(ctx, `SELECT a.id, a.evidence_status, a.payment_status, a.meeting_kind, cd.name, ed.name, a.end_date,
  a.pl_review_note, s.current_fy_ssa_status, a.activity_name_snapshot
FROM activity a LEFT JOIN cluster c ON c.id = a.cluster_id LEFT JOIN district cd ON cd.id = c.district_id
LEFT JOIN district ed ON ed.id = a.event_district_id LEFT JOIN school s ON s.id = a.school_id WHERE a.id = ANY($1)`, ids)
	if err != nil {
		return nil, fmt.Errorf("myplan: reading the rows' columns: %w", err)
	}
	for rows.Next() {
		var id string
		x := &extra{}
		if err := rows.Scan(&id, &x.evidence, &x.payment, &x.meetingKind, &x.clusterDistrict, &x.eventDistrict, &x.endDate,
			&x.reviewNote, &x.schoolSSAStatus, &x.activityName); err != nil {
			rows.Close()
			return nil, fmt.Errorf("myplan: reading the rows' columns: %w", err)
		}
		out[id] = x
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, err
	}
	advs, err := readAdvances(ctx, db, lines)
	if err != nil {
		return nil, err
	}
	for id, x := range out {
		x.advances = advs[id]
	}
	return out, nil
}

// listedIDs are the activities the tables list, by planned date then made
// (qs_period.order_by("planned_date", "created_at")).
func listedIDs(ctx context.Context, db schooldirectory.Querier, owners []string, p Period, f Filters, today time.Time) ([]string, error) {
	b := &sqlb{}
	where := listedWhere(b, owners, p, f, today)
	rows, err := db.Query(ctx, `SELECT a.id `+planFrom+` WHERE `+where+` ORDER BY a.planned_date ASC, a.created_at ASC`, b.args...)
	if err != nil {
		return nil, fmt.Errorf("myplan: reading the listed plan: %w", err)
	}
	defer rows.Close()
	var out []string
	for rows.Next() {
		var id string
		if err := rows.Scan(&id); err != nil {
			return nil, err
		}
		out = append(out, id)
	}
	return out, rows.Err()
}

// unportedRow is why the page with this activity listed is still the
// existing application's, or "".
func unportedRow(a *activity, x *extra, awaiting bool) string {
	switch {
	case str(a.delivery) == "partner":
		return "a partner's delivery (compute_next_action's partner branches)"
	case awaiting:
		return "an SSA visit awaiting scores"
	case str(x.meetingKind) == "training":
		return "a meeting delivering a training"
	}
	return ""
}

// tableOf is the loop's choice of table, or -1 for a table not ported
// (and -2 for none: such work is listed nowhere).
func tableOf(a *activity, slots coreSlots) int {
	r := rules.Rows
	isCore := a.hasSchool && str(a.schoolType) == "core"
	switch {
	case str(a.planningSource) == "manual_work_plan" || in(r.ProgrammeEventTypes, a.activityType):
		return -1
	case a.hasSchool && in(r.ProgrammeSchoolTypes, str(a.schoolType)) && (in(r.VisitTypes, a.activityType) || in(r.TrainingTypes, a.activityType)):
		return tableProgrammeSchool
	case isCore:
		if _, slotted := slots.kind[a.id]; slotted {
			return -1
		}
		if in(r.VisitTypes, a.activityType) {
			return tableCoreVisits
		}
		if in(r.TrainingTypes, a.activityType) {
			return -1
		}
	}
	switch {
	case in(rules.Plan.VisitTypes, a.activityType):
		return tableSchoolVisits
	case in(rules.Plan.TrainingTypes, a.activityType):
		return tableTrainings
	case in(rules.Plan.MeetingTypes, a.activityType):
		if !a.hasCluster {
			return -1
		}
		return tableMeetings
	}
	return -2
}

// ReadPlanTables reads the rows of My Plan's own tables for the plan of
// owners. ok is false when a listed activity needs a part Go does not draw
// yet: the page is the existing application's.
func ReadPlanTables(ctx context.Context, db schooldirectory.Querier, place *registry.Work, owners []string, p Period, f Filters, now time.Time) (PlanTablesResult, bool, error) {
	var res PlanTablesResult
	ids, err := listedIDs(ctx, db, owners, p, f, now)
	if err != nil || len(ids) == 0 {
		return res, err == nil, err
	}
	acts, err := readActivities(ctx, db, ids)
	if err != nil {
		return res, false, err
	}
	pg, err := readPage(ctx, db, place, acts, now)
	if err != nil {
		return res, false, err
	}
	extras, err := readExtras(ctx, db, ids, pg.lines)
	if err != nil {
		return res, false, err
	}
	marks, known, err := dayOffMarks(ctx, db, acts, extras)
	if err != nil || !known {
		return res, false, err
	}
	var all []*planRow
	core := false
	for _, a := range acts {
		x := extras[a.id]
		table := tableOf(a, pg.slots)
		// Work in no table still reaches the attention cards; whether it
		// awaits SSA scores shows only in a row.
		if x == nil || table == -1 || unportedRow(a, x, table >= 0 && pg.awaiting[a.id]) != "" {
			return res, false, nil
		}
		if a.hasSchool && str(a.schoolType) == "core" {
			core = true
		}
		isCore := table == tableCoreVisits
		next, known := computeNextAction(a, x, x.advances, pg.today)
		if !known {
			return res, false, nil
		}
		r := &planRow{row: pg.newRow(a, isCore), x: *x, table: table, inTable: table >= 0, next: next}
		r.tone = baseTone(a, r.statusLabel, isCore)
		if r.awaitingSSA {
			// Delivered, waiting for its school's SSA (visit_scores): its
			// action is the SSA drawer, its pill amber. Only a row in no
			// table reaches here (a table's is passed above).
			r.tone = "amber"
			r.next = nextAction{rules.Rows.EnterSSAText, "ssa", "/schools/" + str(a.schoolPK) + "/ssa-entry?activity=" + a.id, "SSA scores not entered"}
			next = r.next
		}
		if m, ok := marks[a.id]; ok {
			r.dayOff = &m
			res.dayOff = append(res.dayOff, r)
		}
		if in(rules.Tables.FinancePendingPaymentStatuses, str(x.payment)) {
			res.finance = append(res.finance, r)
		}
		switch {
		case in(rules.Plan.ReturnedStatuses, a.status):
			res.returned = append(res.returned, r)
		case onWaitingCard(a, x, next, x.advances, pg.today):
			res.waiting = append(res.waiting, r)
		}
		if table == -2 {
			continue
		}
		all = append(all, r)
		switch table {
		case tableSchoolVisits:
			res.visits = append(res.visits, r)
		case tableMeetings:
			res.meetings = append(res.meetings, r)
		case tableTrainings:
			res.trainings = append(res.trainings, r)
		case tableProgrammeSchool:
			if res.programme == nil {
				res.programme = map[string][]*planRow{}
			}
			res.programme[str(a.schoolType)] = append(res.programme[str(a.schoolType)], r)
		default:
			res.core = append(res.core, r)
		}
	}
	// The loop over Core slots names its variable `status` and so leaves the
	// last slot's status in the Status filter (25.3): shown as "all" when no
	// slot's status is one of the select's values; otherwise which slot is
	// last is the table's order, which Go does not read.
	if core && len(pg.slots.statuses) > 0 {
		for _, s := range pg.slots.statuses {
			if s != nil && in(statusOptions, *s) {
				return res, false, nil
			}
		}
		res.statusShown, res.overwritten = "all", true
	}
	plain := func(rows []*planRow) []*row {
		out := make([]*row, len(rows))
		for i, r := range rows {
			out[i] = r.row
		}
		return out
	}
	expanded, ok, err := expandTrainings(ctx, db, pg, &res)
	if err != nil || !ok {
		return res, false, err
	}
	all = append(all, expanded...)
	visits, meetings, coreRows := plain(res.visits), plain(res.meetings), plain(res.core)
	tables := [][]*row{visits, meetings, coreRows}
	kinds := rules.Rows.ProgrammeSchoolTypes
	for _, kind := range kinds {
		tables = append(tables, plain(res.programme[kind]))
	}
	trainingRows, groupRows := plain(res.trainings), plain(res.group)
	tables = append(tables, trainingRows, groupRows)
	if err := pg.finish(ctx, db, acts, tables...); err != nil {
		return res, false, err
	}
	byRow := map[*row]*planRow{}
	for _, r := range all {
		byRow[r.row] = r
	}
	reorder := func(rows []*row) []*planRow {
		out := make([]*planRow, len(rows))
		for i, r := range rows {
			out[i] = byRow[r]
		}
		return out
	}
	res.visits, res.meetings, res.core = reorder(visits), reorder(meetings), reorder(coreRows)
	res.trainings, res.group = reorder(trainingRows), reorder(groupRows)
	for i, kind := range kinds {
		if rows := tables[3+i]; len(rows) > 0 {
			res.programme[kind] = reorder(rows)
		}
	}
	for _, rows := range [][]*planRow{res.visits, res.meetings, res.core, res.trainings, res.group} {
		if len(rows) > planTablePageSize {
			return res, false, nil
		}
		for _, r := range rows {
			r.settle(pg.today)
		}
	}
	for _, card := range [][]*planRow{res.dayOff, res.returned, res.waiting, res.finance} {
		if len(card) > planTablePageSize {
			return res, false, nil
		}
	}
	for _, rows := range res.programme {
		if len(rows) > programmePageSize {
			return res, false, nil
		}
		for _, r := range rows {
			r.settle(pg.today)
		}
	}
	return res, true, nil
}

// settle is the pass after the loop for one row: its tint, its District,
// the Status the completion columns leave and its tick box.
func (r *planRow) settle(today time.Time) {
	a := r.a
	switch {
	case officerCompleted(a.status):
		r.rowState = "done"
	case in(rules.Tables.NeverOverdue, a.status):
	default:
		if d := planDay(a.plannedDate, a.scheduledDate); d != nil && d.Before(today) {
			r.rowState = "overdue"
		}
	}
	switch r.statusLabel {
	case rules.Rows.MissingSF, rules.Rows.MissingEvidence, rules.Rows.MissingBoth:
		r.tone = "amber"
	case rules.Rows.FinishedEarly:
		r.tone = "green"
	}
	r.showsComplete = r.isComplete && in(rules.Plan.CompletedWorkStatuses, a.status)
	r.canPick = !in(rules.Tables.Untickable, a.status) && !r.showsComplete
	r.districtShown = r.plannedDistrict()
}

// plannedDistrict is plan_row_district: the school's district for school
// work, the cluster's for a cluster session, the other when that is blank.
func (r *planRow) plannedDistrict() string {
	blank := func(v string) bool { return v == "" || v == dash || v == "Unknown" }
	school := r.schoolDistrict
	if !r.a.hasSchool && !r.isClusterInvited {
		school = "Unknown"
		if isSet(r.a.eventDistrictID) {
			school = str(r.x.eventDistrict)
		}
	}
	first, second := school, r.clusterDistrict()
	if !r.schoolID.truthy() && !r.isClusterInvited {
		first, second = second, first
	}
	for _, v := range []string{first, second} {
		if !blank(v) {
			return v
		}
	}
	return dash
}

// clusterDistrict is the row's "cluster_district": the cluster's district,
// else the school's, else "—".
func (r *planRow) clusterDistrict() string {
	a := r.a
	name := ""
	switch {
	case a.hasCluster && isSet(a.clusterDistrictID):
		name = str(r.x.clusterDistrict)
	case a.hasSchool && isSet(a.schoolDistrictID):
		name = str(a.schoolDistrictName)
	}
	return orDash(name)
}

// baseTone is plan_row_tone over get_activity_status_label_and_class's
// class (status_tone): completed work green; a Core school's work blue
// unless sent back or awaiting its owner; planned labels blue; else the
// class's colour.
func baseTone(a *activity, label string, isCore bool) string {
	if in(rules.Plan.CompletedWorkStatuses, a.status) {
		return "green"
	}
	if isCore {
		switch {
		case in(rules.Plan.ReturnedStatuses, a.status):
			return "red"
		case a.status == "awaiting_owner_approval":
			return "amber"
		}
		return "blue"
	}
	switch label {
	case "Scheduled", "This Week":
		return "blue"
	case rules.Rows.CompleteLabel:
		return "green"
	case "Awaiting owner approval", "Activity ID Missing", "Due Today":
		return "amber"
	case "Returned for Correction":
		return "red"
	}
	return "slate"
}

// actions is activity_row.html as the feed reads it: only buttons with an
// hx-get reach the app, in order.
func (r *planRow) actions() *screensv1.PageCell {
	a := r.a
	cell := &screensv1.PageCell{}
	drawer := func(key, label, href string, primary bool) *screensv1.PageAction {
		return &screensv1.PageAction{Key: key, Label: label, Primary: primary, Enabled: true, Href: href, Drawer: true}
	}
	if r.showsComplete {
		done := drawer("button", "Complete", "/my-plan/"+a.id, true)
		done.Reason = "View Completed Activity"
		cell.Actions = append(cell.Actions, done)
		return cell
	}
	cell.Actions = append(cell.Actions, drawer("menu", "View Details", "/my-plan/"+a.id, false))
	if str(a.delivery) != "staff" {
		// Not the reader's to deliver: read-only monitoring.
		cell.Text = "Monitoring — partner-owned"
	} else {
		if a.status != "completed" {
			cell.Actions = append(cell.Actions, drawer("menu", "Reschedule Activity", "/my-plan/"+a.id+"/reschedule-drawer", false))
		}
		if in(rules.Tables.FacilitatorTypes, a.activityType) && in(rules.Tables.FacilitatorEditableStatuses, a.status) {
			cell.Actions = append(cell.Actions, drawer("menu", "Change Facilitator", "/activities/"+a.id+"/facilitator", false))
		}
		if a.status == "scheduled" || a.status == "partner_scheduled" || a.status == "assigned_to_partner" {
			cell.Actions = append(cell.Actions, drawer("menu", "Start Activity", "/activities/"+a.id+"/start", false))
		}
		if a.status != "completed" {
			cell.Actions = append(cell.Actions, drawer("menu", "Complete Activity", "/my-plan/"+a.id+"/complete-drawer", false))
		}
		if r.next.action == "submit" {
			cell.Actions = append(cell.Actions, drawer("menu", "Submit for Review", "/activities/"+a.id+"/submit", false))
		}
	}
	switch a.status {
	case "completed", "cancelled", "ia_verified", "accountant_confirmed", "closed":
	default:
		cell.Actions = append(cell.Actions, drawer("danger", "Cancel Activity", "/my-plan/"+a.id+"/cancel-drawer", false))
	}
	return cell
}

// dayOffMarks is day_off_marks over the listed activities: the days each
// runs on (activity_span: its plan day to its end date, when that is
// later). known is false when a day is in a year the national calendar
// does not hold.
func dayOffMarks(ctx context.Context, db schooldirectory.Querier, acts []*activity, extras map[string]*extra) (map[string]calendarpage.DayOffMark, bool, error) {
	var work []calendarpage.DayOffWork
	for _, a := range acts {
		start := planDay(a.plannedDate, a.scheduledDate)
		if start == nil {
			continue
		}
		end := *start
		if x := extras[a.id]; x != nil && x.endDate != nil {
			if e := date(x.endDate); e.After(end) {
				end = *e
			}
		}
		work = append(work, calendarpage.DayOffWork{ID: a.id, Status: a.status, StaffID: str(a.staffID), Start: *start, End: end})
	}
	return calendarpage.DayOffMarks(ctx, db, work)
}

// expandTrainings is the cluster invited-school expansion over the
// Trainings table: each session (a training at a cluster with no School ID)
// is copied once to Group Trainings, then replaced on Trainings by a row
// for each client school it reached (or by itself at the cluster when it
// reached none); a programme school's row moves to that school type's
// section. The session's own row stays on the cards only (no tick, no
// completion columns). ok is false when a session reached a Core School:
// its row is a Core School Trainings row, still the existing
// application's. It returns the new rows.
func expandTrainings(ctx context.Context, db schooldirectory.Querier, pg *page, res *PlanTablesResult) ([]*planRow, bool, error) {
	if len(res.trainings) == 0 {
		return nil, true, nil
	}
	plain := make([]*row, len(res.trainings))
	for i, r := range res.trainings {
		plain[i] = r.row
	}
	reached, err := pg.expandSessions(ctx, db, plain)
	if err != nil {
		return nil, false, err
	}
	clone := func(r *planRow, c *row) *planRow {
		return &planRow{row: c, x: r.x, table: r.table, tone: r.tone, dayOff: r.dayOff, inTable: true, next: r.next}
	}
	var made, rebuilt []*planRow
	for _, r := range res.trainings {
		reaches, session := reached[r.row]
		if !session {
			rebuilt = append(rebuilt, r)
			continue
		}
		r.inTable = false
		group := clone(r, r.copy())
		res.group = append(res.group, group)
		made = append(made, group)
		for _, x := range reaches {
			c := clone(r, x.row)
			switch {
			case x.school == nil:
				rebuilt = append(rebuilt, c)
			case in(rules.Rows.ProgrammeSchoolTypes, x.school.schoolType):
				c.table = tableProgrammeSchool
				if res.programme == nil {
					res.programme = map[string][]*planRow{}
				}
				res.programme[x.school.schoolType] = append(res.programme[x.school.schoolType], c)
			case x.school.schoolType == "core":
				return nil, false, nil
			default:
				rebuilt = append(rebuilt, c)
			}
			made = append(made, c)
		}
	}
	res.trainings = rebuilt
	return made, true, nil
}
