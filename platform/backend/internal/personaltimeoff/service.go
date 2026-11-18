// Package personaltimeoff builds Personal Time Off (/personal-time-off/:
// apps.frontend.views.leave_views.personal_time_off_view over
// apps.hr.leave_services, and pages/leave/personal_time_off.html, as the
// existing feed reads them): the reader's balances, their leave requests, the
// latest request's impact, their covers and handovers, the calendar's
// upcoming constraints, their team's next four weeks and the team leave
// tracker.
//
// It reads; it never writes. The existing page rewrites the reader's
// balances for the year every time it opens (recalculate_balances), and
// creates the profile, the policies and the balances when any is missing. Go
// answers only when that write would change nothing — the profile, the
// policies and the year's balances are there and every stored balance
// already equals its recalculation — and hands the page on otherwise. It also
// hands on a reader with schedule conflicts (drawn through a school identity
// tag Go does not draw yet) and a query it does not know. The doors and words
// are exported to rules.json by `manage.py export_personal_time_off_rules`;
// apps/hr/test_personal_time_off_rules_export.py fails when the two differ.
package personaltimeoff

import (
	"context"
	_ "embed"
	"encoding/json"
	"errors"
	"fmt"
	"math"
	"net/url"
	"slices"
	"sort"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/calendarpage"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/decisionlog"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/leaveapprovals"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/leavetracker"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pagegate"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// Path is the page this package answers.
const Path = "/personal-time-off/"

//go:embed rules.json
var rulesJSON []byte

type role struct {
	Page             bool               `json:"page"`
	Strip            *decisionlog.Strip `json:"strip"`
	Slug             string             `json:"slug"`
	LeavePolicies    bool               `json:"leave_policies"`
	TeamAvailability bool               `json:"team_availability"`
	Holidays         holidaysRole       `json:"holidays"`
	Coverage         coverageRole       `json:"coverage"`
}

var rules = func() (r struct {
	Roles            map[string]role `json:"roles"`
	BalancePriority  map[string]int  `json:"balance_priority"`
	PastStatuses     []string        `json:"past_statuses"`
	AwaitingDelivery []string        `json:"awaiting_delivery"`
}) {
	if err := json.Unmarshal(rulesJSON, &r); err != nil {
		panic(fmt.Sprintf("personaltimeoff: reading rules.json: %v", err))
	}
	if len(r.Roles) == 0 || len(r.BalancePriority) == 0 || len(r.AwaitingDelivery) == 0 {
		panic("personaltimeoff: rules.json lacks the doors, the balance order or the statuses")
	}
	return r
}()

// kampala is the page's local day.
var kampala = time.FixedZone("EAT", 3*60*60)

// Service builds the page.
type Service struct {
	db  schooldirectory.Querier
	now func() time.Time
}

// NewService is the page over db.
func NewService(db schooldirectory.Querier, now func() time.Time) *Service {
	return &Service{db: db, now: now}
}

// errPassOn is a reader the existing page answers.
var errPassOn = errors.New("personaltimeoff: handed on")

// Build answers /personal-time-off/; every other path is not its own.
func (s *Service) Build(ctx context.Context, p auth.Principal, path string, query url.Values) (*screensv1.GetPageResponse, bool, error) {
	if path == HolidaysPath {
		return s.holidays(ctx, p, query)
	}
	if path == CoveragePath {
		return s.coveragePage(ctx, p, query)
	}
	if path != Path {
		return nil, false, nil
	}
	r, ok := rules.Roles[p.ActiveRole]
	if !ok {
		return nil, false, nil
	}
	if !r.Page {
		return nil, true, pagegate.ErrNotAvailable
	}
	for key := range query {
		if key != "tab" {
			return nil, false, nil
		}
	}
	out, err := s.build(ctx, p, r)
	if errors.Is(err, errPassOn) {
		return nil, false, nil
	}
	if err != nil {
		return nil, true, err
	}
	return out, true, nil
}

// leave is one leave request.
type leave struct {
	id, staffID, staffName, staffRole, kind, start, end, status string
	coverName, reviewerID                                       string
	days, charged                                               int
}

// balance is one stored balance.
type balance struct {
	kind, label                                     string
	entitlement, used, pending, approved, remaining int
}

// cover is one coverage assignment or request.
type cover struct{ name, start, end string }

type view struct {
	r                                      role
	today                                  time.Time
	balances                               []balance
	leaves                                 []leave
	reviewers                              map[string]string
	labels                                 map[string]string
	pending, mine, delegated               []cover
	blocks                                 [][3]string
	heat                                   []leavetracker.HeatRow
	tracker                                []leave
	trackerBalances                        map[[2]string]int
	teamAway, teamTotal, coverActive       int
	impact                                 *impact
	ptoRemaining, ptoEntitlement, ptoUsed  int
	pendingCount, upcomingCount, pastCount int
}

// impact is LeaveImpactPreviewService.preview_impact's figures.
type impact struct {
	start, end                     string
	activities, holidays, blackout int
	conference                     bool
}

func (s *Service) build(ctx context.Context, p auth.Principal, r role) (*screensv1.GetPageResponse, error) {
	now := s.now()
	v := &view{r: r, today: day(now.In(kampala)), reviewers: map[string]string{}, labels: map[string]string{}}
	var staffID, country string
	err := s.db.QueryRow(ctx, `SELECT id, COALESCE(country, '') FROM staff_profile WHERE user_id = $1 ORDER BY id LIMIT 1`, p.UserID).Scan(&staffID, &country)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, errPassOn // the existing page creates the profile
	}
	if err != nil {
		return nil, fmt.Errorf("personaltimeoff: reading the profile: %w", err)
	}
	if err := s.readBalances(ctx, v, staffID); err != nil {
		return nil, err
	}
	if err := s.readLeaves(ctx, v, staffID); err != nil {
		return nil, err
	}
	if err := s.readCovers(ctx, v, staffID, now); err != nil {
		return nil, err
	}
	supervisees, err := strs(ctx, s.db, `SELECT supervisee_id FROM staff_supervisor_assignment WHERE supervisor_id = $1`, staffID)
	if err != nil {
		return nil, err
	}
	if err := s.readTeam(ctx, v, staffID, supervisees, now); err != nil {
		return nil, err
	}
	conflicts, err := s.conflicts(ctx, p, staffID)
	if err != nil {
		return nil, err
	}
	if conflicts > 0 {
		return nil, errPassOn
	}
	if v.heat, err = leavetracker.Heatmap(ctx, s.db, p, false, 10, 4, now.In(kampala)); err != nil {
		return nil, err
	}
	if len(v.leaves) > 0 {
		if v.impact, err = s.preview(ctx, p, staffID, v.leaves[0]); err != nil {
			return nil, err
		}
	}
	if err := s.readTracker(ctx, v, staffID, country, supervisees); err != nil {
		return nil, err
	}
	return page(v), nil
}

