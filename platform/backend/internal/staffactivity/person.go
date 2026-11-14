package staffactivity

import (
	"context"
	"errors"
	"fmt"
	"net/url"
	"slices"
	"sort"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pagegate"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schoolprofile"
)

// PersonPrefix is a person's detail (staff_activity_person_view): the part
// of the log a row opens, partials/staff_activity/_person_detail.html.
const PersonPrefix = "/staff-activity/people/"

// personID is the <str:person_id> of a person's detail, ok false for any
// other path (a follow-up drawer below it is not this page).
func personID(path string) (string, bool) {
	id, ok := strings.CutPrefix(path, PersonPrefix)
	if !ok || id == "" || strings.Contains(id, "/") {
		return "", false
	}
	return id, true
}

// suggestNote is the sentence the template closes a follow-up suggestion
// with.
const suggestNote = "A suggestion is an offer to talk, not a judgement of performance."

// session is one line of the sign-in history.
type session struct {
	at           time.Time
	device       string
	span, active int64
	ended        string
}

// act is one action of fold_acts.
type act struct {
	at                    time.Time
	ok                    bool
	action                string
	label, module         string
	subjectKind, subjectI *string
}

// detail is services.person_detail's answer, as the template draws it.
type detail struct {
	x            *person
	p            period
	sessions     []session
	sessionTotal int
	modules      [][3]string // label, time, actions
	tasks        int
	timeline     []act
	actsTotal    int
	trend        []string
	loginDays    int
	followUps    [][3]string // id, trigger, status
	canFollowUp  bool
	today        time.Time
}

// personPage answers a person's detail. Go answers the country readers;
// a Programme Lead's team (team_user_ids: covers and acting seats) is the
// existing application's.
func (s *Service) personPage(ctx context.Context, p auth.Principal, id string, query url.Values) (*screensv1.GetPageResponse, bool, error) {
	doors, ok := rules.Doors[p.ActiveRole]
	if !ok || !doors.Person {
		return nil, true, pagegate.ErrNotAvailable
	}
	if p.ActiveRole == rules.Roles.ProgramLead {
		return nil, false, nil
	}
	if p.ActiveRole != rules.Roles.CountryDirector && p.ActiveRole != rules.Roles.Admin {
		// viewer_scope is None: nobody is in the reader's scope.
		return nil, true, pagegate.ErrForbidden
	}
	d, err := s.detail(ctx, p, id, query)
	if errors.Is(err, errPassOn) {
		return nil, false, nil
	}
	if err != nil {
		return nil, true, err
	}
	return personBlocks(d, id), true, nil
}

func (s *Service) detail(ctx context.Context, p auth.Principal, id string, query url.Values) (*detail, error) {
	country, err := readerCountry(ctx, s.db, p.UserID)
	if err != nil {
		return nil, err
	}
	roster, err := countryRoster(ctx, s.db, p.UserID, country)
	if err != nil {
		return nil, err
	}
	if !slices.Contains(roster, id) {
		return nil, pagegate.ErrForbidden
	}
	now := s.now()
	today := dateOf(now)
	chosen := choosePeriod(query.Get("period"), query.Get("on"), today)
	people, err := buildPeople(ctx, s.db, []string{id}, chosen, now, today)
	if err != nil {
		return nil, err
	}
	if len(people) == 0 {
		return nil, pagegate.ErrForbidden
	}
	d := &detail{x: people[0], p: chosen, today: today, canFollowUp: p.ActiveRole == rules.Roles.CountryDirector}
	for _, reason := range d.x.reasons {
		if _, ok := rules.Person.SuggestionReasons[reason]; !ok {
			// Excessive time is judged against three of a role; one person
			// never is. Its words are the existing application's.
			return nil, errPassOn
		}
	}
	startDT, endDT := chosen.bounds()
	if err := s.readSessions(ctx, d, id, now, today, startDT, endDT); err != nil {
		return nil, err
	}
	acts, err := readActs(ctx, s.db, id, startDT, endDT)
	if err != nil {
		return nil, err
	}
	d.actsTotal = len(acts)
	d.timeline = acts[:min(len(acts), rules.Person.ActionsShown)]
	for _, a := range d.timeline {
		if !a.ok {
			// A refused request is named by its audit row's reason, which
			// the gateway does not read (it holds sign-in and MFA reasons).
			return nil, errPassOn
		}
	}
	d.modules = moduleLines(d.x, acts)
	err = s.db.QueryRow(ctx, `SELECT COUNT(*) FROM (SELECT DISTINCT working_on FROM presence_time
WHERE user_id = $1 AND day >= $2 AND day <= $3) AS tasks`, id, chosen.start, chosen.end).Scan(&d.tasks)
	if err != nil {
		return nil, fmt.Errorf("staffactivity: counting the person's tasks: %w", err)
	}
	d.trend = trendLabels(chosen)
	err = s.db.QueryRow(ctx, `SELECT COUNT(DISTINCT (at AT TIME ZONE $4)::date) FROM login_event
WHERE user_id = $1 AND at >= $2 AND at < $3`, id, startDT, endDT, rules.TimeZone).Scan(&d.loginDays)
	if err != nil {
		return nil, fmt.Errorf("staffactivity: counting the person's sign-in days: %w", err)
	}
	if d.followUps, err = readFollowUps(ctx, s.db, id); err != nil {
		return nil, err
	}
	return d, nil
}

