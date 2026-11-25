package planningmonitor

import (
	"context"
	"fmt"
	"strconv"
	"strings"
	"time"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/feeddom"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// cpoReader is what the page may offer its reader (country_oversight_views:
// _may_read_quality, may_follow_up, RolePermissionService.can_export).
type cpoReader struct {
	readQuality, followUp, export bool
	// seesSchools is _may_see_schools: school-level rows are part of the
	// reader's reading of the country.
	seesSchools bool
}

func cpoReaderFor(role string, mayExport bool) cpoReader {
	return cpoReader{
		readQuality: role == "ImpactAssessment" || role == "CountryDirector" || role == "Admin",
		followUp:    role == "CountryDirector",
		export:      mayExport,
	}
}

// cpoCountry is header["country"]: the reader's own country, else the one
// most of the deployment's staff work in, else "Country".
func cpoCountry(ctx context.Context, db schooldirectory.Querier, scope schooldirectory.Scope) (string, error) {
	if c := strings.TrimSpace(scope.Country); c != "" && c != schooldirectory.NoCountry {
		return c, nil
	}
	var country string
	err := db.QueryRow(ctx, `SELECT COALESCE((SELECT country FROM staff_profile WHERE country IS NOT NULL AND country <> ''
		GROUP BY country ORDER BY COUNT(*) DESC, country LIMIT 1), '')`).Scan(&country)
	if err != nil {
		return "", fmt.Errorf("planningmonitor: deployment country: %w", err)
	}
	if country == "" {
		country = "Country"
	}
	return country, nil
}

// pctParen is the template's "(n%)" or "(—)".
func pctParen(part, whole int) *feeddom.Node {
	return feeddom.El("span", "cpo-pct", paren(part, whole))
}

// capacityBlock is _capacity.html under service.capacity.
func capacityBlock(snap *cpoSnapshot) *feeddom.Node {
	c := rules.CountryOversight
	roles := map[string]*[3]int{"pl_personal": {}, "cceo": {}}
	for _, lead := range snap.tree.leads {
		for _, owner := range lead.owners {
			entry := roles[owner.kind]
			if entry == nil || owner.ceiling == 0 {
				continue
			}
			t := cpoTally(owner.tally)
			entry[0]++
			entry[1] += t.n("p_visits")
			entry[2] += t.n("target")
		}
	}
	t := cpoTally(snap.tree.country)
	phased := snap.tree.window.hasPhasedTarget()
	dl := feeddom.El("dl", "cpo-capacity")
	gauge := func(label string, each int, e *[3]int) {
		note := "visits planned · " + cpoFmt(e[0]) + " × " + strconv.Itoa(each)
		if phased {
			note += ", phased for the period"
		}
		dl.Add(feeddom.El("div", "cpo-cap",
			feeddom.El("dt", "cpo-cap-name", label),
			feeddom.El("dd", "cpo-cap-figure", feeddom.El("strong", "", cpoFmt(e[1])), " / "+cpoFmt(e[2])+" ", pctParen(e[1], e[2])),
			feeddom.El("dd", "cpo-cap-note", note)))
	}
	gauge("Programme Leads", c.StaffCeilings[rules.ProgramLeadRole], roles["pl_personal"])
	gauge("CCEOs", c.StaffCeilings[rules.CCEORole], roles["cceo"])
	dl.Add(feeddom.El("div", "cpo-cap",
		feeddom.El("dt", "cpo-cap-name", "Partner target"),
		feeddom.El("dd", "cpo-cap-figure", feeddom.El("strong", "", cpoFmt(t.n("partner_assigned"))),
			" / "+cpoFmt(t.n("partner_expected"))+" ", pctParen(t.n("partner_assigned"), t.n("partner_expected"))),
		feeddom.El("dd", "cpo-cap-note", "visits assigned · "+cpoFmt(t.n("core_partner_slots"))+" Core + "+
			cpoFmt(t.n("client_partner_expected"))+" beyond staff capacity · "+cpoFmt(t.n("partner_scheduled"))+" dated by Partners")))
	over, people, coreOnly := t.n("over_cap"), t.n("over_cap_people"), t.n("core_only_people")
	note := "nobody has planned past 280 or 560"
	switch {
	case phased:
		note = "read for the whole year, not a quarter or a month"
	case people > 0:
		note = cpoFmt(over) + " visit" + pluralize(over, "", "s") + " planned past 280 or 560: saved, and the Partner's share"
	}
	if coreOnly > 0 {
		note += " · " + strconv.Itoa(coreOnly) + " with Core schools taking the whole ceiling"
	}
	dl.Add(feeddom.El("div", "cpo-cap",
		feeddom.El("dt", "cpo-cap-name", "Past the ceiling"),
		feeddom.El("dd", "cpo-cap-figure", feeddom.El("strong", "", strconv.Itoa(people)), " "+pluralize(people, "person", "people")),
		feeddom.El("dd", "cpo-cap-note", note)))
	return dl
}

// rowCells is _cells.html over service.row_cells for one row of the people
// table; scope and people say whose figures the links open.
func rowCells(t cpoTally, query, scope, people string, followups int) []*feeddom.Node {
	fig := func(text, table, list, kind string) *feeddom.Node {
		return scopedFigure(text, query, kind, table, list, scope, people)
	}
	cover := func(parts ...any) *feeddom.Node { return feeddom.El("td", "cpo-cover", parts...) }
	of := func(a, b string) string { return cpoFmt(t.n(a)) + " / " + cpoFmt(t.n(b)) }
	plan := []any{feeddom.El("span", "", fig(cpoFmt(t.n("p_visits")), "visits", "", ""))}
	if t.n("target") > 0 {
		plan = []any{feeddom.El("span", "", fig(cpoFmt(t.n("p_visits")), "visits", "", ""), " / "+cpoFmt(t.n("target"))),
			" ", pctParen(t.n("p_visits"), t.n("target"))}
	}
	alert := func(n int, text, table string) *feeddom.Node {
		if n == 0 {
			return feeddom.El("td", "", feeddom.El("span", "cpo-zero", "0"))
		}
		return feeddom.El("td", "", feeddom.El("span", "cpo-alert", fig(text, table, "", "")))
	}
	fu := feeddom.El("td", "", feeddom.El("span", "cpo-zero", "0"))
	if followups > 0 {
		fu = feeddom.El("td", "", feeddom.El("span", "cpo-alert", strconv.Itoa(followups)))
	}
	return []*feeddom.Node{
		cover(plan...),
		cover(feeddom.El("span", "", fig(cpoFmt(t.n("p_core_visits")), "visits", "", "core"), " / ",
			fig(cpoFmt(t.n("core_staff_slots")), "", "core", "")), " ", pctParen(t.n("p_core_visits"), t.n("core_staff_slots"))),
		cover(feeddom.El("span", "", fig(cpoFmt(t.n("p_client_visits")), "visits", "", ""), " / ",
			fig(cpoFmt(t.n("client_staff_expected")), "", "client", "")), " ", pctParen(t.n("p_client_visits"), t.n("client_staff_expected"))),
		feeddom.El("td", "", fig(cpoFmt(t.n("partner_expected")), "", "partner_queue", "")),
		feeddom.El("td", "", fig(cpoFmt(t.n("client_partner_expected")), "", "client_staff_visits_left", "")),
		cover(feeddom.El("span", "", fig(of("partner_assigned", "partner_expected"), "partners", "", "")), " ",
			pctParen(t.n("partner_assigned"), t.n("partner_expected"))),
		cover(feeddom.El("span", "", fig(cpoFmt(t.n("partner_scheduled")), "", "partner_dated", "")), " ",
			pctParen(t.n("partner_scheduled"), t.n("partner_expected"))),
		feeddom.El("td", "", fig(cpoFmt(t.n("schools")), "", "all", "")),
		feeddom.El("td", "", fig(cpoFmt(t.n("core_schools")), "", "core", "")),
		feeddom.El("td", "", fig(cpoFmt(t.n("client_schools")), "", "all", "client")),
		feeddom.El("td", "", fig(cpoFmt(t.n("core_trained_schools")), "", "all", "core_trained")),
		feeddom.El("td", "", fig(cpoFmt(t.n("core_graduate_schools")), "", "all", "core_graduate")),
		cover(feeddom.El("span", "", fig(of("any_visit", "visit_schools"), "", "visited", "")), " ",
			pctParen(t.n("any_visit"), t.n("visit_schools"))),
		alert(t.n("unplanned"), cpoFmt(t.n("unplanned")), "not-planned"),
		feeddom.El("td", "", fig(cpoFmt(t.n("unclustered")), "unclustered", "", "")),
		cover(feeddom.El("span", "", fig(of("training_staff", "training_staff_slots"), "trainings", "", "")), " ",
			pctParen(t.n("training_staff"), t.n("training_staff_slots"))),
		cover(feeddom.El("span", "", fig(of("training_partner", "training_partner_slots"), "trainings", "", "")), " ",
			pctParen(t.n("training_partner"), t.n("training_partner_slots"))),
		cover(feeddom.El("span", "", fig(of("training", "training_slots"), "", "training", "")), " ",
			pctParen(t.n("training"), t.n("training_slots"))),
		alert(t.n("no_training"), cpoFmt(t.n("no_training")), "no-training"),
		cover(feeddom.El("span", "", fig(of("meeting_covered_clustered", "clustered"), "meetings", "", "")), " ",
			pctParen(t.n("meeting_covered_clustered"), t.n("clustered"))),
		fu,
	}
}

// drillBlocks is _table.html as the feed reads it: the heading and its
// tools, the capacity figures, the three readings and the table's first
// body — the country's row (each Lead is a body of its own, opened in the
// browser, and the feed reads the first).
func drillBlocks(snap *cpoSnapshot, country string, reader cpoReader, countryFollowups int) []*screensv1.PageBlock {
	query := snap.filters.query(nil)
	tools := feeddom.El("div", "cpo-drill-tools")
	if reader.readQuality {
		tools.Add(feeddom.El("button", "cpo-quiet", feeddom.El("span", "cpo-tool-label", "Data Quality")).
			Attr("type", "button", "title", "Data Quality", "hx-get", cpoPath+"drawer?kind=dq&"+query,
				"hx-target", "#drawer-container", "hx-swap", "innerHTML"))
	}
	if reader.export {
		tools.Add(feeddom.El("a", "cpo-export", feeddom.El("span", "cpo-tool-label", "Export")).
			Attr("href", cpoPath+"coverage-export?"+query, "title", "Export", "download", ""))
	}
	header := feeddom.El("header", "cpo-drill-head",
		feeddom.El("h2", "cpo-drill-name", "Country ", feeddom.El("span", "", "→"), " Program Lead ",
			feeddom.El("span", "", "→"), " CCEO ", feeddom.El("span", "", "→"), " Partner Drill-down"),
		tools)
	head := feeddom.El("tr", "")
	for _, c := range rules.CountryOversight.Page.TableColumns {
		head.Add(feeddom.El("th", "", c[1]))
	}
	row := feeddom.El("tr", "", feeddom.El("th", "cpo-namecell", feeddom.El("span", "", country+" (Total)")))
	for _, td := range rowCells(cpoTally(snap.tree.country), query, "all=1", "", countryFollowups) {
		row.Add(td)
	}
	row.Add(feeddom.El("td", "cpo-actcell", feeddom.El("span", "cpo-none", "—")))
	table := feeddom.El("table", "cpo-table", feeddom.El("thead", "", head), feeddom.El("tbody", "", row))
	section := feeddom.El("section", "cpo-drill", header, capacityBlock(snap),
		feeddom.PreBlock(cpoChips("People figures", rules.CountryOversight.Page.TableViews)),
		feeddom.El("div", "cpo-tscroll", table))
	return feeddom.Walk(feeddom.El("div", "", section), nil)
}

// cpoFollowUp is one card of _followups_panel.
type cpoFollowUp struct {
	id, title, to, status string
	date                  time.Time
	reminders             int
}

// cpoFollowUps is _followups_panel and open_counts: the open planning
// follow-ups of the year in one stage (planning or execution), the newest
// five, and the count per row.
func cpoFollowUps(ctx context.Context, db schooldirectory.Querier, fy, module string, loc *time.Location) (int, []cpoFollowUp, error) {
	page := rules.CountryOversight.Page
	rows, err := db.Query(ctx, `SELECT id, issue_type, COALESCE(NULLIF(activity_label, ''), NULLIF(school_name, ''),
		NULLIF(partner_name, ''), NULLIF(cceo_name, ''), program_lead_name), program_lead_name, status,
		COALESCE(last_reminder_at, assigned_at), reminder_count
		FROM planning_oversight_follow_up WHERE fy = $1 AND status = ANY($2) AND module = $3
		ORDER BY assigned_at DESC`, fy, page.FollowUpOpenStates, module)
	if err != nil {
		return 0, nil, fmt.Errorf("planningmonitor: open follow-ups: %w", err)
	}
	defer rows.Close()
	count, out := 0, []cpoFollowUp{}
	for rows.Next() {
		var f cpoFollowUp
		var issue, subject, status string
		if err := rows.Scan(&f.id, &issue, &subject, &f.to, &status, &f.date, &f.reminders); err != nil {
			return 0, nil, fmt.Errorf("planningmonitor: open follow-up: %w", err)
		}
		count++
		if len(out) == 5 {
			continue
		}
		label := page.FollowUpIssueLabels[issue]
		if label == "" {
			label = issue
		}
		f.title = label + " · " + subject
		f.status = page.FollowUpStatusLabels[status]
		if f.status == "" {
			f.status = status
		}
		f.date = f.date.In(loc)
		out = append(out, f)
	}
	return count, out, rows.Err()
}

// followUpsPanel is followups_panel.html.
func followUpsPanel(query string, reader cpoReader, count int, items []cpoFollowUp) []*screensv1.PageBlock {
	aside := feeddom.El("aside", "cpo-side",
		feeddom.El("header", "cpo-side-head",
			feeddom.El("h2", "cpo-side-name", "Open Follow-ups ", feeddom.El("span", "cpo-count", strconv.Itoa(count))),
			feeddom.El("button", "cpo-viewall", "View All").Attr("type", "button",
				"hx-get", cpoPath+"drawer?kind=followups&"+query, "hx-target", "#drawer-container", "hx-swap", "innerHTML")))
	if len(items) > 0 {
		ul := feeddom.El("ul", "cpo-fu")
		for _, f := range items {
			to := "To: " + f.to + " (PL)"
			if f.reminders > 0 {
				to += " · reminded " + strconv.Itoa(f.reminders) + "×"
			}
			// The template's line breaks between the parts are words' edges.
			ul.Add(feeddom.El("li", "cpo-fu-item", " ",
				feeddom.El("div", "cpo-fu-copy", " ",
					feeddom.El("button", "cpo-fu-title", f.title).Attr("type", "button",
						"hx-get", cpoPath+"drawer?kind=followups&focus="+f.id+"&"+query,
						"hx-target", "#drawer-container", "hx-swap", "innerHTML"), " ",
					feeddom.El("p", "cpo-fu-to", to), " "), " ",
				feeddom.El("span", "cpo-tag", f.status), " ",
				feeddom.El("time", "cpo-fu-date", f.date.Format("02 Jan 2006")), " "))
		}
		aside.Add(ul)
	} else {
		text := []any{"No follow-ups are open for this year."}
		if reader.followUp {
			text = append(text, " Use ", feeddom.El("strong", "", "Follow Up with PL"), " on a Programme Lead's row, or on a gap in any drawer.")
		}
		aside.Add(feeddom.El("p", "cpo-fu-empty", text...))
	}
	aside.Add(feeddom.El("p", "cpo-info", feeddom.El("span", "",
		"All values are for oversight only and are based on planned, assigned, and required records in Edify. They may differ from actual completed activities.")))
	return feeddom.Walk(feeddom.El("div", "", aside), nil)
}
