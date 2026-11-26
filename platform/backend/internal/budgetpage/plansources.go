package budgetpage

import (
	"context"
	"fmt"
	"net/url"
	"slices"
	"strconv"
	"strings"
	"time"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	registry "github.com/O-Mario88/edify-planning-tool/platform/backend/internal/country"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pageaccess"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pagegate"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/tablepager"
)

// PlanSourcesPath is the General Budget's View Plan Sources drawer.
const PlanSourcesPath = CountryBudgetPath + "/plan-sources"

// planSourcesRefusal is _require_read's refusal.
const planSourcesRefusal = "Only CD, RVP, Accountant, IA, or Admin may view the General Budget."

// planSourcesLimit is get_plan_sources' rows[:200].
const planSourcesLimit = 200

// planSource is one activity's row of the drawer.
type planSource struct {
	activityType, schoolPK, schoolCode, schoolName, staff, delivery string
	planned                                                         *time.Time
	operational                                                     int64
	viability                                                       string
}

// PlanSources is country_budget_plan_sources_view over get_plan_sources:
// the month's scheduled planned activities and their country operational
// cost, by cost, with the month's funding status and each one's
// viability. Go writes nothing on this read: a month with no budget yet is
// a draft, as the existing read would create it.
func PlanSources(ctx context.Context, db schooldirectory.Querier, p auth.Principal, query url.Values, now time.Time) (*screensv1.GetDrawerResponse, bool, error) {
	if !pageaccess.CanOpen(p.ActiveRole, false, PlanSourcesPath) {
		return nil, true, pagegate.ErrNotAvailable
	}
	if !in(rules.Country.ReadRoles, p.ActiveRole) {
		return &screensv1.GetDrawerResponse{Refusal: planSourcesRefusal}, true, nil
	}
	fy, err := strconv.Atoi(strings.TrimSpace(query.Get("fy")))
	if query.Get("fy") == "" {
		fy, err = strconv.Atoi(schooldirectory.OperationalFY(now))
	}
	if err != nil {
		return nil, false, nil
	}
	month := int(now.In(zone).Month())
	if raw := strings.TrimSpace(query.Get("month")); raw != "" {
		if month, err = strconv.Atoi(raw); err != nil || month < 1 || month > 12 {
			return nil, false, nil
		}
	}
	var countryIDs []string
	if p.Country != nil {
		countryIDs = []string{p.Country.ID}
	}
	year := fy
	if month >= 10 {
		year = fy - 1
	}
	start := date(year, time.Month(month), 1)
	end := start.AddDate(0, 1, -1)
	rows, err := db.Query(ctx, `
		SELECT l.activity_id, COALESCE(l.amount, 0), COALESCE(l.responsible_user, ''), COALESCE(a.activity_type, ''),
		       COALESCE(a.school_id, ''), COALESCE(s.school_id, ''), COALESCE(s.name, ''), COALESCE(a.delivery_type, ''), a.planned_date
		FROM activity_schedule_cost_line l JOIN activity a ON a.id = l.activity_id
		LEFT JOIN school s ON s.id = a.school_id LEFT JOIN cluster cl ON cl.id = a.cluster_id
		WHERE a.deleted_at IS NULL AND l.fiscal_year = $1
		  AND ($6::text[] IS NULL OR `+registry.ActivityHeldIn("a", "s", "cl", "$6")+`)
		  AND (a.scheduled_date IS NOT NULL OR a.planned_date IS NOT NULL)
		  AND (a.status IS NULL OR NOT (a.status = ANY($2)))
		  AND (l.planned_date BETWEEN $3 AND $4 OR (l.planned_date IS NULL AND l.month = ANY($5)))`,
		strconv.Itoa(fy), rules.NonFundableStatuses, start, end, wholeMonths(start, end), countryIDs)
	if err != nil {
		return nil, true, fmt.Errorf("budgetpage: reading the month's plan sources: %w", err)
	}
	byActivity := map[string]*planSource{}
	order, users := []string{}, []string{}
	firstUser := map[string]string{}
	for rows.Next() {
		var id, user string
		var amount int64
		r := &planSource{}
		if err := rows.Scan(&id, &amount, &user, &r.activityType, &r.schoolPK, &r.schoolCode, &r.schoolName, &r.delivery, &r.planned); err != nil {
			rows.Close()
			return nil, true, err
		}
		if got, ok := byActivity[id]; ok {
			got.operational += amount
			continue
		}
		r.operational = amount
		byActivity[id], firstUser[id] = r, user
		order = append(order, id)
		users = append(users, user)
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, true, err
	}
	s := &Service{db: db}
	names, err := s.userNames(ctx, users)
	if err != nil {
		return nil, true, err
	}
	viability, err := s.viability(ctx, order)
	if err != nil {
		return nil, true, err
	}
	status := "draft_generated"
	err = db.QueryRow(ctx, `SELECT status FROM monthly_work_plan_budget WHERE country_id = $1 AND month_key = $2`,
		rules.Country.HomeCountryID, monthKey(fy, month)).Scan(&status)
	if err != nil && !strings.Contains(err.Error(), "no rows") {
		return nil, true, fmt.Errorf("budgetpage: reading the month's budget: %w", err)
	}
	funding, ok := rules.Country.ApprovalStatusLabels[status]
	if !ok {
		funding = "Draft"
	}
	list := make([]*planSource, 0, len(order))
	for _, id := range order {
		r := byActivity[id]
		r.staff = "—"
		if n, ok := names[firstUser[id]]; ok {
			r.staff = n
		}
		r.viability = viability[id]
		list = append(list, r)
	}
	slices.SortStableFunc(list, func(a, b *planSource) int {
		switch {
		case a.operational > b.operational:
			return -1
		case a.operational < b.operational:
			return 1
		}
		return 0
	})
	list = list[:min(len(list), planSourcesLimit)]
	return &screensv1.GetDrawerResponse{Drawer: planSourcesDrawer(p, list, fy, month, funding, query)}, true, nil
}

