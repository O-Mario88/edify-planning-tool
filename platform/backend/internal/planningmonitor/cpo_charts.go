package planningmonitor

import (
	"strconv"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
)

// cpoChart is one of service.charts as _charts.html leaves it to the feed:
// the title, the "Chart data" summary and the open table of each Lead's
// figures (the canvas itself is drawn in the browser from the same rows).
type cpoChart struct {
	title   string
	columns []string
	cells   func(t cpoTally) []string
}

func ints(values ...int) []string {
	out := make([]string, len(values))
	for i, v := range values {
		out[i] = strconv.Itoa(v)
	}
	return out
}

var cpoCharts = []cpoChart{
	{"Visits Planned Against Target by Program Lead",
		[]string{"Visit target", "Visits planned", "Follow up", "In-school Training", "SSA Support", "Still to plan",
			"Past the ceiling", "Core visits of target", "Client visits of target", "Partner target",
			"Assigned to Partners", "Partner planned", "Donor, story, social (not counted)"},
		func(t cpoTally) []string {
			out := ints(t.n("target"), t.n("p_visits"), t.n("p_follow_up"), t.n("p_in_school"), t.n("p_ssa"),
				t.planRemaining(), t.n("over_cap"))
			out = append(out, cpoFmt(t.n("p_core_visits"))+" / "+cpoFmt(t.n("core_staff_slots")),
				cpoFmt(t.n("p_client_visits"))+" / "+cpoFmt(t.n("client_staff_expected")))
			return append(out, ints(t.n("partner_expected"), t.n("pa_work"), t.n("pp_work"), t.n("p_outreach"))...)
		}},
	{"Schools With a Visit Planned by Program Lead",
		[]string{"Schools needing a visit", "Staff plan only", "Partner plan only", "Both", "Awaiting a Partner's date",
			"Not yet planned", "In a Partner's hands", "Planned twice"},
		func(t cpoTally) []string {
			return ints(t.n("visit_schools"), t.n("staff_only"), t.n("partner_only"), t.n("both"), t.partnerToPlan(),
				t.n("unplanned"), t.n("with_partner"), t.n("duplicates"))
		}},
	{"Training Planning by Program Lead",
		[]string{"Required slots", "Planned slots", "Remaining slots", "Staff target", "Planned by staff",
			"Partner target", "Assigned to Partners", "Planned by Partners", "Schools with training", "Schools with none"},
		func(t cpoTally) []string {
			return ints(t.n("training_slots"), t.n("training"), t.n("training_gap"), t.n("training_staff_slots"),
				t.n("training_staff"), t.n("training_partner_slots"), t.n("training_partner_assigned"),
				t.n("training_partner"), t.n("any_training"), t.n("no_training"))
		}},
	{"Cluster & Cluster-Meeting Coverage",
		[]string{"Eligible schools", "Clustered", "Unclustered", "Covered by a planned meeting",
			"Clustered, no meeting planned", "Meetings planned by staff"},
		func(t cpoTally) []string {
			return ints(t.n("schools"), t.n("clustered"), t.n("unclustered"), t.n("meeting_covered"),
				t.n("clustered_no_meeting"), t.n("p_meetings"))
		}},
}

// chartLeads is service.charts' categories: every Lead row but an empty
// "no Programme Lead" one.
func chartLeads(snap *cpoSnapshot) []*cpoLeadRow {
	out := []*cpoLeadRow{}
	for _, lead := range snap.tree.leads {
		t := cpoTally(lead.tally)
		if t.n("schools") > 0 || t.n("p_visits") > 0 || !lead.noLead {
			out = append(out, lead)
		}
	}
	return out
}

func cpoChartBlocks(snap *cpoSnapshot) []*screensv1.PageBlock {
	leads := chartLeads(snap)
	out := []*screensv1.PageBlock{}
	for _, chart := range cpoCharts {
		cols := []*screensv1.PageColumn{{Label: "Programme Lead"}}
		for _, c := range chart.columns {
			cols = append(cols, &screensv1.PageColumn{Label: c})
		}
		table := &screensv1.PageTable{Columns: cols}
		for _, lead := range leads {
			cells := []*screensv1.PageCell{plain(lead.name)}
			for _, v := range chart.cells(cpoTally(lead.tally)) {
				cells = append(cells, plain(v))
			}
			table.Rows = append(table.Rows, &screensv1.PageRow{Cells: cells})
		}
		out = append(out, &screensv1.PageBlock{Kind: &screensv1.PageBlock_Section{Section: chart.title}},
			textPanel("Chart data"), &screensv1.PageBlock{Kind: &screensv1.PageBlock_Table{Table: table}})
	}
	return out
}