func day(t time.Time) time.Time { return time.Date(t.Year(), t.Month(), t.Day(), 0, 0, 0, 0, time.UTC) }

func strs(ctx context.Context, db schooldirectory.Querier, sql string, args ...any) ([]string, error) {
	rows, err := db.Query(ctx, sql, args...)
	if err != nil {
		return nil, fmt.Errorf("personaltimeoff: reading ids: %w", err)
	}
	return pgx.CollectRows(rows, pgx.RowTo[string])
}

// readBalances is the year's balances, when recalculate_balances would leave
// them as they are; anything it would write is handed on.
func (s *Service) readBalances(ctx context.Context, v *view, staffID string) error {
	rows, err := s.db.Query(ctx, `SELECT leave_type, label FROM leave_type_policy`)
	if err != nil {
		return fmt.Errorf("personaltimeoff: reading the policies: %w", err)
	}
	policies, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) ([2]string, error) {
		var p [2]string
		err := row.Scan(&p[0], &p[1])
		return p, err
	})
	if err != nil {
		return fmt.Errorf("personaltimeoff: reading the policies: %w", err)
	}
	if len(policies) == 0 {
		return errPassOn // the existing page seeds them
	}
	for _, p := range policies {
		v.labels[p[0]] = p[1]
	}
	year := v.today.Year()
	rows, err = s.db.Query(ctx, `
SELECT b.leave_type, b.entitlement, b.used, b.pending, b.approved, b.remaining,
  COALESCE((SELECT SUM(COALESCE(l.days_charged, l.days)) FROM leave l WHERE l.staff_id = b.staff_id AND l.type = b.leave_type
    AND l.start_date LIKE $3 AND l.status = 'approved'), 0)::int,
  COALESCE((SELECT SUM(COALESCE(l.days_charged, l.days)) FROM leave l WHERE l.staff_id = b.staff_id AND l.type = b.leave_type
    AND l.start_date LIKE $3 AND l.status = 'pending'), 0)::int
FROM leave_balance b WHERE b.staff_id = $1 AND b.year = $2`, staffID, year, fmt.Sprintf("%d%%", year))
	if err != nil {
		return fmt.Errorf("personaltimeoff: reading the balances: %w", err)
	}
	list, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (balance, error) {
		var b balance
		var approved, pending int
		err := row.Scan(&b.kind, &b.entitlement, &b.used, &b.pending, &b.approved, &b.remaining, &approved, &pending)
		if err == nil && (b.approved != approved || b.used != approved || b.pending != pending || b.remaining != b.entitlement-approved-pending) {
			err = errPassOn
		}
		return b, err
	})
	if errors.Is(err, errPassOn) {
		return errPassOn
	}
	if err != nil {
		return fmt.Errorf("personaltimeoff: reading the balances: %w", err)
	}
	if len(list) == 0 {
		return errPassOn // the existing page creates them
	}
	v.ptoRemaining, v.ptoEntitlement = 21, 21
	for i := range list {
		b := &list[i]
		b.label = v.labels[b.kind]
		if b.label == "" {
			b.label = pyTitle(strings.ReplaceAll(b.kind, "_", " "))
		}
		if b.kind == "personal_time_off" {
			v.ptoRemaining, v.ptoEntitlement, v.ptoUsed = b.remaining, b.entitlement, b.used
		}
	}
	sort.SliceStable(list, func(i, j int) bool {
		pi, ok := rules.BalancePriority[list[i].kind]
		if !ok {
			pi = len(rules.BalancePriority)
		}
		pj, ok := rules.BalancePriority[list[j].kind]
		if !ok {
			pj = len(rules.BalancePriority)
		}
		if pi != pj {
			return pi < pj
		}
		return list[i].label < list[j].label
	})
	v.balances = list
	return nil
}

