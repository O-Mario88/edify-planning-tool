package planningoversight

import (
	"context"
	"fmt"
	"net/url"
	"slices"
	"strconv"
	"strings"
	"time"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/partneroversight"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/stafflogs"
)

// periodDays is coverage_service._period_days: the period's first and last
// day, a whole year read to the last year of the horizon.
func periodDays(per partneroversight.Period, years []string) (time.Time, time.Time) {
	fy, _ := strconv.Atoi(per.FY)
	switch per.Kind {
	case "week":
		start := weekStart(per.Week)
		return start, start.AddDate(0, 0, 6)
	case "month":
		year := fy
		if per.Month >= 10 {
			year--
		}
		start := time.Date(year, time.Month(per.Month), 1, 0, 0, 0, 0, time.UTC)
		return start, start.AddDate(0, 1, -1)
	case "quarter":
		n, _ := strconv.Atoi(strings.TrimPrefix(per.Quarter, "Q"))
		start := time.Date(fy-1, time.October, 1, 0, 0, 0, 0, time.UTC).AddDate(0, 3*(n-1), 0)
		return start, start.AddDate(0, 3, -1)
	}
	start := time.Date(fy-1, time.October, 1, 0, 0, 0, 0, time.UTC)
	end := time.Date(fy, time.September, 30, 0, 0, 0, 0, time.UTC)
	if len(years) > 1 {
		last, _ := strconv.Atoi(years[len(years)-1])
		end = time.Date(last, time.September, 30, 0, 0, 0, 0, time.UTC)
	}
	return start, end
}

// windowSQL is school_status._period_filter's dated part over activities
// aliased x: planned in [$s, $e], else scheduled on a day in it.
func windowSQL(s, e string) string {
	return "((x.planned_date BETWEEN " + s + " AND " + e + ") OR (x.planned_date IS NULL AND " +
		"(x.scheduled_date AT TIME ZONE '" + kampala + "')::date BETWEEN " + s + " AND " + e + "))"
}

// trainingCoverage is coverage_service.training_coverage over the reader's
// operating schools (scoping.scoped_school_queryset).
func (s *Service) trainingCoverage(ctx context.Context, scope schooldirectory.Scope, per partneroversight.Period, years []string) (coverageState, error) {
	c := rules.TeamPlan.Coverage
	start, end := periodDays(per, years)
	st := coverageState{periodStart: start, periodEnd: end}
	args := []any{c.ClusterSessionTypes, years, c.DeadStatuses, start, end, c.SchoolTrainingTypes, c.OperatingStatuses}
	reach := schooldirectory.AnalyticsReach(scope, &args)
	args = append(args, c.TrainedTypes)
	trained := "$" + strconv.Itoa(len(args))
	base := `
WITH sessions AS (
  SELECT x.id FROM activity x WHERE x.activity_type = ANY($1) AND x.deleted_at IS NULL AND x.fy = ANY($2)
    AND (x.status IS NULL OR NOT x.status = ANY($3)) AND ` + windowSQL("$4::date", "$5::date") + `
), scoped AS (
  SELECT s.id, COALESCE(s.school_id, '') AS code, COALESCE(s.name, '') AS name, s.school_type,
    COALESCE(s.account_owner_id, '') AS owner, COALESCE(d.name, '') AS district, COALESCE(s.cluster_id, '') AS cluster,
    EXISTS (SELECT 1 FROM cluster_activity_attendance ca WHERE ca.school_id = s.id AND (ca.invited OR ca.attended)
            AND ca.activity_id IN (SELECT id FROM sessions)) AS has_session,
    EXISTS (SELECT 1 FROM activity x WHERE x.school_id = s.id AND x.activity_type = ANY($6) AND x.cluster_id IS NULL
            AND x.deleted_at IS NULL AND x.fy = ANY($2) AND (x.status IS NULL OR NOT x.status = ANY($3))
            AND ` + windowSQL("$4::date", "$5::date") + `) AS has_in_school
  FROM school s LEFT JOIN district d ON d.id = s.district_id
  WHERE ` + reach + ` AND s.operational_status = ANY($7)
)`
	err := s.db.QueryRow(ctx, base+`
SELECT count(*) FILTER (WHERE has_session),
  count(*) FILTER (WHERE NOT has_session AND NOT has_in_school AND school_type = ANY(`+trained+`)),
  count(*) FILTER (WHERE NOT has_session AND has_in_school) FROM scoped`, args...).Scan(&st.plannedCount, &st.missingCount, &st.inSchoolCount)
	if err != nil {
		return st, fmt.Errorf("planningoversight: counting the schools' training: %w", err)
	}
	page := func(where string, args []any) ([]coverageSchool, error) {
		rows, err := s.db.Query(ctx, base+`
SELECT id, code, name, school_type, owner, district, cluster FROM scoped WHERE `+where+`
ORDER BY name, code LIMIT `+strconv.Itoa(c.RowLimit), args...)
		if err != nil {
			return nil, fmt.Errorf("planningoversight: reading the schools' training: %w", err)
		}
		defer rows.Close()
		out := []coverageSchool{}
		for rows.Next() {
			var sc coverageSchool
			if err := rows.Scan(&sc.pk, &sc.code, &sc.name, &sc.schoolType, &sc.owner, &sc.district, &sc.clusterID); err != nil {
				return nil, fmt.Errorf("planningoversight: reading the schools' training: %w", err)
			}
			out = append(out, sc)
		}
		return out, rows.Err()
	}
	if st.planned, err = page("has_session", args[:len(args)-1]); err != nil {
		return st, err
	}
	if st.missing, err = page("NOT has_session AND NOT has_in_school AND school_type = ANY("+trained+")", args); err != nil {
		return st, err
	}
	st.plannedTruncated, st.missTruncated = st.plannedCount > len(st.planned), st.missingCount > len(st.missing)
	statusFY := ""
	if len(years) == 1 {
		statusFY = per.FY
	}
	all := append(append([]coverageSchool{}, st.planned...), st.missing...)
	if err := s.fillCoverage(ctx, all, statusFY, start, end); err != nil {
		return st, err
	}
	n := len(st.planned)
	st.planned, st.missing = all[:n], all[n:]
	return st, nil
}

