package schoolprofile

import (
	"context"
	"fmt"
	"slices"

	"github.com/jackc/pgx/v5"
)

// The profile of many schools (apps.analytics.profile_intelligence.build
// over a district, a sub-region, the country, a cluster, a person or a
// Partner): the reads behind its sections, each over the scope's operating
// schools at once.

// scopeSchool is one of the scope's schools (engine._schools).
type scopeSchool struct {
	id, code, name, kind, cluster, owner, district, subRegion, subCounty string
	districtName                                                         string
	enrolment                                                            int
	// hasEnrolment is whether the school's record has a figure at all.
	hasEnrolment bool
}

// scopeOf is a profile's scope: whose profile it is and the schools it
// speaks for, read by a condition on the school table ("s").
type scopeOf struct {
	kind, key, name, covers string
	where                   string
	args                    []any
}

// readScopeSchools is engine._schools: the scope's operating schools by
// name.
func (s *Service) readScopeSchools(ctx context.Context, sc scopeOf) ([]scopeSchool, error) {
	args := append([]any{rules.Engine.Scope.OperatingStatuses}, sc.args...)
	rows, err := s.db.Query(ctx, `
SELECT s.id, COALESCE(s.school_id, ''), s.name, COALESCE(s.school_type, ''), COALESCE(s.cluster_id, ''),
  COALESCE(s.account_owner_id, ''), COALESCE(s.district_id, ''),
  COALESCE(d.sub_region_id, s.sub_region_id, ''), COALESCE(s.sub_county_id, ''), COALESCE(s.enrollment, 0),
  s.enrollment IS NOT NULL, COALESCE(d.name, '')
FROM school s LEFT JOIN district d ON d.id = s.district_id
WHERE s.deleted_at IS NULL AND s.operational_status = ANY($1) AND `+sc.where+`
ORDER BY s.name, s.id`, args...)
	if err != nil {
		return nil, fmt.Errorf("schoolprofile: reading the profile's schools: %w", err)
	}
	return pgx.CollectRows(rows, func(row pgx.CollectableRow) (scopeSchool, error) {
		var x scopeSchool
		err := row.Scan(&x.id, &x.code, &x.name, &x.kind, &x.cluster, &x.owner, &x.district, &x.subRegion, &x.subCounty, &x.enrolment,
			&x.hasEnrolment, &x.districtName)
		return x, err
	})
}

func idsOf(schools []scopeSchool) []string {
	out := make([]string, len(schools))
	for i, x := range schools {
		out[i] = x.id
	}
	return out
}

// scopeComparison is year_comparison.intervention_comparison over many
// schools: each intervention's mean of the schools' latest confirmed
// records this year and the year before, and the overall mean.
func (s *Service) scopeComparison(ctx context.Context, ids []string, fy string) (comparison, error) {
	before := previousFY(fy)
	rows, err := s.db.Query(ctx, `
SELECT DISTINCT ON (r.school_id, r.fy) r.id, r.fy, r.average_score
FROM ssa_record r
WHERE r.school_id = ANY($1) AND r.fy = ANY($2) AND r.deleted_at IS NULL AND r.verification_status = ANY($3)
ORDER BY r.school_id, r.fy, r.date_of_ssa DESC, r.created_at DESC, r.id DESC`, ids, []string{fy, before}, rules.SSACurrentStatuses)
	if err != nil {
		return comparison{}, fmt.Errorf("schoolprofile: reading SSA records: %w", err)
	}
	type record struct {
		year    string
		average *float64
	}
	records := map[string]record{}
	order := []string{}
	for rows.Next() {
		var id string
		var r record
		if err := rows.Scan(&id, &r.year, &r.average); err != nil {
			rows.Close()
			return comparison{}, err
		}
		records[id] = r
		order = append(order, id)
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return comparison{}, err
	}
	byYear := map[string]map[string][]*float64{fy: {}, before: {}}
	perRecord := map[string][]*float64{}
	if len(order) > 0 {
		rows, err := s.db.Query(ctx, `SELECT ssa_record_id, intervention, score FROM ssa_score WHERE ssa_record_id = ANY($1) ORDER BY ssa_record_id, id`, order)
		if err != nil {
			return comparison{}, fmt.Errorf("schoolprofile: reading SSA scores: %w", err)
		}
		for rows.Next() {
			var id, intervention string
			var score *float64
			if err := rows.Scan(&id, &intervention, &score); err != nil {
				rows.Close()
				return comparison{}, err
			}
			if score == nil {
				continue
			}
			v := *score
			byYear[records[id].year][intervention] = append(byYear[records[id].year][intervention], &v)
			perRecord[id] = append(perRecord[id], &v)
		}
		rows.Close()
		if err := rows.Err(); err != nil {
			return comparison{}, err
		}
	}
	overall := func(year string) *float64 {
		values := []*float64{}
		for _, id := range order {
			r := records[id]
			if r.year != year {
				continue
			}
			if r.average != nil {
				values = append(values, r.average)
			} else {
				values = append(values, pyMean(perRecord[id]))
			}
		}
		return pyMean(values)
	}
	out := comparison{current: overall(fy), previous: overall(before)}
	for _, id := range order {
		if records[id].year == fy {
			out.schools++
		} else {
			out.previousSchools++
		}
	}
	for _, key := range rules.Engine.InterventionOrder {
		out.rows = append(out.rows, ivRow{
			key: key, label: rules.SSAInterventions[key],
			current: pyMean(byYear[fy][key]), previous: pyMean(byYear[before][key]),
		})
	}
	return out, nil
}

