package todos

import (
	"context"
	"errors"
	"math"
	"sort"
	"strconv"
	"strings"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/allocations"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/partneroversight"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/targets"
)

// The Country Director's oversight rows (todo_service._cd_analytics_todos
// over CDAnalyticsService.cd_todos): Programme Lead teams at high risk, the
// recommended actions, weekly requests escalated to the Country Director
// and an underused budget, read live over the whole country with no
// dashboard filter.

const (
	// cdAnalyticsLimit is how many rows cd_todos and the builder keep.
	cdAnalyticsLimit = 8
	// cdProfileLabel is where the country's signals are read.
	cdProfileLabel = "Country Profile"
	// cdWeeklyStatus is a weekly request escalated to the Country Director.
	cdWeeklyStatus = "submitted_to_cd"
	// cdLowBudgetPct is the utilisation below which the budget is flagged.
	cdLowBudgetPct = 50
	// cdLowLeadership is the district Leadership mean (out of ten) below
	// which a district is flagged.
	cdLowLeadership = 5.0
)

// cdBacklogStatuses are the activity states a Programme Lead's backlog
// counts (pl_oversight's _pending_statuses).
var cdBacklogStatuses = []string{"returned_by_pl", "returned_by_ia", "salesforce_id_required", "awaiting_ia_verification"}

// cdNotInPlan are NOT_IN_PLAN_ACTIVITY_STATUSES: called-off work.
var cdNotInPlan = []string{"cancelled", "rejected", "deferred", "not_planned"}

// cdApprovedEnvelope are the General Budget states budget_utilisation_detail
// counts as the approved envelope.
var cdApprovedEnvelope = []string{"approved_by_rvp", "sent_to_accountant", "disbursed", "closed"}

// cdRow is one of cd_todos' dicts.
type cdRow struct{ id, title, description, category, priority, action, url string }

// cdAnalyticsTodos is _cd_analytics_todos for the Country Director. A year
// with any approved milestone allocation is passed on: a lead's achievement
// is then their allocation contract's, which Go does not read here.
func cdAnalyticsTodos(ctx context.Context, s *Service, r *reader) ([]todo, error) {
	if r.role != cdRole {
		return nil, nil
	}
	rows, err := s.cdTodos(ctx, r)
	if err != nil {
		return nil, err
	}
	out := make([]todo, 0, len(rows))
	for _, c := range rows {
		out = append(out, todo{ID: c.id, Title: c.title, Description: c.description, Category: c.category, Priority: c.priority,
			StatusKey: "waiting_me", StatusLabel: "Waiting on Me", StatusTone: "info", DueLabel: "—", DueTone: "neutral",
			Actionable: true, Linked: cdProfileLabel, ActionLabel: c.action, ActionURL: c.url, Shape: cdShape(c.url, r.fy),
			Due: &r.today})
	}
	return out, nil
}

// cdShape is a row's link shape in rules.OpenLinks: a lead's id and the
// year stand as placeholders.
func cdShape(url, fy string) string {
	if strings.HasPrefix(url, "/staff/") {
		return "/staff/{id}"
	}
	if trimmed, ok := strings.CutSuffix(url, "&fy="+fy); ok {
		return trimmed + "&fy={fy}"
	}
	return url
}

// cdScope is resolve_cd_scope(fy, country=…) with no filter: the country's
// operating schools and CCEOs.
type cdScope struct {
	country, fy string
	schools     map[string]cdSchool
	cceos       []targets.Person // newest account first (User's ordering)
}

type cdSchool struct {
	ssaDone  bool
	district string
}

// cdLead is one Programme Lead's team (_pl_cceos_batch).
type cdLead struct {
	id, name, staff string
	members         []cdMember
}

type cdMember struct {
	staffID, userID string
	schools         map[string]bool
}

// cdLeadRow is one pl_oversight row, as cd_todos reads it.
type cdLeadRow struct {
	lead         cdLead
	pct, atRisk  int
	risk         string
	highOrHigher bool
}

