package myplan

import (
	"bytes"
	"context"
	"encoding/csv"
	"errors"
	"fmt"
	"net/url"
	"slices"
	"strconv"
	"strings"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/budgetpage"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/costing"
	registry "github.com/O-Mario88/edify-planning-tool/platform/backend/internal/country"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pagegate"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/workbook"
)

// qget is request.GET.get: the last value, trimmed.
func qget(q url.Values, key string) string {
	vs := q[key]
	if len(vs) == 0 {
		return ""
	}
	return strings.TrimSpace(vs[len(vs)-1])
}

// exportFormat is _export_format: "csv" or "xlsx" when this request is an
// export, else "".
func exportFormat(q url.Values) string {
	export := strings.ToLower(qget(q, "export"))
	if f := strings.ToLower(qget(q, "format")); export == "" && (f == "xlsx" || f == "excel") {
		export = "xlsx"
	}
	switch export {
	case "csv":
		return "csv"
	case "xlsx", "excel":
		return "xlsx"
	}
	for _, key := range rules.ExportPeriodKeys {
		if q.Has(key) {
			return "xlsx"
		}
	}
	return ""
}

// month1to12 is a month field read as _period_filters reads it.
func month1to12(raw string) (int, bool) {
	if raw == "" || strings.Trim(raw, "0123456789") != "" {
		return 0, false
	}
	n, err := strconv.Atoi(raw)
	return n, err == nil && n >= 1 && n <= 12
}

// monthRange is fy.month_range_to_dates: the first day of from to the last
// of to, in the year's order.
func monthRange(fy, from, to int) (time.Time, time.Time) {
	order := []int{10, 11, 12, 1, 2, 3, 4, 5, 6, 7, 8, 9}
	if slices.Index(order, from) > slices.Index(order, to) {
		from, to = to, from
	}
	year := func(m int) int {
		if m >= 10 {
			return fy - 1
		}
		return fy
	}
	start := time.Date(year(from), time.Month(from), 1, 0, 0, 0, 0, time.UTC)
	end := time.Date(year(to), time.Month(to)+1, 0, 0, 0, 0, 0, time.UTC)
	return start, end
}

// exportBounds is _period_filters then export_period_bounds: the first and
// last day an export covers, the drawer's months or dates, else the year.
func exportBounds(q url.Values, fy int) (time.Time, time.Time) {
	start, last, _ := DrawerPeriod(q, fy)
	return start, last
}

// DrawerPeriod is _period_filters' custom period: the first and last day
// the Export options drawer chose (its months, its dates, or the full
// year), custom true; otherwise the whole year and custom false.
func DrawerPeriod(q url.Values, fy int) (time.Time, time.Time, bool) {
	fyStart := time.Date(fy-1, 10, 1, 0, 0, 0, 0, time.UTC)
	fyLast := time.Date(fy, 9, 30, 0, 0, 0, 0, time.UTC)
	kind := strings.ToLower(qget(q, "period_type"))
	if kind != "month_range" && kind != "custom_dates" && kind != "fy" {
		kind = ""
	}
	from, hasFrom := month1to12(qget(q, "from_month"))
	to, hasTo := month1to12(qget(q, "to_month"))
	rawStart, rawEnd := qget(q, "start_date"), qget(q, "end_date")
	months := kind == "month_range" || (kind == "" && hasFrom && hasTo)
	dates := kind == "custom_dates" || (kind == "" && !months && rawStart != "" && rawEnd != "")
	switch {
	case months:
		var s, e time.Time
		switch {
		case hasFrom && hasTo:
			s, e = monthRange(fy, from, to)
		case hasFrom:
			s, e = monthRange(fy, from, from)
		default:
			s, e = monthRange(fy, 10, 9)
		}
		return s, e, true
	case dates:
		s, err1 := time.Parse("2006-1-2", rawStart)
		e, err2 := time.Parse("2006-1-2", rawEnd)
		if err1 == nil && err2 == nil {
			if s.After(e) {
				s, e = e, s
			}
			return s, e, true
		}
		return fyStart, fyLast, false
	case kind == "fy":
		return fyStart, fyLast, true
	}
	return fyStart, fyLast, false
}

