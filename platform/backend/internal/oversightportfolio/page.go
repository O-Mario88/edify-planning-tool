package oversightportfolio

import (
	"fmt"
	"net/url"
	"strconv"
	"unicode"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/closedschools"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schoolprofile"
)

// Words the page and the workspace template write.
const (
	Path               = "/team-planning-oversight/"
	title              = "Planning Oversight"
	countryDescription = "Every school in the country portfolio, under the Programme Lead and the CCEO who hold it — and what is planned on each."
	teamDescription    = "Every school your team holds, under the Programme Lead and the CCEO who hold it — and what is planned on each."
	emptyMessage       = "Widen the filters, or choose another fiscal year."
	unplannedQuery     = "?view=portfolio&planned=unplanned"
)

func isAlnum(r rune) bool { return unicode.IsLetter(r) || unicode.IsDigit(r) }

func plural(n int) string {
	if n == 1 {
		return ""
	}
	return "s"
}

func ugx(n int64) string { return "UGX " + closedschools.Comma(n) }

// view is one reading of the lens: what was asked and what was found.
type view struct {
	// base is the page the lens is drawn on (Planning Oversight or the
	// Country Map); its links go back to it.
	base        string
	country     bool
	fy          string
	years       []string
	programLead string
	district    string
	planned     string
	query       url.Values
	p           portfolio
	lens        []LensTab
}

func block[T any](kind T) *screensv1.PageBlock {
	switch k := any(kind).(type) {
	case *screensv1.PageFilters:
		return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Filters{Filters: k}}
	case *screensv1.PagePanel:
		return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: k}}
	case *screensv1.PageTable:
		return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Table{Table: k}}
	}
	panic("oversightportfolio: no block for this kind")
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

// stripBlock is _portfolio_kpis drawn by components/context_metrics.html:
// the line under a figure is cut to its figure, its sentence kept as the
// note, and a figure carries its tone only where a line is shown.
func stripBlock(v view) *screensv1.PageBlock {
	t := v.totals()
	stripTitle := "Team portfolio"
	if v.country {
		stripTitle = "Country portfolio"
	}
	planned := "No schools in scope"
	if pct := ratio(t.planned, t.schools); pct != "" {
		planned = pct
	}
	unplannedTone := "neutral"
	if t.schools-t.planned > 0 {
		unplannedTone = "danger"
	}
	figures := []schoolprofile.StripFigure{
		{Label: "Schools In Portfolio", Value: closedschools.Comma(int64(t.schools)),
			Helper: fmt.Sprintf("%d lead%s · %d officer%s", t.leads, plural(t.leads), t.officers, plural(t.officers))},
		{Label: "Schools With A Plan", Value: planned, Helper: fmt.Sprintf("%d of %d schools", t.planned, t.schools)},
		{Label: "Schools With No Plan", Value: closedschools.Comma(int64(t.schools - t.planned)), Helper: "Nothing planned all year", Link: v.base + unplannedQuery},
		{Label: "Portfolio Planned Budget", Value: ugx(t.budget), Helper: fmt.Sprintf("Across %d planned activities", t.activities)},
	}
	tones := []string{"neutral", "neutral", unplannedTone, "neutral"}
	b := schoolprofile.Strip(stripTitle, figures)
	for i, m := range b.GetStrip().GetMetrics() {
		if m.GetHelper() != "" {
			m.Tone = tones[i]
		}
	}
	return b
}

func (v view) totals() totals { return v.p.totals }

// ratio is MetricValue.ratio drawn by format_value: round(n / d * 100, 1)
// written as Python's "{:g}%", or "" with nothing to divide.
func ratio(n, d int) string {
	if d == 0 {
		return ""
	}
	value := schooldirectory.PyRound1(float64(n) / float64(d) * 100)
	return strconv.FormatFloat(value, 'g', 6, 64) + "%"
}

