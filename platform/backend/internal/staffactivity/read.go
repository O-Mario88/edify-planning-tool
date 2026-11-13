package staffactivity

import (
	"context"
	"errors"
	"fmt"
	"time"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// errPassOn is a reader the page cannot be answered for exactly; the
// existing application answers them.
var errPassOn = errors.New("staffactivity: passed to the existing application")

// account is one row of _people's user read.
type account struct {
	id, email, role    string
	name, path, action *string
	lastSeen           *time.Time
	loginID, profileID *string
	districtID         *string
}

// signins are a person's sign-ins in the period, and the sessions active in
// it.
type signins struct {
	n                      int
	first, last            *time.Time
	sessionFirst, sessLast *time.Time
}

// acted is meaningful_action_counts for one person.
type acted struct {
	done, failed int
	schools      map[string]bool
	lastLabel    string
	lastAt       *time.Time
}

// collect runs a statement and hands each row to scan.
func collect(ctx context.Context, db schooldirectory.Querier, what, sql string, scan func(pgx.Rows) error, args ...any) error {
	rows, err := db.Query(ctx, sql, args...)
	if err != nil {
		return fmt.Errorf("staffactivity: reading %s: %w", what, err)
	}
	defer rows.Close()
	for rows.Next() {
		if err := scan(rows); err != nil {
			return fmt.Errorf("staffactivity: reading %s: %w", what, err)
		}
	}
	if err := rows.Err(); err != nil {
		return fmt.Errorf("staffactivity: reading %s: %w", what, err)
	}
	return nil
}

func str(s *string) string {
	if s == nil {
		return ""
	}
	return *s
}

// readerCountry is the reader's live staff profile's country (the first by
// id), as country_roster_ids reads it.
func readerCountry(ctx context.Context, db schooldirectory.Querier, userID string) (string, error) {
	var country *string
	err := db.QueryRow(ctx, `SELECT country FROM staff_profile WHERE deleted_at IS NULL AND user_id = $1 ORDER BY id ASC LIMIT 1`, userID).Scan(&country)
	if errors.Is(err, pgx.ErrNoRows) {
		return "", nil
	}
	if err != nil {
		return "", fmt.Errorf("staffactivity: reading the reader's country: %w", err)
	}
	return str(country), nil
}

// countryRoster is country_roster_ids: every active CCEO and Programme Lead
// in the reader's country (every one when the reader has none), the reader
// left out.
func countryRoster(ctx context.Context, db schooldirectory.Querier, userID, country string) ([]string, error) {
	ids := []string{}
	sql := `SELECT u.id FROM "user" u WHERE u.active_role = ANY($1) AND u.deleted_at IS NULL AND u.is_active ORDER BY u.created_at DESC`
	args := []any{rules.InternalRoles}
	if country != "" {
		sql = `SELECT u.id FROM "user" u INNER JOIN staff_profile sp ON (u.id = sp.user_id)
WHERE u.active_role = ANY($1) AND u.deleted_at IS NULL AND u.is_active AND sp.country = $2 ORDER BY u.created_at DESC`
		args = append(args, country)
	}
	seen := map[string]bool{}
	err := collect(ctx, db, "the roster", sql, func(r pgx.Rows) error {
		var id string
		if err := r.Scan(&id); err != nil {
			return err
		}
		if id != userID && !seen[id] {
			seen[id] = true
			ids = append(ids, id)
		}
		return nil
	}, args...)
	return ids, err
}

func readAccounts(ctx context.Context, db schooldirectory.Querier, ids []string) ([]account, error) {
	out := []account{}
	err := collect(ctx, db, "the people", `
SELECT u.id, u.name, u.email, u.active_role, u.last_seen_at, u.last_seen_path, u.last_seen_action, u.last_seen_login_id,
       sp.id, sp.primary_district_id
FROM "user" u LEFT OUTER JOIN staff_profile sp ON (u.id = sp.user_id)
WHERE u.deleted_at IS NULL AND u.id = ANY($1) AND u.is_active
ORDER BY u.created_at DESC`, func(r pgx.Rows) error {
		var a account
		var role *string
		if err := r.Scan(&a.id, &a.name, &a.email, &role, &a.lastSeen, &a.path, &a.action, &a.loginID, &a.profileID, &a.districtID); err != nil {
			return err
		}
		a.role = str(role)
		out = append(out, a)
		return nil
	}, ids)
	return out, err
}

func readSignins(ctx context.Context, db schooldirectory.Querier, ids []string, start, end time.Time) (map[string]*signins, error) {
	out := map[string]*signins{}
	get := func(id string) *signins {
		if out[id] == nil {
			out[id] = &signins{}
		}
		return out[id]
	}
	err := collect(ctx, db, "the sign-ins", `
SELECT user_id, COUNT(id), MIN(at), MAX(at) FROM login_event
WHERE at >= $1 AND at < $2 AND user_id = ANY($3) GROUP BY 1`, func(r pgx.Rows) error {
		var id string
		var n int
		var first, last *time.Time
		if err := r.Scan(&id, &n, &first, &last); err != nil {
			return err
		}
		s := get(id)
		s.n, s.first, s.last = n, first, last
		return nil
	}, start, end, ids)
	if err != nil {
		return nil, err
	}
	err = collect(ctx, db, "the sessions", `
SELECT user_id, MIN(at), MAX(last_active_at) FROM login_event
WHERE at < $2 AND last_active_at >= $1 AND user_id = ANY($3) GROUP BY 1`, func(r pgx.Rows) error {
		var id string
		var first, last *time.Time
		if err := r.Scan(&id, &first, &last); err != nil {
			return err
		}
		s := get(id)
		s.sessionFirst, s.sessLast = first, last
		return nil
	}, start, end, ids)
	return out, err
}

// spent is a person's active time by part of the platform, in the order the
// statement returns the parts.
type spent struct {
	seconds  int64
	sections []string
	by       map[string]int64
}

func (s *spent) add(section string, seconds int64) {
	if s.by == nil {
		s.by = map[string]int64{}
	}
	if _, ok := s.by[section]; !ok {
		s.sections = append(s.sections, section)
	}
	s.by[section] += seconds
}

func readSpent(ctx context.Context, db schooldirectory.Querier, ids []string, p period) (map[string]*spent, error) {
	out := map[string]*spent{}
	err := collect(ctx, db, "the active time", `
SELECT user_id, section, SUM(seconds) FROM presence_time
WHERE day >= $1 AND day <= $2 AND user_id = ANY($3) GROUP BY 1, 2`, func(r pgx.Rows) error {
		var id, section string
		var total *int64
		if err := r.Scan(&id, &section, &total); err != nil {
			return err
		}
		s := out[id]
		if s == nil {
			s = &spent{}
			out[id] = s
		}
		var t int64
		if total != nil {
			t = *total
		}
		s.seconds += t
		s.add(section, t)
		return nil
	}, p.start, p.end, ids)
	return out, err
}

// identities is actor_identities: every id the audit chain may hold for
// these people (their user ids, and every staff profile of theirs), and
// whose it is.
func identities(ctx context.Context, db schooldirectory.Querier, ids []string) (map[string]string, error) {
	owners := map[string]string{}
	for _, id := range ids {
		owners[id] = id
	}
	err := collect(ctx, db, "the staff profiles", `SELECT id, user_id FROM staff_profile WHERE user_id = ANY($1)`, func(r pgx.Rows) error {
		var id string
		var user *string
		if err := r.Scan(&id, &user); err != nil {
			return err
		}
		if _, ok := owners[id]; !ok && user != nil {
			owners[id] = *user
		}
		return nil
	}, ids)
	return owners, err
}

// actKey is services._act_key: the request and the record an audit row is
// about; a row with no request stands alone.
const actKey = `COALESCE(NULLIF(correlation_id, ''), id) || '|' || COALESCE(subject_kind, '') || '|' || COALESCE(subject_id, '')`

// readActions is meaningful_action_counts. A school named only in an audit
// row's payload (a hand-over, a withdrawal) is not the gateway's to read:
// such a row passes the reader on.
func readActions(ctx context.Context, db schooldirectory.Querier, ids []string, start, end time.Time) (map[string]*acted, error) {
	owners, err := identities(ctx, db, ids)
	if err != nil {
		return nil, err
	}
	actors := make([]string, 0, len(owners))
	for id := range owners {
		actors = append(actors, id)
	}
	all, plain, schoolKeys := meaningfulKeys()
	out := map[string]*acted{}
	get := func(actor string) *acted {
		person := owners[actor]
		if out[person] == nil {
			out[person] = &acted{schools: map[string]bool{}}
		}
		return out[person]
	}
	const base = `FROM audit_log WHERE actor_id = ANY($1) AND created_at >= $2 AND created_at < $3`
	err = collect(ctx, db, "the actions", `
SELECT actor_id, COUNT(DISTINCT (`+actKey+`)) FILTER (WHERE action = ANY($4) AND success), COUNT(id) FILTER (WHERE NOT success)
`+base+` AND (action = ANY($4) OR action = ANY($5)) GROUP BY actor_id`, func(r pgx.Rows) error {
		var actor string
		var done, failed int
		if err := r.Scan(&actor, &done, &failed); err != nil {
			return err
		}
		a := get(actor)
		a.done += done
		a.failed += failed
		return nil
	}, actors, start, end, all, rules.FailedRequestActions)
	if err != nil {
		return nil, err
	}

	named := append(append([]string{}, rules.SchoolSubjects...), rules.ActivitySubjects...)
	var unnamed bool
	if err := db.QueryRow(ctx, `SELECT EXISTS (SELECT 1 `+base+` AND action = ANY($4) AND success
AND (subject_kind IS NULL OR NOT subject_kind = ANY($5)))`, actors, start, end, schoolKeys, named).Scan(&unnamed); err != nil {
		return nil, fmt.Errorf("staffactivity: reading the actions' records: %w", err)
	}
	if unnamed {
		return nil, errPassOn
	}
	addSchool := func(r pgx.Rows) error {
		var actor string
		var school *string
		if err := r.Scan(&actor, &school); err != nil {
			return err
		}
		if school != nil && *school != "" {
			get(actor).schools[*school] = true
		}
		return nil
	}
	if err := collect(ctx, db, "the schools acted on", `SELECT DISTINCT actor_id, subject_id `+base+`
AND action = ANY($4) AND success AND subject_kind = ANY($5)`, addSchool, actors, start, end, schoolKeys, rules.SchoolSubjects); err != nil {
		return nil, err
	}
	if err := collect(ctx, db, "the activities acted on", `SELECT DISTINCT a.actor_id,
  (SELECT u0.school_id FROM activity u0 WHERE u0.id = a.subject_id ORDER BY u0.created_at DESC LIMIT 1)
FROM audit_log a WHERE a.actor_id = ANY($1) AND a.created_at >= $2 AND a.created_at < $3
AND a.action = ANY($4) AND a.success AND a.subject_kind = ANY($5)`, addSchool, actors, start, end, schoolKeys, rules.ActivitySubjects); err != nil {
		return nil, err
	}

	type row struct {
		actor, action string
		at            time.Time
		correlation   *string
		subject       *string
	}
	newest := func(keys []string) (map[string]row, error) {
		found := map[string]row{}
		err := collect(ctx, db, "the latest actions", `
SELECT DISTINCT ON (actor_id) actor_id, action, created_at, correlation_id, subject_id `+base+`
AND action = ANY($4) AND success ORDER BY actor_id ASC, created_at DESC`, func(r pgx.Rows) error {
			var x row
			if err := r.Scan(&x.actor, &x.action, &x.at, &x.correlation, &x.subject); err != nil {
				return err
			}
			person := owners[x.actor]
			if prev, ok := found[person]; !ok || x.at.After(prev.at) {
				found[person] = x
			}
			return nil
		}, actors, start, end, keys)
		return found, err
	}
	latest, err := newest(all)
	if err != nil {
		return nil, err
	}
	namedBy, err := newest(plain)
	if err != nil {
		return nil, err
	}
	for person, x := range latest {
		action := x.action
		if other, ok := namedBy[person]; ok && str(x.correlation) != "" &&
			str(other.correlation) == str(x.correlation) && equalPtr(other.subject, x.subject) {
			action = other.action
		}
		if out[person] == nil {
			out[person] = &acted{schools: map[string]bool{}}
		}
		at := x.at
		out[person].lastLabel = rules.MeaningfulActions[action].Label
		out[person].lastAt = &at
	}
	return out, nil
}

func equalPtr(a, b *string) bool {
	if a == nil || b == nil {
		return a == nil && b == nil
	}
	return *a == *b
}

// supervisorNames is _supervisor_names: each person's first reporting line
// to a manager, by the manager's name.
func supervisorNames(ctx context.Context, db schooldirectory.Querier, ids []string) (map[string]string, error) {
	out := map[string]string{}
	err := collect(ctx, db, "the supervisors", `
SELECT sp.user_id, su.name FROM staff_supervisor_assignment a
INNER JOIN staff_profile sp ON (a.supervisee_id = sp.id)
INNER JOIN staff_profile sv ON (a.supervisor_id = sv.id)
INNER JOIN "user" su ON (sv.user_id = su.id)
WHERE sp.deleted_at IS NULL AND sp.user_id = ANY($1) AND sv.deleted_at IS NULL AND su.active_role = ANY($2)
ORDER BY 2 ASC`, func(r pgx.Rows) error {
		var user, name *string
		if err := r.Scan(&user, &name); err != nil {
			return err
		}
		if user == nil {
			return nil
		}
		if _, ok := out[*user]; !ok {
			out[*user] = str(name)
		}
		return nil
	}, ids, rules.SupervisorRoles)
	return out, err
}

// lead is a person's Programme Lead.
type lead struct{ id, name string }

// programLeads is presence._program_lead_of: supervisee user → Programme
// Lead user and the Leads' names, from the direct reporting lines. A person
// with two Leads of one name is ordered by nothing the page fixes; the
// reader is passed on.
func programLeads(ctx context.Context, db schooldirectory.Querier) (map[string]string, map[string]string, error) {
	leadOf, names := map[string]string{}, map[string]string{}
	firstName := map[string]string{}
	ambiguous := false
	err := collect(ctx, db, "the Programme Leads", `
SELECT sve.user_id, sp.user_id, u.name FROM staff_supervisor_assignment a
INNER JOIN staff_profile sp ON (a.supervisor_id = sp.id)
INNER JOIN "user" u ON (sp.user_id = u.id)
INNER JOIN staff_profile sve ON (a.supervisee_id = sve.id)
WHERE (u.active_role = $1 OR u.roles @> (ARRAY[$1])::varchar(64)[]) AND sve.deleted_at IS NULL AND sp.deleted_at IS NULL
ORDER BY 3 ASC`, func(r pgx.Rows) error {
		var who, pl *string
		var name *string
		if err := r.Scan(&who, &pl, &name); err != nil {
			return err
		}
		if who == nil || pl == nil {
			return nil
		}
		if have, ok := leadOf[*who]; !ok {
			leadOf[*who] = *pl
			firstName[*who] = str(name)
		} else if have != *pl && firstName[*who] == str(name) {
			ambiguous = true
		}
		names[*pl] = str(name)
		return nil
	}, rules.Roles.ProgramLead)
	if err == nil && ambiguous {
		err = errPassOn
	}
	return leadOf, names, err
}

func regions(ctx context.Context, db schooldirectory.Querier, districts []string) (map[string]string, error) {
	out := map[string]string{}
	err := collect(ctx, db, "the regions", `
SELECT d.id, r.name FROM district d LEFT OUTER JOIN region r ON (d.region_id = r.id) WHERE d.id = ANY($1)`, func(r pgx.Rows) error {
		var id string
		var name *string
		if err := r.Scan(&id, &name); err != nil {
			return err
		}
		out[id] = str(name)
		return nil
	}, districts)
	return out, err
}

// leaveDays is _leave_days: approved leave days per staff profile; a span
// that does not parse is skipped.
func leaveDays(ctx context.Context, db schooldirectory.Querier, profiles []string) (map[string]map[time.Time]bool, error) {
	out := map[string]map[time.Time]bool{}
	err := collect(ctx, db, "the leave", `SELECT staff_id, start_date, end_date FROM leave WHERE staff_id = ANY($1) AND status = $2`,
		func(r pgx.Rows) error {
			var staff, from, to *string
			if err := r.Scan(&staff, &from, &to); err != nil {
				return err
			}
			if staff == nil {
				return nil
			}
			if out[*staff] == nil {
				out[*staff] = map[time.Time]bool{}
			}
			if from == nil || to == nil {
				return nil
			}
			d0, ok0 := isoDate(*from)
			d1, ok1 := isoDate(*to)
			if !ok0 || !ok1 {
				return nil
			}
			for d := d0; !d.After(d1); d = d.AddDate(0, 0, 1) {
				out[*staff][d] = true
			}
			return nil
		}, profiles, rules.LeaveApproved)
	return out, err
}

func openFollowUps(ctx context.Context, db schooldirectory.Querier, ids []string) (map[string]int, error) {
	out := map[string]int{}
	err := collect(ctx, db, "the follow-ups", `
SELECT subject_id FROM staff_usage_follow_up WHERE status = ANY($1) AND subject_id = ANY($2)`, func(r pgx.Rows) error {
		var id string
		if err := r.Scan(&id); err != nil {
			return err
		}
		out[id]++
		return nil
	}, rules.FollowUpOpenStatuses, ids)
	return out, err
}

// signedOut is _signed_out: when each person's current session was ended by
// signing out.
func signedOut(ctx context.Context, db schooldirectory.Querier, logins []string) (map[string]time.Time, error) {
	out := map[string]time.Time{}
	err := collect(ctx, db, "the sign-outs", `
SELECT user_id, ended_at FROM login_event WHERE ended_at IS NOT NULL AND id = ANY($1) ORDER BY at DESC`, func(r pgx.Rows) error {
		var id string
		var at time.Time
		if err := r.Scan(&id, &at); err != nil {
			return err
		}
		out[id] = at
		return nil
	}, logins)
	return out, err
}

// followUpCount is follow_ups.open_count_for: the open follow-ups the
// reader sent or was sent.
func followUpCount(ctx context.Context, db schooldirectory.Querier, userID string) (int, error) {
	var n int
	err := db.QueryRow(ctx, `SELECT COUNT(*) FROM staff_usage_follow_up WHERE status = ANY($1) AND (assignee_id = $2 OR created_by_id = $2)`,
		rules.FollowUpOpenStatuses, userID).Scan(&n)
	if err != nil {
		return 0, fmt.Errorf("staffactivity: counting the reader's follow-ups: %w", err)
	}
	return n, nil
}

func trendCounts(ctx context.Context, db schooldirectory.Querier, ids []string, from, to time.Time) (map[time.Time]int, error) {
	out := map[time.Time]int{}
	if len(ids) == 0 {
		return out, nil
	}
	err := collect(ctx, db, "the trend", `
SELECT day, COUNT(DISTINCT user_id) FROM presence_time WHERE day >= $1 AND day <= $2 AND user_id = ANY($3) GROUP BY 1`, func(r pgx.Rows) error {
		var d time.Time
		var n int
		if err := r.Scan(&d, &n); err != nil {
			return err
		}
		out[civil(d.Year(), d.Month(), d.Day())] = n
		return nil
	}, from, to, ids)
	return out, err
}

func deviceCounts(ctx context.Context, db schooldirectory.Querier, ids []string, start, end time.Time) (map[string]int, error) {
	out := map[string]int{}
	if len(ids) == 0 {
		return out, nil
	}
	err := collect(ctx, db, "the devices", `
SELECT device, COUNT(id) FROM login_event WHERE at >= $1 AND at < $2 AND user_id = ANY($3) AND NOT (device = '') GROUP BY 1`, func(r pgx.Rows) error {
		var device string
		var n int
		if err := r.Scan(&device, &n); err != nil {
			return err
		}
		out[device] = n
		return nil
	}, start, end, ids)
	return out, err
}