func pyTitle(s string) string {
	words := strings.Fields(s)
	for i, w := range words {
		r := []rune(strings.ToLower(w))
		if len(r) > 0 {
			r[0] = []rune(strings.ToUpper(string(r[0])))[0]
		}
		words[i] = string(r)
	}
	return strings.Join(words, " ")
}

const leaveColumns = `l.id, l.staff_id, COALESCE(u.name, ''), COALESCE(u.active_role, ''), l.type, l.start_date, l.end_date,
  l.status, COALESCE(cu.name, ''), COALESCE(l.reviewed_by_user_id, ''), l.days, COALESCE(l.days_charged, l.days)`

const leaveFrom = `leave l JOIN staff_profile sp ON sp.id = l.staff_id LEFT JOIN "user" u ON u.id = sp.user_id
LEFT JOIN staff_profile csp ON csp.id = l.covering_staff_id LEFT JOIN "user" cu ON cu.id = csp.user_id`

func scanLeave(row pgx.CollectableRow) (leave, error) {
	var l leave
	err := row.Scan(&l.id, &l.staffID, &l.staffName, &l.staffRole, &l.kind, &l.start, &l.end, &l.status,
		&l.coverName, &l.reviewerID, &l.days, &l.charged)
	return l, err
}

func (s *Service) leaves(ctx context.Context, where string, args ...any) ([]leave, error) {
	rows, err := s.db.Query(ctx, `SELECT `+leaveColumns+` FROM `+leaveFrom+` WHERE `+where, args...)
	if err != nil {
		return nil, fmt.Errorf("personaltimeoff: reading leave: %w", err)
	}
	return pgx.CollectRows(rows, scanLeave)
}

