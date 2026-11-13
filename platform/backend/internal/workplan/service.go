package workplan

import (
	"context"
	"fmt"
	"math/big"
	"net/url"
	"slices"
	"sort"
	"time"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/myplan"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pagegate"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schoolprofile"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/visitgate"
)

// Path is the page this package answers (and its alias with a slash).
const Path = "/work-plan"

// zoneName is the project's timezone (settings.TIME_ZONE): today, and the
// day a scheduled instant falls on.
const zoneName = "Africa/Nairobi"

// Service builds the Work Plan.
type Service struct {
	db   schooldirectory.Querier
	now  func() time.Time
	zone *time.Location
}

// NewService wires the service to the database it reads.
func NewService(db schooldirectory.Querier, now func() time.Time) *Service {
	zone, err := time.LoadLocation(zoneName)
	if err != nil {
		panic(fmt.Sprintf("workplan: %v", err))
	}
	return &Service{db: db, now: now, zone: zone}
}

// band is one month's summary card, or the undated one.
type band struct {
	label                    string
	count, completed, atRisk int
	cost                     int64
	url                      string
	month                    int
}

// bucket is one line of the Activity Plan Summary.
type bucket struct {
	label       string
	count       int
	cost        int64
	missing     int
	note        string
	unitDisplay string
	unitNote    string
}

// row is one row of the Detailed Activity Plan.
type row struct {
	a                            *activity
	dateLabel                    string
	dayOff                       *dayOffMark
	word, schoolName, schoolCode string
	district, cluster, purpose   string
	focus, verdict, deviation    string
	score, mode, responsible     string
	cost                         int64
	costMissing                  bool
	costNote                     string
	lines                        []*costLine
	status                       string
	act                          action
	canPick                      bool
}

// view is everything the page draws.
type view struct {
	s                  state
	door               Door
	query              url.Values
	approval           approval
	bands              []*band
	fyTotals           *band
	summary            [2][]*bucket
	totals             [2]bucket
	missingTotal       int
	rows               []*row
	planned, thisMonth int
	budget             int64
	pending, missing   int
	atRisk             int
	responsible        [][2]string
	projects           [][2]string
}

// Build answers path for p with the page's query. served is false for a
// path this package does not answer.
func (s *Service) Build(ctx context.Context, p auth.Principal, path string, query url.Values) (*screensv1.GetPageResponse, bool, error) {
	if path != Path && path != Path+"/" {
		return nil, false, nil
	}
	door, ok := rules.Doors[p.ActiveRole]
	if !ok || !door.Page {
		return nil, true, pagegate.ErrNotAvailable
	}
	passed := url.Values{}
	for key, values := range query {
		if !in(rules.QueryKeysNotPassed, key) {
			passed[key] = values
		}
	}
	v, err := s.read(ctx, p, door, passed)
	if err != nil {
		return nil, true, err
	}
	return v.page(path), true, nil
}

