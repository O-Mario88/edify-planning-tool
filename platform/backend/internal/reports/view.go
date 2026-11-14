package reports

import (
	"strconv"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/decisionlog"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schoolprofile"
)

func text(t string) *screensv1.PagePanelItem {
	return &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Text{Text: t}}
}

func heading(t string) *screensv1.PagePanelItem {
	return &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Heading{Heading: t}}
}

func panel(title, subtitle string, items ...*screensv1.PagePanelItem) *screensv1.PageBlock {
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{Title: title, Subtitle: subtitle, Items: items}}}
}

// pct is a period's share of its target.
func (p period) pct() *int {
	if !p.hasTarget || p.target == 0 {
		return nil
	}
	n := pyRound(float64(p.achieved) / p.target * 100)
	return &n
}

// status is an area's standing on its year's target.
func status(pct int) string {
	switch {
	case pct >= onTrack:
		return "On Track"
	case pct >= atRisk:
		return "At Risk"
	}
	return "Off Track"
}

func intOr0(p *int) int {
	if p == nil {
		return 0
	}
	return *p
}

// page is the Analytics section shell around the reports panel, as the feed
// reads it.
func page(strip *decisionlog.Strip, fy string, choices []string, ps []period, matrix [][]cell) *screensv1.GetPageResponse {
	header := &screensv1.PageHeader{Title: "Programme Output Reports"}
	options := []*screensv1.PageFilterOption{}
	for _, c := range choices {
		options = append(options, &screensv1.PageFilterOption{Value: c, Label: "FY " + c})
	}
	blocks := []*screensv1.PageBlock{panel("", "", text("Programme Output Reports · Edify"))}
	if strip != nil {
		tabs := &screensv1.PageLinkTabs{Label: strip.Label, Scrolls: strip.Scrolls}
		for _, t := range strip.Tabs {
			tabs.Tabs = append(tabs.Tabs, &screensv1.PageLinkTab{Label: t.Label, Href: t.Href, Active: t.Active})
		}
		blocks = append(blocks, &screensv1.PageBlock{Kind: &screensv1.PageBlock_LinkTabs{LinkTabs: tabs}})
	}
	blocks = append(blocks,
		// The frame's last value sits outside what the feed reads.
		panel("", "", heading("Data context Selected financial year"),
			text("Decision frame"), text("Are verified results accumulating fast enough to meet the approved reporting targets?"),
			text("Evidence"), text("Verified delivery against approved FY targets"),
			text("Freshness"), text("Selected financial year"), text("Confidence")),
		&screensv1.PageBlock{Kind: &screensv1.PageBlock_Filters{Filters: &screensv1.PageFilters{Filters: []*screensv1.PageFilter{
			{Name: "fy", Label: "Financial year", Value: fy, Options: options}}}}},
		panel("Target progress timeline", "Performance cadence", text("See how verified delivery accumulates from the current month through the full financial year.")))
	for _, p := range ps {
		value := strconv.Itoa(p.achieved)
		subtitle := p.kind + " · No target"
		if p.hasTarget {
			value += " / " + floatformat0(p.target)
			n := strconv.Itoa(intOr0(p.pct()))
			state := "On track"
			if p.dimmed {
				state = "Not started"
			}
			subtitle = p.kind + " · " + n + "% · " + state + " · Achieved · " + n
		}
		blocks = append(blocks, &screensv1.PageBlock{Kind: &screensv1.PageBlock_Record{Record: &screensv1.PageRecord{
			Title: p.chevron, Subtitle: subtitle, Facts: []*screensv1.PageFact{{Label: "Targets achieved", Value: value}}}}})
	}
	blocks = append(blocks, panel("Core target performance", "Annual delivery", text("Compare verified activity volumes with the approved FY"+fy+" operating targets.")),
		cards(fy, matrix))
	blocks = append(blocks, insights(fy, ps, matrix)...)
	blocks = append(blocks, panel("", "", text("All data is provisional and subject to verification.")))
	return &screensv1.GetPageResponse{Header: header, Blocks: blocks, WebPath: Path}
}