// ReadKindOrTab is export_kinds.read_kind_or_tab: the drawer's kind when it
// sent one, else the page's activity tab, else everything.
func ReadKindOrTab(q url.Values) string {
	if qget(q, "activity_type") != "" {
		return readKind(q)
	}
	if kind, ok := rules.TableExport.TabKinds[strings.ToLower(qget(q, "activity"))]; ok {
		return kind
	}
	return "all"
}

// IsExportKind is whether value is one of export_kinds.KINDS.
func IsExportKind(value string) bool {
	_, ok := rules.TableExport.KindTypes[value]
	return ok || value == "all"
}

// KeepsKind is export_kinds.keeps for an activity of this type, online or not.
func KeepsKind(kind, activityType string, online bool) bool {
	return keepsKind(kind, activityType, online)
}

// readKind is export_kinds.read_kind: the drawer's Activity Type, the whole
// plan for a blank or unknown one.
func readKind(q url.Values) string {
	kind := strings.ToLower(qget(q, "activity_type"))
	if _, ok := rules.TableExport.KindTypes[kind]; ok {
		return kind
	}
	return "all"
}

// keepsStatus is export_kinds.keeps_status.
func keepsStatus(choice, status string) bool {
	done := in(rules.TableExport.CompletedWorkStatuses, status)
	switch choice {
	case "completed":
		return done
	case "scheduled", "in_progress":
		return !done
	}
	return true
}

// keepsKind is export_kinds.keeps.
func keepsKind(kind, activityType string, online bool) bool {
	types, ok := rules.TableExport.KindTypes[kind]
	if !ok {
		return true
	}
	if !in(types, activityType) {
		return false
	}
	if kind == rules.TableExport.OnlineKind {
		return online
	}
	return true
}

// chosenDay is an exported activity with the day the Budget sheet reads.
type chosenDay struct {
	id  string
	day *time.Time
}

// chooseActivities is _my_plan_export's choice: the reader's plan of the
// year (the closed work kept, nothing the page sets aside), on a day within
// the bounds or undated, of the Plan Status and the Activity Type asked.
func chooseActivities(ctx context.Context, db schooldirectory.Querier, owners []string, fy string, start, end time.Time,
	status, kind string) ([]chosenDay, error) {
	b := &sqlb{}
	aside := []string{}
	for _, s := range rules.Plan.ExcludedStatuses {
		if s != "closed" {
			aside = append(aside, s)
		}
	}
	where := planWhereOf(b, PlanOf{Owners: owners}, fy, Filters{}, "") + " AND " + notStatusIn(b, aside)
	rows, err := db.Query(ctx, `SELECT a.id, COALESCE(a.status, ''), COALESCE(a.activity_type, ''),
  COALESCE(a.programme_delivery_mode, ''), a.planned_date, a.scheduled_date `+planFrom+` WHERE `+where, b.args...)
	if err != nil {
		return nil, fmt.Errorf("myplan: choosing the export's activities: %w", err)
	}
	defer rows.Close()
	var out []chosenDay
	for rows.Next() {
		var id, st, typ, mode string
		var planned, scheduled *time.Time
		if err := rows.Scan(&id, &st, &typ, &mode, &planned, &scheduled); err != nil {
			return nil, fmt.Errorf("myplan: choosing the export's activities: %w", err)
		}
		day := planned
		if day == nil && scheduled != nil {
			u := scheduled.UTC()
			d := time.Date(u.Year(), u.Month(), u.Day(), 0, 0, 0, 0, time.UTC)
			day = &d
		}
		if day != nil && (day.Before(start) || day.After(end)) {
			continue
		}
		if !keepsStatus(status, st) || !keepsKind(kind, typ, mode == rules.TableExport.OnlineMode) {
			continue
		}
		out = append(out, chosenDay{id: id, day: day})
	}
	return out, rows.Err()
}