// fillCoverage is cluster_training_coverage and visit_statuses for the
// listed schools, with the owners' and clusters' names.
func (s *Service) fillCoverage(ctx context.Context, list []coverageSchool, fy string, start, end time.Time) error {
	if len(list) == 0 {
		return nil
	}
	c := rules.TeamPlan.Coverage
	ids, owners, clusters := []string{}, []string{}, []string{}
	for _, sc := range list {
		ids = append(ids, sc.pk)
		if sc.owner != "" {
			owners = append(owners, sc.owner)
		}
		if sc.clusterID != "" {
			clusters = append(clusters, sc.clusterID)
		}
	}
	fyWhere, args := "", []any{ids, c.ClusterSessionTypes, start, end}
	if fy != "" {
		args = append(args, fy)
		fyWhere = " AND x.fy = $5"
	}
	type session struct {
		status, kind, label, clusterName, delivery, partner string
		day                                                 *time.Time
	}
	linked := map[string][]session{}
	rows, err := s.db.Query(ctx, `
SELECT ca.school_id, COALESCE(x.status, ''), x.activity_type, COALESCE(x.activity_name_snapshot, ''), COALESCE(cl.name, ''),
  COALESCE(x.delivery_type, ''), COALESCE(pt.name, ''), COALESCE(x.planned_date, (x.scheduled_date AT TIME ZONE '`+kampala+`')::date)
FROM cluster_activity_attendance ca JOIN activity x ON x.id = ca.activity_id
LEFT JOIN cluster cl ON cl.id = x.cluster_id LEFT JOIN partner pt ON pt.id = x.assigned_partner_id
WHERE ca.school_id = ANY($1) AND (ca.invited OR ca.attended) AND x.activity_type = ANY($2) AND x.deleted_at IS NULL
  AND `+windowSQL("$3::date", "$4::date")+fyWhere, args...)
	if err != nil {
		return fmt.Errorf("planningoversight: reading the schools' sessions: %w", err)
	}
	for rows.Next() {
		var school string
		var se session
		if err := rows.Scan(&school, &se.status, &se.kind, &se.label, &se.clusterName, &se.delivery, &se.partner, &se.day); err != nil {
			rows.Close()
			return fmt.Errorf("planningoversight: reading the schools' sessions: %w", err)
		}
		linked[school] = append(linked[school], se)
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return err
	}
	visits, err := s.visitStates(ctx, ids, fy, start, end)
	if err != nil {
		return err
	}
	names, err := s.ownerNames(ctx, owners)
	if err != nil {
		return err
	}
	clusterNames := map[string]string{}
	if len(clusters) > 0 {
		rows, err := s.db.Query(ctx, `SELECT id, COALESCE(name, '') FROM cluster WHERE id = ANY($1)`, clusters)
		if err != nil {
			return fmt.Errorf("planningoversight: reading the clusters: %w", err)
		}
		for rows.Next() {
			var id, name string
			if err := rows.Scan(&id, &name); err != nil {
				rows.Close()
				return err
			}
			clusterNames[id] = name
		}
		rows.Close()
	}
	for i := range list {
		sc := &list[i]
		sc.owner = first(names[sc.owner], "Unassigned")
		v := visits[sc.pk]
		sc.visit, sc.visitTone, sc.nextVisit = c.VisitLabels[v.key], c.VisitTones[v.key], v.day
		live := []session{}
		for _, se := range linked[sc.pk] {
			if !slices.Contains(c.DeadStatuses, se.status) {
				live = append(live, se)
			}
		}
		switch {
		case len(live) > 0:
			slices.SortStableFunc(live, func(x, y session) int { return compareDay(x.day, y.day) })
			se := live[0]
			sc.training = "Training Planned"
			if slices.Contains(c.ClusterMeetingTypes, se.kind) {
				sc.training = "Cluster Meeting Planned"
			}
			sc.activityLabel, sc.kind, sc.day, sc.status = se.label, se.kind, se.day, se.status
			sc.delivery, sc.partnerName = se.delivery, se.partner
			sc.clusterName = se.clusterName
		case sc.schoolType != nil && *sc.schoolType != "" && !slices.Contains(c.TrainedTypes, *sc.schoolType):
			sc.training, sc.reason = "No Training Required", c.Reasons["not_required"]
		default:
			sc.training = "No Training Planned"
			switch {
			case sc.clusterID == "":
				sc.reason = c.Reasons["not_clustered"]
			case len(linked[sc.pk]) > 0:
				sc.reason = c.Reasons["canceled"]
				for _, se := range linked[sc.pk] {
					if se.status == "returned" || se.status == "returned_by_ia" || se.status == "returned_by_pl" {
						sc.reason = c.Reasons["returned"]
					}
				}
			default:
				sc.reason = c.Reasons["no_training"]
			}
		}
		if sc.clusterName == "" {
			sc.clusterName = clusterNames[sc.clusterID]
		}
		if sc.activityLabel == "" {
			sc.activityLabel = pyTitle(strings.ReplaceAll(sc.kind, "_", " "))
		}
	}
	return nil
}

