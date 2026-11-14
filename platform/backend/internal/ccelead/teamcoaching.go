package ccelead

import (
	"context"
	"fmt"
	"net/url"
	"slices"
	"sort"
	"strconv"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/closedschools"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// TeamCoachingPath is the Programme Lead's coaching log, which the Country
// Director, the Regional Lead and Admin read.
const TeamCoachingPath = "/team/coaching"

// officer is one CCEO on the lead's team.
type officer struct{ staff, user, name string }

// leadTeam is hr.team_roster.team_members for a lead in their own seat: the
// live CCEOs they, and any Programme Lead they cover while the cover runs,
// supervise, by name.
func leadTeam(ctx context.Context, db schooldirectory.Querier, profileID string, now time.Time) ([]officer, error) {
	if profileID == "" {
		return nil, nil
	}
	holds := func(n string) string {
		return `(u.active_role = ` + n + ` OR u.roles @> (ARRAY[` + n + `])::varchar(64)[])`
	}
	rows, err := db.Query(ctx, `SELECT sp.id, COALESCE(sp.user_id, ''), COALESCE(u.name, '') FROM staff_profile sp JOIN "user" u ON sp.user_id = u.id
WHERE `+holds("$1")+` AND sp.id IN (
    SELECT a.supervisee_id FROM staff_supervisor_assignment a WHERE a.supervisor_id = $3 OR a.supervisor_id IN (
      SELECT c.id FROM staff_profile c JOIN "user" cu ON c.user_id = cu.id
      WHERE c.deleted_at IS NULL AND (cu.active_role = $2 OR cu.roles @> (ARRAY[$2])::varchar(64)[]) AND c.id IN (
        SELECT t.original_staff_id FROM temporary_coverage_assignment t
        WHERE t.covering_staff_id = $3 AND t.start_datetime <= $4 AND t.end_datetime >= $4 AND t.status = 'active')))
  AND sp.deleted_at IS NULL AND u.deleted_at IS NULL AND u.is_active AND NOT (sp.id = $3)
ORDER BY u.name ASC`, cceo, programLead, profileID, now)
	if err != nil {
		return nil, fmt.Errorf("ccelead: reading the lead's team: %w", err)
	}
	out, err := pgx.CollectRows(rows, func(r pgx.CollectableRow) (officer, error) {
		var o officer
		return o, r.Scan(&o.staff, &o.user, &o.name)
	})
	if err != nil {
		return nil, fmt.Errorf("ccelead: reading the lead's team: %w", err)
	}
	return out, nil
}

// coachingRecord is one coaching record as the register reads it.
type coachingRecord struct {
	id, subject, staff, kind, author string
	held                             time.Time
	due                              *time.Time
	done, shared, acknowledged       *time.Time
}

// coachingState is coaching.state_of for the lead's side of the register.
func coachingState(x coachingRecord, today time.Time) string {
	switch {
	case x.due != nil && x.done == nil && !x.due.After(today):
		return "Follow-up due"
	case x.acknowledged != nil:
		return "Acknowledged"
	case x.shared != nil:
		return "Awaiting the officer"
	}
	return "Not shared yet"
}

// stateWhere is coaching.with_state as a condition on `c`.
func stateWhere(state string, todayArg string) string {
	switch state {
	case "draft":
		return " AND c.shared_at IS NULL"
	case "awaiting":
		return " AND c.shared_at IS NOT NULL AND c.acknowledged_at IS NULL"
	case "acknowledged":
		return " AND c.acknowledged_at IS NOT NULL"
	case "follow_up":
		return " AND c.follow_up_due <= " + todayArg + "::date AND c.follow_up_done_at IS NULL"
	}
	return ""
}

func kindLabel(kind string) string {
	for _, k := range rules.CoachingKinds {
		if k[0] == kind {
			return k[1]
		}
	}
	return kind
}

// teamCoaching is team_coaching_view.
func teamCoaching(ctx context.Context, db schooldirectory.Querier, p auth.Principal, now time.Time, query url.Values) (register, error) {
	local := now.In(zone)
	today := time.Date(local.Year(), local.Month(), local.Day(), 0, 0, 0, 0, time.UTC)
	todayText := today.Format(time.DateOnly)
	lead := p.ActiveRole == programLead
	var members []officer
	visible, args := "FALSE", []any{}
	names := map[string]string{}
	userToStaff := map[string]string{}
	if lead {
		var err error
		if members, err = leadTeam(ctx, db, p.StaffProfileID, now); err != nil {
			return register{}, err
		}
		ids := []string{}
		for _, m := range members {
			ids = append(ids, m.staff)
			names[m.staff] = m.name
			userToStaff[m.user] = m.staff
		}
		if len(ids) > 0 {
			visible, args = "c.author_id = $1 AND c.cceo_staff_id = ANY($2)", []any{p.UserID, ids}
		}
	} else {
		var err error
		if visible, args, err = coachingVisible(ctx, db, p); err != nil {
			return register{}, err
		}
		if err := staffNames(ctx, db, visible, args, names); err != nil {
			return register{}, err
		}
	}
	n := len(args)
	base := func() []any { return append([]any{}, args[:n]...) }
	listArgs := base()
	at := func(v any) string { listArgs = append(listArgs, v); return "$" + strconv.Itoa(len(listArgs)) }

	cceoID := strings.TrimSpace(query.Get("cceo"))
	if s, ok := userToStaff[cceoID]; ok {
		cceoID = s
	}
	kind, state := query.Get("kind"), query.Get("state")
	knownKind := slices.ContainsFunc(rules.CoachingKinds, func(k [2]string) bool { return k[0] == kind })
	knownState := slices.ContainsFunc(rules.CoachingStates, func(k [2]string) bool { return k[0] == state })
	where := visible
	if _, ok := names[cceoID]; ok {
		where += " AND c.cceo_staff_id = " + at(cceoID)
	} else {
		cceoID = ""
	}
	if knownKind {
		where += " AND c.kind = " + at(kind)
	} else {
		kind = ""
	}
	if knownState {
		todayArg := ""
		if state == "follow_up" {
			todayArg = at(todayText)
		}
		where += stateWhere(state, todayArg)
	} else {
		state = ""
	}
	rows, err := db.Query(ctx, fmt.Sprintf(`SELECT c.id, COALESCE(c.subject, ''), COALESCE(c.cceo_staff_id, ''), c.kind, COALESCE(c.author_id, ''), c.held_on,
  c.follow_up_due, c.follow_up_done_at, c.shared_at, c.acknowledged_at
FROM cce_cceo_coaching c WHERE %s ORDER BY c.held_on DESC, c.created_at DESC LIMIT %d`, where, feedbackLimit), listArgs...)
	if err != nil {
		return register{}, fmt.Errorf("ccelead: reading the team's coaching: %w", err)
	}
	list, err := pgx.CollectRows(rows, func(r pgx.CollectableRow) (coachingRecord, error) {
		var x coachingRecord
		return x, r.Scan(&x.id, &x.subject, &x.staff, &x.kind, &x.author, &x.held, &x.due, &x.done, &x.shared, &x.acknowledged)
	})
	if err != nil {
		return register{}, fmt.Errorf("ccelead: reading the team's coaching: %w", err)
	}
	authors := map[string]string{}
	if !lead {
		ids := []string{}
		for _, x := range list {
			ids = append(ids, x.author)
		}
		if authors, err = userNames(ctx, db, ids); err != nil {
			return register{}, err
		}
	}

	reg := register{path: TeamCoachingPath, title: "Coaching", eyebrow: "Performance & coaching", registerTitle: "Coaching log",
		description: "Coaching Programme Leads have shared with their officers, and what each officer said they will do.",
		emptyTitle:  "No shared coaching in your reach",
		emptyBody:   "Coaching appears here once a Programme Lead shares it with an officer.",
		columns:     []string{"Coaching", "Officer"},
	}
	if lead {
		reg.description = "Monthly one-to-ones, school visit and training observations, and feedback for the officers you line-manage. " +
			"Share each record with the officer; they acknowledge it and say what they will do."
		reg.emptyTitle = "No coaching recorded yet"
		reg.emptyBody = "Log a one-to-one or record an observation; it stays private until you share it with the officer."
	} else {
		reg.columns = append(reg.columns, "Programme Lead")
	}
	reg.columns = append(reg.columns, "Kind", "Held", "Follow up by", "State")
	for _, x := range list {
		cells := []string{dash(x.subject), dash(names[x.staff])}
		if !lead {
			cells = append(cells, dash(authors[x.author]))
		}
		follow := ""
		switch {
		case x.done != nil:
			follow = "Closed " + x.done.UTC().Format("2 Jan 2006")
		case x.due != nil:
			follow = x.due.Format("2 Jan 2006")
		}
		cells = append(cells, dash(kindLabel(x.kind)), dash(x.held.Format("2 Jan 2006")), dash(follow), coachingState(x, today))
		reg.rows = append(reg.rows, cells)
		acts := []action{{label: "Open", drawer: TeamCoachingPath + "/" + x.id}}
		switch {
		case lead && x.shared == nil:
			acts = append(acts, action{label: "Share", drawer: TeamCoachingPath + "/" + x.id + "/share"})
		case lead && x.due != nil && x.done == nil:
			acts = append(acts, action{label: "Follow up", drawer: TeamCoachingPath + "/" + x.id + "/follow-up"})
		}
		reg.rowActions = append(reg.rowActions, acts)
	}

	// coaching.coaching_counts over everything visible, unfiltered.
	var drafts, awaiting, followUps int
	if err := db.QueryRow(ctx, fmt.Sprintf(`SELECT count(*) FILTER (WHERE c.shared_at IS NULL),
  count(*) FILTER (WHERE c.shared_at IS NOT NULL AND c.acknowledged_at IS NULL),
  count(*) FILTER (WHERE c.follow_up_due <= $%d::date AND c.follow_up_done_at IS NULL)
FROM cce_cceo_coaching c WHERE %s`, n+1, visible), append(base(), todayText)...).Scan(&drafts, &awaiting, &followUps); err != nil {
		return register{}, fmt.Errorf("ccelead: counting the team's coaching: %w", err)
	}
	monthStart := time.Date(today.Year(), today.Month(), 1, 0, 0, 0, 0, time.UTC)
	var oneToOne metric
	if lead {
		before, held, due, err := oneToOnes(ctx, db, visible, base(), members, today, monthStart, query)
		if err != nil {
			return register{}, err
		}
		reg.before = before
		dueFrom := time.Date(today.Year(), today.Month(), rules.OneToOneDueDay, 0, 0, 0, 0, time.UTC)
		helper, tone := "due from "+dueFrom.Format("2 January")+" with each officer", "info"
		switch {
		case due > 0:
			helper, tone = strconv.Itoa(due)+" "+plural(due, "officer", "officers")+" due", "danger"
		case len(members) > 0:
			tone = "success"
		}
		oneToOne = metric{"One-to-Ones Held This Month", fmt.Sprintf("%d / %d", held, len(members)), helper, tone}
	} else {
		var coached int
		if err := db.QueryRow(ctx, fmt.Sprintf(`SELECT count(DISTINCT c.cceo_staff_id) FROM cce_cceo_coaching c
WHERE %s AND c.kind = $%d AND c.held_on >= $%d::date`, visible, n+1, n+2), append(base(), rules.OneToOneKind, monthStart.Format(time.DateOnly))...).Scan(&coached); err != nil {
			return register{}, fmt.Errorf("ccelead: counting this month's one-to-ones: %w", err)
		}
		oneToOne = metric{"One-to-Ones Held This Month", strconv.Itoa(coached), "officers with a shared one-to-one this month", "info"}
	}
	reg.metrics = append([]metric{oneToOne}, countMetrics(lead, drafts, awaiting, followUps)...)
	switch {
	case !lead:
		reg.notice = "Read only. Each officer's Programme Lead writes their coaching; you read what the lead has shared with the officer."
	case len(members) == 0:
		reg.notice = "No officers are assigned to you yet. Coaching opens for the officers HR records you as the supervisor of."
	default:
		reg.actions = []action{
			{label: "Log coaching", drawer: TeamCoachingPath + "/new"},
			{label: "Record an observation", drawer: TeamCoachingPath + "/new?kind=field_observation"},
		}
	}
	reg.filters = teamFilters(lead, names, cceoID, kind, state)
	return reg, nil
}

// countMetrics is the register's three counted figures.
func countMetrics(lead bool, drafts, awaiting, followUps int) []metric {
	draftHelper, draftTone := "drafts stay with the lead", "info"
	if lead {
		draftHelper = "drafts only you can read"
		if drafts > 0 {
			draftTone = "warning"
		}
	}
	awaitTone, followTone := "info", "info"
	if awaiting > 0 {
		awaitTone = "warning"
	}
	if followUps > 0 {
		followTone = "danger"
	}
	return []metric{
		{"Coaching Notes Not Yet Shared", strconv.Itoa(drafts), draftHelper, draftTone},
		{"Coaching Awaiting Officer Acknowledgement", strconv.Itoa(awaiting), "shared, not yet acknowledged", awaitTone},
		{"Coaching Follow-Ups Due", strconv.Itoa(followUps), "agreed actions to check on", followTone},
	}
}

// teamFilters is the register's selects: the officer (when there is one to
// choose), the kind and the state (a reader who is not the lead never sees
// drafts).
func teamFilters(lead bool, names map[string]string, cceoID, kind, state string) []*screensv1.PageFilter {
	out := []*screensv1.PageFilter{}
	if len(names) > 0 {
		officers := [][2]string{}
		for id, name := range names {
			officers = append(officers, [2]string{id, name})
		}
		sort.SliceStable(officers, func(i, j int) bool {
			if officers[i][1] != officers[j][1] {
				return officers[i][1] < officers[j][1]
			}
			return officers[i][0] < officers[j][0]
		})
		out = append(out, filter("cceo", "Officer", cceoID, "Every officer", officers))
	}
	states := [][2]string{}
	for _, s := range rules.CoachingStates {
		if lead || s[0] != "draft" {
			states = append(states, s)
		}
	}
	// A state the select does not offer (a draft, to a reader) still narrows
	// the records; the select shows none chosen.
	if !slices.ContainsFunc(states, func(k [2]string) bool { return k[0] == state }) {
		state = ""
	}
	return append(out, filter("kind", "Kind", kind, "Every kind", rules.CoachingKinds),
		filter("state", "State", state, "Every state", states))
}

// staffNames is _names_by_staff over the officers the visible coaching is
// about.
func staffNames(ctx context.Context, db schooldirectory.Querier, visible string, args []any, out map[string]string) error {
	rows, err := db.Query(ctx, fmt.Sprintf(`SELECT sp.id, COALESCE(u.name, '') FROM staff_profile sp LEFT JOIN "user" u ON u.id = sp.user_id
WHERE sp.id IN (SELECT DISTINCT c.cceo_staff_id FROM cce_cceo_coaching c WHERE %s AND c.cceo_staff_id IS NOT NULL LIMIT %d)`, visible, feedbackLimit), args...)
	if err != nil {
		return fmt.Errorf("ccelead: reading the officers' names: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var id, name string
		if err := rows.Scan(&id, &name); err != nil {
			return fmt.Errorf("ccelead: reading the officers' names: %w", err)
		}
		out[id] = name
	}
	return rows.Err()
}

// userNames is _names_by_user.
func userNames(ctx context.Context, db schooldirectory.Querier, ids []string) (map[string]string, error) {
	out := map[string]string{}
	rows, err := db.Query(ctx, `SELECT id, COALESCE(name, '') FROM "user" WHERE id = ANY($1)`, ids)
	if err != nil {
		return nil, fmt.Errorf("ccelead: reading the leads' names: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var id, name string
		if err := rows.Scan(&id, &name); err != nil {
			return nil, fmt.Errorf("ccelead: reading the leads' names: %w", err)
		}
		out[id] = name
	}
	return out, rows.Err()
}

// officerFigures is what oneToOnes reads for each officer: this month's
// latest one-to-one, their latest coaching, and their awaiting and due
// counts.
type officerFigures struct {
	held     map[string]time.Time
	last     map[string]time.Time
	lastKind map[string]string
	open     map[string][2]int
}

func readOfficerFigures(ctx context.Context, db schooldirectory.Querier, visible string, args []any, ids []string, today, monthStart time.Time) (officerFigures, error) {
	f := officerFigures{held: map[string]time.Time{}, last: map[string]time.Time{}, lastKind: map[string]string{}, open: map[string][2]int{}}
	if len(ids) == 0 {
		return f, nil
	}
	monthEnd := monthStart.AddDate(0, 1, 0)
	rows, err := db.Query(ctx, `SELECT cceo_staff_id, max(held_on) FROM cce_cceo_coaching
WHERE kind = $1 AND cceo_staff_id = ANY($2) AND held_on >= $3::date AND held_on < $4::date GROUP BY 1`,
		rules.OneToOneKind, ids, monthStart.Format(time.DateOnly), monthEnd.Format(time.DateOnly))
	if err != nil {
		return f, fmt.Errorf("ccelead: reading this month's one-to-ones: %w", err)
	}
	for rows.Next() {
		var id string
		var on time.Time
		if err := rows.Scan(&id, &on); err != nil {
			rows.Close()
			return f, fmt.Errorf("ccelead: reading this month's one-to-ones: %w", err)
		}
		f.held[id] = on
	}
	rows.Close()
	rows, err = db.Query(ctx, fmt.Sprintf(`SELECT DISTINCT ON (c.cceo_staff_id) c.cceo_staff_id, c.held_on, c.kind FROM cce_cceo_coaching c
WHERE %s ORDER BY c.cceo_staff_id, c.held_on DESC, c.created_at DESC`, visible), args...)
	if err != nil {
		return f, fmt.Errorf("ccelead: reading the latest coaching: %w", err)
	}
	for rows.Next() {
		var id, kind string
		var on time.Time
		if err := rows.Scan(&id, &on, &kind); err != nil {
			rows.Close()
			return f, fmt.Errorf("ccelead: reading the latest coaching: %w", err)
		}
		f.last[id], f.lastKind[id] = on, kind
	}
	rows.Close()
	n := len(args)
	rows, err = db.Query(ctx, fmt.Sprintf(`SELECT c.cceo_staff_id, count(*) FILTER (WHERE c.shared_at IS NOT NULL AND c.acknowledged_at IS NULL),
  count(*) FILTER (WHERE c.follow_up_due <= $%d::date AND c.follow_up_done_at IS NULL)
FROM cce_cceo_coaching c WHERE %s GROUP BY 1`, n+1, visible), append(append([]any{}, args...), today.Format(time.DateOnly))...)
	if err != nil {
		return f, fmt.Errorf("ccelead: counting each officer's coaching: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var id string
		var c [2]int
		if err := rows.Scan(&id, &c[0], &c[1]); err != nil {
			return f, fmt.Errorf("ccelead: counting each officer's coaching: %w", err)
		}
		f.open[id] = c
	}
	return f, rows.Err()
}

// oneToOnes is partials/coaching/one_to_ones.html over
// coaching.monthly_one_to_ones, last_coaching_by_cceo and per_officer_counts:
// each officer's one-to-one this month, their latest coaching and what is
// still open, with the held and due counts.
func oneToOnes(ctx context.Context, db schooldirectory.Querier, visible string, args []any, members []officer, today, monthStart time.Time, query url.Values) ([]*screensv1.PageBlock, int, int, error) {
	ids := []string{}
	for _, m := range members {
		ids = append(ids, m.staff)
	}
	f, err := readOfficerFigures(ctx, db, visible, args, ids, today, monthStart)
	if err != nil {
		return nil, 0, 0, err
	}
	dueFrom := time.Date(monthStart.Year(), monthStart.Month(), rules.OneToOneDueDay, 0, 0, 0, 0, time.UTC)
	month := monthStart.Format("January")
	title := month + " one-to-ones"
	t := &screensv1.PageTable{}
	nHeld, nDue := 0, 0
	for _, m := range members {
		label, isHeld := "Due from "+dueFrom.Format("2 Jan"), false
		if on, ok := f.held[m.staff]; ok {
			label, isHeld = "Held "+on.Format("2 Jan"), true
			nHeld++
		} else if !today.Before(dueFrom) {
			label = "Due"
			nDue++
		}
		lastText := "Not coached yet"
		if on, ok := f.last[m.staff]; ok {
			lastText = on.Format("2 Jan") + " · " + kindLabel(f.lastKind[m.staff])
		}
		name := m.name
		if name == "" {
			name = "Officer"
		}
		logLabel, logQuery := "Log one-to-one", "cceo="+url.QueryEscape(m.staff)+"&kind="+url.QueryEscape(rules.OneToOneKind)
		if isHeld {
			logLabel, logQuery = "Log coaching", "cceo="+url.QueryEscape(m.staff)
		}
		t.Rows = append(t.Rows, &screensv1.PageRow{Cells: []*screensv1.PageCell{
			{Text: closedschools.Collapse(name)}, {Text: label}, {Text: closedschools.Collapse(lastText)},
			{Text: strconv.Itoa(f.open[m.staff][0])}, {Text: strconv.Itoa(f.open[m.staff][1])},
			{Actions: []*screensv1.PageAction{
				{Key: "menu", Label: logLabel, Enabled: true, Href: TeamCoachingPath + "/new?" + logQuery, Drawer: true},
				{Key: "menu", Label: "History", Enabled: true, Href: TeamCoachingPath + "?cceo=" + url.QueryEscape(m.staff)},
			}},
		}})
	}
	if len(t.Rows) == 0 {
		t.EmptyMessage = "No officers on your team"
		t.Rows = []*screensv1.PageRow{{Cells: []*screensv1.PageCell{{Text: "No officers on your team Officers appear here once HR records you as their supervisor."}}}}
		return []*screensv1.PageBlock{panel(title), {Kind: &screensv1.PageBlock_Table{Table: t}}}, nHeld, nDue, nil
	}
	for _, c := range []string{"Officer", month + " one-to-one", "Last coaching", "Awaiting acknowledgement", "Follow-ups due", ""} {
		t.Columns = append(t.Columns, &screensv1.PageColumn{Label: c})
	}
	all := t.Rows
	number, pages := closedschools.PageOf(query.Get("one_to_one_page"), len(all), rules.PageSize)
	t.Rows = all[(number-1)*rules.PageSize : min(number*rules.PageSize, len(all))]
	blocks := []*screensv1.PageBlock{panel(title), {Kind: &screensv1.PageBlock_Table{Table: t}}}
	if pages > 1 {
		blocks = append(blocks, closedschools.PagerPanel("one_to_one_page", number, pages, len(all), rules.PageSize, query, rules.QueryKeysNotPassed))
	}
	return blocks, nHeld, nDue, nil
}