// ExportFile is my_plan_view's export (_my_plan_export): the reader's plan
// as My Plan's tables, a sheet each, then the Budget of exactly those
// activities, as my_plan_export.xlsx; or the tables as one CSV. handled is
// false for a request that is not an export and for a plan whose rows Go
// does not draw yet.
func (s *Service) ExportFile(ctx context.Context, p auth.Principal, query url.Values) (string, []byte, bool, error) {
	format := exportFormat(query)
	if format == "" {
		return "", nil, false, nil
	}
	door, ok := rules.Doors[p.ActiveRole]
	if !ok || !door.Page {
		return "", nil, true, pagegate.ErrNotAvailable
	}
	now := s.now()
	fy := qget(query, "fy")
	if fy == "" {
		fy = schooldirectory.OperationalFY(now)
	}
	fyN, err := strconv.Atoi(fy)
	if err != nil {
		return "", nil, false, nil
	}
	start, end := exportBounds(query, fyN)
	kind := readKind(query)
	chosen, err := chooseActivities(ctx, s.db, ownerIDs(p), fy, start, end, strings.ToLower(qget(query, "status")), kind)
	if err != nil {
		return "", nil, true, err
	}
	ids := make([]string, len(chosen))
	for i, c := range chosen {
		ids[i] = c.id
	}
	sheets, ported, err := TableSheets(ctx, s.db, p.Country, ids, kind, now, false)
	if errors.Is(err, ErrUnported) {
		return "", nil, false, nil
	}
	if err != nil || !ported {
		return "", nil, ported, err
	}
	if format == "csv" {
		body, err := TablesCSV(sheets)
		return "my_plan_export.csv", body, true, err
	}
	budget, err := budgetpage.CostPlanSheet(ctx, s.db, rules.TableExport.BudgetSheet, ids, periodLine(chosen))
	if err != nil {
		return "", nil, true, err
	}
	var buf bytes.Buffer
	if err := workbook.Write(&buf, append(sheets, budget)); err != nil {
		return "", nil, true, err
	}
	return "my_plan_export.xlsx", buf.Bytes(), true, nil
}

// periodLine is budget_sheet's "Period: 1 Oct 2026 – 30 Sep 2027" over the
// exported activities' days.
func periodLine(chosen []chosenDay) string {
	var days []time.Time
	for _, c := range chosen {
		if c.day != nil {
			days = append(days, *c.day)
		}
	}
	if len(days) == 0 {
		return ""
	}
	slices.SortFunc(days, func(a, b time.Time) int { return a.Compare(b) })
	f := func(t time.Time) string { return strconv.Itoa(t.Day()) + " " + t.Format("Jan 2006") }
	return "Period: " + f(days[0]) + " – " + f(days[len(days)-1])
}

// TableSheets is table_export.workbook: the sheets of My Plan's tables for
// these activities that kind gives, in the page's order. ported is false
// for rows Go does not draw yet.
func TableSheets(ctx context.Context, db schooldirectory.Querier, place *registry.Work, ids []string, kind string,
	now time.Time, plannedIDs bool) ([]workbook.Sheet, bool, error) {
	t := rules.TableExport
	var res PlanTablesResult
	if len(ids) > 0 {
		var ok bool
		var err error
		if res, ok, err = planTablesFor(ctx, db, place, ids, now, true); err != nil || !ok {
			return nil, ok, err
		}
	}
	keys, ok := t.KindTables[kind]
	if !ok {
		keys = t.AllSheets
	}
	tables := map[string][]*planRow{
		"school_visits": res.visits, "cluster_trainings": res.trainings, "group_trainings": res.group,
		"cluster_meetings": res.meetings, "core_school_visits": res.core, "core_school_trainings": res.coreTrainings,
		"programme_activities": res.programmeActivities,
	}
	var out []workbook.Sheet
	for _, key := range keys {
		switch key {
		case "programme_school_work":
			for _, typ := range rules.Rows.ProgrammeSchoolTypes {
				if rows := res.programme[typ]; len(rows) > 0 {
					title := strings.ReplaceAll(t.ProgrammeTitle, "{label}", t.SchoolTypeLabels[typ])
					out = append(out, sheetOf(title, key, rows, false, plannedIDs))
				}
			}
		case "meeting_schools":
			rows, err := meetingSchoolRows(ctx, db, place, res.meetings)
			if err != nil {
				return nil, true, err
			}
			out = append(out, sheetOf(t.MeetingSchoolsTitle, key, rows, false, plannedIDs))
		default:
			rows := tables[key]
			if key == "group_trainings" {
				var err error
				if rows, err = groupFigures(ctx, db, rows); err != nil {
					return nil, true, err
				}
			}
			out = append(out, sheetOf(t.Titles[key], key, rows, in(t.ShortDays, key), plannedIDs))
		}
	}
	return out, true, nil
}

