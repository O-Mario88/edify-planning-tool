package teamperformance

import (
	"context"
	"fmt"
	"sort"
	"strconv"
	"strings"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// noHolder is the ledger's None: a school nobody holds, or work credited to
// no officer.
const noHolder = "\x00"

// localDay is Django's _day for a stored moment: the calendar day it falls
// on where the platform works (TIME_ZONE, Africa/Nairobi).
func localDay(column string) string {
	return "(" + column + " AT TIME ZONE 'Africa/Nairobi')::date"
}

type school struct {
	pk, code, owner  string
	core, active     bool
	start, closed    *day
	clustered        bool
	region, district string
}

func (s *school) place(level string) string {
	if level == "district" {
		return s.district
	}
	return s.region
}

type event struct {
	day  day
	unit string
	qty  int
}

// stream is a measure's events per holder, in the order the holders were
// first credited.
type stream struct {
	order []string
	by    map[string][]event
}

func (s *stream) Add(holder string, e event) {
	if s.by == nil {
		s.by = map[string][]event{}
	}
	if _, ok := s.by[holder]; !ok {
		s.order = append(s.order, holder)
	}
	s.by[holder] = append(s.by[holder], e)
}

type store map[string]*stream

func (st store) Add(key, holder string, e event) {
	s := st[key]
	if s == nil {
		s = &stream{}
		st[key] = s
	}
	s.Add(holder, e)
}

// facts is measures.Facts: what one piece of work was.
type facts struct {
	kind         string
	core         *bool
	topic        string
	online       bool
	partner      bool
	activityType string
	meeting      string
	alumni       bool
}

func (f facts) cacheKey() string {
	core := "n"
	if f.core != nil {
		core = strconv.FormatBool(*f.core)
	}
	return strings.Join([]string{f.kind, core, f.topic, strconv.FormatBool(f.online), strconv.FormatBool(f.partner), f.activityType, f.meeting, strconv.FormatBool(f.alumni)}, "\x01")
}

// ledger is ledger.Ledger: the year's records as dated events.
type ledger struct {
	fy              string
	fyStart, fyEnd  day
	officerOf       map[string]string
	schools         map[string]*school
	order           []*school // as the page reads them: newest first
	byCode          map[string]string
	events, planned store
	matches         map[string][]string
	recruits        map[string]bool
	ssaScores       map[string]float64
	alumniProjects  map[string]bool
	regions         []string
	unitPlaces      map[string]map[string]map[string]int // level -> unit -> place -> n
	unitPlaceOrder  map[string]map[string][]string
	narrowed        bool
	ssaCache        map[string]bool
}

func fyRange(fy string) (day, day) {
	n, _ := parsePyInt(fy)
	return dateOf(n-1, time.October, 1), dateOf(n, time.October, 1)
}

func newLedger(fy string) *ledger {
	start, end := fyRange(fy)
	return &ledger{
		fy: fy, fyStart: start, fyEnd: end,
		officerOf: map[string]string{}, schools: map[string]*school{}, byCode: map[string]string{},
		events: store{}, planned: store{}, matches: map[string][]string{},
		recruits: map[string]bool{}, ssaScores: map[string]float64{}, alumniProjects: map[string]bool{},
		unitPlaces:     map[string]map[string]map[string]int{"region": {}, "district": {}},
		unitPlaceOrder: map[string]map[string][]string{"region": {}, "district": {}},
	}
}

// loadLedger is Ledger.load; owners (staff ids) narrows it, nil reads all.
func loadLedger(ctx context.Context, db schooldirectory.Querier, fy string, owners map[string]bool) (*ledger, error) {
	l := newLedger(fy)
	steps := []func(context.Context, schooldirectory.Querier) error{l.loadOfficers, l.loadAlumni}
	for _, step := range steps {
		if err := step(ctx, db); err != nil {
			return nil, err
		}
	}
	l.narrowed = owners != nil
	if err := l.loadSchools(ctx, db, owners); err != nil {
		return nil, err
	}
	if err := l.loadRegions(ctx, db); err != nil {
		return nil, err
	}
	if len(l.schools) > 0 || owners == nil {
		for _, step := range []func(context.Context, schooldirectory.Querier) error{
			l.loadWork, l.loadCorePackage, l.loadRecruits, l.loadSSA, l.loadEvidence,
		} {
			if err := step(ctx, db); err != nil {
				return nil, err
			}
		}
		if err := l.loadMSC(ctx, db, owners); err != nil {
			return nil, err
		}
		if err := l.loadLoans(ctx, db); err != nil {
			return nil, err
		}
	}
	if err := l.loadUnattached(ctx, db, owners); err != nil {
		return nil, err
	}
	for _, st := range []store{l.events, l.planned} {
		for _, s := range st {
			for _, events := range s.by {
				sort.SliceStable(events, func(i, j int) bool { return events[i].day.Before(events[j].day) })
			}
		}
	}
	return l, nil
}

func (l *ledger) loadOfficers(ctx context.Context, db schooldirectory.Querier) error {
	rows, err := db.Query(ctx, `SELECT id, COALESCE(user_id, '') FROM staff_profile WHERE deleted_at IS NULL`)
	if err != nil {
		return fmt.Errorf("teamperformance: officers: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var id, user string
		if err := rows.Scan(&id, &user); err != nil {
			return err
		}
		l.officerOf[id] = id
		if user != "" {
			l.officerOf[user] = id
		}
	}
	return rows.Err()
}

func (l *ledger) loadAlumni(ctx context.Context, db schooldirectory.Querier) error {
	rows, err := db.Query(ctx, `SELECT id FROM project WHERE deleted_at IS NULL AND (UPPER(name::text) LIKE UPPER('%alumni%') OR UPPER(code::text) LIKE UPPER('%alumni%'))`)
	if err != nil {
		return fmt.Errorf("teamperformance: alumni: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var id string
		if err := rows.Scan(&id); err != nil {
			return err
		}
		l.alumniProjects[id] = true
	}
	return rows.Err()
}

func (l *ledger) loadSchools(ctx context.Context, db schooldirectory.Querier, owners map[string]bool) error {
	where, args := "s.deleted_at IS NULL", []any{}
	if owners != nil {
		ids := []string{}
		for k, v := range l.officerOf {
			if owners[v] {
				ids = append(ids, k)
			}
		}
		sort.Strings(ids)
		where += " AND s.account_owner_id = ANY($1::varchar[])"
		args = append(args, ids)
	}
	rows, err := db.Query(ctx, `SELECT s.id, COALESCE(s.school_id, ''), COALESCE(s.account_owner_id, ''), COALESCE(s.school_type, ''),
		COALESCE(s.operational_status, ''), `+localDay("s.created_at")+`, s.closure_effective_date, `+localDay("s.closed_at")+`,
		COALESCE(s.cluster_id, ''), COALESCE(r.name, ''), COALESCE(d.name, '')
		FROM school s LEFT JOIN region r ON s.region_id = r.id LEFT JOIN district d ON s.district_id = d.id
		WHERE `+where+` ORDER BY s.created_at DESC`, args...)
	if err != nil {
		return fmt.Errorf("teamperformance: schools: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var pk, code, owner, kind, status, cluster, region, district string
		var created, closes, closedAt *time.Time
		if err := rows.Scan(&pk, &code, &owner, &kind, &status, &created, &closes, &closedAt, &cluster, &region, &district); err != nil {
			return err
		}
		s := &school{pk: pk, code: code, owner: noHolder, core: coreFamily[kind], active: activeStatuses[status],
			start: created, clustered: cluster != "",
			region:   strings.TrimSpace(strings.ReplaceAll(region, " Region", "")),
			district: strings.TrimSpace(district)}
		if owner != "" {
			if o, ok := l.officerOf[owner]; ok {
				s.owner = o
			}
		}
		if !s.active {
			if closes != nil {
				s.closed = closes
			} else {
				s.closed = closedAt
			}
		}
		l.schools[pk] = s
		l.order = append(l.order, s)
		if code != "" {
			l.byCode[code] = pk
		}
		l.Add(l.events, "new_schools", s, s.start, pk, 1, "")
	}
	return rows.Err()
}

func (l *ledger) loadRegions(ctx context.Context, db schooldirectory.Querier) error {
	rows, err := db.Query(ctx, `SELECT name FROM region WHERE country = 'Uganda' ORDER BY name ASC`)
	if err != nil {
		return fmt.Errorf("teamperformance: regions: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var name string
		if err := rows.Scan(&name); err != nil {
			return err
		}
		l.regions = append(l.regions, strings.TrimSpace(strings.ReplaceAll(name, " Region", "")))
	}
	if err := rows.Err(); err != nil {
		return err
	}
	index := func(n string) int {
		for i, r := range rules.RegionOrder {
			if r == n {
				return i
			}
		}
		return len(rules.RegionOrder)
	}
	sort.SliceStable(l.regions, func(i, j int) bool {
		a, b := index(l.regions[i]), index(l.regions[j])
		if a != b {
			return a < b
		}
		return l.regions[i] < l.regions[j]
	})
	return nil
}

func (l *ledger) within(d day) day {
	return minDay(maxDay(d, l.fyStart), addDays(l.fyEnd, -1))
}

func (l *ledger) schoolOf(ref string) *school {
	if ref == "" {
		return nil
	}
	if s := l.schools[ref]; s != nil {
		return s
	}
	return l.schools[l.byCode[ref]]
}

// add is Ledger._add: an event in the year, filed under the school's holder
// (or owner, for work at no school).
func (l *ledger) Add(st store, key string, s *school, d *day, unit string, qty int, owner string) {
	if d == nil || d.Before(l.fyStart) || !d.Before(l.fyEnd) {
		return
	}
	holder := owner
	if s != nil {
		holder = s.owner
	}
	if holder == "" {
		holder = noHolder
	}
	st.Add(key, holder, event{*d, unit, qty})
}

// work is one activity row as the ledger reads it (_WORK_FIELDS).
type work struct {
	id, activityType, itemCode, courseCode, method, itemMethod, delivery string
	actual, plannedDate, scheduled                                       *day
	teachers, leaders                                                    int
	meetingKind, projectID                                               string
}

const workColumns = `a.id, a.activity_type, COALESCE(ci.stable_code, ''), COALESCE(tc.stable_code, ''),
	COALESCE(a.delivery_method_snapshot, ''), COALESCE(ci.delivery_method, ''), COALESCE(a.delivery_type, ''),
	a.actual_delivery_date, a.planned_date, ` + `(a.scheduled_date AT TIME ZONE 'Africa/Nairobi')::date` + `,
	COALESCE(a.teachers_attended, 0), COALESCE(a.leaders_attended, 0), COALESCE(a.meeting_kind, ''), COALESCE(a.project_id, '')`

const workJoins = ` LEFT JOIN activity_catalogue_item ci ON a.catalogue_item_id = ci.id
	LEFT JOIN activity_catalogue_item tc ON a.training_course_id = tc.id`

func (w *work) targets() []any {
	return []any{&w.id, &w.activityType, &w.itemCode, &w.courseCode, &w.method, &w.itemMethod, &w.delivery,
		&w.actual, &w.plannedDate, &w.scheduled, &w.teachers, &w.leaders, &w.meetingKind, &w.projectID}
}

func kindOf(activityType string) string {
	switch {
	case visitTypes[activityType]:
		return "visit"
	case trainingTypes[activityType]:
		return "training"
	case meetingTypes[activityType]:
		return "meeting"
	case eventTypes[activityType]:
		return "event"
	}
	return "other"
}

func (l *ledger) factsOf(w *work, s *school) (facts, *day, *day, map[string]int) {
	kind := kindOf(w.activityType)
	if kind == "meeting" && w.meetingKind == "training" {
		kind = "training"
	}
	f := facts{kind: kind, activityType: w.activityType, meeting: w.meetingKind, partner: w.delivery == "partner"}
	if s != nil {
		core := s.core
		f.core = &core
	}
	f.topic = w.courseCode
	if f.topic == "" {
		f.topic = w.itemCode
	}
	method := w.method
	if method == "" {
		method = w.itemMethod
	}
	f.online = method == "online"
	f.alumni = w.projectID != "" && l.alumniProjects[w.projectID]
	plannedFor := w.plannedDate
	if plannedFor == nil {
		plannedFor = w.scheduled
	}
	done := w.actual
	if done == nil {
		done = plannedFor
	}
	planned := plannedFor
	if planned == nil {
		planned = w.actual
	}
	return f, done, planned, map[string]int{"teachers": w.teachers, "leaders": w.leaders, "": w.teachers + w.leaders}
}

func (l *ledger) keysFor(f facts) []string {
	key := f.cacheKey()
	if keys, ok := l.matches[key]; ok {
		return keys
	}
	keys := []string{}
	for _, m := range workMeasures {
		if matches(m, f) {
			keys = append(keys, m.Key)
		}
	}
	l.matches[key] = keys
	return keys
}

// credit is Ledger._credit: work into the plan, and into achievement once
// completed.
func (l *ledger) credit(w *work, s *school, owner string, achieved, planned bool) {
	f, doneOn, plannedFor, headcount := l.factsOf(w, s)
	if s != nil {
		l.reached(w.id, s)
	}
	for _, key := range l.keysFor(f) {
		m := byKey[key]
		var ref string
		var qty int
		switch m.Unit {
		case unitSchools:
			if s == nil {
				continue
			}
			ref, qty = s.pk, 1
		case unitParticipants:
			ref, qty = w.id, headcount[m.People]
		case unitSessions:
			ref, qty = w.id, 1
		default:
			continue
		}
		if achieved {
			l.Add(l.events, key, s, doneOn, ref, qty, owner)
		}
		if planned {
			l.Add(l.planned, key, s, plannedFor, ref, qty, owner)
		}
	}
}

func (l *ledger) schoolIDs() []string {
	ids := make([]string, 0, len(l.order))
	for _, s := range l.order {
		ids = append(ids, s.pk)
	}
	return ids
}

func (l *ledger) loadWork(ctx context.Context, db schooldirectory.Querier) error {
	args := []any{l.fy, rules.Statuses.Planned}
	narrow := ""
	if l.narrowed {
		narrow = " AND a.school_id = ANY($3::varchar[])"
		args = append(args, l.schoolIDs())
	}
	rows, err := db.Query(ctx, `SELECT a.school_id, a.status, `+workColumns+` FROM activity a`+workJoins+`
		WHERE a.deleted_at IS NULL AND a.fy = $1 AND a.status = ANY($2::varchar[]) AND a.school_id IS NOT NULL`+narrow+`
		ORDER BY a.created_at DESC`, args...)
	if err != nil {
		return fmt.Errorf("teamperformance: work: %w", err)
	}
	type row struct {
		school, status string
		w              work
	}
	own := []row{}
	for rows.Next() {
		var r row
		if err := rows.Scan(append([]any{&r.school, &r.status}, r.w.targets()...)...); err != nil {
			rows.Close()
			return err
		}
		own = append(own, r)
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return err
	}
	for i := range own {
		if s := l.schools[own[i].school]; s != nil {
			l.credit(&own[i].w, s, "", achievedStatuses[own[i].status], true)
		}
	}

	// Cluster sessions: planned for each school invited or attending,
	// achieved for each that attended.
	args = []any{l.fy, rules.Statuses.Planned, sessionTypes}
	narrow = ""
	if l.narrowed {
		narrow = " AND c.school_id = ANY($4::varchar[])"
		args = append(args, l.schoolIDs())
	}
	rows, err = db.Query(ctx, `SELECT c.school_id, c.attended, a.status, `+workColumns+`
		FROM cluster_activity_attendance c JOIN activity a ON c.activity_id = a.id JOIN school sc ON c.school_id = sc.id`+workJoins+`
		WHERE (c.invited OR c.attended)`+narrow+` AND a.deleted_at IS NULL AND a.fy = $1 AND a.status = ANY($2::varchar[])
		AND a.activity_type = ANY($3::varchar[]) ORDER BY sc.name ASC`, args...)
	if err != nil {
		return fmt.Errorf("teamperformance: register: %w", err)
	}
	type reg struct {
		school, status string
		attended       bool
		w              work
	}
	regs := []reg{}
	for rows.Next() {
		var r reg
		if err := rows.Scan(append([]any{&r.school, &r.attended, &r.status}, r.w.targets()...)...); err != nil {
			rows.Close()
			return err
		}
		regs = append(regs, r)
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return err
	}
	registered := map[string]bool{}
	for i := range regs {
		registered[regs[i].w.id] = true
		if s := l.schools[regs[i].school]; s != nil {
			l.credit(&regs[i].w, s, "", regs[i].attended && achievedStatuses[regs[i].status], true)
		}
	}

	// Attendance recorded before the register existed.
	ids := make([]string, 0, len(registered))
	for id := range registered {
		ids = append(ids, id)
	}
	sort.Strings(ids)
	rows, err = db.Query(ctx, `SELECT a.attended_school_ids, a.status, `+workColumns+` FROM activity a`+workJoins+`
		WHERE a.deleted_at IS NULL AND a.fy = $1 AND a.status = ANY($2::varchar[]) AND a.activity_type = ANY($3::varchar[])
		AND NOT (a.attended_school_ids = '{}'::varchar[]) AND NOT (a.id = ANY($4::varchar[]))
		ORDER BY a.created_at DESC`, l.fy, rules.Statuses.Planned, sessionTypes, ids)
	if err != nil {
		return fmt.Errorf("teamperformance: attended lists: %w", err)
	}
	type legacy struct {
		schools []string
		status  string
		w       work
	}
	lists := []legacy{}
	for rows.Next() {
		var r legacy
		if err := rows.Scan(append([]any{&r.schools, &r.status}, r.w.targets()...)...); err != nil {
			rows.Close()
			return err
		}
		lists = append(lists, r)
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return err
	}
	for i := range lists {
		for _, id := range lists[i].schools {
			if s := l.schools[id]; s != nil {
				l.credit(&lists[i].w, s, "", achievedStatuses[lists[i].status], true)
			}
		}
	}
	return nil
}

func (l *ledger) loadUnattached(ctx context.Context, db schooldirectory.Querier, owners map[string]bool) error {
	rows, err := db.Query(ctx, `SELECT DISTINCT c.activity_id FROM cluster_activity_attendance c JOIN activity a ON c.activity_id = a.id
		JOIN school sc ON c.school_id = sc.id
		WHERE (c.invited OR c.attended) AND a.fy = $1 AND a.school_id IS NULL`, l.fy)
	if err != nil {
		return fmt.Errorf("teamperformance: unattached register: %w", err)
	}
	registered := map[string]bool{}
	for rows.Next() {
		var id string
		if err := rows.Scan(&id); err != nil {
			rows.Close()
			return err
		}
		registered[id] = true
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return err
	}
	rows, err = db.Query(ctx, `SELECT COALESCE(a.responsible_staff_id, ''), a.status, `+workColumns+` FROM activity a`+workJoins+`
		WHERE a.deleted_at IS NULL AND a.fy = $1 AND a.school_id IS NULL AND a.status = ANY($2::varchar[])
		AND NOT (a.activity_type = ANY($3::varchar[]) AND NOT (a.attended_school_ids = '{}'::varchar[]))
		AND NOT (a.id IN (SELECT u0.activity_id FROM cluster_activity_attendance u0 JOIN activity u1 ON u0.activity_id = u1.id
			WHERE (u0.invited OR u0.attended) AND u1.fy = $1 AND u1.school_id IS NULL AND u0.attended))
		ORDER BY a.created_at DESC`, l.fy, rules.Statuses.Planned, sessionTypes)
	if err != nil {
		return fmt.Errorf("teamperformance: unattached work: %w", err)
	}
	type row struct {
		staff, status string
		w             work
	}
	found := []row{}
	for rows.Next() {
		var r row
		if err := rows.Scan(append([]any{&r.staff, &r.status}, r.w.targets()...)...); err != nil {
			rows.Close()
			return err
		}
		found = append(found, r)
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return err
	}
	for i := range found {
		owner := noHolder
		if found[i].staff != "" {
			if o, ok := l.officerOf[found[i].staff]; ok {
				owner = o
			}
		}
		if owners != nil && !owners[owner] {
			continue
		}
		l.credit(&found[i].w, nil, owner, achievedStatuses[found[i].status], !registered[found[i].w.id])
	}
	return nil
}

func (l *ledger) loadCorePackage(ctx context.Context, db schooldirectory.Querier) error {
	rows, err := db.Query(ctx, `SELECT COALESCE(cs.school_id, ''), cs.activity_type, COALESCE(cs.activity_id, ''), `+localDay("cs.completed_at")+`, COALESCE(cs.status, '')
		FROM core_activity_slot cs JOIN core_plan cp ON cs.core_plan_id = cp.id
		WHERE cs.activity_type IN ('visit', 'training') AND cp.fy = $1`, l.fy)
	if err != nil {
		return fmt.Errorf("teamperformance: core slots: %w", err)
	}
	type slot struct {
		school, kind, activity, status string
		completed                      *day
	}
	slots := []slot{}
	linkedIDs := []string{}
	for rows.Next() {
		var s slot
		if err := rows.Scan(&s.school, &s.kind, &s.activity, &s.completed, &s.status); err != nil {
			rows.Close()
			return err
		}
		slots = append(slots, s)
		if s.activity != "" {
			linkedIDs = append(linkedIDs, s.activity)
		}
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return err
	}
	type linked struct {
		status        string
		done, planned *day
	}
	work := map[string]linked{}
	if len(linkedIDs) > 0 {
		rows, err = db.Query(ctx, `SELECT id, status, actual_delivery_date, planned_date, `+localDay("scheduled_date")+`
			FROM activity WHERE deleted_at IS NULL AND id = ANY($1::varchar[])`, linkedIDs)
		if err != nil {
			return fmt.Errorf("teamperformance: core slot work: %w", err)
		}
		for rows.Next() {
			var id, status string
			var actual, planned, scheduled *day
			if err := rows.Scan(&id, &status, &actual, &planned, &scheduled); err != nil {
				rows.Close()
				return err
			}
			done := firstDay(actual, planned, scheduled)
			plannedFor := firstDay(planned, scheduled, actual)
			work[id] = linked{status, done, plannedFor}
		}
		rows.Close()
		if err := rows.Err(); err != nil {
			return err
		}
	}
	type at struct{ pk, kind string }
	done, planned := map[at][]day{}, map[at][]day{}
	doneOrder, plannedOrder := []at{}, []at{}
	push := func(m map[at][]day, order *[]at, k at, d day) {
		if _, ok := m[k]; !ok {
			*order = append(*order, k)
		}
		m[k] = append(m[k], d)
	}
	for _, sl := range slots {
		s := l.schoolOf(sl.school)
		if s == nil {
			continue
		}
		k := at{s.pk, sl.kind}
		w, ok := work[sl.activity]
		if sl.activity == "" || !ok {
			if coreSlotDone[sl.status] && sl.completed != nil {
				push(done, &doneOrder, k, *sl.completed)
				push(planned, &plannedOrder, k, *sl.completed)
			}
			continue
		}
		if achievedStatuses[w.status] && w.done != nil {
			push(done, &doneOrder, k, *w.done)
		}
		if plannedStatuses[w.status] && w.planned != nil {
			push(planned, &plannedOrder, k, *w.planned)
		}
	}
	for _, pass := range []struct {
		dates map[at][]day
		order []at
		st    store
	}{{done, doneOrder, l.events}, {planned, plannedOrder, l.planned}} {
		for _, k := range pass.order {
			s := l.schools[k.pk]
			ordered := []day{}
			for _, d := range pass.dates[k] {
				ordered = append(ordered, l.within(d))
			}
			sort.Slice(ordered, func(i, j int) bool { return ordered[i].Before(ordered[j]) })
			for n, d := range ordered {
				if n >= 4 {
					break
				}
				d := d
				l.Add(pass.st, fmt.Sprintf("core_%s_%d", k.kind, n+1), s, &d, s.pk, 1, "")
			}
		}
	}
	return nil
}

func firstDay(days ...*day) *day {
	for _, d := range days {
		if d != nil {
			return d
		}
	}
	return nil
}

func (l *ledger) loadRecruits(ctx context.Context, db schooldirectory.Querier) error {
	rows, err := db.Query(ctx, `SELECT COALESCE(school_id, '') FROM core_school_onboarding WHERE fy = $1`, l.fy)
	if err != nil {
		return fmt.Errorf("teamperformance: onboardings: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var ref string
		if err := rows.Scan(&ref); err != nil {
			return err
		}
		if s := l.schoolOf(ref); s != nil {
			l.recruits[s.pk] = true
		}
	}
	return rows.Err()
}

func (l *ledger) loadSSA(ctx context.Context, db schooldirectory.Querier) error {
	rows, err := db.Query(ctx, `SELECT COALESCE(school_id, ''), `+localDay("date_of_ssa")+`, average_score FROM ssa_record
		WHERE (deleted_at IS NULL AND fy = $1 AND verification_status IN ($2, $3)) ORDER BY date_of_ssa ASC`,
		l.fy, rules.Statuses.Uploaded[0], rules.Statuses.Uploaded[1])
	if err != nil {
		return fmt.Errorf("teamperformance: ssa: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var ref string
		var when *day
		var score *float64
		if err := rows.Scan(&ref, &when, &score); err != nil {
			return err
		}
		s := l.schools[ref]
		if s == nil || when == nil {
			continue
		}
		if score != nil {
			l.ssaScores[s.pk] = *score
		}
		key := "ssa_core_followup"
		switch {
		case !s.core:
			key = "ssa_client"
		case l.recruits[s.pk]:
			key = "ssa_core_baseline"
		}
		d := l.within(*when)
		l.Add(l.events, key, s, &d, s.pk, 1, "")
		l.Add(l.events, "ssa_all", s, &d, s.pk, 1, "")
	}
	return rows.Err()
}

func (l *ledger) loadEvidence(ctx context.Context, db schooldirectory.Querier) error {
	up := rules.Statuses.Uploaded
	rows, err := db.Query(ctx, `SELECT COALESCE(school_id, ''), observed_on, COALESCE(discipleship_groups_active, 0) FROM impact_discipleship_record
		WHERE fy = $1 AND deleted_at IS NULL AND verification_status = ANY($2::varchar[])`, l.fy, up)
	if err != nil {
		return fmt.Errorf("teamperformance: discipleship: %w", err)
	}
	for rows.Next() {
		var ref string
		var observed *day
		var groups int
		if err := rows.Scan(&ref, &observed, &groups); err != nil {
			rows.Close()
			return err
		}
		s := l.schools[ref]
		if s == nil {
			continue
		}
		l.Add(l.events, "dc_data", s, observed, s.pk, 1, "")
		l.Add(l.events, "metrics", s, observed, s.pk, 1, "")
		if groups != 0 {
			l.Add(l.events, "dc_clubs", s, observed, s.pk, 1, "")
			family := "dc_clubs_client"
			if s.core {
				family = "dc_clubs_core"
			}
			l.Add(l.events, family, s, observed, s.pk, 1, "")
		}
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return err
	}
	rows, err = db.Query(ctx, `SELECT COALESCE(school_id, ''), assessed_on, COALESCE(assessment_type, '') FROM impact_learning_result
		WHERE fy = $1 AND deleted_at IS NULL AND verification_status = ANY($2::varchar[])`, l.fy, up)
	if err != nil {
		return fmt.Errorf("teamperformance: learning: %w", err)
	}
	for rows.Next() {
		var ref, kind string
		var assessed *day
		if err := rows.Scan(&ref, &assessed, &kind); err != nil {
			rows.Close()
			return err
		}
		s := l.schools[ref]
		if s == nil {
			continue
		}
		l.Add(l.events, "metrics", s, assessed, s.pk, 1, "")
		if kind == "onetest" {
			l.Add(l.events, "onetest", s, assessed, s.pk, 1, "")
		} else if kind == "national_exam" && s.core {
			l.Add(l.events, "core_exam_scores", s, assessed, s.pk, 1, "")
		}
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return err
	}
	args := []any{l.fyStart, l.fyEnd}
	narrow := ""
	if l.narrowed {
		narrow = " AND id = ANY($3::varchar[])"
		args = append(args, l.schoolIDs())
	}
	rows, err = db.Query(ctx, `SELECT id, last_enrollment_date FROM school WHERE deleted_at IS NULL AND enrollment IS NOT NULL
		AND last_enrollment_date >= $1::date AND last_enrollment_date < $2::date`+narrow, args...)
	if err != nil {
		return fmt.Errorf("teamperformance: enrolment: %w", err)
	}
	for rows.Next() {
		var ref string
		var d *day
		if err := rows.Scan(&ref, &d); err != nil {
			rows.Close()
			return err
		}
		if s := l.schools[ref]; s != nil {
			l.Add(l.events, "enrolment", s, d, s.pk, 1, "")
			l.Add(l.events, "metrics", s, d, s.pk, 1, "")
		}
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return err
	}
	rows, err = db.Query(ctx, `SELECT COALESCE(school_id, ''), `+localDay("recorded_at")+` FROM school_enrollment_history WHERE fy = $1`, l.fy)
	if err != nil {
		return fmt.Errorf("teamperformance: enrolment history: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var ref string
		var d *day
		if err := rows.Scan(&ref, &d); err != nil {
			return err
		}
		s := l.schools[ref]
		if s == nil || d == nil {
			continue
		}
		in := l.within(*d)
		l.Add(l.events, "enrolment", s, &in, s.pk, 1, "")
		l.Add(l.events, "metrics", s, &in, s.pk, 1, "")
	}
	return rows.Err()
}

func (l *ledger) loadMSC(ctx context.Context, db schooldirectory.Querier, owners map[string]bool) error {
	rows, err := db.Query(ctx, `SELECT id, COALESCE(school_id, ''), COALESCE(user_id, ''), story_date FROM mscs_story
		WHERE status = 'approved' AND story_date >= $1::date AND story_date < $2::date`, l.fyStart, l.fyEnd)
	if err != nil {
		return fmt.Errorf("teamperformance: stories: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var id, ref, author string
		var d *day
		if err := rows.Scan(&id, &ref, &author, &d); err != nil {
			return err
		}
		var s *school
		if ref != "" {
			s = l.schools[ref]
		}
		if s == nil {
			officer := noHolder
			if o, ok := l.officerOf[author]; ok {
				officer = o
			}
			if ref != "" || (owners != nil && !owners[officer]) {
				continue
			}
			l.Add(l.events, "msc", nil, d, id, 1, officer)
			continue
		}
		l.Add(l.events, "msc", s, d, id, 1, "")
		l.reached(id, s)
	}
	return rows.Err()
}

func (l *ledger) loadLoans(ctx context.Context, db schooldirectory.Querier) error {
	rows, err := db.Query(ctx, `SELECT m.id, COALESCE(m.school_id, ''), m.disbursement_date, COALESCE(p.is_edtech, false)
		FROM bt_mfi_loan m LEFT JOIN bt_loan_purpose p ON m.purpose_id = p.id
		WHERE m.deleted_at IS NULL AND m.status = ANY($1::varchar[]) AND m.disbursement_date IS NOT NULL`, rules.Statuses.DisbursedLoan)
	if err != nil {
		return fmt.Errorf("teamperformance: loans: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var id, ref string
		var d *day
		var edtech bool
		if err := rows.Scan(&id, &ref, &d, &edtech); err != nil {
			return err
		}
		s := l.schools[ref]
		if s == nil {
			continue
		}
		l.Add(l.events, "loans", s, d, id, 1, "")
		key := "development_loans"
		if edtech {
			key = "edtech_loans"
		}
		l.Add(l.events, key, s, d, id, 1, "")
	}
	return rows.Err()
}

// ── Reading ─────────────────────────────────────────────────────────────────

// reached is Ledger._reached: a session or a story reached this school.
func (l *ledger) reached(unit string, s *school) {
	for _, level := range []string{"region", "district"} {
		places := l.unitPlaces[level][unit]
		if places == nil {
			places = map[string]int{}
			l.unitPlaces[level][unit] = places
		}
		place := s.place(level)
		if _, ok := places[place]; !ok {
			l.unitPlaceOrder[level][unit] = append(l.unitPlaceOrder[level][unit], place)
		}
		places[place]++
	}
}

// placeOf is Ledger.place_of.
func (l *ledger) placeOf(unit, level string) string {
	if s := l.schools[unit]; s != nil {
		return s.place(level)
	}
	reached := l.unitPlaces[level][unit]
	if len(reached) == 0 {
		return ""
	}
	best, bestN := "", -1
	for _, place := range l.unitPlaceOrder[level][unit] {
		n := reached[place]
		if n > bestN || (n == bestN && place < best) {
			best, bestN = place, n
		}
	}
	return best
}

// seen is Ledger._seen: each unit counted over [start, end) and its quantity.
func seen(st store, m *measure, owners map[string]bool, w window) (map[string]int, []string) {
	s := st[m.Key]
	if s == nil || len(s.by) == 0 {
		s = st[m.Source]
	}
	out := map[string]int{}
	order := []string{}
	if s == nil {
		return out, order
	}
	for _, holder := range s.order {
		if owners != nil && !owners[holder] {
			continue
		}
		events := s.by[holder]
		low := sort.Search(len(events), func(i int) bool { return !events[i].day.Before(w.start) })
		high := sort.Search(len(events), func(i int) bool { return !events[i].day.Before(w.end) })
		for _, e := range events[low:high] {
			if _, ok := out[e.unit]; !ok {
				order = append(order, e.unit)
			}
			out[e.unit] = e.qty
		}
	}
	return out, order
}

func tally(st store, m *measure, owners map[string]bool, w window) int {
	found, _ := seen(st, m, owners, w)
	if m.Unit == unitParticipants {
		total := 0
		for _, q := range found {
			total += q
		}
		return total
	}
	return len(found)
}

// count is Ledger.count; nil where the records cannot give the figure.
func (l *ledger) count(key string, owners map[string]bool, w window) *int {
	m := byKey[key]
	if !m.Tracked {
		return nil
	}
	var n int
	switch m.Source {
	case "active":
		n = l.portfolio(owners, "active", &w.end)
	case "in_clusters":
		n = l.portfolio(owners, "clustered", &w.end)
	default:
		n = tally(l.events, m, owners, w)
	}
	return &n
}

// plannedCount is Ledger.planned.
func (l *ledger) plannedCount(key string, owners map[string]bool, w window) *int {
	m := byKey[key]
	if !m.Tracked || !plannable(m) {
		return nil
	}
	n := tally(l.planned, m, owners, w)
	return &n
}

func plannable(m *measure) bool {
	return m.Match != nil || strings.HasPrefix(m.Source, "core_visit_") || strings.HasPrefix(m.Source, "core_training_")
}

func (l *ledger) units(key string, owners map[string]bool, w window) (map[string]int, []string) {
	return seen(l.events, byKey[key], owners, w)
}

func (l *ledger) held(owners map[string]bool, asOf *day) []*school {
	out := []*school{}
	for _, s := range l.order {
		if owners != nil && !owners[s.owner] {
			continue
		}
		if asOf != nil && s.start != nil && !s.start.Before(*asOf) {
			continue
		}
		out = append(out, s)
	}
	return out
}

func (l *ledger) is(s *school, kind string, asOf *day) bool {
	switch kind {
	case "all", "portfolio":
		return true
	case "active":
		return s.active || (asOf != nil && s.closed != nil && !s.closed.Before(*asOf))
	case "core":
		return s.core
	case "client":
		return !s.core
	case "clustered":
		return s.clustered
	case "core_continuing":
		return s.core && !l.recruits[s.pk]
	case "ssa_core", "ssa_client":
		return s.core == (kind == "ssa_core") && l.ssaSchools()[s.pk]
	}
	panic("teamperformance: no portfolio kind " + kind)
}

func (l *ledger) ssaSchools() map[string]bool {
	if l.ssaCache == nil {
		l.ssaCache = map[string]bool{}
		for _, key := range []string{"ssa_client", "ssa_core_baseline", "ssa_core_followup"} {
			if s := l.events[key]; s != nil {
				for _, events := range s.by {
					for _, e := range events {
						l.ssaCache[e.unit] = true
					}
				}
			}
		}
	}
	return l.ssaCache
}

func (l *ledger) portfolio(owners map[string]bool, kind string, asOf *day) int {
	return len(l.portfolioSchools(owners, kind, asOf))
}

func (l *ledger) portfolioSchools(owners map[string]bool, kind string, asOf *day) []string {
	out := []string{}
	for _, s := range l.held(owners, asOf) {
		if l.is(s, kind, asOf) {
			out = append(out, s.pk)
		}
	}
	return out
}

// ssaAverage is Ledger.ssa_average: the mean of the year's latest scores.
func (l *ledger) ssaAverage(owners map[string]bool, core bool) *float64 {
	scores := []float64{}
	for _, s := range l.held(owners, nil) {
		if v, ok := l.ssaScores[s.pk]; ok && s.core == core {
			scores = append(scores, v)
		}
	}
	if len(scores) == 0 {
		return nil
	}
	v := pyRound(schooldirectory.PySum(scores)/float64(len(scores)), 2)
	return &v
}

// placesOf is Ledger.places_of: how many of these officers' schools are in
// each region (or district), with the order each was first met.
func (l *ledger) placesOf(owners map[string]bool, level string) (map[string]int, []string) {
	out, order := map[string]int{}, []string{}
	for _, s := range l.held(owners, nil) {
		place := s.place(level)
		if place == "" {
			continue
		}
		if _, ok := out[place]; !ok {
			order = append(order, place)
		}
		out[place]++
	}
	return out, order
}

func (l *ledger) holders() map[string]bool {
	out := map[string]bool{}
	for _, s := range l.order {
		if s.owner != noHolder {
			out[s.owner] = true
		}
	}
	return out
}

// mostOf is max(tally, key=lambda r: (tally[r], r)).
func mostOf(tally map[string]int) string {
	best, bestN := "", -1
	for place, n := range tally {
		if n > bestN || (n == bestN && place > best) {
			best, bestN = place, n
		}
	}
	return best
}
