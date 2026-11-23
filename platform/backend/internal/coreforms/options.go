package coreforms

import (
	"context"
	"fmt"
	"slices"
	"sort"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"
)

const (
	notSSAScored     = "Not SSA-scored"
	anyInterventions = "any_ssa_intervention"
	strongScore      = 8.0
	recommendedCount = 4
)

// followUpStatuses is FOLLOW_UP_SOURCE_STATUSES, awaitingVerification those a
// reviewer has not yet verified.
var (
	followUpStatuses     = []string{"submitted_to_pl", "awaiting_ia_verification", "completed", "ia_verified", "accountant_confirmed", "closed"}
	awaitingVerification = []string{"submitted_to_pl", "awaiting_ia_verification"}
	schoolTrainingTypes  = []string{"training", "in_school_training", "school_improvement_training", "core_training"}
	clusterSessionTypes  = []string{"cluster_training", "cluster_training_ssa_collection", "cluster_meeting", "cluster_meeting_ssa_review"}
)

// Choice is one option of a form's list.
type Choice struct{ Value, Label string }

// Need is one ranked SSA intervention.
type Need struct {
	Code, Label string
	Score       float64
}

// recommended is CoreInterventionRecommendationService.recommend's rows: the
// four weakest, or none where every intervention is strong.
func recommended(ranked []Need) []Need {
	if len(ranked) == 0 {
		return nil
	}
	strong := true
	for _, need := range ranked {
		strong = strong && need.Score >= strongScore
	}
	if strong {
		return nil
	}
	return ranked[:min(recommendedCount, len(ranked))]
}

// Course is one training the in-school picker offers.
type Course struct {
	ID, Label, Code, Category, Indicator string
	InterventionLabel                    string
	PlannerChooses, PartnerAllowed       bool
	standard                             bool
}

type courseMapping struct {
	intervention, mode string
	primary            bool
}

// applyMappings is _serialize_training_courses' reading of the primary
// mapping: the active one marked primary, else the first.
func (c *Course) applyMappings(mappings []courseMapping, names map[string]string) {
	c.InterventionLabel = notSSAScored
	if len(mappings) == 0 {
		return
	}
	primary := mappings[0]
	for _, mapping := range mappings {
		if mapping.primary {
			primary = mapping
			break
		}
	}
	if primary.intervention != "" {
		c.InterventionLabel = names[primary.intervention]
		return
	}
	c.PlannerChooses = primary.mode == anyInterventions
}

func sortCourses(courses []Course) []Course {
	sorted := slices.Clone(courses)
	sort.SliceStable(sorted, func(i, j int) bool {
		a, b := sorted[i], sorted[j]
		if a.standard != b.standard {
			return a.standard
		}
		if x, y := strings.ToLower(a.Label), strings.ToLower(b.Label); x != y {
			return x < y
		}
		return a.Code < b.Code
	})
	return sorted
}

// courses is in_school_training_course_options on the local day.
func (s *Service) courses(ctx context.Context, interventions map[string]string, day time.Time) ([]Course, error) {
	rows, err := s.db.Query(ctx, `SELECT id, display_name, stable_code, COALESCE(training_category, ''),
  COALESCE(ssa_indicator_label, ''), standard_support, partner_delivery_allowed
FROM activity_catalogue_item
WHERE status = 'active' AND (effective_from IS NULL OR effective_from <= $1)
  AND (effective_to IS NULL OR effective_to >= $1) AND is_training_course AND staff_delivery_allowed
ORDER BY display_name, stable_code`, day.Format(time.DateOnly))
	if err != nil {
		return nil, fmt.Errorf("coreforms: reading the courses: %w", err)
	}
	courses, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (Course, error) {
		var c Course
		err := row.Scan(&c.ID, &c.Label, &c.Code, &c.Category, &c.Indicator, &c.standard, &c.PartnerAllowed)
		return c, err
	})
	if err != nil {
		return nil, fmt.Errorf("coreforms: reading a course: %w", err)
	}
	ids := make([]string, len(courses))
	for i, course := range courses {
		ids[i] = course.ID
	}
	mapped, err := s.db.Query(ctx, `SELECT catalogue_item_id, COALESCE(intervention, ''), mapping_mode, is_primary
FROM activity_intervention_mapping WHERE active AND catalogue_item_id = ANY($1) ORDER BY priority, id`, ids)
	if err != nil {
		return nil, fmt.Errorf("coreforms: reading the course mappings: %w", err)
	}
	defer mapped.Close()
	byCourse := map[string][]courseMapping{}
	for mapped.Next() {
		var id string
		var m courseMapping
		if err := mapped.Scan(&id, &m.intervention, &m.mode, &m.primary); err != nil {
			return nil, fmt.Errorf("coreforms: reading a course mapping: %w", err)
		}
		byCourse[id] = append(byCourse[id], m)
	}
	if err := mapped.Err(); err != nil {
		return nil, fmt.Errorf("coreforms: reading the course mappings: %w", err)
	}
	for i := range courses {
		courses[i].applyMappings(byCourse[courses[i].ID], interventions)
	}
	return sortCourses(courses), nil
}

