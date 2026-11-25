package planningmonitor

import (
	"context"
	"fmt"
	"net/url"
	"slices"
	"time"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// The consolidated tables behind the Execution & Completion figures
// (country_execution.tables, records_view and
// pages/oversight/country_execution_table.html, as the feed reads that page).

// cexWithheld is records_view's withheld_message.
const cexWithheld = "Activity-level rows are not part of this role's reading of the country. The figures on Execution & Completion are."

func cexRecordsSpec(key string) (cpoTableSpec, bool) {
	for _, s := range rules.CountryExecution.Records.Tables {
		if s.Key == key {
			return s, true
		}
	}
	return cpoTableSpec{}, false
}

// cexKeeps is _keeps: the records a table lists, by the test its card
// counts with, or the visits on the plan.
func cexKeeps(key string) func(cexRecord) bool {
	if key == "visits" {
		planned := rules.CountryOversight.PlannedStates
		return func(r cexRecord) bool { return r.counted() && slices.Contains(planned, r.status) }
	}
	return cexStageFilter(key)
}

// cexStageFilter is STAGE_FILTERS[stage], the live work ("due") for a stage
// it lacks.
func cexStageFilter(stage string) func(cexRecord) bool {
	switch stage {
	case "started":
		return func(r cexRecord) bool { return r.started && !r.cancelled }
	case "not_started":
		return func(r cexRecord) bool { return !r.started && !r.cancelled }
	case "executed":
		return func(r cexRecord) bool { return r.executed }
	case "pl_review", "ia_review":
		return func(r cexRecord) bool { return r.stage == stage }
	case "verified":
		return func(r cexRecord) bool { return r.verified }
	case "closed":
		return func(r cexRecord) bool { return r.closed }
	case "returned":
		return func(r cexRecord) bool { return r.returned }
	case "overdue":
		return func(r cexRecord) bool { return r.overdue != "" }
	case "finance":
		return func(r cexRecord) bool { return r.financeOpen }
	case "cancelled":
		return func(r cexRecord) bool { return r.cancelled }
	}
	return func(r cexRecord) bool { return !r.cancelled }
}

// CountryExecutionRecords is records_view: one consolidated table, a page at
// a time.
func CountryExecutionRecords(ctx context.Context, db schooldirectory.Querier, p auth.Principal, key string, query url.Values,
	now time.Time) (*screensv1.GetPageResponse, error) {
	spec, ok := cexRecordsSpec(key)
	if !ok {
		return nil, ErrNoSuchTable
	}
	q := map[string]string{}
	for k, v := range query {
		if len(v) > 0 {
			q[k] = v[len(v)-1]
		}
	}
	scope, err := schooldirectory.ResolveScope(ctx, db, p, now)
	if err != nil {
		return nil, err
	}
	l := now.In(cpoLocation)
	today := date(l.Year(), l.Month(), l.Day())
	f := cexReadFilters(q, today)
	s, err := buildCEXSnapshot(ctx, db, scope, f, today)
	if err != nil {
		return nil, err
	}
	fq := f.query()
	withheld := scope.SummaryOnly
	path := cexBase + "/records/" + key
	header := &screensv1.PageHeader{Eyebrow: "Country Execution & Completion Oversight", Title: spec.Title, Description: spec.Description}
	if slices.Contains(rules.CountryExecution.Records.ExportRoles, p.ActiveRole) && !withheld {
		header.Actions = []*screensv1.PageAction{{Key: "export", Label: "Export", Enabled: true,
			Href: resolvedHref(cexBase+"/records-export/"+key, fq), Download: true}}
	}
	blocks := []*screensv1.PageBlock{cexRecordsTabs(key, fq), s.recordsFilters()}
	w := s.data.window
	title := spec.Title + " · " + cpoFYLabel(f.fy)
	if !w.isAnnual() {
		title = spec.Title + " · " + w.label()
	}
	if withheld {
		blocks = append(blocks, &screensv1.PageBlock{Kind: &screensv1.PageBlock_Table{Table: &screensv1.PageTable{Title: title,
			EmptyMessage: cexWithheld}}})
		return &screensv1.GetPageResponse{Header: header, Blocks: blocks, WebPath: path}, nil
	}
	t, err := s.recordsTable(ctx, db, spec)
	if err != nil {
		return nil, err
	}
	blocks = append(blocks, tableBlocks(t, title, query)...)
	return &screensv1.GetPageResponse{Header: header, Blocks: blocks, WebPath: path}, nil
}

// cexRecordsTabs is _records_tabs through partials/oversight/_lens_tabs.html.
func cexRecordsTabs(active, query string) *screensv1.PageBlock {
	tabs := []*screensv1.PageLinkTab{}
	for _, key := range rules.CountryExecution.Records.Tabs {
		s, _ := cexRecordsSpec(key)
		tabs = append(tabs, &screensv1.PageLinkTab{Label: s.Short, Href: cexBase + "/records/" + key + "?" + query, Active: key == active})
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_LinkTabs{LinkTabs: &screensv1.PageLinkTabs{Tabs: tabs}}}
}

// recordsFilters is the table page's two choices; the rest of the tab's
// selection rides along as hidden fields (carried).
func (s *cexSnapshot) recordsFilters() *screensv1.PageBlock {
	f := s.filters
	leads := []cpoOption{{"", "All leads"}}
	for _, l := range s.roster.leads {
		leads = append(leads, cpoOption{l[0], l[1]})
	}
	filters := []*screensv1.PageFilter{
		filterOf("program_lead", "Programme Lead", "", f.programLead, leads),
		filterOf("channel", "Delivery channel", "Delivered By", f.channel, []cpoOption{{"", "Staff and Partners"}, {"staff", "Staff"}, {"partner", "Partner"}}),
	}
	hidden := map[string]string{}
	params, _ := url.ParseQuery(f.query())
	for name := range params {
		if name != "program_lead" && name != "channel" {
			hidden[name] = params.Get(name)
		}
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Filters{Filters: &screensv1.PageFilters{Filters: filters, Hidden: hidden}}}
}

// recordsTable is tables.build: the whole table for the selection, sorted.
func (s *cexSnapshot) recordsTable(ctx context.Context, db schooldirectory.Querier, spec cpoTableSpec) (cpoTable, error) {
	keeps := cexKeeps(spec.Key)
	records := []cexRecord{}
	for _, r := range s.records() {
		if keeps(r) {
			records = append(records, r)
		}
	}
	places, err := loadPlaces(ctx, db, s.plan)
	if err != nil {
		return cpoTable{}, err
	}
	others, err := cexOtherSchools(ctx, db, places, records)
	if err != nil {
		return cpoTable{}, err
	}
	rows := make([]cpoRow, 0, len(records))
	for _, r := range records {
		rows = append(rows, s.recordRow(r, places, others))
	}
	places.sortRows(rows, "school", "due", "activity")
	return cpoTable{spec: spec, rows: rows, summary: s.recordsSummary(spec, rows)}, nil
}

// cexSchool is a School row the planning dataset does not hold (closed
// since, or outside its requirement): it still has execution to list.
type cexSchool struct{ code, name, schoolType, districtID, clusterID string }

func cexOtherSchools(ctx context.Context, db schooldirectory.Querier, places *cpoPlaces, records []cexRecord) (map[string]cexSchool, error) {
	missing := []string{}
	for _, r := range records {
		if r.schoolID != "" && places.data.byID[r.schoolID] == nil {
			missing = append(missing, r.schoolID)
		}
	}
	out := map[string]cexSchool{}
	if len(missing) == 0 {
		return out, nil
	}
	rows, err := db.Query(ctx, `SELECT id, COALESCE(school_id, ''), COALESCE(name, ''), COALESCE(school_type, ''),
		COALESCE(district_id, ''), COALESCE(cluster_id, '') FROM school WHERE id = ANY($1)`, missing)
	if err != nil {
		return nil, fmt.Errorf("planningmonitor: the schools the plan does not hold: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var id string
		var c cexSchool
		if err := rows.Scan(&id, &c.code, &c.name, &c.schoolType, &c.districtID, &c.clusterID); err != nil {
			return nil, err
		}
		out[id] = c
	}
	return out, rows.Err()
}

// who is _who: the Programme Lead, person and whether anyone is recorded
// for the work as the cards credit it.
func (s *cexSnapshot) who(r cexRecord) (lead, person string) {
	o := s.data.owners[r.ownerKey]
	if o == nil || r.ownerKey == rules.CountryOversight.NoOwner[0] {
		return rules.CountryOversight.NoLead[1], rules.CountryExecution.Records.Words.Nobody
	}
	lead = o.leadName
	if o.leadKey == rules.CountryOversight.NoLead[0] {
		lead = rules.CountryOversight.NoLead[1]
	}
	return lead, o.name
}

// placeOf is _Where.of.
func (s *cexSnapshot) placeOf(r cexRecord, places *cpoPlaces, others map[string]cexSchool, lead, person string) cpoRow {
	labels := rules.CountryOversight.Page.TableLabels
	if r.schoolID != "" {
		if fact := places.data.byID[r.schoolID]; fact != nil {
			return places.ofRecord(fact)
		}
		if o, ok := others[r.schoolID]; ok {
			d := places.districts[o.districtID]
			cluster := labels["unclustered"]
			if c, ok := places.clusters[o.clusterID]; ok {
				cluster = c[0]
				if cluster == "" {
					cluster = "Cluster"
				}
			}
			kind := ""
			if o.schoolType != "" {
				kind = typeLabel(o.schoolType)
			}
			return cpoRow{"holder_lead": rules.CountryOversight.NoLead[1], "holder": rules.CountryOversight.NoOwner[1],
				"sub_region": d[2], "district": d[0], "cluster": cluster, "school_id": o.code, "school": o.name, "type": kind}
		}
	}
	c := places.clusters[r.clusterID]
	d := places.districts[c[1]]
	holder := person
	if person == rules.CountryExecution.Records.Words.Nobody {
		holder = rules.CountryOversight.NoOwner[1]
	}
	cluster, school := c[0], ""
	if r.clusterID != "" {
		name := c[0]
		if name == "" {
			name = "Cluster"
		}
		cluster, school = name, name+" (cluster)"
	}
	return cpoRow{"holder_lead": lead, "holder": holder, "sub_region": d[2], "district": d[0], "cluster": cluster,
		"school_id": "", "school": school, "type": ""}
}

// recordRow is _row.
func (s *cexSnapshot) recordRow(r cexRecord, places *cpoPlaces, others map[string]cexSchool) cpoRow {
	words := rules.CountryExecution.Records.Words
	st := rules.CountryExecution.Stages
	lead, person := s.who(r)
	partner := s.data.partnerName[r.partnerKey]
	if partner == "" {
		partner = "Partner"
	}
	counted := ""
	switch {
	case r.counted():
		counted = words.Counted
	case r.outreach:
		counted = words.NotCounted
	}
	stage := r.stage
	for _, l := range st.StageLabels {
		if l[0] == r.stage {
			stage = l[1]
		}
	}
	if r.overdue != "" {
		stage += " · " + st.OverdueLabels[r.overdue]
	}
	row := s.placeOf(r, places, others, lead, person)
	row["lead"] = row["holder_lead"]
	row["staff"] = person
	row["staff_lead"] = lead
	// _who's role: the owner's, in the tables' words; none for nobody.
	row["role"] = ""
	if o := s.data.owners[r.ownerKey]; o != nil && r.ownerKey != rules.CountryOversight.NoOwner[0] {
		row["role"] = rules.CountryOversight.Page.RoleLabels[o.role]
	}
	row["by"] = "Staff"
	if r.channel != "staff" {
		row["by"] = "Partner · " + partner
	}
	if r.counted() {
		if label, ok := rules.CountryOversight.Page.TableWords.Kinds[r.kind]; ok {
			row["activity"] = label
		} else {
			row["activity"] = nil
		}
	} else {
		row["activity"] = typeLabelOf(r.activityType)
	}
	row["counted"] = counted
	row["due"] = dayValue(r.due)
	row["delivered"] = nil
	if r.started {
		row["delivered"] = dayValue(r.deliveredDay)
	}
	if r.executed && row["delivered"] == nil {
		row["delivered_note"] = words.NotRecorded
	}
	row["stage"] = stage
	switch {
	case r.verified:
		row["state"] = words.Verified
	case r.executed:
		row["state"] = words.Delivered
	default:
		row["state"] = words.Planned
	}
	row["age"] = nil
	if r.overdue != "" {
		row["age"] = r.age
	}
	waiting := ""
	for _, l := range st.OwnerLabels {
		if l[0] == r.owner {
			waiting = l[1]
		}
	}
	row["waiting"] = waiting
	row["last"] = dayValue(r.lastAction)
	return row
}

// dayValue is a day as a row holds it: the date, or nothing.
func dayValue(t *time.Time) any {
	if t == nil {
		return nil
	}
	return *t
}

// recordsSummary is _summary: what the rows add up to and the selection's
// balance.
func (s *cexSnapshot) recordsSummary(spec cpoTableSpec, rows []cpoRow) string {
	c := s.tree.country
	if spec.Key == "visits" {
		text := countLine(len(rows), spec.Unit) + " planned · " + cpoFmt(c.n("v_delivered")) + " delivered · " +
			cpoFmt(c.n("v_verified")) + " verified"
		if f := s.filters; f.activType == "" && f.channel == "" {
			if target := s.targets[[2]string{"country", ""}]; target != 0 {
				text += " · target " + cpoFmt(target) + " · " + cpoFmt(max(0, target-c.n("v_delivered"))) + " still to deliver"
			}
		}
		return text
	}
	schools := map[string]bool{}
	for _, r := range rows {
		if code, _ := r["school_id"].(string); code != "" {
			schools[code] = true
		}
	}
	return countLine(len(rows), spec.Unit) + " at " + countLine(len(schools), "school") + " · " +
		cpoFmt(c.n("executed")) + " of " + cpoFmt(c.n("due")) + " planned delivered · " + cpoFmt(c.n("verified")) +
		" verified · " + cpoFmt(c.n("overdue")) + " overdue"
}