func (s *Service) cdTodos(ctx context.Context, r *reader) ([]cdRow, error) {
	fy := r.fy
	if contract, err := allocations.Exist(ctx, s.db, fy); err != nil || contract {
		return nil, passOnErr(contract, err)
	}
	cd, err := s.cdScope(ctx, r.scope.Country, fy)
	if err != nil {
		return nil, err
	}
	if len(cd.cceos) == 0 {
		// cd_todos then weighs each team against its own agreed areas.
		return nil, errPassOn
	}
	roster, err := targets.Prepare(ctx, s.db, cd.cceos, fy, nil)
	if errors.Is(err, targets.ErrHandOn) {
		return nil, errPassOn
	}
	if err != nil {
		return nil, err
	}
	areas := agreedAreas(roster, cd.cceos)
	leads, err := s.cdOversight(ctx, cd, roster, areas)
	if err != nil {
		return nil, err
	}
	var out []cdRow
	underperforming := 0
	for _, o := range leads {
		if !o.highOrHigher {
			continue
		}
		underperforming++
		out = append(out, cdRow{id: "cd-recovery-" + o.lead.id, title: "Request Recovery Plan from PL",
			description: o.lead.name + "'s team is " + o.risk + " — " + strconv.Itoa(o.atRisk) + " schools at risk.",
			category:    "PL Oversight", priority: "high", action: "Review PL", url: "/staff/" + o.lead.id})
	}
	used, err := s.cdBudgetUse(ctx, fy)
	if err != nil {
		return nil, err
	}
	recommended, err := s.cdRecommended(ctx, cd, underperforming, used)
	if err != nil {
		return nil, err
	}
	out = append(out, recommended...)
	var awaiting int
	if err := s.db.QueryRow(ctx, `SELECT COUNT(*) FROM weekly_fund_request WHERE fy = $1 AND status = $2`,
		fy, cdWeeklyStatus).Scan(&awaiting); err != nil {
		return nil, err
	}
	if awaiting > 0 {
		out = append(out, cdRow{id: "cd-weekly-approve", title: "Approve PL Weekly Fund Request",
			description: strconv.Itoa(awaiting) + " weekly fund request(s) awaiting your approval.",
			category:    "Finance", priority: "high", action: "Open Approvals", url: "/fund-requests/weekly"})
	}
	if used < cdLowBudgetPct {
		out = append(out, cdRow{id: "cd-budget-util", title: "Review Budget Underutilization",
			description: "Country disbursement is below 50% of the requested pipeline.",
			category:    "Finance", priority: "medium", action: "Review Budget", url: "/budget"})
	}
	return out[:min(cdAnalyticsLimit, len(out))], nil
}

// cdOversight is pl_oversight's rows, lowest achievement first: each lead's
// team achievement, schools without this year's SSA, backlog and risk.
func (s *Service) cdOversight(ctx context.Context, cd cdScope, roster *targets.Roster, areas []targets.Area) ([]cdLeadRow, error) {
	leads, err := s.cdLeads(ctx, cd)
	if err != nil {
		return nil, err
	}
	backlog, err := s.cdBacklog(ctx, cd)
	if err != nil {
		return nil, err
	}
	staffUsers, err := s.staffUserIDs(ctx, leads)
	if err != nil {
		return nil, err
	}
	inRoster := map[string]targets.Person{}
	for _, p := range cd.cceos {
		inRoster[p.UserID] = p
	}
	if len(areas) == 0 {
		// With no CCEO agreement the existing service weighs each team over
		// its own agreed areas against CCEO series that carry none, which
		// fails on any team that has some; with none, every team reads 0
		// of 0.
		if found, err := s.teamsAgreeAreas(ctx, cd.fy, leads, staffUsers); err != nil || found {
			return nil, passOnErr(found, err)
		}
	}
	out := make([]cdLeadRow, 0, len(leads))
	for _, l := range leads {
		users := map[string]bool{l.id: true}
		resp, schools := map[string]bool{}, map[string]bool{}
		for _, m := range l.members {
			if m.userID != "" {
				users[m.userID] = true
				resp[m.userID] = true
			}
			if u := staffUsers[m.staffID]; u != "" {
				users[u] = true
			}
			resp[m.staffID] = true
			for id := range m.schools {
				schools[id] = true
			}
		}
		pct, target := teamWeightedPct(roster, inRoster, users, areas)
		atRisk := 0
		for id := range schools {
			if !cd.schools[id].ssaDone {
				atRisk++
			}
		}
		late := 0
		for _, a := range backlog {
			if resp[a.responsible] || schools[a.school] {
				late++
			}
		}
		risk := plRisk(pct, target, atRisk, len(schools), late)
		out = append(out, cdLeadRow{lead: l, pct: pct, atRisk: atRisk, risk: risk,
			highOrHigher: risk == "High Risk" || risk == "Critical Risk"})
	}
	sort.SliceStable(out, func(i, j int) bool { return out[i].pct < out[j].pct })
	return out, nil
}