// readSessions is person_detail's sign-in history: the sessions of the
// period, newest first, the current one credited with the time since the
// person's last beat.
func (s *Service) readSessions(ctx context.Context, d *detail, id string, now, today, startDT, endDT time.Time) error {
	var lastSeen *time.Time
	var current *string
	if err := s.db.QueryRow(ctx, `SELECT last_seen_at, last_seen_login_id FROM "user" WHERE id = $1`, id).Scan(&lastSeen, &current); err != nil {
		return fmt.Errorf("staffactivity: reading the person's last beat: %w", err)
	}
	const where = `FROM login_event WHERE user_id = $1 AND at < $3 AND (at >= $2 OR last_active_at >= $2)`
	if err := s.db.QueryRow(ctx, `SELECT COUNT(*) `+where, id, startDT, endDT).Scan(&d.sessionTotal); err != nil {
		return fmt.Errorf("staffactivity: counting the person's sessions: %w", err)
	}
	timeout := time.Duration(rules.Thresholds.SessionCookieAge) * time.Second
	return collect(ctx, s.db, "the person's sessions", `SELECT id, at, device, active_seconds, last_active_at, ended_at `+where+`
ORDER BY at DESC LIMIT $4`, func(r pgx.Rows) error {
		var loginID, device string
		var at time.Time
		var active int64
		var lastActive, endedAt *time.Time
		if err := r.Scan(&loginID, &at, &device, &active, &lastActive, &endedAt); err != nil {
			return err
		}
		last := at
		if lastActive != nil {
			last = *lastActive
		}
		var end time.Time
		var ended string
		switch {
		case current != nil && loginID == *current && endedAt == nil && lastSeen != nil && now.Sub(*lastSeen) < timeout:
			active += credit(now.Sub(*lastSeen).Seconds())
			end, ended = now, "Current session"
		case endedAt != nil:
			end, ended = *endedAt, "Signed out "+clock(endedAt, today)
		default:
			end, ended = last, "Timed out after "+clock(&last, today)
		}
		span := max(0, int64(end.Sub(at).Seconds()))
		if span != 0 {
			active = min(active, span)
		}
		if device == "" {
			device = "unknown"
		}
		d.sessions = append(d.sessions, session{at: at, device: pyTitle(device), span: span, active: active, ended: ended})
		return nil
	}, id, startDT, endDT, rules.Person.SessionsShown)
}

