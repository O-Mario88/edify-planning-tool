package planningmonitor

import (
	"fmt"
	"strconv"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schoolprofile"
)

// executionAbout is partials/oversight/_execution_about.html as the feed
// reads it, the table's footnote.
const executionAbout = "Each person's own staff work in the year, as My Plan lists it. Visits completed are the visits counted toward a Programme Lead's 280 and a CCEO's 560: Follow up, In-school Training and the SSA Support staff schedule themselves. An in-school training is one visit and one training. SSA Support assigned to a Partner, and donor, story, invitation and social visits, are delivered work like any other, and are not among the visits. Completed: submitted with its visit or training ID, or approved; work started and not yet submitted is not. Counted: only work the Programme Lead has approved is counted in Visits Completed, Remaining to Visit, Schools Trained, Remaining to Train, Delivered of due, Trainings and Meetings, whatever day it was planned for; a Programme Lead's own work is approved when it is handed in. Remaining to Visit: the 280 or 560 less the visits completed and approved. Schools Trained: the schools the person holds that take a training and have had one completed and approved, an in-school training at the school or a group training it attended; training is read against the whole portfolio, never the 280 or 560. Remaining to Train: those schools not yet trained. Awaiting PL Approval: completed work waiting on the Programme Lead's approval, not counted until it has it; the Programme Lead is alerted. PL Approved: the work the Programme Lead has approved. Delivered of due: the work delivered and approved, whatever day it was planned for, against the work whose planned day has arrived or that is already delivered. Complete: delivered with the Salesforce ID and the form both in. Past date, not delivered: the planned day has passed and the work is not delivered (work delivered and waiting on a review is not counted here; the Country Director's Execution tab counts it as overdue). Partner activities are the dated Partner work each person handed over or monitors, or that is at a school they hold."

// executionBlocks is partials/oversight/execution_workspace.html for a
// country or region reader on its own page: the tabs, the tiles, the
// filters and the table.
func executionBlocks(x *executionMonitor, fy string, years []string, countryReader bool) []*screensv1.PageBlock {
	url := monitorPath + "?view=execution&fy=" + fy
	title := "Team execution & completion"
	if countryReader {
		title = "Country execution & completion"
	}
	return []*screensv1.PageBlock{
		{Kind: &screensv1.PageBlock_LinkTabs{LinkTabs: &screensv1.PageLinkTabs{Tabs: []*screensv1.PageLinkTab{
			{Label: "Planning", Href: monitorPath + "?view=planning"},
			{Label: "Execution & Completion", Href: monitorPath + "?view=execution", Active: true},
		}}}},
		executionStrip(x.totals, url, title),
		executionFilters(x, fy, years),
		{Kind: &screensv1.PageBlock_Table{Table: executionTable(x, fy, url)}},
	}
}

// executionStrip is _execution_kpis, each figure folded from the rows.
func executionStrip(t execution, url, title string) *screensv1.PageBlock {
	type tile struct{ key, value, helper, tone, href string }
	share := func(key string, part, whole int, helper, empty, href string) tile {
		value := empty
		if whole > 0 {
			value = ratio(part, whole)
		}
		return tile{key, value, helper, "neutral", href}
	}
	visits := fmt.Sprintf("%s of %s visits", intcomma(t.visitsDelivered), intcomma(t.visitsTarget))
	if t.outreachDelivered > 0 {
		visits += fmt.Sprintf(" · %s donor, story or social (not counted)", intcomma(t.outreachDelivered))
	}
	tiles := []tile{
		share("execution_visits_delivered_target", t.visitsDelivered, t.visitsTarget, visits, "No one in scope", ""),
		share("execution_due_delivered", t.deliveredDue, t.due,
			fmt.Sprintf("%s of %s due or delivered", intcomma(t.deliveredDue), intcomma(t.due)), "Nothing due yet", ""),
		{"execution_overdue", intcomma(t.overdue), "Planned day passed, not delivered", ifTone(t.overdue > 0, "danger"), url + "&list=overdue"},
		share("execution_complete_share", t.complete, t.delivered, fmt.Sprintf("%s no SF ID", intcomma(t.missingSalesforce)),
			"Nothing delivered yet", url+"&list=missing_salesforce"),
		{"execution_awaiting_pl", intcomma(t.awaitingPL), fmt.Sprintf("%s verified", intcomma(t.verified)), "neutral", url + "&list=awaiting_pl"},
		share("execution_partner_delivered", t.partnerDelivered, t.partnerScheduled,
			fmt.Sprintf("%s of %s partner activities", intcomma(t.partnerDelivered), intcomma(t.partnerScheduled)), "No partner work", ""),
	}
	strip := &screensv1.PageStrip{Title: title}
	for _, tl := range tiles {
		m := &screensv1.PageMetric{Label: rules.Execution.KPILabels[tl.key], Value: tl.value, Href: tl.href}
		if brief := schoolprofile.BriefHelper(tl.helper); brief != tl.helper {
			m.Note, m.Helper = tl.helper, brief
		} else {
			m.Helper = tl.helper
		}
		if m.Helper != "" {
			m.Tone = tl.tone
		}
		strip.Metrics = append(strip.Metrics, m)
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Strip{Strip: strip}}
}