// teamsAgreeAreas is whether anyone on a lead's team (the lead, their
// supervisees and those profiles' accounts) has agreed target areas.
func (s *Service) teamsAgreeAreas(ctx context.Context, fy string, leads []cdLead, staffUsers map[string]string) (bool, error) {
	var people []targets.Person
	for _, l := range leads {
		people = append(people, targets.Person{UserID: l.id, StaffID: l.staff})
		for _, m := range l.members {
			user := m.userID
			if user == "" {
				user = staffUsers[m.staffID]
			}
			people = append(people, targets.Person{UserID: user, StaffID: m.staffID})
		}
	}
	if len(people) == 0 {
		return false, nil
	}
	roster, err := targets.Prepare(ctx, s.db, people, fy, nil)
	if errors.Is(err, targets.ErrHandOn) {
		return true, nil
	}
	if err != nil {
		return false, err
	}
	return len(agreedAreas(roster, people)) > 0, nil
}

// passOnErr is errPassOn when found, else err.
func passOnErr(found bool, err error) error {
	if err != nil {
		return err
	}
	if found {
		return errPassOn
	}
	return nil
}

// cdScope reads the country's operating schools (active_schools in the
// country's regions) and its CCEOs: every live account holding the CCEO
// role whose profile is in the country, newest first, with their profile.
func (s *Service) cdScope(ctx context.Context, country, fy string) (cdScope, error) {
	cd := cdScope{country: country, fy: fy, schools: map[string]cdSchool{}}
	rows, err := s.db.Query(ctx, `SELECT s.id, COALESCE(s.current_fy_ssa_status, '') = 'done', COALESCE(s.district_id, '')
FROM school s LEFT JOIN region rg ON rg.id = s.region_id
WHERE s.deleted_at IS NULL AND s.operational_status = ANY($1) AND ($2 = '' OR rg.country = $2)`, rules.OperatingStatuses, country)
	if err != nil {
		return cd, err
	}
	for rows.Next() {
		var id string
		var sc cdSchool
		if err := rows.Scan(&id, &sc.ssaDone, &sc.district); err != nil {
			rows.Close()
			return cd, err
		}
		cd.schools[id] = sc
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return cd, err
	}
	rows, err = s.db.Query(ctx, `SELECT u.id, COALESCE((SELECT sp.id FROM staff_profile sp
    WHERE sp.user_id = u.id AND sp.deleted_at IS NULL ORDER BY sp.id LIMIT 1), '')
FROM "user" u WHERE 'CCEO' = ANY(u.roles) AND u.deleted_at IS NULL
  AND ($1 = '' OR EXISTS (SELECT 1 FROM staff_profile sp WHERE sp.user_id = u.id AND sp.country = $1))
ORDER BY u.created_at DESC, u.id`, country)
	if err != nil {
		return cd, err
	}
	cd.cceos, err = pgx.CollectRows(rows, func(row pgx.CollectableRow) (targets.Person, error) {
		var p targets.Person
		return p, row.Scan(&p.UserID, &p.StaffID)
	})
	return cd, err
}