func (s *Service) names(ctx context.Context, v *view, list []leave) error {
	ids := []string{}
	for _, l := range list {
		if l.reviewerID != "" {
			if _, ok := v.reviewers[l.reviewerID]; !ok {
				ids = append(ids, l.reviewerID)
			}
		}
	}
	if len(ids) == 0 {
		return nil
	}
	rows, err := s.db.Query(ctx, `SELECT id, COALESCE(name, '') FROM "user" WHERE id = ANY($1)`, ids)
	if err != nil {
		return fmt.Errorf("personaltimeoff: reading reviewers: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var id, name string
		if err := rows.Scan(&id, &name); err != nil {
			return fmt.Errorf("personaltimeoff: reading reviewers: %w", err)
		}
		v.reviewers[id] = name
	}
	return rows.Err()
}

func (s *Service) readLeaves(ctx context.Context, v *view, staffID string) error {
	list, err := s.leaves(ctx, `l.staff_id = $1 ORDER BY l.created_at DESC`, staffID)
	if err != nil {
		return err
	}
	v.leaves = list
	for _, l := range list {
		if l.status == "pending" {
			v.pendingCount++
		}
		if slices.Contains(rules.PastStatuses, l.status) {
			v.pastCount++
		}
	}
	v.upcomingCount = len(list) - v.pastCount
	return s.names(ctx, v, list)
}

// readCovers is the coverage requests awaiting the reader, and the covers
// running now that the reader holds and that hold the reader's work.
func (s *Service) readCovers(ctx context.Context, v *view, staffID string, now time.Time) error {
	read := func(sql string, args ...any) ([]cover, error) {
		rows, err := s.db.Query(ctx, sql, args...)
		if err != nil {
			return nil, fmt.Errorf("personaltimeoff: reading covers: %w", err)
		}
		return pgx.CollectRows(rows, func(row pgx.CollectableRow) (cover, error) {
			var c cover
			err := row.Scan(&c.name, &c.start, &c.end)
			return c, err
		})
	}
	var err error
	if v.pending, err = read(`SELECT COALESCE(u.name, ''), l.start_date, l.end_date FROM leave l
JOIN staff_profile sp ON sp.id = l.staff_id LEFT JOIN "user" u ON u.id = sp.user_id
WHERE l.covering_staff_id = $1 AND l.coverage_status = 'Awaiting Acceptance' AND l.status = 'pending'`, staffID); err != nil {
		return err
	}
	assignment := `SELECT COALESCE(u.name, ''), COALESCE(l.start_date, ''), COALESCE(l.end_date, '') FROM temporary_coverage_assignment t
JOIN staff_profile sp ON sp.id = t.%s LEFT JOIN "user" u ON u.id = sp.user_id LEFT JOIN leave l ON l.id = t.leave_request_id
WHERE t.%s = $1 AND t.status = 'active' AND t.start_datetime <= $2 AND t.end_datetime >= $2`
	if v.mine, err = read(fmt.Sprintf(assignment, "original_staff_id", "covering_staff_id"), staffID, now); err != nil {
		return err
	}
	if v.delegated, err = read(fmt.Sprintf(assignment, "covering_staff_id", "original_staff_id"), staffID, now); err != nil {
		return err
	}
	return nil
}

func (s *Service) readTeam(ctx context.Context, v *view, staffID string, supervisees []string, now time.Time) error {
	today := v.today.Format(time.DateOnly)
	if len(supervisees) > 0 {
		if err := s.db.QueryRow(ctx, `SELECT count(*) FROM leave WHERE staff_id = ANY($1) AND status = 'approved'
AND start_date <= $2 AND end_date >= $2`, supervisees, today).Scan(&v.teamAway); err != nil {
			return fmt.Errorf("personaltimeoff: counting the team away: %w", err)
		}
	}
	v.teamTotal = len(supervisees) + 1
	if err := s.db.QueryRow(ctx, `SELECT count(*) FROM temporary_coverage_assignment WHERE status = 'active'
AND start_datetime <= $2 AND end_datetime >= $2 AND (original_staff_id = $1 OR covering_staff_id = $1)`, staffID, now).Scan(&v.coverActive); err != nil {
		return fmt.Errorf("personaltimeoff: counting the covers: %w", err)
	}
	rows, err := s.db.Query(ctx, `SELECT start_date, title, block_type FROM calendar_block WHERE is_active AND end_date >= $1
ORDER BY start_date LIMIT 5`, v.today)
	if err != nil {
		return fmt.Errorf("personaltimeoff: reading the calendar blocks: %w", err)
	}
	v.blocks, err = pgx.CollectRows(rows, func(row pgx.CollectableRow) ([3]string, error) {
		var start time.Time
		var b [3]string
		err := row.Scan(&start, &b[1], &b[2])
		b[0] = start.Format("02 Jan")
		return b, err
	})
	if err != nil {
		return fmt.Errorf("personaltimeoff: reading the calendar blocks: %w", err)
	}
	return nil
}

// conflicts is how many of the reader's planned work items sit on a public
// holiday or their own approved leave (day_off_marks).
func (s *Service) conflicts(ctx context.Context, p auth.Principal, staffID string) (int, error) {
	rows, err := s.db.Query(ctx, `
SELECT a.id, a.status, COALESCE(a.responsible_staff_id, ''),
  COALESCE(a.planned_date, (a.scheduled_date AT TIME ZONE 'Africa/Kampala')::date),
  GREATEST(COALESCE(a.planned_date, (a.scheduled_date AT TIME ZONE 'Africa/Kampala')::date), COALESCE(a.end_date, '0001-01-01'::date))
FROM activity a
WHERE a.responsible_staff_id = ANY($1) AND a.status = ANY($2) AND a.deleted_at IS NULL
  AND (a.planned_date >= $3 OR (a.planned_date IS NULL AND (a.scheduled_date AT TIME ZONE 'Africa/Kampala')::date >= $3))`,
		[]string{p.UserID, staffID}, rules.AwaitingDelivery, day(s.now().In(kampala)))
	if err != nil {
		return 0, fmt.Errorf("personaltimeoff: reading the reader's planned work: %w", err)
	}
	work, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (calendarpage.DayOffWork, error) {
		var w calendarpage.DayOffWork
		var start, end *time.Time
		err := row.Scan(&w.ID, &w.Status, &w.StaffID, &start, &end)
		if start != nil {
			w.Start, w.End = *start, *end
		}
		return w, err
	})
	if err != nil {
		return 0, fmt.Errorf("personaltimeoff: reading the reader's planned work: %w", err)
	}
	marks, known, err := calendarpage.DayOffMarks(ctx, s.db, work)
	if err != nil {
		return 0, err
	}
	if !known {
		return 0, errPassOn
	}
	return len(marks), nil
}

