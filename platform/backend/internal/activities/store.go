package activities

import (
	"context"
	"errors"
	"fmt"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"
)

// Querier is the read the save takes, inside its transaction or before it.
type Querier interface {
	Query(ctx context.Context, sql string, args ...any) (pgx.Rows, error)
	QueryRow(ctx context.Context, sql string, args ...any) pgx.Row
}

type school struct {
	ID, Code, Name, Type, Status string
	DistrictID, ClusterID        string
	DistrictName, DistrictType   string
}

func (s school) closed() bool { return in(rules.ClosedStatuses, s.Status) }

// item is an activity_catalogue_item, as far as the save reads it.
type item struct {
	ID, WorkflowKind, DisplayName, ActivityType, DeliveryMethod   string
	EvidenceProfile, SalesforceRecordType, CostingProfile, Status string
	StandardSupport, CountsTowardClientVisit, RequiresSchool      bool
	RequiresCluster, IsTrainingCourse                             bool
	ParticipantMode                                               string
	// Modes are the active mappings' modes, primary first
	// (activity_catalogue.services._mapping).
	Modes []string
}

const itemColumns = `i.id, i.workflow_kind, i.display_name, i.activity_type, i.delivery_method,
  COALESCE(i.evidence_profile, ''), COALESCE(i.salesforce_record_type, ''), COALESCE(i.costing_profile, ''), i.status,
  i.standard_support, i.counts_toward_client_visit, i.requires_school, i.requires_cluster, i.is_training_course,
  COALESCE(i.participant_mode, '')`

func scanItem(row pgx.Row) (item, error) {
	var it item
	err := row.Scan(&it.ID, &it.WorkflowKind, &it.DisplayName, &it.ActivityType, &it.DeliveryMethod,
		&it.EvidenceProfile, &it.SalesforceRecordType, &it.CostingProfile, &it.Status,
		&it.StandardSupport, &it.CountsTowardClientVisit, &it.RequiresSchool, &it.RequiresCluster,
		&it.IsTrainingCourse, &it.ParticipantMode)
	return it, err
}

// effective is activity_catalogue.services.effective_items(on).
const effective = `i.status = 'active' AND (i.effective_from IS NULL OR i.effective_from <= $1)
  AND (i.effective_to IS NULL OR i.effective_to >= $1)`

// itemByID is any catalogue row by id (the view's pinned-item read, 2229).
func itemByID(ctx context.Context, q Querier, id string) (*item, error) {
	it, err := scanItem(q.QueryRow(ctx, `SELECT `+itemColumns+` FROM activity_catalogue_item i WHERE i.id = $1`, id))
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, nil
	}
	if err != nil {
		return nil, fmt.Errorf("activities: reading the catalogue item: %w", err)
	}
	return &it, nil
}

// selectableItem is get_selectable_item(id or code, on_date).
func selectableItem(ctx context.Context, q Querier, idOrCode string, on time.Time) (*item, error) {
	it, err := scanItem(q.QueryRow(ctx, `SELECT `+itemColumns+` FROM activity_catalogue_item i
WHERE `+effective+` AND (i.id = $2 OR i.stable_code = $2)
ORDER BY i.display_name, i.stable_code LIMIT 1`, on.Format(time.DateOnly), idOrCode))
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, nil
	}
	if err != nil {
		return nil, fmt.Errorf("activities: reading the selectable item: %w", err)
	}
	if it.Modes, err = mappingModes(ctx, q, it.ID); err != nil {
		return nil, err
	}
	return &it, nil
}

// resolveForKind is resolve_item_for_workflow_kind(kind, on_date): the one
// standard-support item of the kind, else the only item of it.
func resolveForKind(ctx context.Context, q Querier, kind string, on time.Time) (*item, error) {
	if costed, ok := rules.CostedAs[kind]; ok {
		kind = costed
	}
	rows, err := q.Query(ctx, `SELECT `+itemColumns+` FROM activity_catalogue_item i
WHERE `+effective+` AND i.workflow_kind = $2 ORDER BY i.stable_code`, on.Format(time.DateOnly), kind)
	if err != nil {
		return nil, fmt.Errorf("activities: resolving the purpose's item: %w", err)
	}
	items, err := pgx.CollectRows(rows, func(r pgx.CollectableRow) (item, error) { return scanItem(r) })
	if err != nil {
		return nil, fmt.Errorf("activities: resolving the purpose's item: %w", err)
	}
	var standard []item
	for _, it := range items {
		if it.StandardSupport {
			standard = append(standard, it)
		}
	}
	switch {
	case len(standard) == 1:
		return &standard[0], nil
	case len(items) == 1:
		return &items[0], nil
	}
	return nil, nil
}

func mappingModes(ctx context.Context, q Querier, itemID string) ([]string, error) {
	rows, err := q.Query(ctx, `SELECT mapping_mode FROM activity_intervention_mapping
WHERE catalogue_item_id = $1 AND active ORDER BY is_primary DESC, priority, id`, itemID)
	if err != nil {
		return nil, fmt.Errorf("activities: reading the item's mappings: %w", err)
	}
	return pgx.CollectRows(rows, pgx.RowTo[string])
}

