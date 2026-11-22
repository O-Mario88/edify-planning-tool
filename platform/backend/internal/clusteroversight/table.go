package clusteroversight

import (
	"fmt"
	"strconv"
	"strings"
)

// columnCount is the Command Center's columns (workspace.COMMAND_COLUMNS).
const columnCount = 19

// cell is one cell of a section's table (workspace.cell, cluster_cell,
// school_cell): its text, its tone, and where it links.
type cell struct {
	text, tone string
	// cluster is set on a cell that opens the cluster, at query's tab.
	cluster, query string
	// school is set on a cell that opens a school profile (/schools/<id>).
	school string
	// href is set on a cell with a direct relative link (e.g. CSV download).
	href string
}

// plain is workspace.cell: a dash for nothing.
func plain(text string) cell {
	if text == "" {
		return cell{text: rules.Dash}
	}
	return cell{text: text}
}

func plainTone(text, tone string) cell {
	c := plain(text)
	c.tone = tone
	return c
}

// link is workspace.cluster_cell: a figure that opens the cluster profile
// at the tab that explains it; a dash opens nothing.
func link(text, clusterID, query, tone string) cell {
	c := plain(text)
	c.tone = tone
	if c.text != rules.Dash {
		c.cluster, c.query = clusterID, query
	}
	return c
}

// schoolLink is workspace.school_cell: opens the school profile.
func schoolLink(name, schoolID string) cell {
	c := plain(name)
	if c.text != rules.Dash {
		c.school = schoolID
	}
	return c
}

func hrefCell(text, href, tone string) cell {
	c := plain(text)
	c.tone = tone
	if c.text != rules.Dash {
		c.href = href
	}
	return c
}

// toneOf is workspace.tone_of: green for a rise, red for a fall, neutral
// for no movement, and none for a figure that is not there.
func toneOf(value *float64) string {
	switch {
	case value == nil:
		return ""
	case *value == 0:
		return "neutral"
	case *value > 0:
		return "success"
	}
	return "danger"
}

// signedOrNone is workspace.signed of a figure that may not be there.
func signedOrNone(value *float64, suffix string) string {
	if value == nil {
		return ""
	}
	return signed(*value, 1, suffix)
}

func deref(s *string) string {
	if s == nil {
		return ""
	}
	return *s
}

func trim(s string) string { return strings.TrimSpace(s) }

// table is a section's table, described (workspace.Table).
type table struct {
	title, summary, note, empty string
	columns                     []Column
	rows                        [][]cell
}

// workspace is the reader's clusters and everything read about them
// (workspace.Workspace).
type workspace struct {
	fy         string
	clusters   []clusterRow
	owners     map[string]string
	facts      map[string]facts
	cards      map[string]scorecard
	now        map[string]ssaNow
	last       map[string]string
	settings   settings
	settingRow *settingRow
	// mine are the clusters filed under the reader's own ids.
	mine map[string]bool
}

