package personaltimeoff

import (
	"fmt"
	"strconv"
	"strings"
	"time"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schoolprofile"
)

func text(t string) *screensv1.PagePanelItem {
	return &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Text{Text: t}}
}

func heading(t string) *screensv1.PagePanelItem {
	return &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Heading{Heading: t}}
}

func links(ls ...*screensv1.PageLink) *screensv1.PagePanelItem {
	return &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Links{Links: &screensv1.PageLinks{Links: ls}}}
}

func figures(rows ...[2]string) *screensv1.PagePanelItem {
	out := []*screensv1.PageDataRow{}
	for _, r := range rows {
		out = append(out, &screensv1.PageDataRow{Label: r[0], Value: r[1]})
	}
	return &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Rows{Rows: &screensv1.PageDataRows{Rows: out}}}
}

func panel(title, subtitle string, items ...*screensv1.PagePanelItem) *screensv1.PageBlock {
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{Title: title, Subtitle: subtitle, Items: items}}}
}

func plural(n int) string {
	if n == 1 {
		return ""
	}
	return "s"
}

// slice is Django's |slice:"a:b" over a string.
func slice(s string, a, b int) string {
	r := []rune(s)
	a, b = min(a, len(r)), min(b, len(r))
	return string(r[a:b])
}

// days is "(Tue - Thu)", or "" for a date strptime cannot read.
func days(l leave) string {
	s, err1 := time.Parse(time.DateOnly, l.start)
	e, err2 := time.Parse(time.DateOnly, l.end)
	if err1 != nil || err2 != nil {
		return ""
	}
	return "(" + s.Format("Mon") + " - " + e.Format("Mon") + ")"
}

func (v *view) label(kind string) string {
	if l, ok := v.labels[kind]; ok {
		return l
	}
	return pyTitle(strings.ReplaceAll(kind, "_", " "))
}

func (v *view) reviewer(l leave, missing string) string {
	if l.reviewerID == "" {
		return "Pending Review"
	}
	if name, ok := v.reviewers[l.reviewerID]; ok {
		return name
	}
	return missing
}

func (v *view) strip() *screensv1.PageBlock {
	conflicts := "Calendar clear"
	away := v.teamTotal - v.teamAway
	return schoolprofile.Strip("Performance overview", []schoolprofile.StripFigure{
		{Label: "Days available", Value: strconv.Itoa(v.ptoRemaining), Helper: fmt.Sprintf("%d used · %d allocated", v.ptoUsed, v.ptoEntitlement)},
		{Label: "Pending requests", Value: strconv.Itoa(v.pendingCount), Helper: "Awaiting approval"},
		{Label: "Team away today", Value: strconv.Itoa(v.teamAway), Helper: fmt.Sprintf("%d of %d available", away, v.teamTotal)},
		{Label: "Active handovers", Value: strconv.Itoa(v.coverActive), Helper: "Cover assignments"},
		{Label: "Schedule conflicts", Value: "0", Helper: conflicts},
		{Label: "Team availability", Value: strconv.Itoa(roundHalfEven(float64(away)/float64(max(v.teamTotal, 1))*100)) + "%", Helper: "Current team capacity"},
	})
}

func (v *view) guidance() *screensv1.PageBlock {
	line := "Review your balance and team calendar before requesting leave."
	if v.pendingCount > 0 {
		line = "Your request is in the approval flow. Coverage activates after approval."
	}
	if v.r.LeavePolicies {
		line += " View leave policy"
	}
	return panel("Leave guidance and policy", "", text(line))
}

func (v *view) balanceStrip() *screensv1.PageBlock {
	figs := []schoolprofile.StripFigure{}
	for _, b := range v.balances {
		helper := fmt.Sprintf("of %d days · %d used", b.entitlement, b.used)
		if b.pending != 0 {
			helper += fmt.Sprintf(" · %d pending", b.pending)
		}
		switch {
		case b.remaining == 0:
			helper += " · Depleted"
		case b.remaining < 5:
			helper += " · Low"
		default:
			helper += " · Available"
		}
		figs = append(figs, schoolprofile.StripFigure{Label: b.label, Value: strconv.Itoa(b.remaining), Helper: helper})
	}
	return schoolprofile.Strip("Performance overview", figs)
}

