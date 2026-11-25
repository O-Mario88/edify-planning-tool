package planningoversight

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
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/partneroversight"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// Piece 4: the Schools & Coverage lens (view=coverage,
// coverage_service.planned_schools and training_coverage,
// coverage_workspace.html): every school with planned work in the period,
// grouped by day, week, month or quarter, with a cluster session listed
// once per school it invited; the schools a live cluster session names;
// and the operating schools that take a training and have none.

const coverageEmptyPlanned = "No school work is planned in this period for your team."

// CoverageRules are coverage_service's and school_status's.
type CoverageRules struct {
	RowLimit                int               `json:"row_limit"`
	AssignmentStatuses      []string          `json:"assignment_statuses"`
	LeftPartnerStatuses     []string          `json:"left_partner_statuses"`
	IAStatusLabels          map[string]string `json:"ia_status_labels"`
	Budget                  map[string]string `json:"budget"`
	DeadStatuses            []string          `json:"dead_statuses"`
	PendingApprovalStatuses []string          `json:"pending_approval_statuses"`
	ClusterSessionTypes     []string          `json:"cluster_session_types"`
	ClusterMeetingTypes     []string          `json:"cluster_meeting_types"`
	VisitTypes              []string          `json:"visit_types"`
	SchoolTrainingTypes     []string          `json:"school_training_types"`
	TrainedTypes            []string          `json:"trained_types"`
	OperatingStatuses       []string          `json:"operating_statuses"`
	VisitLabels             map[string]string `json:"visit_labels"`
	VisitTones              map[string]string `json:"visit_tones"`
	VisitStates             map[string]string `json:"visit_states"`
	VisitPrecedence         []string          `json:"visit_precedence"`
	Reasons                 map[string]string `json:"reasons"`
}

// coverageRow is one row of Planned Schools: a piece of work at a school.
type coverageRow struct {
	workKey, schoolID, code, school, owner, district, cluster string
	activityID, kind, partnerName, budget, ia, finance        string
	status                                                    string
	planned                                                   *time.Time
	partner                                                   bool
}

type coverageGroup struct {
	key, label string
	rows       []coverageRow
}

func (g coverageGroup) schools() int {
	seen := map[string]bool{}
	for _, r := range g.rows {
		if r.schoolID != "" {
			seen[r.schoolID] = true
		}
	}
	return len(seen)
}

func (g coverageGroup) activities() int {
	seen := map[string]bool{}
	for _, r := range g.rows {
		seen[r.workKey] = true
	}
	return len(seen)
}

// pageParam is CoverageGroup.page_param.
func (g coverageGroup) pageParam() string {
	b := strings.Builder{}
	for _, r := range g.key {
		if (r >= 'a' && r <= 'z') || (r >= 'A' && r <= 'Z') || (r >= '0' && r <= '9') {
			b.WriteRune(r)
		} else {
			b.WriteRune('_')
		}
	}
	safe := strings.Trim(b.String(), "_")
	if safe == "" {
		safe = "group"
	}
	return "planned_" + safe + "_page"
}

// coverageSchool is one school of training_coverage's tables.
type coverageSchool struct {
	pk, code, name, owner, district, clusterID, clusterName string
	schoolType                                              *string
	visit, visitTone                                        string
	nextVisit                                               *time.Time
	training, reason, activityLabel, kind, status           string
	delivery, partnerName                                   string
	day                                                     *time.Time
}

type coverageState struct {
	periodStart, periodEnd          time.Time
	planned, missing                []coverageSchool
	plannedCount, missingCount      int
	inSchoolCount                   int
	plannedTruncated, missTruncated bool
}

