package programmeschools

import (
	"fmt"
	"net/url"
	"strconv"
	"strings"
	"time"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/closedschools"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schoolprofile"
)

// pageParam is the table's own page in the query ({% paginate rows
// "programme_page" %}).
const pageParam = "programme_page"

// school is one row: a school, and what it has taken of its year.
type school struct {
	ID, Code, Name, Type, TypeLabel string
	District, Owner                 string
	OwnerID, ClusterID              string
	// SSAAverage is the latest confirmed assessment's average, or nil; and
	// SSATone its band's colour.
	SSAAverage *float64
	SSATone    string
	// VisitsUsed of VisitsAllowed staff support visits this year.
	VisitsUsed, VisitsAllowed int
	VisitLabel, VisitTone     string
	NextVisit                 *time.Time
	TrainingLabel             string
	TrainingPlanned           bool
}

// option is one <option> of a filter.
type option struct{ value, label string }

// filterState is the page's query as the view reads it (each value
// stripped) and the year it validated.
type filterState struct {
	q, schoolType, district, fy string
}

// view is everything the page is drawn from.
type view struct {
	doors     Doors
	f         filterState
	query     url.Values
	years     []string
	districts []option
	// byType counts the whole filtered list by type; total is their sum.
	byType map[string]int
	total  int
	rows   []school
}

// header is the page header as the feed reads it: "Clear search" is offered
// while a search is on.
func header(q string) *screensv1.PageHeader {
	h := &screensv1.PageHeader{
		Eyebrow:     "School lifecycle",
		Title:       "Programme Schools",
		Description: "Core Trained, Core Graduate and Champion schools. Core Trained and Core Graduate schools are planned exactly like client schools, trainings and partner support included; Champion schools take Donor and Content/Story visits from Edify staff.",
	}
	if q != "" {
		h.Actions = append(h.Actions, closedschools.ClearSearch(q, Path))
	}
	return h
}

// strip is the four figures above the list. The total is of the whole
// filtered list; the two planned counts are of the rows the page holds
// (programme_schools counts them over result.rows).
func strip(v view) *screensv1.PageBlock {
	visits, trainings := 0, 0
	for _, s := range v.rows {
		if s.NextVisit != nil {
			visits++
		}
		if s.TrainingPlanned {
			trainings++
		}
	}
	comma := func(n int) string { return closedschools.Comma(int64(n)) }
	return schoolprofile.Strip("Performance overview", []schoolprofile.StripFigure{
		{Label: "Programme schools", Value: comma(v.total), Helper: "Core Trained, Core Graduate and Champion"},
		{Label: "With a visit planned", Value: comma(visits), Helper: "FY" + v.f.fy + ", from the Activity ledger"},
		{Label: "No visit planned", Value: comma(max(0, v.total-visits)), Helper: "The year's outstanding work"},
		{Label: "Attached to a training", Value: comma(trainings), Helper: "Named on a live cluster session"},
	})
}

// selectBlock is one <select> as the feed reads it: the selected option's
// value, or the first option's when none is selected.
func selectBlock(name, label, selected string, options []option) *screensv1.PageFilter {
	f := &screensv1.PageFilter{Name: name, Label: label}
	for i, o := range options {
		if i == 0 {
			f.Value = o.value
		}
		f.Options = append(f.Options, &screensv1.PageFilterOption{Value: o.value, Label: closedschools.Collapse(o.label)})
	}
	for _, o := range options {
		if o.value == selected {
			f.Value = o.value
			break
		}
	}
	return f
}

// filters is the page's filter bar: the type with each type's count over the
// filtered list, every district, and the year.
func filters(v view) *screensv1.PageBlock {
	types := []option{{"", "All three types"}}
	for _, t := range rules.SchoolTypes {
		types = append(types, option{t[0], fmt.Sprintf("%s (%d)", t[1], v.byType[t[0]])})
	}
	years := []option{}
	for _, y := range v.years {
		years = append(years, option{y, "FY" + y})
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Filters{Filters: &screensv1.PageFilters{Filters: []*screensv1.PageFilter{
		selectBlock("school_type", "School type", v.f.schoolType, types),
		selectBlock("district", "District", v.f.district, append([]option{{"", "All districts"}}, v.districts...)),
		selectBlock("fy", "Fiscal year", v.f.fy, years),
	}}}}
}

// scoreText is |floatformat:"-1": one place, none when it is a whole number.
func scoreText(v float64) string {
	return strings.TrimSuffix(strconv.FormatFloat(v, 'f', 1, 64), ".0")
}

