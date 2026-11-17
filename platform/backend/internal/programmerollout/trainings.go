package programmerollout

import (
	"context"
	"fmt"
	"slices"
	"sort"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// training is one TRAINING_FIELDS row.
type training struct {
	id, kind, status, focus, delivery, partner, responsible, monitor string
	schoolID, clusterID, catalogue, course, snapshot                 string
	schoolName, clusterName                                          string
	courseItem                                                       bool
	planned                                                          *time.Time
	teachers, leaders                                                int
	attended                                                         []string
}

// courseID is _course_id: the in-school course, else the catalogue item when
// it is itself a course.
func (t training) courseID() string {
	if t.course != "" {
		return t.course
	}
	if t.courseItem {
		return t.catalogue
	}
	return ""
}

const trainingColumns = `a.id, COALESCE(a.activity_type, ''), COALESCE(a.status, ''), COALESCE(a.focus_intervention, ''),
  COALESCE(a.delivery_type, ''), COALESCE(a.assigned_partner_id, ''), COALESCE(a.responsible_staff_id, ''),
  COALESCE(a.monitored_by_staff_id, ''), COALESCE(a.school_id, ''), COALESCE(a.cluster_id, ''), COALESCE(a.catalogue_item_id, ''),
  COALESCE(a.training_course_id, ''), COALESCE(a.activity_name_snapshot, ''), COALESCE(s.name, ''), COALESCE(cl.name, ''),
  COALESCE(ci.is_training_course, FALSE), a.planned_date, COALESCE(a.teachers_attended, 0), COALESCE(a.leaders_attended, 0),
  COALESCE(a.attended_school_ids, '{}')
FROM activity a LEFT JOIN school s ON s.id = a.school_id LEFT JOIN cluster cl ON cl.id = a.cluster_id
LEFT JOIN activity_catalogue_item ci ON ci.id = a.catalogue_item_id`

func readTrainings(ctx context.Context, db schooldirectory.Querier, sql string, args []any) ([]training, error) {
	rows, err := db.Query(ctx, sql, args...)
	if err != nil {
		return nil, fmt.Errorf("programmerollout: reading the trainings: %w", err)
	}
	defer rows.Close()
	out := []training{}
	for rows.Next() {
		var t training
		if err := rows.Scan(&t.id, &t.kind, &t.status, &t.focus, &t.delivery, &t.partner, &t.responsible, &t.monitor,
			&t.schoolID, &t.clusterID, &t.catalogue, &t.course, &t.snapshot, &t.schoolName, &t.clusterName, &t.courseItem,
			&t.planned, &t.teachers, &t.leaders, &t.attended); err != nil {
			return nil, fmt.Errorf("programmerollout: reading a training: %w", err)
		}
		out = append(out, t)
	}
	return out, rows.Err()
}

// trainingRows is _training_rows: the team's planned trainings of the year.
func (s *scope) trainingRows(ctx context.Context, db schooldirectory.Querier, fy string) ([]training, error) {
	if len(s.ownerByID) == 0 {
		return []training{}, nil
	}
	where, args := s.activityFilter([]any{fy, rules.TrainingTypes, rules.NotPlannedStatuses})
	return readTrainings(ctx, db, "SELECT "+trainingColumns+` WHERE `+where+` AND a.fy = $1 AND a.deleted_at IS NULL
  AND a.activity_type = ANY($2) AND NOT COALESCE(a.status = ANY($3), FALSE) ORDER BY a.planned_date ASC NULLS LAST, a.id`, args)
}

// upcoming is _upcoming: live trainings dated in the next days.
func (s *scope) upcoming(ctx context.Context, db schooldirectory.Querier, today time.Time) ([]training, error) {
	if len(s.ownerByID) == 0 {
		return []training{}, nil
	}
	where, args := s.activityFilter([]any{rules.TrainingTypes, rules.LiveStatuses, today, today.AddDate(0, 0, rules.UpcomingDays), rules.UpcomingRows})
	return readTrainings(ctx, db, "SELECT "+trainingColumns+` WHERE `+where+` AND a.deleted_at IS NULL AND a.activity_type = ANY($1)
  AND a.status = ANY($2) AND a.planned_date >= $3 AND a.planned_date <= $4 ORDER BY a.planned_date ASC NULLS LAST, a.id LIMIT $5`, args)
}

// reach is _reach: the schools each delivered training reached.
func reach(ctx context.Context, db schooldirectory.Querier, rows []training) (map[string]map[string]bool, error) {
	out := map[string]map[string]bool{}
	add := func(id, school string) {
		if out[id] == nil {
			out[id] = map[string]bool{}
		}
		out[id][school] = true
	}
	sessions := []string{}
	for _, r := range rows {
		switch {
		case slices.Contains(rules.SchoolTrainingTypes, r.kind):
			if slices.Contains(rules.CompletedStatuses, r.status) && r.schoolID != "" {
				add(r.id, r.schoolID)
			}
		case slices.Contains(rules.ClusterTrainingTypes, r.kind) && slices.Contains(rules.ClusterCreditStatuses, r.status):
			sessions = append(sessions, r.id)
			for _, s := range r.attended {
				add(r.id, s)
			}
		}
	}
	if len(sessions) == 0 {
		return out, nil
	}
	att, err := db.Query(ctx, `SELECT activity_id, school_id FROM cluster_activity_attendance WHERE activity_id = ANY($1) AND attended`, sessions)
	if err != nil {
		return nil, fmt.Errorf("programmerollout: reading the attendance: %w", err)
	}
	defer att.Close()
	for att.Next() {
		var id, school string
		if err := att.Scan(&id, &school); err != nil {
			return nil, fmt.Errorf("programmerollout: reading an attendance: %w", err)
		}
		add(id, school)
	}
	return out, att.Err()
}

// fold is _fold: a group of trainings' figures.
type fold struct {
	planned, delivered, inReview, schoolsReached, teachers, leaders, byStaff, byPartner int
	deliveredShare                                                                      *int
}

func percentage(n, d int) *int {
	if d == 0 {
		return nil
	}
	v := int(float64(n)/float64(d)*100 + 0.5)
	return &v
}

func folded(rows []training, reached map[string]map[string]bool) fold {
	var f fold
	schools := map[string]bool{}
	f.planned = len(rows)
	for _, r := range rows {
		if slices.Contains(rules.InReviewStatuses, r.status) {
			f.inReview++
		}
		if !slices.Contains(rules.CompletedStatuses, r.status) {
			continue
		}
		f.delivered++
		for s := range reached[r.id] {
			schools[s] = true
		}
		f.teachers += r.teachers
		f.leaders += r.leaders
		if r.delivery == "partner" {
			f.byPartner++
		} else {
			f.byStaff++
		}
	}
	f.schoolsReached = len(schools)
	f.deliveredShare = percentage(f.delivered, f.planned)
	return f
}

// course is one catalogue item a training names, with its intervention.
type course struct {
	id, name, category, intervention string
	isCourse                         bool
}

// courses is _courses: every active governed course and any other item the
// trainings name, each with its primary SSA intervention.
func courses(ctx context.Context, db schooldirectory.Querier, referenced []string) ([]course, map[string]course, error) {
	rows, err := db.Query(ctx, `SELECT id, COALESCE(display_name, ''), COALESCE(training_category, ''), COALESCE(is_training_course, FALSE)
FROM activity_catalogue_item WHERE (is_training_course AND status = 'active') OR id = ANY($1) ORDER BY id`, referenced)
	if err != nil {
		return nil, nil, fmt.Errorf("programmerollout: reading the catalogue: %w", err)
	}
	list := []course{}
	byID := map[string]course{}
	ids := []string{}
	for rows.Next() {
		var c course
		if err := rows.Scan(&c.id, &c.name, &c.category, &c.isCourse); err != nil {
			rows.Close()
			return nil, nil, fmt.Errorf("programmerollout: reading a catalogue item: %w", err)
		}
		list = append(list, c)
		ids = append(ids, c.id)
	}
	rows.Close()
	maps, err := db.Query(ctx, `SELECT catalogue_item_id, intervention FROM activity_intervention_mapping
WHERE catalogue_item_id = ANY($1) AND active AND intervention IS NOT NULL ORDER BY is_primary DESC, priority, id`, ids)
	if err != nil {
		return nil, nil, fmt.Errorf("programmerollout: reading the interventions: %w", err)
	}
	found := map[string]string{}
	for maps.Next() {
		var item, intervention string
		if err := maps.Scan(&item, &intervention); err != nil {
			maps.Close()
			return nil, nil, fmt.Errorf("programmerollout: reading an intervention: %w", err)
		}
		if _, ok := found[item]; !ok {
			found[item] = intervention
		}
	}
	maps.Close()
	for i := range list {
		list[i].intervention = found[list[i].id]
		byID[list[i].id] = list[i]
	}
	return list, byID, nil
}

// trainedSchools is trained_school_ids over the portfolio for the year:
// a completed training at the school, a confirmed attendance at a credited
// cluster training, or the legacy attendance list.
func (s *scope) trainedSchools(ctx context.Context, db schooldirectory.Querier, fy string) (map[string]bool, error) {
	out := map[string]bool{}
	if len(s.schools) == 0 {
		return out, nil
	}
	ids := []string{}
	for id := range s.schools {
		ids = append(ids, id)
	}
	rows, err := db.Query(ctx, `
SELECT a.school_id FROM activity a WHERE a.school_id = ANY($1) AND a.activity_type = ANY($2) AND a.status = ANY($3)
  AND a.deleted_at IS NULL AND a.fy = $6
UNION SELECT c.school_id FROM cluster_activity_attendance c JOIN activity a ON a.id = c.activity_id
  WHERE c.school_id = ANY($1) AND c.attended AND a.activity_type = ANY($4) AND a.status = ANY($5) AND a.deleted_at IS NULL AND a.fy = $6
UNION SELECT x FROM activity a, unnest(a.attended_school_ids) x
  WHERE a.activity_type = ANY($4) AND a.status = ANY($5) AND a.deleted_at IS NULL AND a.fy = $6 AND x = ANY($1)`,
		ids, rules.SchoolTrainingTypes, rules.CompletedStatuses, rules.ClusterTrainingTypes, rules.ClusterCreditStatuses, fy)
	if err != nil {
		return nil, fmt.Errorf("programmerollout: reading the schools trained: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var id string
		if err := rows.Scan(&id); err != nil {
			return nil, fmt.Errorf("programmerollout: reading a school trained: %w", err)
		}
		if _, ok := s.schools[id]; ok {
			out[id] = true
		}
	}
	return out, rows.Err()
}

// sortCourses is course_rows' order: most planned, most delivered, by name.
func sortCourses(rows []courseRow) {
	sort.SliceStable(rows, func(i, j int) bool {
		a, b := rows[i], rows[j]
		if a.planned != b.planned {
			return a.planned > b.planned
		}
		if a.delivered != b.delivered {
			return a.delivered > b.delivered
		}
		return a.name < b.name
	})
}

// courseRow is one course of the Trainings by course table.
type courseRow struct {
	fold
	name, category, abbr string
}
