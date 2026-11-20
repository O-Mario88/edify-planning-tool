// Package ssaverify is SSA Verification (/ssa/verification/): the SSA
// records in the reader's reach waiting for a verifier other than their
// collector, or sent back, as the existing queue draws them
// (apps.frontend.views.ssa_views.ssa_verification_queue_view over
// apps.ssa.services.readable_records and verifiable_records, and
// pages/ssa/verification_queue.html) and the app's feed reads them.
// Confirming and returning stay with the existing application.
//
// The doors, roles, labels and page size are exported to rules.json by
// `manage.py export_ssa_verification_rules`;
// apps/ssa/test_ssa_verification_rules_export.py fails when the two differ.
package ssaverify

import (
	"context"
	_ "embed"
	"encoding/json"
	"fmt"
	"net/url"
	"slices"
	"strconv"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/closedschools"
	registry "github.com/O-Mario88/edify-planning-tool/platform/backend/internal/country"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/decisionlog"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pagegate"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// Path is the page.
const Path = "/ssa/verification/"

//go:embed rules.json
var rulesJSON []byte

type roleRules struct {
	Page     bool               `json:"page"`
	Strip    *decisionlog.Strip `json:"strip"`
	IAVerify bool               `json:"ia_verify"`
}

var rules = func() (r struct {
	Roles               map[string]roleRules `json:"roles"`
	CountryDirectorRole string               `json:"country_director_role"`
	LeadRole            string               `json:"lead_role"`
	IARole              string               `json:"ia_role"`
	QueueStatuses       [][2]string          `json:"queue_statuses"`
	Sources             map[string]string    `json:"sources"`
	StaffKeyedSource    string               `json:"staff_keyed_source"`
	CollectorKinds      map[string]string    `json:"collector_kinds"`
	VisitReviewRoles    []string             `json:"visit_review_roles"`
	PageSize            int                  `json:"page_size"`
}) {
	if err := json.Unmarshal(rulesJSON, &r); err != nil || len(r.Roles) == 0 || len(r.QueueStatuses) == 0 || r.PageSize == 0 {
		panic(fmt.Sprintf("ssaverify: the embedded rules are unreadable: %v", err))
	}
	return r
}()

var zone = func() *time.Location {
	z, err := time.LoadLocation("Africa/Kampala")
	if err != nil {
		panic(fmt.Sprintf("ssaverify: loading the zone: %v", err))
	}
	return z
}()

// Service answers the queue from the existing database.
type Service struct {
	db  schooldirectory.Querier
	now func() time.Time
}

// NewService is the queue over db.
func NewService(db schooldirectory.Querier, now func() time.Time) *Service {
	return &Service{db: db, now: now}
}

// record is one SSA record as the queue's row reads it.
type record struct {
	id, schoolPK, code, school, district string
	// live is whether the school is live: the web fills in a live school's ID.
	live                                        bool
	collector, uploader, returner, kind, source string
	reason, visitID, visitDelivery              string
	date                                        *time.Time
	average                                     *float64
	decidable                                   bool
}

// args builds numbered arguments.
type args []any

func (a *args) add(v any) string {
	*a = append(*a, v)
	return "$" + strconv.Itoa(len(*a))
}

// readable is readable_records over ssa_record r with its school s: a
// country reader's country, a portfolio reader's schools, nobody else's.
// The country is the school's in the registry (country.SchoolIn,
// docs/migration/80 §14): the existing rule also placed a school with no
// region and no country-bound holder in every country.
func readable(scope schooldirectory.Scope, a *args) string {
	switch {
	case scope.CountryScope:
		if scope.Country == "" {
			return "r.deleted_at IS NULL"
		}
		return "r.deleted_at IS NULL AND " + registry.SchoolIn("s", a.add(scope.CountryIDs()))
	case len(scope.SchoolIDs) > 0:
		return "r.deleted_at IS NULL AND r.school_id = ANY(" + a.add(scope.SchoolIDs) + ")"
	}
	return "FALSE"
}

// isLead is lead_clears_own_work: the lead role in use and held.
func isLead(p auth.Principal) bool {
	return p.ActiveRole == rules.LeadRole && slices.Contains(p.Roles, rules.LeadRole)
}

// decides is verifiable_records' condition beyond the readable, pending
// records: an IA verifier decides all, the Country Director those Impact
// Assessment collected, a lead their officers' staff scores; never anyone's
// own. "" when the reader decides none.
func decides(p auth.Principal, scope schooldirectory.Scope, own []string, a *args) string {
	var cond string
	switch {
	case rules.Roles[p.ActiveRole].IAVerify:
		cond = "TRUE"
	case p.ActiveRole == rules.CountryDirectorRole && scope.CountryFromRegistry:
		// In a country whose roles come from the registry, Impact
		// Assessment is the people assigned it there (docs/migration/80, §14),
		// a revoked assignment still marking what they collected.
		ia := fmt.Sprintf(`(SELECT hr.user_id FROM country_registry.country_role_assignment hr
  WHERE hr.country_id::text = %s AND hr.role_name = %s)`, a.add(scope.CountryID), a.add(rules.IARole))
		cond = fmt.Sprintf("(r.collector_type = 'ia' OR r.collected_by_user_id IN %[1]s OR r.uploaded_by IN %[1]s)", ia)
	case p.ActiveRole == rules.CountryDirectorRole:
		ia := fmt.Sprintf(`(SELECT id FROM "user" WHERE roles @> ARRAY[%s]::varchar[])`, a.add(rules.IARole))
		cond = fmt.Sprintf("(r.collector_type = 'ia' OR r.collected_by_user_id IN %[1]s OR r.uploaded_by IN %[1]s)", ia)
	case isLead(p):
		sup := scope.SupervisedStaffIDs
		if sup == nil {
			sup = []string{}
		}
		n := a.add(sup)
		cond = fmt.Sprintf(`(r.collected_by_user_id IN (SELECT unnest(%[1]s::varchar[]) UNION SELECT user_id FROM staff_profile WHERE id = ANY(%[1]s) AND user_id IS NOT NULL)
  AND r.collector_type IS DISTINCT FROM 'partner')`, n)
	default:
		return ""
	}
	if len(own) > 0 {
		o := a.add(own)
		cond += fmt.Sprintf(" AND NOT COALESCE(r.collected_by_user_id = ANY(%[1]s), FALSE) AND NOT COALESCE(r.uploaded_by = ANY(%[1]s), FALSE)", o)
	}
	return cond
}

const from = `FROM ssa_record r JOIN school s ON s.id = r.school_id `

// Build answers Path.
func (s *Service) Build(ctx context.Context, p auth.Principal, path string, query url.Values) (*screensv1.GetPageResponse, bool, error) {
	if path != Path {
		return nil, false, nil
	}
	role, ok := rules.Roles[p.ActiveRole]
	if !ok || !role.Page {
		return nil, true, pagegate.ErrNotAvailable
	}
	status := query.Get("status")
	if !slices.ContainsFunc(rules.QueueStatuses, func(q [2]string) bool { return q[0] == status }) {
		status = "pending"
	}
	mine := query.Get("mine") == "1"
	scope, err := schooldirectory.ResolveScope(ctx, s.db, p, s.now())
	if err != nil {
		return nil, true, fmt.Errorf("ssaverify: resolving the reader's scope: %w", err)
	}
	own := []string{}
	for _, id := range []string{p.UserID, scope.StaffID} {
		if id != "" {
			own = append(own, id)
		}
	}
	// Each query numbers only the arguments it uses: Postgres refuses one it
	// cannot type.
	build := func(decide, list bool) (a *args, decidable, listed string) {
		a = &args{}
		reach := readable(scope, a)
		decidable = "FALSE"
		if decide {
			if d := decides(p, scope, own, a); d != "" {
				decidable = "r.verification_status = 'pending' AND " + d
			}
		}
		listed = reach
		if list {
			listed += " AND r.verification_status = " + a.add(status)
			if mine {
				listed += " AND r.collected_by_user_id = ANY(" + a.add(own) + ")"
			}
		}
		return a, decidable, listed
	}
	a, _, listed := build(false, true)
	var total int
	if err := s.db.QueryRow(ctx, `SELECT count(*) `+from+`WHERE `+listed, *a...).Scan(&total); err != nil {
		return nil, true, fmt.Errorf("ssaverify: counting the queue: %w", err)
	}
	size := rules.PageSize
	number, pages := closedschools.PageOf(query.Get("records_page"), total, size)
	a, decidable, listed := build(true, true)
	limit, offset := a.add(size), a.add((number-1)*size)
	rows, err := s.db.Query(ctx, `SELECT r.id, s.id, COALESCE(s.school_id, ''), s.deleted_at IS NULL, s.name, COALESCE(d.name, ''),
  COALESCE(r.collected_by_user_id, ''), COALESCE(r.uploaded_by, ''), COALESCE(r.returned_by_user_id, ''), COALESCE(r.collector_type, ''),
  COALESCE(r.verification_source, ''), COALESCE(r.return_reason, ''), COALESCE(v.id, ''), COALESCE(v.delivery_type, ''),
  r.date_of_ssa, r.average_score, COALESCE(`+decidable+`, FALSE)
`+from+`LEFT JOIN district d ON d.id = s.district_id LEFT JOIN activity v ON v.id = r.source_activity_id
WHERE `+listed+` ORDER BY r.date_of_ssa DESC, r.id LIMIT `+limit+` OFFSET `+offset, *a...)
	if err != nil {
		return nil, true, fmt.Errorf("ssaverify: reading the queue: %w", err)
	}
	list, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (record, error) {
		var x record
		return x, row.Scan(&x.id, &x.schoolPK, &x.code, &x.live, &x.school, &x.district, &x.collector, &x.uploader, &x.returner, &x.kind,
			&x.source, &x.reason, &x.visitID, &x.visitDelivery, &x.date, &x.average, &x.decidable)
	})
	if err != nil {
		return nil, true, fmt.Errorf("ssaverify: reading the queue: %w", err)
	}
	ids := []string{}
	for _, x := range list {
		ids = append(ids, x.collector, x.uploader, x.returner)
	}
	names, err := s.names(ctx, ids)
	if err != nil {
		return nil, true, err
	}
	return page(p, role.Strip, status, mine, list, names, own, number, pages, total, query), true, nil
}

