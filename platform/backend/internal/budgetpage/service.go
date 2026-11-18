package budgetpage

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"math"
	"net/url"
	"regexp"
	"slices"
	"sort"
	"strconv"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	registry "github.com/O-Mario88/edify-planning-tool/platform/backend/internal/country"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pagegate"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// Service builds the page.
type Service struct {
	db  schooldirectory.Querier
	now func() time.Time
}

// NewService is the page over db.
func NewService(db schooldirectory.Querier, now func() time.Time) *Service {
	return &Service{db: db, now: now}
}

var ownQuery = []string{"fy", "date", "period", "budget_scope", "groups_page"}

var (
	plainYear = regexp.MustCompile(`^[0-9]{4}$`)
	plainDate = regexp.MustCompile(`^[0-9]{4}-[0-9]{2}-[0-9]{2}$`)
)

// errPassOn is a request the existing page answers.
var errPassOn = errors.New("budgetpage: the existing page answers this request")

var zone = func() *time.Location {
	z, err := time.LoadLocation("Africa/Kampala")
	if err != nil {
		panic("budgetpage: " + err.Error())
	}
	return z
}()

// ask is the request as budget_view and scoped_budget_lines read it.
type ask struct {
	fy                  int
	anchor              time.Time
	period, budgetScope string
	isProgramLead       bool
	periods             map[string]period
	weekYears           []string
	selected            period
	// countryIDs keep the country's Budget to the request's country
	// (registry ids, docs/migration/80 §18); nil reads every line.
	countryIDs []string
}

func readAsk(p auth.Principal, query url.Values, now time.Time) (ask, error) {
	for key := range query {
		if !slices.Contains(ownQuery, key) {
			return ask{}, errPassOn
		}
	}
	fyText := query.Get("fy")
	if fyText == "" {
		fyText = schooldirectory.OperationalFY(now)
	}
	if !plainYear.MatchString(fyText) {
		return ask{}, errPassOn
	}
	fy, _ := strconv.Atoi(fyText)
	var anchor time.Time
	if d := query.Get("date"); d != "" {
		parsed, err := time.Parse(time.DateOnly, d)
		if err != nil || !plainDate.MatchString(d) {
			return ask{}, errPassOn
		}
		anchor = parsed
	} else {
		m := now.In(zone).Month()
		year := fy
		if m >= time.October {
			year = fy - 1
		}
		anchor = date(year, m, 1)
	}
	a := ask{fy: fy, anchor: anchor, isProgramLead: p.ActiveRole == "Program Lead"}
	a.period = query.Get("period")
	if a.period != "month" && a.period != "quarter" && a.period != "fy" {
		a.period = "month"
	}
	requested := query.Get("budget_scope")
	if !query.Has("budget_scope") {
		requested = "my"
		if a.isProgramLead {
			requested = "team"
		}
	}
	a.budgetScope = "my"
	if a.isProgramLead && requested == "team" {
		a.budgetScope = "team"
	}
	a.periods = periods(fy, anchor)
	a.selected = a.periods[a.period]
	week := a.periods["week"]
	touches := []string{strconv.Itoa(operationalFY(week.start)), strconv.Itoa(operationalFY(week.end))}
	a.weekYears = []string{fyText}
	if slices.Contains(touches, fyText) {
		for _, y := range touches {
			if !slices.Contains(a.weekYears, y) {
				a.weekYears = append(a.weekYears, y)
			}
		}
	}
	sort.Strings(a.weekYears)
	return a, nil
}

// Build answers /budget; every other path is not its own.
func (s *Service) Build(ctx context.Context, p auth.Principal, path string, query url.Values) (*screensv1.GetPageResponse, bool, error) {
	if path != Path && path != Path+"/" {
		return nil, false, nil
	}
	r, ok := rules.Roles[p.ActiveRole]
	if !ok || !r.Page {
		return nil, true, pagegate.ErrNotAvailable
	}
	if r.Strip {
		return nil, false, nil
	}
	resp, err := s.build(ctx, p, r, query)
	if errors.Is(err, errPassOn) {
		return nil, false, nil
	}
	if err != nil {
		return nil, true, err
	}
	return resp, true, nil
}