// readActs is fold_acts over the person's audit rows of the period (under
// every id the chain holds for them), newest first.
func readActs(ctx context.Context, db schooldirectory.Querier, id string, start, end time.Time) ([]act, error) {
	owners, err := identities(ctx, db, []string{id})
	if err != nil {
		return nil, err
	}
	actors := make([]string, 0, len(owners))
	for actor := range owners {
		actors = append(actors, actor)
	}
	all, _, _ := meaningfulKeys()
	rows := []auditRow{}
	err = collect(ctx, db, "the person's actions", `
SELECT id, action, success, created_at, correlation_id, subject_kind, subject_id FROM audit_log
WHERE actor_id = ANY($1) AND created_at >= $2 AND created_at < $3 AND (action = ANY($4) OR action = ANY($5))
ORDER BY created_at DESC`, func(r pgx.Rows) error {
		var x auditRow
		if err := r.Scan(&x.id, &x.action, &x.success, &x.at, &x.correlation, &x.kind, &x.subject); err != nil {
			return err
		}
		rows = append(rows, x)
		return nil
	}, actors, start, end, all, rules.FailedRequestActions)
	if err != nil {
		return nil, err
	}
	return foldActs(rows), nil
}

// auditRow is one audit row of a person's period.
type auditRow struct {
	id, action                 string
	success                    bool
	at                         time.Time
	correlation, kind, subject *string
}

// foldActs is fold_acts: rows one request wrote about one record are one
// action, named by the row that is not an echo; a refused request stands
// alone, failed.
func foldActs(rows []auditRow) []act {
	index := map[string]int{}
	out := []act{}
	for _, x := range rows {
		definition, meaningful := rules.MeaningfulActions[x.action]
		done := meaningful && x.success
		key := "\x00" + x.id
		if done {
			first := str(x.correlation)
			if first == "" {
				first = x.id
			}
			key = first + "\x00" + str(x.kind) + "\x00" + str(x.subject)
		}
		at, seen := index[key]
		if !seen {
			a := act{at: x.at, ok: done, action: x.action, subjectKind: x.kind, subjectI: x.subject, label: "A request failed"}
			if done {
				a.label, a.module = definition.Label, definition.Module
			}
			index[key] = len(out)
			out = append(out, a)
			continue
		}
		if prev := rules.MeaningfulActions[out[at].action]; prev.Secondary && !definition.Secondary {
			// The echo was read first: the action is named by this row.
			out[at].action, out[at].label, out[at].module = x.action, definition.Label, definition.Module
		}
	}
	return out
}

// moduleLines is person_detail's time by part of the platform: every part
// with time or actions, the most time first, then by name.
func moduleLines(x *person, acts []act) [][3]string {
	actions := map[string]int{}
	for _, a := range acts {
		if a.ok {
			actions[a.module]++
		}
	}
	names := []string{}
	for name := range x.sections.by {
		names = append(names, name)
	}
	for name := range actions {
		if _, ok := x.sections.by[name]; !ok {
			names = append(names, name)
		}
	}
	sort.Slice(names, func(i, j int) bool {
		a, b := x.sections.by[names[i]], x.sections.by[names[j]]
		if a != b {
			return a > b
		}
		return names[i] < names[j]
	})
	out := make([][3]string, len(names))
	for i, name := range names {
		out[i] = [3]string{name, minutes(float64(x.sections.by[name])), fmt.Sprintf("%d action%s", actions[name], plural(actions[name]))}
	}
	return out
}

// trendLabels is _person_trend's bars as the feed reads them (each bar's
// label; its figures are a title and words for screen readers): a bar a day
// up to a month, a week up to 100 days, a month beyond.
func trendLabels(p period) []string {
	start, end := p.start, p.elapsed
	if end.Before(start) {
		return nil
	}
	days := int(end.Sub(start).Hours()/24) + 1
	bucket := func(d time.Time) time.Time { return d.AddDate(0, 0, -weekday(d)) }
	label := func(d time.Time) string { return d.Format("02 Jan") }
	switch {
	case days <= 31:
		bucket = func(d time.Time) time.Time { return d }
		label = func(d time.Time) string {
			if days > 7 {
				return d.Format("Mon 02")
			}
			return d.Format("Mon")
		}
	case days > 100:
		bucket = func(d time.Time) time.Time { return civil(d.Year(), d.Month(), 1) }
		label = func(d time.Time) string { return d.Format("Jan") }
	}
	out := []string{}
	var last time.Time
	for d := start; !d.After(end); d = d.AddDate(0, 0, 1) {
		if k := bucket(d); len(out) == 0 || !k.Equal(last) {
			out, last = append(out, label(k)), k
		}
	}
	return out
}

