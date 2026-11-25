package teamtargets

import (
	"strconv"
	"time"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/feeddom"
)

// signals is the "What needs attention" strip.
func (d *data) signals(list []signal) *node {
	grid := el("div", "tt-signal-grid")
	for _, s := range list {
		var action *node
		switch {
		case s.drill == "core":
			action = el("a", "", s.action+" ", el("span", "", "→").Attr("aria-hidden", "true")).Attr("href", "/core-schools")
		case s.drill == "staff" || s.drill == "high_risk":
			action = el("button", "", s.action+" ", el("span", "", "→").Attr("aria-hidden", "true")).Attr("type", "button")
		default:
			action = drawerButton("", "/team-targets/matrix?fy="+d.fy, s.action+" ", el("span", "", "→").Attr("aria-hidden", "true"))
		}
		grid.Add(el("article", "tt-signal", el("span", "", s.label), el("strong", "", strconv.Itoa(s.count)), el("small", "", s.sub),
			action).Attr("data-tone", s.tone))
	}
	return el("section", "tt-signal-strip",
		el("header", "", el("span", "tt-eyebrow", "Operational signals"), el("h2", "", "What needs attention").Attr("id", "tt-signals-heading")),
		grid).Attr("aria-labelledby", "tt-signals-heading")
}

func pctOrDash(p *int) string {
	if p == nil {
		return "—"
	}
	return strconv.Itoa(*p) + "%"
}

func intcomma(n int) string {
	s := strconv.Itoa(n)
	neg := ""
	if n < 0 {
		neg, s = "-", s[1:]
	}
	out := ""
	for len(s) > 3 {
		out = "," + s[len(s)-3:] + out
		s = s[:len(s)-3]
	}
	return neg + s + out
}

// insights are Priority progress and the team trend.
func (d *data) insights(rows []progress, trend []trendPoint, teamPct int) *node {
	list := el("div", "tt-progress-list")
	for _, r := range rows {
		bar := 0
		if r.pct != nil {
			bar = min(*r.pct, 100)
		}
		list.Add(drawerButton("tt-progress-row", "/team-targets/matrix?fy="+d.fy+"&month="+strconv.Itoa(d.month)+"&area="+r.key,
			el("span", "tt-progress-row__top", el("strong", "", r.label), el("span", "", pctOrDash(r.pct))),
			el("span", "tt-progress", el("span", "").Attr("data-tone", r.tone, "style", "width:"+strconv.Itoa(bar)+"%")),
			el("small", "", intcomma(r.achieved)+" validated of "+intcomma(r.target)+" target · "+r.status)).
			Attr("aria-label", "View "+r.label+" performance detail"))
	}
	if len(rows) == 0 {
		list.Add(el("div", "tt-rail-empty", el("strong", "", "No priority data"), el("span", "", "No measurable performance priorities are agreed in this scope.")))
	}
	label := targetsFYLabel(d.fy)
	tone := "success"
	if teamPct == 0 {
		tone = "danger"
	}
	body := el("tbody", "")
	for _, p := range trend {
		v := "No assigned target"
		if p.pct != nil {
			v = strconv.Itoa(*p.pct) + "%"
		}
		body.Add(el("tr", "", el("th", "", p.month).Attr("scope", "row"), el("td", "", v)))
	}
	figure := el("figure", "tt-line-chart",
		el("p", "sr-only", "Monthly team performance trend for "+label).Attr("id", "tt-trend-title"),
		el("p", "sr-only", "Validated weighted team achievement from October through September. Months without assigned targets are shown as gaps.").Attr("id", "tt-trend-description"),
		el("div", "tt-line-chart__viewport", el("div", "").Attr("role", "img", "aria-label", "Monthly team achievement for "+label)),
		el("figcaption", "tt-insight-note", "Weighted from the same validated ledger used by each team member’s My Targets page."),
		el("table", "sr-only", el("caption", "", "Monthly team performance values for "+label),
			el("thead", "", el("tr", "", el("th", "", "Month").Attr("scope", "col"), el("th", "", "Achievement").Attr("scope", "col"))), body)).
		Attr("aria-labelledby", "tt-trend-title tt-trend-description")
	return el("div", "tt-insights-grid",
		el("section", "tt-panel tt-insight-panel",
			el("header", "tt-panel__header tt-panel__header--compact", el("div", "", el("span", "tt-eyebrow", "Selected month"), el("h2", "", "Priority progress"))),
			list),
		el("section", "tt-panel tt-insight-panel",
			el("header", "tt-panel__header tt-panel__header--compact", el("div", "", el("span", "tt-eyebrow", label), el("h2", "", "Team performance trend")),
				el("span", "tt-status", strconv.Itoa(teamPct)+"%").Attr("data-tone", tone)),
			figure))
}

