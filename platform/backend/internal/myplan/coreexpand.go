package myplan

import (
	"context"
	"fmt"
	"strconv"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

type memberSchool struct {
	pk, name, schoolType string
	code                 *string
	clusterID            string
	confirmed            bool
	// district is the school's district's name ("Unknown" without one).
	district string
}

// reach is one row a cluster session becomes: a copy of the session for a
// school it reached (school set), or the session itself when it reached
// none (the fallback row, at the cluster).
type reach struct {
	row    *row
	school *memberSchool
}

// expandClusters is get_frontend_context's cluster invited-school
// expansion, for the Core schools it reaches: each cluster training planned
// on a cluster is listed once a school it reached, and a Core School among
// them moves to Core School Trainings with its package slot's T-number.
// Only those rows are returned; the client and programme rows stay on the
// tables Core School Oversight does not list.
func (p *page) expandClusters(ctx context.Context, db schooldirectory.Querier, acts []*activity, trainings []*row) ([]*row, error) {
	reached, err := p.expandSessions(ctx, db, trainings)
	if err != nil {
		return nil, err
	}
	var out []*row
	for _, r := range trainings {
		for _, x := range reached[r] {
			if x.school != nil && x.school.schoolType == "core" {
				out = append(out, x.row)
			}
		}
	}
	return out, nil
}

// expandSessions is the cluster invited-school expansion itself: for each
// session among trainings (a row at a cluster with no School ID), the rows
// it becomes, in the order the existing loop writes them. A row that is not
// a session has no entry.
func (p *page) expandSessions(ctx context.Context, db schooldirectory.Querier, trainings []*row) (map[*row][]reach, error) {
	var sessions []*row
	var sessionIDs, clusterIDs []string
	for _, r := range trainings {
		if r.clusterID != "" && !r.schoolID.truthy() {
			sessions = append(sessions, r)
			sessionIDs = append(sessionIDs, r.a.id)
			if !in(clusterIDs, r.clusterID) {
				clusterIDs = append(clusterIDs, r.clusterID)
			}
		}
	}
	if len(sessions) == 0 {
		return nil, nil
	}
	recorded := map[string]bool{}
	ids, err := idsWhere(ctx, db, `SELECT activity_id FROM cluster_activity_attendance WHERE activity_id = ANY($1)`, sessionIDs)
	if err != nil {
		return nil, err
	}
	for _, id := range ids {
		recorded[id] = true
	}
	type key struct{ act, school string }
	attending := map[string][]string{}
	composition := map[key]int{}
	var invitedSchools []string
	rows, err := db.Query(ctx, `SELECT a.activity_id, a.school_id, a.invited, a.teachers, a.leaders, a.other
FROM cluster_activity_attendance a LEFT OUTER JOIN school s ON s.id = a.school_id
WHERE a.activity_id = ANY($1) AND (a.invited OR a.attended) ORDER BY s.name ASC`, sessionIDs)
	if err != nil {
		return nil, fmt.Errorf("myplan: invitations: %w", err)
	}
	for rows.Next() {
		var act, school string
		var invited bool
		var t, l, o *int
		if err := rows.Scan(&act, &school, &invited, &t, &l, &o); err != nil {
			rows.Close()
			return nil, err
		}
		if !in(attending[act], school) {
			attending[act] = append(attending[act], school)
		}
		if !in(invitedSchools, school) {
			invitedSchools = append(invitedSchools, school)
		}
		if invited && (t != nil || l != nil || o != nil) {
			n := 0
			for _, v := range []*int{t, l, o} {
				if v != nil {
					n += *v
				}
			}
			composition[key{act, school}] = n
		}
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, err
	}

	lookup := map[string]memberSchool{}
	byCluster, confirmedBy := map[string][]memberSchool{}, map[string][]memberSchool{}
	members, err := readMembers(ctx, db, `s.cluster_id = ANY($1) AND s.deleted_at IS NULL`, clusterIDs)
	if err != nil {
		return nil, err
	}
	for _, s := range members {
		lookup[s.pk] = s
		byCluster[s.clusterID] = append(byCluster[s.clusterID], s)
		if s.confirmed {
			confirmedBy[s.clusterID] = append(confirmedBy[s.clusterID], s)
		}
	}
	var missing []string
	for _, id := range invitedSchools {
		if _, ok := lookup[id]; !ok {
			missing = append(missing, id)
		}
	}
	if len(missing) > 0 {
		more, err := readMembers(ctx, db, `s.id = ANY($1) AND s.deleted_at IS NULL`, missing)
		if err != nil {
			return nil, err
		}
		for _, s := range more {
			lookup[s.pk] = s
		}
	}

	slotOf, progress, err := sessionSlots(ctx, db, sessionIDs)
	if err != nil {
		return nil, err
	}
	var trainingIDs []string
	for _, r := range trainings {
		trainingIDs = append(trainingIDs, r.a.id)
	}
	meals, err := mealRates(ctx, db, trainingIDs)
	if err != nil {
		return nil, err
	}

	out := map[*row][]reach{}
	var fallback *int64
	fallbackRead := false
	for _, r := range sessions {
		act := r.a.id
		var targets []memberSchool
		for _, id := range attending[act] {
			if s, ok := lookup[id]; ok {
				targets = append(targets, s)
			}
		}
		if len(targets) == 0 && !recorded[act] {
			targets = confirmedBy[r.clusterID]
			if len(targets) == 0 {
				targets = byCluster[r.clusterID]
			}
		}
		if len(targets) == 0 {
			// No school to split it over: the session itself, named by its
			// cluster, with its own head count and cost.
			c := r.copy()
			c.schoolName = orDefault(r.clusterName, "Cluster Training")
			c.placeURL = "/clusters/" + r.clusterID
			out[r] = append(out[r], reach{row: c})
			continue
		}
		var each *int
		for _, v := range []*int{r.a.perSchool, r.a.teachersPerSchool} {
			if v != nil && *v != 0 {
				n := *v
				each = &n
				break
			}
		}
		if each == nil && r.expected != nil && len(targets) > 0 {
			n := max(1, pyFloorDiv(*r.expected, len(targets)))
			each = &n
		}
		for i := range targets {
			s := targets[i]
			c := r.copy()
			code := s.pk
			if s.code != nil && *s.code != "" {
				code = *s.code
			}
			c.schoolID = schoolID{value: code}
			c.schoolName = s.name
			c.schoolDistrict = s.district
			c.placeURL = "/schools/" + code
			c.isClusterInvited = true
			c.expected = each
			if n, ok := composition[key{act, s.pk}]; ok {
				c.expected = &n
			}
			switch {
			case isOnline(r.a):
				zero := int64(0)
				c.budgetTotal = &zero
			case c.expected == nil:
				c.budgetTotal = nil
			default:
				rate, ok := meals[act]
				if !ok {
					if !fallbackRead {
						fallback, err = catalogueRate(ctx, db, rules.Rows.GroupTrainingMealsRateKey)
						if err != nil {
							return nil, err
						}
						fallbackRead = true
					}
					if fallback == nil {
						c.budgetTotal = nil
						break
					}
					rate = *fallback
				}
				v := int64(*c.expected) * rate
				c.budgetTotal = &v
			}
			switch {
			case in(rules.Rows.ProgrammeSchoolTypes, s.schoolType):
				c.trainingNumber, c.coreProgress = "", ""
			case s.schoolType == "core":
				c.trainingNumber = ""
				if seq, ok := slotOf[[2]string{act, str(s.code)}]; ok && s.code != nil && seq != nil && *seq != 0 {
					c.trainingNumber = "T" + strconv.Itoa(*seq)
				}
				c.coreProgress = ""
				if s.code != nil {
					c.coreProgress = progress[*s.code]
				}
			}
			out[r] = append(out[r], reach{row: c, school: &s})
		}
	}
	return out, nil
}

func pyFloorDiv(a, b int) int {
	q := a / b
	if (a%b != 0) && ((a < 0) != (b < 0)) {
		q--
	}
	return q
}

// readMembers reads schools in the School model's order (newest first).
func readMembers(ctx context.Context, db schooldirectory.Querier, where string, arg []string) ([]memberSchool, error) {
	rows, err := db.Query(ctx, `SELECT s.id, s.school_id, s.name, COALESCE(s.school_type, ''), COALESCE(s.cluster_id, ''),
  COALESCE(s.cluster_status = 'clustered' AND (COALESCE(s.operational_status, '') = '' OR s.operational_status = ANY($2)), false),
  CASE WHEN s.district_id IS NULL THEN 'Unknown' ELSE COALESCE(d.name, '') END
FROM school s LEFT JOIN district d ON d.id = s.district_id WHERE `+where+` ORDER BY s.created_at DESC`, arg, rules.Rows.OperatingStatuses)
	if err != nil {
		return nil, fmt.Errorf("myplan: schools reached: %w", err)
	}
	defer rows.Close()
	var out []memberSchool
	for rows.Next() {
		var s memberSchool
		if err := rows.Scan(&s.pk, &s.code, &s.name, &s.schoolType, &s.clusterID, &s.confirmed, &s.district); err != nil {
			return nil, err
		}
		out = append(out, s)
	}
	return out, rows.Err()
}

// sessionSlots are the Core package slots these sessions fill, by
// (session, School ID), and each of those packages' "n/m Completed".
func sessionSlots(ctx context.Context, db schooldirectory.Querier, sessions []string) (map[[2]string]*int, map[string]string, error) {
	slotOf, progress := map[[2]string]*int{}, map[string]string{}
	rows, err := db.Query(ctx, `SELECT s.activity_id, p.school_id, s.sequence_number FROM core_activity_slot s
INNER JOIN core_plan p ON p.id = s.core_plan_id WHERE s.activity_id = ANY($1) AND s.activity_type = 'training'`, sessions)
	if err != nil {
		return nil, nil, fmt.Errorf("myplan: session slots: %w", err)
	}
	var schools []string
	for rows.Next() {
		var act, school *string
		var seq *int
		if err := rows.Scan(&act, &school, &seq); err != nil {
			rows.Close()
			return nil, nil, err
		}
		slotOf[[2]string{str(act), str(school)}] = seq
		if school != nil && !in(schools, *school) {
			schools = append(schools, *school)
		}
	}
	rows.Close()
	if len(schools) == 0 {
		return slotOf, progress, rows.Err()
	}
	rows, err = db.Query(ctx, `SELECT p.school_id, p.fy, s.activity_type, s.sequence_number, s.status FROM core_activity_slot s
INNER JOIN core_plan p ON p.id = s.core_plan_id WHERE p.school_id = ANY($1) AND s.activity_type = ANY($2)`, schools, []string{"visit", "training"})
	if err != nil {
		return nil, nil, fmt.Errorf("myplan: packages: %w", err)
	}
	defer rows.Close()
	type plan struct{ school, fy string }
	taken, done := map[plan]map[string]bool{}, map[plan]map[string]bool{}
	first := map[string]plan{}
	var order []string
	for rows.Next() {
		var school, fy, kind, status *string
		var seq *int
		if err := rows.Scan(&school, &fy, &kind, &seq, &status); err != nil {
			return nil, nil, err
		}
		k := plan{str(school), pyNone(fy)}
		slot := str(kind) + "\x00" + pyIntNone(seq)
		if taken[k] == nil {
			taken[k], done[k] = map[string]bool{}, map[string]bool{}
		}
		taken[k][slot] = true
		if slotComplete(status) {
			done[k][slot] = true
		}
		if _, seen := first[str(school)]; !seen {
			first[str(school)] = k
			order = append(order, str(school))
		}
	}
	for _, school := range order {
		k := first[school]
		progress[school] = strconv.Itoa(len(done[k])) + "/" + strconv.Itoa(len(taken[k])) + " Completed"
	}
	return slotOf, progress, rows.Err()
}