func (s *Service) names(ctx context.Context, ids []string) (map[string]string, error) {
	out := map[string]string{}
	rows, err := s.db.Query(ctx, `SELECT id, COALESCE(name, '') FROM "user" WHERE id = ANY($1)`, ids)
	if err != nil {
		return nil, fmt.Errorf("ssaverify: reading names: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var id, name string
		if err := rows.Scan(&id, &name); err != nil {
			return nil, fmt.Errorf("ssaverify: reading names: %w", err)
		}
		out[id] = name
	}
	return out, rows.Err()
}

// collectorLabel is _collector_label.
func collectorLabel(x record, names map[string]string) string {
	who := x.collector
	if who == "" {
		who = x.uploader
	}
	kind, ok := rules.CollectorKinds[x.kind]
	if !ok {
		kind = pyTitle(x.kind)
	}
	if n := names[who]; n != "" {
		return n + " (" + kind + ")"
	}
	return kind
}

// sourceLabel is apps.ssa.creation.source_label.
func sourceLabel(x record) string {
	if x.source == rules.StaffKeyedSource && x.visitID != "" {
		return "Keyed on a visit"
	}
	if l, ok := rules.Sources[x.source]; ok {
		return l
	}
	return "Recorded"
}

// pyTitle is str.title() over ASCII words.
func pyTitle(s string) string {
	var b strings.Builder
	prev := false
	for _, r := range s {
		letter := (r >= 'a' && r <= 'z') || (r >= 'A' && r <= 'Z')
		switch {
		case letter && !prev:
			b.WriteString(strings.ToUpper(string(r)))
		case letter:
			b.WriteString(strings.ToLower(string(r)))
		default:
			b.WriteRune(r)
		}
		prev = letter
	}
	return b.String()
}

// floatText is Python's str(float).
func floatText(x float64) string {
	s := strconv.FormatFloat(x, 'f', -1, 64)
	if !strings.ContainsAny(s, ".eEIN") {
		s += ".0"
	}
	return s
}

func statusLabel(status string) string {
	for _, q := range rules.QueueStatuses {
		if q[0] == status {
			return q[1]
		}
	}
	return status
}

// page is pages/ssa/verification_queue.html as the feed reads it.
func page(p auth.Principal, strip *decisionlog.Strip, status string, mine bool, list []record, names map[string]string, own []string,
	number, pages, total int, query url.Values) *screensv1.GetPageResponse {
	header := &screensv1.PageHeader{Eyebrow: "Quality & Insights", Title: "SSA Verification",
		BackLabel: "Back to Quality Center", BackHref: "/admin-panel/data-quality-center",
		Description: "Every SSA waits here until a verifier other than the person who collected or uploaded it confirms it: the Programme Lead for their officers' scores (approving the visit confirms the scores keyed on it), an Impact Assessment officer in the school's country, or the Country Director for scores Impact Assessment collected. A Programme Lead's own scores count as they are entered. Only confirmed scores count in outcomes, targets and planning."}
	blocks := []*screensv1.PageBlock{}
	if strip != nil {
		tabs := &screensv1.PageLinkTabs{Label: strip.Label, Scrolls: strip.Scrolls}
		for _, x := range strip.Tabs {
			tabs.Tabs = append(tabs.Tabs, &screensv1.PageLinkTab{Label: x.Label, Href: x.Href, Active: x.Active})
		}
		blocks = append(blocks, &screensv1.PageBlock{Kind: &screensv1.PageBlock_LinkTabs{LinkTabs: tabs}})
	}
	statusOptions := []*screensv1.PageFilterOption{}
	for _, q := range rules.QueueStatuses {
		statusOptions = append(statusOptions, &screensv1.PageFilterOption{Value: q[0], Label: q[1]})
	}
	mineValue := ""
	if mine {
		mineValue = "1"
	}
	// The card's heading reads as a panel of its title; its subtitle (the
	// counts) is not read.
	blocks = append(blocks, &screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{Title: statusLabel(status)}}},
		&screensv1.PageBlock{Kind: &screensv1.PageBlock_Filters{Filters: &screensv1.PageFilters{Filters: []*screensv1.PageFilter{
			{Name: "status", Value: status, Caption: "Records", Options: statusOptions},
			{Name: "mine", Value: mineValue, Caption: "Collected by", Options: []*screensv1.PageFilterOption{{Value: "", Label: "Anyone"}, {Value: "1", Label: "Me"}}},
		}}}})
	t := &screensv1.PageTable{}
	if len(list) == 0 {
		message, hint := "No pending SSA verification records in queue.", "Keyed, imported and partner scores appear here until a different verifier confirms them."
		if status == "returned" {
			message, hint = "No returned SSA records", "Scores a verifier sends back appear here until they are re-keyed."
		}
		t.EmptyMessage = message
		t.Rows = []*screensv1.PageRow{{Cells: []*screensv1.PageCell{{Text: message + " " + hint}}}}
	} else {
		for _, col := range []string{"School ID", "School", "District", "Collected by", "How it arrived", "Date of SSA", "Average", "Status", ""} {
			t.Columns = append(t.Columns, &screensv1.PageColumn{Label: col})
		}
		for _, x := range list {
			t.Rows = append(t.Rows, row(p, x, status, names, own))
		}
	}
	blocks = append(blocks, &screensv1.PageBlock{Kind: &screensv1.PageBlock_Table{Table: t}})
	if pages > 1 {
		blocks = append(blocks, closedschools.PagerPanel("records_page", number, pages, total, rules.PageSize, query, nil))
	}
	return &screensv1.GetPageResponse{Header: header, Blocks: blocks, WebPath: Path}
}

