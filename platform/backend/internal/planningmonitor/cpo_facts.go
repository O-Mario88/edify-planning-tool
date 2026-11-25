package planningmonitor

import (
	"context"
	"fmt"
	"slices"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// Positions in a Partner's counts (coverage.P_*): dated before, inside and in
// the year; waiting before, inside and in the year; verified and returned
// inside; and how much of the year's Partner work is SSA Support.
const (
	pSchedB = iota
	pSchedI
	pSchedT
	pPendB
	pPendI
	pPendT
	pVerified
	pReturned
	pSSAT
	pWidth
)

// cpoSchool is coverage.SchoolFacts: one eligible school and what its
// records say about the year.
type cpoSchool struct {
	id, code, name, schoolType, family string
	ownerKey, rawOwner                 string
	regionID, districtID               string
	clusterID, rawClusterID            string // clusterID only for an active cluster
	clusterStatus                      string
	staff                              [4]int // before, inside, total, verified inside
	partners                           map[string]*[pWidth]int
	partnerOrder                       []string
	training                           [4]int
	meeting                            [3]int
	trainingPartner                    [4]int
	trainingWaiting                    [3]int
	staffSSA                           int
	withPartner                        bool
	annualStaffClaims                  int
	annualHolder                       string
}

func (s *cpoSchool) clustered() bool { return s.clusterID != "" }
func (s *cpoSchool) governed() bool {
	return s.family != rules.CountryOversight.UnmappedFamily
}

// partnerCounts is _partner_counts.
func (s *cpoSchool) partnerCounts(partner string) *[pWidth]int {
	if s.partners == nil {
		s.partners = map[string]*[pWidth]int{}
	}
	c, ok := s.partners[partner]
	if !ok {
		c = &[pWidth]int{}
		s.partners[partner] = c
		s.partnerOrder = append(s.partnerOrder, partner)
	}
	return c
}

// cpoDay is _day: the planned date, else the local day of the scheduled moment.
func cpoDay(alias string) string {
	return "COALESCE(" + alias + ".planned_date, (" + alias + ".scheduled_date AT TIME ZONE '" + cpoZone + "')::date)"
}

// eligibleSchools is eligible_school_queryset's rows: the reader's school lens
// (scoped_school_queryset), never a duplicate record, created by the reporting
// date and operating on it (operating_on_q).
func eligibleSchools(ctx context.Context, db schooldirectory.Querier, scope schooldirectory.Scope, asOf time.Time,
	base []string) ([]*cpoSchool, error) {
	c := rules.CountryOversight
	args := []any{}
	reach := schooldirectory.AnalyticsReach(scope, &args)
	if base != nil {
		// active_schools().filter(account_owner_id__in=base): whole portfolios.
		args = append(args, rules.OperatingStatuses, base)
		reach += fmt.Sprintf(" AND s.operational_status = ANY($%d) AND s.account_owner_id = ANY($%d)", len(args)-1, len(args))
	}
	args = append(args, c.ExcludedDuplicateStatuses, asOf, c.ClosedStatuses)
	n := len(args)
	dup, day, closed := fmt.Sprintf("$%d", n-2), fmt.Sprintf("$%d::date", n-1), fmt.Sprintf("$%d", n)
	local := func(col string) string { return "(" + col + " AT TIME ZONE '" + cpoZone + "')::date" }
	stillOpen := "(s.closure_effective_date > " + day + " OR (s.closure_effective_date IS NULL AND " + local("s.closed_at") + " > " + day + "))"
	rows, err := db.Query(ctx, `
SELECT s.id, COALESCE(s.school_id, ''), COALESCE(s.name, ''), COALESCE(s.school_type, ''), COALESCE(s.account_owner_id, ''),
  COALESCE(s.region_id, ''), COALESCE(s.district_id, ''), COALESCE(s.cluster_id, ''), COALESCE(s.cluster_status, '')
FROM school s
WHERE `+reach+` AND s.deleted_at IS NULL AND NOT COALESCE(s.duplicate_status = ANY(`+dup+`), false)
  AND `+local("s.created_at")+` <= `+day+`
  AND (s.operational_status = 'active'
    OR (s.operational_status = 'reopened' AND s.reopened_at IS NULL)
    OR (s.operational_status = 'reopened' AND `+local("s.reopened_at")+` <= `+day+`)
    OR (s.operational_status = 'reopened' AND `+local("s.reopened_at")+` > `+day+` AND `+stillOpen+`)
    OR (s.operational_status = ANY(`+closed+`) AND `+stillOpen+`))`, args...)
	if err != nil {
		return nil, fmt.Errorf("planningmonitor: the eligible schools: %w", err)
	}
	defer rows.Close()
	out := []*cpoSchool{}
	for rows.Next() {
		s := &cpoSchool{annualHolder: "open"}
		if err := rows.Scan(&s.id, &s.code, &s.name, &s.schoolType, &s.rawOwner, &s.regionID, &s.districtID, &s.rawClusterID,
			&s.clusterStatus); err != nil {
			return nil, fmt.Errorf("planningmonitor: the eligible schools: %w", err)
		}
		s.family = c.family(s.schoolType)
		out = append(out, s)
	}
	return out, rows.Err()
}

// loadFacts is load_facts over the eligible schools: the staff visits that
// count, the Partner's work, the trainings at the school, the cluster
// sessions and meetings whose roster names it, and the open hand-overs.
func loadFacts(ctx context.Context, db schooldirectory.Querier, schools []*cpoSchool, w cpoWindow, outside []string) error {
	if len(schools) == 0 {
		return nil
	}
	byID := make(map[string]*cpoSchool, len(schools))
	ids := make([]string, 0, len(schools))
	for _, s := range schools {
		byID[s.id] = s
		ids = append(ids, s.id)
	}
	if err := markActiveClusters(ctx, db, schools); err != nil {
		return err
	}
	if err := countStaffVisits(ctx, db, byID, ids, w, outside); err != nil {
		return err
	}
	if err := countPartnerWork(ctx, db, byID, ids, w, outside); err != nil {
		return err
	}
	if err := countSchoolTrainings(ctx, db, byID, ids, w); err != nil {
		return err
	}
	if err := countRosters(ctx, db, byID, ids, w); err != nil {
		return err
	}
	return countHandovers(ctx, db, byID, ids, w, outside)
}

func markActiveClusters(ctx context.Context, db schooldirectory.Querier, schools []*cpoSchool) error {
	ids := []string{}
	for _, s := range schools {
		if s.rawClusterID != "" {
			ids = append(ids, s.rawClusterID)
		}
	}
	if len(ids) == 0 {
		return nil
	}
	rows, err := db.Query(ctx, `SELECT id FROM cluster WHERE status = 'active' AND id = ANY($1)`, ids)
	if err != nil {
		return fmt.Errorf("planningmonitor: the active clusters: %w", err)
	}
	defer rows.Close()
	active := map[string]bool{}
	for rows.Next() {
		var id string
		if err := rows.Scan(&id); err != nil {
			return err
		}
		active[id] = true
	}
	for _, s := range schools {
		if active[s.rawClusterID] {
			s.clusterID = s.rawClusterID
		}
	}
	return rows.Err()
}

// formsIn is completion_columns.forms_in_q over the activity alias: the
// Salesforce ID in and the expected form uploaded, not quarantined.
func (b *sql) formsIn(alias string) string {
	return fmt.Sprintf(`(%[1]s.salesforce_activity_id IS NOT NULL AND %[1]s.salesforce_activity_id <> ''
  AND EXISTS (SELECT 1 FROM evidence_record e WHERE e.activity_id = %[1]s.id AND NOT e.quarantined
    AND e.kind = CASE WHEN %[1]s.activity_type = ANY(%[2]s) THEN 'attendance_form' ELSE 'visit_form' END))`,
		alias, b.arg(rules.CountryOversight.AttendanceTypes))
}

// verified is verified_q over the activity alias.
func (b *sql) verified(alias string) string {
	return fmt.Sprintf("(%s.status = ANY(%s) AND %s)", alias, b.arg(rules.CountryOversight.VerifiedStates), b.formsIn(alias))
}

// cpoPlanned is _planned_activities: the year's planned activities with a day.
func (b *sql) cpoPlanned(fy string) string {
	return fmt.Sprintf(`(a.fy = %s AND a.deleted_at IS NULL AND a.status = ANY(%s) AND %s IS NOT NULL)`,
		b.arg(fy), b.arg(rules.CountryOversight.PlannedStates), cpoDay("a"))
}

// windowCounts is _counts: before, inside and the whole year, by the day.
func (b *sql) windowCounts(day string, w cpoWindow) string {
	s, e := b.arg(w.start), b.arg(w.end)
	return fmt.Sprintf(`count(*) FILTER (WHERE %[1]s < %[2]s::date), count(*) FILTER (WHERE %[1]s >= %[2]s::date AND %[1]s < %[3]s::date), count(*)`,
		day, s, e)
}

func (b *sql) insideWindow(day string, w cpoWindow) string {
	return fmt.Sprintf("(%[1]s >= %[2]s::date AND %[1]s < %[3]s::date)", day, b.arg(w.start), b.arg(w.end))
}

func countStaffVisits(ctx context.Context, db schooldirectory.Querier, byID map[string]*cpoSchool, ids []string, w cpoWindow, outside []string) error {
	b := &sql{}
	day := cpoDay("a")
	q := `SELECT a.school_id, ` + b.windowCounts(day, w) + `, count(*) FILTER (WHERE ` + b.insideWindow(day, w) + ` AND ` + b.verified("a") + `),
  count(*) FILTER (WHERE ` + b.ssaKind() + `)
FROM activity a WHERE ` + b.cpoPlanned(w.fy) + ` AND a.school_id = ANY(` + b.arg(ids) + `) AND ` + b.countedVisit(outside) + `
  AND a.delivery_type IS DISTINCT FROM 'partner'
GROUP BY a.school_id`
	rows, err := db.Query(ctx, q, b.args...)
	if err != nil {
		return fmt.Errorf("planningmonitor: the staff visits: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var id string
		var before, inside, total, verified, ssa int
		if err := rows.Scan(&id, &before, &inside, &total, &verified, &ssa); err != nil {
			return err
		}
		if s := byID[id]; s != nil {
			s.staff[0] += before
			s.staff[1] += inside
			s.staff[2] += total
			s.staff[3] += verified
			s.staffSSA += ssa
		}
	}
	return rows.Err()
}

// countPartnerWork is _load_partner_activities: every live Partner activity
// at the schools that no open hand-over carries, grouped by whether the
// Partner dated it, whether it is a counted visit and whether it is a
// training at the school.
func countPartnerWork(ctx context.Context, db schooldirectory.Querier, byID map[string]*cpoSchool, ids []string, w cpoWindow, outside []string) error {
	c := rules.CountryOversight
	b := &sql{}
	day := cpoDay("a")
	dated := "CASE WHEN " + b.partnerPlanned() + " THEN 1 ELSE 0 END"
	counts := "CASE WHEN " + b.countedVisit(outside) + " THEN 1 ELSE 0 END"
	trains := "CASE WHEN a.activity_type = ANY(" + b.arg(rules.SchoolTrainingTypes) + ") AND a.cluster_id IS NULL THEN 1 ELSE 0 END"
	inside := b.insideWindow(day, w)
	start := b.arg(w.start)
	q := `SELECT a.school_id, COALESCE(a.assigned_partner_id, ''), ` + dated + `, ` + counts + `, ` + trains + `,
  count(*) FILTER (WHERE ` + day + ` < ` + start + `::date), count(*) FILTER (WHERE ` + inside + `),
  count(*) FILTER (WHERE ` + day + ` IS NULL), count(*),
  count(*) FILTER (WHERE ` + inside + ` AND ` + b.verified("a") + `), count(*) FILTER (WHERE ` + b.ssaKind() + `)
FROM activity a WHERE a.fy = ` + b.arg(w.fy) + ` AND a.deleted_at IS NULL AND a.school_id = ANY(` + b.arg(ids) + `)
  AND ` + b.partnerHeld() + ` AND ` + b.notOutside("a.project_id", outside) + `
  AND a.id NOT IN (SELECT pa.source_activity_id FROM partner_assignment pa WHERE pa.status = ANY(` + b.arg(c.UnscheduledHandoverStatuses) + `)
    AND pa.source_activity_id IS NOT NULL)
GROUP BY 1, 2, 3, 4, 5`
	rows, err := db.Query(ctx, q, b.args...)
	if err != nil {
		return fmt.Errorf("planningmonitor: the Partner's work: %w", err)
	}
	defer rows.Close()
	undatedInside := !w.fyStart.Before(w.start) && w.fyStart.Before(w.end)
	for rows.Next() {
		var id, partner string
		var isDated, isCounted, isTraining, before, in, undated, total, verified, ssa int
		if err := rows.Scan(&id, &partner, &isDated, &isCounted, &isTraining, &before, &in, &undated, &total, &verified, &ssa); err != nil {
			return err
		}
		s := byID[id]
		if s == nil || !s.governed() {
			continue
		}
		s.withPartner = true
		waitingInside := in
		if undatedInside {
			waitingInside += undated
		}
		if isTraining == 1 && isDated == 0 {
			s.trainingWaiting[0] += before
			s.trainingWaiting[1] += waitingInside
			s.trainingWaiting[2] += total
		}
		if isCounted == 0 {
			continue
		}
		p := s.partnerCounts(partner)
		p[pSSAT] += ssa
		if isDated == 1 {
			p[pSchedB] += before
			p[pSchedI] += in
			p[pSchedT] += total
			p[pVerified] += verified
		} else {
			p[pPendB] += before
			p[pPendI] += waitingInside
			p[pPendT] += total
		}
	}
	return rows.Err()
}

// countSchoolTrainings is the trainings at the school itself: staff's, and a
// Partner's once the Partner dated it.
func countSchoolTrainings(ctx context.Context, db schooldirectory.Querier, byID map[string]*cpoSchool, ids []string, w cpoWindow) error {
	for _, side := range []string{"staff", "partner"} {
		b := &sql{}
		day := cpoDay("a")
		mine := "a.delivery_type IS DISTINCT FROM 'partner'"
		if side == "partner" {
			mine = b.partnerPlanned()
		}
		q := `SELECT a.school_id, ` + b.windowCounts(day, w) + `, count(*) FILTER (WHERE ` + b.insideWindow(day, w) + ` AND ` + b.verified("a") + `)
FROM activity a WHERE ` + b.cpoPlanned(w.fy) + ` AND a.school_id = ANY(` + b.arg(ids) + `)
  AND a.activity_type = ANY(` + b.arg(rules.SchoolTrainingTypes) + `) AND a.cluster_id IS NULL AND ` + mine + `
GROUP BY a.school_id`
		if err := addCounts(ctx, db, byID, q, b.args, func(s *cpoSchool) []int {
			if side == "staff" {
				return s.training[:]
			}
			return s.trainingPartner[:]
		}, 4); err != nil {
			return err
		}
	}
	return nil
}

// countRosters is the cluster trainings (on the half of whoever delivers
// them) and meetings (no side) whose planned roster names the school.
func countRosters(ctx context.Context, db schooldirectory.Querier, byID map[string]*cpoSchool, ids []string, w cpoWindow) error {
	cluster := []string{}
	for _, t := range rules.TrainingTypes {
		if !slices.Contains(rules.SchoolTrainingTypes, t) {
			cluster = append(cluster, t)
		}
	}
	for _, part := range []struct {
		side  string
		types []string
		into  func(*cpoSchool) []int
		width int
	}{
		{"staff", cluster, func(s *cpoSchool) []int { return s.training[:] }, 4},
		{"partner", cluster, func(s *cpoSchool) []int { return s.trainingPartner[:] }, 4},
		{"", rules.ClusterMeetingTypes, func(s *cpoSchool) []int { return s.meeting[:] }, 3},
	} {
		b := &sql{}
		day := cpoDay("a")
		side := ""
		switch part.side {
		case "staff":
			side = " AND a.delivery_type IS DISTINCT FROM 'partner'"
		case "partner":
			side = " AND a.delivery_type = 'partner'"
		}
		verified := ""
		if part.width == 4 {
			verified = ", count(*) FILTER (WHERE " + b.insideWindow(day, w) + " AND " + b.verified("a") + ")"
		}
		q := `SELECT ca.school_id, ` + b.windowCounts(day, w) + verified + `
FROM cluster_activity_attendance ca JOIN activity a ON a.id = ca.activity_id
WHERE ca.invited AND a.fy = ` + b.arg(w.fy) + ` AND a.deleted_at IS NULL AND a.status = ANY(` + b.arg(rules.CountryOversight.PlannedStates) + `)
  AND a.activity_type = ANY(` + b.arg(part.types) + `) AND a.cluster_id IS NOT NULL AND ` + day + ` IS NOT NULL
  AND ca.school_id = ANY(` + b.arg(ids) + `)` + side + `
GROUP BY ca.school_id`
		if err := addCounts(ctx, db, byID, q, b.args, part.into, part.width); err != nil {
			return err
		}
	}
	return nil
}

// addCounts is _add over grouped rows of (school, before, inside, total[, verified]).
func addCounts(ctx context.Context, db schooldirectory.Querier, byID map[string]*cpoSchool, q string, args []any,
	into func(*cpoSchool) []int, width int) error {
	rows, err := db.Query(ctx, q, args...)
	if err != nil {
		return fmt.Errorf("planningmonitor: the school's counts: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var id string
		v := make([]int, width)
		dest := []any{&id}
		for i := range v {
			dest = append(dest, &v[i])
		}
		if err := rows.Scan(dest...); err != nil {
			return err
		}
		s := byID[id]
		if s == nil {
			continue
		}
		counts := into(s)
		for i := range v {
			counts[i] += v[i]
		}
	}
	return rows.Err()
}