// FollowUp is one completed training a follow-up can name.
type FollowUp struct {
	ID, Label, InterventionLabel string
}

type trainingDone struct {
	snapshot, catalogue, kind, typeLabel, cluster, status string
	day                                                   *time.Time
}

// label is follow_up_options' line.
func (t trainingDone) label() string {
	name := t.snapshot
	if name == "" {
		name = t.catalogue
	}
	if name == "" {
		name = t.typeLabel
	}
	when := "Date not recorded"
	if t.day != nil {
		when = t.day.Format("02 Jan 2006")
	}
	where := "At the school"
	if slices.Contains(clusterSessionTypes, t.kind) {
		where = t.cluster
		if where == "" {
			where = "Cluster session"
		}
	}
	line := name + " · " + when + " · " + where
	if slices.Contains(awaitingVerification, t.status) {
		line += " · awaiting verification"
	}
	return line
}

// followUps is follow_up_options(school, fy), newest first.
func (s *Service) followUps(ctx context.Context, school School, fy string, interventions, typeLabels map[string]string) ([]FollowUp, error) {
	rows, err := s.db.Query(ctx, `
SELECT a.id, COALESCE(a.activity_name_snapshot, ''), COALESCE(ci.display_name, ''), a.activity_type,
  COALESCE(c.name, ''), a.status, a.planned_date, COALESCE(NULLIF(a.focus_intervention, ''), a.purpose_intervention, '')
FROM activity a
LEFT JOIN activity_catalogue_item ci ON ci.id = a.catalogue_item_id
LEFT JOIN cluster c ON c.id = a.cluster_id
WHERE a.deleted_at IS NULL AND a.fy = $1 AND a.status = ANY($2)
  AND ((a.school_id = $3 AND a.activity_type = ANY($4))
    OR (a.activity_type = ANY($5) AND (a.attended_school_ids @> ARRAY[$3]::varchar[]
      OR EXISTS (SELECT 1 FROM cluster_activity_attendance att
                  WHERE att.activity_id = a.id AND att.school_id = $3 AND att.attended))))
ORDER BY a.planned_date DESC, a.created_at DESC`, fy, followUpStatuses, school.ID, schoolTrainingTypes, clusterSessionTypes)
	if err != nil {
		return nil, fmt.Errorf("coreforms: reading the trainings done: %w", err)
	}
	options, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (FollowUp, error) {
		var option FollowUp
		var done trainingDone
		var intervention string
		if err := row.Scan(&option.ID, &done.snapshot, &done.catalogue, &done.kind, &done.cluster, &done.status, &done.day, &intervention); err != nil {
			return option, err
		}
		done.typeLabel = typeLabels[done.kind]
		option.Label = done.label()
		option.InterventionLabel = notSSAScored
		if intervention != "" {
			option.InterventionLabel = intervention
			if label, ok := interventions[intervention]; ok {
				option.InterventionLabel = label
			}
		}
		return option, nil
	})
	if err != nil {
		return nil, fmt.Errorf("coreforms: reading a training done: %w", err)
	}
	return options, nil
}

// Partner is one organisation a hand-over may name. Codes are the courses it
// is recorded as delivering, empty for one not yet scoped.
type Partner struct {
	ID, Name string
	Codes    []string
}

