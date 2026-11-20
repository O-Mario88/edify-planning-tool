package iapages

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
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/closedschools"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// collectionRules is the Collection view's vocabulary (export_ia_pages_rules
// _collection).
type collectionRules struct {
	States              [][3]string       `json:"states"`
	WorkStates          []string          `json:"work_states"`
	OperatingStatuses   []string          `json:"operating_statuses"`
	OpenStatuses        []string          `json:"open_statuses"`
	DeliveredStatuses   []string          `json:"delivered_statuses"`
	LiveProjectStatuses []string          `json:"live_project_statuses"`
	VerificationLabels  map[string]string `json:"verification_labels"`
	PageSize            int               `json:"page_size"`
	PageParam           string            `json:"page_param"`
}

// collectionSchool is one school of the worklist's page.
type collectionSchool struct {
	id, code, name, districtName, ownerID, state string
}

// latestRecord is a school's latest SSA record (any status).
type latestRecord struct {
	fy, status, reason string
	assessed           time.Time
	returned           *time.Time
}

// openVisit is a school's first open SSA collection visit.
type openVisit struct {
	responsible string
	planned     *time.Time
}

// collectionScope is collection_schools over school `s`: the scope's
// operating, live schools.
func collectionScope(scope schooldirectory.Scope) (string, []any) {
	args := []any{}
	where := schooldirectory.AnalyticsReach(scope, &args)
	args = append(args, rules.Dashboard.Collection.OperatingStatuses)
	return fmt.Sprintf("%s AND s.operational_status = ANY($%d)", where, len(args)), args
}

// stateSQL is annotate_states' CASE over school `s` for the year numbered
// fy, the open and delivered statuses numbered open and delivered.
func stateSQL(fy, open, delivered int) string {
	return fmt.Sprintf(`CASE
  WHEN ls.verification_status = 'returned' THEN 'returned'
  WHEN ls.verification_status = 'pending' AND ls.collector_type = 'partner' THEN 'partner_pending'
  WHEN ls.verification_status = 'pending' THEN 'pending_verification'
  WHEN EXISTS (SELECT 1 FROM ssa_record r WHERE r.school_id = s.id AND r.deleted_at IS NULL AND r.verification_status = 'confirmed' AND r.fy = $%[1]d) THEN 'up_to_date'
  WHEN EXISTS (SELECT 1 FROM activity c WHERE c.school_id = s.id AND c.deleted_at IS NULL AND c.ssa_collection_expected
       AND c.delivery_type = 'partner' AND c.status = ANY($%[2]d)) THEN 'partner_pending'
  WHEN EXISTS (SELECT 1 FROM activity c WHERE c.school_id = s.id AND c.deleted_at IS NULL AND c.ssa_collection_expected
       AND c.delivery_type IS DISTINCT FROM 'partner' AND c.status = ANY($%[2]d) AND c.ssa_not_collected_reason IS NULL) THEN 'collection_scheduled'
  WHEN EXISTS (SELECT 1 FROM activity c WHERE c.school_id = s.id AND c.deleted_at IS NULL AND c.ssa_collection_expected
       AND c.fy = $%[1]d AND c.status = ANY($%[3]d) AND COALESCE(c.ssa_not_collected_reason, '') <> '') THEN 'visit_completed_without_scores'
  WHEN EXISTS (SELECT 1 FROM ssa_record r WHERE r.school_id = s.id AND r.deleted_at IS NULL AND r.verification_status = 'confirmed') THEN 'follow_up_due'
  ELSE 'never_assessed' END`, fy, open, delivered)
}

// latestJoin is the school's latest record, as the state reads it.
const latestJoin = `LEFT JOIN LATERAL (SELECT r.verification_status, r.collector_type FROM ssa_record r
  WHERE r.school_id = s.id AND r.deleted_at IS NULL ORDER BY r.date_of_ssa DESC, r.created_at DESC LIMIT 1) ls ON TRUE`