// agreedAreas is agreed_target_areas over the CCEOs: the union of the areas
// they agreed, in roster order and each person's own order.
func agreedAreas(roster *targets.Roster, people []targets.Person) []targets.Area {
	seen := map[string]bool{}
	var out []targets.Area
	for _, p := range people {
		for _, a := range roster.Areas(p) {
			if !seen[a.Key] {
				seen[a.Key] = true
				out = append(out, a)
			}
		}
	}
	return out
}

// teamWeightedPct is _weighted_achievement over the primed CCEO series
// (team_weighted_pct): each team member with a series is weighted over the
// country's agreed areas for the whole year; members with no target are
// left out of the average, which rounds half to even. The second answer is
// the team's total target.
func teamWeightedPct(roster *targets.Roster, inRoster map[string]targets.Person, users map[string]bool,
	areas []targets.Area) (int, int) {
	keys := make([]string, len(areas))
	for i, a := range areas {
		keys[i] = a.Key
	}
	months := []int{1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12}
	sum, n, total := 0, 0, 0
	for id := range users {
		p, ok := inRoster[id]
		if !ok {
			continue
		}
		t, a := roster.SeriesOver(p, keys)
		pct, _, target := targets.WeightedPct(areas, t, a, months)
		total += target
		if pct != nil {
			sum += *pct
			n++
		}
	}
	if n == 0 {
		return 0, total
	}
	return int(math.RoundToEven(float64(sum) / float64(n))), total
}

// plRisk is CDAnalyticsService._pl_risk's label.
func plRisk(pct, target, atRisk, schools, backlog int) string {
	score := 0
	switch {
	case target != 0 && pct < 40:
		score += 2
	case target != 0 && pct < 55:
		score++
	}
	if schools != 0 {
		share := float64(atRisk) / float64(schools)
		switch {
		case share > 0.6:
			score += 2
		case share > 0.3:
			score++
		}
	}
	if backlog >= 10 {
		score++
	}
	switch {
	case score >= 4:
		return "Critical Risk"
	case score >= 2:
		return "High Risk"
	case score >= 1:
		return "Medium Risk"
	}
	return "Low Risk"
}

// cdLeads is _pls with _pl_cceos_batch: every live Programme Lead by name,
// each with the live profiles they supervise (by profile id) and each
// member's assigned schools that are in the country's operating set.
func (s *Service) cdLeads(ctx context.Context, cd cdScope) ([]cdLead, error) {
	rows, err := s.db.Query(ctx, `SELECT u.id, COALESCE(u.name, ''), COALESCE((SELECT sp.id FROM staff_profile sp
    WHERE sp.user_id = u.id AND sp.deleted_at IS NULL ORDER BY sp.id LIMIT 1), '')
FROM "user" u WHERE 'Program Lead' = ANY(u.roles) AND u.deleted_at IS NULL ORDER BY u.name`)
	if err != nil {
		return nil, err
	}
	type lead struct{ id, name, staff string }
	list, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (lead, error) {
		var l lead
		return l, row.Scan(&l.id, &l.name, &l.staff)
	})
	if err != nil {
		return nil, err
	}
	out := make([]cdLead, len(list))
	for i, l := range list {
		out[i] = cdLead{id: l.id, name: l.name, staff: l.staff}
		if l.staff == "" {
			continue
		}
		members, err := s.cdMembers(ctx, cd, l.staff)
		if err != nil {
			return nil, err
		}
		out[i].members = members
	}
	return out, nil
}

// cdMembers are the live profiles a lead's profile supervises, by profile
// id, each with its assigned schools in the country's operating set.
func (s *Service) cdMembers(ctx context.Context, cd cdScope, supervisor string) ([]cdMember, error) {
	rows, err := s.db.Query(ctx, `SELECT sp.id, COALESCE(sp.user_id, '') FROM staff_supervisor_assignment a
JOIN staff_profile sp ON sp.id = a.supervisee_id
WHERE a.supervisor_id = $1 AND sp.deleted_at IS NULL ORDER BY a.supervisee_id`, supervisor)
	if err != nil {
		return nil, err
	}
	members, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (cdMember, error) {
		m := cdMember{schools: map[string]bool{}}
		return m, row.Scan(&m.staffID, &m.userID)
	})
	if err != nil {
		return nil, err
	}
	for j := range members {
		schools, err := s.strings(ctx, `SELECT school_id FROM staff_school_assignment WHERE staff_id = $1`, members[j].staffID)
		if err != nil {
			return nil, err
		}
		for _, id := range schools {
			if _, ok := cd.schools[id]; ok {
				members[j].schools[id] = true
			}
		}
	}
	return members, nil
}

