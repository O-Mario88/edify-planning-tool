package myplan

import (
	"context"
	"fmt"

	registry "github.com/O-Mario88/edify-planning-tool/platform/backend/internal/country"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// rosters is table_export._rosters: who each meeting invited, by name; the
// people an invitation names; and, for a meeting with no invitation
// recorded, its cluster's schools (the confirmed members, else the rest).
func rosters(ctx context.Context, db schooldirectory.Querier, meetings []*planRow) (map[string][]string, map[[2]string]int, error) {
	ids := make([]string, 0, len(meetings))
	clusters := []string{}
	for _, m := range meetings {
		ids = append(ids, m.a.id)
		if m.clusterID != "" {
			clusters = append(clusters, m.clusterID)
		}
	}
	recorded := map[string]bool{}
	rows, err := db.Query(ctx, `SELECT DISTINCT activity_id FROM cluster_activity_attendance WHERE activity_id = ANY($1)`, ids)
	if err != nil {
		return nil, nil, fmt.Errorf("myplan: reading the meetings' rosters: %w", err)
	}
	for rows.Next() {
		var id string
		if err := rows.Scan(&id); err != nil {
			rows.Close()
			return nil, nil, err
		}
		recorded[id] = true
	}
	rows.Close()
	onRoster := map[string][]string{}
	people := map[[2]string]int{}
	rows, err = db.Query(ctx, `SELECT ca.activity_id, ca.school_id, ca.teachers, ca.leaders, ca.other
FROM cluster_activity_attendance ca LEFT JOIN school s ON s.id = ca.school_id
WHERE ca.activity_id = ANY($1) AND ca.invited ORDER BY s.name`, ids)
	if err != nil {
		return nil, nil, fmt.Errorf("myplan: reading the meetings' invitations: %w", err)
	}
	for rows.Next() {
		var act, school string
		var v invite
		if err := rows.Scan(&act, &school, &v.teachers, &v.leaders, &v.other); err != nil {
			rows.Close()
			return nil, nil, err
		}
		if !in(onRoster[act], school) {
			onRoster[act] = append(onRoster[act], school)
		}
		if v.given() {
			people[[2]string{act, school}] = v.sum()
		}
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, nil, err
	}
	confirmed, others := map[string][]string{}, map[string][]string{}
	if len(clusters) > 0 {
		rows, err = db.Query(ctx, `SELECT id, cluster_id, COALESCE(cluster_status, ''), COALESCE(operational_status, '')
FROM school WHERE cluster_id = ANY($1) AND deleted_at IS NULL ORDER BY name`, clusters)
		if err != nil {
			return nil, nil, fmt.Errorf("myplan: reading the clusters' schools: %w", err)
		}
		for rows.Next() {
			var id, cluster, status, operating string
			if err := rows.Scan(&id, &cluster, &status, &operating); err != nil {
				rows.Close()
				return nil, nil, err
			}
			if status == "clustered" && (operating == "" || in(rules.TableExport.OperatingStatuses, operating)) {
				confirmed[cluster] = append(confirmed[cluster], id)
			} else {
				others[cluster] = append(others[cluster], id)
			}
		}
		rows.Close()
		if err := rows.Err(); err != nil {
			return nil, nil, err
		}
	}
	out := map[string][]string{}
	for _, m := range meetings {
		id := m.a.id
		switch {
		case len(onRoster[id]) > 0:
			out[id] = onRoster[id]
		case recorded[id] || m.clusterID == "":
			out[id] = nil
		case len(confirmed[m.clusterID]) > 0:
			out[id] = confirmed[m.clusterID]
		default:
			out[id] = others[m.clusterID]
		}
	}
	return out, people, nil
}

// meetingSchoolRows is table_export.meeting_school_rows: each cluster
// meeting once a school on its roster, in the Trainings table's shape; a
// school's people are its invitation's, else the meeting's per school, its
// Cost those people at the meeting's meal rate.
func meetingSchoolRows(ctx context.Context, db schooldirectory.Querier, place *registry.Work, meetings []*planRow) ([]*planRow, error) {
	if len(meetings) == 0 {
		return nil, nil
	}
	roster, people, err := rosters(ctx, db, meetings)
	if err != nil {
		return nil, err
	}
	ids := make([]string, 0, len(meetings))
	var pks []string
	for _, m := range meetings {
		ids = append(ids, m.a.id)
		pks = append(pks, roster[m.a.id]...)
	}
	type school struct{ code, name string }
	schools := map[string]school{}
	if len(pks) > 0 {
		rows, err := db.Query(ctx, `SELECT id, COALESCE(school_id, ''), COALESCE(name, '') FROM school WHERE id = ANY($1)`, pks)
		if err != nil {
			return nil, fmt.Errorf("myplan: reading the invited schools: %w", err)
		}
		for rows.Next() {
			var id string
			var s school
			if err := rows.Scan(&id, &s.code, &s.name); err != nil {
				rows.Close()
				return nil, err
			}
			schools[id] = s
		}
		rows.Close()
		if err := rows.Err(); err != nil {
			return nil, err
		}
	}
	sessions, err := readSessions(ctx, db, ids)
	if err != nil {
		return nil, err
	}
	// planned_meal_rates: the session's own meals line, else the live
	// catalogue's rate for the cluster meals key.
	rates, err := mealRates(ctx, db, ids)
	if err != nil {
		return nil, err
	}
	fallback, err := catalogueRate(ctx, db, place, rules.TableExport.ClusterMealsRateKey)
	if err != nil {
		return nil, err
	}
	var out []*planRow
	for _, m := range meetings {
		act := m.a.id
		list := roster[act]
		each := 0
		if s, ok := sessions[act]; ok {
			each = s.perSchool
		}
		if each == 0 && m.expected != nil && *m.expected != 0 && len(list) > 0 {
			each = max(1, *m.expected/len(list))
		}
		var rate *int64
		if r, ok := rates[act]; ok {
			rate = &r
		} else if _, known := sessions[act]; known {
			rate = fallback
		}
		topic := meetingTopic(m)
		for _, pk := range list {
			sc, ok := schools[pk]
			if !ok {
				continue
			}
			ref := sc.code
			if ref == "" {
				ref = pk
			}
			var heads *int
			if n, given := people[[2]string{act, pk}]; given {
				heads = &n
			} else if each != 0 {
				n := each
				heads = &n
			}
			var total *int64
			if heads != nil && rate != nil {
				t := int64(*heads) * *rate
				total = &t
			}
			c := *m
			c.row = m.row.copy()
			c.schoolID = schoolID{value: ref}
			c.schoolName, c.placeURL, c.isClusterInvited = sc.name, "/schools/"+ref, true
			c.expected, c.budgetTotal, c.costNote = heads, total, ""
			c.trainingMode, c.trainingName = "Cluster Meeting", topic
			out = append(out, &c)
		}
	}
	return out, nil
}
