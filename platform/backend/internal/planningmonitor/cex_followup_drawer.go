package planningmonitor

import (
	"context"
	"fmt"
	"strconv"
	"time"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// CEXFollowUpRefusal is follow_up_view's 403 for a reader who may not follow
// up (only the Country Director does).
const CEXFollowUpRefusal = "Following up with a Programme Lead belongs to the Country Director."

// cexFollowUpRole is may_follow_up's one role.
const cexFollowUpRole = "CountryDirector"

// cexFollowNames are the names the drawer shows for the scope.
type cexFollowNames struct{ lead, cceo, partner string }

// CountryExecutionFollowUpDrawer is follow_up_view's GET:
// partials/country_execution/drawer_follow_up.html as the feed's drawer
// reader reads it, prefilled with the live figures.
func CountryExecutionFollowUpDrawer(ctx context.Context, db schooldirectory.Querier, p auth.Principal, q map[string]string,
	now time.Time) (*screensv1.PageDrawer, error) {
	reader, err := schooldirectory.ResolveScope(ctx, db, p, now)
	if err != nil {
		return nil, err
	}
	l := now.In(cpoLocation)
	today := date(l.Year(), l.Month(), l.Day())
	fs, err := cexReadFollowScope(ctx, db, reader, q, today)
	if err != nil {
		return nil, err
	}
	s, err := buildCEXSnapshot(ctx, db, reader, fs.period, today)
	if err != nil {
		return nil, err
	}
	sys := cexSystemScope(reader)
	names := cexFollowNames{}
	type row struct {
		issue cexIssueRule
		open  int
	}
	rows := []row{}
	if fs.lead != "" {
		f, err := cexEvaluate(ctx, db, sys, fs, today)
		if err != nil {
			return nil, err
		}
		for _, ld := range f.snap.roster.leads {
			if ld[0] == fs.lead {
				names.lead = ld[1]
			}
		}
		if o := f.snap.data.owners[fs.cceo]; fs.cceo != "" && o != nil {
			names.cceo = o.name
		}
		if fs.partner != "" {
			names.partner = f.snap.data.partnerName[fs.partner]
		}
		for _, issue := range rules.CountryExecution.FollowUps.Issues {
			if issue.Key == "exec_other" {
				continue
			}
			n, err := cexMetric(ctx, db, sys, issue, fs, f, today)
			if err != nil {
				return nil, err
			}
			rows = append(rows, row{issue, n})
		}
	}
	issueKey := q["issue"]
	if issueKey == "" && len(rows) > 0 {
		best := rows[0]
		for _, r := range rows[1:] {
			if r.open > best.open {
				best = r
			}
		}
		issueKey = best.issue.Key
	}
	if issueKey == "" {
		issueKey = "exec_team_gap"
	}
	w := fs.period.window()
	items := []*screensv1.DrawerItem{cexHeading("Who it goes to")}
	if fs.lead != "" {
		cceo := names.cceo
		if cceo == "" {
			cceo = "The Lead's whole team"
		}
		lead := names.lead
		if lead == "" {
			lead = "—"
		}
		facts := []*screensv1.PageFact{{Label: "Program Lead", Value: lead}, {Label: "CCEO", Value: cceo}}
		if names.partner != "" {
			facts = append(facts, &screensv1.PageFact{Label: "Partner", Value: names.partner})
		}
		facts = append(facts, &screensv1.PageFact{Label: "Period", Value: w.label()})
		items = append(items, &screensv1.DrawerItem{Kind: &screensv1.DrawerItem_Facts{Facts: &screensv1.PageFacts{Facts: facts}}})
	} else {
		options := []cpoOption{{"", "Choose a Programme Lead"}}
		for _, ld := range s.tree.leads {
			if !ld.noLead {
				options = append(options, cpoOption{ld.key, ld.name})
			}
		}
		items = append(items, cexSelect("lead", "", options, &screensv1.DrawerField{
			ReloadsPath: cexBase + "/follow-up?" + s.filters.query()}))
	}
	if len(rows) > 0 {
		items = append(items, cexHeading("Execution, as it stands"))
		for _, r := range rows {
			text := r.issue.Label + " " + strconv.Itoa(r.open) + " open"
			if r.issue.ResolutionRule == "manual" {
				text += " · closed by you when settled"
			}
			items = append(items, cexDrawerText(text))
		}
		existing, err := cexOpenFollowUps(ctx, db, fs)
		if err != nil {
			return nil, err
		}
		if len(existing) > 0 {
			// _followup_list.html read by the drawer reader's _lines: each
			// row's two spans, the mail icon (no words) and the status.
			lines := &screensv1.PageFacts{}
			for _, status := range existing {
				lines.Facts = append(lines.Facts, &screensv1.PageFact{Value: status})
			}
			items = append(items, cexDrawerText("Already open for this Lead:"),
				&screensv1.DrawerItem{Kind: &screensv1.DrawerItem_Lines{Lines: lines}})
			items = append(items, cexDrawerText("Sending the same kind again reminds the Lead on the open record; the earlier instruction is kept."))
		}
	}
	issues := []cpoOption{}
	for _, i := range rules.CountryExecution.FollowUps.Issues {
		issues = append(issues, cpoOption{i.Key, i.Label})
	}
	maxLen := int32(2000)
	items = append(items, cexHeading("The ask"),
		cexSelect("issue", issueKey, issues, nil),
		&screensv1.DrawerItem{Kind: &screensv1.DrawerItem_Field{Field: &screensv1.DrawerField{Name: "due_date", Kind: "date",
			Value: today.AddDate(0, 0, rules.CountryExecution.FollowUps.DueInDays).Format("2006-01-02"), Required: true,
			MinDate: today.Format("2006-01-02")}}},
		cexSelect("priority", "normal", pairs(rules.CountryExecution.FollowUps.Priorities), nil),
		&screensv1.DrawerItem{Kind: &screensv1.DrawerItem_Field{Field: &screensv1.DrawerField{Name: "instruction", Kind: "textarea",
			Required: true, Placeholder: "What should the Lead take up with their team, and by when?", MaxLength: &maxLen}}},
		cexDrawerText("The Lead gets a To-Do and a notification that open Planning Oversight. Nothing in any activity, plan or target changes, and the CCEO is not contacted."))
	subtitle := names.lead
	if subtitle == "" {
		subtitle = "Choose a Programme Lead"
	}
	for _, part := range []string{names.cceo, names.partner} {
		if part != "" {
			subtitle += " · " + part
		}
	}
	subtitle += " · " + w.label()
	to := names.lead
	if to == "" {
		to = "the Programme Lead"
	}
	return &screensv1.PageDrawer{Title: "Follow Up with PL", Subtitle: subtitle, HasRequired: true, Items: items,
		SubmitLabel: "Send to " + to, CancelLabel: "Cancel", CanSubmit: true}, nil
}

func cexHeading(text string) *screensv1.DrawerItem {
	return &screensv1.DrawerItem{Kind: &screensv1.DrawerItem_Heading{Heading: text}}
}

// cexSelect is a required select as the drawer reader reads it: the chosen
// option, else (the browser) the first.
func cexSelect(name, value string, options []cpoOption, base *screensv1.DrawerField) *screensv1.DrawerItem {
	f := &screensv1.DrawerField{}
	if base != nil {
		f = base
	}
	f.Name, f.Kind, f.Required = name, "select", true
	found := false
	for _, o := range options {
		f.Options = append(f.Options, &screensv1.DrawerOption{Value: o.value, Label: o.label})
		found = found || o.value == value
	}
	f.Value = value
	if !found && len(options) > 0 {
		f.Value = options[0].value
	}
	return &screensv1.DrawerItem{Kind: &screensv1.DrawerItem_Field{Field: f}}
}

// cexOpenFollowUps is _scoped: the statuses of the Lead's open execution
// follow-ups of the year (the officer's, when one is named), the newest ten.
func cexOpenFollowUps(ctx context.Context, db schooldirectory.Querier, fs cexFollowScope) ([]string, error) {
	page := rules.CountryOversight.Page
	rows, err := db.Query(ctx, `SELECT status FROM planning_oversight_follow_up WHERE fy = $1 AND module = 'execution'
		AND status = ANY($2) AND program_lead_staff_id = $3 AND ($4 = '' OR cceo_staff_id = $4) ORDER BY assigned_at DESC LIMIT 10`,
		fs.period.fy, rules.CountryExecution.FollowUps.OpenStates, fs.lead, fs.cceo)
	if err != nil {
		return nil, fmt.Errorf("planningmonitor: the Lead's open follow-ups: %w", err)
	}
	defer rows.Close()
	out := []string{}
	for rows.Next() {
		var status string
		if err := rows.Scan(&status); err != nil {
			return nil, err
		}
		if label := page.FollowUpStatusLabels[status]; label != "" {
			status = label
		}
		out = append(out, status)
	}
	return out, rows.Err()
}