// readFollowUps are the person's latest follow-ups, newest first.
func readFollowUps(ctx context.Context, db schooldirectory.Querier, id string) ([][3]string, error) {
	out := [][3]string{}
	err := collect(ctx, db, "the person's follow-ups", `SELECT f.id, f.trigger, f.status, f.due_date FROM staff_usage_follow_up f
WHERE f.subject_id = $1 ORDER BY f.created_at DESC LIMIT $2`, func(r pgx.Rows) error {
		var fid, trigger, status string
		var due time.Time
		if err := r.Scan(&fid, &trigger, &status, &due); err != nil {
			return err
		}
		out = append(out, [3]string{fid, choice(rules.Person.FollowUpTriggers, trigger), choice(rules.Person.FollowUpStatuses, status) + " · due " + jM(due)})
		return nil
	}, id, rules.Person.FollowUpsShown)
	return out, err
}

// choice is a model field's get_FOO_display: the label, else the value.
func choice(pairs [][2]string, value string) string {
	if l, ok := label(pairs, value); ok {
		return l
	}
	return value
}

// jM is Django's date filter "j M": the day without a leading zero and the
// month's short name.
func jM(d time.Time) string { return fmt.Sprintf("%d %s", d.Day(), d.Format("Jan")) }

// collapse is the reader's whitespace: runs of spaces as one, none at the
// ends.
func collapse(s string) string { return strings.Join(strings.Fields(s), " ") }

// personBlocks is _person_detail.html as the feed reads it.
func personBlocks(d *detail, id string) *screensv1.GetPageResponse {
	x := d.x
	status, _ := label(rules.StatusOptions, x.status)
	if status == "" {
		status = "Offline"
	}
	subtitle := x.title
	if x.region != "" {
		subtitle += " · " + x.region
	}
	if x.supervisor != "" {
		subtitle += " · Reports to " + x.supervisor
	}
	top := []*screensv1.PagePanelItem{
		text(initials(x.name)),
		text("Logins"), text(fmt.Sprint(x.logins)),
		text("Active time"), text(minutes(float64(x.seconds))),
		text("Meaningful actions"), text(fmt.Sprint(x.actions)),
		text("Schools acted on"), text(fmt.Sprint(x.schools)),
	}
	if d.canFollowUp {
		top = append(top, &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Links{Links: &screensv1.PageLinks{Links: []*screensv1.PageLink{{
			Text: "Follow up", Drawer: true,
			Href: fmt.Sprintf("%s%s/follow-up?period=%s&on=%s", PersonPrefix, x.id, d.p.key, d.p.on.Format(time.DateOnly)),
		}}}}})
	}
	top = append(top, text("×"))
	blocks := []*screensv1.PageBlock{block(&screensv1.PagePanel{
		Title: collapse(x.name + " " + status), Subtitle: collapse(subtitle), Items: schoolprofile.PairedItems(top),
	})}
	if len(x.reasons) > 0 {
		reasons := make([]string, len(x.reasons))
		for i, key := range x.reasons {
			reasons[i] = strings.ReplaceAll(rules.Person.SuggestionReasons[key], "{}", fmt.Sprint(x.failed))
		}
		lead := "Follow-up suggested:"
		blocks = append(blocks, block(&screensv1.PagePanel{Items: []*screensv1.PagePanelItem{{
			Kind: &screensv1.PagePanelItem_Text{Text: collapse(lead + " " + strings.Join(reasons, "; ") + ". " + suggestNote)}, Lead: lead,
		}}}))
	}
	blocks = append(blocks, block(&screensv1.PagePanel{Items: schoolprofile.PairedItems(quads(d))}))
	return &screensv1.GetPageResponse{Header: &screensv1.PageHeader{}, Blocks: blocks, WebPath: PersonPrefix + id}
}