// collection is the Collection view (collection_worklist and
// collection_tiles). It hands on a summary-only reader and an empty page.
func (s *Service) collection(ctx context.Context, p auth.Principal, scope schooldirectory.Scope, query url.Values, now time.Time) ([]*screensv1.PageBlock, bool, error) {
	c := rules.Dashboard.Collection
	if scope.SummaryOnly {
		return nil, false, nil
	}
	fy := schooldirectory.OperationalFY(now)
	schools, args := collectionScope(scope)
	options, err := s.collectionOptions(ctx, schools, args)
	if err != nil {
		return nil, true, err
	}
	chosen := map[string]string{}
	filtered, fargs := schools, slices.Clone(args)
	for _, f := range []struct{ key, column string }{{"district", "s.district_id"}, {"owner", "s.account_owner_id"}, {"school_type", "s.school_type"}} {
		v := strings.TrimSpace(query.Get(f.key))
		if v != "" && slices.ContainsFunc(options[f.key], func(o [2]string) bool { return o[0] == v }) {
			fargs = append(fargs, v)
			filtered += fmt.Sprintf(" AND %s = $%d", f.column, len(fargs))
			chosen[f.key] = v
		}
	}
	if v := strings.TrimSpace(query.Get("project")); v != "" && slices.ContainsFunc(options["project"], func(o [2]string) bool { return o[0] == v }) {
		fargs = append(fargs, v, c.LiveProjectStatuses)
		filtered += fmt.Sprintf(` AND s.id IN (SELECT a.school_id FROM project_school_assignment a JOIN project pr ON pr.id = a.project_id
  WHERE a.project_id = $%d AND pr.deleted_at IS NULL AND pr.status = ANY($%d))`, len(fargs)-1, len(fargs))
		chosen["project"] = v
	}
	n := len(fargs)
	sargs := append(slices.Clone(fargs), fy, c.OpenStatuses, c.DeliveredStatuses)
	state := stateSQL(n+1, n+2, n+3)
	counted := fmt.Sprintf(`SELECT s.id, s.school_id, s.name, COALESCE(d.name, ''), COALESCE(s.account_owner_id, ''), %s AS state
FROM school s LEFT JOIN district d ON d.id = s.district_id %s WHERE %s`, state, latestJoin, filtered)
	counts := map[string]int{}
	rows, err := s.db.Query(ctx, "SELECT state, count(*) FROM ("+counted+") x GROUP BY state", sargs...)
	if err != nil {
		return nil, true, fmt.Errorf("iapages: counting the collection states: %w", err)
	}
	for rows.Next() {
		var st string
		var k int
		if err := rows.Scan(&st, &k); err != nil {
			rows.Close()
			return nil, true, fmt.Errorf("iapages: counting a collection state: %w", err)
		}
		counts[st] = k
	}
	rows.Close()
	listed := c.WorkStates
	if v := strings.TrimSpace(query.Get("state")); slices.ContainsFunc(c.States, func(x [3]string) bool { return x[0] == v }) {
		listed, chosen["state"] = []string{v}, v
	}
	total := 0
	for _, st := range listed {
		total += counts[st]
	}
	number, pages := closedschools.PageOf(query.Get(c.PageParam), total, c.PageSize)
	if pages > 1 && carriedKeys(query, c.PageParam) > 1 {
		// The pager's links keep the request's own query in its order, which
		// the query as Go receives it no longer holds.
		return nil, false, nil
	}
	order := "CASE x.state"
	for i, st := range c.States {
		order += fmt.Sprintf(" WHEN '%s' THEN %d", st[0], i+1)
	}
	order += " ELSE 99 END"
	pargs := append(slices.Clone(sargs), listed, c.PageSize, (number-1)*c.PageSize)
	k := len(pargs)
	rows, err = s.db.Query(ctx, fmt.Sprintf(`SELECT x.* FROM (%s) x WHERE x.state = ANY($%d) ORDER BY %s, x.name, x.id LIMIT $%d OFFSET $%d`,
		counted, k-2, order, k-1, k), pargs...)
	if err != nil {
		return nil, true, fmt.Errorf("iapages: reading the collection worklist: %w", err)
	}
	page := []collectionSchool{}
	for rows.Next() {
		var x collectionSchool
		if err := rows.Scan(&x.id, &x.code, &x.name, &x.districtName, &x.ownerID, &x.state); err != nil {
			rows.Close()
			return nil, true, fmt.Errorf("iapages: reading a worklist school: %w", err)
		}
		page = append(page, x)
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, true, fmt.Errorf("iapages: reading the collection worklist: %w", err)
	}
	table, err := s.worklistTable(ctx, p, page)
	if err != nil {
		return nil, true, err
	}
	unmatched, uargs := unmatchedSSA(scope)
	var unmatchedRows int
	if err := s.db.QueryRow(ctx, "SELECT count(*) FROM unmatched_ssa_record u WHERE "+unmatched, uargs...).Scan(&unmatchedRows); err != nil {
		return nil, true, fmt.Errorf("iapages: counting the unmatched SSA rows: %w", err)
	}
	blocks := []*screensv1.PageBlock{
		collectionFilters(options, chosen),
		tileStrip("Assessment collection", []metricTile{
			tile("Schools Never Assessed", strconv.Itoa(counts["never_assessed"]), "no confirmed SSA on record", "danger", ""),
			tile("SSA Follow-up Due", strconv.Itoa(counts["follow_up_due"]), "confirmed before, none in FY"+fy, "warning", ""),
			tile("SSA Awaiting Verification", strconv.Itoa(counts["pending_verification"]+counts["partner_pending"]),
				"schools whose latest scores wait for a verifier", "info", ""),
			tile("Unmatched SSA Import Rows", strconv.Itoa(unmatchedRows), "imported rows no school in your country matched", "warning", ""),
		}),
		panelOf("Assessment collection worklist"),
		tableBlock(table),
	}
	if pages > 1 {
		blocks = append(blocks, closedschools.PagerPanel(c.PageParam, number, pages, total, c.PageSize, query, rules.QueryKeysNotPassed))
	}
	return blocks, true, nil
}

