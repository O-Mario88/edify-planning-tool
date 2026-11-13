package trainingsummary

import (
	"net/url"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
)

// The words partials/trainings/coverage_table.html and the workspace's
// Schools filters write.
const (
	coverageTitle         = "Training coverage"
	coverageNeedsTraining = "Choose a training to list the schools not yet covered for it."
	coverageEmpty         = "No school matches this view."
	coverageNote          = "Assigned is not scheduled, and scheduled is not completed: a school assigned to a partner is " +
		"covered from that day and reads Partner Assigned — Awaiting Schedule until the partner dates it. Choose a " +
		"training to add the schools not yet covered for it."
	coveragePageParam = "coverage_page"
)

var coverageColumns = []string{"School ID", "School", "Training", "Staff", "Route", "Responsible", "Status", "Scheduled", "Next Action"}

// selectFilter is a select as the feed reads it: the value is the option
// marked selected, else the first.
func selectFilter(name, label, chosen string, options [][2]string) *screensv1.PageFilter {
	f := &screensv1.PageFilter{Name: name, Label: label}
	for _, o := range options {
		f.Options = append(f.Options, &screensv1.PageFilterOption{Value: o[0], Label: collapse(o[1])})
	}
	f.Value = options[0][0]
	for _, o := range options {
		if o[0] == chosen {
			f.Value = o[0]
			break
		}
	}
	return f
}

// schoolsFilters are the Training, Staff and Show selects the Schools tab adds.
func schoolsFilters(s summary, trainings [][2]string, training, staff, show string) []*screensv1.PageFilter {
	trainingOptions := append([][2]string{{"", "All trainings"}}, trainings...)
	staffOptions := [][2]string{{"", "All staff"}}
	for _, p := range s.staff {
		staffOptions = append(staffOptions, [2]string{p.id, p.display()})
	}
	return []*screensv1.PageFilter{
		selectFilter("training", "Training", training, trainingOptions),
		selectFilter("staff", "Staff", staff, staffOptions),
		selectFilter("show", "Show", show, rules.Coverage.ShowOptions),
	}
}

func coverageCells(r coverageRow, opens bool) []*screensv1.PageCell {
	route := rules.Coverage.RouteLabels[r.route]
	if route == "" {
		route = dash
	}
	if r.cluster != "" {
		route += " · " + r.cluster
	}
	if r.repeat {
		route += " · same school, counted once"
	}
	responsible := r.responsible
	if responsible == "" {
		responsible = dash
	}
	status := &screensv1.PageCell{Text: rules.Coverage.StatusLabels[r.status], Tone: rules.Coverage.StatusTones[r.status]}
	switch {
	case r.activityID != "":
		status.Href = "/my-plan/" + r.activityID
	case r.assignmentID != "":
		status.Href = "/partner-oversight/"
	}
	scheduled := "No"
	if r.scheduled() {
		scheduled = "Yes"
		if r.date != nil {
			scheduled = r.date.Format("2 Jan 2006")
		}
	}
	return []*screensv1.PageCell{
		// {% school_code %} is a token span the feed reads as nothing.
		plain(""),
		{Text: collapse(r.schoolName), Href: "/schools/" + r.schoolPK},
		plain(collapse(r.trainingName)),
		staffLinkCell(r.staffName, r.staffID, opens),
		plain(collapse(route)),
		plain(collapse(responsible)),
		status,
		plain(scheduled),
		plain(r.nextAction()),
	}
}

// coverageBlock is coverage_table.html under components/data_table.
func coverageBlock(c coverage, fy string, query url.Values, opens bool) *screensv1.PageBlock {
	subtitle := intcomma(c.schoolCount) + " school"
	if c.schoolCount != 1 {
		subtitle += "s"
	}
	for _, count := range c.counts {
		subtitle += " · " + count[1] + " " + count[0]
	}
	t := &screensv1.PageTable{Title: coverageTitle, Subtitle: subtitle + " · FY " + fy}
	if len(c.rows) == 0 {
		t.EmptyMessage = coverageEmpty
		if c.needsTraining {
			t.EmptyMessage = coverageNeedsTraining
		}
		return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Table{Table: t}}
	}
	for _, label := range coverageColumns {
		t.Columns = append(t.Columns, &screensv1.PageColumn{Label: label})
	}
	shown, pager := paginate(len(c.rows), query, coveragePageParam)
	for _, r := range c.rows[shown[0]:shown[1]] {
		t.Rows = append(t.Rows, &screensv1.PageRow{Cells: coverageCells(r, opens)})
	}
	t.Footnote = coverageNote
	if pager != nil {
		t.Pager, t.Footnote = pager, pager.GetSummary()
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Table{Table: t}}
}
