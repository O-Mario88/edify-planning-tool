package targets

import (
	"context"
	"fmt"
	"slices"
	"strings"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// The ledger statuses the rebuild writes.
const (
	validated   = "validated"
	provisional = "provisional"
	reversed    = "reversed"
)

// sourceKey is a ledger row's source: one source credits once per person.
type sourceKey struct{ kind, id string }

// credit is what the rebuild wants a source's row to say.
type credit struct {
	area   string
	day    time.Time
	month  int
	status string
}

// ledgerRow is a stored ledger row as the rebuild compares it.
type ledgerRow struct {
	fy, area, status string
	day              time.Time
	month, quantity  int
	// id and validatedAt are the stored row's, for the ledger sync's writes.
	id          string
	validatedAt *time.Time
}

// sources are the stale people's workflow records of the year, as
// _RebuildSources.for_users reads them.
type sources struct {
	activities map[string][]activityRow // by responsible id
	ssa        map[string][]dayRow      // by collector's id
	mscs       map[string][]dayRow      // by author's account
	ledger     map[string]map[sourceKey]ledgerRow
}

type activityRow struct {
	id, kind, status, salesforceID string
	day                            time.Time
}

type dayRow struct {
	id, status string
	day        time.Time
}

// projectLedger is refresh_many without its writes: for each person whose
// ledger is marked stale, TargetAchievementService._rebuild worked out in
// memory, and their validated quantity a month in each of keys read from
// the result in place of the stored rows. A person whose stored ledger holds
// one source under two areas is handed on: the rebuild keeps whichever row
// it happens to read last.
func (r *Roster) projectLedger(ctx context.Context, db schooldirectory.Querier, people []Person, active map[string]bool, keys []string) error {
	src, err := readSources(ctx, db, people, r.FY)
	if err != nil {
		return err
	}
	for _, p := range people {
		rows, err := rebuilt(p, r.FY, active, src)
		if err != nil {
			return err
		}
		series := Series{}
		for _, row := range rows {
			if row.fy != r.FY || row.status != validated || !slices.Contains(keys, row.area) || row.month < 1 || row.month > 12 {
				continue
			}
			s := series[row.area]
			s[row.month-1] += row.quantity
			series[row.area] = s
		}
		delete(r.ledger, p.UserID)
		if len(series) > 0 {
			r.ledger[p.UserID] = series
		}
	}
	return nil
}

// rebuilt is the person's whole ledger after _rebuild for fy.
func rebuilt(p Person, fy string, active map[string]bool, src sources) ([]ledgerRow, error) {
	pending, seen, err := planLedger(p, fy, active, src)
	if err != nil {
		return nil, err
	}
	existing := src.ledger[p.UserID]
	out := []ledgerRow{}
	for key, row := range existing {
		want, ok := pending[key]
		switch {
		case ok && (row.status != want.status || !row.day.Equal(want.day) || row.fy != fy):
			// The row is moved to this year and rewritten; its area stays.
			row.fy, row.day, row.month, row.status = fy, want.day, want.month, want.status
		case !ok && row.fy == fy && !seen[key] && row.status != reversed:
			row.status = reversed // its source left the workflow
		}
		out = append(out, row)
	}
	for key, want := range pending {
		if _, ok := existing[key]; !ok {
			out = append(out, ledgerRow{fy: fy, area: want.area, status: want.status, day: want.day, month: want.month, quantity: 1})
		}
	}
	return out, nil
}

// planLedger is _rebuild's reading of the person's sources: the credit each
// source in the year wants, and every source it looked at.
func planLedger(p Person, fy string, active map[string]bool, src sources) (map[sourceKey]credit, map[sourceKey]bool, error) {
	ids := []string{p.UserID}
	if p.StaffID != "" {
		ids = append(ids, p.StaffID)
	}
	seen := map[sourceKey]bool{}
	pending := map[sourceKey]credit{}
	upsert := func(area string, key sourceKey, day time.Time, status string) {
		seen[key] = true
		month := MonthOfFY(day, fy)
		if month == 0 || !active[area] {
			return
		}
		pending[key] = credit{area: area, day: day, month: month, status: status}
	}
	for _, s := range rules.Rebuild.Sources {
		switch s.Kind {
		case "activity":
			for _, id := range ids {
				for _, a := range src.activities[id] {
					if !slices.Contains(s.Types, a.kind) {
						continue
					}
					var status string
					switch {
					case slices.Contains(rules.Rebuild.Returned, a.status):
						status = reversed
					case slices.Contains(rules.Rebuild.Completed, a.status):
						status = provisional
						if slices.Contains(rules.Rebuild.IAVerified, a.status) && strings.TrimSpace(a.salesforceID) != "" {
							status = validated
						}
					default:
						continue // scheduled or planned work is not an achievement
					}
					upsert(s.Area, sourceKey{"activity", a.id}, a.day, status)
				}
			}
		case "ssa_record":
			for _, id := range ids {
				for _, rec := range src.ssa[id] {
					status := provisional
					if rec.status == "confirmed" {
						status = validated
					}
					upsert(s.Area, sourceKey{"ssa_record", rec.id}, rec.day, status)
				}
			}
		case "mscs":
			for _, story := range src.mscs[p.UserID] {
				status := reversed
				switch {
				case slices.Contains(rules.Rebuild.MSCSCredited, story.status):
					status = validated
				case slices.Contains(rules.Rebuild.MSCSPending, story.status):
					status = provisional
				}
				upsert(s.Area, sourceKey{"mscs", story.id}, story.day, status)
			}
		default:
			return nil, nil, fmt.Errorf("%w: the rebuild credits an unknown source %q", ErrHandOn, s.Kind)
		}
	}
	return pending, seen, nil
}

// readSources reads the stale people's sources and whole ledgers at once.
func readSources(ctx context.Context, db schooldirectory.Querier, people []Person, fy string) (sources, error) {
	src := sources{activities: map[string][]activityRow{}, ssa: map[string][]dayRow{}, mscs: map[string][]dayRow{},
		ledger: map[string]map[sourceKey]ledgerRow{}}
	users, ids := []string{}, []string{}
	for _, p := range people {
		users = append(users, p.UserID)
		ids = append(ids, p.UserID)
		if p.StaffID != "" {
			ids = append(ids, p.StaffID)
		}
	}
	types := []string{}
	for _, s := range rules.Rebuild.Sources {
		if s.Kind == "activity" {
			types = append(types, s.Types...)
		}
	}
	rows, err := db.Query(ctx, `
SELECT id, responsible_staff_id, activity_type, status, planned_date, coalesce(salesforce_activity_id, '')
FROM activity
WHERE responsible_staff_id = ANY($1) AND fy = $2 AND activity_type = ANY($3) AND deleted_at IS NULL
  AND planned_date IS NOT NULL AND delivery_type IS DISTINCT FROM 'partner'`, ids, fy, types)
	if err != nil {
		return src, fmt.Errorf("targets: reading the rebuild's activities: %w", err)
	}
	for rows.Next() {
		var a activityRow
		var owner string
		if err := rows.Scan(&a.id, &owner, &a.kind, &a.status, &a.day, &a.salesforceID); err != nil {
			rows.Close()
			return src, fmt.Errorf("targets: reading a rebuild activity: %w", err)
		}
		a.day = Day(a.day)
		src.activities[owner] = append(src.activities[owner], a)
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return src, fmt.Errorf("targets: reading the rebuild's activities: %w", err)
	}
	// SSA records are timestamped; the rebuild reads the year's UTC bounds
	// and credits the assessment's UTC day.
	start, end := FYRange(fy)
	if err := readDays(ctx, db, src.ssa, `
SELECT id, collected_by_user_id, verification_status, (date_of_ssa AT TIME ZONE 'UTC')::date
FROM ssa_record
WHERE collected_by_user_id = ANY($1) AND deleted_at IS NULL AND date_of_ssa >= $2 AND date_of_ssa < $3`,
		ids, start, end); err != nil {
		return src, fmt.Errorf("targets: reading the rebuild's SSA records: %w", err)
	}
	if err := readDays(ctx, db, src.mscs, `SELECT id, user_id, status, story_date FROM mscs_story WHERE user_id = ANY($1)`,
		users); err != nil {
		return src, fmt.Errorf("targets: reading the rebuild's stories: %w", err)
	}
	return src, readStoredLedger(ctx, db, users, src.ledger)
}

func readDays(ctx context.Context, db schooldirectory.Querier, into map[string][]dayRow, query string, args ...any) error {
	rows, err := db.Query(ctx, query, args...)
	if err != nil {
		return err
	}
	defer rows.Close()
	for rows.Next() {
		var d dayRow
		var owner string
		if err := rows.Scan(&d.id, &owner, &d.status, &d.day); err != nil {
			return err
		}
		d.day = Day(d.day)
		into[owner] = append(into[owner], d)
	}
	return rows.Err()
}

// readStoredLedger is each person's whole ledger, every year, by source.
func readStoredLedger(ctx context.Context, db schooldirectory.Querier, users []string, into map[string]map[sourceKey]ledgerRow) error {
	rows, err := db.Query(ctx, `
SELECT l.user_id, l.source_type, l.source_id, l.fy, a.key, l.validation_status, l.activity_date, l.credited_month, l.quantity,
  l.id, l.validated_at
FROM target_achievement_ledger l JOIN target_area a ON a.id = l.area_id
WHERE l.user_id = ANY($1)`, users)
	if err != nil {
		return fmt.Errorf("targets: reading the stored ledger: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var user string
		var key sourceKey
		var row ledgerRow
		if err := rows.Scan(&user, &key.kind, &key.id, &row.fy, &row.area, &row.status, &row.day, &row.month, &row.quantity,
			&row.id, &row.validatedAt); err != nil {
			return fmt.Errorf("targets: reading a stored ledger row: %w", err)
		}
		row.day = Day(row.day)
		if into[user] == nil {
			into[user] = map[sourceKey]ledgerRow{}
		}
		if _, twice := into[user][key]; twice {
			return fmt.Errorf("%w: a source is in the ledger under two areas", ErrHandOn)
		}
		into[user][key] = row
	}
	return rows.Err()
}