// carriedKeys counts the query keys the pager carries besides its own.
func carriedKeys(query url.Values, param string) int {
	n := 0
	for key := range query {
		if key != param && !slices.Contains(rules.QueryKeysNotPassed, key) {
			n++
		}
	}
	return n
}

// collectionOptions is _filter_options: the districts, account owners,
// school types and live projects of the reader's schools.
func (s *Service) collectionOptions(ctx context.Context, schools string, args []any) (map[string][][2]string, error) {
	out := map[string][][2]string{}
	read := func(key, sql string, qargs ...any) error {
		rows, err := s.db.Query(ctx, sql, qargs...)
		if err != nil {
			return fmt.Errorf("iapages: reading the %s options: %w", key, err)
		}
		defer rows.Close()
		for rows.Next() {
			var v, label string
			if err := rows.Scan(&v, &label); err != nil {
				return fmt.Errorf("iapages: reading a %s option: %w", key, err)
			}
			out[key] = append(out[key], [2]string{v, label})
		}
		return rows.Err()
	}
	if err := read("district", `SELECT DISTINCT s.district_id, d.name FROM school s JOIN district d ON d.id = s.district_id
WHERE `+schools+` ORDER BY d.name`, args...); err != nil {
		return nil, err
	}
	if err := read("school_type", `SELECT DISTINCT s.school_type, s.school_type FROM school s
WHERE `+schools+` AND COALESCE(s.school_type, '') <> '' ORDER BY s.school_type`, args...); err != nil {
		return nil, err
	}
	for i, t := range out["school_type"] {
		out["school_type"][i][1] = pyTitle(strings.ReplaceAll(t[0], "_", " "))
	}
	pargs := append(slices.Clone(args), rules.Dashboard.Collection.LiveProjectStatuses)
	if err := read("project", fmt.Sprintf(`SELECT pr.id, pr.name FROM project pr WHERE pr.id IN (
  SELECT a.project_id FROM project_school_assignment a JOIN school s ON s.id = a.school_id JOIN project p2 ON p2.id = a.project_id
  WHERE %s AND p2.deleted_at IS NULL AND p2.status = ANY($%d)) ORDER BY pr.name`, schools, len(pargs)), pargs...); err != nil {
		return nil, err
	}
	rows, err := s.db.Query(ctx, `SELECT DISTINCT s.account_owner_id FROM school s WHERE `+schools+` AND COALESCE(s.account_owner_id, '') <> ''`, args...)
	if err != nil {
		return nil, fmt.Errorf("iapages: reading the account owners: %w", err)
	}
	ids := []string{}
	for rows.Next() {
		var id string
		if err := rows.Scan(&id); err != nil {
			rows.Close()
			return nil, fmt.Errorf("iapages: reading an account owner: %w", err)
		}
		ids = append(ids, id)
	}
	rows.Close()
	names, err := s.ownerNames(ctx, ids)
	if err != nil {
		return nil, err
	}
	owners := [][2]string{}
	for _, id := range ids {
		name, ok := names[id]
		if !ok {
			name = "Unmatched owner"
		}
		owners = append(owners, [2]string{id, name})
	}
	sort.SliceStable(owners, func(i, j int) bool { return strings.ToLower(owners[i][1]) < strings.ToLower(owners[j][1]) })
	out["owner"] = owners
	return out, nil
}