// executionFilters is partials/oversight/_execution_filters.html: the year,
// the Lead when there is more than one, and the follow-up list.
func executionFilters(x *executionMonitor, fy string, years []string) *screensv1.PageBlock {
	year := &screensv1.PageFilter{Name: "fy", Label: "Financial year", Value: fy, Caption: "FY"}
	for _, y := range years {
		year.Options = append(year.Options, &screensv1.PageFilterOption{Value: y, Label: "FY " + y})
	}
	filters := []*screensv1.PageFilter{year}
	if len(x.teams) > 1 {
		lead := &screensv1.PageFilter{Name: "program_lead", Label: "Programme Lead",
			Options: []*screensv1.PageFilterOption{{Value: "", Label: "All leads"}}}
		for _, t := range x.teams {
			lead.Options = append(lead.Options, &screensv1.PageFilterOption{Value: t.key, Label: fmt.Sprintf("%s (%d)", t.name, len(t.people))})
		}
		filters = append(filters, lead)
	}
	list := &screensv1.PageFilter{Name: "list", Label: "Activities to list", Caption: "Follow up",
		Options: []*screensv1.PageFilterOption{{Value: "", Label: "Choose a list"}}}
	for _, l := range rules.Execution.Lists {
		list.Options = append(list.Options, &screensv1.PageFilterOption{Value: l[0], Label: l[1]})
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Filters{Filters: &screensv1.PageFilters{
		Filters: append(filters, list), Hidden: map[string]string{"view": "execution"}}}}
}

// executionTable is the Execution & completion table: each Lead's head
// line, their people, and their total when they have more than one.
func executionTable(x *executionMonitor, fy, url string) *screensv1.PageTable {
	t := x.totals
	table := &screensv1.PageTable{Title: "Execution & completion · FY " + fy,
		Subtitle: fmt.Sprintf("%d staff · %s of %s completed · %s with their ID", t.people, intcomma(t.delivered),
			intcomma(t.planned), intcomma(t.complete))}
	if len(x.teams) == 0 {
		// The empty table carries its message alone, without the footer.
		table.EmptyMessage = "No Programme Lead or CCEO in your scope."
		return table
	}
	table.Footnote = executionAbout
	labels := []string{"Staff", "Visits Completed", "Remaining to Visit", "Schools Trained", "Remaining to Train", "Delivered of due", "Complete"}
	for _, c := range rules.Execution.ListColumns {
		labels = append(labels, c[1])
	}
	table.Columns = columns(append(labels, "PL Approved", "Trainings", "Meetings", "Partner activities")...)
	for _, team := range x.teams {
		head := fmt.Sprintf("%s %d staff · %s of %s visits completed · %s of %s schools trained · %s past date, not completed",
			team.name, len(team.people), intcomma(team.total.visitsDelivered), intcomma(team.total.visitsTarget),
			intcomma(team.total.schoolsTrained), intcomma(team.total.trainingPortfolio), intcomma(team.total.overdue))
		table.Rows = append(table.Rows, &screensv1.PageRow{Cells: []*screensv1.PageCell{{Text: head}}})
		for _, e := range team.people {
			role := " CCEO"
			if e.isLead() {
				role = " PL"
			}
			table.Rows = append(table.Rows, executionRow(e, e.name+role, url, true))
		}
		if len(team.people) > 1 {
			table.Rows = append(table.Rows, executionRow(&team.total, team.name+" total", url, false))
		}
	}
	return table
}

// executionRow is partials/oversight/_execution_row.html: a person's row,
// whose follow-up counts open their lists, or a subtotal.
func executionRow(e *execution, label, url string, person bool) *screensv1.PageRow {
	progress := func(part, whole int) (string, string) {
		text := intcomma(part) + " / " + intcomma(whole)
		p := percentage(part, whole)
		if p != nil {
			text += " · " + strconv.Itoa(*p) + "%"
		}
		return text, executionTone(p)
	}
	visits, visitsTone := progress(e.visitsDelivered, e.visitsTarget)
	trained, trainedTone := progress(e.schoolsTrained, e.trainingPortfolio)
	due, dueTone := progress(e.deliveredDue, e.due)
	cells := []*screensv1.PageCell{{Text: label}, {Text: visits, Tone: visitsTone}, {Text: intcomma(e.remainingVisits)},
		{Text: trained, Tone: trainedTone}, {Text: intcomma(e.remainingTrain)}, {Text: due, Tone: dueTone},
		{Text: intcomma(e.complete) + " / " + intcomma(e.delivered)}}
	for _, c := range rules.Execution.ListColumns {
		n := e.listCount(c[0])
		cell := &screensv1.PageCell{Text: intcomma(n)}
		switch {
		case n > 0 && person:
			cell.Href, cell.Tone = url+"&list="+c[0]+"&person="+e.key, c[2]
		case n > 0:
			cell.Tone = c[2]
		}
		cells = append(cells, cell)
	}
	cells = append(cells, &screensv1.PageCell{Text: intcomma(e.verified)},
		&screensv1.PageCell{Text: intcomma(e.trainingsDelivered) + " / " + intcomma(e.trainingsPlanned)},
		&screensv1.PageCell{Text: intcomma(e.meetingsDelivered) + " / " + intcomma(e.meetingsPlanned)},
		&screensv1.PageCell{Text: intcomma(e.partnerDelivered) + " / " + intcomma(e.partnerScheduled)})
	return &screensv1.PageRow{Cells: cells}
}

// executionTone is execution_monitor._tone: success from 90%, info from
// 60%, neutral with nothing to measure.
func executionTone(progress *int) string {
	switch {
	case progress == nil:
		return "neutral"
	case *progress >= 90:
		return "success"
	case *progress >= 60:
		return "info"
	}
	return "warning"
}