// TablesCSV is table_export.csv_rows through safe_csv_writer: each sheet's
// name, its headings and its rows (a day as "5 Oct 2026"), a blank line
// between.
func TablesCSV(sheets []workbook.Sheet) ([]byte, error) {
	var buf bytes.Buffer
	w := csv.NewWriter(&buf)
	w.UseCRLF = true
	write := func(cells []workbook.Cell) error { return w.Write(workbook.SafeCSVRow(cells)) }
	for _, sh := range sheets {
		if err := write([]workbook.Cell{txt(sh.Title)}); err != nil {
			return nil, err
		}
		heads := make([]workbook.Cell, len(sh.Headers))
		for i, h := range sh.Headers {
			heads[i] = txt(h)
		}
		if err := write(heads); err != nil {
			return nil, err
		}
		for _, row := range sh.Rows {
			cells := make([]workbook.Cell, len(row))
			for i, c := range row {
				cells[i] = c
				if d, ok := c.DateValue(); ok {
					cells[i] = txt(strconv.Itoa(d.Day()) + " " + d.Format("Jan 2006"))
				}
			}
			if err := write(cells); err != nil {
				return nil, err
			}
		}
		if err := write(nil); err != nil {
			return nil, err
		}
	}
	w.Flush()
	return buf.Bytes(), w.Error()
}

// groupFigures is table_export._session_figures over plan_export
// .session_figures: a group training's people are those its invited
// schools bring, and its Cost its meals, venue and facilitation lines.
func groupFigures(ctx context.Context, db schooldirectory.Querier, rows []*planRow) ([]*planRow, error) {
	if len(rows) == 0 {
		return rows, nil
	}
	ids := make([]string, 0, len(rows))
	for _, r := range rows {
		ids = append(ids, r.a.id)
	}
	clusters := map[string]string{}
	res, err := db.Query(ctx, `SELECT id, cluster_id FROM activity WHERE id = ANY($1) AND cluster_id IS NOT NULL`, ids)
	if err != nil {
		return nil, fmt.Errorf("myplan: reading the trainings' clusters: %w", err)
	}
	for res.Next() {
		var id, cluster string
		if err := res.Scan(&id, &cluster); err != nil {
			res.Close()
			return nil, err
		}
		clusters[id] = cluster
	}
	res.Close()
	if err := res.Err(); err != nil {
		return nil, err
	}
	heads, err := invitedHeadCounts(ctx, db, clusters)
	if err != nil {
		return nil, err
	}
	costs := map[string]int64{}
	res, err = db.Query(ctx, `SELECT activity_id, COALESCE(line_item_type, ''), COALESCE(cost_setting_key, ''), COALESCE(amount, 0)
FROM activity_schedule_cost_line WHERE activity_id = ANY($1)`, ids)
	if err != nil {
		return nil, fmt.Errorf("myplan: reading the trainings' cost lines: %w", err)
	}
	for res.Next() {
		var id, kind, key string
		var amount int64
		if err := res.Scan(&id, &kind, &key, &amount); err != nil {
			res.Close()
			return nil, err
		}
		if kind == "" {
			kind = costing.LineItemType(key)
		}
		if in(rules.TableExport.GroupTrainingCostTypes, kind) {
			costs[id] += amount
		}
	}
	res.Close()
	if err := res.Err(); err != nil {
		return nil, err
	}
	out := make([]*planRow, len(rows))
	for i, r := range rows {
		c := *r
		c.row = r.row.copy()
		if n, ok := heads[r.a.id]; ok {
			c.expected = &n
		}
		if amount, ok := costs[r.a.id]; ok {
			c.budgetTotal = &amount
		}
		out[i] = &c
	}
	return out, nil
}