type visitState struct {
	key string
	day *time.Time
}

// visitStates is school_status.visit_statuses over the period.
func (s *Service) visitStates(ctx context.Context, ids []string, fy string, start, end time.Time) (map[string]visitState, error) {
	c := rules.TeamPlan.Coverage
	out := map[string]visitState{}
	for _, id := range ids {
		out[id] = visitState{key: "no_visit_planned"}
	}
	fyWhere, args := "", []any{ids, c.VisitTypes, c.PendingApprovalStatuses, start, end}
	if fy != "" {
		args = append(args, fy)
		fyWhere = " AND x.fy = $6"
	}
	rows, err := s.db.Query(ctx, `
SELECT x.school_id, COALESCE(x.status, ''), COALESCE(x.planned_date, (x.scheduled_date AT TIME ZONE '`+kampala+`')::date)
FROM activity x WHERE x.school_id = ANY($1) AND x.activity_type = ANY($2) AND x.deleted_at IS NULL
  AND (x.status IS NULL OR NOT x.status = ANY($3)) AND `+windowSQL("$4::date", "$5::date")+fyWhere, args...)
	if err != nil {
		return nil, fmt.Errorf("planningoversight: reading the schools' visits: %w", err)
	}
	defer rows.Close()
	rank := map[string]int{}
	for rows.Next() {
		var school, status string
		var day *time.Time
		if err := rows.Scan(&school, &status, &day); err != nil {
			return nil, fmt.Errorf("planningoversight: reading the schools' visits: %w", err)
		}
		state := "visit_canceled"
		if !slices.Contains(c.DeadStatuses, status) {
			st, ok := c.VisitStates[status]
			if !ok {
				continue
			}
			state = st
		}
		r := slices.Index(c.VisitPrecedence, state)
		cur, seen := rank[school]
		if !seen || r < cur || (r == cur && day != nil && (out[school].day == nil || day.Before(*out[school].day))) {
			rank[school] = r
			out[school] = visitState{key: state, day: day}
		}
	}
	return out, rows.Err()
}