// placeWork is a school's year of visits and trainings (engine._NO_WORK),
// or a cluster's sessions.
type placeWork struct {
	visits, visitsDone, trainings, trainingsDone, teachers, leaders int
	meetings, meetingsDone                                          int
}

// scopeWork is engine._activities as a condition on "a", its arguments
// appended to args: the year's work in somebody's plan at the scope's
// schools, or a session of one of its clusters, in the window.
func scopeWork(ids, clusters []string, fy string, w window, args *[]any) string {
	*args = append(*args, ids, clusters, fy, rules.Engine.NotInPlanStatuses)
	n := len(*args)
	return fmt.Sprintf(`(a.school_id = ANY($%d) OR (a.school_id IS NULL AND a.cluster_id = ANY($%d))) AND a.fy = $%d
  AND a.deleted_at IS NULL AND NOT (a.status = ANY($%d)) AND %s`, n-3, n-2, n-1, n, w.sql(args))
}

// workByPlace is engine._work_by_place: each school's visits and trainings
// (with the teachers and leaders its completed trainings and the register
// of completed group trainings record), and each cluster's own sessions.
func (s *Service) workByPlace(ctx context.Context, ids, clusters []string, fy string, w window) (map[string]*placeWork, map[string]*placeWork, error) {
	args := []any{rules.Engine.VisitTypes, rules.Engine.TrainingTypes, rules.Engine.MeetingTypes, rules.Engine.CompletedWorkStatuses}
	where := scopeWork(ids, clusters, fy, w, &args)
	rows, err := s.db.Query(ctx, `
SELECT COALESCE(a.school_id, ''), COALESCE(a.cluster_id, ''),
  count(*) FILTER (WHERE a.activity_type = ANY($1)),
  count(*) FILTER (WHERE a.activity_type = ANY($1) AND a.status = ANY($4)),
  count(*) FILTER (WHERE a.activity_type = ANY($2)),
  count(*) FILTER (WHERE a.activity_type = ANY($2) AND a.status = ANY($4)),
  COALESCE(sum(a.teachers_attended) FILTER (WHERE a.activity_type = ANY($2) AND a.status = ANY($4)), 0),
  COALESCE(sum(a.leaders_attended) FILTER (WHERE a.activity_type = ANY($2) AND a.status = ANY($4)), 0),
  count(*) FILTER (WHERE a.activity_type = ANY($3)),
  count(*) FILTER (WHERE a.activity_type = ANY($3) AND a.status = ANY($4))
FROM activity a WHERE `+where+`
GROUP BY 1, 2`, args...)
	if err != nil {
		return nil, nil, fmt.Errorf("schoolprofile: reading the profile's work: %w", err)
	}
	schools, clusterWork := map[string]*placeWork{}, map[string]*placeWork{}
	for rows.Next() {
		var school, cluster string
		var x placeWork
		if err := rows.Scan(&school, &cluster, &x.visits, &x.visitsDone, &x.trainings, &x.trainingsDone,
			&x.teachers, &x.leaders, &x.meetings, &x.meetingsDone); err != nil {
			rows.Close()
			return nil, nil, err
		}
		switch {
		case school != "":
			at := schools[school]
			if at == nil {
				at = &placeWork{}
				schools[school] = at
			}
			at.visits += x.visits
			at.visitsDone += x.visitsDone
			at.trainings += x.trainings
			at.trainingsDone += x.trainingsDone
			at.teachers += x.teachers
			at.leaders += x.leaders
		case cluster != "":
			at := clusterWork[cluster]
			if at == nil {
				at = &placeWork{}
				clusterWork[cluster] = at
			}
			at.meetings += x.meetings
			at.meetingsDone += x.meetingsDone
			at.trainings += x.trainings
			at.trainingsDone += x.trainingsDone
		}
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, nil, err
	}
	// The register of completed group trainings, for the scope's schools.
	register, err := s.registerOf(ctx, ids, fy, w, rules.Engine.TrainingTypes)
	if err != nil {
		return nil, nil, err
	}
	for school, r := range register {
		at := schools[school]
		if at == nil {
			at = &placeWork{}
			schools[school] = at
		}
		at.teachers += r[0]
		at.leaders += r[1]
	}
	return schools, clusterWork, nil
}

