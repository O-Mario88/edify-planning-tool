package extrawork

import (
	"fmt"
	"net/url"
	"strconv"
	"time"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/closedschools"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pageheader"
)

// assignment is one hr_extra_assignment row as the page reads it.
type assignment struct {
	ID, Title, Instruction, AssignerRole, AssigneeRole, Status string
	ReturnReason, Outcome, EvidenceNote, EvidenceURI           string
	Due                                                        time.Time
	// Points is contribution_points as Python writes the Decimal, or nil.
	Points      *string
	SubmittedAt *time.Time
}

// summary is performance_summary.
type summary struct {
	verified, open, submitted, overdue int
	// points is the verified work's points as Python writes their Decimal
	// sum, or nil when none was scored.
	points         *string
	policyApproved bool
}

// view is everything the page is drawn from.
type view struct {
	role  Role
	fy    string
	query url.Values
	// today is timezone.localdate(), at midnight UTC.
	today                                    time.Time
	mine, assignedByMe, toReview, monitoring []assignment
	summary                                  summary
}

// overdue is the view's is_overdue: open work due before today.
func (v view) overdue(a assignment) bool { return open(a.Status) && a.Due.Before(v.today) }

// day is |date:"d M Y".
func day(t time.Time) string { return t.Format("02 Jan 2006") }

func text(t string) *screensv1.PagePanelItem {
	return &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Text{Text: closedschools.Collapse(t)}}
}

func toned(t, tone string) *screensv1.PagePanelItem {
	item := text(t)
	item.Tone = tone
	return item
}

func panel(title, subtitle string, items ...*screensv1.PagePanelItem) *screensv1.PageBlock {
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{Title: title, Subtitle: subtitle, Items: items}}}
}

// zeroDecimal is whether Python's Decimal of text is zero (falsy).
func zeroDecimal(text string) bool {
	f, err := strconv.ParseFloat(text, 64)
	return err == nil && f == 0
}

// caption is the Assigned to me line: the lane's counts, its points, what is
// overdue and how many the table shows.
func caption(v view) string {
	s := v.summary
	out := fmt.Sprintf("%d open · %d awaiting review · %d verified", s.open, s.submitted, s.verified)
	if s.points != nil && !zeroDecimal(*s.points) {
		f, _ := strconv.ParseFloat(*s.points, 64)
		plural := "s"
		if f == 1 {
			plural = ""
		}
		out += " · " + *s.points + " performance point" + plural
	}
	if s.overdue > 0 {
		out += fmt.Sprintf(" · %d overdue", s.overdue)
	}
	if len(v.mine) > rules.SummaryShows {
		out += fmt.Sprintf(" · showing the %d soonest of %d", rules.SummaryShows, len(v.mine))
	}
	return out
}

func cell(t, tone string) *screensv1.PageCell {
	return &screensv1.PageCell{Text: closedschools.Collapse(t), Tone: tone}
}

// mineTone is the status word's tone in the Assigned to me table.
func mineTone(status string) string {
	switch status {
	case "verified":
		return "success"
	case "returned":
		return "danger"
	case "submitted":
		return "info"
	}
	return "neutral"
}

// action is the Assigned to me row's last cell as the feed reads it: the
// button's words (the button itself is the existing application's save),
// the points verified work earned, or a dash.
func action(a assignment) string {
	switch {
	case a.Status == "assigned":
		return "Start"
	case a.Status == "acknowledged" || a.Status == "in_progress" || a.Status == "returned":
		return "Submit Result"
	case a.Status == "verified" && a.Points != nil:
		return "+" + *a.Points + " pts"
	}
	return "—"
}

func (v view) mineRow(a assignment) *screensv1.PageRow {
	task := a.Title + " " + closedschools.TruncateChars(a.Instruction, rules.Cuts.Instruction)
	if a.Status == "returned" {
		task += " Returned: " + closedschools.TruncateChars(a.ReturnReason, rules.Cuts.ReturnReason)
	}
	status := label(a.Status)
	if v.overdue(a) {
		status += " · Overdue"
	}
	return &screensv1.PageRow{Cells: []*screensv1.PageCell{
		cell(task, ""), cell(a.AssignerRole, ""), cell(day(a.Due), ""), cell(status, mineTone(a.Status)), cell(action(a), ""),
	}}
}

var mineColumns = []*screensv1.PageColumn{{Label: "Task"}, {Label: "From"}, {Label: "Due"}, {Label: "Status"}, {Label: "Action", Numeric: true}}

// mineBlocks is the Assigned to me card as the feed reads it: its heading and
// line, the table's page and, past one page, its pager.
func mineBlocks(v view) []*screensv1.PageBlock {
	number, pages := closedschools.PageOf(v.query.Get(rules.PageParam), len(v.mine), rules.PageSize)
	t := &screensv1.PageTable{Columns: mineColumns}
	for _, a := range v.mine[(number-1)*rules.PageSize : min(number*rules.PageSize, len(v.mine))] {
		t.Rows = append(t.Rows, v.mineRow(a))
	}
	out := []*screensv1.PageBlock{
		panel("Assigned to me", "", text(caption(v))),
		{Kind: &screensv1.PageBlock_Table{Table: t}},
	}
	if pages > 1 {
		out = append(out, closedschools.PagerPanel(rules.PageParam, number, pages, len(v.mine), rules.PageSize, v.query, rules.QueryKeysNotPassed))
	}
	return out
}