// load is workspace.load, from the records: each cluster's facts and
// scorecard. today is the local day, which decides what was due by now.
func load(r *records, fy, today string, readerIDs []string) workspace {
	s := settingsOf(r.Setting)
	ws := workspace{
		fy: fy, clusters: r.Clusters, owners: r.Owners, last: r.LastDelivered,
		settings: s, settingRow: r.Setting,
		facts: map[string]facts{}, cards: map[string]scorecard{}, now: map[string]ssaNow{}, mine: map[string]bool{},
	}
	members := map[string][]string{}
	memberRows := map[string][]memberRow{}
	clusterOf, country := map[string]string{}, map[string]string{}
	known := map[string]bool{}
	for _, c := range r.Clusters {
		known[c.ID] = true
		if c.OwnerID != nil && in(readerIDs, *c.OwnerID) {
			ws.mine[c.ID] = true
		}
	}
	for _, m := range r.Members {
		members[m.ClusterID] = append(members[m.ClusterID], m.ID)
		memberRows[m.ClusterID] = append(memberRows[m.ClusterID], m)
		clusterOf[m.ID], country[m.ID] = m.ClusterID, m.Country
	}
	sessions := map[string][]sessionRow{}
	for _, s := range r.Sessions {
		sessions[s.ClusterID] = append(sessions[s.ClusterID], s)
	}
	register := map[string]map[string]registerRow{}
	for _, row := range r.Register {
		if register[row.ActivityID] == nil {
			register[row.ActivityID] = map[string]registerRow{}
		}
		register[row.ActivityID][row.SchoolID] = row
	}
	classified := classify(r, country)
	yearly := map[string]map[string]int{}
	for _, row := range r.Enrolment {
		if yearly[row.SchoolID] == nil {
			yearly[row.SchoolID] = map[string]int{}
		}
		yearly[row.SchoolID][row.FY] = row.Enrollment
	}
	learned := schoolScores(r.Learning)
	funded := map[string]int{}
	for _, school := range r.Funded {
		if cluster, ok := clusterOf[school]; ok {
			funded[cluster]++
		}
	}
	loansByCluster := map[string]*loanSummary{}
	for _, l := range r.Loans {
		cluster, ok := clusterOf[l.SchoolID]
		if !ok {
			continue
		}
		ls := loansByCluster[cluster]
		if ls == nil {
			ls = &loanSummary{bySchool: map[string]int{}}
			loansByCluster[cluster] = ls
		}
		ls.loanCount++
		ls.bySchool[l.SchoolID]++
		if in(rules.FundedLoanStatuses, l.Status) {
			ls.disbursed += l.DisbursedAmount
		}
	}
	told := map[string]stories{}
	for _, story := range r.Stories {
		cluster := story.ClusterID
		if !known[cluster] {
			var ok bool
			if cluster, ok = clusterOf[story.SchoolID]; !ok || !known[cluster] {
				continue
			}
		}
		st := told[cluster]
		st.count++
		switch story.Status {
		case rules.StoryApprovedStatus:
			st.approved++
		case "submitted", "returned":
			st.waiting++
		}
		if story.HasEvidence {
			st.withEvidence++
		} else if story.Status != "rejected" {
			st.withoutEvidence++
		}
		if story.Date != "" && story.Date > st.latestDate {
			st.latestDate = story.Date
		}
		told[cluster] = st
	}
	plans := map[string]*plan{}
	for _, row := range r.Plan {
		if plans[row.ClusterID] == nil {
			plans[row.ClusterID] = &plan{}
		}
		plans[row.ClusterID].add(row, today)
	}
	scored := currentScores(r.YearRecords, r.YearScores)
	for _, c := range r.Clusters {
		ls := loanSummary{bySchool: map[string]int{}}
		if found := loansByCluster[c.ID]; found != nil {
			ls = *found
		}
		f := facts{
			members:    members[c.ID],
			memberRows: memberRows[c.ID],
			attendance: attendanceOf(memberRows[c.ID], sessions[c.ID], register, fy),
			movement:   movementOf(members[c.ID], classified),
			enrolment:  enrolmentOf(memberRows[c.ID], yearly, fy),
			learning:   learningOf(members[c.ID], learned, fy),
			stories:    told[c.ID],
			loans:      ls,
			funded:     funded[c.ID],
		}
		if p := plans[c.ID]; p != nil {
			f.plan = *p
		}
		ws.facts[c.ID] = f
		ws.cards[c.ID] = scorecardOf(f, fy, s)
		ws.now[c.ID] = ssaNowOf(members[c.ID], scored)
	}
	return ws
}

// ownerOf is Workspace.owner_of: who holds the cluster, as the page names
// them.
func (ws workspace) ownerOf(c clusterRow) string {
	if label, ok := ws.owners[trim(deref(c.OwnerID))]; ok {
		return label
	}
	return "Unassigned"
}