func plural2(n int, one, many string) string {
	if n == 1 {
		return one
	}
	return many
}

// coveragePage is coverage_workspace.html under the lens strip and the
// period bar.
func coveragePage(w teamPlan, groups []coverageGroup, cov coverageState, lens string, reader Reader, query url.Values) *screensv1.GetPageResponse {
	blocks := []*screensv1.PageBlock{}
	if len(reader.LensTabs) > 0 {
		tabs := []*screensv1.PageLinkTab{}
		for _, t := range reader.LensTabs {
			tabs = append(tabs, &screensv1.PageLinkTab{Label: t.Label, Href: t.Href, Active: strings.HasSuffix(t.Href, "?view=coverage")})
		}
		blocks = append(blocks, &screensv1.PageBlock{Kind: &screensv1.PageBlock_LinkTabs{LinkTabs: &screensv1.PageLinkTabs{Tabs: tabs}}})
	}
	f := teamFilters(w)
	f.GetFilters().Hidden = nil
	blocks = append(blocks, f)

	schools, activities := map[string]bool{}, map[string]bool{}
	for _, g := range groups {
		for _, r := range g.rows {
			if r.schoolID != "" {
				schools[r.schoolID] = true
			}
			activities[r.workKey] = true
		}
	}
	tone := "success"
	if cov.missingCount > 0 {
		tone = "warning"
	}
	line := strconv.Itoa(len(schools)) + " school" + plural2(len(schools), "", "s") + " with planned work in " + w.periodLabel +
		" · " + strconv.Itoa(cov.plannedCount) + " with a cluster training or meeting ·"
	if cov.inSchoolCount > 0 {
		line += " " + strconv.Itoa(cov.inSchoolCount) + " with an in-school training ·"
	}
	line += " " + strconv.Itoa(cov.missingCount) + " with none."
	blocks = append(blocks, panel("", "", &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Text{Text: line}, Tone: tone, Lead: strconv.Itoa(len(schools))}))

	title := "Planned Schools · " + w.periodLabel
	if len(groups) == 0 {
		blocks = append(blocks, panel(title, "", text(coverageEmptyPlanned)))
	} else {
		blocks = append(blocks, panel(title, "", text(strconv.Itoa(len(activities))+" activit"+plural2(len(activities), "y", "ies")+
			" across "+strconv.Itoa(len(schools))+" school"+plural2(len(schools), "", "s"))))
		for _, g := range groups {
			sc, ac := g.schools(), g.activities()
			blocks = append(blocks, &screensv1.PageBlock{Kind: &screensv1.PageBlock_Section{Section: g.label + " · " + strconv.Itoa(sc) +
				" school" + plural2(sc, "", "s") + " · " + strconv.Itoa(ac) + " activit" + plural2(ac, "y", "ies")}})
			rows := []*screensv1.PageRow{}
			for _, r := range g.rows {
				rows = append(rows, r.cells())
			}
			blocks = append(blocks, pagedTable(plannedColumns, rows, query, g.pageParam())...)
		}
	}

	period := dayLong(cov.periodStart) + " and " + dayLong(cov.periodEnd)
	limit := strconv.Itoa(rules.TeamPlan.Coverage.RowLimit)
	note := strconv.Itoa(cov.plannedCount) + " school" + plural2(cov.plannedCount, "", "s") +
		" the planning record attaches to a live cluster session between " + period + "."
	if cov.plannedTruncated {
		note += " The table below holds the first " + limit + " by name; narrow the period or the filters to see the rest."
	}
	blocks = append(blocks, panel("Schools with Planned Cluster Training or Meeting", "", text(note)))
	rows := []*screensv1.PageRow{}
	for _, sc := range cov.planned {
		rows = append(rows, sc.trainedCells())
	}
	blocks = append(blocks, pagedTableOr(trainedColumns, rows, query, "trained_page",
		"No cluster training or meeting is planned for these schools in the selected period.")...)

	note = strconv.Itoa(cov.missingCount) + " active school" + plural2(cov.missingCount, "", "s") + " in your " + strings.ToLower(lens) +
		" scope with no live cluster training, cluster meeting or in-school training in this period. Core, Client, Core Trained and Core Graduate schools are listed: a Champion school takes no training. Closed schools are not counted."
	if cov.missTruncated {
		note += " The table below holds the first " + limit + " by name; narrow the period or the filters to see the rest."
	}
	blocks = append(blocks, panel("Schools with No Training Planned", "", text(note)))
	rows = []*screensv1.PageRow{}
	for _, sc := range cov.missing {
		rows = append(rows, sc.missingCells())
	}
	blocks = append(blocks, pagedTableOr(missingColumns, rows, query, "untrained_page",
		"Every active school in your scope that takes a training has one planned in this period.")...)

	description := teamDescription
	if w.country {
		description = countryDescription
		if w.region {
			description = regionDescription
		}
	}
	return &screensv1.GetPageResponse{
		Header: &screensv1.PageHeader{Title: pageTitle, Description: description},
		Blocks: blocks, WebPath: rules.Pages[teamKey].Path,
	}
}

