package planningmonitor

import (
	"context"
	"slices"
	"sort"
	"strings"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/partneroversight"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// Follow Up with PL on the planning stage (country_oversight.followups):
// the gaps a Country Director can ask a Programme Lead about, read over the
// scope's own portfolios through the page's dataset and fold.

func cpoIssueOf(key string) (cpoIssueRule, bool) {
	for _, i := range rules.CountryOversight.Page.FollowUpIssues {
		if i.Key == key {
			return i, true
		}
	}
	return cpoIssueRule{}, false
}

// cpoFigure is getattr(tally, name): a stored figure or one of Tally's
// properties.
func cpoFigure(t cpoTally, name string) int {
	switch name {
	case "planned":
		return t.planned()
	case "assigned_unscheduled":
		return max(0, t.n("partner_assigned")-t.n("partner_scheduled"))
	}
	if _, ok := cpoIdx[name]; !ok {
		return 0
	}
	return t.n(name)
}

// metricValues is metric_values: required, planned and remaining.
func (i cpoIssueRule) metricValues(t cpoTally) (int, int, int) {
	return cpoFigure(t, i.Required), cpoFigure(t, i.Planned), cpoFigure(t, i.Remaining)
}

// cpoFollowScope is followups.Scope: the page's period and who it is about.
type cpoFollowScope struct {
	filters            cpoFilters
	lead, cceo, school string
}

// cpoReadFollowScope is the view's _scope_from, with an officer named
// without a Lead placed under theirs on the reader's own page.
func cpoReadFollowScope(ctx context.Context, db schooldirectory.Querier, reader schooldirectory.Scope, q map[string]string,
	today time.Time) (cpoFollowScope, error) {
	get := func(name string) string { return strings.TrimSpace(q[name]) }
	fs := cpoFollowScope{filters: cpoReadFilters(q, today), lead: get("lead"), cceo: get("owner"), school: get("school")}
	if fs.cceo == "" || fs.lead != "" {
		return fs, nil
	}
	snap, err := buildCPOSnapshot(ctx, db, reader, fs.filters, today)
	if err != nil {
		return fs, err
	}
	for _, l := range snap.tree.leads {
		for _, o := range l.owners {
			if o.key == fs.cceo {
				fs.lead = l.key
				return fs, nil
			}
		}
	}
	return fs, nil
}

// cpoFollowFigures is evaluate's answer: the tally, the dataset and where
// each school landed.
type cpoFollowFigures struct {
	tally  cpoTally
	snap   *cpoSnapshot
	placed []*cpoSchool
}

// cpoEvaluate is evaluate: the scope's own portfolios (a Lead's and their
// team's, or one officer's) read as the system reads the country.
func cpoEvaluate(ctx context.Context, db schooldirectory.Querier, sys schooldirectory.Scope, fs cpoFollowScope, roster cexRoster,
	today time.Time) (cpoFollowFigures, error) {
	ids := []string{}
	if fs.cceo != "" {
		ids = append(ids, fs.cceo)
	} else {
		ids = append(ids, fs.lead)
		ids = append(ids, roster.ids[fs.lead]...)
		for _, p := range roster.people[fs.lead] {
			ids = append(ids, roster.ids[p[0]]...)
		}
	}
	ids = slices.DeleteFunc(ids, func(id string) bool { return id == "" })
	owners, err := partneroversight.BothIDSpaces(ctx, db, ids)
	if err != nil {
		return cpoFollowFigures{}, err
	}
	if owners == nil {
		owners = []string{}
	}
	f := fs.filters
	only := cpoFilters{fy: f.fy, period: f.period, quarter: f.quarter, month: f.month, week: f.week, programLead: fs.lead, cceo: fs.cceo}
	snap, err := buildCPOSnapshotOn(ctx, db, sys, only, today, owners)
	if err != nil {
		return cpoFollowFigures{}, err
	}
	out := cpoFollowFigures{tally: cpoTally(snap.tree.country), snap: snap}
	d := snap.data
	for _, s := range d.schools {
		lead := rules.CountryOversight.NoLead[0]
		if o := d.owners[s.ownerKey]; o != nil {
			lead = o.leadKey
		}
		if keepsPlace(only, s, lead) && s.governed() && statusMatches(d.claims[s.id], only) {
			out.placed = append(out.placed, s)
		}
	}
	if fs.school != "" {
		out.tally = cpoBlank()
		if s := d.byID[fs.school]; s != nil && s.governed() {
			out.tally = phase(schoolValues(s, d.claims[s.id]), d.window)
		}
	}
	return out, nil
}

// affected is affected_schools: the placed schools in the gap, worst first.
func (f cpoFollowFigures) affected(i cpoIssueRule, limit int) ([]string, int) {
	type row struct {
		amount   int
		name, id string
	}
	rows := []row{}
	for _, s := range f.placed {
		amount := 0
		if i.SchoolTest == "awaiting_partner" {
			cl := f.snap.data.claims[s.id]
			amount = max(0, cl.cumPartnerAssigned-cl.cumPartnerScheduled)
		} else if _, ok := cpoIdx[i.SchoolTest]; ok {
			amount = f.snap.data.vectors[s.id][cpoIdx[i.SchoolTest]]
		}
		if amount > 0 {
			rows = append(rows, row{amount, s.name, s.id})
		}
	}
	sort.SliceStable(rows, func(a, b int) bool {
		if rows[a].amount != rows[b].amount {
			return rows[a].amount > rows[b].amount
		}
		if x, y := strings.ToLower(rows[a].name), strings.ToLower(rows[b].name); x != y {
			return x < y
		}
		return rows[a].id < rows[b].id
	})
	out := []string{}
	for k, r := range rows {
		if k == limit {
			break
		}
		out = append(out, r.id)
	}
	return out, len(rows)
}

// CountryOversightFollowUpFigures is the planning drawer's issue menu as a
// comparison reads it (local proofs against Django's own figures): the Lead
// the scope lands on, each gap's (required, planned, remaining) and the
// first eight affected schools of each.
func CountryOversightFollowUpFigures(ctx context.Context, db schooldirectory.Querier, p auth.Principal, q map[string]string,
	now time.Time) (string, map[string][]any, error) {
	reader, err := schooldirectory.ResolveScope(ctx, db, p, now)
	if err != nil {
		return "", nil, err
	}
	l := now.In(cpoLocation)
	today := date(l.Year(), l.Month(), l.Day())
	fs, err := cpoReadFollowScope(ctx, db, reader, q, today)
	if err != nil || fs.lead == "" {
		return fs.lead, nil, err
	}
	sys := cexSystemScope(reader)
	roster, err := cexRosterOf(ctx, db, sys)
	if err != nil {
		return "", nil, err
	}
	f, err := cpoEvaluate(ctx, db, sys, fs, roster, today)
	if err != nil {
		return "", nil, err
	}
	out := map[string][]any{}
	for _, i := range rules.CountryOversight.Page.FollowUpIssues {
		r, pl, rem := i.metricValues(f.tally)
		ids, total := f.affected(i, 8)
		out[i.Key] = []any{r, pl, rem, total, ids}
	}
	return fs.lead, out, nil
}