// buildCoverage answers the coverage lens for a reader the lens opens for,
// or served=false.
func (s *Service) buildCoverage(ctx context.Context, p auth.Principal, reader Reader, query url.Values) (*screensv1.GetPageResponse, bool, error) {
	now := s.now()
	per, ok := partneroversight.ReadPeriod(query, now)
	if !ok {
		return nil, false, nil
	}
	w, served, err := s.lensBase(ctx, p, reader, query, per, now)
	if !served || err != nil {
		return nil, served, err
	}
	scope, err := schooldirectory.ResolveScope(ctx, s.db, p, now)
	if err != nil {
		return nil, true, err
	}
	var team, regions []string
	switch reader.Scope {
	case "pl":
		if p.ActiveRole != rules.TeamPlan.LeadRole {
			return nil, false, nil
		}
		own, err := partneroversight.BothIDSpaces(ctx, s.db, []string{p.UserID, p.StaffProfileID})
		if err != nil {
			return nil, true, err
		}
		supervised, err := partneroversight.BothIDSpaces(ctx, s.db, scope.SupervisedStaffIDs)
		if err != nil {
			return nil, true, err
		}
		team = append(append([]string{}, own...), supervised...)
		if len(team) == 0 {
			return nil, false, nil
		}
	case "region":
		if regions, err = s.regionalReach(ctx, p, now); err != nil || regions == nil {
			return nil, err != nil, err
		}
	}
	items, err := s.buildItemsKeeping(ctx, team, regions, w.years, w.read, w.today, true)
	if err != nil {
		return nil, true, err
	}
	handovers, err := s.handoverItems(ctx, team, regions, w.years, w.read)
	if err != nil {
		return nil, true, err
	}
	items = append(items, handovers...)
	groups, err := s.plannedSchools(ctx, items, per.Kind)
	if err != nil {
		return nil, true, err
	}
	cov, err := s.trainingCoverage(ctx, scope, per, w.years)
	if err != nil {
		return nil, true, err
	}
	lens := "Team"
	switch reader.Scope {
	case "country":
		lens = "Country"
	case "region":
		lens = "Regional"
	}
	return coveragePage(w, groups, cov, lens, reader, query), true, nil
}

// handoverItems is _unscheduled_assignments_in_scope with _assignment_item:
// the hand-overs a Partner has not dated, in the scope, opened in the period.
func (s *Service) handoverItems(ctx context.Context, team, regions, years []string, read periodRead) ([]*item, error) {
	c := rules.TeamPlan.Coverage
	rows, err := s.db.Query(ctx, `
SELECT pa.id, pa.status, COALESCE(pa.school_id, ''), COALESCE(s.school_id, ''), COALESCE(s.name, ''),
  COALESCE(s.school_type, ''), COALESCE(s.district_id, ''), COALESCE(sd.name, ''), s.id IS NOT NULL,
  COALESCE(pa.cluster_id, ''), COALESCE(c.name, ''), COALESCE(c.district_id, ''), COALESCE(cd.name, ''),
  COALESCE(pa.expected_activity_type, ''), COALESCE(pa.monitoring_staff_id, ''), COALESCE(pa.assigning_staff_id, ''),
  COALESCE(pt.name, ''), pa.created_at
FROM partner_assignment pa
LEFT JOIN school s ON s.id = pa.school_id
LEFT JOIN district sd ON sd.id = s.district_id
LEFT JOIN cluster c ON c.id = pa.cluster_id
LEFT JOIN district cd ON cd.id = c.district_id
LEFT JOIN partner pt ON pt.id = pa.partner_id
WHERE pa.status = ANY($1) AND NOT (pa.status = ANY($2) OR (pa.status = 'returned_to_staff' AND pa.resolved_at IS NOT NULL))
  AND ($3::text[] IS NULL OR pa.monitoring_staff_id = ANY($3) OR pa.assigning_staff_id = ANY($3))
  AND ($4::text[] IS NULL OR s.region_id = ANY($4) OR cd.region_id = ANY($4))
ORDER BY pa.created_at DESC, pa.id`, c.AssignmentStatuses, c.LeftPartnerStatuses, team, regions)
	if err != nil {
		return nil, fmt.Errorf("planningoversight: reading the hand-overs not dated: %w", err)
	}
	type handover struct {
		it                    *item
		monitoring, assigning string
	}
	list := []handover{}
	owners := []string{}
	for rows.Next() {
		it := &item{a: &act{}, partner: true, plannedFrom: "—", training: "—"}
		var h handover
		var schoolType, sDistrictID, sDistrict, cDistrictID, cDistrict string
		var hasSchool bool
		var created time.Time
		if err := rows.Scan(&it.assignment, &it.assignmentStatus, &it.schoolPK, &it.schoolCode, &it.schoolName,
			&schoolType, &sDistrictID, &sDistrict, &hasSchool, &it.clusterID, &it.clusterName, &cDistrictID, &cDistrict,
			&it.activityType, &h.monitoring, &h.assigning, &it.partnerName, &created); err != nil {
			rows.Close()
			return nil, fmt.Errorf("planningoversight: reading the hand-overs not dated: %w", err)
		}
		if !createdInPeriod(created, years, read) {
			continue
		}
		it.schoolType = schoolType
		it.schoolCode = first(it.schoolCode, it.schoolPK, "—")
		if hasSchool {
			it.districtID, it.districtName = sDistrictID, sDistrict
		}
		if it.districtName == "" && it.clusterID != "" && cDistrictID != "" {
			it.districtID, it.districtName = cDistrictID, cDistrict
		}
		it.owner = first(h.monitoring, h.assigning)
		h.it = it
		list = append(list, h)
		owners = append(owners, it.owner)
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, err
	}
	names, err := s.staffNames(ctx, owners)
	if err != nil {
		return nil, err
	}
	out := make([]*item, len(list))
	for i, h := range list {
		h.it.ownerName = names[h.it.owner].name
		out[i] = h.it
	}
	return out, nil
}

