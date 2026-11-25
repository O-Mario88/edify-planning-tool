package planningmonitor

import (
	"context"
	"strings"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/activities"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
)

// SendPlanningFollowUp is the planning follow_up_view's POST through
// send_follow_up: the follow-up created, or the open one reminded. A
// *CEXFollowUpError is a refusal to show.
func SendPlanningFollowUp(ctx context.Context, db *pgxpool.Pool, deps CEXSendDeps, p auth.Principal, values map[string]string,
	origin activities.Origin, now time.Time) (string, error) {
	if p.Acting != nil || p.InActingAppointment {
		return "", ErrCEXFollowUpHandOn
	}
	if p.ActiveRole != cexFollowUpRole {
		return "", cexRefuse(CEXFollowUpRefusal)
	}
	now = now.Truncate(time.Microsecond)
	l := now.In(cpoLocation)
	today := date(l.Year(), l.Month(), l.Day())
	issue, ok := cpoIssueOf(strings.TrimSpace(values["issue"]))
	if !ok {
		return "", cexRefuse("Choose what kind of follow-up this is.")
	}
	instruction, priority, due, err := fuCommonChecks(values, today)
	if err != nil {
		return "", err
	}
	r, err := cpoFollowReadOf(ctx, db, p, values, now)
	if err != nil {
		return "", err
	}
	lead, err := cexLeadOf(ctx, db, r.fs.lead)
	if err != nil {
		return "", err
	}
	if lead == nil || lead.userID == "" {
		return "", cexRefuse("This gap has no Programme Lead on record, so there is nobody to follow up with. Place the officer under a Programme Lead first.")
	}
	if lead.role != "Program Lead" {
		return "", cexRefuse(lead.name + " is not a Programme Lead.")
	}
	required, planned, remaining := issue.metricValues(r.f.tally)
	if issue.ResolutionRule == "metric_zero" && remaining <= 0 {
		return "", cexRefuse("There is no " + strings.ToLower(issue.Label) + " in this scope right now, so there is nothing to follow up.")
	}
	schools, affected := []string{r.fs.school}, 1
	if r.fs.school == "" {
		schools, affected = r.f.affected(issue, 500)
	}
	a := r.ask(issue, *lead, required, planned, remaining, schools, affected)
	a.sender, a.origin, a.now, a.due, a.instruction, a.priority = p, origin, now, due, instruction, priority
	name := orElse(p.Name, "Country Director")
	a.entry = map[string]any{"at": cexISO(now), "by": p.UserID, "name": name, "instruction": instruction, "priority": priority,
		"due": due.Format("2006-01-02"), "required": required, "planned": planned, "remaining": remaining}
	a.sentAudit = map[string]any{"required": required, "planned": planned, "remaining": remaining,
		"due": due.Format("2006-01-02"), "priority": priority}
	return fuSend(ctx, db, deps, a)
}

// fuCommonChecks is send_follow_up's checks after the issue: the
// instruction, the due date and the priority.
func fuCommonChecks(values map[string]string, today time.Time) (string, string, time.Time, error) {
	instruction := strings.TrimSpace(values["instruction"])
	if instruction == "" {
		return "", "", time.Time{}, cexRefuse("Write the instruction for the Programme Lead.")
	}
	due, err := time.Parse("2006-01-02", strings.TrimSpace(values["due_date"]))
	if err != nil {
		return "", "", time.Time{}, cexRefuse("Give the follow-up a due date.")
	}
	if due.Before(today) {
		return "", "", time.Time{}, cexRefuse("The due date cannot be in the past.")
	}
	priority := strings.TrimSpace(values["priority"])
	for _, p := range rules.CountryExecution.FollowUps.Priorities {
		if p[0] == priority {
			return instruction, priority, due, nil
		}
	}
	return "", "", time.Time{}, cexRefuse("Choose a priority.")
}

// ask is the planning record: the condition, the school or officer it is
// about, and the snapshot of the page's selection and policy.
func (r *cpoFollowRead) ask(issue cpoIssueRule, lead cexFollowLead, required, planned, remaining int, schools []string,
	affected int) *fuAsk {
	d := r.f.snap.data
	dash := func(s string) string { return orElse(s, "-") }
	key := "cpo|" + r.fs.filters.fy + "|" + d.window.period + ":" + d.window.start.Format("2006-01-02") + "|pl:" + r.fs.lead +
		"|cceo:" + dash(r.fs.cceo) + "|issue:" + issue.Key + "|school:" + dash(r.fs.school)
	schoolName := ""
	if s := d.byID[r.fs.school]; r.fs.school != "" && s != nil {
		schoolName = s.name
	}
	snapshot := map[string]any{"filters": r.fs.filters.params(), "policy_version": rules.CountryOversight.Page.PolicyVersion,
		"as_of": d.asOf.Format("2006-01-02"), "required": required, "planned": planned, "remaining": remaining}
	return &fuAsk{module: "planning", key: key, issueKey: issue.Key, issueLabel: issue.Label, metricKey: issue.Remaining,
		resolutionRule: issue.ResolutionRule, required: required, planned: planned, remaining: remaining, affected: affected,
		schoolIDs: schools, snapshot: snapshot, cceo: r.fs.cceo, cceoName: r.cceoName(), school: r.fs.school,
		schoolName: schoolName, fy: r.fs.filters.fy, country: r.reader.Country, w: d.window, lead: lead,
		remindAudit: func(n int) map[string]any { return map[string]any{"reminder_count": n} }}
}