func (v *view) requests() *screensv1.PageBlock {
	blocks := []*screensv1.PageBlock{}
	for _, l := range v.leaves {
		items := []*screensv1.PagePanelItem{text(slice(l.start, 5, 7) + "/" + slice(l.start, 8, 10)),
			text(fmt.Sprintf("%d day%s", l.charged, plural(l.charged))), text(v.label(l.kind)),
			text(strings.TrimSpace(l.start + " – " + l.end + " " + days(l)))}
		if l.coverName != "" {
			items = append(items, text("Coverage: "+l.coverName))
		}
		items = append(items, text(l.status), text(v.reviewer(l, "Pending Review")))
		blocks = append(blocks, panel("", "", items...))
	}
	if len(v.leaves) == 0 {
		blocks = append(blocks, panel("", "", text("No leave requests yet"),
			text("When you submit a request, its approval and coverage status will appear here."), text("Request leave")))
	} else {
		blocks = append(blocks, panel("", "", text("Request leave")))
	}
	segment := func(label string, n int) *screensv1.PageSegment {
		// The tab's count is a span inside its button, read as its label.
		return &screensv1.PageSegment{Label: label + " " + strconv.Itoa(n), Blocks: blocks}
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Segments{Segments: &screensv1.PageSegments{Segments: []*screensv1.PageSegment{
		segment("Upcoming", v.upcomingCount), segment("Past", v.pastCount), segment("All", len(v.leaves))}}}}
}

func initial(name string) string { return slice(name, 0, 1) }

// impactPanel is the aside: the latest request's impact, then the coverage
// and handover card.
func (v *view) impactPanel() *screensv1.PageBlock {
	items := []*screensv1.PagePanelItem{}
	if im := v.impact; im != nil {
		conference := "None"
		if im.conference {
			conference = "Yes"
		}
		items = append(items, text(slice(im.start, 5, 10)+" – "+slice(im.end, 5, 10)),
			figures([2]string{"Affected activities", strconv.Itoa(im.activities)}, [2]string{"School visit conflicts", strconv.Itoa(im.activities)},
				[2]string{"Public holidays skipped", strconv.Itoa(im.holidays)}, [2]string{"Blackout dates skipped", strconv.Itoa(im.blackout)}),
			text("Conference overlap"), text(conference))
	} else {
		items = append(items, text("No leave period to assess"), text("Impact analysis appears after you create a request."))
	}
	// "{{ my_coverages|length|add:delegations_for_me|length }} active": add
	// cannot add a queryset to a number, so the count always reads 0.
	items = append(items, text("Accountability"), heading("Coverage & handover"), text("0 active"))
	for _, c := range v.pending {
		items = append(items, text("Coverage request"), text(c.name), text(slice(c.start, 5, 99)+" – "+slice(c.end, 5, 99)))
	}
	for _, c := range v.mine {
		items = append(items, text(initial(c.name)), text("Covering "+c.name), text(c.start+" – "+c.end), text("Active"))
	}
	for _, c := range v.delegated {
		items = append(items, text(initial(c.name)), text(c.name+" covers you"), text(c.start+" – "+c.end), text("Active"))
	}
	if len(v.mine) == 0 && len(v.delegated) == 0 && len(v.pending) == 0 {
		items = append(items, text("No active handovers"), text("Coverage is created and permissioned through approved leave."))
	}
	items = append(items, text("Handover scope"), text("Planning"), text("My Plan"), text("Clusters"), text("Approvals"))
	return panel("Leave impact", "", items...)
}