// preview is LeaveImpactPreviewService.preview_impact over the latest
// request.
func (s *Service) preview(ctx context.Context, p auth.Principal, staffID string, l leave) (*impact, error) {
	start, err1 := time.Parse(time.DateOnly, l.start)
	end, err2 := time.Parse(time.DateOnly, l.end)
	if err1 != nil || err2 != nil {
		return nil, errPassOn
	}
	im := &impact{start: l.start, end: l.end}
	holidays, err := calendarpage.PublicHolidayDays(ctx, s.db, start, end)
	if err != nil {
		return nil, err
	}
	im.holidays = len(holidays)
	from := time.Date(start.Year(), start.Month(), start.Day(), 0, 0, 0, 0, kampala)
	to := time.Date(end.Year(), end.Month(), end.Day(), 0, 0, 0, 0, kampala).AddDate(0, 0, 1)
	err = s.db.QueryRow(ctx, `SELECT
  (SELECT count(*) FROM activity WHERE responsible_staff_id = ANY($1) AND scheduled_date >= $2 AND scheduled_date < $3
     AND NOT (status IN ('cancelled', 'completed'))),
  EXISTS (SELECT 1 FROM calendar_block WHERE block_type = 'STAFF_CONFERENCE' AND is_active AND start_date <= $5 AND end_date >= $4)`,
		[]string{staffID, p.UserID}, from, to, start, end).Scan(&im.activities, &im.conference)
	if err != nil {
		return nil, fmt.Errorf("personaltimeoff: previewing the impact: %w", err)
	}
	blackout, err := leaveapprovals.BlackoutDays(ctx, s.db, start, end)
	if err != nil {
		return nil, err
	}
	im.blackout = len(blackout)
	return im, nil
}

