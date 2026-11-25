package teamtargets

import (
	"fmt"
	"strconv"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/feeddom"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/targets"
)

type node = feeddom.Node

var el = feeddom.El

// commandGrid is body.html's tt-command-grid: the matrix panel and the
// intervention rail.
func (d *data) commandGrid(matrix *node, support []support, plans []plan, awaiting, sfMissing, returned int) *node {
	n := len(d.t.rows)
	plural := "s"
	if n == 1 {
		plural = ""
	}
	panel := el("section", "tt-panel tt-matrix-panel",
		el("header", "tt-panel__header",
			el("div", "", el("span", "tt-eyebrow", "Validated performance"), el("h2", "", "Cumulative progress by time period"),
				el("p", "", fmt.Sprintf("%s · %s · agreed performance priorities and approved strategic allocations · %d matching team member%s",
					targets.MonthLabel(d.fy, d.month), d.categoryLabel, n, plural))),
			el("div", "tt-segmented", el("button", "", "All").Attr("type", "button"), el("button", "", "Behind").Attr("type", "button"),
				el("button", "", "High risk").Attr("type", "button")).Attr("aria-label", "Filter performance status")),
		matrix).Attr("id", "staff-performance")
	return el("div", "tt-command-grid", panel, d.rail(support, plans, awaiting, sfMissing, returned))
}

// emptyMatrix is the matrix panel's state without rows to draw.
func (d *data) emptyMatrix() *node {
	icon := el("span", "tt-empty__icon", "◎").Attr("aria-hidden", "true")
	if len(d.t.rows) > 0 {
		return el("div", "tt-empty", icon, el("h3", "", "No measurable team priorities agreed for FY "+d.fy),
			el("p", "", "Team performance rows are populated from each employee’s agreed performance priorities, not from the global activity catalogue."))
	}
	return el("div", "tt-empty", icon, el("h3", "", "No team members match these filters"),
		el("p", "", "Adjust the reporting scope to return to the full supervised team."),
		el("a", "tt-button tt-button--quiet", "Clear filters").Attr("href", "/team-planning-oversight/?view=targets&fy="+d.fy+"&month="+strconv.Itoa(d.month)))
}

func drawerButton(class, href string, children ...any) *node {
	return el("button", class, children...).Attr("type", "button", "hx-get", href, "hx-target", "#drawer-container", "hx-swap", "innerHTML")
}

// rail is the intervention rail: staff requiring support, recovery plans
// and validation issues.
func (d *data) rail(support []support, plans []plan, awaiting, sfMissing, returned int) *node {
	q := "fy=" + d.fy + "&month=" + strconv.Itoa(d.month)
	head := func(eyebrow, title string) *node {
		return el("header", "tt-panel__header tt-panel__header--compact", el("div", "", el("span", "tt-eyebrow", eyebrow), el("h2", "", title)))
	}
	list := el("div", "tt-support-list")
	for _, s := range support {
		list.Add(drawerButton("tt-support-item", "/team-targets/staff-drawer?staff="+s.userID+"&"+q,
			el("span", "tt-avatar", s.initials), el("span", "tt-support-item__copy", el("strong", "", s.name), el("small", "", s.reason)),
			el("span", "tt-status", s.status).Attr("data-tone", s.tone)))
	}
	if len(support) == 0 {
		list.Add(el("div", "tt-rail-empty", el("strong", "", "No urgent interventions"), el("span", "", "The selected team scope is at pace.")))
	}
	planList := el("div", "tt-plan-list")
	for _, p := range plans {
		tone := "success"
		if p.statusKey == "submitted" {
			tone = "warning"
		}
		planList.Add(drawerButton("tt-plan-item", "/team-targets/recovery?"+q, el("span", "tt-plan-item__icon", "↗").Attr("aria-hidden", "true"),
			el("span", "", el("strong", "", p.staff), el("small", "", p.area+" · due "+p.due.Format("02 Jan"))),
			el("span", "tt-status", p.status).Attr("data-tone", tone)))
	}
	if len(plans) == 0 {
		planList.Add(el("div", "tt-rail-empty", el("strong", "", "No active recovery plans"),
			el("span", "", "Create one when performance needs structured intervention.")))
	}
	label := func(key string) string { return rules.MetricLabels["targets_team_targets_"+key] }
	issue := func(value int, key, href string) *node {
		return drawerButton("tt-validation-card", href, el("strong", "", strconv.Itoa(value)), el("span", "", label(key)))
	}
	return el("aside", "tt-rail",
		el("section", "tt-panel tt-rail-panel", head("Intervention queue", "Staff requiring support"), list,
			el("footer", "tt-rail-panel__actions", el("button", "tt-link-button", "View all").Attr("type", "button"))),
		el("section", "tt-panel tt-rail-panel", head("Planning workflow", "Recovery plans"), planList,
			el("footer", "tt-rail-panel__actions", drawerButton("tt-link-button", "/team-targets/recovery?"+q, "View all"),
				el("button", "tt-button tt-button--primary tt-button--recovery tt-rail-panel__primary-action edify-card-action",
					"Create recovery plan").Attr("type", "button"))),
		el("section", "tt-panel tt-rail-panel",
			el("header", "tt-panel__header tt-panel__header--compact", el("div", "", el("span", "tt-eyebrow", "Data quality"), el("h2", "", "Validation issues"))),
			el("div", "tt-validation-grid",
				issue(awaiting, "awaiting_ia", "/team-targets/validation-backlog?status=awaiting_ia_verification&fy="+d.fy),
				issue(sfMissing, "missing_sf_ids", "/team-targets/sfid-backlog?fy="+d.fy),
				issue(returned, "returned_by_ia", "/team-targets/validation-backlog?status=returned_by_ia&fy="+d.fy))),
	).Attr("aria-label", "Team intervention summary")
}
