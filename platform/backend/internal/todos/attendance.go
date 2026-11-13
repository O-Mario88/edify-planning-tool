package todos

import (
	"context"
	"sort"
	"time"

	"github.com/jackc/pgx/v5"
)

func sortStable[T any](list []T, less func(a, b T) bool) {
	sort.SliceStable(list, func(i, j int) bool { return less(list[i], list[j]) })
}

// attendanceTodos is clusters.followups.attendance_todos: one row for each
// of the reader's clusters with schools that missed MissedInARowAlert or
// more sessions in a row, the most such schools first, at most
// AttendanceMaxRows.
func attendanceTodos(ctx context.Context, s *Service, r *reader) ([]todo, error) {
	// Only a Programme Lead's rows differ (their category).
	if r.role != "CCEO" && r.role != roleIA {
		return nil, errPassOn
	}
	if len(r.owners) == 0 {
		return nil, nil
	}
	rows, err := s.db.Query(ctx, `SELECT id, COALESCE(name, '') FROM cluster
WHERE deleted_at IS NULL AND responsible_staff_id = ANY($1)`, r.owners)
	if err != nil {
		return nil, err
	}
	type cluster struct{ id, name string }
	clusters, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (cluster, error) {
		var c cluster
		return c, row.Scan(&c.id, &c.name)
	})
	if err != nil || len(clusters) == 0 {
		return nil, err
	}
	ids := make([]string, len(clusters))
	for i, c := range clusters {
		ids[i] = c.id
	}
	drifting, err := s.drifting(ctx, ids)
	if err != nil {
		return nil, err
	}
	type found struct {
		c     cluster
		count int
	}
	var list []found
	for _, c := range clusters {
		if n := drifting[c.id]; n > 0 {
			list = append(list, found{c, n})
		}
	}
	sortStable(list, func(a, b found) bool {
		if a.count != b.count {
			return a.count > b.count
		}
		return a.c.name < b.c.name
	})
	var out []todo
	for _, f := range list[:min(rules.AttendanceMaxRows, len(list))] {
		url := "/clusters/" + f.c.id + "/profile?tab=attendance&show=missing"
		out = append(out, todo{Title: "Follow Up Schools Missing Cluster Sessions", Category: "Planning", Priority: "high",
			StatusKey: "waiting_me", Actionable: true, Linked: f.c.name, ActionLabel: "Open Schools", ActionURL: url,
			Shape: idShape(url, f.c.id), Due: &r.today})
	}
	return out, nil
}

// drifting is how many of each cluster's operating schools missed
// MissedInARowAlert or more of its delivered sessions in a row
// (profile_insights.attendance_by_cluster's "drifting"): counting back from
// the latest session a school was asked to, across years; a session nobody
// was ticked at is not counted against anyone.
func (s *Service) drifting(ctx context.Context, clusterIDs []string) (map[string]int, error) {
	rows, err := s.db.Query(ctx, `SELECT id, cluster_id FROM school
WHERE deleted_at IS NULL AND operational_status = ANY($1) AND cluster_id = ANY($2) ORDER BY name ASC`,
		rules.OperatingStatuses, clusterIDs)
	if err != nil {
		return nil, err
	}
	members := map[string][]string{}
	for rows.Next() {
		var id, clusterID string
		if err := rows.Scan(&id, &clusterID); err != nil {
			rows.Close()
			return nil, err
		}
		members[clusterID] = append(members[clusterID], id)
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, err
	}
	rows, err = s.db.Query(ctx, `SELECT id, cluster_id, COALESCE(attended_school_ids, '{}'), actual_delivery_date, planned_date
FROM activity WHERE cluster_id = ANY($1) AND school_id IS NULL AND deleted_at IS NULL AND activity_type = ANY($2)
  AND status = ANY($3) ORDER BY created_at DESC`, clusterIDs, rules.ClusterSessionTypes, rules.ClusterDeliveredStatuses)
	if err != nil {
		return nil, err
	}
	type session struct {
		id, cluster string
		named       []string
		heldOn      *time.Time
	}
	sessions, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (session, error) {
		var x session
		var actual, planned *time.Time
		err := row.Scan(&x.id, &x.cluster, &x.named, &actual, &planned)
		x.heldOn = actual
		if x.heldOn == nil {
			x.heldOn = planned
		}
		return x, err
	})
	if err != nil || len(sessions) == 0 {
		return map[string]int{}, err
	}
	activityIDs := make([]string, len(sessions))
	for i, x := range sessions {
		activityIDs[i] = x.id
	}
	rows, err = s.db.Query(ctx, `SELECT activity_id, school_id, invited, attended FROM cluster_activity_attendance
WHERE activity_id = ANY($1)`, activityIDs)
	if err != nil {
		return nil, err
	}
	type mark struct{ invited, attended bool }
	register := map[string]map[string]mark{}
	for rows.Next() {
		var activityID, schoolID string
		var m mark
		if err := rows.Scan(&activityID, &schoolID, &m.invited, &m.attended); err != nil {
			rows.Close()
			return nil, err
		}
		if register[activityID] == nil {
			register[activityID] = map[string]mark{}
		}
		register[activityID][schoolID] = m
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, err
	}
	type entry struct {
		heldOn   *time.Time
		attended bool
	}
	out := map[string]int{}
	for _, clusterID := range clusterIDs {
		timeline := map[string][]entry{}
		for _, x := range sessions {
			if x.cluster != clusterID {
				continue
			}
			came, asked := map[string]bool{}, map[string]bool{}
			for sid, m := range register[x.id] {
				if m.attended {
					came[sid] = true
				}
			}
			for _, sid := range x.named {
				came[sid] = true
			}
			if len(came) == 0 {
				continue
			}
			for sid, m := range register[x.id] {
				if m.invited {
					asked[sid] = true
				}
			}
			for sid := range came {
				asked[sid] = true
			}
			for _, sid := range members[clusterID] {
				if asked[sid] {
					timeline[sid] = append(timeline[sid], entry{x.heldOn, came[sid]})
				}
			}
		}
		for _, sid := range members[clusterID] {
			line := timeline[sid]
			// sorted(key=held_on or date.min, reverse=True): newest first,
			// equal days in the order the sessions came.
			sortStable(line, func(a, b entry) bool {
				switch {
				case a.heldOn == nil:
					return false
				case b.heldOn == nil:
					return true
				}
				return a.heldOn.After(*b.heldOn)
			})
			missed := 0
			for _, e := range line {
				if e.attended {
					break
				}
				missed++
			}
			if missed >= rules.MissedInARowAlert {
				out[clusterID]++
			}
		}
	}
	return out, nil
}