// staffUserIDs is _staff_user_ids over every team member: each live
// profile's account.
func (s *Service) staffUserIDs(ctx context.Context, leads []cdLead) (map[string]string, error) {
	var ids []string
	for _, l := range leads {
		for _, m := range l.members {
			ids = append(ids, m.staffID)
		}
	}
	out := map[string]string{}
	if len(ids) == 0 {
		return out, nil
	}
	rows, err := s.db.Query(ctx, `SELECT id, COALESCE(user_id, '') FROM staff_profile WHERE id = ANY($1) AND deleted_at IS NULL`, ids)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	for rows.Next() {
		var id, user string
		if err := rows.Scan(&id, &user); err != nil {
			return nil, err
		}
		out[id] = user
	}
	return out, rows.Err()
}

type cdActivity struct{ school, responsible string }

// cdBacklog is _activity_rows over _country_activities narrowed to the
// backlog states: the year's planned work in the country (its school's or
// its cluster's region, or, with neither, a responsible profile of the
// country).
func (s *Service) cdBacklog(ctx context.Context, cd cdScope) ([]cdActivity, error) {
	rows, err := s.db.Query(ctx, `SELECT COALESCE(a.school_id, ''), COALESCE(a.responsible_staff_id, '')
FROM activity a
LEFT JOIN school s ON s.id = a.school_id LEFT JOIN region rg ON rg.id = s.region_id
LEFT JOIN cluster c ON c.id = a.cluster_id LEFT JOIN district d ON d.id = c.district_id LEFT JOIN region crg ON crg.id = d.region_id
WHERE a.fy = $1 AND a.deleted_at IS NULL AND NOT (a.status IS NOT NULL AND a.status = ANY($2)) AND a.status = ANY($3)
  AND ($4 = '' OR rg.country = $4 OR crg.country = $4
       OR (a.school_id IS NULL AND a.cluster_id IS NULL
           AND a.responsible_staff_id IN (SELECT id FROM staff_profile WHERE country = $4 AND deleted_at IS NULL)))`,
		cd.fy, cdNotInPlan, cdBacklogStatuses, cd.country)
	if err != nil {
		return nil, err
	}
	return pgx.CollectRows(rows, func(row pgx.CollectableRow) (cdActivity, error) {
		var a cdActivity
		return a, row.Scan(&a.school, &a.responsible)
	})
}

// cdRecommended is recommended_actions' items with a count, as cd_todos
// words them.
func (s *Service) cdRecommended(ctx context.Context, cd cdScope, underperforming, used int) ([]cdRow, error) {
	noSSA := 0
	for _, sc := range cd.schools {
		if !sc.ssaDone {
			noSSA++
		}
	}
	lowLeadership, err := s.cdLowLeadership(ctx, cd)
	if err != nil {
		return nil, err
	}
	partners, err := partneroversight.FollowUps(ctx, s.db, cd.country, cd.fy)
	if err != nil {
		return nil, err
	}
	lowBudget := 0
	if used < cdLowBudgetPct {
		lowBudget = 1
	}
	var out []cdRow
	for _, item := range []struct {
		issue       string
		count       int
		danger      bool
		owner, link string
	}{
		{"Schools without SSA", noSSA, true, "PL", "?drill=risk&issue=no_ssa"},
		{"Districts with low Leadership scores (<5.0/10)", lowLeadership, false, "PL", "?drill=district_low_lship"},
		{"Partners needing follow-up", len(partners), false, "CD", "?drill=partner"},
		{"Underperforming CCEO teams (Ach. <55%)", underperforming, false, "PL", "?drill=pl"},
		{"Budget risks & low utilization (<50%)", lowBudget, false, "CD", "?drill=budget"},
	} {
		if item.count == 0 {
			continue
		}
		priority := "medium"
		if item.danger {
			priority = "high"
		}
		out = append(out, cdRow{id: "cd-rec-" + firstRunes(item.issue, 20), title: item.issue,
			description: strconv.Itoa(item.count) + " flagged — responsible: " + item.owner + ".",
			category:    "Recommended Action", priority: priority, action: "Review",
			url: "/analytics/country-director/drilldown" + item.link + "&fy=" + cd.fy})
	}
	return out, nil
}