// readTracker is the team leave tracker: the fifteen newest requests of the
// people the reader's role reads.
func (s *Service) readTracker(ctx context.Context, v *view, staffID, country string, supervisees []string) error {
	var where string
	var args []any
	switch {
	case v.r.Slug == "ADMIN" || v.r.Slug == "HR":
		where = "TRUE"
	case v.r.Slug == "CD":
		where, args = "sp.country IS NOT DISTINCT FROM $1", []any{nullable(country)}
	case len(supervisees) > 0:
		where, args = "l.staff_id = ANY($1)", []any{supervisees}
	default:
		var supervisor string
		err := s.db.QueryRow(ctx, `SELECT supervisor_id FROM staff_supervisor_assignment WHERE supervisee_id = $1 ORDER BY id LIMIT 1`, staffID).Scan(&supervisor)
		switch {
		case errors.Is(err, pgx.ErrNoRows):
			where, args = "l.staff_id = $1", []any{staffID}
		case err != nil:
			return fmt.Errorf("personaltimeoff: reading the supervisor: %w", err)
		default:
			where, args = "l.staff_id IN (SELECT supervisee_id FROM staff_supervisor_assignment WHERE supervisor_id = $1)", []any{supervisor}
		}
	}
	list, err := s.leaves(ctx, where+` ORDER BY l.created_at DESC LIMIT 15`, args...)
	if err != nil {
		return err
	}
	v.tracker = list
	if err := s.names(ctx, v, list); err != nil {
		return err
	}
	v.trackerBalances = map[[2]string]int{}
	if len(list) == 0 {
		return nil
	}
	staff, kinds := []string{}, []string{}
	for _, l := range list {
		staff, kinds = append(staff, l.staffID), append(kinds, l.kind)
	}
	rows, err := s.db.Query(ctx, `SELECT staff_id, leave_type, remaining FROM leave_balance WHERE staff_id = ANY($1)
AND leave_type = ANY($2) AND year = $3 ORDER BY id`, staff, kinds, v.today.Year())
	if err != nil {
		return fmt.Errorf("personaltimeoff: reading the tracker's balances: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var id, kind string
		var remaining int
		if err := rows.Scan(&id, &kind, &remaining); err != nil {
			return fmt.Errorf("personaltimeoff: reading the tracker's balances: %w", err)
		}
		v.trackerBalances[[2]string{id, kind}] = remaining
	}
	return rows.Err()
}

func nullable(s string) any {
	if s == "" {
		return nil
	}
	return s
}

// roundHalfEven is Python's round().
func roundHalfEven(x float64) int { return int(math.RoundToEven(x)) }