var (
	plannedColumns = []string{"School ID", "School", "CCEO owner", "District", "Cluster", "Planned activity", "Category", "Planned date", "Channel", "Budget status", "PL status", "Status", "Action"}
	trainedColumns = []string{"School ID", "School", "CCEO owner", "Cluster", "Activity", "Date", "Delivery", "Status", "Visit status", "Training plan", "Action"}
	missingColumns = []string{"School ID", "School", "CCEO owner", "District", "Cluster", "Reason", "Visit status", "Action"}
)

// dayLong is |date:"j M Y".
func dayLong(t time.Time) string {
	return strconv.Itoa(t.Day()) + " " + t.Month().String()[:3] + " " + strconv.Itoa(t.Year())
}

func button(label, href string, drawer bool) *screensv1.PageCell {
	return &screensv1.PageCell{Actions: []*screensv1.PageAction{{Key: "button", Label: label, Primary: true, Enabled: true, Href: href, Drawer: drawer}}}
}

func (r coverageRow) cells() *screensv1.PageRow {
	c := rules.TeamPlan.Coverage
	category := "Training"
	switch {
	case slices.Contains(c.ClusterMeetingTypes, r.kind):
		category = "Cluster meeting"
	case strings.Contains(r.kind, "visit"):
		category = "Visit"
	}
	planned := "Not dated"
	if r.planned != nil {
		planned = dayLong(*r.planned)
	}
	channel := "Staff"
	if r.partner {
		channel = "Partner"
		if r.partnerName != "" {
			channel += " · " + r.partnerName
		}
	}
	budget := r.budget
	if r.finance != "" {
		budget += " · " + stafflogs.StatusLabel(r.finance)
	}
	action := &screensv1.PageCell{Actions: []*screensv1.PageAction{}}
	if r.activityID != "" {
		action = button("Open", "/team-planning-oversight/detail?activity="+r.activityID, true)
	}
	school := &screensv1.PageCell{Text: r.school}
	if r.code != "" && r.school != "" {
		school.Href = "/schools/" + url.PathEscape(r.code)
	}
	return &screensv1.PageRow{Cells: []*screensv1.PageCell{
		{Text: orDash(r.code)}, school, {Text: r.owner}, {Text: orDash(r.district)}, {Text: orDash(r.cluster)},
		{Text: pyTitle(strings.ReplaceAll(r.kind, "_", " "))}, {Text: category}, {Text: planned}, {Text: channel},
		{Text: budget}, {Text: r.ia}, {Text: first(r.status, "—")}, action,
	}}
}

func (sc coverageSchool) visitCell() *screensv1.PageCell {
	t := sc.visit
	if sc.nextVisit != nil {
		t += " " + strconv.Itoa(sc.nextVisit.Day()) + " " + sc.nextVisit.Month().String()[:3]
	}
	return &screensv1.PageCell{Text: t}
}

func (sc coverageSchool) clusterCell(none string) *screensv1.PageCell {
	if sc.clusterID != "" {
		return &screensv1.PageCell{Text: sc.clusterName, Href: "/clusters/" + sc.clusterID}
	}
	return &screensv1.PageCell{Text: none}
}

