package teamperformance

import (
	"context"
	"sort"
	"strconv"
	"strings"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// report is report.Report: one reader's report for one period.
type report struct {
	ledger     *ledger
	book       *targetBook
	roster     *roster
	period     period
	breakdowns map[[3]string]*breakdown
	spreads    map[string]map[string]map[string]*counter
}

func buildReport(ctx context.Context, db schooldirectory.Querier, p auth.Principal, per period) (*report, error) {
	visible, err := visibleStaff(ctx, db, p)
	if err != nil {
		return nil, err
	}
	l, err := loadLedger(ctx, db, per.fy, visible)
	if err != nil {
		return nil, err
	}
	book, err := loadTargets(ctx, db, per.fy)
	if err != nil {
		return nil, err
	}
	ro, err := buildRoster(ctx, db, p, visible, l)
	if err != nil {
		return nil, err
	}
	return &report{ledger: l, book: book, roster: ro, period: per, breakdowns: map[[3]string]*breakdown{}}, nil
}

// cell is report.Cell.
type cell struct {
	target, achieved, planned *float64
}

func (c cell) variance() *float64 { return variance(c.achieved, c.target) }
func (c cell) pct() *float64      { return share(c.achieved, c.target) }

// ── Scopes ──────────────────────────────────────────────────────────────────

func (r *report) owners(s scope) map[string]bool {
	if s.kind == "country" {
		if r.roster.narrowed() {
			out := map[string]bool{}
			for _, o := range r.roster.officers() {
				out[o.staffID] = true
			}
			return out
		}
		return nil
	}
	return s.staff
}

func (r *report) home() scope {
	if r.roster.own() && len(r.roster.officers()) > 0 {
		return officerScope(r.roster.officers()[0].staffID)
	}
	if r.roster.lead != "" {
		if t := r.roster.team(r.roster.lead); t != nil {
			return regionScope(r.roster.lead, t.staffIDs())
		}
		return regionScope(r.roster.lead, nil)
	}
	if r.roster.narrowed() {
		return regionScope("", nil)
	}
	return countryScope()
}

func (r *report) teamScope(t *team) scope {
	if r.roster.own() && len(t.officers) > 0 {
		return officerScope(t.officers[0].staffID)
	}
	return regionScope(t.key, t.staffIDs())
}

type scopeOption struct {
	key, label string
	scope      scope
}

func (r *report) scopes() []scopeOption {
	out := []scopeOption{}
	if r.roster.own() {
		for _, o := range r.roster.officers() {
			out = append(out, scopeOption{o.staffID, o.name, officerScope(o.staffID)})
		}
		return out
	}
	if !r.roster.narrowed() {
		out = append(out, scopeOption{"country", "Country", countryScope()})
	}
	for _, t := range r.roster.teams {
		out = append(out, scopeOption{"region:" + t.key, "Team · " + t.label, regionScope(t.key, t.staffIDs())})
	}
	for _, o := range r.roster.officers() {
		out = append(out, scopeOption{o.staffID, o.name, officerScope(o.staffID)})
	}
	return out
}

func (r *report) scopeFor(key string) scopeOption {
	options := r.scopes()
	if len(options) == 0 {
		return scopeOption{"home", r.roster.homeLabel(), r.home()}
	}
	for _, o := range options {
		if o.key == key {
			return o
		}
	}
	return options[0]
}

// ── One figure ──────────────────────────────────────────────────────────────

func (r *report) count(key string, s scope, w window) *float64 {
	return fptr(r.ledger.count(key, r.owners(s), w))
}

func (r *report) planned(key string, s scope, w window) *float64 {
	return fptr(r.ledger.plannedCount(key, r.owners(s), w))
}

func (r *report) eligible(m *measure, s scope) *int {
	if m.Basis == "" {
		return nil
	}
	return iptr(r.ledger.portfolio(r.owners(s), m.Basis, nil))
}

func (r *report) target(m *measure, s scope) target {
	return r.book.targetOf(m, s, r.eligible(m, s))
}

// weeklyRow is one Detailed Country Report row (Report.row).
type weeklyRow struct {
	m        *measure
	target   target
	month    cell
	quarters []quarterCell
	year     cell
	status   string
	phased   bool
}

type quarterCell struct {
	q       int
	future  bool
	planned *float64
	cell    cell
}

func (r *report) row(m *measure, s scope) weeklyRow {
	per := r.period
	t := r.target(m, s)
	level := t.source == rules.Eligible
	month := cell{nil, r.count(m.Key, s, per.monthSpan()), r.planned(m.Key, s, per.monthSpan())}
	if !level {
		month.target = t.month(per.month)
	}
	quarters := []quarterCell{}
	for q := 1; q <= 4; q++ {
		w := per.through(q * 3)
		if !per.quarterStarted(q) {
			quarters = append(quarters, quarterCell{q: q, future: true, planned: r.planned(m.Key, s, w)})
			continue
		}
		qt := t.through(q * 3)
		if level {
			qt = t.annual
		}
		quarters = append(quarters, quarterCell{q: q, cell: cell{qt, r.count(m.Key, s, w), r.planned(m.Key, s, w)}})
	}
	year := cell{t.annual, r.count(m.Key, s, per.now()), r.planned(m.Key, s, window{per.fyStart(), per.fyEnd()})}
	return weeklyRow{m: m, target: t, month: month, quarters: quarters, year: year,
		status: statusOf(year.pct(), per.today.Before(per.fyEnd())), phased: t.months != nil}
}

// ── Executive Summary ───────────────────────────────────────────────────────

func sectionIndex(section string) int {
	for i, s := range rules.Sections {
		if s == section {
			return i
		}
	}
	return len(rules.Sections)
}

func (r *report) areas() []*measure {
	out := []*measure{}
	for i := range rules.Measures {
		m := &rules.Measures[i]
		if m.Tracked && (m.Milestone != "" || m.Basis != "") && m.Key != "dc_data" {
			out = append(out, m)
		}
	}
	sort.SliceStable(out, func(i, j int) bool { return sectionIndex(out[i].Section) < sectionIndex(out[j].Section) })
	return out
}

func areaLabel(m *measure, all []*measure) string {
	n := 0
	for _, x := range all {
		if x.Label == m.Label {
			n++
		}
	}
	if n > 1 && m.Slice != "" {
		return m.Label + " – " + pyTitle(m.Slice)
	}
	return m.Label
}

func pyTitle(s string) string {
	if s == "" {
		return s
	}
	return strings.ToUpper(s[:1]) + strings.ToLower(s[1:])
}

type figures map[string]*float64

func (r *report) summaryFigures(s scope, w window) figures {
	owners := r.owners(s)
	f := figures{
		"portfolio": ptr(float64(r.ledger.portfolio(owners, "all", &w.end))),
		"active":    ptr(float64(r.ledger.portfolio(owners, "active", &w.end))),
		"dc_data":   r.count("dc_data", s, w),
		"dc":        r.count("dc_clubs", s, w),
	}
	for _, m := range r.areas() {
		t := r.target(m, s).annual
		achieved := r.count(m.Key, s, w)
		f[m.Key] = achieved
		f[m.Key+"_target"] = t
		f[m.Key+"_pct"] = share(achieved, t)
	}
	f["inactive"] = ptr(*f["portfolio"] - *f["active"])
	f["active_pct"] = share(f["active"], f["portfolio"])
	f["dc_pct"] = share(f["dc"], f["dc_data"])
	return f
}

type area struct {
	key, label, status string
	m                  *measure
	target, achieved   *float64
	pct, change        *float64
	teams              []columnCell
	charts             []areaChart
}

type areaChart struct {
	level, label string
	bars         []bar
}

type summary struct {
	now, before figures
	change      map[string]*float64
	bd          *breakdown
	sections    []sectionAreas
	milestones  []deliveryLine
}

type sectionAreas struct {
	section string
	areas   []*area
}

func (r *report) executiveSummary(by, inRegion, inLead string) summary {
	per := r.period
	home := r.home()
	now := r.summaryFigures(home, per.toDate())
	before := r.summaryFigures(home, per.before())
	bd := r.resolve(by, inRegion, inLead)
	all := r.areas()
	counted := []string{"portfolio", "active", "dc_data", "dc"}
	for _, m := range all {
		counted = append(counted, m.Key)
	}
	change := map[string]*float64{}
	for _, key := range counted {
		// isinstance(..., int): a count, never a missing figure.
		if now[key] != nil && before[key] != nil {
			change[key] = ptr(*now[key] - *before[key])
		}
	}
	sections := []sectionAreas{}
	at := map[string]int{}
	for _, m := range all {
		a := r.areaOf(m, all, now, bd)
		a.change = change[m.Key]
		i, ok := at[m.Section]
		if !ok {
			i = len(sections)
			at[m.Section] = i
			sections = append(sections, sectionAreas{section: m.Section})
		}
		sections[i].areas = append(sections[i].areas, a)
	}
	return summary{now: now, before: before, change: change, bd: bd, sections: sections, milestones: r.deliveryMilestones(home)}
}

// sectionCharts is Report.section_charts; nil for a section the report does
// not have.
func (r *report) sectionCharts(section, by, inRegion, inLead string) []*area {
	all := r.areas()
	rows := []*measure{}
	for _, m := range all {
		if m.Section == section {
			rows = append(rows, m)
		}
	}
	if len(rows) == 0 {
		return nil
	}
	now := r.summaryFigures(r.home(), r.period.toDate())
	bd := r.resolve(by, inRegion, inLead)
	shown := []*breakdown{bd}
	if under := r.under(bd); under != nil {
		shown = append(shown, under)
	}
	out := []*area{}
	for _, m := range rows {
		a := r.areaOf(m, all, now, bd)
		for _, b := range shown {
			a.charts = append(a.charts, areaChart{level: b.level, label: b.label(), bars: b.bars(m.Key)})
		}
		out = append(out, a)
	}
	return out
}

func (r *report) areaOf(m *measure, all []*measure, now figures, bd *breakdown) *area {
	s := now[m.Key+"_pct"]
	a := &area{key: m.Key, label: areaLabel(m, all), m: m, target: now[m.Key+"_target"], achieved: now[m.Key],
		pct: s, status: statusOf(s, true)}
	for _, c := range bd.columns {
		a.teams = append(a.teams, c.cell(m.Key))
	}
	return a
}

// counter is a collections.Counter that remembers the order its keys came.
type counter struct {
	order []string
	n     map[string]int
}

func (c *counter) inc(key string) {
	if c.n == nil {
		c.n = map[string]int{}
	}
	if _, ok := c.n[key]; !ok {
		c.order = append(c.order, key)
	}
	c.n[key]++
}

// ordered is a dict of ints that keeps insertion order.
type ordered struct {
	order []string
	n     map[string]int
}

func newOrdered(keys []string) *ordered {
	o := &ordered{n: map[string]int{}}
	for _, k := range keys {
		o.set(k, 0)
	}
	return o
}

func (o *ordered) set(key string, v int) {
	if _, ok := o.n[key]; !ok {
		o.order = append(o.order, key)
	}
	o.n[key] = v
}

func (o *ordered) addTo(key string, v int) { o.set(key, o.n[key]+v) }

// placeSplit is Report.place_split: (places, target, achieved).
func (r *report) placeSplit(key, level string) ([]string, *ordered, *ordered) {
	m := byKey[key]
	l := r.ledger
	home := r.home()
	owners := r.owners(home)
	var every []string
	if level == "region" {
		every = append([]string{}, l.regions...)
	} else {
		places, _ := l.placesOf(owners, level)
		for p := range places {
			every = append(every, p)
		}
		sort.Strings(every)
	}
	tgt, ach := newOrdered(every), newOrdered(every)
	participants := m.Unit == unitParticipants
	w := r.period.toDate()
	var counted map[string]int
	var order []string
	if kind, ok := rules.PortfolioSources[m.Source]; ok {
		counted = map[string]int{}
		for _, pk := range l.portfolioSchools(owners, kind, &w.end) {
			if _, seen := counted[pk]; !seen {
				order = append(order, pk)
			}
			counted[pk] = 1
		}
	} else {
		counted, order = l.units(m.Key, owners, w)
	}
	for _, unit := range order {
		place := l.placeOf(unit, level)
		if place == "" {
			place = rules.NotPlaced
		}
		qty := 1
		if participants {
			qty = counted[unit]
		}
		ach.addTo(place, qty)
	}
	placed := 0
	family := familyOf(m)
	for _, staff := range r.holdersOf(m, owners) {
		annual := r.target(m, officerScope(staff)).annual
		if annual == nil || *annual == 0 {
			continue
		}
		portion := int(pyRoundInt(*annual))
		placed += portion
		parts, partOrder := spread(portion, r.where(staff, family, level))
		for _, place := range partOrder {
			tgt.addTo(place, parts[place])
		}
	}
	if whole := r.target(m, home).annual; whole != nil && *whole != 0 && int(pyRoundInt(*whole)) > placed {
		tgt.addTo(rules.NotPlaced, int(pyRoundInt(*whole))-placed)
	}
	places := append([]string{}, every...)
	if tgt.n[rules.NotPlaced] != 0 || ach.n[rules.NotPlaced] != 0 {
		places = append(places, rules.NotPlaced)
	}
	return places, tgt, ach
}

func (r *report) holdersOf(m *measure, owners map[string]bool) []string {
	var holders []string
	if m.Milestone != "" {
		holders = r.book.holders(m.Milestone)
	} else {
		for _, o := range r.roster.officers() {
			holders = append(holders, o.staffID)
		}
	}
	if owners == nil {
		return holders
	}
	out := []string{}
	for _, h := range holders {
		if owners[h] {
			out = append(out, h)
		}
	}
	return out
}

// where is Report._where: the places an officer's schools of a family are
// in, by how many; all their schools when they hold none of it.
func (r *report) where(staff, family, level string) *counter {
	if r.spreads == nil {
		r.spreads = map[string]map[string]map[string]*counter{}
	}
	spreads := r.spreads[level]
	if spreads == nil {
		spreads = map[string]map[string]*counter{}
		for _, s := range r.ledger.order {
			if s.owner == noHolder {
				continue
			}
			place := s.place(level)
			if place == "" {
				place = rules.NotPlaced
			}
			held := spreads[s.owner]
			if held == nil {
				held = map[string]*counter{"all": {}, "core": {}, "client": {}}
				spreads[s.owner] = held
			}
			held["all"].inc(place)
			if s.core {
				held["core"].inc(place)
			} else {
				held["client"].inc(place)
			}
		}
		r.spreads[level] = spreads
	}
	held := spreads[staff]
	if held == nil {
		return &counter{}
	}
	if c := held[family]; c != nil && len(c.order) > 0 {
		return c
	}
	if c := held["all"]; c != nil {
		return c
	}
	return &counter{}
}

// familyOf is report._family.
func familyOf(m *measure) string {
	if m.Key == "core_recruitment" || m.Key == "ssa_core_baseline" {
		return "client"
	}
	for _, f := range []string{m.Basis, m.Slice} {
		switch f {
		case "client", "ssa_client":
			return "client"
		case "core", "core_continuing", "ssa_core":
			return "core"
		}
	}
	switch {
	case strings.HasPrefix(m.Key, "client_"):
		return "client"
	case strings.HasPrefix(m.Key, "core_"):
		return "core"
	}
	return "all"
}

// spread is report._spread: a whole number shared by weight, largest
// remainder first.
func spread(total int, weights *counter) (map[string]int, []string) {
	whole := 0
	for _, k := range weights.order {
		whole += weights.n[k]
	}
	if whole == 0 {
		return map[string]int{rules.NotPlaced: total}, []string{rules.NotPlaced}
	}
	exact := map[string]float64{}
	parts := map[string]int{}
	sum := 0
	for _, k := range weights.order {
		exact[k] = float64(total*weights.n[k]) / float64(whole)
		parts[k] = int(exact[k])
		sum += parts[k]
	}
	left := total - sum
	keys := append([]string{}, weights.order...)
	sort.SliceStable(keys, func(i, j int) bool {
		return exact[keys[i]]-float64(parts[keys[i]]) > exact[keys[j]]-float64(parts[keys[j]])
	})
	for i := 0; i < left && i < len(keys); i++ {
		parts[keys[i]]++
	}
	return parts, weights.order
}

// bar is one bar of a target-vs-achieved chart (report._bars).
type bar struct {
	label, place     string
	target, achieved *float64
	variance, pct    *float64
}

func bars(rows []bar) []bar {
	for i := range rows {
		rows[i].variance = variance(rows[i].achieved, rows[i].target)
		rows[i].pct = share(rows[i].achieved, rows[i].target)
	}
	return rows
}

// deliveryLine is one Program Delivery & Operational Milestones row.
type deliveryLine struct {
	label, key, status string
	target             target
	cell               cell
}

func (r *report) deliveryMilestones(s scope) []deliveryLine {
	out := []deliveryLine{}
	for _, d := range rules.Delivery {
		m := byKey[d.Key]
		t := r.target(m, s)
		c := cell{target: t.annual, achieved: r.count(d.Key, s, r.period.toDate())}
		out = append(out, deliveryLine{label: d.Label, key: d.Key, target: t, cell: c, status: statusOf(c.pct(), !d.Closes)})
	}
	return out
}

// ── Strategic Milestones ────────────────────────────────────────────────────

type strategicLine struct {
	spec             *strategicRow
	target           *target
	inPeriod, toDate cell
	year             cell
	status, tone     string
	tracker          [2]string
	unit             string
}

type milestoneSheet struct {
	domains      []domainLines
	count        int
	domainCount  int
	tracked      int
	toDateTarget float64
	pacing       *float64
}

type domainLines struct {
	domain string
	rows   []strategicLine
}

func (r *report) milestones() milestoneSheet {
	s := r.home()
	sheet := milestoneSheet{count: len(rules.Strategic)}
	toDate := 0.0
	targetValues, achievedValues := []float64{}, []float64{}
	for i := range rules.Strategic {
		spec := &rules.Strategic[i]
		line := r.strategicLine(spec, s)
		placed := false
		for j := range sheet.domains {
			if sheet.domains[j].domain == spec.Domain {
				sheet.domains[j].rows = append(sheet.domains[j].rows, line)
				placed = true
			}
		}
		if !placed {
			sheet.domains = append(sheet.domains, domainLines{spec.Domain, []strategicLine{line}})
		}
		if spec.Kind != rules.StrategicKinds.Untracked {
			sheet.tracked++
		}
		c := line.toDate
		if spec.Kind == rules.StrategicKinds.Count && c.target != nil && *c.target != 0 && c.achieved != nil {
			targetValues = append(targetValues, *c.target)
			achievedValues = append(achievedValues, *c.achieved)
		}
	}
	// to_date_target += cell.target: added one at a time from 0.
	total := 0.0
	for _, v := range targetValues {
		total += v
	}
	for _, v := range achievedValues {
		toDate += v
	}
	sheet.toDateTarget = total
	sheet.domainCount = len(sheet.domains)
	sheet.pacing = share(&toDate, &total)
	return sheet
}

func (r *report) strategicLine(spec *strategicRow, s scope) strategicLine {
	kinds := rules.StrategicKinds
	per := r.period
	owners := r.owners(s)
	var eligible *int
	if spec.Basis != "" {
		eligible = iptr(r.ledger.portfolio(owners, spec.Basis, nil))
	}
	achieved := func(w window) *float64 {
		if len(spec.Measures) == 0 {
			return nil
		}
		total := 0.0
		for _, key := range spec.Measures {
			v := r.count(key, s, w)
			if v == nil {
				return nil
			}
			total += *v
		}
		if spec.Kind == kinds.Rate {
			var e *float64
			if eligible != nil {
				e = ptr(float64(*eligible))
			}
			return share(&total, e)
		}
		return &total
	}
	_, countrySet := r.book.country[spec.Key]
	var t *target
	if spec.Plan != "" || spec.Basis != "" || countrySet {
		basis := ""
		if spec.Kind == kinds.Count {
			basis = spec.Basis
		}
		found := r.book.forCode(spec.Plan, s, spec.Slice, basis, eligible, spec.Key)
		t = &found
	}
	line := strategicLine{spec: spec, target: t}
	switch spec.Kind {
	case kinds.Untracked:
		var annual *float64
		if t != nil {
			annual = t.annual
		}
		line.year = cell{target: annual}
	case kinds.Score:
		line.year = cell{achieved: r.ledger.ssaAverage(owners, false)}
	case kinds.Rate:
		var rate *float64
		if t != nil {
			rate = t.rate
			if rate == nil && countrySet {
				rate = t.annual
			}
		}
		line.toDate = cell{target: rate, achieved: achieved(per.toDate())}
		line.year = cell{target: rate, achieved: line.toDate.achieved}
	default:
		phased := t != nil && t.months != nil
		line.inPeriod = cell{achieved: achieved(per.span())}
		line.toDate = cell{achieved: achieved(per.toDate())}
		if phased {
			line.inPeriod.target = t.over(per.months())
			line.toDate.target = t.through(per.lastMonth())
		}
		line.year = cell{achieved: line.toDate.achieved}
		if t != nil {
			line.year.target = t.annual
		}
	}
	switch {
	case spec.Kind == kinds.Untracked:
		line.status = "Not tracked"
	case line.year.pct() != nil && *line.year.pct() >= 100:
		line.status = rules.StatusWords.Achieved
	case line.toDate.pct() != nil:
		line.status = statusOf(line.toDate.pct(), true)
	case line.year.achieved != nil && *line.year.achieved != 0:
		line.status = "In Progress"
	default:
		line.status = "Not Started"
	}
	line.tone = rules.StatusTones[line.status]
	if line.tone == "" {
		line.tone = "info"
		if line.status == "Not tracked" {
			line.tone = "neutral"
		}
	}
	if len(spec.Measures) > 0 {
		line.tracker = trackerOf(byKey[spec.Measures[0]])
		line.unit = byKey[spec.Measures[0]].Unit
	}
	return line
}

func trackerOf(m *measure) [2]string {
	t := rules.Trackers
	source := m.Source
	switch {
	case strings.HasPrefix(source, "ssa"):
		return t["ssa"]
	case source == "msc":
		return t["msc"]
	case evidenceSources[source]:
		return t["evidence"]
	case source == "loans" || source == "edtech_loans" || source == "development_loans":
		return t["loans"]
	case strings.HasPrefix(source, "core_"):
		return t["core"]
	case source == "active" || source == "in_clusters" || source == "new_schools" || source == "enrolment":
		return t["schools"]
	}
	return t["work"]
}

// ── CCEO Officer Performance & Milestones Dashboard ─────────────────────────

func (r *report) officerFigures(s scope) figures {
	w := r.period.monthToDate()
	owners := r.owners(s)
	l := r.ledger
	count := func(key string, span window) float64 {
		if v := r.count(key, s, span); v != nil {
			return *v
		}
		return 0
	}
	f := figures{
		"portfolio":      ptr(float64(l.portfolio(owners, "all", &w.end))),
		"active":         ptr(float64(l.portfolio(owners, "active", &w.end))),
		"core_schools":   ptr(float64(l.portfolio(owners, "core", nil))),
		"client_schools": ptr(float64(l.portfolio(owners, "client", nil))),
	}
	f["inactive"] = ptr(*f["portfolio"] - *f["active"])
	f["active_pct"] = share(f["active"], f["portfolio"])
	visits, trainings := 0.0, 0.0
	for n := 1; n <= 4; n++ {
		v := count("core_visit_"+itoa(n), w)
		t := count("core_training_"+itoa(n), w)
		f["core_visit_step_"+itoa(n)] = ptr(v)
		f["core_training_step_"+itoa(n)] = ptr(t)
		visits += v
		trainings += t
	}
	f["visits_core"] = ptr(visits)
	f["visits_noncore"] = ptr(count("client_visit_total", w))
	f["visits_noncore_month_staff"] = ptr(count("client_visit_staff", r.period.monthSpan()))
	f["visits_noncore_partner"] = ptr(count("client_visit_partner", w))
	f["visits"] = ptr(visits + *f["visits_noncore"])
	f["trainings_core"] = ptr(trainings)
	f["trainings_client"] = ptr(count("client_trained", w))
	f["trainings_online"] = ptr(count("online_schools", w))
	f["trainings_tam"] = ptr(count("tam_bi_online_schools", w))
	f["trainings_ece"] = ptr(count("ece", w))
	f["trainings_other"] = ptr(*f["trainings_client"] + *f["trainings_online"] + *f["trainings_tam"] + *f["trainings_ece"])
	f["trainings"] = ptr(trainings + *f["trainings_other"])
	f["recruit"] = ptr(count("core_recruitment", w))
	f["recruit_target"] = r.target(byKey["core_recruitment"], s).annual
	f["recruit_var"] = variance(f["recruit"], f["recruit_target"])
	f["baseline_ssa"] = ptr(count("ssa_core_baseline", w))
	f["ssa_cohort"] = ptr(count("ssa_core_followup", w))
	f["ssa_cohort_target"] = ptr(float64(l.portfolio(owners, "core_continuing", nil)))
	f["ssa_cohort_var"] = ptr(*f["ssa_cohort"] - *f["ssa_cohort_target"])
	f["ssa_client"] = ptr(count("ssa_client", w))
	f["ssa_client_target"] = f["client_schools"]
	f["ssa"] = ptr(*f["ssa_cohort"] + *f["ssa_client"])
	f["dc_data"] = ptr(count("dc_data", w))
	f["dc"] = ptr(count("dc_clubs", w))
	f["dc_pct"] = share(f["dc"], f["dc_data"])
	f["enrol_pct"] = share(ptr(count("enrolment", w)), f["portfolio"])
	f["metrics_pct"] = share(ptr(count("schools_with_metrics", w)), f["portfolio"])
	return f
}

type card struct {
	o            *officer
	region, team string
	f            figures
}

type rollup struct {
	t        *team
	officers int
	f        figures
}

type board struct {
	cards, grid []card
	rollups     []rollup
	total       figures
	officers    int
}

func (r *report) cceoBoard(lead, sortKey string) board {
	teams := []*team{}
	for _, t := range r.roster.teams {
		if lead == "" || t.key == lead {
			teams = append(teams, t)
		}
	}
	cards := []card{}
	for _, t := range teams {
		for _, o := range t.officers {
			cards = append(cards, card{o: o, region: o.region, team: t.label, f: r.officerFigures(officerScope(o.staffID))})
		}
	}
	sortBy := map[string]string{"portfolio": "portfolio", "visits": "visits", "trainings": "trainings", "recruitment": "recruit", "ssa": "ssa"}
	field, ranked := sortBy[sortKey]
	sort.SliceStable(cards, func(i, j int) bool {
		if ranked {
			a, b := -*cards[i].f[field], -*cards[j].f[field]
			if a != b {
				return a < b
			}
		}
		return pyLower(cards[i].o.name) < pyLower(cards[j].o.name)
	})
	rollups := []rollup{}
	for _, t := range teams {
		rollups = append(rollups, rollup{t: t, officers: len(t.officers), f: r.officerFigures(r.teamScope(t))})
	}
	var total figures
	if lead != "" {
		ids := map[string]bool{}
		for _, c := range cards {
			ids[c.o.staffID] = true
		}
		total = r.officerFigures(scope{kind: "region", staff: ids})
	} else {
		total = r.officerFigures(r.home())
	}
	order := map[string]int{}
	for n, t := range r.roster.teams {
		order[t.key] = n
	}
	teamOf := map[string]string{}
	for _, t := range teams {
		for _, o := range t.officers {
			teamOf[o.staffID] = t.key
		}
	}
	grid := append([]card{}, cards...)
	sort.SliceStable(grid, func(i, j int) bool {
		a, b := order[teamOf[grid[i].o.staffID]], order[teamOf[grid[j].o.staffID]]
		if a != b {
			return a < b
		}
		return pyLower(grid[i].o.name) < pyLower(grid[j].o.name)
	})
	return board{cards: cards, grid: grid, rollups: rollups, total: total, officers: len(cards)}
}

// ── {Month} {Year} Summary ──────────────────────────────────────────────────

type monthGroup struct {
	t     *team
	lines []monthLine
	total figures
}

type monthLine struct {
	o    *officer
	cols figures
}

type monthSheet struct {
	groups              []monthGroup
	national, lastMonth figures
	unlisted            int
}

func (r *report) monthSummary() monthSheet {
	per := r.period
	w := per.monthToDate()
	sheet := monthSheet{}
	for _, t := range r.roster.teams {
		g := monthGroup{t: t}
		for _, o := range t.officers {
			g.lines = append(g.lines, monthLine{o: o, cols: r.summaryColumns(officerScope(o.staffID), w)})
		}
		g.total = r.summaryColumns(r.teamScope(t), w)
		sheet.groups = append(sheet.groups, g)
	}
	home := r.home()
	if !r.roster.narrowed() {
		listed := map[string]bool{}
		for _, o := range r.roster.officers() {
			listed[o.staffID] = true
		}
		sheet.unlisted = r.ledger.portfolio(nil, "all", nil) - r.ledger.portfolio(listed, "all", nil)
	}
	sheet.national = r.summaryColumns(home, w)
	sheet.lastMonth = r.summaryColumns(home, per.monthBefore())
	return sheet
}

func (r *report) summaryColumns(s scope, w window) figures {
	owners := r.owners(s)
	l := r.ledger
	per := r.period
	c := figures{}
	count := func(key string, span window) *float64 { return r.count(key, s, span) }
	goal := func(key string) *float64 { return r.target(byKey[key], s).annual }
	block := func(prefix string, g, a *float64, ratio bool) {
		c[prefix+"_t"] = g
		c[prefix+"_a"] = a
		c[prefix+"_v"] = variance(a, g)
		if ratio {
			c[prefix+"_p"] = share(a, g)
		}
	}
	c["portfolio"] = ptr(float64(l.portfolio(owners, "all", &w.end)))
	c["active"] = ptr(float64(l.portfolio(owners, "active", &w.end)))
	c["inactive"] = ptr(*c["portfolio"] - *c["active"])
	c["active_p"] = share(c["active"], c["portfolio"])
	block("recruit", goal("core_recruitment"), count("core_recruitment", w), true)
	c["recruit_ssa"] = count("ssa_core_baseline", w)
	block("cohort", ptr(float64(l.portfolio(owners, "core_continuing", nil))), count("ssa_core_followup", w), false)
	block("ssa", goal("ssa_client"), count("ssa_client", w), true)
	c["new_m_t"] = r.target(byKey["new_schools"], s).month(per.month)
	c["new_m_a"] = count("new_schools", per.monthSpan())
	base := c["portfolio"]
	for _, pair := range [][2]string{{"enrol", "enrolment"}, {"metrics", "schools_with_metrics"}} {
		have := count(pair[1], w)
		c[pair[0]+"_base"], c[pair[0]+"_with"] = base, have
		h := 0.0
		if have != nil {
			h = *have
		}
		c[pair[0]+"_without"] = ptr(*base - h)
		c[pair[0]+"_p"] = share(have, base)
	}
	block("new", goal("new_schools"), count("new_schools", w), true)
	core := ptr(float64(l.portfolio(owners, "core", nil)))
	client := ptr(float64(l.portfolio(owners, "client", nil)))
	for n := 1; n <= 4; n++ {
		block("cv"+itoa(n), core, count("core_visit_"+itoa(n), w), true)
		block("ct"+itoa(n), core, count("core_training_"+itoa(n), w), true)
	}
	block("nc", client, count("client_visit_total", w), true)
	c["ncm_t"] = client
	c["ncm_a"] = count("client_visit_staff", per.monthSpan())
	c["ncm_p"] = share(c["ncm_a"], client)
	block("ncp", client, count("client_visit_partner", w), true)
	c["pend_base"], c["pend_a"] = client, c["nc_a"]
	visited := 0.0
	if c["nc_a"] != nil {
		visited = *c["nc_a"]
	}
	c["pend_left"] = ptr(*client - visited)
	c["pend_p"] = c["nc_p"]
	block("cst", client, count("client_trained", w), true)
	c["onl_a"], c["onl_s"] = count("online_schools", w), count("online_sessions", w)
	c["tam_a"], c["tam_s"] = count("tam_bi_online_schools", w), count("tam_bi_online_sessions", w)
	c["ece_a"] = count("ece", w)
	block("msc", goal("msc"), count("msc", w), true)
	c["dc_t"], c["dc_a"] = count("dc_data", w), count("dc_clubs", w)
	c["dc_none"] = variance(c["dc_t"], c["dc_a"])
	c["dc_p"] = share(c["dc_a"], c["dc_t"])
	return c
}

// ── Core Visits & Training ──────────────────────────────────────────────────

type packageLine struct {
	o            *officer
	region, team string
	f            packageFigures
}

type packageFigures struct {
	core  float64
	kinds map[string]figures
}

func (r *report) corePackage() ([]packageLine, packageFigures) {
	lines := []packageLine{}
	for _, t := range r.roster.teams {
		officers := append([]*officer{}, t.officers...)
		sort.SliceStable(officers, func(i, j int) bool { return pyLower(officers[i].name) < pyLower(officers[j].name) })
		for _, o := range officers {
			lines = append(lines, packageLine{o: o, region: o.region, team: t.label, f: r.packageFigures(officerScope(o.staffID))})
		}
	}
	return lines, r.packageFigures(r.home())
}

func (r *report) packageFigures(s scope) packageFigures {
	w := r.period.now()
	core := float64(r.ledger.portfolio(r.owners(s), "core", nil))
	out := packageFigures{core: core, kinds: map[string]figures{}}
	for _, kind := range []string{"visit", "training"} {
		atLeast := [4]float64{}
		for n := 1; n <= 4; n++ {
			if v := r.count("core_"+kind+"_"+itoa(n), s, w); v != nil {
				atLeast[n-1] = *v
			}
		}
		exactly := [4]float64{}
		done := 0.0
		for i := 0; i < 4; i++ {
			exactly[i] = atLeast[i]
			if i < 3 {
				exactly[i] -= atLeast[i+1]
			}
			done += atLeast[i]
		}
		expected := core * 4
		out.kinds[kind] = figures{
			"one": ptr(exactly[0]), "two": ptr(exactly[1]), "three": ptr(exactly[2]), "four": ptr(exactly[3]),
			"expected": ptr(expected), "done": ptr(done), "pct": share(&done, &expected),
			"three_plus": ptr(atLeast[2]), "three_pct": share(&atLeast[2], &core),
		}
	}
	return out
}

func itoa(n int) string { return strconv.Itoa(n) }