// invite is one invitation's people (teachers, leaders, other), nil where
// not given.
type invite struct{ teachers, leaders, other *int }

func (v invite) given() bool { return v.teachers != nil || v.leaders != nil || v.other != nil }
func (v invite) sum() int {
	n := 0
	for _, p := range []*int{v.teachers, v.leaders, v.other} {
		if p != nil {
			n += *p
		}
	}
	return n
}

// session is what a cluster session's head count reads of the activity.
type session struct {
	perSchool, expected int
}

func readSessions(ctx context.Context, db schooldirectory.Querier, ids []string) (map[string]session, error) {
	out := map[string]session{}
	rows, err := db.Query(ctx, `SELECT id, COALESCE(NULLIF(participants_per_school, 0), teachers_per_school, 0),
  COALESCE(expected_participants, 0) FROM activity WHERE id = ANY($1)`, ids)
	if err != nil {
		return nil, fmt.Errorf("myplan: reading the sessions: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var id string
		var s session
		if err := rows.Scan(&id, &s.perSchool, &s.expected); err != nil {
			return nil, err
		}
		out[id] = s
	}
	return out, rows.Err()
}

// invitedHeadCounts is cluster_attendance.invited_head_counts: the people
// each cluster session's invited schools bring; a session nobody is
// invited to reads its head count, or its per-school figure across the
// cluster's schools.
func invitedHeadCounts(ctx context.Context, db schooldirectory.Querier, clusterOf map[string]string) (map[string]int, error) {
	out := map[string]int{}
	if len(clusterOf) == 0 {
		return out, nil
	}
	ids, clusters := []string{}, []string{}
	for id, c := range clusterOf {
		ids = append(ids, id)
		if c != "" {
			clusters = append(clusters, c)
		}
	}
	sessions, err := readSessions(ctx, db, ids)
	if err != nil {
		return nil, err
	}
	members := map[string]int{}
	rows, err := db.Query(ctx, `SELECT cluster_id, COUNT(*) FROM school WHERE cluster_id = ANY($1) AND deleted_at IS NULL GROUP BY cluster_id`, clusters)
	if err != nil {
		return nil, fmt.Errorf("myplan: counting the clusters' schools: %w", err)
	}
	for rows.Next() {
		var c string
		var n int
		if err := rows.Scan(&c, &n); err != nil {
			rows.Close()
			return nil, err
		}
		members[c] = n
	}
	rows.Close()
	invites := map[string][]invite{}
	rows, err = db.Query(ctx, `SELECT activity_id, teachers, leaders, other FROM cluster_activity_attendance
WHERE activity_id = ANY($1) AND invited`, ids)
	if err != nil {
		return nil, fmt.Errorf("myplan: reading the sessions' invitations: %w", err)
	}
	for rows.Next() {
		var id string
		var v invite
		if err := rows.Scan(&id, &v.teachers, &v.leaders, &v.other); err != nil {
			rows.Close()
			return nil, err
		}
		invites[id] = append(invites[id], v)
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, err
	}
	for id, cluster := range clusterOf {
		s := sessions[id]
		invited := invites[id]
		switch {
		case len(invited) > 0:
			if s.perSchool == 0 && !slices.ContainsFunc(invited, invite.given) {
				out[id] = s.expected
				continue
			}
			n := 0
			for _, v := range invited {
				if v.given() {
					n += v.sum()
				} else {
					n += s.perSchool
				}
			}
			out[id] = n
		case cluster != "":
			if s.expected != 0 {
				out[id] = s.expected
			} else {
				out[id] = s.perSchool * members[cluster]
			}
		}
	}
	return out, nil
}

// ReadExportKind is export_kinds.read_kind: the drawer's Activity Type, the
// whole plan for a blank or unknown one.
func ReadExportKind(q url.Values) string { return readKind(q) }

// KeepsStatus is export_kinds.keeps_status.
func KeepsStatus(choice, status string) bool { return keepsStatus(choice, status) }