func (v *view) continuity() *screensv1.PageBlock {
	items := []*screensv1.PagePanelItem{text("Calendar controls"), heading("Upcoming constraints"),
		links(&screensv1.PageLink{Text: "View all →", Href: "/public-holidays"})}
	for _, b := range v.blocks {
		parts := strings.SplitN(b[0], " ", 2)
		items = append(items, text(parts[0]), text(parts[1]), text(b[1]), text(b[2]))
	}
	if len(v.blocks) == 0 {
		items = append(items, text("No upcoming constraints"), text("The planning calendar is open."))
	}
	items = append(items, text("Risk controls"), heading("Schedule conflicts"), text("0 active"),
		text("Schedule compliant"), text("No leave-related planning conflicts detected."),
		text("Next four weeks"), heading("Team availability"))
	// Consecutive links are one links item: the report's and the first
	// person's name.
	pending := []*screensv1.PageLink{}
	if v.r.TeamAvailability {
		pending = append(pending, &screensv1.PageLink{Text: "Full report →", Href: "/leave/team-availability"})
	}
	flush := func() {
		if len(pending) > 0 {
			items = append(items, links(pending...))
			pending = nil
		}
	}
	for _, row := range v.heat {
		pending = append(pending, &screensv1.PageLink{Text: row.Name, Href: "/staff/" + row.StaffID})
		flush()
		for i, w := range row.Weeks {
			count := strconv.Itoa(w.Activities)
			if w.Status == "Blocked" {
				count = ""
			}
			if i == 0 {
				items = append(items, figures([2]string{row.Role, count}))
				continue
			}
			if count != "" {
				items = append(items, text(count))
			}
		}
	}
	flush()
	if len(v.heat) == 0 {
		items = append(items, text("No team data yet"), text("Availability will appear when team assignments are active."))
	}
	return panel("Operational continuity", "Upcoming constraints, planning risks, and team capacity in one view.", items...)
}

func (v *view) trackerBlocks() []*screensv1.PageBlock {
	columns := []*screensv1.PageColumn{}
	for _, c := range []string{"Staff", "Role", "Leave", "Period", "Days", "Balance", "Cover", "Status"} {
		columns = append(columns, &screensv1.PageColumn{Label: c})
	}
	cell := func(t string) *screensv1.PageCell { return &screensv1.PageCell{Text: t} }
	rows := []*screensv1.PageRow{}
	for _, l := range v.tracker {
		balance := "Not available"
		if remaining, ok := v.trackerBalances[[2]string{l.staffID, l.kind}]; ok {
			balance = strconv.Itoa(remaining) + "d"
		}
		coverName := "Not assigned"
		if l.coverName != "" {
			coverName = l.coverName
		}
		rows = append(rows, &screensv1.PageRow{Cells: []*screensv1.PageCell{
			cell(l.staffName + v.reviewer(l, "System")), cell(l.staffRole), cell(v.label(l.kind)), cell(l.start + " – " + l.end),
			cell(strconv.Itoa(l.charged) + "d"), cell(balance), cell(coverName), cell(l.status)}})
	}
	if len(v.tracker) == 0 {
		rows = append(rows, &screensv1.PageRow{Cells: []*screensv1.PageCell{
			cell("No team leave historyApproved and pending team requests will appear here.")}})
	}
	return []*screensv1.PageBlock{panel("Team leave tracker", ""),
		{Kind: &screensv1.PageBlock_Table{Table: &screensv1.PageTable{Columns: columns, Rows: rows}}}}
}

func page(v *view) *screensv1.GetPageResponse {
	blocks := []*screensv1.PageBlock{}
	if s := v.r.Strip; s != nil {
		tabs := &screensv1.PageLinkTabs{Label: s.Label, Scrolls: s.Scrolls}
		for _, t := range s.Tabs {
			tabs.Tabs = append(tabs.Tabs, &screensv1.PageLinkTab{Label: t.Label, Href: t.Href, Active: t.Active})
		}
		blocks = append(blocks, &screensv1.PageBlock{Kind: &screensv1.PageBlock_LinkTabs{LinkTabs: tabs}})
	}
	blocks = append(blocks, v.strip(), v.guidance(), panel("Leave balance portfolio", "", text("Remaining / annual allocation")),
		v.balanceStrip(), v.requests(), v.impactPanel(), v.continuity())
	blocks = append(blocks, v.trackerBlocks()...)
	h := &screensv1.PageHeader{Eyebrow: "Time & availability", Title: "Personal Time Off",
		Description: "Plan time away with confidence, protect delivery, and keep every handover accountable.",
		Actions:     []*screensv1.PageAction{{Key: "request_leave", Label: "Request leave", Enabled: true}}}
	return &screensv1.GetPageResponse{Header: h, Blocks: blocks, WebPath: Path}
}
