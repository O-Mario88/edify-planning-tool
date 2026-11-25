package planningmonitor

import (
	"context"
	"fmt"
	"sort"
	"strconv"
	"strings"
	"time"

	registry "github.com/O-Mario88/edify-planning-tool/platform/backend/internal/country"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// The timeliness table's CCEO and Partner views (table_owners.html,
// table_partners.html).

// selectedIDs is selected_ids: every id of the people the Lead and CCEO
// filters select, or nil when neither is set.
func (s *cexSnapshot) selectedIDs() []string {
	f := s.filters
	if f.programLead == "" && f.cceo == "" {
		return nil
	}
	type person struct {
		key string
		ids []string
	}
	people := []person{}
	for _, l := range s.roster.leads {
		if f.programLead != "" && l[0] != f.programLead {
			continue
		}
		people = append(people, person{l[0], s.roster.ids[l[0]]})
		for _, p := range s.roster.people[l[0]] {
			people = append(people, person{p[0], s.roster.ids[p[0]]})
		}
	}
	for key, o := range s.data.owners {
		if f.programLead == "" || o.leadKey == f.programLead {
			people = append(people, person{key, append([]string{key}, o.ids...)})
		}
	}
	out := []string{}
	for _, p := range people {
		if f.cceo == "" || p.key == f.cceo {
			out = append(out, p.key)
			out = append(out, p.ids...)
		}
	}
	return out
}

// unscheduledByPartner is _unscheduled_by_partner over unscheduled_handovers.
func (s *cexSnapshot) unscheduledByPartner(ctx context.Context, db schooldirectory.Querier) (map[string]int, error) {
	f := s.filters
	out := map[string]int{}
	if f.channel == "staff" {
		return out, nil
	}
	fy, _ := strconv.Atoi(s.data.window.fy)
	end := time.Date(fy, time.October, 1, 0, 0, 0, 0, cpoLocation)
	b := &sql{}
	where := `pa.status = ANY(` + b.arg(rules.CountryOversight.UnscheduledHandoverStatuses) + `) AND pa.created_at < ` + b.arg(end)
	if s.scope.Country != "" && s.scope.CountryScope {
		b.args = append(b.args, s.scope.CountryIDs())
		where += " AND " + registry.SchoolIn("s", fmt.Sprintf("$%d", len(b.args)))
	}
	if f.partner != "" {
		where += " AND pa.partner_id = " + b.arg(f.partner)
	}
	if f.region != "" {
		where += " AND s.region_id = " + b.arg(f.region)
	}
	if ids := s.selectedIDs(); ids != nil {
		arg := b.arg(ids)
		where += ` AND (pa.monitoring_staff_id = ANY(` + arg + `) OR (pa.monitoring_staff_id IS NULL AND pa.assigning_staff_id = ANY(` + arg +
			`)) OR (pa.monitoring_staff_id IS NULL AND pa.assigning_staff_id IS NULL AND s.account_owner_id = ANY(` + arg + `)))`
	}
	rows, err := db.Query(ctx, `SELECT COALESCE(pa.partner_id, ''), count(*) FROM partner_assignment pa
		LEFT JOIN school s ON s.id = pa.school_id WHERE `+where+` GROUP BY 1`, b.args...)
	if err != nil {
		return nil, fmt.Errorf("planningmonitor: the hand-overs not yet dated: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var key string
		var n int
		if err := rows.Scan(&key, &n); err != nil {
			return nil, err
		}
		out[key] = n
	}
	return out, rows.Err()
}

// cexPartnerRow is one of partner_rows.
type cexPartnerRow struct {
	key, name                                                                string
	assigned, due, started, executed, verified, awaiting, unpaid, paid, late int
}

func (s *cexSnapshot) partnerRows(ctx context.Context, db schooldirectory.Querier) ([]cexPartnerRow, error) {
	byPartner := map[string][]cexRecord{}
	for _, r := range s.records() {
		if r.channel == "partner" {
			byPartner[r.partnerKey] = append(byPartner[r.partnerKey], r)
		}
	}
	unscheduled, err := s.unscheduledByPartner(ctx, db)
	if err != nil {
		return nil, err
	}
	names := map[string]string{}
	for k, v := range s.data.partnerName {
		names[k] = v
	}
	unnamed := []string{}
	for k := range unscheduled {
		if _, ok := names[k]; k != "" && !ok {
			unnamed = append(unnamed, k)
		}
	}
	more, err := cpoNames(ctx, db, "partner", unnamed)
	if err != nil {
		return nil, err
	}
	for _, o := range more {
		names[o.value] = o.label
	}
	keys := []string{}
	for k := range byPartner {
		keys = append(keys, k)
	}
	for k := range unscheduled {
		if _, ok := byPartner[k]; !ok {
			keys = append(keys, k)
		}
	}
	sort.Strings(keys)
	sort.SliceStable(keys, func(i, j int) bool { return strings.ToLower(names[keys[i]]) < strings.ToLower(names[keys[j]]) })
	out := []cexPartnerRow{}
	for _, k := range keys {
		row := cexPartnerRow{key: k, name: "Partner not recorded"}
		if k != "" {
			row.name = names[k]
			if row.name == "" {
				row.name = "Unrecorded Partner"
			}
		}
		for _, r := range byPartner[k] {
			if r.cancelled {
				continue
			}
			row.due++
			inc := func(cond bool, n *int) {
				if cond {
					*n++
				}
			}
			inc(r.started, &row.started)
			inc(r.executed, &row.executed)
			inc(r.complete, &row.verified)
			inc(r.stage == "ia_review", &row.awaiting)
			inc(r.verified && !r.paid, &row.unpaid)
			inc(r.paid, &row.paid)
			inc(r.overdue != "", &row.late)
		}
		row.assigned = row.due + unscheduled[k]
		out = append(out, row)
	}
	return out, nil
}

// ownerTableNodes is table_owners.html.
func (s *cexSnapshot) ownerTableNodes(reader cpoReader, reminders map[[2]string]int) *node {
	q := s.filters.query()
	heads := []string{"Planned", "In-Progress", "Completed & PL Verified", "On-Time %", "Overdue", "Carried Forward", "Returned",
		"Remaining Slots", "Forecast", "Open Reminders"}
	body := el("tbody", "")
	rows := 0
	noLead := rules.CountryOversight.NoLead[0]
	for _, l := range s.tree.leads {
		for _, o := range l.owners {
			if rows == cpoRowsPerPage {
				break
			}
			rows++
			c := s.cells(o.tally, s.remainingOf("owner", o.key), reminders[[2]string{"owner", o.key}], l.key != noLead)
			hint := l.name
			if o.kind == "pl_personal" {
				hint = o.name + " · personal delivery"
			}
			act := el("button", "cpo-view", "View").Attr("type", "button", "hx-get", cexBase+"/drawer?kind=activities&owner="+o.key+"&stage=due&"+q,
				"hx-target", "#drawer-container", "hx-swap", "innerHTML")
			if reader.followUp && l.key != noLead {
				cceo := o.key
				if o.kind == "pl_personal" {
					cceo = ""
				}
				act = el("button", "cpo-ask", "Follow Up").Attr("type", "button", "hx-get", cexBase+"/follow-up?lead="+l.key+"&cceo="+cceo+"&"+q,
					"hx-target", "#drawer-container", "hx-swap", "innerHTML")
			}
			th := el("th", "cpo-namecell", el("span", "", o.label()), el("span", "cpo-hint", el("span", "", hint)))
			body.Add(el("tr", "", append(append([]any{th}, cellNodes(c, reader)...), el("td", "cpo-actcell", el("div", "cpo-acts", act)))...))
		}
	}
	if rows == 0 {
		body.Add(el("tr", "", el("td", "cpo-empty", "No officer has work due in this selection.")))
	}
	return el("div", "cpo-tscroll", el("table", "cpo-table", headRow("CCEO", heads, "Action"), body))
}

// partnerTableNodes is table_partners.html.
func (s *cexSnapshot) partnerTableNodes(rows []cexPartnerRow) *node {
	q := s.filters.query()
	body := el("tbody", "")
	alert := func(n int) *node {
		if n == 0 {
			return el("td", "", "0")
		}
		return el("td", "", el("span", "cpo-alert", strconv.Itoa(n)))
	}
	for _, r := range rows[:min(len(rows), cpoRowsPerPage)] {
		pay := el("td", "cpo-cover", el("span", "", strconv.Itoa(r.paid)+" paid"))
		if r.unpaid > 0 {
			pay.Add(" ", el("span", "cpo-pct", "("+strconv.Itoa(r.unpaid)+" due)"))
		}
		body.Add(el("tr", "", el("th", "cpo-namecell", el("span", "", r.name)), el("td", "", strconv.Itoa(r.assigned)),
			el("td", "", strconv.Itoa(r.due)), el("td", "", strconv.Itoa(r.started)), el("td", "", strconv.Itoa(r.executed)),
			el("td", "", strconv.Itoa(r.verified)), alert(r.awaiting), pay, alert(r.late),
			el("td", "cpo-actcell", el("div", "cpo-acts", el("button", "cpo-view", "View").Attr("type", "button",
				"hx-get", cexBase+"/drawer?kind=activities&partner_key="+r.key+"&stage=due&"+q, "hx-target", "#drawer-container", "hx-swap", "innerHTML")))))
	}
	if len(rows) == 0 {
		body.Add(el("tr", "", el("td", "cpo-empty", "No Partner has work in this selection.")))
	}
	heads := []string{"Assigned", "Scheduled", "Started", "Evidence Submitted", "Verified", "Awaiting Verification", "Payment", "Overdue"}
	return el("div", "cpo-tscroll", el("table", "cpo-table", headRow("Partner", heads, "Action"), body))
}