// createdInPeriod is the hand-over's opening day (created_at.date(), the
// stored moment's UTC day) read against the period: its operational year
// among the years, then the month, quarter or dated days.
func createdInPeriod(created time.Time, years []string, read periodRead) bool {
	d := created.UTC()
	day := time.Date(d.Year(), d.Month(), d.Day(), 0, 0, 0, 0, time.UTC)
	if !slices.Contains(years, schooldirectory.OperationalFY(day)) {
		return false
	}
	switch {
	case read.month != 0:
		return int(day.Month()) == read.month
	case read.quarter != "":
		return quarterOf(day) == read.quarter
	case !read.start.IsZero():
		return !day.Before(read.start) && day.Before(read.end)
	}
	return true
}

// quarterOf is fy.get_quarter_for_date: Q1 is October to December.
func quarterOf(day time.Time) string {
	return "Q" + strconv.Itoa((int(day.Month())+2)%12/3+1)
}

// plannedSchools is coverage_service.planned_schools.
func (s *Service) plannedSchools(ctx context.Context, items []*item, period string) ([]coverageGroup, error) {
	ids := []string{}
	for _, it := range items {
		if it.a != nil && it.a.id != "" {
			ids = append(ids, it.a.id)
		}
	}
	requested, err := s.idSet(ctx, `SELECT DISTINCT cl.activity_id FROM weekly_fund_request_line l
JOIN activity_schedule_cost_line cl ON cl.id = l.activity_budget_line_id WHERE cl.activity_id = ANY($1)`, ids)
	if err != nil {
		return nil, err
	}
	rows := []coverageRow{}
	for _, it := range items {
		if it.schoolPK != "" {
			rows = append(rows, coverageRowOf(it, it.schoolPK, it.schoolCode, it.schoolName, it.ownerName, it.districtName, requested))
		}
	}
	invited, err := s.invitedSchoolRows(ctx, items, requested)
	if err != nil {
		return nil, err
	}
	rows = append(rows, invited...)
	groups := []coverageGroup{}
	at := map[string]int{}
	for _, r := range rows {
		key, label := groupOf(r.planned, period)
		i, ok := at[key]
		if !ok {
			i = len(groups)
			at[key] = i
			groups = append(groups, coverageGroup{key: key, label: label})
		}
		groups[i].rows = append(groups[i].rows, r)
	}
	slices.SortStableFunc(groups, func(x, y coverageGroup) int {
		switch {
		case x.key == "undated" && y.key == "undated":
			return 0
		case x.key == "undated":
			return 1
		case y.key == "undated":
			return -1
		}
		return strings.Compare(x.key, y.key)
	})
	for i := range groups {
		slices.SortStableFunc(groups[i].rows, func(x, y coverageRow) int {
			if c := compareDay(x.planned, y.planned); c != 0 {
				return c
			}
			return compareText(x.school, y.school)
		})
	}
	return groups, nil
}

