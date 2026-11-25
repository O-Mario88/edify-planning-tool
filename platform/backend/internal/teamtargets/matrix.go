package teamtargets

import (
	"strconv"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/targets"
)

// head is one of matrix_heads.
type head struct{ key, label, sub string }

func (d *data) heads() []head {
	month := targets.MonthLabel(d.fy, d.month)
	for i, c := range month {
		if c == ' ' {
			month = month[:i]
			break
		}
	}
	out := []head{{"month", month, "Selected month"}}
	for _, q := range []string{"Q1", "Q2", "Q3", "Q4"} {
		out = append(out, head{q, q, targets.QuarterLabel(d.fy, q)})
	}
	return append(out, head{"fy", targetsFYLabel(d.fy), "Full year"})
}

// currentClass is the column's is-current / is-current-quarter class.
func currentClass(first bool, key, quarter string) string {
	switch {
	case first && key == quarter:
		return "is-current is-current-quarter"
	case first:
		return "is-current"
	case key == quarter:
		return "is-current-quarter"
	}
	return ""
}

// matrix is body.html's member matrix: each member's month, quarters and
// year, and under each the period matrix of their priorities.
func (d *data) matrix() *node {
	heads := d.heads()
	quarter := targets.QuarterOfMonth(d.month)
	headRow := el("tr", "", el("th", "", "Team member").Attr("scope", "col"))
	for i, h := range heads {
		small := h.sub
		if h.key == quarter {
			small += " · Current quarter"
		}
		th := el("th", "", el("span", "", h.label), el("small", "", small)).Attr("scope", "col")
		if c := currentClass(i == 0, h.key, quarter); c != "" {
			th.Attr("class", c)
		}
		headRow.Add(th)
	}
	headRow.Add(el("th", "tt-matrix__action-head", el("span", "", "Review"), el("small", "", "Details")).Attr("scope", "col"))
	body := el("tbody", "")
	q := "fy=" + d.fy + "&month=" + strconv.Itoa(d.month)
	for _, r := range d.t.rows {
		bucket := "ok"
		switch r.Status {
		case "High Risk", "Critical":
			bucket = "risk"
		case "Slightly Behind":
			bucket = "behind"
		}
		row := el("tr", "tt-member-row",
			el("td", "", el("div", "tt-person", " ",
				el("button", "tt-expand").Attr("type", "button"), " ",
				el("span", "tt-avatar", r.initials), " ",
				el("span", "tt-person__copy", " ", el("strong", "", r.member.Name), " ", el("small", "", "CCEO · "+r.districtLabel), " "), " "))).
			Attr("data-bucket", bucket, "x-show", "staffFilter === 'all'")
		for i, c := range r.Cells {
			value := "—"
			if c.DisplayPct != nil {
				value = strconv.Itoa(*c.DisplayPct) + "%"
			}
			td := el("td", "", el("div", "tt-period-cell", " ", el("strong", "tt-period-cell__value", value).Attr("data-tone", c.Tone), " ",
				el("small", "", strconv.Itoa(c.Achieved)+" of "+strconv.Itoa(c.Target)), " ", el("span", "tt-status", c.Status).Attr("data-tone", c.Tone), " "))
			if cls := currentClass(i == 0, c.Key, quarter); cls != "" {
				td.Attr("class", cls)
			}
			row.Add(td)
		}
		row.Add(el("td", "tt-matrix__action-cell", drawerButton("tt-row-action", "/team-targets/staff-drawer?staff="+r.member.UserID+"&"+q).
			Attr("aria-label", "Open "+r.member.Name+" validated achievement, pace, and blockers")))
		body.Add(row, el("tr", "tt-area-row", el("td", "", el("div", "tt-area-matrix-shell tt-area-matrix-shell--matrix",
			d.periodMatrix(r, heads, quarter))).Attr("colspan", strconv.Itoa(len(heads)+2))).
			Attr("id", "tt-desktop-areas-"+r.member.UserID, "x-show", "expandedStaff === '"+r.member.UserID+"'", "x-cloak", ""))
	}
	table := el("table", "tt-matrix", el("caption", "sr-only", "Team cumulative target and verified achievement by reporting period"),
		el("thead", "", headRow), body)
	return el("div", "",
		el("div", "tt-matrix-scroll-guide", el("span", "", "Period comparison"),
			el("span", "", "Scroll horizontally to compare Q3, Q4, and full-year performance →")).Attr("aria-hidden", "true"),
		el("div", "tt-matrix-scroll", table).Attr("data-table-scroll-region", "", "tabindex", "0",
			"aria-label", "Scrollable team performance table. Scroll horizontally to compare every quarter and the full fiscal year."),
		el("footer", "tt-panel__footer", el("span", "", "Showing "+strconv.Itoa(len(d.t.rows))+" of "+strconv.Itoa(len(d.all))+" supervised team members"),
			drawerButton("tt-link-button", "/team-targets/matrix?fy="+d.fy, "Open detailed priority matrix")))
}