// cards is the core target headline: each area's year against its target.
func cards(fy string, matrix [][]cell) *screensv1.PageBlock {
	metrics := []*screensv1.PageMetric{}
	for i, a := range rules.Areas {
		c := matrix[i][len(matrix[i])-1]
		m := &screensv1.PageMetric{Label: a.Label, Value: strconv.Itoa(c.achieved)}
		helper, tone := "No FY"+fy+" target configured", "neutral"
		if c.target != nil {
			pct := intOr0(c.pct)
			m.Value += " / " + fixed0(*c.target)
			helper = strconv.Itoa(pct) + "% of FY" + fy + " target"
			tone = map[string]string{"On Track": "success", "At Risk": "warning", "Off Track": "danger"}[status(pct)]
		}
		// A helper that starts with a figure stays the line under the figure,
		// with its tone; any other is the tile's note.
		if brief := schoolprofile.BriefHelper(helper); brief != "" {
			m.Helper, m.Tone = brief, tone
		} else {
			m.Note = helper
		}
		metrics = append(metrics, m)
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Strip{Strip: &screensv1.PageStrip{Title: "Core target headline", Metrics: metrics}}}
}

// insights is the Performance insights disclosure: the trend, target health
// and priorities.
func insights(fy string, ps []period, matrix [][]cell) []*screensv1.PageBlock {
	var on, risk, off int
	priorities := []*screensv1.PagePanelItem{}
	for i, a := range rules.Areas {
		c := matrix[i][len(matrix[i])-1]
		if c.target == nil {
			priorities = append(priorities, text("•"), heading(a.Label),
				text("No FY"+fy+" target configured — set a target to track achievement."), text("No Target"))
			continue
		}
		pct := intOr0(c.pct)
		switch status(pct) {
		case "On Track":
			on++
		case "At Risk":
			risk++
		default:
			off++
		}
		priorities = append(priorities, heading(a.Label),
			text(strconv.Itoa(pct)+"% achieved against the FY"+fy+" target ("+strconv.Itoa(c.achieved)+" / "+fixed0(*c.target)+")."),
			text(status(pct)))
	}
	assessed := on + risk + off
	blocks := []*screensv1.PageBlock{
		panel("", "", text("Performance insights"), text("Trend, target health and management priorities")),
		panel("Performance insights", "Decision support", text("Use trend, target health and priority signals to focus the next management action.")),
	}
	if assessed == 0 && !ps[0].hasTarget {
		blocks = append(blocks, &screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{
			Title: "Cumulative Progress Trend", Badges: []*screensv1.PageBadge{{Tone: "plain"}},
			Items: []*screensv1.PagePanelItem{text("No FY" + fy + " targets are configured, so there is no share of target to chart. Set targets in Target Setting to see progress by period here.")}}}})
	} else {
		list := []*screensv1.PagePanelItem{}
		for _, p := range ps {
			share := "no target"
			if p.hasTarget {
				share = strconv.Itoa(intOr0(p.pct())) + "%"
			}
			list = append(list, text(p.chevron+": "+share))
		}
		blocks = append(blocks, panel("Cumulative Progress Trend", ""), panel("", "", list...))
	}
	if assessed > 0 {
		blocks = append(blocks, panel("Achievement vs Target", ""),
			&screensv1.PageBlock{Kind: &screensv1.PageBlock_Chart{Chart: &screensv1.PageChart{Horizontal: true,
				Categories: []string{"On track (≥70%)", "At risk (50–69%)", "Off track (<50%)"},
				Series:     []*screensv1.PageSeries{{Values: []float64{float64(on), float64(risk), float64(off)}}}}}},
			panel("", "", &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Rows{Rows: &screensv1.PageDataRows{Rows: []*screensv1.PageDataRow{
				{Label: "Overall FY" + fy + " Achievement", Value: strconv.Itoa(intOr0(ps[len(ps)-1].pct())) + "%"}}}}}))
	} else {
		blocks = append(blocks, panel("Achievement vs Target", "",
			text("No FY"+fy+" targets are configured yet. Set targets in Target Setting to see on-track / at-risk / off-track status here.")))
	}
	return append(blocks, panel("Top Priorities", "", priorities...))
}
