package planningmonitor

import (
	"context"
	"errors"
	"fmt"
	"sort"
	"strconv"
	"time"

	"github.com/jackc/pgx/v5"

	registry "github.com/O-Mario88/edify-planning-tool/platform/backend/internal/country"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// Country Execution's period snapshots (country_execution.snapshots): each
// recently ended week, month, quarter and year is locked once, with the
// figures the page reads for the whole country as of the day after the
// period's last day.

// snapshotGraceDays is GRACE_DAYS: how long after a period ends its closing
// snapshot may still be taken.
func snapshotGraceDays() int { return rules.CountryExecution.Snapshots.GraceDays }

// SnapshotWindow is one period a snapshot locks.
type SnapshotWindow struct{ w cpoWindow }

// FY, Period, Start, End (exclusive) and Label are the period's.
func (s SnapshotWindow) FY() string       { return s.w.fy }
func (s SnapshotWindow) Period() string   { return s.w.period }
func (s SnapshotWindow) Start() time.Time { return s.w.start }
func (s SnapshotWindow) End() time.Time   { return s.w.end }
func (s SnapshotWindow) Label() string    { return s.w.label() }

// operationalFYOf is get_operational_fy for a day.
func operationalFYOf(d time.Time) string {
	if d.Month() >= time.October {
		return strconv.Itoa(d.Year() + 1)
	}
	return strconv.Itoa(d.Year())
}

// quarterOfDay is get_quarter_for_date.
func quarterOfDay(d time.Time) string {
	switch {
	case d.Month() >= time.October:
		return "Q1"
	case d.Month() <= time.March:
		return "Q2"
	case d.Month() <= time.June:
		return "Q3"
	}
	return "Q4"
}

// endedWindows is ended_windows: the most recently ended week (Monday to
// Sunday), month, quarter and financial year, for today (a day at UTC
// midnight).
func endedWindows(today time.Time) []cpoWindow {
	monday := today.AddDate(0, 0, -((int(today.Weekday()) + 6) % 7))
	lastWeek := monday.AddDate(0, 0, -7)
	out := []cpoWindow{cpoWindowFor(operationalFYOf(lastWeek), "week", "", 0, &lastWeek)}
	lastMonthDay := date(today.Year(), today.Month(), 1).AddDate(0, 0, -1)
	out = append(out, cpoWindowFor(operationalFYOf(lastMonthDay), "month", "", int(lastMonthDay.Month()), nil))
	this := cpoWindowFor(operationalFYOf(today), "quarter", quarterOfDay(today), 0, nil)
	before := this.start.AddDate(0, 0, -1)
	out = append(out, cpoWindowFor(operationalFYOf(before), "quarter", quarterOfDay(before), 0, nil))
	n, _ := strconv.Atoi(operationalFYOf(today))
	return append(out, cpoWindowFor(strconv.Itoa(n-1), "fy", "", 0, nil))
}

// DueSnapshotWindows is due_windows: the ended periods still close enough
// to their end to be locked.
func DueSnapshotWindows(today time.Time) []SnapshotWindow {
	out := []SnapshotWindow{}
	for _, w := range endedWindows(today) {
		if !w.end.After(today) && int(today.Sub(w.end).Hours()/24) <= snapshotGraceDays() {
			out = append(out, SnapshotWindow{w})
		}
	}
	return out
}

// SnapshotCountries are lock_ended_periods' countries (warm_targets): each
// country an active Country Director or Impact Assessment officer reads.
func SnapshotCountries(ctx context.Context, db schooldirectory.Querier) ([]string, error) {
	roles := rules.CountryExecution.Snapshots.CountryRoles
	rows, err := db.Query(ctx, `SELECT DISTINCT btrim(COALESCE(sp.country, '')) FROM staff_profile sp JOIN "user" u ON u.id = sp.user_id
WHERE (u.active_role = ANY($1) OR COALESCE(u.roles, '{}') && $1::varchar[]) AND sp.deleted_at IS NULL AND u.is_active AND u.deleted_at IS NULL
ORDER BY 1`, roles)
	if err != nil {
		return nil, fmt.Errorf("planningmonitor: the snapshot countries: %w", err)
	}
	defer rows.Close()
	out := []string{}
	for rows.Next() {
		var c string
		if err := rows.Scan(&c); err != nil {
			return nil, err
		}
		if c != "" {
			out = append(out, c)
		}
	}
	return out, rows.Err()
}

// SnapshotLocked is whether the period already has a snapshot (latest).
func SnapshotLocked(ctx context.Context, db schooldirectory.Querier, country string, w SnapshotWindow) (bool, error) {
	var locked bool
	err := db.QueryRow(ctx, `SELECT EXISTS (SELECT 1 FROM execution_period_snapshot WHERE country = $1 AND period_type = $2 AND period_start = $3::date)`,
		country, w.w.period, w.w.start).Scan(&locked)
	if err != nil {
		return false, fmt.Errorf("planningmonitor: the period's snapshot: %w", err)
	}
	return locked, nil
}

// PeriodSnapshot is _read: a period's figures for the whole country, as of
// the day after it ended.
type PeriodSnapshot struct {
	AsOf        time.Time
	StagePolicy string
	Figures     map[string]any
	Channels    map[string]any
	Hierarchy   []map[string]any
	FollowUps   []map[string]any
}

// ReadPeriodSnapshot is _read for the country's window; liveDay is the day
// the required slots are read on (the planning fold reads them as of
// timezone.localdate(), whatever day the close is asked for).
func ReadPeriodSnapshot(ctx context.Context, db schooldirectory.Querier, country string, sw SnapshotWindow, liveDay time.Time) (PeriodSnapshot, error) {
	w := sw.w
	scope, err := systemScopeOf(ctx, db, country)
	if err != nil {
		return PeriodSnapshot{}, err
	}
	asOf := w.end
	d, err := buildCEXDataset(ctx, db, scope, w, asOf)
	if err != nil {
		return PeriodSnapshot{}, err
	}
	roster, err := cexRosterOf(ctx, db, scope)
	if err != nil {
		return PeriodSnapshot{}, err
	}
	f := cexFilters{fy: w.fy, period: w.period, quarter: w.quarter, month: w.month, week: w.week}
	tree := cexFold(d, roster, f)
	figures := namedFigures(tree.country)
	in := d.integrity
	tracked := in.tracked
	orNil := func(v int) any {
		if tracked {
			return v
		}
		return nil
	}
	due, verified := tree.country.n("due"), tree.country.n("verified")
	schools := map[string]bool{}
	for _, r := range d.records {
		if r.schoolID != "" && !r.cancelled {
			schools[r.schoolID] = true
		}
	}
	figures["original_plan"], figures["added"] = orNil(in.original), orNil(in.added)
	figures["rescheduled_in"], figures["rescheduled_out"] = orNil(in.movedIn), orNil(in.movedOut)
	figures["plan_cancelled"], figures["current_plan"] = orNil(in.cancelled), due
	figures["carryover"], figures["plan_tracked"] = max(0, due-verified), tracked
	figures["unique_schools"] = len(schools)
	slots, err := periodSlots(ctx, db, scope, f, liveDay)
	if err != nil {
		return PeriodSnapshot{}, err
	}
	figures["slots"] = slots
	followUps, err := openExecutionFollowUps(ctx, db, country)
	if err != nil {
		return PeriodSnapshot{}, err
	}
	return PeriodSnapshot{AsOf: asOf, StagePolicy: rules.CountryExecution.Stages.Policy, Figures: figures,
		Channels:  map[string]any{"staff": namedFigures(tree.staff), "partner": namedFigures(tree.partner)},
		Hierarchy: snapshotHierarchy(tree, d.partnerName), FollowUps: followUps}, nil
}

// namedFigures is _named: the figures a snapshot keeps of a row.
func namedFigures(t cexTally) map[string]any {
	out := map[string]any{}
	for _, name := range rules.CountryExecution.Snapshots.RowFigures {
		out[name] = t.n(name)
	}
	return out
}

// snapshotHierarchy is _read's hierarchy: each Lead, the officers with any
// work due, cancelled or carried forward, and each officer's delivery
// channels by key.
func snapshotHierarchy(tree *cexTree, partnerNames map[string]string) []map[string]any {
	out := []map[string]any{}
	for _, l := range tree.leads {
		owners := []map[string]any{}
		for _, o := range l.owners {
			if o.tally.n("due") == 0 && o.tally.n("cancelled") == 0 && o.tally.n("carried_forward") == 0 {
				continue
			}
			keys := make([]string, 0, len(o.partners))
			for k := range o.partners {
				keys = append(keys, k)
			}
			sort.Strings(keys)
			partners := []map[string]any{}
			for _, k := range keys {
				name := rules.CountryExecution.Snapshots.StaffDelivery
				if k != rules.CountryExecution.StaffKey {
					name = partnerNames[k]
					if name == "" {
						name = rules.CountryExecution.Snapshots.UnrecordedPartner
					}
				}
				partners = append(partners, map[string]any{"key": k, "name": name, "figures": namedFigures(o.partners[k])})
			}
			owners = append(owners, map[string]any{"key": o.key, "name": o.label(), "kind": o.kind,
				"figures": namedFigures(o.tally), "partners": partners})
		}
		out = append(out, map[string]any{"key": l.key, "name": l.name, "figures": namedFigures(l.tally), "owners": owners})
	}
	return out
}

// periodSlots is _slots: required-slot completion for the period from the
// planning fold (a week has no phased requirement).
func periodSlots(ctx context.Context, db schooldirectory.Querier, scope schooldirectory.Scope, f cexFilters, today time.Time) (any, error) {
	if f.period == "week" {
		return nil, nil
	}
	plan, err := buildCPOSnapshot(ctx, db, scope, f.planning(), today)
	if err != nil {
		return nil, err
	}
	t := cpoTally(plan.tree.country)
	visits := t.n("staff_verified") + t.n("partner_verified")
	return map[string]any{
		"visit_slots": t.n("visit_slots"), "visits_verified": visits,
		"training_slots": t.n("training_slots"), "trainings_verified": t.n("training_verified"),
		"remaining": max(0, t.n("visit_slots")-visits) + max(0, t.n("training_slots")-t.n("training_verified")),
	}, nil
}

// openExecutionFollowUps is _open_follow_ups: the country's open execution
// follow-ups, oldest first, five hundred at most.
func openExecutionFollowUps(ctx context.Context, db schooldirectory.Querier, country string) ([]map[string]any, error) {
	rows, err := db.Query(ctx, `SELECT id, COALESCE(issue_type, ''), COALESCE(program_lead_name, ''), COALESCE(cceo_name, ''),
  COALESCE(partner_name, ''), COALESCE(activity_label, ''), COALESCE(status, ''), remaining_value, assigned_at, due_date
FROM planning_oversight_follow_up WHERE module = 'execution' AND status = ANY($1) AND country = $2
ORDER BY assigned_at, id LIMIT 500`, rules.CountryExecution.FollowUps.OpenStates, country)
	if err != nil {
		return nil, fmt.Errorf("planningmonitor: the open execution follow-ups: %w", err)
	}
	defer rows.Close()
	out := []map[string]any{}
	for rows.Next() {
		var id, issue, lead, cceo, partner, activity, status string
		var open *int
		var sent *time.Time
		var due *time.Time
		if err := rows.Scan(&id, &issue, &lead, &cceo, &partner, &activity, &status, &open, &sent, &due); err != nil {
			return nil, err
		}
		row := map[string]any{"id": id, "issue": issue, "lead": lead, "cceo": cceo, "partner": partner,
			"activity": activity, "status": status, "open": open, "sent": "", "due": ""}
		if sent != nil {
			row["sent"] = sent.In(cpoLocation).Format(time.DateOnly)
		}
		if due != nil {
			row["due"] = due.Format(time.DateOnly)
		}
		out = append(out, row)
	}
	return out, rows.Err()
}

// LockSnapshot writes one period's original snapshot; it answers false when
// the period was locked meanwhile.
type LockSnapshot func(ctx context.Context, country string, w SnapshotWindow, s PeriodSnapshot) (bool, error)

// LockEndedPeriods is lock_ended_periods: every recently ended period not yet
// locked, for each country the oversight is read in, as of today (a day at
// UTC midnight; liveDay is the application's own day, which the required
// slots are read on). The first failure is returned once the rest are done.
func LockEndedPeriods(ctx context.Context, db schooldirectory.Querier, lock LockSnapshot, today, liveDay time.Time) (int, error) {
	countries, err := SnapshotCountries(ctx, db)
	if err != nil {
		return 0, err
	}
	locked := 0
	var failed error
	for _, country := range countries {
		for _, w := range DueSnapshotWindows(today) {
			done, err := SnapshotLocked(ctx, db, country, w)
			if err != nil {
				return locked, err
			}
			if done {
				continue
			}
			s, err := ReadPeriodSnapshot(ctx, db, country, w, liveDay)
			if err == nil {
				var wrote bool
				if wrote, err = lock(ctx, country, w, s); err == nil && wrote {
					locked++
				}
			}
			if err != nil && failed == nil {
				failed = fmt.Errorf("planningmonitor: locking %s %s: %w", country, w.Label(), err)
			}
		}
	}
	return locked, failed
}

// systemScopeOf is system_scope(country): the whole of one country as the
// system reads it, bounded by the country's registry id (the name's alias)
// as a Country Director's scope is, its roster the registry's only where the
// country's roles come from there.
func systemScopeOf(ctx context.Context, db schooldirectory.Querier, country string) (schooldirectory.Scope, error) {
	var id string
	var fromRegistry bool
	err := db.QueryRow(ctx, `SELECT al.country_id::text, c.roles_source = $2 FROM country_registry.country_alias al
JOIN country_registry.country c ON c.id = al.country_id WHERE al.alias = $1 ORDER BY al.country_id LIMIT 1`,
		country, registry.RolesFromRegistry).Scan(&id, &fromRegistry)
	if errors.Is(err, pgx.ErrNoRows) {
		return schooldirectory.Scope{}, fmt.Errorf("planningmonitor: %q names no registered country", country)
	}
	if err != nil {
		return schooldirectory.Scope{}, fmt.Errorf("planningmonitor: the country's registry id: %w", err)
	}
	return schooldirectory.Scope{Role: "CountryDirector", UserID: "system", CountryScope: true, Country: country,
		CountryID: id, CountryFromRegistry: fromRegistry}, nil
}