func (s *Service) build(ctx context.Context, p auth.Principal, r role, query url.Values) (*screensv1.GetPageResponse, error) {
	now := s.now()
	a, err := readAsk(p, query, now)
	if err != nil {
		return nil, err
	}
	scope, err := schooldirectory.ResolveScope(ctx, s.db, p, now)
	if err != nil {
		return nil, fmt.Errorf("budgetpage: resolving the reader's scope: %w", err)
	}
	var owners []string
	switch {
	case r.Country && (scope.CountryScope || in(rules.CountryLedgerRoles, p.ActiveRole)):
		// The country's Budget: every planned line of the country the
		// request is made in, no owner (docs/migration/80, §18). Money is
		// never summed across countries: the Admin and the regional roles,
		// who reach every country, read the one they work in.
		a.budgetScope = "country"
		if p.Country != nil {
			a.countryIDs = []string{p.Country.ID}
		}
	case r.Country || scope.CountryScope:
		return nil, errPassOn
	default:
		if owners, err = s.owners(ctx, p, scope, a.budgetScope == "team"); err != nil {
			return nil, err
		}
	}
	lines, err := s.lines(ctx, a, owners)
	if err != nil {
		return nil, err
	}
	dayRates, err := s.dayRates(ctx, lines)
	if err != nil {
		return nil, err
	}
	gs := groups(lines, dayRates)
	if len(gs) > groupsPageSize {
		return nil, errPassOn
	}
	var team []member
	if a.budgetScope == "team" {
		names, err := s.names(ctx, lines)
		if err != nil {
			return nil, err
		}
		team = teamSummary(lines, names)
	}
	v := view{a: a, role: p.ActiveRole, export: r.Export, groups: gs, team: team, now: now}
	if v.currency, err = registry.CurrencyOf(ctx, s.db, p.Country); err != nil {
		return nil, err
	}
	if a.budgetScope == "country" {
		if p.Country == nil {
			// With no country to keep it to, the existing page's rule: a
			// platform whose People name several countries is handed on.
			several, err := s.multiCountry(ctx)
			if err != nil {
				return nil, err
			}
			if several {
				return nil, errPassOn
			}
		}
		v.country, v.countryIDs = true, a.countryIDs
		if v.wf, err = s.workflow(ctx, registry.SettingsName(p.Country, rules.Country.HomeCountryID), a.countryIDs, a.fy, int(a.anchor.Month())); err != nil {
			return nil, err
		}
		if v.fin, err = s.financeHealth(ctx, a.fy, a.countryIDs); err != nil {
			return nil, err
		}
		if v.districts, err = s.districts(ctx); err != nil {
			return nil, err
		}
	}
	return &screensv1.GetPageResponse{Header: v.header(), Blocks: v.blocks(), WebPath: Path}, nil
}

// owners is _workspace_owner_ids: the reader and their staff profiles, and
// for a Program Lead's team their live supervisees and those people's
// accounts.
func (s *Service) owners(ctx context.Context, p auth.Principal, scope schooldirectory.Scope, team bool) ([]string, error) {
	ids := []string{}
	add := func(id string) {
		if id != "" && !slices.Contains(ids, id) {
			ids = append(ids, id)
		}
	}
	add(p.UserID)
	collect := func(sql string, arg any) error {
		rows, err := s.db.Query(ctx, sql, arg)
		if err != nil {
			return err
		}
		found, err := pgx.CollectRows(rows, pgx.RowTo[*string])
		if err != nil {
			return err
		}
		for _, id := range found {
			if id != nil {
				add(*id)
			}
		}
		return nil
	}
	if err := collect(`SELECT id FROM staff_profile WHERE user_id = $1 AND deleted_at IS NULL`, p.UserID); err != nil {
		return nil, fmt.Errorf("budgetpage: reading the reader's profiles: %w", err)
	}
	if team && p.ActiveRole == "Program Lead" && len(scope.SupervisedStaffIDs) > 0 {
		for _, id := range scope.SupervisedStaffIDs {
			add(id)
		}
		if err := collect(`SELECT user_id FROM staff_profile WHERE id = ANY($1) AND deleted_at IS NULL`, scope.SupervisedStaffIDs); err != nil {
			return nil, fmt.Errorf("budgetpage: reading the team's accounts: %w", err)
		}
	}
	return ids, nil
}

