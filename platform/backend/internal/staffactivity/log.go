package staffactivity

import (
	"context"
	"sort"
	"strings"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/calendarpage"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// person is one row of the log (services._people).
type person struct {
	id, name, role, title, supervisor, region string
	logins                                    int
	firstActive, lastActive                   *time.Time
	seconds                                   int64
	sections                                  spent
	lastPage                                  string
	lastAction                                string
	lastActionAt                              *time.Time
	actions, failed, schools                  int
	schoolIDs                                 map[string]bool
	status                                    string
	expected, leaveDays                       int
	openFollowUps                             int
	usageKey, usageLabel                      string
	suggestions                               int
	lead                                      *lead
}

// filters are the page's own: role, Programme Lead, status and the search.
type filters struct {
	period, on, role, programLead, status, q string
}

// theLog is activity_log's answer for a country reader.
type theLog struct {
	period        period
	everyone      []*person
	people        []*person
	total         int
	roleOptions   [][2]string
	leadOptions   [][2]string
	filters       filters
	canFollowUp   bool
	followUpCount int
	insights      insights
	today         time.Time
}

// credit is presence._credit_for: all of a gap while the person was active,
// the final-beat credit when they had gone idle or left in between.
func credit(gap float64) int64 {
	if gap <= 0 {
		return 0
	}
	if gap <= float64(rules.Thresholds.IdleSeconds) {
		return int64(gap)
	}
	return rules.Thresholds.FinalBeatSeconds
}

// buildPeople is services._people for the ids in scope.
func buildPeople(ctx context.Context, db schooldirectory.Querier, ids []string, p period, now, today time.Time) ([]*person, error) {
	if len(ids) == 0 {
		return nil, nil
	}
	startDT, endDT := p.bounds()
	accounts, err := readAccounts(ctx, db, ids)
	if err != nil {
		return nil, err
	}
	ids = ids[:0:0]
	districts, profiles, loginIDs := []string{}, []string{}, []string{}
	for _, a := range accounts {
		ids = append(ids, a.id)
		if a.districtID != nil && *a.districtID != "" {
			districts = append(districts, *a.districtID)
		}
		if a.profileID != nil && *a.profileID != "" {
			profiles = append(profiles, *a.profileID)
		}
		if a.loginID != nil && *a.loginID != "" {
			loginIDs = append(loginIDs, *a.loginID)
		}
	}
	signs, err := readSignins(ctx, db, ids, startDT, endDT)
	if err != nil {
		return nil, err
	}
	times, err := readSpent(ctx, db, ids, p)
	if err != nil {
		return nil, err
	}
	acts, err := readActions(ctx, db, ids, startDT, endDT)
	if err != nil {
		return nil, err
	}
	supervisors, err := supervisorNames(ctx, db, ids)
	if err != nil {
		return nil, err
	}
	regionOf, err := regions(ctx, db, districts)
	if err != nil {
		return nil, err
	}
	holidays, err := calendarpage.PublicHolidayDays(ctx, db, p.start, p.end)
	if err != nil {
		// A year the national calendar does not cover.
		return nil, errPassOn
	}
	leave, err := leaveDays(ctx, db, profiles)
	if err != nil {
		return nil, err
	}
	follow, err := openFollowUps(ctx, db, ids)
	if err != nil {
		return nil, err
	}
	ended, err := signedOut(ctx, db, loginIDs)
	if err != nil {
		return nil, err
	}
	onlineAfter := now.Add(-time.Duration(rules.Thresholds.OnlineSeconds) * time.Second)
	sessionAfter := now.Add(-time.Duration(rules.Thresholds.SessionCookieAge) * time.Second)

	people := make([]*person, 0, len(accounts))
	for _, a := range accounts {
		name := str(a.name)
		if name == "" {
			name = a.email
		}
		x := &person{id: a.id, name: name, role: a.role, supervisor: supervisors[a.id], openFollowUps: follow[a.id]}
		x.title = a.role
		if t, ok := rules.RoleTitles[a.role]; ok {
			x.title = t
		} else if a.role == "" {
			x.title = "—"
		}
		if a.districtID != nil {
			x.region = regionOf[*a.districtID]
		}
		if t := times[a.id]; t != nil {
			x.sections = spent{sections: append([]string{}, t.sections...), by: map[string]int64{}}
			for k, v := range t.by {
				x.sections.by[k] = v
			}
			x.seconds = t.seconds
		}
		path := str(a.path)
		if a.lastSeen != nil && path != "" && !untracked(path) {
			if d := dateOf(*a.lastSeen); !d.Before(p.start) && !d.After(p.end) {
				pending := credit(now.Sub(*a.lastSeen).Seconds())
				x.seconds += pending
				x.sections.add(runes(sectionFor(path), 64), pending)
			}
		}
		s := signs[a.id]
		if s == nil {
			s = &signins{}
		}
		x.logins = s.n
		switch {
		case s.sessionFirst != nil:
			first := *s.sessionFirst
			if first.Before(startDT) {
				first = startDT
			}
			x.firstActive = &first
		default:
			x.firstActive = s.first
		}
		switch {
		case a.lastSeen != nil && !a.lastSeen.Before(startDT) && a.lastSeen.Before(endDT):
			x.lastActive = a.lastSeen
		case s.sessLast != nil:
			last := *s.sessLast
			if last.After(endDT) {
				last = endDT
			}
			x.lastActive = &last
		}
		endedAt, signedOff := ended[a.id]
		switch {
		case signedOff && (a.lastSeen == nil || !endedAt.Before(*a.lastSeen)):
			x.status = "offline"
		case a.lastSeen != nil && !a.lastSeen.Before(onlineAfter):
			x.status = "online"
		case a.lastSeen != nil && !a.lastSeen.Before(sessionAfter) && path != "":
			x.status = "idle"
		default:
			x.status = "offline"
		}
		own := map[time.Time]bool{}
		if a.profileID != nil {
			if l := leave[*a.profileID]; l != nil {
				own = l
			}
		}
		if x.status == "offline" && own[today] {
			x.status = "on_leave"
		}
		for d := p.start; !d.After(p.elapsed); d = d.AddDate(0, 0, 1) {
			if weekday(d) < 5 && !holidays[d.Format(time.DateOnly)] {
				if own[d] {
					x.leaveDays++
				} else {
					x.expected++
				}
			}
		}
		if ac := acts[a.id]; ac != nil {
			x.actions, x.failed, x.lastAction, x.lastActionAt = ac.done, ac.failed, ac.lastLabel, ac.lastAt
			x.schoolIDs, x.schools = ac.schools, len(ac.schools)
		}
		x.lastPage = "—"
		if path != "" && !untracked(path) {
			x.lastPage = sectionFor(path)
		}
		people = append(people, x)
	}
	judgeUsage(people, p)
	sort.SliceStable(people, func(i, j int) bool {
		a, b := people[i], people[j]
		if (a.status != "online") != (b.status != "online") {
			return a.status == "online"
		}
		return pyLower(a.name) < pyLower(b.name)
	})
	return people, nil
}

// median is statistics.median.
func median(values []int64) float64 {
	v := append([]int64{}, values...)
	sort.Slice(v, func(i, j int) bool { return v[i] < v[j] })
	n := len(v)
	if n%2 == 1 {
		return float64(v[n/2])
	}
	return (float64(v[n/2-1]) + float64(v[n/2])) / 2
}

// judgeUsage is services._judge_usage: the Usage column and the follow-up
// suggestions, excessive time judged against colleagues in the same role.
func judgeUsage(people []*person, p period) {
	byRole := map[string][]int64{}
	for _, x := range people {
		if x.seconds != 0 {
			byRole[x.role] = append(byRole[x.role], x.seconds)
		}
	}
	roleMedian := map[string]float64{}
	for role, values := range byRole {
		if len(values) >= 3 {
			roleMedian[role] = median(values)
		}
	}
	t := rules.Thresholds
	for _, x := range people {
		suggestions := 0
		switch {
		case p.isFuture:
			x.usageKey, x.usageLabel = "not_expected", "Not yet"
		case x.expected == 0 && x.leaveDays > 0:
			x.usageKey, x.usageLabel = "on_leave", "On approved leave"
		case x.expected == 0:
			x.usageKey, x.usageLabel = "not_expected", "No expected activity"
		case x.logins == 0 && x.seconds == 0:
			x.usageKey, x.usageLabel = "no_login", "No login"
			suggestions++
		default:
			x.usageKey, x.usageLabel = "normal", "Normal"
		}
		if x.usageKey == "normal" {
			if x.actions == 0 && x.expected >= t.LowEngagementMinExpectedDays {
				suggestions++
			}
			if x.failed >= t.FailedActionsSuggestion {
				suggestions++
			}
			if m, ok := roleMedian[x.role]; ok && m != 0 && x.seconds >= t.ExcessiveTimeFloorSeconds &&
				float64(x.seconds) >= float64(t.ExcessiveTimeFactor)*m {
				suggestions++
			}
			if suggestions > 0 {
				x.usageKey, x.usageLabel = "follow_up", "Follow-up suggested"
			}
		}
		x.suggestions = suggestions
	}
}

func matchesStatus(x *person, status string) bool {
	switch status {
	case "follow_up":
		return x.suggestions > 0 || x.openFollowUps > 0
	case "no_login":
		return x.usageKey == "no_login"
	}
	return x.status == status
}

// narrow is activity_log's filter: the strip counts the rows the table
// lists.
func narrow(everyone []*person, f filters) []*person {
	out := []*person{}
	q := pyLower(f.q)
	for _, x := range everyone {
		if f.role != "" && x.role != f.role {
			continue
		}
		if f.programLead != "" && x.id != f.programLead && (x.lead == nil || x.lead.id != f.programLead) {
			continue
		}
		if f.status != "" && !matchesStatus(x, f.status) {
			continue
		}
		if f.q != "" && !strings.Contains(pyLower(x.name), q) {
			continue
		}
		out = append(out, x)
	}
	return out
}

// group is one of _groups' country groups.
type group struct {
	kind, label string
	order       [2]string
	lead        *person
	members     []*person
	total       int
	online      int
	seconds     int64
	actions     int
	noLogin     int
}

// groups is services._groups for the country: each Programme Lead's team
// under the Lead, then the CCEOs without one, then everyone else by role.
func groups(people []*person) []*group {
	byKey := map[string]*group{}
	order := []*group{}
	get := func(key, label, kind string, rank string, name string) *group {
		if g, ok := byKey[key]; ok {
			return g
		}
		g := &group{kind: kind, label: label, order: [2]string{rank, name}}
		byKey[key] = g
		order = append(order, g)
		return g
	}
	for _, x := range people {
		switch {
		case x.role == rules.Roles.ProgramLead:
			get("pl:"+x.id, x.name, "program_lead", "0", x.name).lead = x
		case x.lead != nil:
			g := get("pl:"+x.lead.id, x.lead.name, "program_lead", "0", x.lead.name)
			g.members = append(g.members, x)
		case x.role == rules.Roles.CCEO:
			g := get("cceo:unled", "CCEOs without a Program Lead", "cceo", "1", "")
			g.members = append(g.members, x)
		default:
			l, ok := label(rules.RoleFilterLabels, x.role)
			if !ok {
				l = x.role
				if l == "" {
					l = "Other"
				}
			}
			g := get("role:"+x.role, l, "role", "2", l)
			g.members = append(g.members, x)
		}
	}
	for _, g := range order {
		everyone := g.members
		if g.lead != nil {
			everyone = append([]*person{g.lead}, g.members...)
		}
		g.total = len(everyone)
		for _, x := range everyone {
			if x.status == "online" {
				g.online++
			}
			g.seconds += x.seconds
			g.actions += x.actions
			if x.usageKey == "no_login" {
				g.noLogin++
			}
		}
	}
	sort.SliceStable(order, func(i, j int) bool {
		a, b := order[i].order, order[j].order
		if a[0] != b[0] {
			return a[0] < b[0]
		}
		return a[1] < b[1]
	})
	return order
}

// kpis is services._kpis over the rows the table lists.
type kpis struct {
	expected, total, active int
	activeShare             *int
	noLogin                 int
	totalLabel, medianLabel string
	actions, schools        int
	openFollowUps           int
	suggested               int
}

func figures(people []*person) kpis {
	k := kpis{total: len(people), medianLabel: "0m"}
	expectedActive := 0
	seconds := []int64{}
	var sum int64
	schools := map[string]bool{}
	for _, x := range people {
		active := x.logins > 0 || x.seconds != 0
		if x.expected > 0 {
			k.expected++
			if active {
				expectedActive++
			}
		}
		if active {
			k.active++
			seconds = append(seconds, x.seconds)
			sum += x.seconds
		}
		if x.usageKey == "no_login" {
			k.noLogin++
		}
		k.actions += x.actions
		k.openFollowUps += x.openFollowUps
		if x.suggestions > 0 && x.openFollowUps == 0 {
			k.suggested++
		}
		for s := range x.schoolIDs {
			schools[s] = true
		}
	}
	if k.expected > 0 {
		s := share(int64(expectedActive), int64(k.expected))
		k.activeShare = &s
	}
	k.totalLabel = minutes(float64(sum))
	if len(seconds) > 0 {
		k.medianLabel = minutes(median(seconds))
	}
	k.schools = len(schools)
	return k
}

// insights is the Team Insights panel (services._insights).
type insights struct {
	status     [4]int
	statusKeys [4]string
	total      int
	modules    []module
	trend      []trendDay
	trendEnd   time.Time
	latest     bool
	devices    [3]int
	deviceSum  int
}

type module struct {
	label string
	share int
}

type trendDay struct {
	day   time.Time
	count int
}

var deviceKeys = [3][2]string{{"desktop", "Desktop"}, {"mobile", "Mobile"}, {"tablet", "Tablet"}}

func teamInsights(ctx context.Context, db schooldirectory.Querier, people []*person, p period, today time.Time) (insights, error) {
	in := insights{statusKeys: [4]string{"online", "idle", "offline", "on_leave"}, total: len(people)}
	ids := make([]string, 0, len(people))
	type mod struct {
		label   string
		seconds int64
	}
	mods := []mod{}
	at := map[string]int{}
	var all int64
	for _, x := range people {
		ids = append(ids, x.id)
		for i, k := range in.statusKeys {
			if x.status == k {
				in.status[i]++
			}
		}
		for _, s := range x.sections.sections {
			if i, ok := at[s]; ok {
				mods[i].seconds += x.sections.by[s]
			} else {
				at[s] = len(mods)
				mods = append(mods, mod{s, x.sections.by[s]})
			}
			all += x.sections.by[s]
		}
	}
	sort.SliceStable(mods, func(i, j int) bool { return mods[i].seconds > mods[j].seconds })
	top := mods
	if len(mods) > 5 {
		top = append([]mod{}, mods[:5]...)
		var rest int64
		for _, m := range mods[5:] {
			rest += m.seconds
		}
		top = append(top, mod{"Other", rest})
	}
	for _, m := range top {
		s := 0
		if all != 0 {
			s = share(m.seconds, all)
		}
		in.modules = append(in.modules, module{m.label, s})
	}
	in.trendEnd = p.elapsed
	in.latest = !p.elapsed.Before(today)
	from := p.elapsed.AddDate(0, 0, -6)
	perDay, err := trendCounts(ctx, db, ids, from, p.elapsed)
	if err != nil {
		return in, err
	}
	for i := 0; i < 7; i++ {
		d := from.AddDate(0, 0, i)
		in.trend = append(in.trend, trendDay{d, perDay[d]})
	}
	startDT, endDT := p.bounds()
	devices, err := deviceCounts(ctx, db, ids, startDT, endDT)
	if err != nil {
		return in, err
	}
	for _, n := range devices {
		in.deviceSum += n
	}
	for i, d := range deviceKeys {
		in.devices[i] = devices[d[0]]
	}
	return in, nil
}
