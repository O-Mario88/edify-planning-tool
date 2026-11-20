package closurequality

import (
	"net/url"
	"slices"
	"strconv"
	"strings"
	"time"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/closedschools"
)

func empty(message string) *screensv1.PageBlock {
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Empty{Empty: message}}
}

func cell(t string) *screensv1.PageCell { return &screensv1.PageCell{Text: closedschools.Collapse(t)} }

// page is the Analytics section shell around the closure-quality partials,
// as the feed reads them.
func page(p auth.Principal, period, fy string, sum summary, reasons []reasonRow, attention, reopened []closureRow, query url.Values) *screensv1.GetPageResponse {
	header := &screensv1.PageHeader{Title: "Closure Quality"}
	shown := "all"
	if period == "fy" {
		shown = "fy"
	}
	blocks := []*screensv1.PageBlock{
		panel("", text("Closure Quality · Edify")),
		// The frame's last value sits outside what the feed reads.
		panel("", &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Heading{Heading: "Data context Live closure ledger"}},
			text("Decision frame"), text("Which closure records should not yet be trusted, and who needs to correct them?"),
			text("Evidence"), text("Closure reasons, dates, enrolment and reopen history"),
			text("Freshness"), text("Live closure ledger"), text("Confidence")),
		{Kind: &screensv1.PageBlock_Filters{Filters: &screensv1.PageFilters{Filters: []*screensv1.PageFilter{{
			Name: "period", Label: "Period", Value: shown,
			Options: []*screensv1.PageFilterOption{{Value: "all", Label: "All time"}, {Value: "fy", Label: "FY " + fy}},
		}}}}},
	}
	if sum.recorded == 0 {
		blocks = append(blocks, empty("When a school is closed from its profile, its record appears here so the closure can be checked for duplicates, missing enrolment counts and late recording."))
	} else {
		blocks = append(blocks, summaryBlocks(sum)...)
		blocks = append(blocks, attentionBlocks(p, attention, query)...)
		blocks = append(blocks, reasonBlocks(reasons, query)...)
		blocks = append(blocks, reopenedBlocks(reopened, query)...)
	}
	blocks = append(blocks, panel("", text("All data is provisional and subject to verification.")))
	return &screensv1.GetPageResponse{Header: header, Blocks: blocks, WebPath: Path}
}

func summaryBlocks(sum summary) []*screensv1.PageBlock {
	rate := "No closures to compare"
	if sum.recorded > 0 {
		rate = strconv.FormatFloat(pyRound1(float64(sum.reopened)/float64(sum.recorded)*100), 'f', -1, 64)
		if !strings.Contains(rate, ".") {
			rate += ".0"
		}
		rate += "% of recorded closures"
	}
	lag := "—"
	if sum.averageLag != nil {
		lag = strconv.Itoa(*sum.averageLag) + " days"
	}
	strip := func(metrics ...*screensv1.PageMetric) *screensv1.PageBlock {
		return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Strip{Strip: &screensv1.PageStrip{Title: "Performance overview", Metrics: metrics}}}
	}
	return []*screensv1.PageBlock{
		{Kind: &screensv1.PageBlock_Section{Section: "Summary"}},
		strip(
			&screensv1.PageMetric{Label: "Closures recorded", Value: intcomma(sum.recorded), Note: "Schools that stopped operating"},
			&screensv1.PageMetric{Label: "Stranded duplicates", Value: intcomma(sum.stranded), Note: "Closed before the duplicate flag was resolved"},
			// The rate is drawn as the figure's helper, not its note.
			&screensv1.PageMetric{Label: "Reopened", Value: intcomma(sum.reopened), Helper: rate},
			&screensv1.PageMetric{Label: "Recording lag", Value: lag, Note: "Average between closing and being recorded"},
		),
		strip(
			&screensv1.PageMetric{Label: "No enrolment recorded", Value: intcomma(sum.missing), Note: "Cannot say what the programme lost"},
			&screensv1.PageMetric{Label: "Closed unconfirmed", Value: intcomma(sum.weak), Note: "Absence of evidence, not evidence of closure"},
			&screensv1.PageMetric{Label: "Recorded late", Value: intcomma(sum.stale), Note: "More than " + strconv.Itoa(rules.StaleDays) + " days after closing"},
			&screensv1.PageMetric{Label: "Enrolment removed", Value: intcomma(sum.removed), Note: "Learners, at the moment each school closed"},
		),
	}
}

// pyRound1 is round(x, 1).
func pyRound1(x float64) float64 {
	v, _ := strconv.ParseFloat(strconv.FormatFloat(x, 'f', 1, 64), 64)
	return v
}