func cell(text, href, tone string) *screensv1.PageCell {
	return &screensv1.PageCell{Text: closedschools.Collapse(text), Href: href, Tone: tone}
}

func orElse(text, fallback string) string {
	if text == "" {
		return fallback
	}
	return text
}

// row is one school as the table writes it.
func row(s school, d Doors) *screensv1.PageRow {
	ssa, ssaTone := "Not assessed", ""
	if s.SSAAverage != nil {
		ssa, ssaTone = scoreText(*s.SSAAverage)+"/10", s.SSATone
	}
	left := "entitlement used"
	if n := max(0, s.VisitsAllowed-s.VisitsUsed); n > 0 {
		left = fmt.Sprintf("%d left", n)
	}
	visit := s.VisitLabel
	if s.NextVisit != nil {
		visit += " " + s.NextVisit.Format("2 Jan 2006")
	}
	training := "danger"
	if s.TrainingPlanned {
		training = "neutral"
	}
	// A planner's row offers Schedule, a button the feed reads no link from;
	// anyone else's is a link to the school.
	action := cell("Schedule", "", "")
	if !d.Schedule {
		action = cell("View", "/schools/"+s.Code, "")
	}
	return &screensv1.PageRow{Cells: []*screensv1.PageCell{
		// The School ID is filled in by the page's script, so the feed reads none.
		cell("", "", ""),
		cell(s.Name+" "+s.Code, "/schools/"+s.Code, ""),
		cell(s.TypeLabel, "", ""),
		cell(orElse(s.District, "—"), "", ""),
		cell(orElse(s.Owner, "Unassigned"), "", ""),
		cell(ssa, "", ssaTone),
		cell(fmt.Sprintf("%d/%d %s", s.VisitsUsed, s.VisitsAllowed, left), "", ""),
		cell(visit, "", s.VisitTone),
		cell(s.TrainingLabel, "", training),
		action,
	}}
}

func textPanel(text string) *screensv1.PageBlock {
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{Items: []*screensv1.PagePanelItem{
		{Kind: &screensv1.PagePanelItem_Text{Text: text}},
	}}}}
}

// partnerNote is the line under the list.
const partnerNote = "Partner delivery is closed to every school on this page. The Assign control is greyed on the school's own profile with the same reason, and the partner creation door refuses it, so a bulk path cannot hand one over."

// table is the list: one page of its rows, past one page the pager under it
// (read as a panel, as the archive's is), and the line about partners.
func table(v view) []*screensv1.PageBlock {
	t := &screensv1.PageTable{}
	for _, label := range []string{"School ID", "School", "Type", "District", "Owner", "SSA", "Visits FY" + v.f.fy, "Visit plan", "Training"} {
		t.Columns = append(t.Columns, &screensv1.PageColumn{Label: label})
	}
	t.Columns = append(t.Columns, &screensv1.PageColumn{Numeric: true})
	number, pages := closedschools.PageOf(v.query.Get(pageParam), len(v.rows), rules.PageSize)
	for _, s := range v.rows[(number-1)*rules.PageSize : min(number*rules.PageSize, len(v.rows))] {
		t.Rows = append(t.Rows, row(s, v.doors))
	}
	out := []*screensv1.PageBlock{{Kind: &screensv1.PageBlock_Table{Table: t}}}
	if pages > 1 {
		out = append(out, closedschools.PagerPanel(pageParam, number, pages, len(v.rows), rules.PageSize, v.query, rules.QueryKeysNotPassed))
	}
	return append(out, textPanel(partnerNote))
}

// emptyMessage is what the page says in the list's place: a search or a
// filter that matched nothing is not an empty list.
func emptyMessage(f filterState) string {
	if f.q != "" || f.schoolType != "" || f.district != "" {
		return "Clear the filters to see every Core Trained, Core Graduate and Champion school in your portfolio."
	}
	return "A school arrives here when it is verified as a core candidate, graduates the core programme, or is advanced to Champion. Until then it is on the School Directory with everyone else."
}

// page is the whole answer.
func page(v view) *screensv1.GetPageResponse {
	blocks := []*screensv1.PageBlock{strip(v), filters(v)}
	if len(v.rows) > 0 {
		blocks = append(blocks, table(v)...)
	} else {
		blocks = append(blocks, &screensv1.PageBlock{Kind: &screensv1.PageBlock_Empty{Empty: emptyMessage(v.f)}})
	}
	return &screensv1.GetPageResponse{Header: header(v.f.q), Blocks: blocks, WebPath: Path}
}
