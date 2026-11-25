package planningmonitor

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"slices"
	"sort"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/activities"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// CEXFollowUpError is FollowUpError: why a follow-up was not sent, in the
// words the drawer shows.
type CEXFollowUpError struct{ Message string }

func (e *CEXFollowUpError) Error() string { return e.Message }

func cexRefuse(msg string) error { return &CEXFollowUpError{Message: msg} }

// ErrCEXFollowUpHandOn is a send Go leaves to the existing application: the
// sender is working in an acting appointment (its audit stamp is not Go's).
var ErrCEXFollowUpHandOn = errors.New("planningmonitor: the follow-up is handed on")

// CEXSendDeps are what follows a send: the notice's phone copy and the word
// to the Lead's open pages.
type CEXSendDeps struct {
	Push   activities.NoticePush
	Live   activities.NoticePublisher
	Logger *slog.Logger
}

const (
	cexFollowUpContext = "PlanningOversightFollowUp"
	cexFollowUpEvent   = "planning_followup_assigned"
	cexTeamOversight   = "/team-planning-oversight/"
)

// cexSend is one send's settled inputs.
type cexSend struct {
	issue       cexIssueRule
	instruction string
	priority    string
	due         time.Time
	lead        cexFollowLead
	open        int
	f           cexFollowFigures
	fs          cexFollowScope
	country     string
	now         time.Time
	sender      auth.Principal
	origin      activities.Origin
}

// cexFollowLead is the Programme Lead a follow-up goes to (_lead).
type cexFollowLead struct{ staffID, userID, role, name string }

// SendExecutionFollowUp is follow_up_view's POST through send_follow_up: the
// execution follow-up created, or the open one reminded. values are the
// form as posted (the tab's selection among them). It answers the drawer's
// message; a *CEXFollowUpError is a refusal to show.
func SendExecutionFollowUp(ctx context.Context, db *pgxpool.Pool, deps CEXSendDeps, p auth.Principal, values map[string]string,
	origin activities.Origin, now time.Time) (string, error) {
	if p.Acting != nil || p.InActingAppointment {
		return "", ErrCEXFollowUpHandOn
	}
	if p.ActiveRole != cexFollowUpRole {
		return "", cexRefuse(CEXFollowUpRefusal)
	}
	now = now.Truncate(time.Microsecond)
	reader, err := schooldirectory.ResolveScope(ctx, db, p, now)
	if err != nil {
		return "", err
	}
	l := now.In(cpoLocation)
	today := date(l.Year(), l.Month(), l.Day())
	fs, err := cexReadFollowScope(ctx, db, reader, values, today)
	if err != nil {
		return "", err
	}
	in, err := cexSettle(ctx, db, reader, fs, values, today)
	if err != nil {
		return "", err
	}
	in.now, in.sender, in.origin, in.country = now, p, origin, reader.Country
	return fuSend(ctx, db, deps, in.ask())
}

// cexSettle is send_follow_up's checks, in its order, and the figures read
// before anything is written.
func cexSettle(ctx context.Context, db *pgxpool.Pool, reader schooldirectory.Scope, fs cexFollowScope, values map[string]string,
	today time.Time) (*cexSend, error) {
	issue, ok := cexIssueOf(strings.TrimSpace(values["issue"]))
	if !ok {
		return nil, cexRefuse("Choose what kind of follow-up this is.")
	}
	instruction := strings.TrimSpace(values["instruction"])
	if instruction == "" {
		return nil, cexRefuse("Write the instruction for the Programme Lead.")
	}
	due, err := time.Parse("2006-01-02", strings.TrimSpace(values["due_date"]))
	if err != nil {
		return nil, cexRefuse("Give the follow-up a due date.")
	}
	if due.Before(today) {
		return nil, cexRefuse("The due date cannot be in the past.")
	}
	priority := strings.TrimSpace(values["priority"])
	if !slices.ContainsFunc(rules.CountryExecution.FollowUps.Priorities, func(p [2]string) bool { return p[0] == priority }) {
		return nil, cexRefuse("Choose a priority.")
	}
	lead, err := cexLeadOf(ctx, db, fs.lead)
	if err != nil {
		return nil, err
	}
	if lead == nil || lead.userID == "" {
		return nil, cexRefuse("This work has no Programme Lead on record, so there is nobody to follow up with. Place the officer under a Programme Lead first.")
	}
	if lead.role != "Program Lead" {
		return nil, cexRefuse(lead.name + " is not a Programme Lead.")
	}
	sys := cexSystemScope(reader)
	f, err := cexEvaluate(ctx, db, sys, fs, today)
	if err != nil {
		return nil, err
	}
	open, err := cexMetric(ctx, db, sys, issue, fs, f, today)
	if err != nil {
		return nil, err
	}
	if issue.ResolutionRule == "metric_zero" && open <= 0 {
		return nil, cexRefuse("There is no " + strings.ToLower(issue.Label) + " in this scope right now, so there is nothing to follow up.")
	}
	return &cexSend{issue: issue, instruction: instruction, priority: priority, due: due, lead: *lead, open: open, f: f, fs: fs}, nil
}