// coverageRowOf is _row_of.
func coverageRowOf(it *item, schoolID, code, school, owner, district string, requested map[string]bool) coverageRow {
	c := rules.TeamPlan.Coverage
	r := coverageRow{schoolID: schoolID, code: code, school: school, owner: first(owner, "Unassigned"), district: district,
		cluster: it.clusterName, kind: it.activityType, partner: it.partner, partnerName: it.partnerName, planned: it.plannedDate}
	switch {
	case it.a != nil && it.a.id != "":
		r.workKey, r.activityID = it.a.id, it.a.id
	case it.assignment != "":
		r.workKey = it.assignment
	default:
		r.workKey = "awaiting:" + schoolID
	}
	switch {
	case r.activityID != "" && requested[r.activityID]:
		r.budget = c.Budget["in_weekly_request"]
	case it.plannedCost != 0:
		r.budget = c.Budget["created"]
	case it.costOnVisit:
		r.budget = c.Budget["in_school_visit"]
	default:
		r.budget = c.Budget["no_cost"]
	}
	ia, finance := "", ""
	if it.a != nil {
		ia, finance = it.a.ia, it.a.payment
	}
	label, ok := c.IAStatusLabels[ia]
	if !ok {
		label = "Pending"
	}
	r.ia, r.finance = label, finance
	r.status = first(it.status, it.assignmentStatus)
	return r
}

// groupOf is the row's group for the period (planned_schools' and
// _group_of): its quarter across a year, its month in a quarter, its week
// in a month, its day in a week.
func groupOf(day *time.Time, period string) (string, string) {
	if day == nil {
		return "undated", "No date yet"
	}
	d := *day
	switch period {
	case "week":
		return d.Format("2006-01-02"), d.Weekday().String() + " " + strconv.Itoa(d.Day()) + " " + d.Month().String()[:3]
	case "month":
		week := min(5, (d.Day()-1)/7+1)
		return "w" + strconv.Itoa(week), "Week " + strconv.Itoa(week)
	case "quarter":
		return "m" + strconv.Itoa(int(d.Month())), d.Month().String() + " " + strconv.Itoa(d.Year())
	}
	q := quarterOf(d)
	spans := map[string]string{"Q1": "Oct–Dec", "Q2": "Jan–Mar", "Q3": "Apr–Jun", "Q4": "Jul–Sep"}
	return q, q + " · " + spans[q]
}

