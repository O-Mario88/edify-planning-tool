package targets

import (
	"context"
	"errors"
	"fmt"
	"slices"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/calendarpage"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// Person is someone measured: their account and People record.
type Person struct{ UserID, StaffID string }

// Area is PriorityTargetArea: one measured area of one person's year.
type Area struct {
	Key, Label        string
	Weight, SortOrder int
	// Annual is the agreed priority's annual target; nil for a legacy row,
	// whose annual figure is the person's target profile's.
	Annual *int
}

// Series is {area key: twelve monthly figures}.
type Series map[string][12]int

// Roster is the year's figures for a set of people, read once.
type Roster struct {
	FY       string
	areas    map[string][]Area              // by user id
	explicit map[string]map[string][12]*int // user → area → month
	profiles map[string]map[string]int      // staff id → profile column → figure
	ledger   map[string]Series              // user → area → validated quantity a month
	leave    map[string]map[string]bool     // staff id → leave days
	holidays map[string]bool
}

// Prepare reads everyone's year at once. leave is each person's approved
// leave spans by People record, as the page already read them (nil reads
// them here). ErrHandOn when the existing engine would write on this read.
func Prepare(ctx context.Context, db schooldirectory.Querier, people []Person, fy string, leave map[string][][2]time.Time) (*Roster, error) {
	r := &Roster{FY: fy, areas: map[string][]Area{}, explicit: map[string]map[string][12]*int{},
		profiles: map[string]map[string]int{}, ledger: map[string]Series{}, leave: map[string]map[string]bool{}}
	canonical, err := activeAreas(ctx, db)
	if err != nil {
		return nil, err
	}
	stale, err := staleLedgers(ctx, db, people, fy)
	if err != nil {
		return nil, err
	}
	if err := r.readAreas(ctx, db, people, canonical); err != nil {
		return nil, err
	}
	if err := r.readFigures(ctx, db, people); err != nil {
		return nil, err
	}
	if len(stale) > 0 {
		if err := r.projectLedger(ctx, db, stale, canonical, r.areaKeys(people)); err != nil {
			return nil, err
		}
	}
	start, end := FYRange(fy)
	r.holidays, err = calendarpage.PublicHolidayDays(ctx, db, start, end.AddDate(0, 0, -1))
	if err != nil {
		// The national calendar does not cover the year Go would read.
		return nil, fmt.Errorf("%w: %v", ErrHandOn, err)
	}
	if leave == nil {
		if leave, err = readLeave(ctx, db, people); err != nil {
			return nil, err
		}
	}
	for staff, spans := range leave {
		days := map[string]bool{}
		for _, s := range spans {
			for d := s[0]; !d.After(s[1]); d = d.AddDate(0, 0, 1) {
				days[d.Format(time.DateOnly)] = true
			}
		}
		r.leave[staff] = days
	}
	return r, nil
}

// activeAreas is active_target_areas: the active areas' keys. A missing
// official area is repaired on read by the existing engine (ErrHandOn); one
// recorded inactive is an administrator's choice and stays out.
func activeAreas(ctx context.Context, db schooldirectory.Querier) (map[string]bool, error) {
	rows, err := db.Query(ctx, `SELECT key, active FROM target_area`)
	if err != nil {
		return nil, fmt.Errorf("targets: reading the target areas: %w", err)
	}
	defer rows.Close()
	active, known := map[string]bool{}, map[string]bool{}
	for rows.Next() {
		var key string
		var on bool
		if err := rows.Scan(&key, &on); err != nil {
			return nil, fmt.Errorf("targets: reading a target area: %w", err)
		}
		known[key] = true
		if on {
			active[key] = true
		}
	}
	if err := rows.Err(); err != nil {
		return nil, fmt.Errorf("targets: reading the target areas: %w", err)
	}
	for _, key := range rules.OfficialAreas {
		if !active[key] && !known[key] {
			return nil, fmt.Errorf("%w: the official area %s is missing", ErrHandOn, key)
		}
	}
	return active, nil
}

// staleLedgers is refresh_many's question: the people with a mark for the
// year (by account or People record), whose ledger the existing engine
// rebuilds on this read.
func staleLedgers(ctx context.Context, db schooldirectory.Querier, people []Person, fy string) ([]Person, error) {
	owners := []string{}
	for _, p := range people {
		owners = append(owners, p.UserID)
		if p.StaffID != "" {
			owners = append(owners, p.StaffID)
		}
	}
	rows, err := db.Query(ctx, `SELECT DISTINCT owner_id FROM target_ledger_dirty WHERE fy = $1 AND owner_id = ANY($2)`, fy, owners)
	if err != nil {
		return nil, fmt.Errorf("targets: reading the ledger marks: %w", err)
	}
	defer rows.Close()
	marked := map[string]bool{}
	for rows.Next() {
		var owner string
		if err := rows.Scan(&owner); err != nil {
			return nil, fmt.Errorf("targets: reading a ledger mark: %w", err)
		}
		marked[owner] = true
	}
	if err := rows.Err(); err != nil {
		return nil, fmt.Errorf("targets: reading the ledger marks: %w", err)
	}
	stale, seen := []Person{}, map[string]bool{}
	for _, p := range people {
		if (marked[p.UserID] || (p.StaffID != "" && marked[p.StaffID])) && !seen[p.UserID] {
			seen[p.UserID] = true
			stale = append(stale, p)
		}
	}
	return stale, nil
}

// readAreas is priority_target_areas_for_users: the latest agreed review's
// priorities, one per measured area; else the legacy monthly targets' areas
// for a person with no agreement.
func (r *Roster) readAreas(ctx context.Context, db schooldirectory.Querier, people []Person, canonical map[string]bool) error {
	byStaff := map[string]string{}
	staff := []string{}
	for _, p := range people {
		if p.StaffID != "" {
			byStaff[p.StaffID] = p.UserID
			staff = append(staff, p.StaffID)
		}
	}
	rows, err := db.Query(ctx, `
SELECT r.staff_id, p.metric_key, p.target_number, p.outcome_statement, p.weight, p.sequence
FROM (SELECT DISTINCT ON (staff_id) id, staff_id FROM hr_performance_review
      WHERE staff_id = ANY($1) AND fy = $2 AND review_type = $3 AND (stage IS NULL OR stage <> ALL($4))
      ORDER BY staff_id, updated_at DESC) r
LEFT JOIN hr_performance_priority p ON p.review_id = r.id
ORDER BY r.staff_id, p.sequence, p.created_at`, staff, r.FY, rules.AgreementReviewType, rules.UnagreedStages)
	if err != nil {
		return fmt.Errorf("targets: reading the agreed priorities: %w", err)
	}
	defer rows.Close()
	agreed := map[string]bool{}
	seen := map[string]bool{}
	for rows.Next() {
		var staffID string
		var metric, statement *string
		var target, weight, sequence *int
		if err := rows.Scan(&staffID, &metric, &target, &statement, &weight, &sequence); err != nil {
			return fmt.Errorf("targets: reading a priority: %w", err)
		}
		user := byStaff[staffID]
		agreed[user] = true
		if metric == nil && statement == nil && sequence == nil {
			continue // an agreement with no priorities
		}
		key := rules.MetricToArea[deref(metric)]
		annual := 0
		if target != nil {
			annual = *target
		}
		if key == "" || !canonical[key] || seen[user+"\x00"+key] || annual <= 0 {
			continue
		}
		if weight == nil || sequence == nil {
			// The existing arithmetic fails on a missing weight and the
			// page then shows no targets; Go does not guess.
			return fmt.Errorf("%w: a priority has no weight", ErrHandOn)
		}
		seen[user+"\x00"+key] = true
		a := annual
		r.areas[user] = append(r.areas[user], Area{Key: key, Label: deref(statement), Weight: *weight, SortOrder: *sequence, Annual: &a})
	}
	if err := rows.Err(); err != nil {
		return fmt.Errorf("targets: reading the agreed priorities: %w", err)
	}
	legacy := []string{}
	for _, p := range people {
		if p.StaffID != "" && len(r.areas[p.UserID]) == 0 && !agreed[p.UserID] {
			legacy = append(legacy, p.UserID)
		}
	}
	if len(legacy) == 0 {
		return nil
	}
	lrows, err := db.Query(ctx, `
SELECT t.user_id, a.key, a.label, a.weight, a.sort_order
FROM monthly_personal_target t JOIN target_area a ON a.id = t.area_id
WHERE t.user_id = ANY($1) AND t.fy = $2 AND t.target > 0
ORDER BY t.user_id, a.sort_order, t.month_of_fy`, legacy, r.FY)
	if err != nil {
		return fmt.Errorf("targets: reading the legacy targets: %w", err)
	}
	defer lrows.Close()
	for lrows.Next() {
		var user string
		var a Area
		if err := lrows.Scan(&user, &a.Key, &a.Label, &a.Weight, &a.SortOrder); err != nil {
			return fmt.Errorf("targets: reading a legacy target: %w", err)
		}
		if !seen[user+"\x00"+a.Key] {
			seen[user+"\x00"+a.Key] = true
			r.areas[user] = append(r.areas[user], a)
		}
	}
	return lrows.Err()
}

// readFigures reads the explicit monthly targets, the target profiles and
// the validated ledger of everyone's areas.
func (r *Roster) readFigures(ctx context.Context, db schooldirectory.Querier, people []Person) error {
	users, staff, keys := []string{}, []string{}, r.areaKeys(people)
	for _, p := range people {
		users = append(users, p.UserID)
		if p.StaffID != "" {
			staff = append(staff, p.StaffID)
		}
	}
	rows, err := db.Query(ctx, `
SELECT t.user_id, a.key, t.month_of_fy, t.target FROM monthly_personal_target t JOIN target_area a ON a.id = t.area_id
WHERE t.user_id = ANY($1) AND t.fy = $2 AND a.key = ANY($3)`, users, r.FY, keys)
	if err != nil {
		return fmt.Errorf("targets: reading the monthly targets: %w", err)
	}
	for rows.Next() {
		var user, key string
		var month, target int
		if err := rows.Scan(&user, &key, &month, &target); err != nil {
			rows.Close()
			return fmt.Errorf("targets: reading a monthly target: %w", err)
		}
		if r.explicit[user] == nil {
			r.explicit[user] = map[string][12]*int{}
		}
		months := r.explicit[user][key]
		if month >= 1 && month <= 12 {
			t := target
			months[month-1] = &t
		}
		r.explicit[user][key] = months
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return fmt.Errorf("targets: reading the monthly targets: %w", err)
	}
	prow, err := db.Query(ctx, `
SELECT staff_id, visits_target, trainings_target, group_trainings_target, cluster_meetings_target, ssa_target
FROM staff_target_profile WHERE staff_id = ANY($1) AND fy = $2`, staff, r.FY)
	if err != nil {
		return fmt.Errorf("targets: reading the target profiles: %w", err)
	}
	for prow.Next() {
		var id string
		var v, t, g, c, s int
		if err := prow.Scan(&id, &v, &t, &g, &c, &s); err != nil {
			prow.Close()
			return fmt.Errorf("targets: reading a target profile: %w", err)
		}
		r.profiles[id] = map[string]int{"visits_target": v, "trainings_target": t, "group_trainings_target": g,
			"cluster_meetings_target": c, "ssa_target": s}
	}
	prow.Close()
	if err := prow.Err(); err != nil {
		return fmt.Errorf("targets: reading the target profiles: %w", err)
	}
	lrow, err := db.Query(ctx, `
SELECT l.user_id, a.key, l.credited_month, l.quantity FROM target_achievement_ledger l JOIN target_area a ON a.id = l.area_id
WHERE l.user_id = ANY($1) AND l.fy = $2 AND l.validation_status = 'validated' AND a.key = ANY($3)`, users, r.FY, keys)
	if err != nil {
		return fmt.Errorf("targets: reading the ledger: %w", err)
	}
	defer lrow.Close()
	for lrow.Next() {
		var user, key string
		var month, quantity int
		if err := lrow.Scan(&user, &key, &month, &quantity); err != nil {
			return fmt.Errorf("targets: reading a ledger row: %w", err)
		}
		if month < 1 || month > 12 {
			continue
		}
		if r.ledger[user] == nil {
			r.ledger[user] = Series{}
		}
		s := r.ledger[user][key]
		s[month-1] += quantity
		r.ledger[user][key] = s
	}
	return lrow.Err()
}

// areaKeys are the areas anyone of people is measured on.
func (r *Roster) areaKeys(people []Person) []string {
	keys := []string{}
	for _, p := range people {
		for _, a := range r.areas[p.UserID] {
			if !slices.Contains(keys, a.Key) {
				keys = append(keys, a.Key)
			}
		}
	}
	return keys
}

// readLeave is each person's approved leave spans (start and end as ISO
// days; a span that does not read is left out).
func readLeave(ctx context.Context, db schooldirectory.Querier, people []Person) (map[string][][2]time.Time, error) {
	staff := []string{}
	for _, p := range people {
		if p.StaffID != "" {
			staff = append(staff, p.StaffID)
		}
	}
	rows, err := db.Query(ctx, `SELECT staff_id, start_date::text, end_date::text FROM leave WHERE status = 'approved' AND staff_id = ANY($1)`, staff)
	if err != nil {
		return nil, fmt.Errorf("targets: reading the approved leave: %w", err)
	}
	defer rows.Close()
	out := map[string][][2]time.Time{}
	for rows.Next() {
		var id string
		var start, end *string
		if err := rows.Scan(&id, &start, &end); err != nil {
			return nil, fmt.Errorf("targets: reading a leave: %w", err)
		}
		if s, e, ok := Span(deref(start), deref(end)); ok {
			out[id] = append(out[id], [2]time.Time{s, e})
		}
	}
	return out, rows.Err()
}

// Span reads a leave's start and end as the roster does (their first ten
// characters as ISO days); false when either does not read.
func Span(start, end string) (time.Time, time.Time, bool) {
	s, err1 := time.Parse(time.DateOnly, first10(start))
	e, err2 := time.Parse(time.DateOnly, first10(end))
	if errors.Join(err1, err2) != nil {
		return time.Time{}, time.Time{}, false
	}
	return s, e, true
}

func first10(s string) string {
	if len(s) > 10 {
		return s[:10]
	}
	return s
}

func deref(s *string) string {
	if s == nil {
		return ""
	}
	return *s
}