func (sc coverageSchool) trainedCells() *screensv1.PageRow {
	day := "Not dated"
	if sc.day != nil {
		day = dayLong(*sc.day)
	}
	delivery := "Staff"
	if sc.delivery == "partner" {
		delivery = "Partner"
	}
	if sc.partnerName != "" {
		delivery += " · " + sc.partnerName
	}
	cluster := sc.clusterCell(orDash(sc.clusterName))
	action := &screensv1.PageCell{Actions: []*screensv1.PageAction{}}
	if sc.clusterID != "" {
		action = button("Open cluster", "/clusters/"+sc.clusterID, false)
	}
	return &screensv1.PageRow{Cells: []*screensv1.PageCell{
		{Text: orDash(sc.code)}, {Text: sc.name, Href: "/schools/" + sc.code}, {Text: sc.owner}, cluster,
		{Text: first(sc.activityLabel, "Cluster session")}, {Text: day}, {Text: delivery}, {Text: orDash(sc.status)},
		sc.visitCell(), {Text: sc.training}, action,
	}}
}

func (sc coverageSchool) missingCells() *screensv1.PageRow {
	action := button("Open school", "/schools/"+sc.code, false)
	if sc.clusterID != "" {
		action = button("Plan a cluster session", "/clusters/"+sc.clusterID, false)
	}
	return &screensv1.PageRow{Cells: []*screensv1.PageCell{
		{Text: orDash(sc.code)}, {Text: sc.name, Href: "/schools/" + sc.code}, {Text: sc.owner}, {Text: orDash(sc.district)},
		sc.clusterCell("Not in a cluster"), {Text: sc.reason}, sc.visitCell(), action,
	}}
}

// pagedTable is one {% paginate %} table and the shared pager panel after
// it (the feed reads the pager apart from its table here).
func pagedTable(labels []string, rows []*screensv1.PageRow, query url.Values, param string) []*screensv1.PageBlock {
	cols := []*screensv1.PageColumn{}
	for _, l := range labels {
		cols = append(cols, &screensv1.PageColumn{Label: l})
	}
	number, pages, start, end := pageOf(query, param, len(rows))
	blocks := []*screensv1.PageBlock{{Kind: &screensv1.PageBlock_Table{Table: &screensv1.PageTable{Columns: cols, Rows: rows[start:end]}}}}
	if pages > 1 {
		blocks = append(blocks, pagerPanel(pager(number, pages, len(rows), end-start, query, param)))
	}
	return blocks
}

// pagedTableOr is pagedTable with the table's empty row ({% empty %}).
func pagedTableOr(labels []string, rows []*screensv1.PageRow, query url.Values, param, empty string) []*screensv1.PageBlock {
	if len(rows) > 0 {
		return pagedTable(labels, rows, query, param)
	}
	cols := []*screensv1.PageColumn{}
	for _, l := range labels {
		cols = append(cols, &screensv1.PageColumn{Label: l})
	}
	return []*screensv1.PageBlock{{Kind: &screensv1.PageBlock_Table{Table: &screensv1.PageTable{
		Columns: cols, EmptyMessage: empty, Rows: []*screensv1.PageRow{{Cells: []*screensv1.PageCell{{Text: empty}}}},
	}}}}
}

// pagerPanel is components/table_pager.html read apart from its table: the
// summary, then the controls in order, links side by side grouped, the
// current page and a gap as text.
func pagerPanel(p *screensv1.PagePager) *screensv1.PageBlock {
	items := []*screensv1.PagePanelItem{text(p.GetSummary())}
	var links *screensv1.PageLinks
	for _, pg := range p.GetPages() {
		if pg.GetHref() == "" {
			items, links = append(items, text(pg.GetLabel())), nil
			continue
		}
		if links == nil {
			links = &screensv1.PageLinks{}
			items = append(items, &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Links{Links: links}})
		}
		caption := ""
		switch pg.GetLabel() {
		case "Next":
			caption = "›"
		case "Prev":
			caption = "‹"
		}
		links.Links = append(links.Links, &screensv1.PageLink{Text: pg.GetLabel(), Href: pg.GetHref(), Caption: caption})
	}
	return panel("", "", items...)
}
