package planningpage

import (
	"context"
	"fmt"
	"strconv"
	"time"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schoolplanning"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schoolprofile"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/visitgate"
)

// school is one listed school and what its row shows
// (get_dashboard_data's schools_data).
type school struct {
	ID, Code, Name, Type              string
	DistrictID, District              string
	HasDistrictRow                    bool
	Shipping, ClusterID, ClusterName  string
	Contact, Phone, OwnerID, OwnerRaw string
	Enrolment                         *int
	ownerName                         string
	visits, trainings                 int
	scores                            []schooldirectory.SSAScore
	gate                              visitgate.Gate
	badges                            *schoolplanning.Badges
	partner                           bool
	next                              *schoolplanning.Next
	group                             string
}

func each(ctx context.Context, q schooldirectory.Querier, what, sql string, scan func(pgx.Rows) error, args ...any) error {
	rows, err := q.Query(ctx, sql, args...)
	if err != nil {
		return fmt.Errorf("planningpage: reading %s: %w", what, err)
	}
	defer rows.Close()
	for rows.Next() {
		if err := scan(rows); err != nil {
			return fmt.Errorf("planningpage: reading %s: %w", what, err)
		}
	}
	if err := rows.Err(); err != nil {
		return fmt.Errorf("planningpage: reading %s: %w", what, err)
	}
	return nil
}

// readSchools reads the page's schools in the order of ids.
func readSchools(ctx context.Context, q schooldirectory.Querier, ids []string) ([]school, map[string]int, error) {
	at := map[string]int{}
	for i, id := range ids {
		at[id] = i
	}
	out := make([]school, len(ids))
	err := each(ctx, q, "the page's schools", `
SELECT s.id, COALESCE(s.school_id, ''), COALESCE(s.name, ''), COALESCE(s.school_type, ''),
  COALESCE(s.district_id, ''), d.id IS NOT NULL, COALESCE(d.name, ''),
  COALESCE(s.shipping_address, ''), COALESCE(s.cluster_id, ''),
  COALESCE(s.primary_contact_name, ''), COALESCE(NULLIF(s.primary_contact_phone, ''), NULLIF(s.school_phone, ''), ''),
  COALESCE(s.account_owner_id, ''), COALESCE(s.account_owner_name_raw, ''), s.enrollment
FROM school s LEFT JOIN district d ON d.id = s.district_id WHERE s.id = ANY($1)`, func(rows pgx.Rows) error {
		var r school
		if err := rows.Scan(&r.ID, &r.Code, &r.Name, &r.Type, &r.DistrictID, &r.HasDistrictRow, &r.District,
			&r.Shipping, &r.ClusterID, &r.Contact, &r.Phone, &r.OwnerID, &r.OwnerRaw, &r.Enrolment); err != nil {
			return err
		}
		out[at[r.ID]] = r
		return nil
	}, ids)
	return out, at, err
}