// assignablePartners is partners.services.assignable_partners.
func (s *Service) assignablePartners(ctx context.Context) ([]Partner, error) {
	rows, err := s.db.Query(ctx, `SELECT p.id, p.name, COALESCE(p.activity_codes, '{}')
FROM partner p
WHERE p.deleted_at IS NULL AND p.active_status AND p.partner_role <> 'loan'
  AND NOT EXISTS (SELECT 1 FROM partner_hold h WHERE h.partner_id = p.id AND h.lifted_at IS NULL)
ORDER BY p.name`)
	if err != nil {
		return nil, fmt.Errorf("coreforms: reading the partners: %w", err)
	}
	partners, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (Partner, error) {
		var partner Partner
		err := row.Scan(&partner.ID, &partner.Name, &partner.Codes)
		return partner, err
	})
	if err != nil {
		return nil, fmt.Errorf("coreforms: reading a partner: %w", err)
	}
	return partners, nil
}

// facilitators is facilitation.facilitator_partners: every active partner.
func (s *Service) facilitators(ctx context.Context) ([]Choice, error) {
	return s.choices(ctx, `SELECT id, name FROM partner WHERE deleted_at IS NULL AND active_status ORDER BY name`)
}

// staffMembers is the Responsible staff list: a person's user id and name.
func (s *Service) staffMembers(ctx context.Context) ([]Choice, error) {
	return s.choices(ctx, `SELECT COALESCE(sp.user_id, ''), COALESCE(u.name, '') FROM staff_profile sp
JOIN "user" u ON u.id = sp.user_id WHERE sp.deleted_at IS NULL ORDER BY u.name`)
}

func (s *Service) choices(ctx context.Context, sql string) ([]Choice, error) {
	rows, err := s.db.Query(ctx, sql)
	if err != nil {
		return nil, fmt.Errorf("coreforms: reading a list: %w", err)
	}
	choices, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (Choice, error) {
		var choice Choice
		err := row.Scan(&choice.Value, &choice.Label)
		return choice, err
	})
	if err != nil {
		return nil, fmt.Errorf("coreforms: reading a list's row: %w", err)
	}
	return choices, nil
}

// approvalOwner is visit_requests.approval_owner_for and staff_name: the name
// of the person whose approval an Accountant's visit needs, "" when none.
func (s *Service) approvalOwner(ctx context.Context, school School, userID, staffID string) (string, error) {
	owners, err := s.ownerIDs(ctx, school)
	if err != nil || len(owners) == 0 {
		return "", err
	}
	if slices.Contains(owners, userID) || (staffID != "" && slices.Contains(owners, staffID)) {
		return "", nil
	}
	var name *string
	err = s.db.QueryRow(ctx, `SELECT u.name FROM staff_profile sp LEFT JOIN "user" u ON u.id = sp.user_id
WHERE sp.deleted_at IS NULL AND (sp.id = ANY($1) OR sp.user_id = ANY($1)) ORDER BY sp.id LIMIT 1`, owners).Scan(&name)
	if err != nil {
		if err == pgx.ErrNoRows {
			return "", nil
		}
		return "", fmt.Errorf("coreforms: reading the school's owner: %w", err)
	}
	if name == nil || *name == "" {
		return "the school's owner", nil
	}
	return *name, nil
}

// ownerIDs is school_owner_ids: the owner column, else a single assignment,
// in both id spaces.
func (s *Service) ownerIDs(ctx context.Context, school School) ([]string, error) {
	owner := strings.TrimSpace(school.AccountOwner)
	if owner == "" {
		rows, err := s.db.Query(ctx, `SELECT staff_id FROM staff_school_assignment WHERE school_id = $1 LIMIT 2`, school.ID)
		if err != nil {
			return nil, fmt.Errorf("coreforms: reading the school's assignment: %w", err)
		}
		assigned, err := pgx.CollectRows(rows, pgx.RowTo[string])
		if err != nil {
			return nil, fmt.Errorf("coreforms: reading an assignment: %w", err)
		}
		if len(assigned) != 1 {
			return nil, nil
		}
		owner = assigned[0]
	}
	ids := []string{owner}
	rows, err := s.db.Query(ctx, `SELECT id, COALESCE(user_id, '') FROM staff_profile
WHERE deleted_at IS NULL AND (id = $1 OR user_id = $1)`, owner)
	if err != nil {
		return nil, fmt.Errorf("coreforms: reading the owner's ids: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var id, user string
		if err := rows.Scan(&id, &user); err != nil {
			return nil, fmt.Errorf("coreforms: reading an owner id: %w", err)
		}
		for _, value := range []string{id, user} {
			if value != "" && !slices.Contains(ids, value) {
				ids = append(ids, value)
			}
		}
	}
	return ids, rows.Err()
}