// ownerNames is ia_collection._owner_names: an account owner recorded by
// People record or account, named by the person ("Staff member" without a
// name).
func (s *Service) ownerNames(ctx context.Context, ids []string) (map[string]string, error) {
	out := map[string]string{}
	if len(ids) == 0 {
		return out, nil
	}
	rows, err := s.db.Query(ctx, `SELECT sp.id, COALESCE(sp.user_id, ''), COALESCE(NULLIF(u.name, ''), 'Staff member')
FROM staff_profile sp LEFT JOIN "user" u ON u.id = sp.user_id WHERE sp.id = ANY($1) OR sp.user_id = ANY($1)`, ids)
	if err != nil {
		return nil, fmt.Errorf("iapages: reading the owners' names: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var id, user, name string
		if err := rows.Scan(&id, &user, &name); err != nil {
			return nil, fmt.Errorf("iapages: reading an owner's name: %w", err)
		}
		for _, key := range []string{id, user} {
			if key != "" && slices.Contains(ids, key) {
				out[key] = name
			}
		}
	}
	return out, rows.Err()
}

// pyTitle is Python's str.title(): each run of letters capitalised.
func pyTitle(s string) string {
	out := []rune{}
	prev := false
	for _, r := range s {
		letter := (r >= 'a' && r <= 'z') || (r >= 'A' && r <= 'Z')
		switch {
		case letter && !prev:
			out = append(out, []rune(strings.ToUpper(string(r)))...)
		case letter:
			out = append(out, []rune(strings.ToLower(string(r)))...)
		default:
			out = append(out, r)
		}
		prev = letter
	}
	return string(out)
}

func collectionFilters(options map[string][][2]string, chosen map[string]string) *screensv1.PageBlock {
	c := rules.Dashboard.Collection
	filters := []*screensv1.PageFilter{}
	add := func(name, caption, every string, opts [][2]string) {
		if len(opts) == 0 {
			return
		}
		f := &screensv1.PageFilter{Name: name, Value: chosen[name], Caption: caption, Options: []*screensv1.PageFilterOption{{Value: "", Label: every}}}
		for _, o := range opts {
			f.Options = append(f.Options, &screensv1.PageFilterOption{Value: o[0], Label: o[1]})
		}
		filters = append(filters, f)
	}
	states := [][2]string{}
	for _, st := range c.States {
		states = append(states, [2]string{st[0], st[1]})
	}
	add("state", "Collection need", "Every school needing work", states)
	add("district", "District", "Every district", options["district"])
	add("owner", "Account owner", "Every owner", options["owner"])
	add("school_type", "School type", "Every type", options["school_type"])
	add("project", "Special project", "Every school", options["project"])
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Filters{Filters: &screensv1.PageFilters{Filters: filters, Hidden: map[string]string{"view": "collection"}}}}
}

// worklistTable is the page's rows: each school's need, the detail its
// latest record or open visit gives, and its actions.
func (s *Service) worklistTable(ctx context.Context, p auth.Principal, page []collectionSchool) (*screensv1.PageTable, error) {
	c := rules.Dashboard.Collection
	ids := []string{}
	for _, x := range page {
		ids = append(ids, x.id)
	}
	latest := map[string]latestRecord{}
	rows, err := s.db.Query(ctx, `SELECT DISTINCT ON (r.school_id) r.school_id, COALESCE(r.fy, ''), COALESCE(r.verification_status, ''),
  COALESCE(r.return_reason, ''), r.date_of_ssa, r.returned_at
FROM ssa_record r WHERE r.school_id = ANY($1) AND r.deleted_at IS NULL ORDER BY r.school_id, r.date_of_ssa DESC, r.created_at DESC`, ids)
	if err != nil {
		return nil, fmt.Errorf("iapages: reading the latest SSA records: %w", err)
	}
	for rows.Next() {
		var id string
		var r latestRecord
		if err := rows.Scan(&id, &r.fy, &r.status, &r.reason, &r.assessed, &r.returned); err != nil {
			rows.Close()
			return nil, fmt.Errorf("iapages: reading a latest SSA record: %w", err)
		}
		latest[id] = r
	}
	rows.Close()
	visits := map[string]openVisit{}
	rows, err = s.db.Query(ctx, `SELECT DISTINCT ON (a.school_id) a.school_id, COALESCE(a.responsible_staff_id, ''), a.planned_date
FROM activity a WHERE a.school_id = ANY($1) AND a.deleted_at IS NULL AND a.ssa_collection_expected AND a.status = ANY($2)
ORDER BY a.school_id, a.planned_date ASC NULLS LAST`, ids, c.OpenStatuses)
	if err != nil {
		return nil, fmt.Errorf("iapages: reading the open collection visits: %w", err)
	}
	for rows.Next() {
		var id string
		var v openVisit
		if err := rows.Scan(&id, &v.responsible, &v.planned); err != nil {
			rows.Close()
			return nil, fmt.Errorf("iapages: reading an open collection visit: %w", err)
		}
		visits[id] = v
	}
	rows.Close()
	people := []string{}
	for _, x := range page {
		if x.ownerID != "" {
			people = append(people, x.ownerID)
		}
	}
	for _, v := range visits {
		if v.responsible != "" {
			people = append(people, v.responsible)
		}
	}
	names, err := s.ownerNames(ctx, people)
	if err != nil {
		return nil, err
	}
	t := &screensv1.PageTable{Columns: columns("School ID", "School", "District", "Account owner", "Need", "Detail", "")}
	if len(page) == 0 {
		t.EmptyMessage = "No school needs collection work here"
		t.Rows = []*screensv1.PageRow{{Cells: []*screensv1.PageCell{cell("No school needs collection work here Every school in this " +
			"selection has a confirmed SSA for this financial year, or choose another filter.")}}}
		return t, nil
	}
	for _, x := range page {
		owner, ok := names[x.ownerID]
		switch {
		case ok && owner != "":
		case x.ownerID != "":
			owner = "Unmatched owner"
		default:
			owner = "No owner"
		}
		label := x.state
		for _, st := range c.States {
			if st[0] == x.state {
				label = st[1]
			}
		}
		district := x.districtName
		if district == "" {
			district = "—"
		}
		// The school's ID as the web fills in its {% school_code %} tag (the
		// worklist's schools are live).
		code := closedschools.SchoolCode(x.code)
		if x.code == "" {
			code = "—"
		}
		t.Rows = append(t.Rows, &screensv1.PageRow{Cells: []*screensv1.PageCell{
			cell(code), {Text: x.name, Href: "/schools/" + x.id}, cell(district), cell(owner), cell(label),
			cell(collectionDetail(x.state, latest, visits, names, x.id)), {Actions: worklistActions(x)},
		}})
	}
	return t, nil
}