// invitedSchoolRows is _invited_school_rows: a cluster session's row at
// each school it invited (or that attended), else at its cluster's
// clustered operating schools.
func (s *Service) invitedSchoolRows(ctx context.Context, items []*item, requested map[string]bool) ([]coverageRow, error) {
	c := rules.TeamPlan.Coverage
	sessions := map[string]*item{}
	ids := []string{}
	for _, it := range items {
		if it.a != nil && it.a.id != "" && it.schoolPK == "" && slices.Contains(c.ClusterSessionTypes, it.activityType) {
			if _, seen := sessions[it.a.id]; !seen {
				ids = append(ids, it.a.id)
			}
			sessions[it.a.id] = it
		}
	}
	if len(ids) == 0 {
		return nil, nil
	}
	type pair struct{ activity, school string }
	attendance := []pair{}
	rows, err := s.db.Query(ctx, `SELECT a.activity_id, a.school_id FROM cluster_activity_attendance a JOIN school s ON s.id = a.school_id
WHERE a.activity_id = ANY($1) AND (a.invited OR a.attended) ORDER BY s.name, a.id`, ids)
	if err != nil {
		return nil, fmt.Errorf("planningoversight: reading the sessions' schools: %w", err)
	}
	withRows := map[string]bool{}
	for rows.Next() {
		var p pair
		if err := rows.Scan(&p.activity, &p.school); err != nil {
			rows.Close()
			return nil, fmt.Errorf("planningoversight: reading the sessions' schools: %w", err)
		}
		attendance = append(attendance, p)
		withRows[p.activity] = true
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, err
	}
	clusters := []string{}
	for _, id := range ids {
		if it := sessions[id]; !withRows[id] && it.clusterID != "" && !slices.Contains(clusters, it.clusterID) {
			clusters = append(clusters, it.clusterID)
		}
	}
	type school struct{ pk, code, name, owner, district, cluster string }
	byPK := map[string]school{}
	read := func(sql string, args ...any) ([]school, error) {
		rows, err := s.db.Query(ctx, `SELECT s.id, COALESCE(s.school_id, ''), COALESCE(s.name, ''), COALESCE(s.account_owner_id, ''),
  COALESCE(d.name, ''), COALESCE(s.cluster_id, '') FROM school s LEFT JOIN district d ON d.id = s.district_id WHERE `+sql, args...)
		if err != nil {
			return nil, fmt.Errorf("planningoversight: reading the invited schools: %w", err)
		}
		return pgx.CollectRows(rows, func(r pgx.CollectableRow) (school, error) {
			var sc school
			err := r.Scan(&sc.pk, &sc.code, &sc.name, &sc.owner, &sc.district, &sc.cluster)
			return sc, err
		})
	}
	named := []string{}
	for _, p := range attendance {
		named = append(named, p.school)
	}
	if len(named) > 0 {
		found, err := read(`s.id = ANY($1)`, named)
		if err != nil {
			return nil, err
		}
		for _, sc := range found {
			byPK[sc.pk] = sc
		}
	}
	if len(clusters) > 0 {
		fallback, err := read(`s.cluster_id = ANY($1) AND s.cluster_status = 'clustered' AND s.deleted_at IS NULL
  AND (s.operational_status IS NULL OR s.operational_status = ANY($2)) ORDER BY s.created_at DESC, s.id`, clusters, c.OperatingStatuses)
		if err != nil {
			return nil, err
		}
		for _, sc := range fallback {
			byPK[sc.pk] = sc
		}
		for _, id := range ids {
			it := sessions[id]
			if withRows[id] || it.clusterID == "" {
				continue
			}
			for _, sc := range fallback {
				if sc.cluster == it.clusterID {
					attendance = append(attendance, pair{activity: id, school: sc.pk})
				}
			}
		}
	}
	if len(attendance) == 0 {
		return nil, nil
	}
	ownerIDs := []string{}
	for _, sc := range byPK {
		if sc.owner != "" {
			ownerIDs = append(ownerIDs, sc.owner)
		}
	}
	owners, err := s.ownerNames(ctx, ownerIDs)
	if err != nil {
		return nil, err
	}
	out := []coverageRow{}
	for _, p := range attendance {
		sc, ok := byPK[p.school]
		if !ok {
			continue
		}
		out = append(out, coverageRowOf(sessions[p.activity], sc.pk, sc.code, sc.name, owners[sc.owner], sc.district, requested))
	}
	return out, nil
}

// ownerNames is coverage_service._owner_names: a school's account owner's
// name, under the profile id and the user id, where the user has a name.
func (s *Service) ownerNames(ctx context.Context, ids []string) (map[string]string, error) {
	out := map[string]string{}
	if len(ids) == 0 {
		return out, nil
	}
	rows, err := s.db.Query(ctx, `SELECT sp.id, COALESCE(sp.user_id, ''), COALESCE(u.name, '')
FROM staff_profile sp LEFT JOIN "user" u ON u.id = sp.user_id WHERE sp.id = ANY($1) OR sp.user_id = ANY($1)`, ids)
	if err != nil {
		return nil, fmt.Errorf("planningoversight: reading the schools' owners: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var id, user, name string
		if err := rows.Scan(&id, &user, &name); err != nil {
			return nil, fmt.Errorf("planningoversight: reading the schools' owners: %w", err)
		}
		if user != "" && name != "" {
			out[id], out[user] = name, name
		}
	}
	return out, rows.Err()
}