// state is the row's Status words and tone.
func state(x record, status string, canDecide, isOwn bool, names map[string]string) (string, string) {
	switch {
	case status == "returned":
		by, ok := names[x.returner]
		if !ok {
			by = "a verifier"
		}
		reason := x.reason
		if reason == "" {
			reason = "no reason recorded"
		}
		return "Returned by " + by + ": " + reason, "danger"
	case canDecide:
		return "Awaiting your verification", "warning"
	case isOwn:
		return "Your scores: a different verifier confirms them", "neutral"
	}
	return "Awaiting a verifier", "neutral"
}

// visitURL is the door the reader opens the visit through.
func visitURL(p auth.Principal, x record) string {
	switch {
	case x.visitID == "":
		return ""
	case slices.Contains(rules.VisitReviewRoles, p.ActiveRole) && x.visitDelivery == "partner":
		return "/ia/partner-evidence/" + x.visitID + "/"
	case slices.Contains(rules.VisitReviewRoles, p.ActiveRole):
		return "/ia/verification/" + x.visitID + "/"
	}
	return "/my-plan/" + x.visitID
}

// row is one record's row: its words, its state, and the visit link or the
// decision menu (its Confirm form is not read).
func row(p auth.Principal, x record, status string, names map[string]string, own []string) *screensv1.PageRow {
	isOwn := slices.Contains(own, x.collector) || slices.Contains(own, x.uploader)
	canDecide := x.decidable && status == "pending"
	words, _ := state(x, status, canDecide, isOwn, names) // the feed reads data-edify-tone, not data-tone
	visit := visitURL(p, x)
	code := "—"
	if x.code != "" {
		// The school's ID as the web fills in its {% school_code %} tag.
		code = closedschools.SchoolCode("")
		if x.live {
			code = x.code
		}
	}
	district := x.district
	if district == "" {
		district = "—"
	}
	date := "—"
	if x.date != nil {
		date = x.date.In(zone).Format("2 Jan 2006")
	}
	average := "—"
	if x.average != nil {
		average = floatText(*x.average) + " / 10"
	}
	actions := &screensv1.PageCell{}
	switch {
	case canDecide:
		if visit != "" {
			actions.Actions = append(actions.Actions, &screensv1.PageAction{Key: "menu", Label: "Open visit", Enabled: true, Href: visit})
		}
		actions.Actions = append(actions.Actions, &screensv1.PageAction{Key: "menu", Label: "Return", Enabled: true,
			Href: "/ssa/verification/" + x.id + "/return-drawer", Drawer: true})
	case visit != "":
		actions.Actions = []*screensv1.PageAction{{Key: "button", Label: "Open visit", Primary: true, Enabled: true, Href: visit}}
	}
	return &screensv1.PageRow{Cells: []*screensv1.PageCell{
		{Text: code}, {Text: closedschools.Collapse(x.school), Href: "/schools/" + x.schoolPK + "#ssa-timeline"}, {Text: closedschools.Collapse(district)},
		{Text: closedschools.Collapse(collectorLabel(x, names))}, {Text: sourceLabel(x)}, {Text: date}, {Text: average},
		{Text: closedschools.Collapse(words)}, actions,
	}}
}
