package partnerworkspace

import (
	"context"
	"fmt"
	"net/url"
	"slices"
	"strings"
	"time"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pagegate"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/partnerassigned"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// Service answers Partner Activities from the existing database.
type Service struct {
	db  schooldirectory.Querier
	now func() time.Time
}

// NewService is the page over db, its day read from now.
func NewService(db schooldirectory.Querier, now func() time.Time) *Service {
	return &Service{db: db, now: now}
}

// filters is what the request asks for, as _partner_workspace reads it.
type filters struct {
	fy, region, partner, status string
}

// Build answers /partners; every other path is not its own.
func (s *Service) Build(ctx context.Context, p auth.Principal, path string, query url.Values) (*screensv1.GetPageResponse, bool, error) {
	if path != Path {
		return nil, false, nil
	}
	if !slices.Contains(rules.PageRoles, p.ActiveRole) {
		return nil, true, pagegate.ErrNotAvailable
	}
	if slices.Contains(rules.OversightRoles, p.ActiveRole) {
		return &screensv1.GetPageResponse{Redirect: oversightURL(query)}, true, nil
	}
	if strings.TrimSpace(query.Get("q")) != "" || query.Has("export") {
		return nil, false, nil
	}
	now := s.now()
	f := filters{
		fy:      query.Get("fy"),
		region:  strings.TrimSpace(query.Get("region")),
		partner: strings.TrimSpace(query.Get("partner")),
		status:  strings.TrimSpace(query.Get("status")),
	}
	options := schooldirectory.FYOptions(now)
	if !slices.Contains(options, f.fy) {
		f.fy = schooldirectory.OperationalFY(now)
	}
	today := civil(now.In(zone))

	var own []string
	if slices.Contains(rules.OwnOrganisationRoles, p.ActiveRole) {
		ids, err := partnerassigned.PartnerIDs(ctx, s.db, p)
		if err != nil {
			return nil, true, err
		}
		own = append([]string{}, ids...)
	}
	partners, err := s.partners(ctx, own, f.partner)
	if err != nil {
		return nil, true, err
	}
	ids := make([]string, len(partners))
	for i, pa := range partners {
		ids[i] = pa.id
	}
	activities, err := s.activities(ctx, ids, f, today)
	if err != nil {
		return nil, true, err
	}
	assignments, err := s.assignments(ctx, ids, f, today)
	if err != nil {
		return nil, true, err
	}
	w := build(partners, activities, assignments, f, today)
	for _, card := range w.cards {
		if len(card.rows) > rules.PageSize {
			// The card's table has pages of its own (card_rows_page<n>).
			return nil, false, nil
		}
	}
	view := view{w: w, f: f, fyOptions: options, partners: partners, role: p.ActiveRole, today: today}
	return &screensv1.GetPageResponse{Header: header(), Blocks: view.blocks(), WebPath: Path}, true, nil
}

// oversightURL is partners_list_view's redirect: Partner Oversight with the
// year and the partner the two pages read under the same names.
func oversightURL(query url.Values) string {
	carried := []string{}
	for _, key := range []string{"fy", "partner"} {
		if v := query.Get(key); v != "" {
			carried = append(carried, url.QueryEscape(key)+"="+url.QueryEscape(v))
		}
	}
	if len(carried) == 0 {
		return "/partner-oversight/"
	}
	return "/partner-oversight/?" + strings.Join(carried, "&")
}

// day is a calendar day, compared and printed as the page does.
type day struct{ t time.Time }

func civil(t time.Time) day {
	return day{time.Date(t.Year(), t.Month(), t.Day(), 0, 0, 0, 0, time.UTC)}
}

func (d day) before(o day) bool { return d.t.Before(o.t) }

// partner is one organisation, with what its card prints.
type partner struct {
	id, name, role, region, contact, phone, intervention string
	regions, interventions, activityCodes                []string
}

func (s *Service) partners(ctx context.Context, own []string, chosen string) ([]partner, error) {
	sql := `
SELECT id, name, partner_role, COALESCE(region_name, ''), region_names, COALESCE(contact_person, ''),
       COALESCE(phone, ''), COALESCE(ssa_intervention, ''), ssa_interventions, activity_codes
FROM partner WHERE deleted_at IS NULL`
	args := []any{}
	if own != nil {
		args = append(args, own)
		sql += fmt.Sprintf(" AND id = ANY($%d)", len(args))
	}
	if chosen != "" {
		args = append(args, chosen)
		sql += fmt.Sprintf(" AND id = $%d", len(args))
	}
	rows, err := s.db.Query(ctx, sql+" ORDER BY name", args...)
	if err != nil {
		return nil, fmt.Errorf("partnerworkspace: reading partners: %w", err)
	}
	defer rows.Close()
	out := []partner{}
	for rows.Next() {
		var pa partner
		if err := rows.Scan(&pa.id, &pa.name, &pa.role, &pa.region, &pa.regions, &pa.contact, &pa.phone,
			&pa.intervention, &pa.interventions, &pa.activityCodes); err != nil {
			return nil, fmt.Errorf("partnerworkspace: reading a partner: %w", err)
		}
		out = append(out, pa)
	}
	return out, rows.Err()
}

// target is the school or cluster a piece of work is for, as its row names it.
type target struct {
	schoolID, schoolName, code, district, schoolCluster string
	hasSchool, hasDistrict                              bool
	clusterID, clusterName                              string
	hasCluster                                          bool
	clusterOfSchool                                     string // the school's cluster's name ("" when none or deleted)
}

type activity struct {
	partnerID, activityType, purpose, focus, status string
	planned                                         *time.Time
	scheduled                                       *time.Time
	cost                                            int64
	costMissing                                     bool
	fy                                              string
	target
}

type assignment struct {
	partnerID, expected, purpose, focus string
	scheduled                           *time.Time
	target
}

// targetCols reads the school (s, its district d, its live cluster sc) and
// the work's own cluster (c).
const targetCols = `
       s.id IS NOT NULL, COALESCE(s.id, ''), COALESCE(s.name, ''), COALESCE(s.school_id, ''),
       d.id IS NOT NULL, COALESCE(d.name, ''), COALESCE(sc.name, ''),
       c.id IS NOT NULL, COALESCE(c.id, ''), COALESCE(c.name, '')`

func targetJoins(alias string) string {
	return `
LEFT JOIN school s ON s.id = ` + alias + `.school_id
LEFT JOIN district d ON d.id = s.district_id
LEFT JOIN cluster sc ON sc.id = s.cluster_id AND sc.deleted_at IS NULL
LEFT JOIN cluster c ON c.id = ` + alias + `.cluster_id`
}

func scanTarget(t *target) []any {
	return []any{&t.hasSchool, &t.schoolID, &t.schoolName, &t.code, &t.hasDistrict, &t.district, &t.clusterOfSchool,
		&t.hasCluster, &t.clusterID, &t.clusterName}
}

// todayStart is the moment timezone.localdate()'s day begins, which the
// Overdue filter compares a dated visit with.
func todayStart(today day) time.Time {
	return time.Date(today.t.Year(), today.t.Month(), today.t.Day(), 0, 0, 0, 0, zone)
}

func (s *Service) activities(ctx context.Context, ids []string, f filters, today day) ([]activity, error) {
	args := []any{ids, f.fy, rules.NonFundableStatuses}
	sql := `
SELECT a.assigned_partner_id, a.activity_type, COALESCE(a.purpose_type, ''), COALESCE(a.focus_intervention, ''),
       a.status, a.planned_date, a.scheduled_date, a.est_cost_cents, a.cost_missing, a.fy,` + targetCols + `
FROM activity a` + targetJoins("a") + `
WHERE a.assigned_partner_id = ANY($1) AND a.deleted_at IS NULL AND a.fy = $2 AND a.status <> ALL($3)`
	if f.region != "" {
		args = append(args, f.region)
		sql += fmt.Sprintf(" AND s.region_id = $%d", len(args))
	}
	switch f.status {
	case "scheduled":
		sql += " AND a.scheduled_date IS NOT NULL"
	case "yet_to_schedule":
		sql += " AND a.scheduled_date IS NULL"
	case "overdue":
		args = append(args, todayStart(today), rules.CompletedWork)
		sql += fmt.Sprintf(" AND a.scheduled_date < $%d AND a.status <> ALL($%d)", len(args)-1, len(args))
	}
	rows, err := s.db.Query(ctx, sql+" ORDER BY a.planned_date, a.scheduled_date, a.created_at", args...)
	if err != nil {
		return nil, fmt.Errorf("partnerworkspace: reading partner work: %w", err)
	}
	defer rows.Close()
	out := []activity{}
	for rows.Next() {
		var a activity
		dest := append([]any{&a.partnerID, &a.activityType, &a.purpose, &a.focus, &a.status, &a.planned, &a.scheduled,
			&a.cost, &a.costMissing, &a.fy}, scanTarget(&a.target)...)
		if err := rows.Scan(dest...); err != nil {
			return nil, fmt.Errorf("partnerworkspace: reading partner work: %w", err)
		}
		out = append(out, a)
	}
	return out, rows.Err()
}

func (s *Service) assignments(ctx context.Context, ids []string, f filters, today day) ([]assignment, error) {
	var fyNumber int
	if _, err := fmt.Sscan(f.fy, &fyNumber); err != nil {
		return nil, fmt.Errorf("partnerworkspace: the year %q: %w", f.fy, err)
	}
	start := time.Date(fyNumber-1, time.October, 1, 0, 0, 0, 0, time.UTC)
	end := time.Date(fyNumber, time.October, 1, 0, 0, 0, 0, time.UTC)
	args := []any{ids, rules.ReleasedStatuses, start, end}
	sql := `
SELECT pa.partner_id, COALESCE(pa.expected_activity_type, ''), COALESCE(pa.purpose_of_visit, ''),
       COALESCE(pa.focus_intervention, ''), pa.scheduled_date,` + targetCols + `
FROM partner_assignment pa` + targetJoins("pa") + `
WHERE pa.partner_id = ANY($1) AND pa.status <> ALL($2)
  AND (pa.scheduled_date IS NULL OR (pa.scheduled_date >= $3::date AND pa.scheduled_date < $4::date))`
	if f.region != "" {
		args = append(args, f.region)
		sql += fmt.Sprintf(" AND s.region_id = $%d", len(args))
	}
	switch f.status {
	case "scheduled":
		sql += " AND pa.scheduled_date IS NOT NULL"
	case "yet_to_schedule":
		sql += " AND pa.scheduled_date IS NULL"
	case "overdue":
		args = append(args, today.t)
		sql += fmt.Sprintf(" AND pa.scheduled_date < $%d::date", len(args))
	}
	rows, err := s.db.Query(ctx, sql+" ORDER BY pa.scheduled_date, pa.created_at", args...)
	if err != nil {
		return nil, fmt.Errorf("partnerworkspace: reading hand-overs: %w", err)
	}
	defer rows.Close()
	out := []assignment{}
	for rows.Next() {
		var a assignment
		dest := append([]any{&a.partnerID, &a.expected, &a.purpose, &a.focus, &a.scheduled}, scanTarget(&a.target)...)
		if err := rows.Scan(dest...); err != nil {
			return nil, fmt.Errorf("partnerworkspace: reading a hand-over: %w", err)
		}
		out = append(out, a)
	}
	return out, rows.Err()
}