// cdLowLeadership is how many districts' confirmed Leadership scores of the
// latest SSA year (up to fy) average below five once rounded to one decimal
// (_ssa_score).
func (s *Service) cdLowLeadership(ctx context.Context, cd cdScope) (int, error) {
	ids := make([]string, 0, len(cd.schools))
	for id := range cd.schools {
		ids = append(ids, id)
	}
	var latest *string
	if err := s.db.QueryRow(ctx, `SELECT MAX(fy) FROM ssa_record
WHERE school_id = ANY($1) AND verification_status = 'confirmed' AND fy <= $2`, ids, cd.fy).Scan(&latest); err != nil {
		return 0, err
	}
	if latest == nil {
		return 0, nil
	}
	rows, err := s.db.Query(ctx, `SELECT r.school_id, sc.score FROM ssa_record r JOIN ssa_score sc ON sc.ssa_record_id = r.id
WHERE r.school_id = ANY($1) AND r.verification_status = 'confirmed' AND r.fy = $2 AND sc.intervention = 'leadership'`,
		ids, *latest)
	if err != nil {
		return 0, err
	}
	defer rows.Close()
	sums, counts := map[string]float64{}, map[string]int{}
	for rows.Next() {
		var school string
		var score *float64
		if err := rows.Scan(&school, &score); err != nil {
			return 0, err
		}
		district := cd.schools[school].district
		if district == "" || score == nil {
			continue
		}
		sums[district] += *score
		counts[district]++
	}
	if err := rows.Err(); err != nil {
		return 0, err
	}
	low := 0
	for district, n := range counts {
		if ssaScore(sums[district]/float64(n)) < cdLowLeadership {
			low++
		}
	}
	return low, nil
}

// ssaScore is _ssa_score: round to six places, then to one.
func ssaScore(v float64) float64 {
	return pyRound(pyRound(v, 6), 1)
}

// pyRound is round(x, n) on the scaled value, half to even.
func pyRound(v float64, n int) float64 {
	scale := math.Pow(10, float64(n))
	return math.RoundToEven(v*scale) / scale
}

// cdBudgetUse is budget_utilisation_detail's pct with no filter: the year's
// disbursed advances against the RVP-approved envelope, or against the
// advances requested while no envelope is approved (percentage_or_zero).
func (s *Service) cdBudgetUse(ctx context.Context, fy string) (int, error) {
	var requested, disbursed, approved int64
	if err := s.db.QueryRow(ctx, `SELECT COALESCE(SUM(ar.amount), 0), COALESCE(SUM(ar.disbursed_amount), 0)
FROM advance_request ar JOIN activity a ON a.id = ar.activity_id WHERE a.fy = $1 AND a.deleted_at IS NULL`, fy).
		Scan(&requested, &disbursed); err != nil {
		return 0, err
	}
	if err := s.db.QueryRow(ctx, `SELECT COALESCE(SUM(total_amount), 0) FROM monthly_work_plan_budget
WHERE fy = $1 AND status = ANY($2)`, fy, cdApprovedEnvelope).Scan(&approved); err != nil {
		return 0, err
	}
	base := requested
	if approved != 0 {
		base = approved
	}
	if base == 0 {
		return 0, nil
	}
	return int(math.RoundToEven(float64(disbursed) / float64(base) * 100)), nil
}