// cexLeadOf is _lead: the live profile and its user (name, else email).
func cexLeadOf(ctx context.Context, db *pgxpool.Pool, staffID string) (*cexFollowLead, error) {
	if staffID == "" {
		return nil, nil
	}
	l := &cexFollowLead{}
	var user, role, name, email *string
	err := db.QueryRow(ctx, `SELECT sp.id, sp.user_id, u.active_role, u.name, u.email FROM staff_profile sp
		LEFT JOIN "user" u ON u.id = sp.user_id WHERE sp.id = $1 AND sp.deleted_at IS NULL`, staffID).Scan(&l.staffID, &user, &role, &name, &email)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, nil
	}
	if err != nil {
		return nil, fmt.Errorf("planningmonitor: the Programme Lead: %w", err)
	}
	l.userID, l.role = deref(user), deref(role)
	l.name = deref(name)
	if l.name == "" {
		l.name = deref(email)
	}
	return l, nil
}

func deref(s *string) string {
	if s == nil {
		return ""
	}
	return *s
}

// ask is the record the send writes: the condition, the oldest overdue
// age, the affected schools and the instruction's history line.
func (in *cexSend) ask() *fuAsk {
	oldest := 0
	ids := map[string]bool{}
	for _, r := range in.f.records {
		if r.overdue != "" || r.returned || r.financeOpen {
			oldest = max(oldest, r.age)
			if r.schoolID != "" {
				ids[r.schoolID] = true
			}
		}
	}
	schools := []string{}
	for id := range ids {
		schools = append(schools, id)
	}
	sort.Strings(schools)
	if len(schools) > 500 {
		schools = schools[:500]
	}
	w := in.fs.period.window()
	dash := func(s string) string {
		if s == "" {
			return "-"
		}
		return s
	}
	key := "cpx|" + in.fs.period.fy + "|" + w.period + ":" + w.start.Format("2006-01-02") + "|pl:" + in.fs.lead + "|cceo:" +
		dash(in.fs.cceo) + "|partner:" + dash(in.fs.partner) + "|issue:" + in.issue.Key + "|activity:" + dash(in.fs.activityID)
	name := in.sender.Name
	if name == "" {
		name = "Country Director"
	}
	d, c := in.f.snap.data, in.f.snap.tree.country
	a := &fuAsk{module: "execution", key: key, issueKey: in.issue.Key, issueLabel: in.issue.Label, metricKey: in.issue.Figure,
		resolutionRule: in.issue.ResolutionRule, stage: in.issue.Stage, blockerOwner: in.issue.Owner, required: c.n("due"),
		planned: c.n("verified"), remaining: in.open, affected: len(schools), schoolIDs: schools, daysOverdue: &oldest,
		cceo: in.fs.cceo, partner: in.fs.partner, activity: in.fs.activityID, fy: in.fs.period.fy, country: in.country, w: w,
		lead: in.lead, sender: in.sender, origin: in.origin, now: in.now, due: in.due, instruction: in.instruction,
		priority: in.priority}
	a.entry = map[string]any{"at": cexISO(in.now), "by": in.sender.UserID, "name": name, "instruction": in.instruction,
		"priority": in.priority, "due": in.due.Format("2006-01-02"), "open": in.open}
	a.snapshot = map[string]any{"due": c.n("due"), "started": c.n("started"), "executed": c.n("executed"),
		"verified": c.n("verified"), "closed": c.n("closed"), "overdue": c.n("overdue"), "open": in.open,
		"as_of": d.today.Format("2006-01-02")}
	if o := d.owners[in.fs.cceo]; in.fs.cceo != "" && o != nil {
		a.cceoName = o.name
	}
	if in.fs.partner != "" {
		a.partnerName = d.partnerName[in.fs.partner]
	}
	if in.fs.activityID != "" && len(in.f.records) > 0 {
		r := in.f.records[0]
		if r.due != nil {
			label := rules.CountryOversight.Page.TableWords.Types[r.activityType]
			if label == "" {
				label = r.activityType
			}
			a.activityLabel = fmt.Sprintf("%s · due %d %s", label, r.due.Day(), r.due.Format("Jan 2006"))
		}
		if a.stage == "" {
			a.stage = r.stage
		}
	}
	a.sentAudit = map[string]any{"module": "execution", "open": in.open, "due": in.due.Format("2006-01-02"),
		"priority": in.priority, "stage": a.stage}
	a.remindAudit = func(n int) map[string]any { return map[string]any{"module": "execution", "reminder_count": n} }
	return a
}

// cexISO is datetime.isoformat() of an aware UTC moment.
func cexISO(t time.Time) string {
	t = t.UTC()
	if t.Nanosecond()/int(time.Microsecond) == 0 {
		return t.Format("2006-01-02T15:04:05") + "+00:00"
	}
	return t.Format("2006-01-02T15:04:05.000000") + "+00:00"
}
