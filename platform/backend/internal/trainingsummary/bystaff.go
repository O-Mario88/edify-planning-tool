package trainingsummary

import (
	"context"
	"net/url"
	"slices"
	"strings"
	"time"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// The words partials/trainings/coverage_by_staff.html writes.
const (
	byStaffTitle = "Training coverage by staff"
	byStaffEmpty = "No training has a ceiling or a school committed yet."
	byStaffNote  = "A school counts from the day it is committed. Partner Assigned is every school with a partner for " +
		"the training; Awaiting Partner is those the partner has not dated yet. Schools Covered counts each school " +
		"once, so it can be less than the columns added up."
	byStaffPageParam = "by_staff_page"
)

var byStaffColumns = []string{"Staff", "Training", "Ceiling", "Staff Planned", "Partner Assigned",
	"Awaiting Partner", "Group Scheduled", "Schools Covered", "Remaining", "Excess", "Status"}

// summaryRow is training_ceilings.SummaryRow: one staff member and training
// with a ceiling or a school committed.
type summaryRow struct {
	staffID, staffName        string
	trainingID, trainingName  string
	ceilingID                 string
	ceiling                   *int
	group, inSchool           int
	partner, partnerScheduled int
	both                      int
}

func (r summaryRow) total() int { return r.group + r.inSchool + r.partner - r.both }

func (r summaryRow) awaitingPartner() int { return max(r.partner-r.partnerScheduled, 0) }

// balance is the places left; nil with no ceiling.
func (r summaryRow) balance() *int {
	if r.ceiling == nil {
		return nil
	}
	left := max(*r.ceiling-r.total(), 0)
	return &left
}

func (r summaryRow) excess() int {
	if r.ceiling == nil {
		return 0
	}
	return max(r.total()-*r.ceiling, 0)
}

func (r summaryRow) state() string {
	switch {
	case r.ceiling == nil:
		return "unset"
	case r.total() > *r.ceiling:
		return "above"
	case r.total() == *r.ceiling:
		return "reached"
	}
	return "available"
}

// flag is SummaryRow.flag.
func (r summaryRow) flag() string {
	switch r.state() {
	case "above":
		return intcomma(r.excess()) + " above ceiling"
	case "available":
		return intcomma(*r.balance()) + " below ceiling"
	case "reached":
		return "At ceiling"
	}
	return "No ceiling set"
}

// counted is the number of schools a set holds.
func counted(set map[string]bool) int { return len(set) }

// summaryForStaff is training_ceilings.summary_for_staff: one row per staff
// member and training with a ceiling or anything committed, by name.
func summaryForStaff(ctx context.Context, q schooldirectory.Querier, staff []profile, fy string, now time.Time) ([]summaryRow, error) {
	if len(staff) == 0 {
		return nil, nil
	}
	byIdentity := map[string]string{}
	ids := []string{}
	names := map[string]string{}
	staffIDs := []string{}
	for _, p := range staff {
		for _, identity := range []string{p.id, p.userID} {
			if identity == "" {
				continue
			}
			if _, seen := byIdentity[identity]; !seen {
				ids = append(ids, identity)
			}
			byIdentity[identity] = p.id
		}
		if _, seen := names[p.id]; !seen {
			staffIDs = append(staffIDs, p.id)
		}
		names[p.id] = p.display()
	}
	found, err := commitments(ctx, q, ids, fy, now, func(owner, course string) (string, bool) {
		staffID, ok := byIdentity[owner]
		return pairKey(staffID, course), ok
	})
	if err != nil {
		return nil, err
	}
	ceilings, err := staffCeilings(ctx, q, staffIDs, fy)
	if err != nil {
		return nil, err
	}
	projectOwn, err := projectTrainingIDs(ctx, q)
	if err != nil {
		return nil, err
	}
	type pair struct{ staff, training string }
	keys := map[pair]bool{}
	for k := range ceilings {
		if !in(projectOwn, k[1]) {
			keys[pair{k[0], k[1]}] = true
		}
	}
	for k := range found {
		staffID, course, _ := strings.Cut(k, "\x00")
		keys[pair{staffID, course}] = true
	}
	courses := []string{}
	for k := range keys {
		if !slices.Contains(courses, k.training) {
			courses = append(courses, k.training)
		}
	}
	items, err := catalogueItems(ctx, q, courses)
	if err != nil {
		return nil, err
	}
	trainingNames := map[string]string{}
	for _, it := range items {
		trainingNames[it.id] = it.name
	}
	out := make([]summaryRow, 0, len(keys))
	for k := range keys {
		r := summaryRow{staffID: k.staff, staffName: names[k.staff], trainingID: k.training, trainingName: "Training"}
		if name, ok := trainingNames[k.training]; ok {
			r.trainingName = name
		}
		if c, ok := ceilings[[2]string{k.staff, k.training}]; ok && !in(projectOwn, k.training) {
			value := c.value
			r.ceilingID, r.ceiling = c.id, &value
		}
		if routes := found[pairKey(k.staff, k.training)]; routes != nil {
			r.group, r.inSchool = counted(routes.group), counted(routes.inSchool)
			r.partner, r.partnerScheduled = counted(routes.partner), counted(routes.partnerScheduled)
			r.both = r.group + r.inSchool + r.partner - routes.covered()
		}
		out = append(out, r)
	}
	slices.SortStableFunc(out, func(a, b summaryRow) int {
		if c := strings.Compare(strings.ToLower(a.staffName), strings.ToLower(b.staffName)); c != 0 {
			return c
		}
		if c := strings.Compare(strings.ToLower(a.trainingName), strings.ToLower(b.trainingName)); c != 0 {
			return c
		}
		// Python's order between equal names is a set's; any fixed one will do.
		return strings.Compare(a.staffID+a.trainingID, b.staffID+b.trainingID)
	})
	return out, nil
}

// staffLinkCell is the staff_link tag: the name, linked to the profile for
// a reader who may open one.
func staffLinkCell(name, ref string, opens bool) *screensv1.PageCell {
	c := plain(collapse(name))
	if name != "" && strings.TrimSpace(ref) != "" && opens {
		c.Href = "/staff/" + url.PathEscape(strings.TrimSpace(ref))
	}
	return c
}

// figureCell is one of the By staff tab's figures: the count, opening the
// schools behind it, or a muted 0.
func figureCell(r summaryRow, fy string, value int, figure, tone string, strong bool) *screensv1.PageCell {
	if value == 0 {
		return plain("0")
	}
	return &screensv1.PageCell{Text: intcomma(value), Tone: tone, Strong: strong, Href: schoolsBehind(r, fy, figure)}
}

func schoolsBehind(r summaryRow, fy, figure string) string {
	return "/training-summary/schools?staff=" + r.staffID + "&training=" + r.trainingID + "&fy=" + fy + "&figure=" + figure
}

func byStaffCells(r summaryRow, fy string, opens bool) []*screensv1.PageCell {
	ceilingText := "Not set"
	if r.ceiling != nil {
		ceilingText = intcomma(*r.ceiling)
	}
	remaining := &screensv1.PageCell{Text: "View", Href: schoolsBehind(r, fy, "remaining")}
	if left := r.balance(); left != nil {
		remaining.Text = intcomma(*left)
	}
	excess := plain("0")
	if e := r.excess(); e > 0 {
		excess = &screensv1.PageCell{Text: intcomma(e), Tone: "danger"}
	}
	return []*screensv1.PageCell{
		staffLinkCell(r.staffName, r.staffID, opens),
		plain(collapse(r.trainingName)),
		plain(ceilingText),
		figureCell(r, fy, r.inSchool, "staff", "", false),
		figureCell(r, fy, r.partner, "partner", "", false),
		figureCell(r, fy, r.awaitingPartner(), "awaiting", "warning", false),
		figureCell(r, fy, r.group, "group", "", false),
		figureCell(r, fy, r.total(), "covered", "", true),
		remaining,
		excess,
		{Text: r.flag(), Tone: rules.Coverage.SummaryFlagTones[r.state()]},
	}
}

// byStaffTable is coverage_by_staff.html under components/data_table, with
// summary_totals in its summary line.
func byStaffTable(rows []summaryRow, fy string, query url.Values, opens bool) *screensv1.PageBlock {
	covered, awaiting := 0, 0
	for _, r := range rows {
		covered += r.total()
		awaiting += r.awaitingPartner()
	}
	t := &screensv1.PageTable{
		Title:    byStaffTitle,
		Subtitle: intcomma(covered) + " covered · " + intcomma(awaiting) + " awaiting partner scheduling · FY " + fy,
	}
	if len(rows) == 0 {
		t.EmptyMessage = byStaffEmpty
		return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Table{Table: t}}
	}
	for i, label := range byStaffColumns {
		t.Columns = append(t.Columns, &screensv1.PageColumn{Label: label, Numeric: i >= 2 && i <= 9})
	}
	shown, pager := paginate(len(rows), query, byStaffPageParam)
	for _, r := range rows[shown[0]:shown[1]] {
		t.Rows = append(t.Rows, &screensv1.PageRow{Cells: byStaffCells(r, fy, opens)})
	}
	t.Footnote = byStaffNote
	if pager != nil {
		t.Pager, t.Footnote = pager, pager.GetSummary()
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Table{Table: t}}
}