func latestVersion(ctx context.Context, q Querier, itemID string) (int, bool, error) {
	var v int
	err := q.QueryRow(ctx, `SELECT version FROM activity_catalogue_version WHERE catalogue_item_id = $1
ORDER BY version DESC LIMIT 1`, itemID).Scan(&v)
	if errors.Is(err, pgx.ErrNoRows) {
		return 0, false, nil
	}
	if err != nil {
		return 0, false, fmt.Errorf("activities: reading the item's version: %w", err)
	}
	return v, true, nil
}

// schoolByIDOrCode is the view's School lookup (Q(id=…) | Q(school_id=…)),
// soft-deleted schools left out as School.objects leaves them.
func schoolByIDOrCode(ctx context.Context, q Querier, key string) (*school, error) {
	var s school
	err := q.QueryRow(ctx, `
SELECT s.id, COALESCE(s.school_id, ''), s.name, COALESCE(s.school_type, ''), COALESCE(s.operational_status, ''),
       COALESCE(s.district_id, ''), COALESCE(s.cluster_id, ''), COALESCE(d.name, ''), COALESCE(d.district_type, '')
FROM school s LEFT JOIN district d ON d.id = s.district_id
WHERE s.deleted_at IS NULL AND (s.id = $1 OR s.school_id = $1)
ORDER BY s.created_at DESC LIMIT 1`, key).Scan(&s.ID, &s.Code, &s.Name, &s.Type, &s.Status,
		&s.DistrictID, &s.ClusterID, &s.DistrictName, &s.DistrictType)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, nil
	}
	if err != nil {
		return nil, fmt.Errorf("activities: reading the school: %w", err)
	}
	return &s, nil
}

// schoolOwner is ResponsibleActorService.for_school: the staff profile of
// the school's first assignment, when it has an account and a name.
func schoolOwner(ctx context.Context, q Querier, schoolID string) (string, error) {
	var staffID, userID, name *string
	err := q.QueryRow(ctx, `
SELECT sp.id, sp.user_id, u.name FROM staff_school_assignment a
LEFT JOIN staff_profile sp ON sp.id = a.staff_id LEFT JOIN "user" u ON u.id = sp.user_id
WHERE a.school_id = $1 ORDER BY a.created_at LIMIT 1`, schoolID).Scan(&staffID, &userID, &name)
	if errors.Is(err, pgx.ErrNoRows) {
		return "", nil
	}
	if err != nil {
		return "", fmt.Errorf("activities: reading the school's owner: %w", err)
	}
	if staffID == nil || userID == nil || *userID == "" || name == nil || *name == "" {
		return "", nil
	}
	return *staffID, nil
}

// followUpNeedsTraining is fy_policy.follow_up_requires_prior_training: true
// when the year has no policy.
func followUpNeedsTraining(ctx context.Context, q Querier, fy string) (bool, error) {
	var needs bool
	err := q.QueryRow(ctx, `SELECT follow_up_visit_requires_prior_training FROM fiscal_year_planning_policy
WHERE country = $1 AND fy = $2 ORDER BY created_at LIMIT 1`, rules.DefaultCountry, fy).Scan(&needs)
	if errors.Is(err, pgx.ErrNoRows) {
		return true, nil
	}
	if err != nil {
		return false, fmt.Errorf("activities: reading the year's planning policy: %w", err)
	}
	return needs, nil
}

// staffDistrictHome is what district_type_for_staff reads of the person:
// their roles and home district.
type staffHome struct {
	Found          bool
	Roles          []string
	ActiveRole     string
	HomeDistrictID string
}

func staffHomeOf(ctx context.Context, q Querier, responsible string) (staffHome, error) {
	var h staffHome
	var home *string
	err := q.QueryRow(ctx, `
SELECT u.roles, COALESCE(u.active_role, ''), sp.primary_district_id
FROM staff_profile sp JOIN "user" u ON u.id = sp.user_id
WHERE sp.deleted_at IS NULL AND (sp.user_id = $1 OR sp.id = $1) LIMIT 1`, responsible).Scan(&h.Roles, &h.ActiveRole, &home)
	if errors.Is(err, pgx.ErrNoRows) {
		return h, nil
	}
	if err != nil {
		return h, fmt.Errorf("activities: reading the person's home district: %w", err)
	}
	h.Found = true
	if home != nil {
		h.HomeDistrictID = *home
	}
	return h, nil
}

func fieldRole(role string) bool {
	return in(rules.Batch.FieldRoles, role) || in(rules.Batch.FieldRoleAliases, strings.ToLower(strings.TrimSpace(role)))
}