// userNames is _user_names: each account's name.
func (s *Service) userNames(ctx context.Context, ids []string) (map[string]string, error) {
	out := map[string]string{}
	rows, err := s.db.Query(ctx, `SELECT id, COALESCE(name, '') FROM "user" WHERE id = ANY($1)`, ids)
	if err != nil {
		return nil, fmt.Errorf("budgetpage: reading the staff's names: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var id, name string
		if err := rows.Scan(&id, &name); err != nil {
			return nil, err
		}
		out[id] = name
	}
	return out, rows.Err()
}

// viability is each activity's operational viability from its current
// cost snapshot: a regional rate required without a reference cost, a cost
// review for missing configuration, a review for warnings, else viable.
func (s *Service) viability(ctx context.Context, ids []string) (map[string]string, error) {
	out := map[string]string{}
	for _, id := range ids {
		out[id] = "Regional rate required"
	}
	q, err := s.db.Query(ctx, `SELECT activity_id, reference_cost IS NOT NULL,
  COALESCE(missing_configuration::text NOT IN ('null', '[]', '{}', '""', 'false', '0'), false),
  COALESCE(warnings::text NOT IN ('null', '[]', '{}', '""', 'false', '0'), false)
FROM activity_cost_snapshot WHERE activity_id = ANY($1) AND is_current`, ids)
	if err != nil {
		return nil, fmt.Errorf("budgetpage: reading the plan's cost snapshots: %w", err)
	}
	defer q.Close()
	for q.Next() {
		var id string
		var referenced, missing, warned bool
		if err := q.Scan(&id, &referenced, &missing, &warned); err != nil {
			return nil, err
		}
		switch {
		case !referenced:
			out[id] = "Regional rate required"
		case missing:
			out[id] = "Cost review required"
		case warned:
			out[id] = "Review recommended"
		default:
			out[id] = "Viable"
		}
	}
	return out, q.Err()
}

// planSourcesDrawer is plan_sources_drawer.html as the feed reads it.
func planSourcesDrawer(p auth.Principal, list []*planSource, fy, month int, funding string, query url.Values) *screensv1.PageDrawer {
	monthLabel := strconv.Itoa(month)
	if month >= 1 && month <= 12 && month < len(rules.Country.Months) {
		monthLabel = rules.Country.Months[month]
	}
	word := "activities"
	if len(list) == 1 {
		word = "activity"
	}
	pg := tablepager.Paginate(len(list), groupsPageSize, query, "rows_page")
	table := &screensv1.PageTable{Columns: []*screensv1.PageColumn{{Label: "Activity"}, {Label: "Staff"},
		{Label: "Country operational cost", Numeric: true}, {Label: "Funding status"}, {Label: "Operational viability"}}}
	opens := pageaccess.CanOpen(p.ActiveRole, false, "/schools/0")
	for _, r := range list[pg.Start:pg.End] {
		where := &screensv1.PageCell{}
		identity := "—"
		if r.schoolPK != "" {
			identity = strings.TrimSpace(orWord(r.schoolCode, "—") + " " + orWord(r.schoolName, "School not recorded"))
			if opens && r.schoolName != "" {
				where.Href = "/schools/" + r.schoolPK
			}
		}
		day := "—"
		if r.planned != nil {
			day = r.planned.Format("Jan 2, 2006")
		}
		where.Text = label(rules.ActivityTypes, r.activityType) + " " + identity + " · " + day + " · " + titleWords(r.delivery)
		table.Rows = append(table.Rows, &screensv1.PageRow{Cells: []*screensv1.PageCell{where, {Text: r.staff},
			{Text: ugxCompact(r.operational)}, {Text: funding}, {Text: r.viability, Tone: "primary", Badge: true}}})
	}
	if len(list) == 0 {
		table.Rows = []*screensv1.PageRow{{Cells: []*screensv1.PageCell{{Text: "No plan sources for this month."}}}}
	}
	if pg.Pager != nil {
		table.Pager, table.Footnote = pg.Pager, pg.Pager.Summary
	}
	return &screensv1.PageDrawer{
		Title: "Plan sources for " + monthLabel + " " + strconv.Itoa(fy), Subtitle: strconv.Itoa(len(list)) + " scheduled " + word,
		HasRequired: true, Items: []*screensv1.DrawerItem{{Kind: &screensv1.DrawerItem_Block{Block: &screensv1.PageBlock{
			Kind: &screensv1.PageBlock_Table{Table: table}}}}},
		CancelLabel: "Close",
	}
}

// titleWords is Django's |title: each word capitalised after a non-letter.
func titleWords(s string) string { return pyTitle(s) }