// enrich reads what each row shows beside the school itself.
func enrich(ctx context.Context, q schooldirectory.Querier, list []school, at map[string]int, fy, operational string,
	horizon []string, support bool, now time.Time) error {
	ids := make([]string, len(list))
	clusterIDs := []string{}
	ownerIDs := []string{}
	for i, s := range list {
		ids[i] = s.ID
		if s.ClusterID != "" {
			clusterIDs = append(clusterIDs, s.ClusterID)
		}
		if s.OwnerID != "" {
			ownerIDs = append(ownerIDs, s.OwnerID)
		}
	}
	if len(ids) == 0 {
		return nil
	}
	// The cluster names (a deleted cluster reads "Cluster missing").
	names := map[string]string{}
	if err := each(ctx, q, "cluster names", `SELECT id, COALESCE(name, '') FROM cluster WHERE id = ANY($1) AND deleted_at IS NULL`,
		func(rows pgx.Rows) error {
			var id, name string
			if err := rows.Scan(&id, &name); err != nil {
				return err
			}
			names[id] = name
			return nil
		}, clusterIDs); err != nil {
		return err
	}
	// The owners' names, in both id spaces, where the profile is live and
	// its user has a name.
	owners := map[string]string{}
	if len(ownerIDs) > 0 {
		if err := each(ctx, q, "owner names", `
SELECT sp.id, sp.user_id, u.name FROM staff_profile sp JOIN "user" u ON u.id = sp.user_id
WHERE sp.deleted_at IS NULL AND (sp.id = ANY($1) OR sp.user_id = ANY($1)) AND COALESCE(u.name, '') <> ''`,
			func(rows pgx.Rows) error {
				var id, userID, name string
				if err := rows.Scan(&id, &userID, &name); err != nil {
					return err
				}
				owners[id], owners[userID] = name, name
				return nil
			}, ownerIDs); err != nil {
			return err
		}
	}
	for i := range list {
		s := &list[i]
		if s.ClusterID != "" {
			if name, ok := names[s.ClusterID]; ok {
				s.ClusterName = name
			} else {
				s.ClusterName = "Cluster missing"
			}
		}
		s.ownerName = owners[s.OwnerID]
		if s.ownerName == "" {
			s.ownerName = s.OwnerRaw
		}
		if s.ownerName == "" {
			s.ownerName = "Unassigned"
		}
	}

	// The year's latest confirmed assessment, newest first.
	latest := map[string]string{}
	records := []string{}
	if err := each(ctx, q, "the year's assessments", `
SELECT id, school_id FROM ssa_record WHERE school_id = ANY($1) AND fy = $2 AND verification_status = 'confirmed'
  AND deleted_at IS NULL ORDER BY school_id ASC, date_of_ssa DESC`, func(rows pgx.Rows) error {
		var id, schoolID string
		if err := rows.Scan(&id, &schoolID); err != nil {
			return err
		}
		if _, seen := latest[schoolID]; !seen {
			latest[schoolID] = id
			records = append(records, id)
		}
		return nil
	}, ids, fy); err != nil {
		return err
	}
	bySchool := map[string]string{}
	for school, record := range latest {
		bySchool[record] = school
	}
	if len(records) > 0 {
		if err := each(ctx, q, "the year's scores", `SELECT ssa_record_id, intervention, score::float8 FROM ssa_score WHERE ssa_record_id = ANY($1)`,
			func(rows pgx.Rows) error {
				var record, intervention string
				var score *float64
				if err := rows.Scan(&record, &intervention, &score); err != nil {
					return err
				}
				s := &list[at[bySchool[record]]]
				s.scores = append(s.scores, schooldirectory.SSAScore{Intervention: intervention, Score: score})
				return nil
			}, records); err != nil {
			return err
		}
	}

	// Completed visits and trainings of any year, and the cluster sessions
	// that recorded the school as attending.
	if err := each(ctx, q, "completed visits and trainings", `
SELECT school_id, COUNT(*) FILTER (WHERE activity_type = ANY($3)), COUNT(*) FILTER (WHERE activity_type = ANY($4))
FROM activity WHERE school_id = ANY($1) AND status = ANY($2) AND deleted_at IS NULL GROUP BY school_id`,
		func(rows pgx.Rows) error {
			var id string
			var visits, trainings int
			if err := rows.Scan(&id, &visits, &trainings); err != nil {
				return err
			}
			list[at[id]].visits, list[at[id]].trainings = visits, trainings
			return nil
		}, ids, rules.CompletedWorkStatuses, rules.RowVisitCountTypes, rules.RowTrainingCountTypes); err != nil {
		return err
	}
	if err := each(ctx, q, "attended sessions", `
SELECT COALESCE(attended_school_ids, '{}') FROM activity WHERE activity_type = ANY($2) AND status = ANY($3)
  AND deleted_at IS NULL AND attended_school_ids && $1::varchar[]`, func(rows pgx.Rows) error {
		var attended []string
		if err := rows.Scan(&attended); err != nil {
			return err
		}
		for _, id := range attended {
			if i, ok := at[id]; ok {
				list[i].trainings++
			}
		}
		return nil
	}, ids, rules.RowAttendanceTypes, rules.CompletedWorkStatuses); err != nil {
		return err
	}

	badges, counted, err := schoolplanning.ForSchools(ctx, q, ids, horizon)
	if err != nil {
		return err
	}
	for i := range list {
		list[i].badges = badges[list[i].ID]
	}
	if support {
		partner, err := schoolplanning.PartnerSupported(ctx, q, ids, fy)
		if err != nil {
			return err
		}
		next, err := schoolplanning.NextActivities(ctx, q, counted, now)
		if err != nil {
			return err
		}
		for i := range list {
			list[i].partner = partner[list[i].ID]
			if n, ok := next[list[i].ID]; ok {
				list[i].next = &n
			}
		}
	}
	gates := schoolprofile.GateRules()
	for i := range list {
		s := &list[i]
		g, err := visitgate.Of(ctx, q, gates, visitgate.School{ID: s.ID, Code: s.Code, Name: s.Name, Type: s.Type}, fy, operational)
		if err != nil {
			return err
		}
		s.gate = g
	}
	return nil
}

func itoa(n int) string { return strconv.Itoa(n) }
