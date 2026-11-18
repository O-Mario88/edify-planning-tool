// Package peopledirectory is the People Directory (/staff): the active
// people in the reader's reach with their role, place, reporting line,
// onboarding state and field workload, as the existing page draws them
// (apps.frontend.views.staff_views.staff_directory_view and
// pages/staff/index.html) and the app's feed reads them.
//
// The doors, role words, statuses and page size are exported to rules.json
// by `manage.py export_people_directory_rules`;
// apps/accounts/test_people_directory_rules_export.py fails when the two
// differ.
package peopledirectory

import (
	"context"
	_ "embed"
	"encoding/json"
	"fmt"
	"net/url"
	"slices"
	"sort"
	"strconv"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/closedschools"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/hrregister"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pagegate"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// Path is the page.
const Path = "/staff"

// overdueRisk is "more than 3 overdue activities".
const overdueRisk = 3

//go:embed rules.json
var rulesJSON []byte

var rules = func() (r struct {
	PageRoles           []string          `json:"page_roles"`
	AddStaffRoles       []string          `json:"add_staff_roles"`
	EmailRoles          []string          `json:"email_roles"`
	SingularRoleLabels  map[string]string `json:"singular_role_labels"`
	RoleLabels          map[string]string `json:"role_labels"`
	VisitTypes          []string          `json:"visit_types"`
	CompletedStatuses   []string          `json:"completed_statuses"`
	NotInPlanStatuses   []string          `json:"not_in_plan_statuses"`
	NotFinishedStatuses []string          `json:"not_finished_statuses"`
	PageSize            int               `json:"page_size"`
}) {
	if err := json.Unmarshal(rulesJSON, &r); err != nil || len(r.PageRoles) == 0 || r.PageSize == 0 {
		panic(fmt.Sprintf("peopledirectory: the embedded rules are unreadable: %v", err))
	}
	return r
}()

var zone = func() *time.Location {
	z, err := time.LoadLocation("Africa/Kampala")
	if err != nil {
		panic(fmt.Sprintf("peopledirectory: loading the zone: %v", err))
	}
	return z
}()

// tabs are the directory's role tabs.
var tabs = [][2]string{{"all", "All Staff"}, {"cceo", "Field Officers (CCEO)"}, {"pl", "Program Leads"}, {"admin", "Admin & Support"}}

// Service answers the directory from the existing database.
type Service struct {
	db  schooldirectory.Querier
	now func() time.Time
}

// NewService is the directory over db.
func NewService(db schooldirectory.Querier, now func() time.Time) *Service {
	return &Service{db: db, now: now}
}

// person is one directory row.
type person struct {
	id, name, email, role, profile string
	district, country, department  string
	onboarding                     string
	hasProfile                     bool
	reportsTo                      []string
	schools, visits                int
}

// figures is the strip's three counts.
type figures struct{ active, pending, risk int }

// args builds numbered arguments.
type args []any

func (a *args) add(v any) string {
	*a = append(*a, v)
	return "$" + strconv.Itoa(len(*a))
}

// likeEscape is a value for icontains: its wildcards taken literally.
func likeEscape(s string) string {
	return "%" + strings.NewReplacer(`\`, `\\`, "%", `\%`, "_", `\_`).Replace(s) + "%"
}

// pageOf is Paginator.get_page: anything that is not a whole number is the
// first page, a number outside the pages the last.
func pageOf(requested string, total, size int) (number, pages int) {
	pages = max(1, (total+size-1)/size)
	n, err := strconv.Atoi(strings.TrimSpace(requested))
	switch {
	case requested == "" || err != nil:
		return 1, pages
	case n < 1 || n > pages:
		return pages, pages
	}
	return n, pages
}

// Build answers Path.
func (s *Service) Build(ctx context.Context, p auth.Principal, path string, query url.Values) (*screensv1.GetPageResponse, bool, error) {
	if path != Path {
		return nil, false, nil
	}
	if !slices.Contains(rules.PageRoles, p.ActiveRole) {
		return nil, true, pagegate.ErrNotAvailable
	}
	reach, list, team, err := hrregister.PeopleReachUsers(ctx, s.db, p, nil)
	if err != nil {
		return nil, true, fmt.Errorf("peopledirectory: resolving the reader's reach: %w", err)
	}
	a := args(list)
	scoped := `u.status = 'active' AND u.deleted_at IS NULL AND ` + reach
	f, err := s.figures(ctx, scoped, a, team)
	if err != nil {
		return nil, true, err
	}
	search := strings.TrimSpace(query.Get("q"))
	tab := query.Get("tab")
	if tab == "" || team {
		tab = "all"
	}
	showEmail := slices.Contains(rules.EmailRoles, p.ActiveRole)
	listed := scoped
	if search != "" {
		like := a.add(likeEscape(search))
		match := "UPPER(u.name::text) LIKE UPPER(" + like + ")"
		if showEmail {
			match = "(" + match + " OR UPPER(u.email::text) LIKE UPPER(" + like + "))"
		}
		listed += " AND " + match
	}
	switch tab {
	case "cceo":
		listed += ` AND COALESCE(u.roles, '{}') @> ARRAY['CCEO']::varchar[]`
	case "pl":
		listed += ` AND COALESCE(u.roles, '{}') @> ARRAY['Program Lead']::varchar[]`
	case "admin":
		listed += ` AND NOT COALESCE(u.roles, '{}') @> ARRAY['CCEO']::varchar[] AND NOT COALESCE(u.roles, '{}') @> ARRAY['Program Lead']::varchar[]`
	}
	var total int
	if err := s.db.QueryRow(ctx, `SELECT count(*) FROM "user" u WHERE `+listed, a...).Scan(&total); err != nil {
		return nil, true, fmt.Errorf("peopledirectory: counting the directory: %w", err)
	}
	number, pages := pageOf(query.Get("page"), total, rules.PageSize)
	limit, offset := a.add(rules.PageSize), a.add((number-1)*rules.PageSize)
	rows, err := s.db.Query(ctx, `SELECT u.id, COALESCE(u.name, ''), COALESCE(u.email, ''), COALESCE(u.active_role, ''),
  COALESCE(sp.id, ''), COALESCE(d.name, ''), COALESCE(sp.country, ''), COALESCE(sp.department, ''), COALESCE(sp.onboarding_state, ''), sp.id IS NOT NULL
FROM "user" u LEFT JOIN staff_profile sp ON sp.user_id = u.id LEFT JOIN district d ON d.id = sp.primary_district_id
WHERE `+listed+` ORDER BY u.name LIMIT `+limit+` OFFSET `+offset, a...)
	if err != nil {
		return nil, true, fmt.Errorf("peopledirectory: reading the directory: %w", err)
	}
	people, err := pgx.CollectRows(rows, func(r pgx.CollectableRow) (person, error) {
		var x person
		return x, r.Scan(&x.id, &x.name, &x.email, &x.role, &x.profile, &x.district, &x.country, &x.department, &x.onboarding, &x.hasProfile)
	})
	if err != nil {
		return nil, true, fmt.Errorf("peopledirectory: reading the directory: %w", err)
	}
	if err := s.workload(ctx, people); err != nil {
		return nil, true, err
	}
	addStaff := slices.Contains(rules.AddStaffRoles, p.ActiveRole)
	return page(people, f, team, showEmail, addStaff, search, tab, number, pages, total), true, nil
}

// figures is the strip over the whole reach, whatever the tab and search.
func (s *Service) figures(ctx context.Context, scoped string, a []any, team bool) (figures, error) {
	var f figures
	n := len(a)
	today := s.now().In(zone).Format(time.DateOnly)
	err := s.db.QueryRow(ctx, fmt.Sprintf(`WITH scoped AS (SELECT u.id FROM "user" u WHERE %[1]s),
owners AS (SELECT id FROM scoped UNION SELECT sp.id FROM staff_profile sp WHERE sp.user_id IN (SELECT id FROM scoped))
SELECT (SELECT count(*) FROM scoped),
  (SELECT count(*) FROM staff_profile sp WHERE sp.deleted_at IS NULL AND sp.onboarding_state = 'pending' AND sp.user_id IN (SELECT id FROM scoped)),
  (SELECT count(*) FROM (SELECT a.responsible_staff_id FROM activity a
     WHERE a.planned_date < $%[2]d::date AND a.status = ANY($%[3]d) AND a.deleted_at IS NULL AND a.responsible_staff_id IN (SELECT id FROM owners)
     GROUP BY a.responsible_staff_id HAVING count(*) > %[4]d) o)`, scoped, n+1, n+2, overdueRisk),
		append(append([]any{}, a...), today, rules.NotFinishedStatuses)...).Scan(&f.active, &f.pending, &f.risk)
	if err != nil {
		return f, fmt.Errorf("peopledirectory: counting the reach: %w", err)
	}
	if team {
		f.pending = 0
	}
	return f, nil
}

// workload fills each person's schools visited, completed visits and
// reporting line, in three queries for the page.
func (s *Service) workload(ctx context.Context, people []person) error {
	if len(people) == 0 {
		return nil
	}
	owner := map[string]int{}
	ids, profiles := []string{}, []string{}
	for i, x := range people {
		owner[x.id] = i
		ids = append(ids, x.id)
		if x.profile != "" {
			owner[x.profile] = i
			ids = append(ids, x.profile)
			profiles = append(profiles, x.profile)
		}
	}
	schools := make([]map[string]bool, len(people))
	rows, err := s.db.Query(ctx, `SELECT DISTINCT responsible_staff_id, school_id FROM activity
WHERE responsible_staff_id = ANY($1) AND deleted_at IS NULL AND activity_type = ANY($2) AND school_id IS NOT NULL AND school_id <> ''
  AND NOT (status = ANY($3))`, ids, rules.VisitTypes, rules.NotInPlanStatuses)
	if err != nil {
		return fmt.Errorf("peopledirectory: reading the schools visited: %w", err)
	}
	for rows.Next() {
		var who, school string
		if err := rows.Scan(&who, &school); err != nil {
			rows.Close()
			return fmt.Errorf("peopledirectory: reading the schools visited: %w", err)
		}
		i := owner[who]
		if schools[i] == nil {
			schools[i] = map[string]bool{}
		}
		schools[i][school] = true
	}
	rows.Close()
	for i := range people {
		people[i].schools = len(schools[i])
	}
	rows, err = s.db.Query(ctx, `SELECT responsible_staff_id, count(*) FROM activity
WHERE responsible_staff_id = ANY($1) AND status = ANY($2) AND activity_type = ANY($3) AND deleted_at IS NULL GROUP BY 1`,
		ids, rules.CompletedStatuses, rules.VisitTypes)
	if err != nil {
		return fmt.Errorf("peopledirectory: counting the completed visits: %w", err)
	}
	for rows.Next() {
		var who string
		var n int
		if err := rows.Scan(&who, &n); err != nil {
			rows.Close()
			return fmt.Errorf("peopledirectory: counting the completed visits: %w", err)
		}
		people[owner[who]].visits += n
	}
	rows.Close()
	rows, err = s.db.Query(ctx, `SELECT a.supervisee_id, COALESCE(u.name, '') FROM staff_supervisor_assignment a
JOIN staff_profile sv ON sv.id = a.supervisor_id JOIN "user" u ON u.id = sv.user_id WHERE a.supervisee_id = ANY($1)`, profiles)
	if err != nil {
		return fmt.Errorf("peopledirectory: reading the reporting lines: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var who, name string
		if err := rows.Scan(&who, &name); err != nil {
			return fmt.Errorf("peopledirectory: reading the reporting lines: %w", err)
		}
		i := owner[who]
		people[i].reportsTo = append(people[i].reportsTo, name)
	}
	return rows.Err()
}

// RoleLabel is a role in the singular, as the existing application names
// it to people (CountryDirector → Country Director).
func RoleLabel(role string) string { return roleLabel(role) }

// roleLabel is the role in the singular.
func roleLabel(role string) string {
	if l, ok := rules.SingularRoleLabels[role]; ok {
		return l
	}
	if l, ok := rules.RoleLabels[role]; ok {
		return l
	}
	return role
}

// initials is the name's first two characters, upper-cased.
func initials(name string) string {
	r := []rune(name)
	if len(r) == 0 {
		return "??"
	}
	return strings.ToUpper(string(r[:min(2, len(r))]))
}

// onboarding is the row's onboarding pill.
func onboarding(x person) string {
	switch {
	case !x.hasProfile:
		return "no_profile"
	case x.onboarding == "active" || x.onboarding == "complete":
		return "Active"
	case x.onboarding == "pending":
		return "Pending"
	case x.onboarding == "":
		return "Unknown"
	}
	return x.onboarding
}

// place is the role-and-place line.
func place(x person) string {
	parts := []string{}
	for _, v := range []string{x.district, x.country, x.department} {
		if v != "" {
			parts = append(parts, v)
		}
	}
	where := strings.Join(parts, " · ")
	if where == "" {
		where = "No place recorded"
	}
	line := roleLabel(x.role) + " " + where
	if len(x.reportsTo) > 0 {
		names := slices.Clone(x.reportsTo)
		sort.Strings(names)
		line += " · reports to " + strings.Join(names, ", ")
	}
	return line
}

// page is pages/staff/index.html as the feed reads it.
func page(people []person, f figures, team, showEmail, addStaff bool, search, tab string, number, pages, total int) *screensv1.GetPageResponse {
	header := &screensv1.PageHeader{Title: "People Directory",
		Description: "The people in your scope: role, place, reporting line, onboarding status and field workload."}
	if addStaff {
		header.Actions = []*screensv1.PageAction{{Key: "new_staff_member", Label: "New Staff Member", Enabled: true, Href: "/admin-panel/users"}}
	}
	metrics := []*screensv1.PageMetric{{Label: "People", Value: strconv.Itoa(f.active), Note: "active in your scope"}}
	if !team {
		metrics = append(metrics, &screensv1.PageMetric{Label: "Pending onboarding", Value: strconv.Itoa(f.pending), Note: "Needs HR completion"})
	}
	metrics = append(metrics, &screensv1.PageMetric{Label: "Overdue field work", Value: strconv.Itoa(f.risk), Note: "people with more than 3 overdue activities"})
	blocks := []*screensv1.PageBlock{{Kind: &screensv1.PageBlock_Strip{Strip: &screensv1.PageStrip{Title: "Workforce attention", Metrics: metrics}}}}
	if !team {
		links := []*screensv1.PageLink{}
		for _, t := range tabs {
			links = append(links, &screensv1.PageLink{Text: t[1], Href: "?tab=" + t[0]})
		}
		blocks = append(blocks, &screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{
			Items: []*screensv1.PagePanelItem{{Kind: &screensv1.PagePanelItem_Links{Links: &screensv1.PageLinks{Links: links}}}}}}})
	}
	t := &screensv1.PageTable{}
	for _, c := range []string{"", "Staff Member", "Role and place", "Assigned Schools", "Completed Visits", "Onboarding Status", "Actions"} {
		t.Columns = append(t.Columns, &screensv1.PageColumn{Label: c, Numeric: c == "Actions"})
	}
	for _, x := range people {
		who := initials(x.name) + " " + x.name
		if showEmail {
			who += " " + x.email
		}
		t.Rows = append(t.Rows, &screensv1.PageRow{Cells: []*screensv1.PageCell{
			{}, {Text: closedschools.Collapse(who)}, {Text: closedschools.Collapse(place(x))},
			{Text: strconv.Itoa(x.schools)}, {Text: strconv.Itoa(x.visits)},
			{Text: closedschools.Collapse(onboarding(x)), Tone: "primary", Badge: true},
			{Text: "View Profile", Href: "/staff/" + x.id},
		}})
	}
	if len(people) == 0 {
		t.Rows = []*screensv1.PageRow{{Cells: []*screensv1.PageCell{{Text: "No staff members found."}}}}
	}
	blocks = append(blocks, &screensv1.PageBlock{Kind: &screensv1.PageBlock_Table{Table: t}},
		&screensv1.PageBlock{Kind: &screensv1.PageBlock_Pager{Pager: pager(search, tab, number, pages, total)}})
	return &screensv1.GetPageResponse{Header: header, Blocks: blocks, WebPath: Path}
}

// pager is the directory's own pager: "Showing a to b of n staff", then, past
// one page, Prev, the elided page numbers and Next, each link keeping the
// search and tab.
func pager(search, tab string, number, pages, total int) *screensv1.PagePager {
	start, end := 0, 0
	if total > 0 {
		start, end = (number-1)*rules.PageSize+1, min(number*rules.PageSize, total)
	}
	p := &screensv1.PagePager{Summary: fmt.Sprintf("Showing %d to %d of %d staff", start, end, total)}
	if pages <= 1 {
		return p
	}
	href := func(n int) string { return "?q=" + search + "&tab=" + tab + "&page=" + strconv.Itoa(n) }
	if number > 1 {
		p.Pages = append(p.Pages, &screensv1.PagePagerPage{Label: "Prev‹", Href: href(number - 1)},
			&screensv1.PagePagerPage{Label: "Prev"}, &screensv1.PagePagerPage{Label: "‹"})
	}
	for _, n := range elided(number, pages) {
		switch {
		case n == 0:
			p.Pages = append(p.Pages, &screensv1.PagePagerPage{Label: "…"})
		case n == number:
			p.Pages = append(p.Pages, &screensv1.PagePagerPage{Label: strconv.Itoa(n), Current: true})
		default:
			p.Pages = append(p.Pages, &screensv1.PagePagerPage{Label: strconv.Itoa(n), Href: href(n)})
		}
	}
	if number < pages {
		p.Pages = append(p.Pages, &screensv1.PagePagerPage{Label: "Next›", Href: href(number + 1)},
			&screensv1.PagePagerPage{Label: "Next"}, &screensv1.PagePagerPage{Label: "›"})
	}
	return p
}

// elided is Paginator.get_elided_page_range(number, on_each_side=1,
// on_ends=1); 0 is the gap.
func elided(number, pages int) []int {
	out := []int{}
	span := func(from, to int) {
		for i := from; i < to; i++ {
			out = append(out, i)
		}
	}
	if pages <= 4 {
		span(1, pages+1)
		return out
	}
	if number > 4 {
		out = append(out, 1, 0)
		span(number-1, number+1)
	} else {
		span(1, number+1)
	}
	if number < pages-3 {
		span(number+1, number+2)
		out = append(out, 0, pages)
	} else {
		span(number+1, pages+1)
	}
	return out
}
