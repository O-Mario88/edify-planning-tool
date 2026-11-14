// Package plreview is Completion Reviews (/pl/review-queue): the completed
// work waiting on this reviewer, longest waiting first, as the existing page
// draws it (apps.frontend.views.my_plan_views.pl_queue_view,
// apps.pl_review.services.review_register and
// partials/my_plan/completion_reviews_register.html) and the app's feed reads
// it. A Programme Lead reads the register on their dashboard, so the page
// sends them there. Verifying and returning stay with the existing
// application.
//
// The door, the roles, the labels and the page size are exported to
// rules.json by `manage.py export_completion_reviews_rules`;
// apps/pl_review/test_completion_reviews_rules_export.py fails when the two
// differ.
package plreview

import (
	"context"
	_ "embed"
	"encoding/json"
	"fmt"
	"net/url"
	"slices"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pagegate"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// Path is the page.
const Path = "/pl/review-queue"

const pageParam = "review_page"

//go:embed rules.json
var rulesJSON []byte

var rules = func() (r struct {
	PageRoles                 []string          `json:"page_roles"`
	DashboardRole             string            `json:"dashboard_role"`
	LeadRole                  string            `json:"lead_role"`
	AdminRole                 string            `json:"admin_role"`
	LeadVerifiedRoles         []string          `json:"lead_verified_roles"`
	ActivityTypes             map[string]string `json:"activity_types"`
	InterventionAbbreviations map[string]string `json:"intervention_abbreviations"`
	PageSize                  int               `json:"page_size"`
}) {
	if err := json.Unmarshal(rulesJSON, &r); err != nil || len(r.PageRoles) == 0 || r.LeadRole == "" || len(r.LeadVerifiedRoles) == 0 || r.PageSize == 0 {
		panic(fmt.Sprintf("plreview: the embedded rules are unreadable: %v", err))
	}
	return r
}()

// zone is settings.TIME_ZONE, the zone the local day is read in.
var zone = func() *time.Location {
	z, err := time.LoadLocation("Africa/Kampala")
	if err != nil {
		panic(fmt.Sprintf("plreview: loading the zone: %v", err))
	}
	return z
}()

// Service answers the register from the existing database.
type Service struct {
	db  schooldirectory.Querier
	now func() time.Time
}

// NewService is the register over db.
func NewService(db schooldirectory.Querier, now func() time.Time) *Service {
	return &Service{db: db, now: now}
}

// completion is one waiting completion as its row needs it.
type completion struct {
	ID, Owner, Type, Name, Venue, SalesforceID, Intervention string
	School, SchoolCode, Cluster                              *string
	Actual, Planned                                          *time.Time
	Scheduled                                                *time.Time
	Teachers, Leaders, Others, AttendedSchools               int
	Since                                                    time.Time
}

// Build answers Path: a Programme Lead is sent to their dashboard's tab;
// Admin and Impact Assessment read the register here.
func (s *Service) Build(ctx context.Context, p auth.Principal, path string, query url.Values) (*screensv1.GetPageResponse, bool, error) {
	if path != Path {
		return nil, false, nil
	}
	if !slices.Contains(rules.PageRoles, p.ActiveRole) {
		return nil, true, pagegate.ErrNotAvailable
	}
	if p.ActiveRole == rules.DashboardRole {
		return &screensv1.GetPageResponse{Redirect: dashboardURL(strings.TrimSpace(query.Get("cceo")), strings.TrimSpace(query.Get("open")))}, true, nil
	}
	list, err := s.queue(ctx, p)
	if err != nil {
		return nil, true, err
	}
	owners := []string{}
	for _, c := range list {
		if c.Owner != "" {
			owners = append(owners, c.Owner)
		}
	}
	names, profileOf, err := s.people(ctx, owners)
	if err != nil {
		return nil, true, err
	}
	now := s.now().In(zone)
	today := time.Date(now.Year(), now.Month(), now.Day(), 0, 0, 0, 0, time.UTC)
	rows, options := register(list, names, profileOf, today)
	wanted := strings.TrimSpace(query.Get("cceo"))
	chosen := wanted
	if pr, ok := profileOf[wanted]; ok {
		chosen = pr
	}
	if wanted != "" {
		kept := []row{}
		for _, r := range rows {
			if r.Profile == chosen {
				kept = append(kept, r)
			}
		}
		rows = kept
	}
	return page(rows, options, chosen, query), true, nil
}

// dashboardURL is reviews_on_dashboard_url: the dashboard's Execution &
// Completion tab carrying the officer and the completion asked for, in that
// order.
func dashboardURL(cceo, open string) string {
	carried := "view=execution"
	if cceo != "" {
		carried += "&cceo=" + url.QueryEscape(cceo)
	}
	if open != "" {
		carried += "&open=" + url.QueryEscape(open)
	}
	return "/dashboard?pm=" + url.QueryEscape(carried) + "#planning-monitor"
}

// queue is _queue_queryset: the live completions sent to a lead, and work an
// older path left with Impact Assessment whose owner a lead verifies; all of
// them for the Admin, else those filed under the people this reviewer
// supervises (never their own), and a lead's own staff work. Newest first,
// the model's order, before the register sorts them by their wait.
func (s *Service) queue(ctx context.Context, p auth.Principal) ([]completion, error) {
	args := []any{rules.LeadVerifiedRoles, rules.LeadRole}
	where := `a.deleted_at IS NULL AND (a.status = 'submitted_to_pl' OR (a.status = 'awaiting_ia_verification'
  AND a.delivery_type IS DISTINCT FROM 'partner'
  AND (a.responsible_staff_id IN (SELECT id FROM lead_verified) OR a.responsible_staff_id IN (SELECT user_id FROM lead_verified))))`
	if p.ActiveRole != rules.AdminRole {
		scope, err := schooldirectory.ResolveScope(ctx, s.db, p, s.now())
		if err != nil {
			return nil, fmt.Errorf("plreview: resolving the reviewer's scope: %w", err)
		}
		mine := []string{}
		for _, id := range []string{p.UserID, scope.StaffID} {
			if id != "" {
				mine = append(mine, id)
			}
		}
		clearsOwn := p.ActiveRole == rules.LeadRole && slices.Contains(p.Roles, rules.LeadRole)
		if len(scope.SupervisedStaffIDs) == 0 && !clearsOwn {
			return nil, nil
		}
		supervised := scope.SupervisedStaffIDs
		if supervised == nil {
			supervised = []string{}
		}
		args = append(args, supervised, mine)
		sup, own := len(args)-1, len(args)
		reviewable := fmt.Sprintf(`(SELECT unnest($%[1]d::varchar[]) UNION SELECT user_id FROM staff_profile WHERE id = ANY($%[1]d) AND user_id IS NOT NULL)`, sup)
		mineSet := fmt.Sprintf(`(SELECT unnest($%d::varchar[]))`, own)
		filedUnder := func(ids string) string {
			return fmt.Sprintf(`(COALESCE(a.responsible_staff_id IN %[1]s, FALSE) OR (a.responsible_staff_id IS NULL AND COALESCE(a.monitored_by_staff_id IN %[1]s, FALSE)))`, ids)
		}
		waiting := fmt.Sprintf("(%s AND NOT %s)", filedUnder(reviewable), filedUnder(mineSet))
		if clearsOwn {
			waiting = fmt.Sprintf("(%s OR (a.responsible_staff_id = ANY($%d) AND a.delivery_type IS DISTINCT FROM 'partner'))", waiting, own)
		}
		where += " AND " + waiting
	}
	rows, err := s.db.Query(ctx, `
WITH lead_verified AS (
  SELECT DISTINCT sp.id, sp.user_id FROM staff_profile sp LEFT JOIN "user" u ON u.id = sp.user_id
  WHERE sp.deleted_at IS NULL AND (u.roles && $1::varchar[] OR EXISTS (
    SELECT 1 FROM staff_supervisor_assignment l JOIN staff_profile sv ON sv.id = l.supervisor_id JOIN "user" su ON su.id = sv.user_id
    WHERE l.supervisee_id = sp.id AND sv.deleted_at IS NULL AND su.roles @> ARRAY[$2::varchar])))
SELECT a.id, COALESCE(a.responsible_staff_id, a.monitored_by_staff_id, ''), a.activity_type, COALESCE(a.activity_name_snapshot, ''),
  COALESCE(a.venue, ''), COALESCE(a.salesforce_activity_id, ''), COALESCE(a.focus_intervention, ''),
  s.name, s.school_id, cl.name, a.actual_delivery_date, a.planned_date, a.scheduled_date,
  COALESCE(a.teachers_attended, 0), COALESCE(a.leaders_attended, 0), COALESCE(a.other_participants, 0),
  CASE WHEN a.cluster_id IS NOT NULL AND a.school_id IS NULL THEN COALESCE(cardinality(a.attended_school_ids), 0) ELSE 0 END,
  COALESCE(v.updated_at, a.submitted_to_ia_at, a.updated_at)
FROM activity a LEFT JOIN school s ON s.id = a.school_id LEFT JOIN cluster cl ON cl.id = a.cluster_id
LEFT JOIN activity_completion_verification v ON v.activity_id = a.id
WHERE `+where+`
ORDER BY a.created_at DESC`, args...)
	if err != nil {
		return nil, fmt.Errorf("plreview: reading the waiting completions: %w", err)
	}
	return pgx.CollectRows(rows, func(r pgx.CollectableRow) (completion, error) {
		var c completion
		err := r.Scan(&c.ID, &c.Owner, &c.Type, &c.Name, &c.Venue, &c.SalesforceID, &c.Intervention,
			&c.School, &c.SchoolCode, &c.Cluster, &c.Actual, &c.Planned, &c.Scheduled,
			&c.Teachers, &c.Leaders, &c.Others, &c.AttendedSchools, &c.Since)
		return c, err
	})
}

// people is _people: the name and People record of everyone filed under
// either id space.
func (s *Service) people(ctx context.Context, ids []string) (map[string]string, map[string]string, error) {
	names, profileOf := map[string]string{}, map[string]string{}
	if len(ids) == 0 {
		return names, profileOf, nil
	}
	rows, err := s.db.Query(ctx, `SELECT sp.id, COALESCE(sp.user_id, ''), COALESCE(u.name, '') FROM staff_profile sp
LEFT JOIN "user" u ON u.id = sp.user_id WHERE sp.deleted_at IS NULL AND (sp.id = ANY($1) OR sp.user_id = ANY($1))`, ids)
	if err != nil {
		return nil, nil, fmt.Errorf("plreview: reading the officers' names: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var id, user, name string
		if err := rows.Scan(&id, &user, &name); err != nil {
			return nil, nil, fmt.Errorf("plreview: reading the officers' names: %w", err)
		}
		for _, key := range []string{id, user} {
			if key != "" {
				names[key], profileOf[key] = name, id
			}
		}
	}
	return names, profileOf, rows.Err()
}