// districtTypeFor is districts.district_type_for_staff for a person found
// on a profile (the save's responsible person always is).
func districtTypeFor(h staffHome, districtID, districtName, districtType string) string {
	if districtID == "" {
		return "primary"
	}
	field := false
	if len(h.Roles) == 0 {
		field = fieldRole(h.ActiveRole)
	}
	for _, r := range h.Roles {
		field = field || fieldRole(r)
	}
	if field {
		if h.HomeDistrictID != "" {
			if h.HomeDistrictID == districtID {
				return "primary"
			}
			return "secondary"
		}
		return districtType
	}
	if in(rules.Batch.HQZone, strings.ToLower(strings.TrimSpace(districtName))) {
		return "primary"
	}
	return "secondary"
}

// The SSA reads (needReader).

type pgNeed struct{ q Querier }

func (n pgNeed) confirmedHistory(ctx context.Context, schoolID string) ([]ssaRecord, error) {
	rows, err := n.q.Query(ctx, `SELECT id, COALESCE(fy, ''), date_of_ssa, created_at, average_score FROM ssa_record
WHERE school_id = $1 AND verification_status = 'confirmed' AND deleted_at IS NULL
ORDER BY date_of_ssa, created_at`, schoolID)
	if err != nil {
		return nil, fmt.Errorf("activities: reading the school's SSAs: %w", err)
	}
	records, err := pgx.CollectRows(rows, func(r pgx.CollectableRow) (ssaRecord, error) {
		var s ssaRecord
		return s, r.Scan(&s.ID, &s.FY, &s.Date, &s.CreatedAt, &s.AverageScore)
	})
	if err != nil {
		return nil, fmt.Errorf("activities: reading the school's SSAs: %w", err)
	}
	for i := range records {
		// The prefetch: SsaScore in its model order.
		rows, err := n.q.Query(ctx, `SELECT intervention, score FROM ssa_score WHERE ssa_record_id = $1 ORDER BY intervention, id`, records[i].ID)
		if err != nil {
			return nil, fmt.Errorf("activities: reading the SSA's scores: %w", err)
		}
		if records[i].Scores, err = pgx.CollectRows(rows, func(r pgx.CollectableRow) (ssaScore, error) {
			var s ssaScore
			return s, r.Scan(&s.Intervention, &s.Score)
		}); err != nil {
			return nil, fmt.Errorf("activities: reading the SSA's scores: %w", err)
		}
	}
	return records, nil
}

func (n pgNeed) pendingSince(ctx context.Context, schoolID string, after *time.Time) (*time.Time, error) {
	var at *time.Time
	err := n.q.QueryRow(ctx, `SELECT date_of_ssa FROM ssa_record
WHERE school_id = $1 AND deleted_at IS NULL AND verification_status = 'pending'
  AND ($2::timestamptz IS NULL OR date_of_ssa >= $2)
ORDER BY date_of_ssa DESC LIMIT 1`, schoolID, after).Scan(&at)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, nil
	}
	if err != nil {
		return nil, fmt.Errorf("activities: reading the pending SSA: %w", err)
	}
	return at, nil
}

// peerScores is _latest_scores_by_cluster for the school's cluster, the
// school itself left out: each operating member's latest confirmed scores,
// in the order the existing reads put them (school_id).
func (n pgNeed) peerScores(ctx context.Context, clusterID, schoolID string) ([]map[string]float64, error) {
	rows, err := n.q.Query(ctx, `
SELECT DISTINCT ON (r.school_id) r.school_id, r.id FROM ssa_record r
WHERE r.school_id IN (SELECT s.id FROM school s WHERE s.cluster_id = $1 AND s.deleted_at IS NULL
                       AND s.operational_status = ANY($2))
  AND r.verification_status = 'confirmed' AND r.deleted_at IS NULL
ORDER BY r.school_id, r.date_of_ssa DESC, r.created_at DESC`, clusterID, rules.OperatingStatuses)
	if err != nil {
		return nil, fmt.Errorf("activities: reading the cluster's SSAs: %w", err)
	}
	type latest struct{ school, record string }
	records, err := pgx.CollectRows(rows, func(r pgx.CollectableRow) (latest, error) {
		var l latest
		return l, r.Scan(&l.school, &l.record)
	})
	if err != nil {
		return nil, fmt.Errorf("activities: reading the cluster's SSAs: %w", err)
	}
	out := []map[string]float64{}
	for _, l := range records {
		if l.school == schoolID {
			continue
		}
		rows, err := n.q.Query(ctx, `SELECT intervention, score FROM ssa_score WHERE ssa_record_id = $1 AND score IS NOT NULL`, l.record)
		if err != nil {
			return nil, fmt.Errorf("activities: reading a peer's scores: %w", err)
		}
		scores := map[string]float64{}
		for rows.Next() {
			var code string
			var score float64
			if err := rows.Scan(&code, &score); err != nil {
				rows.Close()
				return nil, err
			}
			if rules.labels[code] != "" {
				scores[code] = score
			}
		}
		rows.Close()
		out = append(out, scores)
	}
	return out, nil
}
