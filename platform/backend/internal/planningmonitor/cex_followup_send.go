package planningmonitor

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"net/url"
	"slices"
	"sort"
	"strconv"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/activities"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/audit"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/realtime"
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
	issue        cexIssueRule
	instruction  string
	priority     string
	due          time.Time
	lead         cexFollowLead
	open, oldest int
	f            cexFollowFigures
	fs           cexFollowScope
	country      string
	now          time.Time
	sender       auth.Principal
	origin       activities.Origin
	schoolIDs    []string
	key          string
	entry        map[string]any
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
	in.prepare()
	tx, err := db.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite})
	if err != nil {
		return "", fmt.Errorf("planningmonitor: opening the follow-up: %w", err)
	}
	defer func() { _ = tx.Rollback(ctx) }()
	w, err := in.write(ctx, tx)
	if err != nil {
		return "", err
	}
	if err := in.notify(ctx, tx, deps, w); err != nil {
		return "", err
	}
	if err := tx.Commit(ctx); err != nil {
		return "", fmt.Errorf("planningmonitor: committing the follow-up: %w", err)
	}
	if deps.Live != nil {
		deps.Live.Publish(realtime.Event{Type: "notification." + cexFollowUpEvent, EntityType: cexFollowUpContext, EntityID: w.id,
			TargetUserID: in.lead.userID, ActorUserID: p.UserID})
	}
	if w.created {
		return "Sent to " + in.lead.name + ". It is on their To-Do.", nil
	}
	return fmt.Sprintf("Reminder %d sent to %s on the open follow-up.", w.reminders, in.lead.name), nil
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

// prepare settles what the record names: the oldest overdue age, the
// condition, the affected schools and the instruction's history line.
func (in *cexSend) prepare() {
	ids := map[string]bool{}
	for _, r := range in.f.records {
		if r.overdue != "" || r.returned || r.financeOpen {
			in.oldest = max(in.oldest, r.age)
			if r.schoolID != "" {
				ids[r.schoolID] = true
			}
		}
	}
	for id := range ids {
		in.schoolIDs = append(in.schoolIDs, id)
	}
	sort.Strings(in.schoolIDs)
	if len(in.schoolIDs) > 500 {
		in.schoolIDs = in.schoolIDs[:500]
	}
	w := in.fs.period.window()
	dash := func(s string) string {
		if s == "" {
			return "-"
		}
		return s
	}
	in.key = "cpx|" + in.fs.period.fy + "|" + w.period + ":" + w.start.Format("2006-01-02") + "|pl:" + in.fs.lead + "|cceo:" + dash(in.fs.cceo) +
		"|partner:" + dash(in.fs.partner) + "|issue:" + in.issue.Key + "|activity:" + dash(in.fs.activityID)
	name := in.sender.Name
	if name == "" {
		name = "Country Director"
	}
	in.entry = map[string]any{"at": cexISO(in.now), "by": in.sender.UserID, "name": name, "instruction": in.instruction,
		"priority": in.priority, "due": in.due.Format("2006-01-02"), "open": in.open}
}

// cexISO is datetime.isoformat() of an aware UTC moment.
func cexISO(t time.Time) string {
	t = t.UTC()
	if t.Nanosecond()/int(time.Microsecond) == 0 {
		return t.Format("2006-01-02T15:04:05") + "+00:00"
	}
	return t.Format("2006-01-02T15:04:05.000000") + "+00:00"
}

// historyLine is _history's entry.
func (in *cexSend) historyLine(action string) map[string]any {
	by, name := any(in.sender.UserID), in.sender.Name
	if in.sender.UserID == "" {
		by = "system"
	}
	if name == "" {
		name = "System"
	}
	return map[string]any{"at": cexISO(in.now), "by": by, "name": name, "action": action, "note": in.instruction}
}

// teamOversightLink is team_oversight_link: where the Lead acts.
func (in *cexSend) teamOversightLink(id string) string {
	w := in.fs.period.window()
	v := []string{"followup=" + url.QueryEscape(id), "fy=" + url.QueryEscape(in.fs.period.fy)}
	if w.period != "fy" {
		v = append(v, "period="+w.period)
		switch w.period {
		case "quarter":
			v = append(v, "quarter="+cexQuarterOf(w.start))
		case "month":
			v = append(v, "month="+strconv.Itoa(int(w.start.Month())))
		case "week":
			y, wk := w.start.ISOWeek()
			v = append(v, fmt.Sprintf("week=%04d-W%02d", y, wk))
		}
	}
	if in.fs.cceo != "" {
		v = append(v, "owner="+url.QueryEscape(in.fs.cceo))
	}
	return cexTeamOversight + "?" + strings.Join(v, "&")
}

// cexQuarterOf is get_quarter_for_date: the FY quarter (October opens Q1).
func cexQuarterOf(d time.Time) string {
	return "Q" + strconv.Itoa((int(d.Month())+2)%12/3+1)
}

// auditRow is planning_fu._audit through log(): the actor with any cover
// they hold, and the request's address, browser and correlation id.
func (in *cexSend) auditRow(ctx context.Context, tx pgx.Tx, action, id, status string, extra map[string]any) error {
	cover, err := audit.CoverageStamp(ctx, tx, in.sender.UserID, in.now)
	if err != nil {
		return err
	}
	var cceo any
	if in.fs.cceo != "" {
		cceo = in.fs.cceo
	}
	payload := map[string]any{"condition_key": in.key, "issue_type": in.issue.Key, "program_lead": in.lead.staffID, "cceo": cceo,
		"school": nil, "status": status}
	for k, v := range extra {
		payload[k] = v
	}
	role := in.sender.ActiveRole
	if _, err := audit.Append(ctx, tx, audit.Entry{Action: "planning_followup." + action, SubjectKind: audit.Text(cexFollowUpContext),
		SubjectID: audit.Text(id), ActorID: audit.Text(in.sender.UserID), ActorRole: &role, Success: true,
		Payload: audit.WithStamps(payload, cover), IPAddress: audit.Text(in.origin.IP), UserAgent: audit.Text(in.origin.UserAgent),
		CorrelationID: audit.Text(in.origin.CorrelationID)}, in.now); err != nil {
		return fmt.Errorf("planningmonitor: auditing the follow-up: %w", err)
	}
	return nil
}