// lines is the selected period's cost lines: of the page's years, of live
// fundable dated activities, owned by the reader (or the line's activity
// is theirs, or a partner's work they monitor; any owner when owners is
// nil, the country's), planned in the period (or dated only by a month
// wholly inside it).
func (s *Service) lines(ctx context.Context, a ask, owners []string) ([]line, error) {
	rows, err := s.db.Query(ctx, `
		SELECT l.activity_id, COALESCE(l.responsible_user, ''), COALESCE(l.label, ''), COALESCE(l.cost_setting_key, ''),
		       COALESCE(l.line_item_type, ''), COALESCE(l.amount, 0), COALESCE(l.unit_cost, 0), COALESCE(l.quantity, 0),
		       l.planned_date, l.partner_id,
		       COALESCE(a.activity_type, ''), COALESCE(a.programme_activity_type, ''), COALESCE(a.delivery_type, ''),
		       COALESCE(a.teachers_attended, 0), COALESCE(a.leaders_attended, 0), COALESCE(a.other_participants, 0),
		       COALESCE(a.expected_participants, 0), COALESCE(a.daily_visit_batch_id, '')
		FROM activity_schedule_cost_line l
		JOIN activity a ON a.id = l.activity_id
		LEFT JOIN school s ON s.id = a.school_id
		LEFT JOIN cluster cl ON cl.id = a.cluster_id
		WHERE l.fiscal_year = ANY($1)
		  AND ($7::text[] IS NULL OR `+registry.ActivityIn("a", "s", "cl", "$7")+`)
		  AND a.deleted_at IS NULL
		  AND (a.scheduled_date IS NOT NULL OR a.planned_date IS NOT NULL)
		  AND (a.status IS NULL OR NOT (a.status = ANY($2)))
		  AND ($3::text[] IS NULL
		       OR l.responsible_user = ANY($3)
		       OR (a.delivery_type = 'partner' AND a.monitored_by_staff_id = ANY($3))
		       OR ((l.responsible_user IS NULL OR l.responsible_user = '')
		           AND (a.responsible_staff_id = ANY($3)
		                OR (a.delivery_type = 'partner' AND a.monitored_by_staff_id = ANY($3)))))
		  AND (l.planned_date BETWEEN $4 AND $5 OR (l.planned_date IS NULL AND l.month = ANY($6)))`,
		a.weekYears, rules.NonFundableStatuses, owners, a.selected.start, a.selected.end, wholeMonths(a.selected.start, a.selected.end),
		a.countryIDs)
	if err != nil {
		return nil, fmt.Errorf("budgetpage: reading the cost lines: %w", err)
	}
	out, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (line, error) {
		var l line
		err := row.Scan(&l.activityID, &l.responsibleUser, &l.label, &l.settingKey, &l.lineItemType, &l.amount, &l.unitCost,
			&l.quantity, &l.plannedDate, &l.partnerID, &l.activityType, &l.programmeType, &l.deliveryType,
			&l.teachers, &l.leaders, &l.others, &l.expected, &l.batchID)
		return l, err
	})
	if err != nil {
		return nil, fmt.Errorf("budgetpage: reading the cost lines: %w", err)
	}
	return out, nil
}

// dayRates is each shared day's rate snapshot, the rates it sets.
func (s *Service) dayRates(ctx context.Context, lines []line) (map[string]map[string]int64, error) {
	ids := []string{}
	for _, l := range lines {
		if l.batchID != "" && in(rules.DayRateKeys, l.settingKey) && !slices.Contains(ids, l.batchID) {
			ids = append(ids, l.batchID)
		}
	}
	out := map[string]map[string]int64{}
	if len(ids) == 0 {
		return out, nil
	}
	rows, err := s.db.Query(ctx, `SELECT id, rate_snapshot FROM daily_visit_batch WHERE id = ANY($1)`, ids)
	if err != nil {
		return nil, fmt.Errorf("budgetpage: reading the days' rates: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var id string
		var raw []byte
		if err := rows.Scan(&id, &raw); err != nil {
			return nil, fmt.Errorf("budgetpage: reading the days' rates: %w", err)
		}
		rates, err := snapshotRates(raw)
		if err != nil {
			return nil, err
		}
		out[id] = rates
	}
	return out, rows.Err()
}

// snapshotRates reads a day's snapshot as budget_groups does: a set (truthy)
// value is int() of it. A value int() would refuse is passed on.
func snapshotRates(raw []byte) (map[string]int64, error) {
	out := map[string]int64{}
	if len(raw) == 0 || string(raw) == "null" {
		return out, nil
	}
	var snapshot map[string]any
	if err := json.Unmarshal(raw, &snapshot); err != nil {
		return nil, errPassOn
	}
	for key, value := range snapshot {
		switch v := value.(type) {
		case float64:
			if v == 0 {
				continue
			}
			out[key] = int64(math.Trunc(v))
		case string:
			if v == "" {
				continue
			}
			n, err := strconv.ParseInt(strings.TrimSpace(v), 10, 64)
			if err != nil {
				return nil, errPassOn
			}
			out[key] = n
		case bool:
			if v {
				out[key] = 1
			}
		case nil:
		default:
			if in(rules.DayRateKeys, key) {
				return nil, errPassOn
			}
		}
	}
	return out, nil
}

// names is each line owner's account name.
func (s *Service) names(ctx context.Context, lines []line) (map[string]string, error) {
	ids := []string{}
	for _, l := range lines {
		if l.responsibleUser != "" && !slices.Contains(ids, l.responsibleUser) {
			ids = append(ids, l.responsibleUser)
		}
	}
	out := map[string]string{}
	if len(ids) == 0 {
		return out, nil
	}
	rows, err := s.db.Query(ctx, `SELECT id, COALESCE(name, '') FROM "user" WHERE id = ANY($1)`, ids)
	if err != nil {
		return nil, fmt.Errorf("budgetpage: reading the owners' names: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var id, name string
		if err := rows.Scan(&id, &name); err != nil {
			return nil, fmt.Errorf("budgetpage: reading the owners' names: %w", err)
		}
		out[id] = name
	}
	return out, rows.Err()
}