// scoreCell is workspace._score_cell: a score with its band, opening its
// parts; a dash where there are too few parts to score.
func scoreCell(c composite, clusterID, fy string) cell {
	score := c.score()
	if score == nil {
		return plain("")
	}
	label, tone := band(score)
	return link(fmt.Sprintf("%d · %s", *score, label), clusterID, "?tab=scores&fy="+fy+"&part="+c.key, tone)
}

// command is workspace.command: the Command Center, every cluster on one
// line. mayReadLoans is whether the count of schools holding a loan opens
// the loans tab.
func (ws workspace) command(mayReadLoans bool) table {
	return ws.commandFor(ws.clusters, rules.Command.Title, rules.Command.Empty, mayReadLoans)
}

func (ws workspace) commandFor(clusters []clusterRow, title, empty string, mayReadLoans bool) table {
	t := table{title: title, columns: rules.Command.Columns, note: rules.Command.Note, empty: empty}
	invited, attended, absent, schools := 0, 0, 0, 0
	for _, c := range clusters {
		f, card, now := ws.facts[c.ID], ws.cards[c.ID], ws.now[c.ID]
		att, moved := f.attendance, f.movement[overall]
		invited += att.invitedTotal
		attended += att.attendedTotal
		absent += att.drifting
		schools += len(f.members)
		attendanceTab := "?tab=attendance&fy=" + ws.fy
		ssaTab := "?tab=ssa&fy=" + ws.fy

		rate := ""
		if att.rate != nil {
			rate = strconv.Itoa(*att.rate) + "%"
		}
		drifting := plain("0")
		if att.drifting > 0 {
			drifting = link(strconv.Itoa(att.drifting), c.ID, attendanceTab+"&show=missing", "danger")
		}
		average, weakest := "", ""
		if now.average != nil {
			average = floatStr(*now.average)
		}
		if now.weakest != "" {
			weakest = interventionLabel(now.weakest) + " (" + fixed(now.weakestMean, 1) + ")"
		}
		loans := plain(strconv.Itoa(f.funded))
		if mayReadLoans && f.funded > 0 {
			loans = link(strconv.Itoa(f.funded), c.ID, "?tab=loans", "")
		}
		approved := plain("0")
		if f.stories.count > 0 {
			approved = link(strconv.Itoa(f.stories.approved), c.ID, "?tab=stories", "")
		}
		t.rows = append(t.rows, []cell{
			link(c.Name, c.ID, "", ""),
			plain(c.District),
			plain(ws.ownerOf(c)),
			plain(deref(c.LeaderName)),
			plain(deref(c.LeaderPhone)),
			plain(strconv.Itoa(len(f.members))),
			link(rate, c.ID, attendanceTab, ""),
			drifting,
			link(ws.last[c.ID], c.ID, attendanceTab, ""),
			link(average, c.ID, ssaTab, ""),
			link(weakest, c.ID, ssaTab+"&area="+now.weakest, ""),
			link(signedOrNone(moved.change(), ""), c.ID, ssaTab, toneOf(moved.change())),
			link(signedOrNone(f.enrolment.growthPct(), "%"), c.ID, "?tab=students&fy="+ws.fy, toneOf(f.enrolment.growthPct())),
			link(signedOrNone(f.learning.change(), ""), c.ID, "?tab=learning&fy="+ws.fy, toneOf(f.learning.change())),
			loans,
			approved,
			scoreCell(card.health, c.ID, ws.fy),
			scoreCell(card.impact, c.ID, ws.fy),
			link(fmt.Sprintf("%d · %s", card.maturity, maturityLabel(card.maturity)), c.ID, "?tab=scores&fy="+ws.fy+"&part=maturity", ""),
		})
	}
	overallRate := "no"
	if invited > 0 {
		overallRate = strconv.Itoa(pyRoundInt(float64(100*attended)/float64(invited))) + "%"
	}
	t.summary = fmt.Sprintf("%s · %s schools · %s attendance · %d schools absent %d+ sessions",
		plural(len(clusters), "cluster"), commas(schools), overallRate, absent, rules.MissedInARowAlert)
	return t
}