// flags are a closure's quality flags, in needs_attention's order.
func flags(c closureRow) []string {
	out := []string{}
	if c.dupStatus == rules.UnresolvedDup {
		out = append(out, "Closed with its duplicate flag unresolved")
	}
	if slices.Contains(rules.WeakGroundReasons, c.reason) {
		out = append(out, "Closed without confirmation")
	}
	if c.enrolment == nil {
		out = append(out, "No enrolment recorded")
	}
	if c.underReview != 0 {
		out = append(out, strconv.Itoa(c.underReview)+" awaiting finance")
	}
	if lag := days(c); lag > rules.StaleDays {
		out = append(out, "Recorded "+strconv.Itoa(lag)+" days after closing")
	}
	return out
}

// days is the lag the row shows: the day it was recorded (UTC) less the
// day the school stopped.
func days(c closureRow) int { return int(c.createdDay.Sub(c.effective).Hours() / 24) }

func attentionBlocks(p auth.Principal, list []closureRow, query url.Values) []*screensv1.PageBlock {
	if len(list) == 0 {
		return []*screensv1.PageBlock{empty("Every closure recorded so far names a reason, carries an enrolment count and was recorded promptly.")}
	}
	links := slices.Contains(rules.SchoolProfileRoles, p.ActiveRole)
	rows := []*screensv1.PageRow{}
	for _, c := range list {
		school := cell(c.name)
		if links {
			school.Href = "/schools/" + c.schoolPK
		}
		district := c.district
		if district == "" {
			district = "—"
		}
		rows = append(rows, &screensv1.PageRow{Cells: []*screensv1.PageCell{
			cell(c.code), school, cell(district), cell(c.effective.Format("2 Jan 2006")), cell(reasonLabel(c.reason)),
			cell(strings.Join(flags(c), " ")), cell(strconv.Itoa(days(c)) + " d"),
			{Text: "View", Href: "/schools/" + c.code},
		}})
	}
	t := &screensv1.PageTable{Title: "Needs attention", Subtitle: "Closures carrying at least one quality flag. A row can carry several, and each says what it is.",
		Columns: columns(nil, "School ID", "School", "District", "Closed", "Reason", "Flags", "Lag", "")}
	return paged(t, rows, "attention_page", query)
}

func reasonBlocks(list []reasonRow, query url.Values) []*screensv1.PageBlock {
	rows := []*screensv1.PageRow{}
	for _, r := range list {
		label := reasonLabel(r.key)
		if slices.Contains(rules.WeakGroundReasons, r.key) {
			label += " Unconfirmed"
		}
		rows = append(rows, &screensv1.PageRow{Cells: []*screensv1.PageCell{
			cell(label), cell(intcomma(r.total)), cell(dashOr(r.missing)), cell(dashOr(r.reopened)), cell(intcomma(r.learned)),
		}})
	}
	t := &screensv1.PageTable{Title: "By reason", Subtitle: "Each reason carries its own missing-enrolment count. A category where nobody records learner numbers is a training problem, not a data problem.",
		Columns: columns([]bool{false, true, true, true, true}, "Reason", "Closures", "No enrolment", "Reopened", "Learners")}
	return paged(t, rows, "closure_quality_workspace_by_reason_page", query)
}

func reopenedBlocks(list []closureRow, query url.Values) []*screensv1.PageBlock {
	if len(list) == 0 {
		return nil
	}
	rows := []*screensv1.PageRow{}
	for _, c := range list {
		where := c.name + " " + c.code
		if c.district != "" {
			where += " · " + c.district
		}
		reopenedDay := c.reopenedAt.UTC()
		closedFor := int(dayOf(reopenedDay).Sub(c.effective).Hours() / 24)
		rows = append(rows, &screensv1.PageRow{Cells: []*screensv1.PageCell{
			cell(liveCode(c)), {Text: closedschools.Collapse(where), Href: "/schools/" + c.code},
			cell(c.effective.Format("2 Jan 2006")), cell(c.reopenedAt.In(zone).Format("2 Jan 2006")),
			cell(strconv.Itoa(closedFor)), cell(reasonLabel(c.reason)),
		}})
	}
	t := &screensv1.PageTable{Title: "Reopened schools", Subtitle: "A school that reopens is a closure that turned out to be wrong. Schools do resume, so this is not misconduct — it is the honest measure of how well closure decisions are being made.",
		Columns: columns([]bool{false, false, false, false, true, false}, "School ID", "School", "Closed", "Reopened", "Days closed", "Original reason")}
	return paged(t, rows, "reopened_page", query)
}

// dayOf is the calendar day of t, at midnight UTC.
func dayOf(t time.Time) time.Time {
	return time.Date(t.Year(), t.Month(), t.Day(), 0, 0, 0, 0, time.UTC)
}

// liveCode is the school's ID as the web fills in its {% school_code %} tag:
// a live school's ID, else "ID unavailable".
func liveCode(c closureRow) string {
	if !c.live {
		return closedschools.SchoolCode("")
	}
	return closedschools.SchoolCode(c.code)
}
