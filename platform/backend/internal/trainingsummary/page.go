package trainingsummary

import (
	"strconv"
	"strings"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pageheader"
)

// The words the page's templates write (pages/oversight/team_planning.html,
// partials/oversight/training_summary_workspace.html,
// partials/trainings/summary_matrix.html and its cells).
const (
	title       = "Planning Oversight"
	description = "Every training with a school committed to it this year: the schools covered out of the Country Ceiling, " +
		"the schools planned by staff, those assigned to a partner that still await the partner's date, what remains, " +
		"then each officer's schools against the ceiling their Programme Lead set."
	tableTitle    = "Staff and the summary of all their planned trainings"
	nobody        = "Nobody is in this table yet."
	nothingYet    = "No training has been planned yet this year."
	dash          = "—"
	tableFootnote = "A training is listed once a school is committed to it, and a school counts from that day: planned by staff, " +
		"assigned to a partner — before the partner has scheduled it — or invited to a group training or cluster meeting. " +
		"Awaiting Partner is the schools assigned to a partner that the partner has not dated yet; one the partner has dated " +
		"stays in Total Covered. Total Covered is the schools covered out of the Country Ceiling, each school counted once " +
		"across the country; Remaining is the Country Ceiling less Total Covered. Each staff column adds that person’s " +
		"in-school schools, the schools on their group trainings and the schools they have with a partner, awaiting the " +
		"partner’s schedule or scheduled by the partner, beside the ceiling their Programme Lead set; a Programme Lead’s own " +
		"column is marked PL, with the ceiling they set themselves. Red is above the ceiling, amber below it and green at it. " +
		"A training a project delivers is listed once, under its project, and its numbers are the schools added to the project."
)

// intcomma is Django's humanize intcomma for an integer.
func intcomma(n int) string {
	digits := strconv.Itoa(n)
	sign := ""
	if strings.HasPrefix(digits, "-") {
		sign, digits = "-", digits[1:]
	}
	for i := len(digits) - 3; i > 0; i -= 3 {
		digits = digits[:i] + "," + digits[i:]
	}
	return sign + digits
}

// collapse is the feed's whitespace-collapsed text.
func collapse(text string) string { return strings.Join(strings.Fields(text), " ") }

func plain(text string) *screensv1.PageCell { return &screensv1.PageCell{Text: text} }

// countryFigure is _country_figure.html: value schools, opening the Schools
// tab for a reader of the country, in tone.
func countryFigure(s summary, r row, value int, show, tone string) *screensv1.PageCell {
	if value == 0 {
		return plain("0")
	}
	c := &screensv1.PageCell{Text: intcomma(value), Tone: tone}
	if s.countryLinks {
		c.Href = "/team-planning-oversight/?view=trainings&tab=schools&fy=" + s.fy + "&training=" + r.trainingID + "&show=" + show
	}
	return c
}

// countryCeiling is _country_ceiling_cell.html for a training row: its text
// and its link.
func countryCeiling(s summary, r row) (string, string) {
	switch {
	case s.maySetCountry && r.countryCeilingID != "":
		return intcomma(*r.countryCeiling), "/training-ceilings/country/" + r.countryCeilingID + "/edit"
	case s.maySetCountry:
		return "Set", "/training-ceilings/country/set?training=" + r.trainingID + "&fy=" + s.fy
	case r.countryCeiling == nil:
		return "Not set", ""
	}
	return intcomma(*r.countryCeiling), ""
}

// staffCell is _summary_cell.html.
func staffCell(s summary, r row, c cell) *screensv1.PageCell {
	if c.blank() {
		return plain("0")
	}
	out := &screensv1.PageCell{Text: intcomma(c.schools), Tone: rules.Tones.Cell[c.state()]}
	if c.limit != nil {
		out.Text += " / " + intcomma(*c.limit)
	}
	switch {
	case r.project:
		out.Href = "/projects/monitoring?project=" + r.projectID
	case c.schools > 0:
		out.Href = "/training-summary/schools?staff=" + c.staffID + "&training=" + r.trainingID + "&fy=" + s.fy
	case s.maySet && c.ceilingID != "":
		out.Href = "/training-ceilings/" + c.ceilingID + "/edit"
	}
	return out
}

func rowCells(s summary, r row) []*screensv1.PageCell {
	cells := []*screensv1.PageCell{plain(collapse(r.name)), plain(collapse(r.mode))}
	if r.project {
		cells = append(cells,
			&screensv1.PageCell{Text: intcomma(r.planned), Href: "/projects/monitoring?project=" + r.projectID},
			plain(dash), plain(dash), plain(dash))
	} else {
		total := countryFigure(s, r, r.planned, "covered", rules.Tones.Country[r.countryState()])
		ceilingText, ceilingHref := countryCeiling(s, r)
		total.Text += " / " + ceilingText
		if total.Href == "" {
			total.Href = ceilingHref
		}
		remaining := plain(dash)
		if left := r.remaining(); left != nil {
			remaining.Text = intcomma(*left)
		}
		if s.countryLinks {
			remaining.Href = "/team-planning-oversight/?view=trainings&tab=schools&fy=" + s.fy + "&training=" + r.trainingID + "&show=remaining"
		}
		cells = append(cells, total,
			countryFigure(s, r, r.staffPlanned, "staff", ""),
			countryFigure(s, r, r.awaitingPartner(), "awaiting", "warning"),
			remaining)
	}
	for _, c := range r.cells {
		cells = append(cells, staffCell(s, r, c))
	}
	return cells
}