func (s *Service) read(ctx context.Context, p auth.Principal, door Door, query url.Values) (*view, error) {
	now := s.now()
	local := now.In(s.zone)
	today := time.Date(local.Year(), local.Month(), local.Day(), 0, 0, 0, 0, time.UTC)
	next, err := nextOpenFY(ctx, s.db, today, s.zone)
	if err != nil {
		return nil, err
	}
	st := readState(query.Get, p.ActiveRole, next, today)
	v := &view{s: st, door: door, query: query}

	scope, err := schooldirectory.ResolveScope(ctx, s.db, p, now)
	if err != nil {
		return nil, err
	}
	filter, err := scoped(ctx, s.db, p, scope, st.scope)
	if err != nil {
		return nil, err
	}
	where, args := st.where(filter)
	start, end := st.windowBounds()
	window, periodArgs := windowSQL(args, start, end)
	acts, err := readActivities(ctx, s.db, where+" AND "+window, periodArgs)
	if err != nil {
		return nil, err
	}
	monthStart := time.Date(today.Year(), today.Month(), 1, 0, 0, 0, 0, time.UTC)
	monthEnd := monthStart.AddDate(0, 1, -1)
	thisMonth, monthArgs := windowSQL(args, monthStart, monthEnd)
	if v.thisMonth, err = countActivities(ctx, s.db, where+" AND "+thisMonth, monthArgs); err != nil {
		return nil, err
	}

	ids := make([]string, 0, len(acts))
	staffIDs, partnerIDs, clusterIDs := []string{}, []string{}, []string{}
	add := func(list *[]string, p *string) {
		if isSet(p) && !in(*list, *p) {
			*list = append(*list, *p)
		}
	}
	for _, a := range acts {
		ids = append(ids, a.id)
		add(&staffIDs, a.staffID)
		add(&staffIDs, a.monitorID)
		add(&partnerIDs, a.partnerID)
		if isSet(a.schoolPK) {
			add(&clusterIDs, a.schoolCluster)
		}
	}
	lines, err := readCostLines(ctx, s.db, ids)
	if err != nil {
		return nil, err
	}
	nm, err := readNames(ctx, s.db, staffIDs, p.ActiveRole == roleCountryDirector)
	if err != nil {
		return nil, err
	}
	clusterNames, err := namesOf(ctx, s.db, "cluster", clusterIDs)
	if err != nil {
		return nil, err
	}
	partnerNames, err := namesOf(ctx, s.db, "partner", partnerIDs)
	if err != nil {
		return nil, err
	}
	outsideList, err := visitgate.ProjectsOutsideSSA(ctx, s.db, schoolprofile.GateRules())
	if err != nil {
		return nil, fmt.Errorf("workplan: projects outside the SSA: %w", err)
	}
	outside := map[string]bool{}
	for _, id := range outsideList {
		outside[id] = true
	}
	pairIn := make([]myplan.PairActivity, 0, len(acts))
	for _, a := range acts {
		pairIn = append(pairIn, myplan.PairActivity{ID: a.id, Type: a.activityType, PairedVisit: a.pairedVisit,
			CostMissing: a.costMissing, DeliveryMode: a.deliveryMode, HasLines: len(lines[a.id]) > 0})
	}
	notes, err := myplan.PairNotes(ctx, s.db, pairIn)
	if err != nil {
		return nil, err
	}
	marks, err := dayOffMarks(ctx, s.db, acts)
	if err != nil {
		return nil, err
	}
	if v.approval, err = readApproval(ctx, s.db, p.ActiveRole, st.fy); err != nil {
		return nil, err
	}
	if v.projects, err = scopedProjects(ctx, s.db, p, scope); err != nil {
		return nil, err
	}

	v.tally(p, acts, lines, nm, clusterNames, partnerNames, outside, notes, marks, start, end)
	return v, nil
}