// sessionsIn is engine._sessions as a condition on "a", its arguments
// appended to args: the year's completed work not at one school, in the
// window.
func sessionsIn(fy string, w window, args *[]any) string {
	*args = append(*args, rules.Engine.CompletedWorkStatuses, fy)
	n := len(*args)
	return fmt.Sprintf(`a.status = ANY($%d) AND a.school_id IS NULL AND a.fy = $%d AND a.deleted_at IS NULL AND %s`, n-1, n, w.sql(args))
}

// registerOf is engine._register: the teachers and leaders recorded for
// each of the scope's schools attending a completed session of types.
func (s *Service) registerOf(ctx context.Context, ids []string, fy string, w window, types []string) (map[string][2]int, error) {
	args := []any{ids, types}
	where := sessionsIn(fy, w, &args)
	rows, err := s.db.Query(ctx, `
SELECT r.school_id, COALESCE(sum(r.teachers), 0), COALESCE(sum(r.leaders), 0)
FROM cluster_activity_attendance r
WHERE r.school_id = ANY($1) AND r.attended
  AND r.activity_id IN (SELECT a.id FROM activity a WHERE a.activity_type = ANY($2) AND `+where+`)
GROUP BY r.school_id`, args...)
	if err != nil {
		return nil, fmt.Errorf("schoolprofile: reading the session register: %w", err)
	}
	out := map[string][2]int{}
	for rows.Next() {
		var school string
		var t, l int
		if err := rows.Scan(&school, &t, &l); err != nil {
			rows.Close()
			return nil, err
		}
		out[school] = [2]int{t, l}
	}
	rows.Close()
	return out, rows.Err()
}

// liveClusters is the scope's clusters that are not deleted, by id.
func (s *Service) liveClusters(ctx context.Context, ids []string) (map[string]string, error) {
	rows, err := s.db.Query(ctx, `SELECT id, name FROM cluster WHERE id = ANY($1) AND deleted_at IS NULL`, ids)
	if err != nil {
		return nil, fmt.Errorf("schoolprofile: reading the profile's clusters: %w", err)
	}
	out := map[string]string{}
	for rows.Next() {
		var id, name string
		if err := rows.Scan(&id, &name); err != nil {
			rows.Close()
			return nil, err
		}
		out[id] = name
	}
	rows.Close()
	return out, rows.Err()
}

func clusterIDsOf(schools []scopeSchool) []string {
	out := []string{}
	for _, x := range schools {
		if x.cluster != "" && !slices.Contains(out, x.cluster) {
			out = append(out, x.cluster)
		}
	}
	slices.Sort(out)
	return out
}