// worklistActions is the row's actions as the feed reads them: Add SSA, and
// Request SSA visit where the school needs a visit, in one menu when there
// are two (Ask owner to collect posts a form, which the feed does not read).
func worklistActions(x collectionSchool) []*screensv1.PageAction {
	request := slices.Contains([]string{"never_assessed", "follow_up_due", "visit_completed_without_scores", "returned"}, x.state)
	add := &screensv1.PageAction{Label: "Add SSA", Enabled: true, Href: "/ssa/manual/?school_id=" + x.code}
	if !request {
		add.Key, add.Primary = "button", true
		return []*screensv1.PageAction{add}
	}
	add.Key = "menu"
	return []*screensv1.PageAction{add,
		{Key: "menu", Label: "Request SSA visit", Enabled: true, Href: "/planning/schedule-modal?school_id=" + x.code, Drawer: true}}
}

// localDate is a moment's local calendar day as _detail writes it.
func localDate(t time.Time) string {
	t = t.In(nairobi)
	return fmt.Sprintf("%d %s", t.Day(), t.Format("Jan 2006"))
}

// collectionDetail is ia_collection._detail.
func collectionDetail(state string, latest map[string]latestRecord, visits map[string]openVisit, names map[string]string, id string) string {
	c := rules.Dashboard.Collection
	record, hasRecord := latest[id]
	visit, hasVisit := visits[id]
	switch {
	case state == "returned" && hasRecord:
		when := ""
		if record.returned != nil {
			when = localDate(*record.returned)
		}
		reason := record.reason
		if reason == "" {
			reason = "no reason recorded"
		}
		return "Returned " + when + ": " + reason
	case (state == "pending_verification" || state == "partner_pending") && hasRecord && record.status == "pending":
		return "Scores dated " + localDate(record.assessed) + " wait for a verifier"
	case (state == "collection_scheduled" || state == "partner_pending") && hasVisit:
		when := ""
		if visit.planned != nil {
			when = fmt.Sprintf("%d %s", visit.planned.Day(), visit.planned.Format("Jan 2006"))
		}
		out := "Planned " + when
		if who := names[visit.responsible]; who != "" {
			out += " · " + who
		}
		return strings.TrimSpace(out)
	case state == "follow_up_due" && hasRecord:
		label, ok := c.VerificationLabels[record.status]
		if !ok {
			label = record.status
		}
		return "Last SSA FY" + record.fy + " (" + strings.ToLower(label) + ")"
	}
	for _, st := range c.States {
		if st[0] == state {
			return st[2]
		}
	}
	return ""
}
