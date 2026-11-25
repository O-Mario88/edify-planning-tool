package planningmonitor

import (
	"context"
	"errors"
	"fmt"
	"net/url"
	"strconv"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// cpoFollowRead is what the planning drawer and its send both read.
type cpoFollowRead struct {
	reader schooldirectory.Scope
	sys    schooldirectory.Scope
	fs     cpoFollowScope
	f      cpoFollowFigures
	today  time.Time
}

func cpoFollowReadOf(ctx context.Context, db schooldirectory.Querier, p auth.Principal, q map[string]string,
	now time.Time) (*cpoFollowRead, error) {
	reader, err := schooldirectory.ResolveScope(ctx, db, p, now)
	if err != nil {
		return nil, err
	}
	l := now.In(cpoLocation)
	today := date(l.Year(), l.Month(), l.Day())
	fs, err := cpoReadFollowScope(ctx, db, reader, q, today)
	if err != nil {
		return nil, err
	}
	sys := cexSystemScope(reader)
	roster, err := cexRosterOf(ctx, db, sys)
	if err != nil {
		return nil, err
	}
	f, err := cpoEvaluate(ctx, db, sys, fs, roster, today)
	if err != nil {
		return nil, err
	}
	return &cpoFollowRead{reader: reader, sys: sys, fs: fs, f: f, today: today}, nil
}

// leadName is the Lead's name on the evaluated dataset's roster.
func (r *cpoFollowRead) leadName() string {
	for _, l := range r.f.snap.leads {
		if l[0] == r.fs.lead {
			return l[1]
		}
	}
	return ""
}

func (r *cpoFollowRead) cceoName() string {
	if o := r.f.snap.data.owners[r.fs.cceo]; r.fs.cceo != "" && o != nil {
		return o.name
	}
	return ""
}

// CountryOversightFollowUpDrawer is the planning follow_up_view's GET:
// partials/country_oversight/drawer_follow_up.html as the feed's drawer
// reader reads it.
func CountryOversightFollowUpDrawer(ctx context.Context, db schooldirectory.Querier, p auth.Principal, q map[string]string,
	now time.Time) (*screensv1.PageDrawer, error) {
	r, err := cpoFollowReadOf(ctx, db, p, q, now)
	if err != nil {
		return nil, err
	}
	d := r.f.snap.data
	school := d.byID[r.fs.school]
	schoolName, region := "", ""
	if school != nil {
		schoolName = school.name
		region, err = cpoRegionName(ctx, db, school.regionID)
		if err != nil {
			return nil, err
		}
	}
	issueKey := strings.TrimSpace(q["issue"])
	if r.fs.school != "" && issueKey == "" {
		issueKey = "school_gap"
	}
	type row struct {
		issue                        cpoIssueRule
		required, planned, remaining int
	}
	rows := []row{}
	for _, i := range rules.CountryOversight.Page.FollowUpIssues {
		if i.Key == "school_gap" || i.Key == "other" {
			continue
		}
		a, b, c := i.metricValues(r.f.tally)
		rows = append(rows, row{i, a, b, c})
	}
	if issueKey == "" {
		issueKey = "other"
		if len(rows) > 0 {
			best := rows[0]
			for _, x := range rows[1:] {
				if x.remaining > best.remaining {
					best = x
				}
			}
			issueKey = best.issue.Key
		}
	}
	issue, ok := cpoIssueOf(issueKey)
	if !ok {
		issue, _ = cpoIssueOf("other")
	}
	lead, cceo := r.leadName(), r.cceoName()
	country := r.fs.countryOf(ctx, db, r.reader)
	facts := []*screensv1.PageFact{{Label: "Program Lead", Value: orDash(lead)}, {Label: "Affected CCEO", Value: orElse(cceo, "The Lead's whole team")},
		{Label: "Country", Value: country}, {Label: "Region", Value: orElse(region, "All regions in scope")},
		{Label: "Period", Value: d.window.label()}}
	if schoolName != "" {
		facts = append(facts, &screensv1.PageFact{Label: "School", Value: schoolName})
	}
	items := []*screensv1.DrawerItem{cexHeading("What the follow-up is about"),
		{Kind: &screensv1.DrawerItem_Facts{Facts: &screensv1.PageFacts{Facts: facts}}}, cexHeading("Planning metric, as it stands")}
	for _, x := range rows {
		items = append(items, cexDrawerText(fmt.Sprintf("%s Required %d · planned %d · %d remaining", x.issue.Label, x.required, x.planned, x.remaining)))
	}
	affected, total := []string{r.fs.school}, 1
	if r.fs.school == "" {
		affected, total = r.f.affected(issue, 8)
	}
	names := []string{}
	for _, id := range affected {
		if s := d.byID[id]; s != nil {
			names = append(names, s.name+" ("+s.code+")")
		}
	}
	if len(names) > 0 {
		line := "Affected schools: " + strconv.Itoa(total)
		if total > len(names) {
			line += " — the first " + strconv.Itoa(len(names)) + ":"
		}
		items = append(items, cexDrawerText(line+" "+strings.Join(names, ", ")))
	}
	existing, err := cpoOpenFollowUps(ctx, db, r.fs)
	if err != nil {
		return nil, err
	}
	if len(existing) > 0 {
		lines := &screensv1.PageFacts{}
		for _, status := range existing {
			lines.Facts = append(lines.Facts, &screensv1.PageFact{Value: status})
		}
		items = append(items, cexDrawerText("Already open for this scope:"), &screensv1.DrawerItem{Kind: &screensv1.DrawerItem_Lines{Lines: lines}},
			cexDrawerText("Sending the same kind again reminds the Lead on the open record; the earlier instruction is kept."))
	}
	options := []*screensv1.DrawerOption{}
	for _, i := range rules.CountryOversight.Page.FollowUpIssues {
		options = append(options, &screensv1.DrawerOption{Value: i.Key, Label: i.Label, Disabled: i.Key == "school_gap" && r.fs.school == ""})
	}
	maxLen := int32(2000)
	who := orElse(cceo, "their team")
	items = append(items, cexHeading("The ask"),
		&screensv1.DrawerItem{Kind: &screensv1.DrawerItem_Field{Field: &screensv1.DrawerField{Name: "issue", Kind: "select", Required: true,
			Value: issueKey, Options: options}}},
		&screensv1.DrawerItem{Kind: &screensv1.DrawerItem_Field{Field: &screensv1.DrawerField{Name: "due_date", Kind: "date",
			Value: r.today.AddDate(0, 0, rules.CountryExecution.FollowUps.DueInDays).Format("2006-01-02"), Required: true,
			MinDate: r.today.Format("2006-01-02")}}},
		cexSelect("priority", "normal", pairs(rules.CountryExecution.FollowUps.Priorities), nil),
		&screensv1.DrawerItem{Kind: &screensv1.DrawerItem_Field{Field: &screensv1.DrawerField{Name: "instruction", Kind: "textarea",
			Required: true, Placeholder: "What should the Lead follow up with their CCEO, and by when?", MaxLength: &maxLen}}},
		cexDrawerText("The Lead gets a To-Do and a notification that open Planning Oversight on "+who+". Nothing in any plan changes."))
	subtitle := orElse(lead, "Programme Lead")
	for _, part := range []string{cceo, schoolName} {
		if part != "" {
			subtitle += " · " + part
		}
	}
	return &screensv1.PageDrawer{Title: "Follow Up with PL", Subtitle: subtitle, HasRequired: true, Items: items,
		SubmitLabel: "Send to " + orElse(lead, "the Programme Lead"), CancelLabel: "Cancel", CanSubmit: true}, nil
}

func orElse(s, other string) string {
	if s == "" {
		return other
	}
	return s
}

func orDash(s string) string { return orElse(s, "—") }

// countryOf is scope.country or deployment_country(): the country most staff
// work in, else "Country".
func (fs cpoFollowScope) countryOf(ctx context.Context, db schooldirectory.Querier, reader schooldirectory.Scope) string {
	if reader.Country != "" {
		return reader.Country
	}
	var c string
	err := db.QueryRow(ctx, `SELECT country FROM staff_profile WHERE deleted_at IS NULL AND country IS NOT NULL AND country <> ''
		GROUP BY country ORDER BY count(*) DESC LIMIT 1`).Scan(&c)
	if err != nil || c == "" {
		return "Country"
	}
	return c
}

// cpoRegionName is dataset.region_names for one region.
func cpoRegionName(ctx context.Context, db schooldirectory.Querier, id string) (string, error) {
	if id == "" {
		return "", nil
	}
	var name string
	err := db.QueryRow(ctx, `SELECT COALESCE(name, '') FROM region WHERE id = $1`, id).Scan(&name)
	if errors.Is(err, pgx.ErrNoRows) {
		return "", nil
	}
	if err != nil {
		return "", fmt.Errorf("planningmonitor: the school's region: %w", err)
	}
	return name, nil
}

// cpoOpenFollowUps is _scoped_followups: the open follow-ups of the year of
// either stage (the Lead's and the officer's, when named), the newest
// twenty, by status.
func cpoOpenFollowUps(ctx context.Context, db schooldirectory.Querier, fs cpoFollowScope) ([]string, error) {
	page := rules.CountryOversight.Page
	rows, err := db.Query(ctx, `SELECT status FROM planning_oversight_follow_up WHERE fy = $1 AND status = ANY($2)
		AND ($3 = '' OR program_lead_staff_id = $3) AND ($4 = '' OR cceo_staff_id = $4) ORDER BY assigned_at DESC LIMIT 20`,
		fs.filters.fy, rules.CountryExecution.FollowUps.OpenStates, fs.lead, fs.cceo)
	if err != nil {
		return nil, fmt.Errorf("planningmonitor: the open follow-ups: %w", err)
	}
	defer rows.Close()
	out := []string{}
	for rows.Next() {
		var status string
		if err := rows.Scan(&status); err != nil {
			return nil, err
		}
		out = append(out, orElse(page.FollowUpStatusLabels[status], status))
	}
	return out, rows.Err()
}

// params is Filters.params: the page's selection, a month as a number.
func (f cpoFilters) params() map[string]any {
	out := map[string]any{}
	values, _ := url.ParseQuery(f.query(nil))
	for k := range values {
		v := values.Get(k)
		if k == "month" {
			if n, err := strconv.Atoi(v); err == nil {
				out[k] = n
				continue
			}
		}
		out[k] = v
	}
	return out
}