// subtitle is the card's summary slot: the flags, when any, and the year.
func subtitle(s summary) string {
	counts := map[string]int{}
	for _, r := range s.rows {
		for _, c := range r.cells {
			counts[c.state()]++
		}
	}
	if counts["above"]+counts["below"]+counts["reached"] == 0 {
		return "FY " + s.fy
	}
	return strconv.Itoa(counts["above"]) + " above · " + strconv.Itoa(counts["below"]) + " below · " +
		strconv.Itoa(counts["reached"]) + " at the number set · FY " + s.fy
}

// tableBlock is summary_matrix.html under components/data_table.
func tableBlock(s summary) *screensv1.PageBlock {
	t := &screensv1.PageTable{Title: tableTitle, Subtitle: subtitle(s)}
	switch {
	case len(s.staff) == 0:
		t.EmptyMessage = nobody
	case len(s.rows) == 0:
		t.EmptyMessage = nothingYet
	default:
		for _, label := range []string{"Training Name", "Mode of delivery"} {
			t.Columns = append(t.Columns, &screensv1.PageColumn{Label: label})
		}
		for _, label := range []string{"Total Covered / Country Ceiling", "Staff Planned", "Awaiting Partner", "Remaining"} {
			t.Columns = append(t.Columns, &screensv1.PageColumn{Label: label, Numeric: true})
		}
		for _, p := range s.staff {
			label := "# Schools (" + p.display()
			if in(s.leadIDs, p.id) {
				label += " · PL"
			}
			t.Columns = append(t.Columns, &screensv1.PageColumn{Label: collapse(label + ")"), Numeric: true})
		}
		for _, r := range s.rows {
			t.Rows = append(t.Rows, &screensv1.PageRow{Cells: rowCells(s, r)})
		}
		t.Footnote = tableFootnote
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Table{Table: t}}
}

// filterBlock is the workspace's filter_bar: the year, and a reader of the
// country's Programme Lead.
func filterBlock(s summary, years []string) *screensv1.PageBlock {
	options := []*screensv1.PageFilterOption{}
	for _, year := range years {
		options = append(options, &screensv1.PageFilterOption{Value: year, Label: "FY " + year})
	}
	filters := []*screensv1.PageFilter{{Name: "fy", Label: "Fiscal year", Value: s.fy, Options: options}}
	if len(s.leads) > 0 {
		leads := []*screensv1.PageFilterOption{{Value: "", Label: "All Programme Leads"}}
		for _, pair := range s.leads {
			leads = append(leads, &screensv1.PageFilterOption{Value: pair[0], Label: collapse(pair[1])})
		}
		filters = append(filters, &screensv1.PageFilter{Name: "program_lead", Label: "Programme Lead", Value: s.lead, Options: leads})
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Filters{Filters: &screensv1.PageFilters{
		Filters: filters, Hidden: map[string]string{"view": "trainings", "tab": "summary"},
	}}}
}

// entityTabs is the Summary / By staff / Schools strip.
func entityTabs(s summary) *screensv1.PageBlock {
	base := "/team-planning-oversight/?view=trainings"
	tail := "fy=" + s.fy + "&program_lead=" + s.lead
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_LinkTabs{LinkTabs: &screensv1.PageLinkTabs{
		Tabs: []*screensv1.PageLinkTab{
			{Label: "Summary", Href: base + "&" + tail, Active: true},
			{Label: "By staff", Href: base + "&tab=staff&" + tail},
			{Label: "Schools", Href: base + "&tab=schools&" + tail},
		},
		Scrolls: true,
	}}}
}

// lensBlock is _lens_tabs.html; a strip of one is not drawn.
func lensBlock(tabs []LensTab) *screensv1.PageBlock {
	if len(tabs) == 0 {
		return nil
	}
	out := &screensv1.PageLinkTabs{}
	for _, t := range tabs {
		out.Tabs = append(out.Tabs, &screensv1.PageLinkTab{Label: t.Label, Href: t.Href, Active: t.Active})
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_LinkTabs{LinkTabs: out}}
}

// page is the lens as the feed reads it.
func page(s summary, years []string, lens []LensTab) *screensv1.GetPageResponse {
	blocks := []*screensv1.PageBlock{}
	if b := lensBlock(lens); b != nil {
		blocks = append(blocks, b)
	}
	blocks = append(blocks, filterBlock(s, years), entityTabs(s), tableBlock(s))
	return &screensv1.GetPageResponse{
		Header:  &screensv1.PageHeader{Title: title, Description: description, Actions: ceilingButtons(s)},
		Blocks:  blocks,
		WebPath: Path,
	}
}

// ceilingButtons are the header's ceiling doors (pages/oversight/
// team_planning.html, the trainings view): a Programme Lead's Set Training
// Capacity for the officers they supervise, and the Country Ceiling for the
// roles that set it.
func ceilingButtons(s summary) []*screensv1.PageAction {
	out := []*screensv1.PageAction{}
	if s.maySet {
		out = append(out, pageheader.Drawer("+ Set Training Capacity", "/training-ceilings/set?fy="+s.fy, true))
	}
	if s.maySetCountry {
		out = append(out, pageheader.Drawer("+ Set Country Ceiling", "/training-ceilings/country/set?fy="+s.fy, true))
	}
	return out
}