// lower is Partner contribution, Districts most behind and the debrief card.
func (d *data) lower(partners []partnerRow, districts []district) *node {
	partnerPanel := el("section", "tt-panel tt-partner-panel",
		el("header", "tt-panel__header", el("div", "", el("span", "tt-eyebrow", "Delivery assurance"), el("h2", "", "Partner contribution"),
			el("p", "", "Partner-delivered work remains visible but is never double-counted into CCEO credit."))))
	if len(partners) > 0 {
		body := el("tbody", "")
		for _, p := range partners {
			// The template links partner.id, which the row does not carry
			// (it is partner_id), so the name is printed without a link.
			body.Add(el("tr", "", el("td", "", el("strong", "", p.name)), el("td", "", p.region),
				el("td", "", strconv.Itoa(p.assigned)), el("td", "", strconv.Itoa(p.scheduled)), el("td", "", strconv.Itoa(p.valid)),
				el("td", "", strconv.Itoa(p.pct)+"%"), el("td", "", strconv.Itoa(p.sf)+"%"),
				el("td", "", el("span", "tt-status", p.risk).Attr("data-tone", p.tone))))
		}
		heads := el("tr", "")
		for _, h := range []string{"Partner", "Region", "Assigned", "Scheduled", "Valid done", "Achievement", "SF ID", "Risk"} {
			heads.Add(el("th", "", h))
		}
		partnerPanel.Add(el("div", "tt-table-scroll", el("table", "tt-compact-table", el("thead", "", heads), body)))
	} else {
		partnerPanel.Add(el("div", "tt-empty tt-empty--compact", el("h3", "", "No partner-delivered activities in this scope"),
			el("p", "", "Assigned partner work will appear here without changing personal target credit.")))
	}
	list := el("div", "tt-district-list")
	for _, r := range districts {
		list.Add(el("div", "", el("span", "", el("strong", "", r.name), el("small", "", strconv.Itoa(r.staff)+" staff · "+strconv.Itoa(r.schools)+" schools")),
			el("span", "tt-district-list__score", strconv.Itoa(r.pct)+"%")))
	}
	if len(districts) == 0 {
		list.Add(el("div", "tt-rail-empty", el("strong", "", "No district data"), el("span", "", "Team members need school portfolio assignments.")))
	}
	return el("div", "tt-lower-grid", partnerPanel,
		el("aside", "tt-lower-stack",
			el("section", "tt-panel tt-insight-panel",
				el("header", "tt-panel__header tt-panel__header--compact", el("div", "", el("span", "tt-eyebrow", "Portfolio risk"), el("h2", "", "Districts most behind"))),
				list),
			el("a", "tt-panel tt-debrief-card", el("span", "tt-eyebrow", "Field intelligence"), el("h2", "", "Open team debriefs"),
				el("p", "", "Connect target variance to field evidence, blockers, and follow-up actions."),
				el("span", "", "Review debrief intelligence ", el("span", "", "→").Attr("aria-hidden", "true"))).Attr("href", "/debriefs")))
}

// dataNote is the body's footer.
func dataNote(now time.Time) *node {
	return el("footer", "tt-data-note",
		el("span", "", el("strong", "", "Validated system data."), " Achievement comes from the canonical My Targets ledger; partner delivery, SF ID compliance, and IA exceptions are reported separately."),
		el("span", "", "Refreshed "+now.Format("02 Jan 2006, 15:04")))
}

// projectSection is the workspace's Supervised-Team Project Priorities;
// Go draws it only empty (a team with Projects is handed on).
func (d *data) projectSection() *node {
	return el("section", "tt-panel",
		el("div", "tt-panel__header", el("div", "", el("span", "tt-eyebrow", "Assigned execution portfolio"),
			el("h2", "", "Supervised-Team Project Priorities").Attr("id", "team-project-priorities"),
			el("p", "", "Projects assigned by IA, the Country Director, or Admin. Manager personal Project work remains on My Targets."))),
		el("div", "tt-empty tt-empty--compact", el("h3", "", "No Projects assigned to this team scope"),
			el("p", "", "Assigned Projects will appear here automatically and remain separate from the manager’s personal priorities."))).
		Attr("aria-labelledby", "team-project-priorities")
}

// milestoneSection is Supervised-Team Milestone Allocations, drawn only
// empty as well.
func (d *data) milestoneSection() *node {
	return el("section", "tt-panel",
		el("div", "tt-panel__header", el("div", "", el("span", "tt-eyebrow", "Strategy cascade"),
			el("h2", "", "Supervised-Team Milestone Allocations").Attr("id", "team-strategic-milestones"),
			el("p", "", "Manager personal targets remain on My Targets. This table contains only the selected supervised team’s approved allocations and canonical actuals."))),
		el("div", "tt-empty tt-empty--compact", el("h3", "", "No approved supervised-team milestone allocations"),
			el("p", "", "The FY priorities remain visible above, but they do not affect team achievement or risk until their milestones are defined, approved, and allocated."))).
		Attr("aria-labelledby", "team-strategic-milestones")
}

// feedWalk reads the nodes as the feed reads the page, after out.
func feedWalk(n *node, out []*screensv1.PageBlock) []*screensv1.PageBlock {
	return feeddom.Walk(el("div", "", n), out)
}
