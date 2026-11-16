package iapages

import (
	"context"
	"fmt"
	"net/url"
	"slices"
	"strconv"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// VerificationPath is the Verification Queue (apps.frontend.views.ia_views:
// ia_verification_queue_view and pages/ia/verification_queue.html): the
// staff submissions waiting on this verifier, ranked critical first, then
// overdue, then oldest, with its filters and drill-downs. The figures above
// the filters and the SLA measure are not read by the feed. It reads; it
// writes nothing.
const VerificationPath = "/ia/verification/"

// The queue's constants (ia_views).
const (
	verificationSLAHours = 24
	verificationPageSize = 50
)

var (
	criticalTypes   = []string{"core_visit", "core_training", "baseline_ssa_visit"}
	reviewable      = []string{"completed", "ia_verified", "closed"}
	queueDrilldowns = map[string]map[string]string{
		"evidence": {"ready": "Evidence ready for review"},
		"age":      {"overdue": "Waiting longer than 24 hours"},
		"sf_id":    {"missing": "Delivered work with no Salesforce ID"},
	}
	// The query the queue reads, in the order its form sends it.
	verificationQuery = []string{"fy", "activity_type", "district", "evidence", "age", "sf_id", "quarter", "core_school",
		"staff", "month", "region", "cluster", "school", "partner", "project", "status", "q", "page"}
	verificationTypes = [][2]string{{"school_visit", "School Visit"}, {"training", "Training"},
		{"cluster_meeting", "Cluster Meeting"}, {"core_visit", "Core Visit"}, {"core_training", "Core Training"}}
)

type queued struct {
	id, fy, quarter, kind, delivery, salesforce, responsible string
	schoolCode, schoolName, clusterName                      *string
	submitted                                                time.Time
}

// likeArg is icontains: the value with LIKE's own characters escaped.
func likeArg(v string) string {
	r := strings.NewReplacer(`\`, `\\`, `%`, `\%`, `_`, `\_`)
	return "%" + r.Replace(v) + "%"
}

// staffNamed is _ia_staff_ids_named: the People records and accounts whose
// person's name contains value, as a sub-select.
func staffNamed(arg func(any) string, value string) string {
	v := arg(likeArg(value))
	return `(SELECT sp.id FROM staff_profile sp JOIN "user" u ON u.id = sp.user_id WHERE u.name ILIKE ` + v +
		` UNION SELECT u.id FROM "user" u WHERE u.name ILIKE ` + v + `)`
}

func (s *Service) verification(ctx context.Context, p auth.Principal, role Role, query url.Values) (*screensv1.GetPageResponse, bool, error) {
	for key := range query {
		if !slices.Contains(verificationQuery, key) {
			return nil, false, nil
		}
	}
	now := s.now()
	where, args, err := reach(ctx, s.db, p, now, nil)
	if err != nil {
		return nil, true, err
	}
	arg := func(v any) string { args = append(args, v); return "$" + strconv.Itoa(len(args)) }
	drill := map[string]string{}
	for key, options := range queueDrilldowns {
		if _, ok := options[query.Get(key)]; ok {
			drill[key] = query.Get(key)
		}
	}
	missing := drill["sf_id"] == "missing"
	overdueBefore := now.Add(-verificationSLAHours * time.Hour)
	conds := []string{"a.deleted_at IS NULL", where}
	if missing {
		conds = append(conds, "a.status = ANY("+arg(reviewable)+")", "COALESCE(a.salesforce_activity_id, '') = ''")
	} else {
		// _ia_staff_queue: staff submissions with their Salesforce ID, not a
		// lead's to verify, never the reader's own.
		conds = append(conds, "a.status = 'awaiting_ia_verification'", "a.delivery_type IS DISTINCT FROM 'partner'",
			"COALESCE(a.salesforce_activity_id, '') <> ''")
		args = append(args, rules.LeadVerifiedRoles, rules.LeadRole)
		conds = append(conds, "NOT COALESCE("+leadVerifiedSQL(len(args)-1)+", FALSE)")
		own := []string{p.UserID}
		if p.StaffProfileID != "" {
			own = append(own, p.StaffProfileID)
		}
		conds = append(conds, "(a.responsible_staff_id IS NULL OR NOT a.responsible_staff_id = ANY("+arg(own)+"))")
	}
	if drill["age"] == "overdue" {
		conds = append(conds, "a.submitted_to_ia_at <= "+arg(overdueBefore))
	}
	eq := func(param, column string) {
		if v := query.Get(param); v != "" {
			conds = append(conds, column+" = "+arg(v))
		}
	}
	eq("fy", "a.fy")
	eq("quarter", "a.quarter")
	if m, err := strconv.Atoi(query.Get("month")); err == nil {
		conds = append(conds, "a.planned_month = "+arg(m))
	}
	eq("region", "s.region_id")
	if v := strings.TrimSpace(query.Get("district")); v != "" {
		id, like := arg(v), arg(likeArg(v))
		conds = append(conds, "(s.district_id = "+id+" OR sd.name ILIKE "+like+" OR ed.name ILIKE "+like+")")
	}
	eq("cluster", "a.cluster_id")
	eq("school", "a.school_id")
	if v := strings.TrimSpace(query.Get("staff")); v != "" {
		conds = append(conds, "(a.responsible_staff_id IN "+staffNamed(arg, v)+" OR a.responsible_staff_id = "+arg(v)+")")
	}
	eq("partner", "a.assigned_partner_id")
	eq("activity_type", "a.activity_type")
	eq("project", "a.project_id")
	if query.Get("core_school") == "true" {
		conds = append(conds, "s.school_type = 'core'")
	}
	eq("status", "a.status")
	if v := strings.TrimSpace(query.Get("q")); v != "" {
		like := arg(likeArg(v))
		conds = append(conds, "(s.name ILIKE "+like+" OR s.school_id ILIKE "+like+" OR a.salesforce_activity_id ILIKE "+like+
			" OR sd.name ILIKE "+like+" OR a.responsible_staff_id IN "+staffNamed(arg, v)+")")
	}
	sql := `FROM activity a LEFT JOIN school s ON s.id = a.school_id LEFT JOIN cluster cl ON cl.id = a.cluster_id
		LEFT JOIN district sd ON sd.id = s.district_id LEFT JOIN district ed ON ed.id = a.event_district_id
		WHERE ` + strings.Join(conds, " AND ")
	var total int
	if err := s.db.QueryRow(ctx, "SELECT COUNT(*) "+sql, args...).Scan(&total); err != nil {
		return nil, true, fmt.Errorf("iapages: counting the verification queue: %w", err)
	}
	pages := max(1, (total+verificationPageSize-1)/verificationPageSize)
	page, err := strconv.Atoi(query.Get("page"))
	if err != nil || page < 1 {
		page = 1
	}
	page = min(page, pages)
	rows, err := s.db.Query(ctx, `SELECT a.id, COALESCE(a.fy, ''), COALESCE(a.quarter, ''), COALESCE(a.activity_type, ''),
		COALESCE(a.delivery_type, ''), COALESCE(a.salesforce_activity_id, ''), COALESCE(a.responsible_staff_id, ''),
		s.school_id, s.name, cl.name, COALESCE(a.submitted_to_ia_at, a.updated_at) `+sql+`
		ORDER BY CASE WHEN a.activity_type = ANY(`+arg(criticalTypes)+`) THEN 0 ELSE 1 END,
		         CASE WHEN a.submitted_to_ia_at <= `+arg(overdueBefore)+` THEN 0 ELSE 1 END,
		         COALESCE(a.submitted_to_ia_at, a.updated_at), a.id
		LIMIT `+strconv.Itoa(verificationPageSize)+` OFFSET `+strconv.Itoa((page-1)*verificationPageSize), args...)
	if err != nil {
		return nil, true, fmt.Errorf("iapages: reading the verification queue: %w", err)
	}
	list, err := pgx.CollectRows(rows, func(r pgx.CollectableRow) (queued, error) {
		var q queued
		return q, r.Scan(&q.id, &q.fy, &q.quarter, &q.kind, &q.delivery, &q.salesforce, &q.responsible,
			&q.schoolCode, &q.schoolName, &q.clusterName, &q.submitted)
	})
	if err != nil {
		return nil, true, fmt.Errorf("iapages: reading the verification queue: %w", err)
	}
	ids := []string{}
	for _, q := range list {
		if q.responsible != "" {
			ids = append(ids, q.responsible)
		}
	}
	names, err := staffNames(ctx, s.db, ids)
	if err != nil {
		return nil, true, err
	}
	v := verificationView{p: p, role: role, query: query, drill: drill, missing: missing, list: list, names: names,
		now: now, total: total, page: page, pages: pages}
	return v.response(), true, nil
}

type verificationView struct {
	p                  auth.Principal
	role               Role
	query              url.Values
	drill              map[string]string
	missing            bool
	list               []queued
	names              map[string]string
	now                time.Time
	total, page, pages int
}

// keptQuery is the reader's query without key and the page, in the form's
// order (a drill-down chip's Remove).
func keptQuery(query url.Values, key string) string {
	parts := []string{}
	for _, k := range verificationQuery {
		if k == key || k == "page" {
			continue
		}
		for _, v := range query[k] {
			parts = append(parts, url.QueryEscape(k)+"="+url.QueryEscape(v))
		}
	}
	if len(parts) == 0 {
		return VerificationPath
	}
	return VerificationPath + "?" + strings.Join(parts, "&")
}

// djangoTitle is the title filter: each word's first letter up, the rest down.
func djangoTitle(s string) string {
	out := []rune(strings.ToLower(s))
	start := true
	for i, r := range out {
		letter := (r >= 'a' && r <= 'z') || (r >= '0' && r <= '9')
		if start && r >= 'a' && r <= 'z' {
			out[i] = r - 'a' + 'A'
		}
		start = !letter
	}
	return string(out)
}

func (v verificationView) filters() *screensv1.PageBlock {
	selected := func(value string, options []*screensv1.PageFilterOption) string {
		for _, o := range options {
			if o.Value == value {
				return value
			}
		}
		return options[0].Value
	}
	fy := []*screensv1.PageFilterOption{{Value: "", Label: "All FYs"}}
	current, _ := strconv.Atoi(schooldirectory.OperationalFY(v.now))
	for i := 0; i < 4; i++ {
		y := strconv.Itoa(current - i)
		fy = append(fy, &screensv1.PageFilterOption{Value: y, Label: "FY " + y})
	}
	kinds := []*screensv1.PageFilterOption{{Value: "", Label: "All types"}}
	for _, t := range verificationTypes {
		kinds = append(kinds, &screensv1.PageFilterOption{Value: t[0], Label: t[1]})
	}
	quarters := []*screensv1.PageFilterOption{{Value: "", Label: "All quarters"}}
	for _, q := range []string{"Q1", "Q2", "Q3", "Q4"} {
		quarters = append(quarters, &screensv1.PageFilterOption{Value: q, Label: q})
	}
	scope := []*screensv1.PageFilterOption{{Value: "", Label: "All schools"}, {Value: "true", Label: "Core schools only"}}
	f := func(name, label string, options []*screensv1.PageFilterOption) *screensv1.PageFilter {
		return &screensv1.PageFilter{Name: name, Label: label, Value: selected(v.query.Get(name), options), Options: options}
	}
	// A drill-down travels with every filter change (a hidden input each).
	var hidden map[string]string
	if len(v.drill) > 0 {
		hidden = map[string]string{}
		for k, value := range v.drill {
			hidden[k] = value
		}
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Filters{Filters: &screensv1.PageFilters{Filters: []*screensv1.PageFilter{
		f("fy", "Fiscal year", fy), f("activity_type", "Activity type", kinds), f("quarter", "Quarter", quarters),
		f("core_school", "School scope", scope),
	}, Hidden: hidden}}}
}

func (v verificationView) response() *screensv1.GetPageResponse {
	header := &screensv1.PageHeader{Eyebrow: "Verification", Title: "Verification Queue",
		Description: "Review implementation evidence, cross-reference Salesforce records and certify school improvement activities."}
	if slices.Contains(rules.ExportRoles, v.p.ActiveRole) {
		// {% querystring export='xlsx' page=None %}: the reader's query with
		// the export and without its page, its keys in order.
		keys := []string{"export"}
		for _, k := range verificationQuery {
			if k != "page" && len(v.query[k]) > 0 {
				keys = append(keys, k)
			}
		}
		slices.Sort(keys)
		parts := []string{}
		for _, k := range keys {
			if k == "export" {
				parts = append(parts, "export=xlsx")
				continue
			}
			for _, value := range v.query[k] {
				parts = append(parts, url.QueryEscape(k)+"="+url.QueryEscape(value))
			}
		}
		href := VerificationPath + "?" + strings.Join(parts, "&")
		header.Actions = []*screensv1.PageAction{{Key: "export", Label: "Export", Enabled: true, Href: href, Download: true}}
	}
	blocks := workspaceStrip(v.role)
	blocks = append(blocks, v.filters())
	if len(v.drill) > 0 {
		items := []*screensv1.PagePanelItem{}
		for _, key := range []string{"evidence", "age", "sf_id"} {
			value, ok := v.drill[key]
			if !ok {
				continue
			}
			label := queueDrilldowns[key][value]
			items = append(items, &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Text{Text: label + " Remove"},
				TextLinks: []*screensv1.PageLink{{Text: "Remove", Href: keptQuery(v.query, key)}}})
		}
		if v.missing {
			items = append(items, &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Text{
				Text: "Completed, verified or closed work in your country that carries no Salesforce Activity ID."}})
		}
		blocks = append(blocks, &screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{Items: items}}})
	}
	blocks = append(blocks, &screensv1.PageBlock{Kind: &screensv1.PageBlock_Table{Table: v.table()}})
	if v.pages > 1 {
		blocks = append(blocks, v.pager())
	}
	return &screensv1.GetPageResponse{Header: header, Blocks: blocks, WebPath: VerificationPath}
}

var verificationColumns = []string{"Activity or SSA record", "School ID", "School or cluster", "Record type", "Submitted by",
	"Salesforce ID status", "Submission date", "Age", "Risk", "Next action"}

func (v verificationView) table() *screensv1.PageTable {
	t := &screensv1.PageTable{}
	for _, c := range verificationColumns {
		t.Columns = append(t.Columns, &screensv1.PageColumn{Label: c})
	}
	if len(v.list) == 0 {
		title, message := "No Activities Awaiting Verification", "All submitted Activities have been reviewed."
		if len(v.drill) > 0 {
			title, message = "Nothing matches this view", "No records in your country match the filter applied from the dashboard."
		}
		t.EmptyMessage = message
		t.Rows = []*screensv1.PageRow{{Cells: []*screensv1.PageCell{{Text: title + " " + message}}}}
		return t
	}
	profiles := slices.Contains(rules.SchoolProfileRoles, v.p.ActiveRole)
	for _, q := range v.list {
		review := VerificationPath + q.id + "/"
		id := q.id
		if r := []rune(id); len(r) > 8 {
			id = string(r[:8])
		}
		code := "—"
		if q.schoolCode != nil && *q.schoolCode != "" {
			code = *q.schoolCode
		}
		cluster := "No cluster"
		if q.clusterName != nil && *q.clusterName != "" {
			cluster = *q.clusterName
		}
		place := &screensv1.PageCell{Text: "Cluster-wide " + cluster}
		if q.schoolName != nil && *q.schoolName != "" {
			place = &screensv1.PageCell{Text: *q.schoolName + " " + cluster}
			if profiles && code != "—" {
				place.Href = "/schools/" + code
			}
		}
		owner, ok := v.names[q.responsible]
		if !ok {
			owner = q.responsible
		}
		if owner == "" {
			owner = "Unassigned"
		}
		delivery := "None"
		if q.delivery != "" {
			delivery = djangoTitle(q.delivery)
		}
		status := "Confirm ID"
		if v.missing {
			status = "Missing"
		}
		if q.salesforce != "" {
			status += " " + q.salesforce
		}
		age := max(0, int(v.now.Sub(q.submitted).Seconds())/3600)
		ageLabel := strconv.Itoa(age) + "h"
		if age >= 24 {
			ageLabel = fmt.Sprintf("%dd %dh", age/24, age%24)
		}
		risk := "Standard"
		switch {
		case slices.Contains(criticalTypes, q.kind):
			risk = "Critical"
		case age >= verificationSLAHours:
			risk = "High"
		}
		t.Rows = append(t.Rows, &screensv1.PageRow{Cells: []*screensv1.PageCell{
			{Text: "#" + id + " FY " + q.fy + " · " + q.quarter, Href: review},
			{Text: code},
			place,
			{Text: strings.ReplaceAll(djangoTitle(q.kind), "_", " ")},
			{Text: owner + " " + delivery},
			{Text: status},
			{Text: q.submitted.In(zone).Format("2 Jan 2006, 15:04")},
			{Text: ageLabel},
			{Text: risk},
			{Text: "Review ••• Compare evidence View audit timeline", Href: review},
		}})
	}
	return t
}

// pager is the queue's own page links (page_obj): where it is, then Prev and
// Next as the feed reads each link (its label, and its two spans).
func (v verificationView) pager() *screensv1.PageBlock {
	links := []*screensv1.PagePagerPage{{Label: fmt.Sprintf("Page %d of %d · %d records", v.page, v.pages, v.total)}}
	if v.page > 1 {
		links = append(links, &screensv1.PagePagerPage{Label: "Prev", Href: VerificationPath + "?page=" + strconv.Itoa(v.page-1)},
			&screensv1.PagePagerPage{Label: "Prev"}, &screensv1.PagePagerPage{Label: "‹"})
	}
	if v.page < v.pages {
		links = append(links, &screensv1.PagePagerPage{Label: "Next", Href: VerificationPath + "?page=" + strconv.Itoa(v.page+1)},
			&screensv1.PagePagerPage{Label: "Next"}, &screensv1.PagePagerPage{Label: "›"})
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Pager{Pager: &screensv1.PagePager{Pages: links}}}
}
