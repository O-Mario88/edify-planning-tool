package clusteroversight

import (
	"bytes"
	"context"
	"encoding/csv"
	"fmt"
	"math"
	"net/http"
	"net/url"
	"sort"
	"strconv"
	"strings"
	"time"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

var leadColumns = []Column{
	{Label: "Cluster"},
	{Label: "District"},
	{Label: "CCEO"},
}

var notCollected = map[string][]string{
	"teacher": {
		"Share of a school's teachers trained (schools do not record how many teachers they have)",
		"Classroom practice adoption",
		"Lesson quality",
		"Teacher retention",
		"Teacher confidence",
	},
	"leader": {
		"Financial management and planning adoption",
		"School governance and staff management",
	},
}

var maturityLabels = map[string]string{
	"min_dimensions":       "Fewest parts a score needs",
	"active_sessions":      "Active: sessions held in the year",
	"active_participation": "Active: schools represented (%)",
	"healthy_health":       "Healthy: Cluster Health at least",
	"healthy_ssa_improved": "Healthy: schools whose SSA improved (%)",
	"high_impact":          "High Impact: Cluster Impact at least",
	"model_health":         "Model Cluster: Cluster Health at least",
	"model_impact":         "Model Cluster: Cluster Impact at least",
	"model_stories":        "Model Cluster: approved change stories",
}

var maturityRuleOrder = []string{
	"min_dimensions",
	"active_sessions",
	"active_participation",
	"healthy_health",
	"healthy_ssa_improved",
	"high_impact",
	"model_health",
	"model_impact",
	"model_stories",
}

var scoreOrder = []string{"health", "impact", "teacher", "leader"}

func ruleSentence() string {
	return fmt.Sprintf(
		"Improved and declined follow the published IA measurement rule for each SSA domain "+
			"(the school's country first, then the deployment rule); where no threshold is approved "+
			"any movement counts, and readings less than %d days apart are not compared.",
		rules.Change.MinIntervalDays,
	)
}

func formatDay(iso string) string {
	if iso == "" {
		return ""
	}
	t, err := time.Parse(time.DateOnly, iso)
	if err != nil {
		return iso
	}
	return t.Format("2 Jan 2006")
}

func pctFloat(v *float64) string {
	if v == nil {
		return ""
	}
	return strconv.Itoa(pyRoundInt(*v)) + "%"
}

func pctInt(v *int) string {
	if v == nil {
		return ""
	}
	return strconv.Itoa(*v) + "%"
}

func leadCells(ws workspace, c clusterRow, query string) []cell {
	return []cell{
		link(c.Name, c.ID, query, ""),
		plain(c.District),
		plain(ws.ownerOf(c)),
	}
}

func intPtrTone(v *int) string {
	if v == nil {
		return ""
	}
	f := float64(*v)
	return toneOf(&f)
}

func signedInt(v *int) string {
	if v == nil {
		return ""
	}
	if *v > 0 {
		return "+" + commas(*v)
	}
	return commas(*v)
}

// isBuiltInSection reports whether key is one of the 17 in-workspace sections
// built by Go (all sections in rules.Sections except external doors like directory).
func isBuiltInSection(key string) bool {
	switch key {
	case "command", "my", "meetings", "training", "attendance", "schools",
		"ssa", "teachers", "leaders", "students", "academic", "loans",
		"stories", "impact", "planning", "evidence", "reports":
		return true
	default:
		return false
	}
}

func sectionMeta(key string) (Section, bool) {
	for _, s := range rules.Sections {
		if s.Key == key {
			return s, true
		}
	}
	return Section{}, false
}

func (ws workspace) buildSection(key string, d Doors, area, view string) table {
	switch key {
	case "command":
		return ws.command(d.Loans)
	case "my":
		return ws.my(d.Loans)
	case "meetings":
		return ws.sessionsTable(false)
	case "training":
		return ws.sessionsTable(true)
	case "attendance":
		return ws.attendanceTable()
	case "schools":
		return ws.schoolsTable(d.Loans)
	case "ssa":
		return ws.ssaTable(area)
	case "teachers":
		return ws.indexTable("teacher", "Teachers Reached", func(a attendance) int { return a.teachers })
	case "leaders":
		return ws.indexTable("leader", "School Leaders Reached", func(a attendance) int { return a.leaders })
	case "students":
		return ws.studentsTable()
	case "academic":
		return ws.academicTable()
	case "loans":
		return ws.loansTable(d.Loans)
	case "stories":
		return ws.storiesTable()
	case "impact":
		if view == "courses" {
			return ws.coursesTable()
		}
		return ws.impactTable()
	case "planning":
		return ws.planningTable()
	case "evidence":
		return ws.evidenceTable()
	case "reports":
		return ws.reportsTable(d.Export)
	default:
		return table{title: "Cluster Oversight", empty: "Section not found."}
	}
}

func (ws workspace) my(mayReadLoans bool) table {
	mine := make([]clusterRow, 0, len(ws.mine))
	for _, c := range ws.clusters {
		if ws.mine[c.ID] {
			mine = append(mine, c)
		}
	}
	return ws.commandFor(mine, "My Clusters", "You are not the responsible officer for any cluster.", mayReadLoans)
}

func (ws workspace) sessionsTable(trainings bool) table {
	type entry struct {
		heldOn string
		cells  []cell
	}
	entries := []entry{}
	without := 0
	for _, c := range ws.clusters {
		att := ws.facts[c.ID].attendance
		without += att.withoutRegister
		for _, s := range att.sessions {
			if s.isTraining != trainings {
				continue
			}
			areaText := ""
			if s.area != "" {
				areaText = interventionLabel(s.area)
			}
			entries = append(entries, entry{
				heldOn: s.heldOn,
				cells: []cell{
					plain(formatDay(s.heldOn)),
					link(c.Name, c.ID, "?tab=attendance&fy="+ws.fy+"&show=sessions", ""),
					plain(s.name),
					plain(areaText),
					plain(strconv.Itoa(len(s.invited))),
					plain(strconv.Itoa(len(s.attended))),
					plain(pctInt(s.rate())),
					plain(strconv.Itoa(s.teachers)),
					plain(strconv.Itoa(s.leaders)),
				},
			})
		}
	}
	sort.SliceStable(entries, func(i, j int) bool { return entries[i].heldOn > entries[j].heldOn })
	rows := make([][]cell, len(entries))
	for i, e := range entries {
		rows[i] = e.cells
	}
	word := "Cluster Meetings"
	kindCol := "Meeting"
	if trainings {
		word = "Group Trainings"
		kindCol = "Training"
	}
	note := ""
	if without > 0 {
		note = fmt.Sprintf("%s across these clusters have no register (nobody was ticked as attending) and are not listed.",
			plural(without, "delivered session"))
	}
	return table{
		title:   fmt.Sprintf("%s Held, FY %s", word, ws.fy),
		summary: fmt.Sprintf("%d with a register", len(rows)),
		columns: []Column{
			{Label: "Date"},
			{Label: "Cluster"},
			{Label: kindCol},
			{Label: "SSA Area"},
			{Label: "Schools Invited", Numeric: true},
			{Label: "Schools Attended", Numeric: true},
			{Label: "Attendance", Numeric: true},
			{Label: "Teachers", Numeric: true},
			{Label: "School Leaders", Numeric: true},
		},
		rows:  rows,
		note:  note,
		empty: fmt.Sprintf("No %s with a register in this year.", strings.ToLower(word)),
	}
}

func (ws workspace) attendanceTable() table {
	type entry struct {
		missed      int
		clusterName string
		schoolName  string
		cells       []cell
	}
	entries := []entry{}
	clustersHit := 0
	for _, c := range ws.clusters {
		drifting := ws.facts[c.ID].attendance.driftingRows
		if len(drifting) > 0 {
			clustersHit++
		}
		for _, s := range drifting {
			lastText := "Never"
			if s.lastAttended != "" {
				lastText = formatDay(s.lastAttended)
			}
			entries = append(entries, entry{
				missed:      s.missedInARow,
				clusterName: c.Name,
				schoolName:  s.name,
				cells: []cell{
					link(c.Name, c.ID, "?tab=attendance&fy="+ws.fy+"&show=missing", ""),
					plain(ws.ownerOf(c)),
					plain(s.code),
					schoolLink(s.name, s.id),
					plain(strconv.Itoa(s.invited)),
					plain(strconv.Itoa(s.attended)),
					plain(pctInt(s.rate())),
					plain(lastText),
					plainTone(strconv.Itoa(s.missedInARow), "danger"),
				},
			})
		}
	}
	sort.SliceStable(entries, func(i, j int) bool {
		if entries[i].missed != entries[j].missed {
			return entries[i].missed > entries[j].missed
		}
		if entries[i].clusterName != entries[j].clusterName {
			return entries[i].clusterName < entries[j].clusterName
		}
		return entries[i].schoolName < entries[j].schoolName
	})
	rows := make([][]cell, len(entries))
	for i, e := range entries {
		rows[i] = e.cells
	}
	return table{
		title:   fmt.Sprintf("Schools Absent %d or More Sessions in a Row", rules.MissedInARowAlert),
		summary: fmt.Sprintf("%s in %s", plural(len(rows), "school"), plural(clustersHit, "cluster")),
		columns: []Column{
			{Label: "Cluster"},
			{Label: "CCEO"},
			{Label: "School ID"},
			{Label: "School Name"},
			{Label: "Invited", Numeric: true},
			{Label: "Attended", Numeric: true},
			{Label: "Attendance", Numeric: true},
			{Label: "Last Attended"},
			{Label: "Consecutive Misses", Numeric: true},
		},
		rows:  rows,
		note:  "Invited and Attended count this year's sessions; Consecutive Misses counts back from the school's latest invitation, across years. The officer who holds the cluster has a To-Do for these schools.",
		empty: "No school has missed that many sessions in a row.",
	}
}

func (ws workspace) schoolsTable(mayReadLoans bool) table {
	rows := [][]cell{}
	for _, c := range ws.clusters {
		f := ws.facts[c.ID]
		attBySchool := map[string]schoolAttendance{}
		for _, a := range f.attendance.schools {
			attBySchool[a.id] = a
		}
		ssaBySchool := f.movement[overall].schools
		for _, m := range f.memberRows {
			a, hasAtt := attBySchool[m.ID]
			sr := ssaBySchool[m.ID]
			er := f.enrolment.rows[m.ID]
			lrChange := f.learning.changes[m.ID]

			attRate := ""
			missedText := ""
			missedTone := ""
			if hasAtt {
				attRate = pctInt(a.rate())
				missedText = strconv.Itoa(a.missedInARow)
				if a.isDrifting() {
					missedTone = "danger"
				}
			}
			latestEnrol := ""
			if er.latest != nil {
				latestEnrol = commas(*er.latest)
			}
			cells := []cell{
				link(c.Name, c.ID, "", ""),
				plain(m.Code),
				schoolLink(m.Name, m.ID),
				plainTone(signedOrNone(sr.change, ""), sr.tone),
				plain(sr.verdictLabel),
				plain(attRate),
				plainTone(missedText, missedTone),
				plain(latestEnrol),
				plainTone(signedOrNone(er.growthPct, "%"), toneOf(er.growthPct)),
				plainTone(signedOrNone(lrChange, ""), toneOf(lrChange)),
			}
			if mayReadLoans {
				cells = append(cells, plain(strconv.Itoa(f.loans.bySchool[m.ID])))
			}
			rows = append(rows, cells)
		}
	}
	cols := []Column{
		{Label: "Cluster"},
		{Label: "School ID"},
		{Label: "School Name"},
		{Label: "SSA Change", Numeric: true},
		{Label: "SSA Verdict"},
		{Label: "Attendance", Numeric: true},
		{Label: "Consecutive Misses", Numeric: true},
		{Label: "Latest Enrolment", Numeric: true},
		{Label: "Enrolment Growth", Numeric: true},
		{Label: "Learning Change", Numeric: true},
	}
	if mayReadLoans {
		cols = append(cols, Column{Label: "Loans", Numeric: true})
	}
	summaryWord := "schools"
	if len(rows) == 1 {
		summaryWord = "school"
	}
	return table{
		title:   "Schools in Their Clusters",
		summary: fmt.Sprintf("%s %s", commas(len(rows)), summaryWord),
		columns: cols,
		rows:    rows,
		empty:   "No school is in a cluster in your scope.",
	}
}

func (ws workspace) ssaTable(area string) table {
	before := previousFY(ws.fy)
	key := overall
	areaLabel := "All SSA Areas"
	for _, iv := range rules.SSAInterventions {
		if iv[0] == area {
			key = iv[0]
			areaLabel = iv[1]
			break
		}
	}
	rows := [][]cell{}
	comparedTotal, improvedTotal, declinedTotal := 0, 0, 0
	for _, c := range ws.clusters {
		f := ws.facts[c.ID]
		a := f.movement[key]
		base := "?tab=ssa&fy=" + ws.fy + "&area=" + key + "&verdict="
		comparedTotal += a.compared
		improvedTotal += a.improved
		declinedTotal += a.declined
		beforeText, afterText := "", ""
		if a.before != nil {
			beforeText = fixed(*a.before, 1)
		}
		if a.after != nil {
			afterText = fixed(*a.after, 1)
		}
		improvedCell := plain("0")
		if a.improved > 0 {
			improvedCell = link(strconv.Itoa(a.improved), c.ID, base+"improved", "")
		}
		heldCell := plain("0")
		if a.held() > 0 {
			heldCell = link(strconv.Itoa(a.held()), c.ID, base+"no_change", "")
		}
		declinedCell := plain("0")
		if a.declined > 0 {
			declinedCell = link(strconv.Itoa(a.declined), c.ID, base+"declined", "danger")
		}
		notCompCell := plain("0")
		if a.notCompared > 0 {
			notCompCell = link(strconv.Itoa(a.notCompared), c.ID, base+"not_compared", "")
		}
		row := append(leadCells(ws, c, "?tab=ssa&fy="+ws.fy),
			plain(strconv.Itoa(len(f.members))),
			plain(strconv.Itoa(a.compared)),
			plain(beforeText),
			plain(afterText),
			plainTone(signedOrNone(a.change(), ""), toneOf(a.change())),
			improvedCell,
			heldCell,
			declinedCell,
			notCompCell,
		)
		rows = append(rows, row)
	}
	cols := append([]Column{}, leadColumns...)
	cols = append(cols,
		Column{Label: "Schools", Numeric: true},
		Column{Label: "Schools Compared", Numeric: true},
		Column{Label: "FY " + before, Numeric: true},
		Column{Label: "FY " + ws.fy, Numeric: true},
		Column{Label: "Change", Numeric: true},
		Column{Label: "Improved", Numeric: true},
		Column{Label: "No Change", Numeric: true},
		Column{Label: "Declined", Numeric: true},
		Column{Label: "Not Compared", Numeric: true},
	)
	note := ""
	if len(ws.clusters) > 0 {
		note = ruleSentence()
	}
	return table{
		title:   fmt.Sprintf("SSA Performance: %s, FY %s to FY %s", areaLabel, before, ws.fy),
		summary: fmt.Sprintf("%s schools compared · %s improved · %s declined", commas(comparedTotal), commas(improvedTotal), commas(declinedTotal)),
		columns: cols,
		rows:    rows,
		note:    note,
		empty:   "No cluster is in your scope.",
	}
}

func (ws workspace) indexTable(key, reachedLabel string, reachedOf func(attendance) int) table {
	scoreRule := rules.Scores[key]
	type entry struct {
		sortScore int
		cells     []cell
	}
	entries := make([]entry, 0, len(ws.clusters))
	for _, c := range ws.clusters {
		card := ws.cards[c.ID]
		comp := card.teacher
		if key == "leader" {
			comp = card.leader
		}
		sc := comp.score()
		sortVal := -1
		if sc != nil {
			sortVal = *sc
		}
		cells := append(leadCells(ws, c, "?tab=scores&fy="+ws.fy+"&part="+key),
			plain(commas(reachedOf(ws.facts[c.ID].attendance))),
		)
		for _, p := range comp.parts {
			cells = append(cells, plain(pctFloat(p.score)))
		}
		cells = append(cells, scoreCell(comp, c.ID, ws.fy))
		entries = append(entries, entry{sortScore: sortVal, cells: cells})
	}
	sort.SliceStable(entries, func(i, j int) bool { return entries[i].sortScore > entries[j].sortScore })
	rows := make([][]cell, len(entries))
	for i, e := range entries {
		rows[i] = e.cells
	}
	cols := append([]Column{}, leadColumns...)
	cols = append(cols, Column{Label: reachedLabel, Numeric: true})
	for _, d := range scoreRule.Dimensions {
		cols = append(cols, Column{Label: d.Label, Numeric: true})
	}
	cols = append(cols, Column{Label: scoreRule.Title})
	return table{
		title:   fmt.Sprintf("%s by Cluster, FY %s", scoreRule.Title, ws.fy),
		summary: plural(len(rows), "cluster"),
		columns: cols,
		rows:    rows,
		note:    "Not collected on the platform yet, so not in this index: " + strings.Join(notCollected[key], "; ") + ".",
		empty:   "No cluster is in your scope.",
	}
}

func (ws workspace) studentsTable() table {
	previous := previousFY(ws.fy)
	rows := [][]cell{}
	beforeTotal, afterTotal, comparedTotal := 0, 0, 0
	for _, c := range ws.clusters {
		e := ws.facts[c.ID].enrolment
		comparedTotal += e.compared
		beforeTotal += e.before
		afterTotal += e.after
		beforeText, afterText := "", ""
		if e.compared > 0 {
			beforeText = commas(e.before)
			afterText = commas(e.after)
		}
		chg := e.change()
		growth := e.growthPct()
		row := append(leadCells(ws, c, "?tab=students&fy="+ws.fy),
			plain(strconv.Itoa(e.schoolCount)),
			plain(strconv.Itoa(e.compared)),
			plain(beforeText),
			plain(afterText),
			plainTone(signedInt(chg), intPtrTone(chg)),
			plainTone(signedOrNone(growth, "%"), toneOf(growth)),
			plain(commas(e.latestTotal)),
		)
		rows = append(rows, row)
	}
	summary := "No school has an enrolment figure in both years"
	if comparedTotal > 0 {
		var growth *float64
		if beforeTotal != 0 {
			g := pyRound(float64(100*(afterTotal-beforeTotal))/float64(beforeTotal), 1)
			growth = &g
		}
		summary = fmt.Sprintf("%s to %s learners (%s) across %s schools compared",
			commas(beforeTotal), commas(afterTotal), signedOrNone(growth, "%"), commas(comparedTotal))
	}
	cols := append([]Column{}, leadColumns...)
	cols = append(cols,
		Column{Label: "Schools", Numeric: true},
		Column{Label: "Schools Compared", Numeric: true},
		Column{Label: "FY " + previous, Numeric: true},
		Column{Label: "FY " + ws.fy, Numeric: true},
		Column{Label: "Change", Numeric: true},
		Column{Label: "Growth", Numeric: true},
		Column{Label: "Latest Enrolment", Numeric: true},
	)
	return table{
		title:   fmt.Sprintf("Enrolment by Cluster, FY %s to FY %s", previous, ws.fy),
		summary: summary,
		columns: cols,
		rows:    rows,
		note:    "Growth counts only schools with a figure in both years, so a school joining a cluster is never read as growth.",
		empty:   "No cluster is in your scope.",
	}
}

func (ws workspace) academicTable() table {
	previous := previousFY(ws.fy)
	rows := [][]cell{}
	comparedTotal := 0
	for _, c := range ws.clusters {
		lr := ws.facts[c.ID].learning
		comparedTotal += lr.compared
		beforeText, afterText := "", ""
		if lr.before != nil {
			beforeText = fixed(*lr.before, 1) + "%"
		}
		if lr.after != nil {
			afterText = fixed(*lr.after, 1) + "%"
		}
		declinedTone := ""
		if lr.declined > 0 {
			declinedTone = "danger"
		}
		row := append(leadCells(ws, c, "?tab=learning&fy="+ws.fy),
			plain(strconv.Itoa(lr.compared)),
			plain(beforeText),
			plain(afterText),
			plainTone(signedOrNone(lr.change(), ""), toneOf(lr.change())),
			plain(strconv.Itoa(lr.improved)),
			plain(strconv.Itoa(lr.unchanged)),
			plainTone(strconv.Itoa(lr.declined), declinedTone),
		)
		rows = append(rows, row)
	}
	cols := append([]Column{}, leadColumns...)
	cols = append(cols,
		Column{Label: "Schools Compared", Numeric: true},
		Column{Label: "FY " + previous, Numeric: true},
		Column{Label: "FY " + ws.fy, Numeric: true},
		Column{Label: "Change", Numeric: true},
		Column{Label: "Improved", Numeric: true},
		Column{Label: "Unchanged", Numeric: true},
		Column{Label: "Declined", Numeric: true},
	)
	return table{
		title:   fmt.Sprintf("Learning Results by Cluster, FY %s to FY %s", previous, ws.fy),
		summary: fmt.Sprintf("%s schools compared", commas(comparedTotal)),
		columns: cols,
		rows:    rows,
		note:    "Confirmed results only. These are the results the schools recorded, not a measure of what any one activity caused.",
		empty:   "No cluster is in your scope.",
	}
}

func (ws workspace) loansTable(mayReadLoans bool) table {
	rows := [][]cell{}
	fundedTotal := 0
	for _, c := range ws.clusters {
		f := ws.facts[c.ID]
		card := ws.cards[c.ID]
		fundedTotal += f.funded
		partScore := func(comp composite, key string) *float64 {
			for _, p := range comp.parts {
				if p.key == key {
					return p.score
				}
			}
			return nil
		}
		leadQuery := ""
		if mayReadLoans {
			leadQuery = "?tab=loans"
		}
		cells := append(leadCells(ws, c, leadQuery), plain(strconv.Itoa(f.funded)))
		if mayReadLoans {
			cells = append(cells,
				plain(strconv.Itoa(f.loans.loanCount)),
				plain(commas(int(math.Round(f.loans.disbursed)))),
			)
		}
		cells = append(cells,
			plain(pctFloat(partScore(card.leader, "finance_ssa"))),
			plain(pctFloat(partScore(card.leader, "compliance_ssa"))),
			plain(pctFloat(partScore(card.impact, "bt"))),
		)
		rows = append(rows, cells)
	}
	cols := append([]Column{}, leadColumns...)
	cols = append(cols, Column{Label: "Schools With Loans", Numeric: true})
	if mayReadLoans {
		cols = append(cols,
			Column{Label: "Loans", Numeric: true},
			Column{Label: "Disbursed (UGX)", Numeric: true},
		)
	}
	cols = append(cols,
		Column{Label: "Financial Health SSA", Numeric: true},
		Column{Label: "Government Requirements SSA", Numeric: true},
		Column{Label: "Business Transformation", Numeric: true},
	)
	return table{
		title:   "Loans and Business Transformation by Cluster",
		summary: fmt.Sprintf("%s schools hold a loan", commas(fundedTotal)),
		columns: cols,
		rows:    rows,
		note:    "The SSA columns are the share of compared schools that improved on the area. Loan records are the loan register's; a reader sees here what the register shows them.",
		empty:   "No cluster is in your scope.",
	}
}

func (ws workspace) storiesTable() table {
	type entry struct {
		count int
		cells []cell
	}
	entries := make([]entry, 0, len(ws.clusters))
	approvedTotal, waitingTotal := 0, 0
	for _, c := range ws.clusters {
		st := ws.facts[c.ID].stories
		approvedTotal += st.approved
		waitingTotal += st.waiting
		cells := append(leadCells(ws, c, "?tab=stories"),
			plain(strconv.Itoa(st.approved)),
			plain(strconv.Itoa(st.waiting)),
			plain(strconv.Itoa(st.count)),
			plain(strconv.Itoa(st.withEvidence)),
			plain(formatDay(st.latestDate)),
		)
		entries = append(entries, entry{count: st.count, cells: cells})
	}
	sort.SliceStable(entries, func(i, j int) bool { return entries[i].count > entries[j].count })
	rows := make([][]cell, len(entries))
	for i, e := range entries {
		rows[i] = e.cells
	}
	cols := append([]Column{}, leadColumns...)
	cols = append(cols,
		Column{Label: "Approved", Numeric: true},
		Column{Label: "Under Review", Numeric: true},
		Column{Label: "All Stories", Numeric: true},
		Column{Label: "With Evidence", Numeric: true},
		Column{Label: "Latest Story"},
	)
	return table{
		title:   "Most Significant Change Stories by Cluster",
		summary: fmt.Sprintf("%d approved · %d with a reviewer", approvedTotal, waitingTotal),
		columns: cols,
		rows:    rows,
		note:    "Only an approved story counts as evidence. A draft is not listed.",
		empty:   "No cluster is in your scope.",
	}
}

func (ws workspace) impactTable() table {
	type entry struct {
		sortScore int
		cells     []cell
	}
	entries := make([]entry, 0, len(ws.clusters))
	for _, c := range ws.clusters {
		card := ws.cards[c.ID]
		sc := card.impact.score()
		sortVal := -1
		if sc != nil {
			sortVal = *sc
		}
		cells := append(leadCells(ws, c, "?tab=scores&fy="+ws.fy+"&part=impact"),
			scoreCell(card.health, c.ID, ws.fy),
			scoreCell(card.impact, c.ID, ws.fy),
			plain(fmt.Sprintf("%d · %s", card.maturity, maturityLabel(card.maturity))),
		)
		for _, p := range card.impact.parts {
			cells = append(cells, plain(pctFloat(p.score)))
		}
		entries = append(entries, entry{sortScore: sortVal, cells: cells})
	}
	sort.SliceStable(entries, func(i, j int) bool { return entries[i].sortScore > entries[j].sortScore })
	rows := make([][]cell, len(entries))
	for i, e := range entries {
		rows[i] = e.cells
	}
	cols := append([]Column{}, leadColumns...)
	cols = append(cols, Column{Label: "Health"}, Column{Label: "Impact"}, Column{Label: "Maturity"})
	for _, d := range rules.Scores["impact"].Dimensions {
		cols = append(cols, Column{Label: d.Label, Numeric: true})
	}
	return table{
		title:   fmt.Sprintf("Clusters Compared, FY %s", ws.fy),
		summary: fmt.Sprintf("%s, highest Impact first", plural(len(rows), "cluster")),
		columns: cols,
		rows:    rows,
		note:    "Each part is a share out of 100 from the cluster's own records; a dash is a part that cannot be measured yet and is left out of the score. Use this to ask why one cluster moves and another does not.",
		empty:   "No cluster is in your scope.",
	}
}

func (ws workspace) coursesTable() table {
	before := previousFY(ws.fy)
	type agg struct {
		course      string
		areaLabel   string
		sessions    map[string]bool
		clusters    map[string]bool
		readings    int
		better      int
		totalChange float64
	}
	byKey := map[[2]string]*agg{}
	order := [][2]string{}
	for _, c := range ws.clusters {
		f := ws.facts[c.ID]
		for _, s := range f.attendance.allSessions {
			if !s.isTraining || s.area == "" || (s.fy != ws.fy && s.fy != before) {
				continue
			}
			area := f.movement[s.area]
			if area == nil {
				continue
			}
			for schoolID := range s.attended {
				sr, ok := area.schools[schoolID]
				if !ok || sr.verdict == "not_compared" {
					continue
				}
				k := [2]string{s.name, s.area}
				entry := byKey[k]
				if entry == nil {
					entry = &agg{
						course:    s.name,
						areaLabel: interventionLabel(s.area),
						sessions:  map[string]bool{},
						clusters:  map[string]bool{},
					}
					byKey[k] = entry
					order = append(order, k)
				}
				entry.sessions[s.id] = true
				entry.clusters[c.ID] = true
				entry.readings++
				if sr.verdict == rules.Change.Improved || sr.verdict == rules.Change.MaintainedStrong {
					entry.better++
				}
				if sr.change != nil {
					entry.totalChange += *sr.change
				}
			}
		}
	}
	type courseRow struct {
		course     string
		areaLabel  string
		sessions   int
		clusters   int
		readings   int
		better     int
		betterPct  int
		meanChange float64
	}
	out := make([]courseRow, 0, len(order))
	for _, k := range order {
		e := byKey[k]
		out = append(out, courseRow{
			course:     e.course,
			areaLabel:  e.areaLabel,
			sessions:   len(e.sessions),
			clusters:   len(e.clusters),
			readings:   e.readings,
			better:     e.better,
			betterPct:  pyRoundInt(float64(100*e.better) / float64(e.readings)),
			meanChange: pyRound(e.totalChange/float64(e.readings), 1),
		})
	}
	sort.SliceStable(out, func(i, j int) bool {
		if out[i].meanChange != out[j].meanChange {
			return out[i].meanChange > out[j].meanChange
		}
		return out[i].course < out[j].course
	})
	rows := make([][]cell, len(out))
	for i, r := range out {
		mc := r.meanChange
		rows[i] = []cell{
			plain(r.course),
			plain(r.areaLabel),
			plain(strconv.Itoa(r.sessions)),
			plain(strconv.Itoa(r.clusters)),
			plain(strconv.Itoa(r.readings)),
			plain(fmt.Sprintf("%d (%d%%)", r.better, r.betterPct)),
			plainTone(signed(mc, 1, ""), toneOf(&mc)),
		}
	}
	return table{
		title:   fmt.Sprintf("SSA Movement After Each Training, FY %s to FY %s", before, ws.fy),
		summary: plural(len(rows), "training course"),
		columns: []Column{
			{Label: "Training"},
			{Label: "SSA Area"},
			{Label: "Sessions", Numeric: true},
			{Label: "Clusters", Numeric: true},
			{Label: "School Readings", Numeric: true},
			{Label: "Rose", Numeric: true},
			{Label: "Mean SSA Change", Numeric: true},
		},
		rows:  rows,
		note:  "A school is counted once for each training it attended. This shows how the area trained moved at the schools that took part; it does not show that the training caused the movement, and a course with few readings should be read with care.",
		empty: "No school attended a group training with a named SSA area and has a confirmed SSA on that area in both years.",
	}
}

func (ws workspace) planningTable() table {
	rows := [][]cell{}
	unplanned := 0
	yes := func(flag bool) cell {
		if flag {
			return plainTone("Planned", "success")
		}
		return plainTone("Not planned", "danger")
	}
	for _, c := range ws.clusters {
		f := ws.facts[c.ID]
		if !f.plan.meetingPlanned || !f.plan.trainingPlanned {
			unplanned++
		}
		notSeen := 0
		for _, s := range f.attendance.schools {
			if s.attended == 0 {
				notSeen++
			}
		}
		moved := f.movement[overall]
		notSeenCell := plain("0")
		if notSeen > 0 {
			notSeenCell = link(strconv.Itoa(notSeen), c.ID, "?tab=attendance&fy="+ws.fy, "")
		}
		driftingCell := plain("0")
		if f.attendance.drifting > 0 {
			driftingCell = link(strconv.Itoa(f.attendance.drifting), c.ID, "?tab=attendance&fy="+ws.fy+"&show=missing", "danger")
		}
		notCompCell := plain("0")
		if moved.notCompared > 0 {
			notCompCell = link(strconv.Itoa(moved.notCompared), c.ID, "?tab=ssa&fy="+ws.fy+"&area=overall&verdict=not_compared", "")
		}
		row := append(leadCells(ws, c, ""),
			yes(f.plan.meetingPlanned),
			yes(f.plan.trainingPlanned),
			plain(fmt.Sprintf("%d of %d", f.plan.meetingsDelivered, f.plan.meetingsDue)),
			plain(fmt.Sprintf("%d of %d", f.plan.trainingsDelivered, f.plan.trainingsDue)),
			notSeenCell,
			driftingCell,
			notCompCell,
		)
		rows = append(rows, row)
	}
	cols := append([]Column{}, leadColumns...)
	cols = append(cols,
		Column{Label: "Cluster Meeting"},
		Column{Label: "Group Training"},
		Column{Label: "Meetings Delivered", Numeric: true},
		Column{Label: "Trainings Delivered", Numeric: true},
		Column{Label: "Schools With No Session", Numeric: true},
		Column{Label: fmt.Sprintf("Absent %d+ Sessions", rules.MissedInARowAlert), Numeric: true},
		Column{Label: "SSA Not Compared", Numeric: true},
	)
	return table{
		title:   fmt.Sprintf("Cluster Planning and Gaps, FY %s", ws.fy),
		summary: fmt.Sprintf("%d of %s missing a meeting or a group training in the plan", unplanned, plural(len(ws.clusters), "cluster")),
		columns: cols,
		rows:    rows,
		note:    "Planning makes the work; this page only measures it. Schedule a meeting or a group training from the cluster's profile, which opens the planning page with the cluster chosen.",
		empty:   "No cluster is in your scope.",
	}
}

func (ws workspace) evidenceTable() table {
	rows := [][]cell{}
	withoutTotal := 0
	for _, c := range ws.clusters {
		f := ws.facts[c.ID]
		withoutTotal += f.attendance.withoutRegister
		moved := f.movement[overall]
		sessionsCell := plain("0")
		if len(f.attendance.sessions) > 0 {
			sessionsCell = link(strconv.Itoa(len(f.attendance.sessions)), c.ID, "?tab=attendance&fy="+ws.fy+"&show=sessions", "")
		}
		missingTone := ""
		if f.attendance.withoutRegister > 0 {
			missingTone = "danger"
		}
		notCompCell := plain("0")
		if moved.notCompared > 0 {
			notCompCell = link(strconv.Itoa(moved.notCompared), c.ID, "?tab=ssa&fy="+ws.fy+"&area=overall&verdict=not_compared", "")
		}
		storiesCell := plain("0")
		if f.stories.withoutEvidence > 0 {
			storiesCell = link(strconv.Itoa(f.stories.withoutEvidence), c.ID, "?tab=stories", "")
		}
		row := append(leadCells(ws, c, ""),
			sessionsCell,
			plainTone(strconv.Itoa(f.attendance.withoutRegister), missingTone),
			notCompCell,
			plain(strconv.Itoa(f.enrolment.schoolCount-f.enrolment.compared)),
			storiesCell,
		)
		rows = append(rows, row)
	}
	cols := append([]Column{}, leadColumns...)
	cols = append(cols,
		Column{Label: "Registers Taken", Numeric: true},
		Column{Label: "Registers Missing", Numeric: true},
		Column{Label: "SSA Not Compared", Numeric: true},
		Column{Label: "No Enrolment Pair", Numeric: true},
		Column{Label: "Stories Without Evidence", Numeric: true},
	)
	return table{
		title:   fmt.Sprintf("Where the Record Is Missing, FY %s", ws.fy),
		summary: fmt.Sprintf("%d delivered sessions without a register", withoutTotal),
		columns: cols,
		rows:    rows,
		note:    "A figure on any other section is only as complete as these records. Activity evidence is reviewed on the Evidence page.",
		empty:   "No cluster is in your scope.",
	}
}

func (ws workspace) reportsTable(canExport bool) table {
	rows := [][]cell{}
	for _, s := range rules.Sections {
		if !isBuiltInSection(s.Key) || s.Key == "reports" {
			continue
		}
		downloadCell := plain("Export not enabled for your role")
		if canExport {
			downloadCell = hrefCell("Download CSV", "/cluster-oversight/"+s.Key+"?fy="+url.QueryEscape(ws.fy)+"&format=csv", "")
		}
		rows = append(rows, []cell{
			plain(s.Label),
			plain(s.Description),
			downloadCell,
		})
	}
	return table{
		title:   fmt.Sprintf("Reports, FY %s", ws.fy),
		summary: plural(len(rows), "download"),
		columns: []Column{
			{Label: "Report"},
			{Label: "What It Holds"},
			{Label: "Download"},
		},
		rows: rows,
		note: "A download holds the rows the section shows you, for the clusters in your scope and the year chosen above.",
	}
}

func scoringPage(setting *settingRow) *screensv1.GetPageResponse {
	s := settingsOf(setting)
	blocks := []*screensv1.PageBlock{}

	statusFacts := []*screensv1.PageFact{}
	if setting == nil {
		statusFacts = append(statusFacts, &screensv1.PageFact{Label: "Status", Value: "Using default weights and maturity thresholds"})
	} else {
		who := setting.SetByName
		if who == "" {
			who = setting.SetBy
		}
		if who == "" {
			who = "Configured"
		}
		statusFacts = append(statusFacts, &screensv1.PageFact{Label: "Configured by", Value: who})
		if setting.SetAt != "" {
			statusFacts = append(statusFacts, &screensv1.PageFact{Label: "Last updated", Value: formatDay(setting.SetAt)})
		}
		if strings.TrimSpace(setting.Note) != "" {
			statusFacts = append(statusFacts, &screensv1.PageFact{Label: "Note", Value: collapse(setting.Note)})
		}
	}
	blocks = append(blocks, &screensv1.PageBlock{
		Kind: &screensv1.PageBlock_Facts{Facts: &screensv1.PageFacts{Facts: statusFacts}},
	})

	for _, key := range scoreOrder {
		scoreRule := rules.Scores[key]
		weights := s.weights[key]
		total := 0.0
		for _, d := range scoreRule.Dimensions {
			total += weights[d.Key]
		}
		if total == 0 {
			total = 1
		}
		rows := make([]*screensv1.PageRow, 0, len(scoreRule.Dimensions))
		for _, d := range scoreRule.Dimensions {
			w := weights[d.Key]
			sharePct := pyRoundInt(100 * w / total)
			rows = append(rows, &screensv1.PageRow{
				Cells: []*screensv1.PageCell{
					{Text: d.Label},
					{Text: strconv.FormatFloat(w, 'f', -1, 64)},
					{Text: strconv.FormatFloat(d.Weight, 'f', -1, 64)},
					{Text: fmt.Sprintf("%d%%", sharePct)},
				},
			})
		}
		footnote := ""
		if missing := notCollected[key]; len(missing) > 0 {
			footnote = "Not collected on the platform yet: " + strings.Join(missing, "; ") + "."
		}
		blocks = append(blocks, &screensv1.PageBlock{
			Kind: &screensv1.PageBlock_Table{Table: &screensv1.PageTable{
				Title: scoreRule.Title,
				Columns: []*screensv1.PageColumn{
					{Label: "Part"},
					{Label: "Weight", Numeric: true},
					{Label: "Default", Numeric: true},
					{Label: "Share", Numeric: true},
				},
				Rows:     rows,
				Footnote: footnote,
			}},
		})
	}

	mRows := make([]*screensv1.PageRow, 0, len(maturityRuleOrder))
	for _, key := range maturityRuleOrder {
		lbl := maturityLabels[key]
		if lbl == "" {
			lbl = pyTitle(replaceUnderscores(key))
		}
		mRows = append(mRows, &screensv1.PageRow{
			Cells: []*screensv1.PageCell{
				{Text: lbl},
				{Text: strconv.FormatFloat(s.maturity[key], 'f', -1, 64)},
				{Text: strconv.FormatFloat(rules.MaturityDefaults[key], 'f', -1, 64)},
			},
		})
	}
	blocks = append(blocks, &screensv1.PageBlock{
		Kind: &screensv1.PageBlock_Table{Table: &screensv1.PageTable{
			Title: "Maturity Thresholds",
			Columns: []*screensv1.PageColumn{
				{Label: "Rule"},
				{Label: "Current", Numeric: true},
				{Label: "Default", Numeric: true},
			},
			Rows: mRows,
		}},
	})

	return &screensv1.GetPageResponse{
		Header: &screensv1.PageHeader{
			Eyebrow:     "Cluster Oversight",
			Title:       "Cluster Scoring",
			Description: "What each score weighs, and what each maturity level asks.",
			BackLabel:   "Cluster Oversight",
			BackHref:    Path,
		},
		Blocks:  blocks,
		WebPath: "/cluster-oversight/scoring",
	}
}

// csvSafe protects spreadsheet readers against CSV formula injection while
// leaving signed numbers ("+1.5", "-0.3%") untouched.
func csvSafe(value string) string {
	if value == "" {
		return ""
	}
	switch value[0] {
	case '=', '@':
		return "'" + value
	case '+', '-':
		clean := strings.TrimSuffix(strings.ReplaceAll(value, ",", ""), "%")
		if _, err := strconv.ParseFloat(clean, 64); err != nil {
			return "'" + value
		}
	}
	return value
}

func encodeCSV(t table) ([]byte, error) {
	var buf bytes.Buffer
	w := csv.NewWriter(&buf)
	cols := t.columns
	if len(cols) == 0 {
		cols = rules.Command.Columns
	}
	headerRow := make([]string, len(cols))
	for i, c := range cols {
		headerRow[i] = csvSafe(collapse(c.Label))
	}
	if err := w.Write(headerRow); err != nil {
		return nil, err
	}
	for _, r := range t.rows {
		line := make([]string, len(r))
		for i, c := range r {
			line[i] = csvSafe(collapse(c.text))
		}
		if err := w.Write(line); err != nil {
			return nil, err
		}
	}
	w.Flush()
	return buf.Bytes(), w.Error()
}

// Authenticator authenticates a Bearer Authorization header.
type Authenticator interface {
	Authenticate(ctx context.Context, header string) (auth.Principal, error)
}

// RegisterHTTP mounts the native Go Cluster Oversight CSV export endpoint:
//   - GET /api/v1/cluster-oversight/{section}/csv?fy=...&area=...&view=...
func (s *Service) RegisterHTTP(mux *http.ServeMux, auther Authenticator) {
	mux.HandleFunc("GET /api/v1/cluster-oversight/{section}/csv", func(w http.ResponseWriter, r *http.Request) {
		p, err := auther.Authenticate(r.Context(), r.Header.Get("Authorization"))
		if err != nil {
			http.Error(w, "Sign in first.", http.StatusUnauthorized)
			return
		}
		section := strings.TrimSpace(r.PathValue("section"))
		if !isBuiltInSection(section) || section == "reports" {
			http.Error(w, "Unknown Cluster Oversight section.", http.StatusNotFound)
			return
		}
		doors, ok := rules.Doors[p.ActiveRole]
		if !ok || !doors.Page || !doors.Export {
			http.Error(w, "You are not authorized to export this section.", http.StatusForbidden)
			return
		}
		now := s.now()
		scope, err := schooldirectory.ResolveScope(r.Context(), s.db, p, now)
		if err != nil {
			http.Error(w, "Could not resolve reader scope.", http.StatusInternalServerError)
			return
		}
		rc := reach{}
		if !scope.CountryScope && !scope.SummaryOnly {
			if rc, err = reachOf(r.Context(), s.db, scope); err != nil {
				http.Error(w, "Could not resolve cluster scope.", http.StatusInternalServerError)
				return
			}
		}
		years := yearOptions(now)
		query := r.URL.Query()
		fy := strings.TrimSpace(query.Get("fy"))
		if !in(years, fy) {
			fy = schooldirectory.OperationalFY(now)
		}
		found, err := read(r.Context(), s.db, scope, rc, fy)
		if err != nil {
			http.Error(w, "Could not read Cluster Oversight records.", http.StatusInternalServerError)
			return
		}
		ws := load(found, fy, now.In(kampala).Format(time.DateOnly), nonEmpty(p.UserID, p.StaffProfileID))
		tbl := ws.buildSection(section, doors, ssaArea(query), impactView(query))
		payload, err := encodeCSV(tbl)
		if err != nil {
			http.Error(w, "Could not encode CSV.", http.StatusInternalServerError)
			return
		}
		w.Header().Set("Content-Type", "text/csv; charset=utf-8")
		w.Header().Set("Content-Disposition", fmt.Sprintf(`attachment; filename="cluster-oversight-%s-fy%s.csv"`, section, fy))
		w.Header().Set("Cache-Control", "no-store")
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write(payload)
	})
}
