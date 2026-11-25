package planningmonitor

import (
	"context"
	"fmt"
	"net/url"
	"slices"
	"sort"
	"strconv"
	"strings"
	"time"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/projectmonitoring"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// The consolidated tables behind Country Planning Oversight's figures
// (country_oversight.tables, table_view and pages/oversight/country_table.html,
// as the feed reads that page).

const cpoRowsPerPage = 50

// ErrNoSuchTable is table_view's Http404 for a key tables.SPECS lacks.
var ErrNoSuchTable = fmt.Errorf("planningmonitor: no such table")

func cpoSpec(key string) (cpoTableSpec, bool) {
	for _, s := range rules.CountryOversight.Page.Tables {
		if s.Key == key {
			return s, true
		}
	}
	return cpoTableSpec{}, false
}

// cpoExtra is tables.Extra: the choices only a table offers.
type cpoExtra struct{ subRegion, cluster, project string }

func cpoReadExtra(q map[string]string) cpoExtra {
	pick := func(name string) string {
		v := strings.TrimSpace(q[name])
		if v == "all" || v == "All" {
			return ""
		}
		return v
	}
	return cpoExtra{pick("sub_region"), pick("cluster"), pick("project")}
}

// tableQuery is _table_query: the page's filters and the table's own.
func tableQuery(f cpoFilters, e cpoExtra) string {
	q := f.query(nil)
	for _, kv := range [][2]string{{"sub_region", e.subRegion}, {"cluster", e.cluster}, {"project", e.project}} {
		if kv[1] != "" {
			q += "&" + kv[0] + "=" + url.QueryEscape(kv[1])
		}
	}
	return q
}

// cpoRow is one row of a table: each column's value by key.
type cpoRow map[string]any

// cpoTable is tables.Table.
type cpoTable struct {
	spec    cpoTableSpec
	rows    []cpoRow
	summary string
}

func (t cpoTable) shown() []cpoColumn {
	out := []cpoColumn{}
	for _, c := range t.spec.Columns {
		if !slices.Contains(t.spec.ExportOnly, c.Key) {
			out = append(out, c)
		}
	}
	return out
}

// countLine is _count_line.
func countLine(n int, unit string) string {
	plural := unit + "s"
	if strings.HasSuffix(unit, "y") {
		plural = unit[:len(unit)-1] + "ies"
	}
	if n == 1 {
		return cpoFmt(n) + " " + unit
	}
	return cpoFmt(n) + " " + plural
}

// cpoPlaces is tables._Places: who holds a school and where it sits, from
// the page's own dataset.
type cpoPlaces struct {
	data      *cpoDataset
	leadOrder map[string]int
	districts map[string][3]string // id → name, sub-region id, sub-region name
	clusters  map[string][3]string // id → name, district id, responsible staff
	// newest is each school's place in School's own order (-created_at),
	// the order the existing page's ties fall in.
	newest map[string]int
	active map[string]bool // cluster id → whether it is active
}

func loadPlaces(ctx context.Context, db schooldirectory.Querier, snap *cpoSnapshot) (*cpoPlaces, error) {
	p := &cpoPlaces{data: snap.data, leadOrder: map[string]int{}, districts: map[string][3]string{}, clusters: map[string][3]string{},
		newest: map[string]int{}, active: map[string]bool{}}
	ids := make([]string, 0, len(snap.data.schools))
	for _, s := range snap.data.schools {
		ids = append(ids, s.id)
	}
	order, err := db.Query(ctx, `SELECT id FROM school WHERE id = ANY($1) ORDER BY created_at DESC, id`, ids)
	if err != nil {
		return nil, fmt.Errorf("planningmonitor: the schools' order: %w", err)
	}
	for order.Next() {
		var id string
		if err := order.Scan(&id); err != nil {
			order.Close()
			return nil, err
		}
		p.newest[id] = len(p.newest)
	}
	order.Close()
	if err := order.Err(); err != nil {
		return nil, err
	}
	for i, l := range snap.leads {
		if _, ok := p.leadOrder[l[1]]; !ok {
			p.leadOrder[l[1]] = i
		}
	}
	rows, err := db.Query(ctx, `SELECT d.id, COALESCE(d.name, ''), COALESCE(d.sub_region_id, ''), COALESCE(sr.name, '')
		FROM district d LEFT JOIN sub_region sr ON sr.id = d.sub_region_id`)
	if err != nil {
		return nil, fmt.Errorf("planningmonitor: districts: %w", err)
	}
	for rows.Next() {
		var id string
		var v [3]string
		if err := rows.Scan(&id, &v[0], &v[1], &v[2]); err != nil {
			rows.Close()
			return nil, err
		}
		p.districts[id] = v
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, err
	}
	rows, err = db.Query(ctx, `SELECT id, COALESCE(name, ''), COALESCE(district_id, ''), COALESCE(responsible_staff_id, ''),
		status = 'active' FROM cluster`)
	if err != nil {
		return nil, fmt.Errorf("planningmonitor: clusters: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var id string
		var v [3]string
		var active bool
		if err := rows.Scan(&id, &v[0], &v[1], &v[2], &active); err != nil {
			return nil, err
		}
		p.clusters[id] = v
		p.active[id] = active
	}
	return p, rows.Err()
}

// ofRecord is _Places.of_record.
func (p *cpoPlaces) ofRecord(s *cpoSchool) cpoRow {
	labels := rules.CountryOversight.Page.TableLabels
	lead, holder := labels["no_lead"], labels["no_owner"]
	if o := p.data.owners[s.ownerKey]; o != nil {
		lead, holder = o.leadName, o.name
	}
	d := p.districts[s.districtID]
	cluster, clusterID := labels["unclustered"], ""
	if c, ok := p.clusters[s.rawClusterID]; ok && s.clustered() {
		cluster, clusterID = c[0], s.rawClusterID
		if cluster == "" {
			cluster = "Cluster"
		}
	}
	kind := ""
	if s.schoolType != "" {
		kind = typeLabel(s.schoolType)
	}
	return cpoRow{"holder_lead": lead, "holder": holder, "sub_region": d[2], "district": d[0], "cluster": cluster,
		"school_id": s.code, "school": s.name, "type": kind, "_sub_region": d[1], "_cluster": clusterID, "_school": s.id}
}

// sortRows is _Places.sort: by Programme Lead in the page's order, then
// the place, then keys (each read case-folded), a tie in the order the
// rows were read.
func (p *cpoPlaces) sortRows(rows []cpoRow, keys ...string) {
	order := p.leadOrder
	str := func(r cpoRow, k string) (bool, string) {
		v, ok := r[k]
		if !ok || v == nil {
			return true, ""
		}
		switch x := v.(type) {
		case time.Time:
			return false, x.Format("2006-01-02")
		case string:
			return false, strings.ToLower(x)
		}
		return false, strings.ToLower(fmt.Sprint(v))
	}
	rank := func(r cpoRow) int {
		if i, ok := order[r["lead"].(string)]; ok {
			return i
		}
		return len(order)
	}
	all := append([]string{"sub_region", "district", "holder", "cluster"}, keys...)
	sort.SliceStable(rows, func(i, j int) bool {
		a, b := rows[i], rows[j]
		if ra, rb := rank(a), rank(b); ra != rb {
			return ra < rb
		}
		if la, lb := strings.ToLower(a["lead"].(string)), strings.ToLower(b["lead"].(string)); la != lb {
			return la < lb
		}
		for _, k := range all {
			na, va := str(a, k)
			nb, vb := str(b, k)
			if na != nb {
				return !na
			}
			if va != vb {
				return va < vb
			}
		}
		return false
	})
}

// expectedFrom is _expected_from.
func expectedFrom(staff, partner int) string {
	switch {
	case staff > 0 && partner > 0:
		return fmt.Sprintf("Staff %d · Partner %d", staff, partner)
	case partner > 0:
		return "Partner"
	case staff > 0:
		return "Staff"
	}
	return ""
}

// schoolTables are tables.SCHOOL_TABLES: the figure that puts a school in
// each table.
var schoolTables = map[string]string{"not-planned": "unplanned", "partly-planned": "partially_planned",
	"no-training": "no_training", "unclustered": "unclustered"}

// enrolledIn is _project_schools.
func enrolledIn(ctx context.Context, db schooldirectory.Querier, project string) (map[string]bool, error) {
	if project == "" {
		return nil, nil
	}
	rows, err := db.Query(ctx, `SELECT school_id FROM project_school_assignment WHERE project_id = $1`, project)
	if err != nil {
		return nil, fmt.Errorf("planningmonitor: a project's schools: %w", err)
	}
	defer rows.Close()
	out := map[string]bool{}
	for rows.Next() {
		var id string
		if err := rows.Scan(&id); err != nil {
			return nil, err
		}
		out[id] = true
	}
	return out, rows.Err()
}

// schoolRows is _school_rows: the schools the selection keeps for which
// wanted holds, under whoever holds each.
func schoolRows(ctx context.Context, db schooldirectory.Querier, snap *cpoSnapshot, places *cpoPlaces, e cpoExtra,
	wanted func(t cpoTally) bool) ([]cpoRow, error) {
	d, f := snap.data, snap.filters
	enrolled, err := enrolledIn(ctx, db, e.project)
	if err != nil {
		return nil, err
	}
	partnerIDs := []string{}
	for _, s := range d.schools {
		for pid := range s.partners {
			partnerIDs = append(partnerIDs, pid)
		}
	}
	names, err := cpoNames(ctx, db, "partner", partnerIDs)
	if err != nil {
		return nil, err
	}
	partnerName := map[string]string{}
	for _, o := range names {
		partnerName[o.value] = o.label
	}
	// The dataset's facts in School's own order (-created_at).
	schools := slices.Clone(d.schools)
	sort.SliceStable(schools, func(i, j int) bool { return places.newest[schools[i].id] < places.newest[schools[j].id] })
	rows := []cpoRow{}
	for _, s := range schools {
		values := cpoTally(d.vectors[s.id])
		if len(values) == 0 {
			continue
		}
		lead := rules.CountryOversight.NoLead[0]
		if o := d.owners[s.ownerKey]; o != nil {
			lead = o.leadKey
		}
		if !keepsPlace(f, s, lead) {
			continue
		}
		if f.planningStatus != "" && !vectorStateMatches(f, values) {
			continue
		}
		if enrolled != nil && !enrolled[s.id] {
			continue
		}
		if !wanted(values) {
			continue
		}
		row := places.ofRecord(s)
		if e.subRegion != "" && row["_sub_region"] != e.subRegion || e.cluster != "" && row["_cluster"] != e.cluster {
			continue
		}
		held := []string{}
		for pid := range s.partners {
			name, ok := partnerName[pid]
			if !ok {
				name = "Unrecorded Partner"
			}
			held = append(held, name)
		}
		sort.Strings(held)
		withPartner := strings.Join(held, ", ")
		if withPartner == "" {
			withPartner = map[bool]string{true: "Yes", false: "No"}[s.withPartner]
		}
		visits := values.n("cum_staff") + values.n("cum_partner_scheduled")
		row["lead"], row["staff"] = row["holder_lead"], row["holder"]
		row["visits_needed"] = values.n("visit_slots")
		row["expected_from"] = expectedFrom(values.n("staff_expected"), values.n("partner_expected"))
		row["visits_planned"] = visits
		row["visits_remaining"] = max(0, values.n("visit_slots")-visits)
		row["trainings_needed"] = values.n("training_slots")
		row["trainings_planned"] = values.n("cum_training")
		row["trainings_remaining"] = values.n("training_gap")
		row["with_partner"] = withPartner
		row["partner"] = strings.Join(held, ", ")
		why := []string{}
		for _, r := range duplicateReasons(s) {
			why = append(why, rules.CountryOversight.Page.TableWords.Duplicates[r])
		}
		row["why"] = strings.Join(why, "; ")
		rows = append(rows, row)
	}
	places.sortRows(rows, "school")
	return rows, nil
}

// vectorStateMatches is _state_matches over state_of(vector) and the
// vector's awaiting figure.
func vectorStateMatches(f cpoFilters, v cpoTally) bool {
	if f.planningStatus == "awaiting" {
		return v.n("awaiting_partner") > 0
	}
	state := "outside"
	switch {
	case v.n("fully_planned") > 0:
		state = "full"
	case v.n("partially_planned") > 0:
		state = "partial"
	case v.n("not_planned") > 0:
		state = "none"
	}
	return state == f.planningStatus
}

// buildTable is tables.build for the tables Go draws.
func buildTable(ctx context.Context, db schooldirectory.Querier, snap *cpoSnapshot, places *cpoPlaces, key string, e cpoExtra) (cpoTable, bool, error) {
	spec, _ := cpoSpec(key)
	t := cpoTable{spec: spec}
	figure, ok := schoolTables[key]
	if !ok {
		return activityTable(ctx, db, snap, places, t, e)
	}
	rows, err := schoolRows(ctx, db, snap, places, e, func(v cpoTally) bool { return v.n(figure) != 0 })
	if err != nil {
		return t, true, err
	}
	t.rows, t.summary = rows, countLine(len(rows), spec.Unit)
	if key == "partly-planned" {
		remaining := 0
		for _, r := range rows {
			remaining += r["visits_remaining"].(int)
		}
		t.summary += " · " + cpoFmt(remaining) + " visits still to plan"
	}
	return t, true, nil
}

// CountryOversightTable is table_view: one consolidated table, a page at a
// time, or served=false for a table Go does not draw yet.
func CountryOversightTable(ctx context.Context, db schooldirectory.Querier, p auth.Principal, key string, query url.Values,
	now time.Time) (*screensv1.GetPageResponse, bool, error) {
	spec, ok := cpoSpec(key)
	if !ok {
		return nil, true, ErrNoSuchTable
	}
	if !tablesDrawn[key] {
		return nil, false, nil
	}
	q := map[string]string{}
	for k, v := range query {
		if len(v) > 0 {
			q[k] = v[len(v)-1]
		}
	}
	scope, err := schooldirectory.ResolveScope(ctx, db, p, now)
	if err != nil {
		return nil, true, err
	}
	l := now.In(cpoLocation)
	today := date(l.Year(), l.Month(), l.Day())
	f, e := cpoReadFilters(q, today), cpoReadExtra(q)
	tq := tableQuery(f, e)
	withheld := scope.SummaryOnly
	header := &screensv1.PageHeader{Eyebrow: "Country Planning Oversight", Title: spec.Title, Description: spec.Description}
	if slices.Contains(rules.CountryOversight.Page.ExportRoles, p.ActiveRole) && !withheld {
		header.Actions = []*screensv1.PageAction{
			{Key: "export", Label: "Export", Enabled: true, Href: resolvedHref(cpoPath+"table-export/"+key, tq), Download: true},
			{Key: "all_tables", Label: "All Tables", Enabled: true, Href: resolvedHref(cpoPath+"table-export/all", tq), Download: true},
		}
	}
	blocks := []*screensv1.PageBlock{tableTabs(key, tq)}
	w := cpoWindowOf(f)
	title := spec.Title + " · " + cpoFYLabel(f.fy)
	if !w.isAnnual() {
		title = spec.Title + " · " + w.label()
	}
	if withheld {
		blocks = append(blocks, &screensv1.PageBlock{Kind: &screensv1.PageBlock_Table{Table: &screensv1.PageTable{Title: title,
			EmptyMessage: "School-level rows are not part of this role's reading of the country. The figures on Country Planning Oversight are."}}})
		return &screensv1.GetPageResponse{Header: header, Blocks: blocks, WebPath: cpoPath + "table/" + key}, true, nil
	}
	snap, err := buildCPOSnapshot(ctx, db, scope, f, today)
	if err != nil {
		return nil, true, err
	}
	places, err := loadPlaces(ctx, db, snap)
	if err != nil {
		return nil, true, err
	}
	filters, err := tableFilters(ctx, db, p, scope, snap, places, f, e, today)
	if err != nil {
		return nil, true, err
	}
	blocks = append(blocks, filters)
	t, _, err := buildTable(ctx, db, snap, places, key, e)
	if err != nil {
		return nil, true, err
	}
	blocks = append(blocks, tableBlocks(t, title, query)...)
	return &screensv1.GetPageResponse{Header: header, Blocks: blocks, WebPath: cpoPath + "table/" + key}, true, nil
}

// tableTabs is _table_tabs through partials/oversight/_lens_tabs.html.
func tableTabs(active, query string) *screensv1.PageBlock {
	tabs := []*screensv1.PageLinkTab{}
	for _, key := range rules.CountryOversight.Page.TableTabs {
		s, _ := cpoSpec(key)
		tabs = append(tabs, &screensv1.PageLinkTab{Label: s.Short, Href: cpoPath + "table/" + key + "?" + query, Active: key == active})
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_LinkTabs{LinkTabs: &screensv1.PageLinkTabs{Tabs: tabs}}}
}

// tableFilters is the table page's form over _table_filter_options.
func tableFilters(ctx context.Context, db schooldirectory.Querier, p auth.Principal, scope schooldirectory.Scope, snap *cpoSnapshot,
	places *cpoPlaces, f cpoFilters, e cpoExtra, today time.Time) (*screensv1.PageBlock, error) {
	with := func(first string, rest []cpoOption) []cpoOption { return append([]cpoOption{{"", first}}, rest...) }
	years := []cpoOption{}
	for y := 2025; y <= max(cpoOperationalFY(today)+1, 2027); y++ {
		years = append(years, cpoOption{strconv.Itoa(y), cpoFYLabel(strconv.Itoa(y))})
	}
	districtIDs := map[string]bool{}
	for _, s := range snap.data.schools {
		if s.districtID != "" {
			districtIDs[s.districtID] = true
		}
	}
	districts, subs := []cpoOption{}, map[string]string{}
	for id := range districtIDs {
		if d, ok := places.districts[id]; ok {
			districts = append(districts, cpoOption{id, d[0]})
			if d[1] != "" {
				subs[d[1]] = d[2]
			}
		}
	}
	byLabel := func(o []cpoOption) {
		sort.SliceStable(o, func(i, j int) bool {
			if a, b := strings.ToLower(o[i].label), strings.ToLower(o[j].label); a != b {
				return a < b
			}
			return o[i].value < o[j].value
		})
	}
	byLabel(districts)
	subRegions := []cpoOption{}
	for id, name := range subs {
		subRegions = append(subRegions, cpoOption{id, name})
	}
	byLabel(subRegions)
	holders := []cpoOption{}
	for _, o := range snap.data.owners {
		if ownerKind(o.key, o.role) != "unassigned" {
			holders = append(holders, cpoOption{o.key, o.name})
		}
	}
	byLabel(holders)
	partners, err := cpoAllPartners(ctx, db)
	if err != nil {
		return nil, err
	}
	clusters, err := cpoActiveClusters(ctx, db, districtIDs, f.district)
	if err != nil {
		return nil, err
	}
	watched, err := projectmonitoring.WatchedProjects(ctx, db, p, scope)
	if err != nil {
		return nil, err
	}
	filters := []*screensv1.PageFilter{
		filterOf("fy", "Financial year", "FY", f.fy, years),
		filterOf("program_lead", "Programme Lead", "", f.programLead, with("All leads", pairs(snap.leads))),
		filterOf("sub_region", "Sub-region", "", e.subRegion, with("All sub-regions", subRegions)),
		filterOf("district", "District", "", f.district, with("All districts", districts)),
		filterOf("cceo", "CCEO or Programme Lead", "CCEO / PL", f.cceo, with("Everyone", holders)),
		filterOf("cluster", "Cluster", "", e.cluster, with("All clusters", clusters)),
		filterOf("school_type", "School type", "School Type", f.schoolType, with("All types", pairs(rules.CountryOversight.Page.TypeOptions))),
		filterOf("partner", "Partner", "", f.partner, with("All Partners", partners)),
		filterOf("project", "Project", "", e.project, with("All projects", pairs(watched))),
	}
	// The page's other filters ride along as hidden fields (carried).
	hidden := map[string]string{}
	params, _ := url.ParseQuery(f.query(nil))
	for name := range params {
		if !slices.Contains(tableFilterFields, name) {
			hidden[name] = params.Get(name)
		}
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Filters{Filters: &screensv1.PageFilters{Filters: filters, Hidden: hidden}}}, nil
}

// tableFilterFields are TABLE_FILTER_FIELDS: the choices the table page
// offers as fields.
var tableFilterFields = []string{"fy", "program_lead", "district", "cceo", "school_type", "partner", "sub_region", "cluster", "project"}

func cpoAllPartners(ctx context.Context, db schooldirectory.Querier) ([]cpoOption, error) {
	rows, err := db.Query(ctx, `SELECT id, name FROM partner ORDER BY name`)
	if err != nil {
		return nil, fmt.Errorf("planningmonitor: partners: %w", err)
	}
	defer rows.Close()
	out := []cpoOption{}
	for rows.Next() {
		var o cpoOption
		if err := rows.Scan(&o.value, &o.label); err != nil {
			return nil, err
		}
		out = append(out, o)
	}
	return out, rows.Err()
}

func cpoActiveClusters(ctx context.Context, db schooldirectory.Querier, districts map[string]bool, district string) ([]cpoOption, error) {
	ids := []string{}
	for id := range districts {
		ids = append(ids, id)
	}
	rows, err := db.Query(ctx, `SELECT c.id, c.name, COALESCE(d.name, '') FROM cluster c LEFT JOIN district d ON d.id = c.district_id
		WHERE c.status = 'active' AND c.district_id = ANY($1) AND ($2 = '' OR c.district_id = $2) ORDER BY c.name`, ids, district)
	if err != nil {
		return nil, fmt.Errorf("planningmonitor: clusters to narrow to: %w", err)
	}
	defer rows.Close()
	out := []cpoOption{}
	for rows.Next() {
		var id, name, dname string
		if err := rows.Scan(&id, &name, &dname); err != nil {
			return nil, err
		}
		if dname != "" {
			name += " · " + dname
		}
		out = append(out, cpoOption{id, name})
	}
	return out, rows.Err()
}

// tableBlocks is _consolidated_table.html: the table with its count and a
// page of its rows, or the empty state.
func tableBlocks(t cpoTable, title string, query url.Values) []*screensv1.PageBlock {
	total := len(t.rows)
	if total == 0 {
		return []*screensv1.PageBlock{{Kind: &screensv1.PageBlock_Table{Table: &screensv1.PageTable{Title: title, Subtitle: t.summary,
			EmptyMessage: "Nothing in this selection."}}}}
	}
	number, pages, start, end := cpoPageOf(query, "page", total)
	shown := t.shown()
	table := &screensv1.PageTable{Title: title, Subtitle: t.summary}
	for _, c := range shown {
		table.Columns = append(table.Columns, &screensv1.PageColumn{Label: c.Label, Numeric: c.Numeric})
	}
	for _, r := range t.rows[start:end] {
		row := &screensv1.PageRow{}
		code, _ := r["school_id"].(string)
		for _, c := range shown {
			row.Cells = append(row.Cells, tableCell(c, r, code))
		}
		table.Rows = append(table.Rows, row)
	}
	if pages > 1 {
		table.Pager = cpoPager(number, pages, total, end-start, query, "page")
		table.Footnote = table.Pager.GetSummary()
	}
	return []*screensv1.PageBlock{{Kind: &screensv1.PageBlock_Table{Table: table}}}
}

// tableCell is one cell of _consolidated_table.html.
func tableCell(c cpoColumn, r cpoRow, code string) *screensv1.PageCell {
	v, has := r[c.Key]
	if c.IsDate {
		if d, ok := v.(time.Time); ok && !d.IsZero() {
			return plain(fmt.Sprintf("%d %s", d.Day(), d.Format("Jan 2006")))
		}
		blank, _ := r[c.Key+"_note"].(string)
		if blank == "" {
			blank = c.Blank
		}
		if blank != "" || !c.Quiet {
			if blank == "" {
				blank = "Not yet scheduled"
			}
			return &screensv1.PageCell{Text: blank, Tone: "warning"}
		}
		return plain("—")
	}
	if !has || v == nil || v == "" {
		return plain("—")
	}
	text := fmt.Sprint(v)
	if c.Key == "flag" {
		return &screensv1.PageCell{Text: text, Tone: "danger"}
	}
	switch c.Kind {
	case "change":
		n, _ := v.(int)
		tone := "neutral"
		switch {
		case n > 0:
			text, tone = "+"+text, "success"
		case n < 0:
			tone = "danger"
		}
		return &screensv1.PageCell{Text: text, Tone: tone}
	case "money":
		if n, ok := v.(int); ok {
			text = cpoFmt(n)
		}
	}
	if c.IsSchool && code != "" {
		return &screensv1.PageCell{Text: text, Href: "/schools/" + code}
	}
	return plain(text)
}

// resolvedHref is page_blocks._resolved: a header link's parameters in name
// order, the blank ones dropped.
func resolvedHref(base, query string) string {
	values, _ := url.ParseQuery(query)
	keys := []string{}
	for k := range values {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	parts := []string{}
	for _, k := range keys {
		for _, v := range values[k] {
			if v != "" {
				parts = append(parts, url.QueryEscape(k)+"="+url.QueryEscape(v))
			}
		}
	}
	if len(parts) == 0 {
		return base
	}
	return base + "?" + strings.Join(parts, "&")
}

// tablesDrawn are the tables Go draws; the rest are handed on.
var tablesDrawn = map[string]bool{"not-planned": true, "partly-planned": true, "no-training": true, "unclustered": true,
	"visits": true, "meetings": true, "partners": true, "all-visits": true, "plans": true, "trainings": true,
	"project-partners": true, "project-activities": true, "clusters": true, "duplicates": true}

// activityTable is tables.build for the people-first tables Go draws.
func activityTable(ctx context.Context, db schooldirectory.Querier, snap *cpoSnapshot, places *cpoPlaces, t cpoTable,
	e cpoExtra) (cpoTable, bool, error) {
	book, err := newBook(ctx, db, snap, places, e)
	if err != nil {
		return t, true, err
	}
	switch t.spec.Key {
	case "duplicates":
		return duplicateTable(ctx, db, snap, places, t, e)
	case "clusters":
		rows, err := book.clusterRows()
		if err != nil {
			return t, true, err
		}
		places.sortRows(rows, "school")
		clusters := map[[2]any]bool{}
		for _, r := range rows {
			clusters[[2]any{r["district"], r["cluster"]}] = true
		}
		t.rows = rows
		t.summary = countLine(len(rows), t.spec.Unit) + " in " + cpoFmt(len(clusters)) + " cluster" + pluralize(len(clusters), "", "s")
	case "visits":
		rows, err := book.visitRows()
		if err != nil {
			return t, true, err
		}
		rows = flagRows(rows, twiceCodes(snap))
		places.sortRows(rows, "date", "school")
		t.rows = rows
		t.summary = countLine(len(rows), t.spec.Unit) + " planned · " + balance(len(rows), cpoTally(snap.tree.country).n("target"))
	case "meetings":
		yes := true
		rows, err := book.sessionRows(&yes)
		if err != nil {
			return t, true, err
		}
		places.sortRows(rows, "date")
		invited := 0
		for _, r := range rows {
			invited += r["invited"].(int)
		}
		t.rows = rows
		t.summary = countLine(len(rows), t.spec.Unit) + " planned · " + cpoFmt(invited) + " school invitation" + pluralize(invited, "", "s")
	default:
		rows, summary, ok, err := partnerTable(book, snap, t.spec)
		if err != nil || !ok {
			return t, ok, err
		}
		t.rows, t.summary = rows, summary
	}
	return t, true, nil
}

// gather is one table's rows from several sets, in the order given.
func gather(parts ...func() ([]cpoRow, error)) ([]cpoRow, error) {
	out := []cpoRow{}
	for _, part := range parts {
		rows, err := part()
		if err != nil {
			return nil, err
		}
		out = append(out, rows...)
	}
	return out, nil
}

func where(rows []cpoRow, keep func(cpoRow) bool) []cpoRow {
	out := []cpoRow{}
	for _, r := range rows {
		if keep(r) {
			out = append(out, r)
		}
	}
	return out
}

func byStaff(rows []cpoRow) int {
	n := 0
	for _, r := range rows {
		if r["channel"] == "Staff" {
			n++
		}
	}
	return n
}

func distinct(rows []cpoRow, key string) int {
	seen := map[any]bool{}
	for _, r := range rows {
		seen[r[key]] = true
	}
	return len(seen)
}

// partnerBalance is _partner_balance.
func partnerBalance(rows []cpoRow) string {
	planned := rules.CountryOversight.Page.TableLabels["partner_planned"]
	dated := len(where(rows, func(r cpoRow) bool { return r["state"] == planned }))
	return cpoFmt(dated) + " of " + cpoFmt(len(rows)) + " planned by the Partner · " + cpoFmt(len(rows)-dated) + " awaiting partner schedule"
}

// partnerTable is tables.build for the tables that list Partner work.
func partnerTable(k *cpoBook, snap *cpoSnapshot, spec cpoTableSpec) ([]cpoRow, string, bool, error) {
	planned := rules.CountryOversight.Page.TableLabels["partner_planned"]
	partnerDated := func(every bool, sessions bool) func() ([]cpoRow, error) {
		return func() ([]cpoRow, error) {
			rows, err := k.partnerRows(every)
			if err != nil || !sessions {
				return rows, err
			}
			more, err := k.partnerSessionRows(nil)
			return append(rows, more...), err
		}
	}
	no := false
	visits := k.visitRows
	outreach := k.outreachRows
	trainings := func() ([]cpoRow, error) { return k.trainingRows(true) }
	sessions := func() ([]cpoRow, error) { return k.sessionRows(nil) }
	twice := twiceCodes(snap)
	var rows []cpoRow
	var err error
	summary := ""
	unit := spec.Unit
	switch spec.Key {
	case "partners":
		if rows, err = k.partnerRows(false); err != nil {
			return nil, "", true, err
		}
		rows = flagRows(rows, twice)
		k.places.sortRows(rows, "partner", "school", "date")
		schools := distinct(rows, "school_id")
		summary = countLine(len(rows), unit) + " at " + cpoFmt(schools) + " school" + pluralize(schools, "", "s") + " · " + partnerBalance(rows)
	case "all-visits":
		if rows, err = gather(visits, outreach, func() ([]cpoRow, error) {
			p, err := k.partnerRows(false)
			return where(p, func(r cpoRow) bool {
				return (r["is_visit"] == true || r["is_training"] != true) && r["state"] == planned
			}), err
		}); err != nil {
			return nil, "", true, err
		}
		rows = flagRows(rows, twice)
		k.places.sortRows(rows, "date", "school")
		staff := byStaff(rows)
		summary = countLine(len(rows), unit) + " planned · " + cpoFmt(staff) + " by staff · " + cpoFmt(len(rows)-staff) + " by Partners"
	case "plans":
		if rows, err = gather(visits, outreach, trainings, k.otherRows, sessions, partnerDated(true, true)); err != nil {
			return nil, "", true, err
		}
		rows = flagRows(rows, twice)
		k.places.sortRows(rows, "date", "school", "activity")
		staff := byStaff(rows)
		summary = countLine(len(rows), "activity") + " · " + cpoFmt(staff) + " by staff · " + cpoFmt(len(rows)-staff) + " with Partners"
	case "trainings":
		if rows, err = gather(func() ([]cpoRow, error) { return k.trainingRows(false) },
			func() ([]cpoRow, error) { return k.sessionRows(&no) },
			func() ([]cpoRow, error) {
				p, err := k.partnerRows(false)
				return where(p, func(r cpoRow) bool { return r["is_training"] == true }), err
			},
			func() ([]cpoRow, error) { return k.partnerSessionRows(&no) }); err != nil {
			return nil, "", true, err
		}
		k.places.sortRows(rows, "date", "school")
		summary = countLine(len(rows), unit) + " planned"
	case "project-partners":
		p, err := k.partnerRows(true)
		if err != nil {
			return nil, "", true, err
		}
		rows = where(p, func(r cpoRow) bool { return r["_project"] != "" })
		k.places.sortRows(rows, "project", "partner", "school", "date")
		schools := distinct(rows, "school_id")
		summary = countLine(len(rows), unit) + " at " + cpoFmt(schools) + " school" + pluralize(schools, "", "s") + " · " + partnerBalance(rows)
	case "project-activities":
		all, err := gather(visits, outreach, trainings, k.otherRows, sessions, func() ([]cpoRow, error) {
			p, err := partnerDated(true, true)()
			return where(p, func(r cpoRow) bool { return r["state"] == planned }), err
		})
		if err != nil {
			return nil, "", true, err
		}
		rows = where(all, func(r cpoRow) bool { return r["_project"] != "" })
		k.places.sortRows(rows, "project", "date", "school", "activity")
		staff := byStaff(rows)
		projects := distinct(rows, "_project")
		summary = countLine(len(rows), unit) + " in " + cpoFmt(projects) + " project" + pluralize(projects, "", "s") + " · " +
			cpoFmt(staff) + " by staff · " + cpoFmt(len(rows)-staff) + " by Partners"
	default:
		return nil, "", false, nil
	}
	return rows, summary, true, nil
}

// duplicateTable is _duplicate_table: every plan at every school planned
// twice, whoever made it.
func duplicateTable(ctx context.Context, db schooldirectory.Querier, snap *cpoSnapshot, places *cpoPlaces, t cpoTable,
	e cpoExtra) (cpoTable, bool, error) {
	schools, err := schoolRows(ctx, db, snap, places, e, func(v cpoTally) bool { return v.n("duplicates") != 0 })
	if err != nil {
		return t, true, err
	}
	if len(schools) == 0 {
		t.summary = "No school is planned twice"
		return t, true, nil
	}
	byCode, ids := map[string]cpoRow{}, []string{}
	for _, r := range schools {
		byCode[r["school_id"].(string)] = r
		ids = append(ids, r["_school"].(string))
	}
	// The page's Lead and CCEO choice picked the schools, not the planners.
	everyone := *snap
	everyone.filters.programLead, everyone.filters.cceo = "", ""
	everyone.narrow = cpoNarrow{schoolIDs: ids}
	book, err := newBook(ctx, db, &everyone, places, cpoExtra{})
	if err != nil {
		return t, true, err
	}
	plans, err := gather(book.visitRows, func() ([]cpoRow, error) {
		p, err := book.partnerRows(false)
		return where(p, func(r cpoRow) bool { return r["is_visit"] == true }), err
	})
	if err != nil {
		return t, true, err
	}
	rows := []cpoRow{}
	for _, plan := range plans {
		school, ok := byCode[plan["school_id"].(string)]
		if !ok {
			continue
		}
		responsible := plan["staff"]
		if plan["channel"] == "Partner" {
			responsible = fmt.Sprintf("%s (assigned by %s)", plan["partner"], plan["staff"])
		}
		plan["why"], plan["staff"] = school["why"], responsible
		rows = append(rows, plan)
	}
	places.sortRows(rows, "school", "school_id", "date")
	count := distinct(rows, "school_id")
	t.rows = rows
	t.summary = cpoFmt(count) + " school" + pluralize(count, "", "s") + " planned twice · " + countLine(len(rows), "plan") + " between them"
	return t, true, nil
}