// shareTone is the period matrix's share colour.
func shareTone(pct *int, good, fair int) string {
	switch {
	case pct == nil:
		return "neutral"
	case *pct >= good:
		return "success"
	case *pct >= fair:
		return "warning"
	}
	return "danger"
}

// periodMatrix is partials/targets/_period_matrix.html, the team variant,
// over one member's priorities.
func (d *data) periodMatrix(r *row, heads []head, quarter string) *node {
	top := el("tr", "", el("th", "period-matrix__label period-matrix__label--head", " ", el("span", "", "Cumulative progress by time period"), " ",
		el("small", "", "Target · achieved · share"), " ").Attr("scope", "col", "rowspan", "2"))
	measures := el("tr", "period-matrix__measures")
	for i, h := range heads {
		cls := "period-matrix__period"
		if i == 0 {
			cls += " is-current"
		}
		if h.key == quarter {
			cls += " is-current-quarter"
		}
		top.Add(el("th", cls, " ", el("span", "", h.label), " ", el("small", "", h.sub), " ").Attr("scope", "colgroup", "colspan", "3"))
		c := currentClass(i == 0, h.key, quarter)
		for _, m := range []string{"Target", "Achieved", "%"} {
			th := el("th", "", m).Attr("scope", "col")
			if c != "" {
				th.Attr("class", c)
			}
			measures.Add(th)
		}
	}
	top.Add(el("th", "tt-area-matrix__action-spacer", el("span", "sr-only", "Review")).Attr("scope", "col", "rowspan", "2"))
	body := el("tbody", "")
	for _, a := range r.Matrix {
		tr := el("tr", "", el("th", "period-matrix__label", a.Label).Attr("scope", "row"))
		for i, p := range a.Periods {
			cls := "period-matrix__target"
			if i == 0 {
				cls += " is-current"
			}
			share := "—"
			if p.DisplayPct != nil {
				share = strconv.Itoa(*p.DisplayPct) + "%"
			}
			tr.Add(el("td", cls, strconv.Itoa(p.Target)), el("td", "period-matrix__achieved", strconv.Itoa(p.Achieved)),
				el("td", "period-matrix__share", share).Attr("data-tone", shareTone(p.DisplayPct, 100, 60)))
		}
		tr.Add(el("td", "tt-area-matrix__action-spacer").Attr("aria-label", "No review action"))
		body.Add(tr)
	}
	if len(r.Cells) > 0 {
		overall := el("tr", "period-matrix__overall", el("th", "period-matrix__label", "Overall progress").Attr("scope", "row"))
		for _, c := range r.Cells {
			v := "—"
			if c.DisplayPct != nil {
				v = strconv.Itoa(*c.DisplayPct) + "%"
			}
			overall.Add(el("td", "", v).Attr("colspan", "3", "data-tone", shareTone(c.DisplayPct, 70, 50)))
		}
		overall.Add(el("td", "tt-area-matrix__action-spacer"))
		body.Add(overall)
	}
	return el("table", "tt-area-matrix", el("caption", "sr-only", r.member.Name+" agreed-priority performance by reporting period"),
		el("thead", "", top, measures), body)
}