// filtersBlock is the workspace's filter form: the year, the lead, the
// district and the planning state. A select with nothing chosen reads as its
// first option.
func filtersBlock(v view, years []string) *screensv1.PageBlock {
	pick := func(name, label, caption, chosen string, options [][2]string) *screensv1.PageFilter {
		f := &screensv1.PageFilter{Name: name, Label: label, Caption: caption}
		for _, o := range options {
			f.Options = append(f.Options, &screensv1.PageFilterOption{Value: o[0], Label: o[1]})
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
	fys := [][2]string{}
	for _, y := range years {
		fys = append(fys, [2]string{y, "FY " + y})
	}
	leads := [][2]string{{"", "All leads"}}
	for _, o := range v.p.options {
		leads = append(leads, [2]string{o.id, fmt.Sprintf("%s (%d)", o.name, o.count)})
	}
	districts := [][2]string{{"", "All districts"}}
	for _, d := range v.p.districts {
		districts = append(districts, [2]string{d.id, d.name})
	}
	planned := [][2]string{{"", "Every school"}, {"planned", "Planned"}, {"unplanned", "Not planned"}}
	return block(&screensv1.PageFilters{
		Filters: []*screensv1.PageFilter{
			pick("fy", "Financial year", "FY", v.fy, fys),
			pick("program_lead", "Programme Lead", "", v.programLead, leads),
			pick("district", "District", "", v.district, districts),
			pick("planned", "Planning state", "Planning", v.planned, planned),
		},
		Hidden: map[string]string{"view": "portfolio"},
	})
}

func text(t string) *screensv1.PagePanelItem {
	return &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Text{Text: t}}
}

func lead(t, l string) *screensv1.PagePanelItem {
	item := text(t)
	item.Lead = l
	return item
}

// leadBlock is a lead's <summary>: the name, the folded figures and the
// planned share in its tone.
func leadBlock(l *leadGroup) *screensv1.PageBlock {
	count, planned := l.count(), l.planned()
	coverage := text("No schools")
	coverage.Tone = "neutral"
	if pct := share(planned, count); pct != nil {
		coverage = text(fmt.Sprintf("%d%% planned", *pct))
		switch {
		case *pct >= 80:
			coverage.Tone = "success"
		case *pct >= 50:
			coverage.Tone = "warning"
		default:
			coverage.Tone = "danger"
		}
	}
	return block(&screensv1.PagePanel{Items: []*screensv1.PagePanelItem{
		text(l.name),
		lead(fmt.Sprintf("%d school%s", count, plural(count)), strconv.Itoa(count)),
		text("·"),
		lead(fmt.Sprintf("%d planned", planned), strconv.Itoa(planned)),
		text("·"),
		lead(fmt.Sprintf("%d not planned", count-planned), strconv.Itoa(count-planned)),
		text("·"),
		text(ugx(l.budget())),
		coverage,
	}})
}

var columns = []*screensv1.PageColumn{
	{Label: "School ID"}, {Label: "School"}, {Label: "District"}, {Label: "Cluster"},
	{Label: "Planning"}, {Label: "Visits", Numeric: true}, {Label: "Trainings", Numeric: true},
	{Label: "Next planned"}, {Label: "Planned budget", Numeric: true},
}

func cell(t, href string) *screensv1.PageCell { return &screensv1.PageCell{Text: t, Href: href} }

// schoolRow is one school's row. Its school code is drawn as a token the
// page fills in after it renders, which the feed reads as no text.
func schoolRow(s school) *screensv1.PageRow {
	code := "—"
	if s.code != "" {
		code = ""
	}
	district := s.district
	if district == "" {
		district = "—"
	}
	cluster := cell("No cluster", "")
	if s.clusterID != "" {
		name := s.clusterName
		if name == "" {
			name = "—"
		}
		cluster = cell(name, "/clusters/"+s.clusterID)
	}
	planning := "Nothing planned"
	if s.planned() {
		planning = fmt.Sprintf("%d planned", s.activities)
	}
	next := "—"
	if s.firstDate != nil {
		next = s.firstDate.Format("2 Jan 2006")
	}
	return &screensv1.PageRow{Cells: []*screensv1.PageCell{
		cell(code, ""), cell(s.name, "/schools/"+s.code), cell(district, ""), cluster,
		cell(planning, ""), cell(strconv.Itoa(s.visits), ""), cell(strconv.Itoa(s.trainings), ""),
		cell(next, ""), cell(ugx(s.budget), ""),
	}}
}

// officerBlocks is one officer's table: the group heading folded from the
// officer's whole portfolio, the page of the listed schools, and the pager
// when there is more than one page.
func officerBlocks(o *officerGroup, query url.Values) []*screensv1.PageBlock {
	count, planned := o.count(), o.planned()
	head := fmt.Sprintf("%s %d school%s · %d planned", o.name, count, plural(count), planned)
	if count-planned > 0 {
		head += fmt.Sprintf(" %d with no plan", count-planned)
	}
	if len(o.visible) != count {
		head += fmt.Sprintf(" showing %d", len(o.visible))
	}
	param := o.pageParam()
	number, pages := closedschools.PageOf(query.Get(param), len(o.visible), rules.PageSize)
	rows := []*screensv1.PageRow{{Cells: []*screensv1.PageCell{cell(closedschools.Collapse(head), "")}}}
	start := (number - 1) * rules.PageSize
	for _, s := range o.visible[start:min(start+rules.PageSize, len(o.visible))] {
		rows = append(rows, schoolRow(s))
	}
	out := []*screensv1.PageBlock{block(&screensv1.PageTable{Columns: columns, Rows: rows})}
	if pages > 1 {
		out = append(out, closedschools.PagerPanel(param, number, pages, len(o.visible), rules.PageSize, query, rules.QueryKeysNotPassed))
	}
	return out
}

// page is the lens as the feed reads it.
func page(v view, years []string) *screensv1.GetPageResponse {
	blocks := []*screensv1.PageBlock{}
	if b := lensBlock(v.lens); b != nil {
		blocks = append(blocks, b)
	}
	blocks = append(blocks, stripBlock(v), filtersBlock(v, years))
	if len(v.p.leads) == 0 {
		blocks = append(blocks, &screensv1.PageBlock{Kind: &screensv1.PageBlock_Empty{Empty: emptyMessage}})
	}
	for _, l := range v.p.leads {
		blocks = append(blocks, leadBlock(l))
		for _, o := range l.officers {
			blocks = append(blocks, officerBlocks(o, v.query)...)
		}
	}
	description := teamDescription
	if v.country {
		description = countryDescription
	}
	return &screensv1.GetPageResponse{
		Header:  &screensv1.PageHeader{Title: title, Description: description},
		Blocks:  blocks,
		WebPath: Path,
	}
}