// quads are the template's four boxes, read as one panel.
func quads(d *detail) []*screensv1.PagePanelItem {
	x := d.x
	items := []*screensv1.PagePanelItem{heading("Sign-in history")}
	sub := fmt.Sprintf("%d session%s", d.sessionTotal, plural(d.sessionTotal))
	if d.sessionTotal > len(d.sessions) {
		sub = fmt.Sprintf("Latest %d of %d sessions", len(d.sessions), d.sessionTotal)
	}
	items = append(items, text(sub+" · "+d.p.label))
	if len(d.sessions) > 0 {
		lines := make([]string, len(d.sessions))
		for i, s := range d.sessions {
			lines[i] = collapse(fmt.Sprintf("%s · %s Active %s · Idle %s · Span %s %s", s.at.In(zone).Format("Mon 02 Jan 2006, 15:04"), s.device,
				minutes(float64(s.active)), minutes(float64(max(0, s.span-s.active))), minutes(float64(s.span)), s.ended))
		}
		items = append(items, links(lines))
	} else {
		items = append(items, text("No sessions in this period."))
	}

	items = append(items, heading("Time by module"),
		text(fmt.Sprintf("%d task%s across %d part%s of the platform", d.tasks, plural(d.tasks), len(d.modules), plural(len(d.modules)))))
	if len(d.modules) > 0 {
		lines := []string{"ModuleShareActiveActions"}
		for _, m := range d.modules {
			lines = append(lines, collapse(m[0]+m[1]+m[2]))
		}
		items = append(items, links(lines))
	} else {
		items = append(items, text("No active time in this period."))
	}

	sub = fmt.Sprintf("%d in the period", d.actsTotal)
	if d.actsTotal > len(d.timeline) {
		sub = fmt.Sprintf("Latest %d of %d", len(d.timeline), d.actsTotal)
	}
	sub += fmt.Sprintf(" · %d done", x.actions)
	if x.failed > 0 {
		sub += fmt.Sprintf(", %d failed", x.failed)
	}
	items = append(items, heading("Meaningful actions"), text(sub+" · page views are not actions"))
	if len(d.timeline) > 0 {
		out := make([]*screensv1.PageLink, len(d.timeline))
		for i, a := range d.timeline {
			if href := recordLink(a); href != "" {
				out[i] = &screensv1.PageLink{Text: collapse(a.label), Href: href}
			} else {
				out[i] = &screensv1.PageLink{Text: collapse(clock(&a.at, d.today) + " " + a.label + " " + a.module)}
			}
		}
		items = append(items, &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Links{Links: &screensv1.PageLinks{Links: out}}})
	} else {
		items = append(items, text("No meaningful actions in this period."))
	}

	items = append(items, heading("Period trend"), text(fmt.Sprintf("Signed in on %d day%s · active time and actions", d.loginDays, plural(d.loginDays))))
	if len(d.trend) > 0 {
		items = append(items, links(d.trend))
	}
	items = append(items, heading("Manager follow-up"))
	if len(d.followUps) > 0 {
		out := make([]*screensv1.PageLink, len(d.followUps))
		for i, f := range d.followUps {
			out[i] = &screensv1.PageLink{Text: collapse(f[1]), Href: "/staff-activity/follow-ups/" + f[0]}
		}
		items = append(items, &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Links{Links: &screensv1.PageLinks{Links: out}}})
	} else {
		items = append(items, text("No follow-ups."))
	}
	return items
}

// recordLink is registry.record_link: the page a timeline row opens.
func recordLink(a act) string {
	subject := str(a.subjectI)
	if subject == "" {
		return ""
	}
	switch {
	case slices.Contains(rules.SchoolSubjects, str(a.subjectKind)):
		return "/schools/" + subject
	case slices.Contains(rules.ActivitySubjects, str(a.subjectKind)):
		return "/activities/" + subject
	}
	return ""
}