// tally is the page's one pass: rows, month bands and the strip's counters
// together, then the summary and the responsible-person choices.
func (v *view) tally(p auth.Principal, acts []*activity, lines map[string][]*costLine, nm names,
	clusterNames, partnerNames map[string]string, outside map[string]bool, notes map[string]string,
	marks map[string]dayOffMark, start, end time.Time) {
	st := v.s
	base := st.base()
	months := st.windowMonths()
	bands := map[int]*band{}
	for _, m := range months {
		b := &band{label: monthLabel(st.fyInt, m), month: m,
			url: link(base, kv{"view", "month"}, kv{"period", itoa(m)}, kv{"flag", ""})}
		bands[m] = b
		v.bands = append(v.bands, b)
	}
	undated := &band{label: "Undated", url: link(base, kv{"flag", ""})}
	inWindow := func(m int) bool { return slices.Contains(months, m) }
	viewer := []string{}
	for _, id := range []string{p.UserID, p.StaffProfileID} {
		if id != "" {
			viewer = append(viewer, id)
		}
	}
	buckets := [2]map[string]*bucket{{}, {}}
	order := [2][]string{}

	for _, a := range acts {
		anchor := a.planned
		if anchor == nil {
			anchor = a.scheduled
		}
		var b *band
		switch {
		case anchor != nil:
			m := int(anchor.Month())
			if !inWindow(m) {
				m = months[len(months)-1]
				if anchor.Before(start) {
					m = months[0]
				}
			}
			b = bands[m]
		case a.month != nil && inWindow(*a.month):
			b = bands[*a.month]
		default:
			b = undated
		}
		all := lines[a.id]
		period := []*costLine{}
		for _, l := range all {
			var ok bool
			switch {
			case l.planned != nil:
				ok = !l.planned.Before(start) && !l.planned.After(end)
			case l.month != nil && *l.month != 0:
				ok = inWindow(*l.month) && (!isSet(l.fiscalYear) || *l.fiscalYear == st.fy)
			default:
				ok = anchor != nil && !anchor.Before(start) && !anchor.After(end)
			}
			if ok {
				period = append(period, l)
			}
		}
		note := notes[a.id]
		missing := a.costMissing || (len(all) == 0 && note == "")
		var cost int64
		for _, l := range period {
			lm := 0
			if l.planned != nil {
				lm = int(l.planned.Month())
			} else if l.month != nil {
				lm = *l.month
			}
			target := b
			if inWindow(lm) {
				target = bands[lm]
			}
			target.cost += l.amount
			cost += l.amount
		}
		v.budget += cost
		completed := in(rules.CompletedWorkStatuses, a.status)
		effectiveEnd := a.endDate
		if effectiveEnd == nil {
			effectiveEnd = anchor
		}
		atRisk := effectiveEnd != nil && effectiveEnd.Before(st.today) && in(rules.AtRiskOpenStatuses, a.status)
		pending := false
		for _, l := range period {
			for _, status := range l.requests {
				if in(rules.PendingApprovalWFRStatuses, status) {
					pending = true
				}
			}
		}
		b.count++
		v.planned++
		if completed {
			b.completed++
		}
		if atRisk {
			b.atRisk++
			v.atRisk++
		}
		if pending {
			v.pending++
		}
		if missing {
			v.missing++
		}
		if (st.flag == "pending_approval" && !pending) || (st.flag == "cost_missing" && !missing) || (st.flag == "at_risk" && !atRisk) {
			continue
		}

		g := group(a)
		gi := 0
		if g == "non_school" {
			gi = 1
		}
		label := bucketLabel(a, note)
		bk, ok := buckets[gi][label]
		if !ok {
			bk = &bucket{label: label, note: note}
			buckets[gi][label] = bk
			order[gi] = append(order[gi], label)
		}
		bk.count++
		bk.cost += cost
		if missing {
			bk.missing++
		}

		owned := in(viewer, str(a.staffID)) || (a.delivery == "partner" && in(viewer, str(a.monitorID)))
		var act action
		if v.door.ActionsEnabled && (owned || v.door.OperationalAdmin) {
			advances := []advance{}
			for _, l := range all {
				advances = append(advances, l.advances...)
			}
			act = nextAction(a, st.today, advances)
		} else {
			act = action{text: "View", url: "/my-plan/" + a.id}
		}
		recipient := str(a.staffID)
		if a.delivery == "partner" {
			recipient = str(a.monitorID)
		}
		var ta *action
		if lead, ok := nm.lead[recipient]; ok && lead[0] != "" && !in(viewer, lead[0]) {
			name := lead[1]
			if name == "" {
				name = "the Program Lead"
			}
			ta = tableAction(a, owned, v.door.ActionsEnabled, lead[0], name, "PL")
		} else {
			name, ok := nm.name[recipient]
			if !ok {
				name = "responsible person"
			}
			ta = tableAction(a, owned, v.door.ActionsEnabled, nm.recipient[recipient], name, "")
		}
		r := &row{a: a, dateLabel: dateLabel(anchor, a.endDate), word: activityWord(a, g),
			schoolName: str(a.schoolName), schoolCode: str(a.schoolCode),
			district: districtName(a), purpose: activityPurpose(a, g),
			focus: focusIntervention(a, g, outside), score: previousScore(a), mode: deliveryMode(a, g),
			cost: cost, costMissing: missing, costNote: note, lines: period, status: deliveryStatus(a)}
		if !isSet(a.schoolPK) {
			r.schoolName, r.schoolCode = "", ""
		}
		if m, ok := marks[a.id]; ok {
			r.dayOff = &m
		}
		switch {
		case isSet(a.clusterID):
			r.cluster = str(a.clusterName)
		case isSet(a.schoolPK):
			r.cluster = clusterNames[str(a.schoolCluster)]
		}
		if a.alignment != "" {
			r.verdict = verdictLabel(a)
			r.deviation = a.deviation
		}
		if a.delivery == "partner" {
			r.responsible = partnerNames[str(a.partnerID)]
			if _, ok := partnerNames[str(a.partnerID)]; !ok {
				r.responsible = "Unassigned Partner"
			}
		} else if name, ok := nm.name[str(a.staffID)]; ok {
			r.responsible = name
		} else {
			r.responsible = "Unassigned"
		}
		if ta != nil {
			r.act = *ta
			r.canPick = ta.own
		} else {
			r.act = act
		}
		v.rows = append(v.rows, r)
	}

	for gi := range 2 {
		list := []*bucket{}
		for _, label := range order[gi] {
			list = append(list, buckets[gi][label])
		}
		sort.SliceStable(list, func(i, j int) bool {
			if list[i].cost != list[j].cost {
				return list[i].cost > list[j].cost
			}
			return list[i].label < list[j].label
		})
		for _, bk := range list {
			bk.unitDisplay = unitCost(bk.cost, bk.count)
			if bk.missing > 0 {
				bk.unitDisplay = "Cost setup required"
			}
			bk.unitNote = bk.note
			if bk.cost != 0 || bk.missing > 0 {
				bk.unitNote = ""
			}
			v.totals[gi].count += bk.count
			v.totals[gi].cost += bk.cost
			v.missingTotal += bk.missing
		}
		v.summary[gi] = list
	}
	if undated.count > 0 {
		v.bands = append(v.bands, undated)
	}
	if st.view == "fy" {
		t := &band{}
		for _, b := range v.bands {
			t.count += b.count
			t.cost += b.cost
			t.completed += b.completed
			t.atRisk += b.atRisk
		}
		v.fyTotals = t
	}

	type pick struct{ id, name string }
	seen := map[string]bool{}
	people := []pick{}
	for _, a := range acts {
		if !isSet(a.staffID) || seen[*a.staffID] {
			continue
		}
		seen[*a.staffID] = true
		name, ok := nm.name[*a.staffID]
		if !ok {
			name = "Staff"
		}
		people = append(people, pick{*a.staffID, name})
	}
	sort.Slice(people, func(i, j int) bool {
		if people[i].name != people[j].name {
			return people[i].name < people[j].name
		}
		return people[i].id < people[j].id
	})
	for _, pk := range people {
		v.responsible = append(v.responsible, [2]string{pk.id, pk.name})
	}
}

// unitCost is _finish_summary_rows' unit cost: the total over the count,
// to the cent, half up, written without cents when it is whole.
func unitCost(cost int64, count int) string {
	q := new(big.Rat).SetFrac(big.NewInt(cost), big.NewInt(int64(count)))
	cents := new(big.Rat).Mul(q, big.NewRat(100, 1))
	n, d := cents.Num(), cents.Denom()
	whole, rem := new(big.Int).QuoRem(n, d, new(big.Int))
	twice := new(big.Int).Mul(new(big.Int).Abs(rem), big.NewInt(2))
	if twice.Cmp(d) >= 0 {
		if n.Sign() < 0 {
			whole.Sub(whole, big.NewInt(1))
		} else {
			whole.Add(whole, big.NewInt(1))
		}
	}
	c := whole.Int64()
	neg := c < 0
	if neg {
		c = -c
	}
	units, frac := c/100, c%100
	out := comma(units)
	if frac != 0 {
		out += fmt.Sprintf(".%02d", frac)
	}
	if neg {
		out = "-" + out
	}
	return out
}
