package planningmonitor

import (
	"context"
	"fmt"
	"slices"
	"strings"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/partneroversight"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// Follow Up with PL for execution (country_execution.followups): the issues
// a Country Director can ask a Programme Lead about, and how much of each is
// open in a scope, read through the page's own fold.

// cexFollowUpRules are the follow-ups' words (exported with the rules).
type cexFollowUpRules struct {
	Issues     []cexIssueRule `json:"issues"`
	Priorities [][2]string    `json:"priorities"`
	OpenStates []string       `json:"open_states"`
	DueInDays  int            `json:"due_in_days"`
	// ResolvedAutomatically is the status the sweep closes a follow-up in.
	ResolvedAutomatically string `json:"resolved_automatically"`
}

// cexIssueRule is ExecIssue.
type cexIssueRule struct {
	Key            string `json:"key"`
	Label          string `json:"label"`
	Figure         string `json:"figure"`
	Stage          string `json:"stage"`
	Owner          string `json:"owner"`
	ResolutionRule string `json:"resolution_rule"`
}

func cexIssueOf(key string) (cexIssueRule, bool) {
	for _, i := range rules.CountryExecution.FollowUps.Issues {
		if i.Key == key {
			return i, true
		}
	}
	return cexIssueRule{}, false
}

// cexFollowScope is ExecScope: the period of the tab's selection and who the
// follow-up is about.
type cexFollowScope struct {
	period                          cexFilters // the tab's selection; only its period is read
	lead, cceo, partner, activityID string
}

// filters is ExecScope.filters: the period, and the Lead, officer and
// Partner the follow-up names.
func (fs cexFollowScope) filters() cexFilters {
	p := fs.period
	out := cexFilters{fy: p.fy, period: p.period, quarter: p.quarter, month: p.month, programLead: fs.lead, cceo: fs.cceo,
		partner: fs.partner}
	if p.period == "week" {
		y, w := p.window().start.ISOWeek()
		out.week = fmt.Sprintf("%04d-W%02d", y, w)
	}
	return out
}

// cexSystemScope is system_scope: the whole of the reader's country, as the
// system reads it.
func cexSystemScope(reader schooldirectory.Scope) schooldirectory.Scope {
	return schooldirectory.Scope{Role: "CountryDirector", UserID: "system", CountryScope: true, Country: reader.Country,
		CountryID: reader.CountryID, CountryFromRegistry: reader.CountryFromRegistry}
}

// cexFollowFigures is evaluate: the fold and the records for the scope.
type cexFollowFigures struct {
	snap    *cexSnapshot
	records []cexRecord
}

func cexEvaluate(ctx context.Context, db schooldirectory.Querier, sys schooldirectory.Scope, fs cexFollowScope,
	today time.Time) (cexFollowFigures, error) {
	s, err := buildCEXSnapshot(ctx, db, sys, fs.filters(), today)
	if err != nil {
		return cexFollowFigures{}, err
	}
	records := []cexRecord{}
	for _, r := range s.records() {
		if fs.activityID == "" || r.id == fs.activityID {
			records = append(records, r)
		}
	}
	return cexFollowFigures{snap: s, records: records}, nil
}

// cexMetric is metric: how much of the gap is still open.
func cexMetric(ctx context.Context, db schooldirectory.Querier, sys schooldirectory.Scope, issue cexIssueRule, fs cexFollowScope,
	f cexFollowFigures, today time.Time) (int, error) {
	if fs.activityID != "" {
		if len(f.records) == 0 || f.records[0].cancelled {
			return 0, nil
		}
		if cexRecordOpen(issue, f.records[0]) {
			return 1, nil
		}
		return 0, nil
	}
	if issue.Figure == "slots_visit" || issue.Figure == "slots_training" {
		return cexSlotsLeft(ctx, db, sys, issue.Figure, fs, f.snap.roster, today)
	}
	if _, ok := cexIdx[issue.Figure]; !ok {
		return 0, nil
	}
	return f.snap.tree.country.n(issue.Figure), nil
}

// cexRecordOpen is _record_open.
func cexRecordOpen(issue cexIssueRule, r cexRecord) bool {
	switch fig := issue.Figure; {
	case fig == "overdue":
		return r.overdue != ""
	case fig == "own_partner":
		return r.owner == "partner"
	case fig == "returned":
		return r.returned
	case len(fig) > 3 && fig[:3] == "od_":
		return r.overdue == fig[3:]
	}
	return r.overdue != ""
}

// cexSlotsLeft is _slots_left: the required slots not yet verified over the
// whole portfolios of the people the scope names, on the planning tab.
func cexSlotsLeft(ctx context.Context, db schooldirectory.Querier, sys schooldirectory.Scope, figure string, fs cexFollowScope,
	roster cexRoster, today time.Time) (int, error) {
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
		return 0, err
	}
	if owners == nil {
		owners = []string{}
	}
	plan, err := buildCPOSnapshotOn(ctx, db, sys, fs.filters().planning(), today, owners)
	if err != nil {
		return 0, err
	}
	t := cpoTally(plan.tree.country)
	if figure == "slots_visit" {
		return max(0, t.n("visit_slots")-t.n("staff_verified")-t.n("partner_verified")), nil
	}
	return max(0, t.n("training_slots")-t.n("training_verified")), nil
}

// cexReadFollowScope is the view's _scope: the tab's period and the Lead,
// officer (cceo, or the row's owner), Partner and activity asked about; an
// officer with no Lead named is placed under their Lead on the reader's own
// fold, as follow_up_view places them.
func cexReadFollowScope(ctx context.Context, db schooldirectory.Querier, reader schooldirectory.Scope, q map[string]string,
	today time.Time) (cexFollowScope, error) {
	get := func(name string) string { return strings.TrimSpace(q[name]) }
	fs := cexFollowScope{period: cexReadFilters(q, today), lead: get("lead"), cceo: get("cceo"), partner: get("partner_key"),
		activityID: get("activity")}
	if fs.cceo == "" {
		fs.cceo = get("owner")
	}
	if fs.cceo == "" || fs.lead != "" {
		return fs, nil
	}
	s, err := buildCEXSnapshot(ctx, db, reader, fs.period, today)
	if err != nil {
		return fs, err
	}
	for _, l := range s.tree.leads {
		for _, o := range l.owners {
			if o.key == fs.cceo {
				fs.lead = o.leadKey
				return fs, nil
			}
		}
	}
	return fs, nil
}

// CountryExecutionFollowUpFigures is follow_up_view's issue rows as a
// comparison reads them (local proofs against Django's own figures): the
// Lead the scope lands on and each issue's open count.
func CountryExecutionFollowUpFigures(ctx context.Context, db schooldirectory.Querier, p auth.Principal, q map[string]string,
	now time.Time) (string, map[string]int, error) {
	reader, err := schooldirectory.ResolveScope(ctx, db, p, now)
	if err != nil {
		return "", nil, err
	}
	l := now.In(cpoLocation)
	today := date(l.Year(), l.Month(), l.Day())
	fs, err := cexReadFollowScope(ctx, db, reader, q, today)
	if err != nil || fs.lead == "" {
		return fs.lead, nil, err
	}
	sys := cexSystemScope(reader)
	f, err := cexEvaluate(ctx, db, sys, fs, today)
	if err != nil {
		return "", nil, err
	}
	out := map[string]int{}
	for _, issue := range rules.CountryExecution.FollowUps.Issues {
		if issue.Key == "exec_other" {
			continue
		}
		if out[issue.Key], err = cexMetric(ctx, db, sys, issue, fs, f, today); err != nil {
			return "", nil, err
		}
	}
	return fs.lead, out, nil
}