func reviewBlock(v view) *screensv1.PageBlock {
	items := []*screensv1.PagePanelItem{}
	for _, a := range v.toReview {
		submitted := ""
		if a.SubmittedAt != nil {
			submitted = day(a.SubmittedAt.In(zone))
		}
		items = append(items, text(a.Title+" · submitted "+submitted),
			text("Outcome: "+closedschools.TruncateChars(a.Outcome, rules.Cuts.Outcome)))
		if a.EvidenceNote != "" {
			items = append(items, text("Evidence: "+closedschools.TruncateChars(a.EvidenceNote, rules.Cuts.Evidence)))
		}
		if a.EvidenceURI != "" {
			// The feed reads the link's words only: the address is the
			// submitter's own, unchecked, and is not offered to the app.
			items = append(items, text("Evidence link"))
		}
	}
	return panel("Awaiting my review",
		"Verify what was delivered, or return it with what must be corrected — the assignee can never verify their own work.", items...)
}

func assignedByMeBlock(v view) *screensv1.PageBlock {
	items := []*screensv1.PagePanelItem{}
	for _, a := range v.assignedByMe {
		tone := "neutral"
		switch {
		case a.Status == "verified":
			tone = "success"
		case a.Status == "returned":
			tone = "warning"
		case v.overdue(a):
			tone = "danger"
		}
		status := label(a.Status)
		if v.overdue(a) {
			status += " · Overdue"
		}
		items = append(items, text(a.Title), text("· "+a.AssigneeRole+" · due "+day(a.Due)), toned(status, tone))
	}
	return panel("Assigned by me", "Everything you handed out, and where it stands.", items...)
}

func monitoringBlock(v view) *screensv1.PageBlock {
	items := []*screensv1.PagePanelItem{}
	for _, a := range v.monitoring {
		tone := "neutral"
		switch {
		case a.Status == "verified":
			tone = "success"
		case v.overdue(a):
			tone = "danger"
		}
		items = append(items, text(a.Title), toned(label(a.Status), tone))
	}
	return panel("On my team (assigned by the CD)", "You monitor these; the Country Director owns them.", items...)
}

func strip(s *Role) *screensv1.PageBlock {
	tabs := &screensv1.PageLinkTabs{Label: s.Strip.Label, Scrolls: s.Strip.Scrolls}
	for _, t := range s.Strip.Tabs {
		tabs.Tabs = append(tabs.Tabs, &screensv1.PageLinkTab{Label: t.Label, Href: t.Href, Active: t.Active})
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_LinkTabs{LinkTabs: tabs}}
}

const (
	title       = "Extra Assigned Work"
	description = "Governed assignments beyond your targets — assigned by the CD or your Program Lead, verified independently, " +
		"and counted in performance separately from target achievement."
)

// assignHref is the Assign button's link as the feed gives it: the template
// writes hx-get="…?fy={{ fy }}" unencoded, and the feed reads that query back
// (_resolved: parse_qsl, blanks dropped, names in order), so a year holding
// "&" loses what follows it.
func assignHref(fy string) string {
	query, _ := url.ParseQuery("fy=" + fy)
	return pageheader.Href("/extra-work/assign-drawer", query)
}

// page is the whole answer, in the order the template draws it.
func page(v view) *screensv1.GetPageResponse {
	header := &screensv1.PageHeader{Eyebrow: "Performance", Title: title, Description: description}
	if v.role.CanAssign {
		header.Actions = append(header.Actions, &screensv1.PageAction{
			Key: "assign_extra_work", Label: "Assign Extra Work", Primary: true, Enabled: true,
			Href: assignHref(v.fy), Drawer: true,
		})
	}
	blocks := []*screensv1.PageBlock{}
	if v.role.Strip != nil {
		blocks = append(blocks, strip(&v.role))
	}
	if !v.summary.policyApproved && v.summary.verified > 0 {
		blocks = append(blocks, panel("", "", text("Verified extra work is tracked but not yet scored — the FY scoring policy awaits approval. "+
			"Points appear here the moment it is approved.")))
	}
	if len(v.mine) > 0 {
		blocks = append(blocks, mineBlocks(v)...)
	}
	if len(v.toReview) > 0 {
		blocks = append(blocks, reviewBlock(v))
	}
	if len(v.assignedByMe) > 0 {
		blocks = append(blocks, assignedByMeBlock(v))
	}
	if len(v.monitoring) > 0 {
		blocks = append(blocks, monitoringBlock(v))
	}
	if len(v.mine)+len(v.assignedByMe)+len(v.toReview)+len(v.monitoring) == 0 {
		blocks = append(blocks, panel("", "", text("No extra work this year"),
			text("Assignments from the CD or your Program Lead appear here, with their own performance lane.")))
	}
	return &screensv1.GetPageResponse{Header: header, Blocks: blocks, WebPath: Path}
}
