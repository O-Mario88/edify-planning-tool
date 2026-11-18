package schoolprofile

import (
	"context"
	"fmt"
	"math"
	"net/url"
	"sort"
	"strconv"
	"strings"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
)

// The Overview's tables and insight rail for a profile of many schools:
// the best and struggling intervention, what the profile covers level by
// level, the rankings of its schools, and what needs attention.

// ranked is a row a ranking reads (engine._rank and _movers): a school or a
// cluster, with its scores and their change.
type ranked struct {
	id, code, name    string
	current, previous *float64
	verdict           change
	rank              int
	// The work at the row's schools (and a cluster's own sessions).
	visits, visitsDone, trainings, trainingsDone int
}

func (r ranked) changeOr0() float64 {
	if r.verdict.delta == nil {
		return 0
	}
	return *r.verdict.delta
}

// rank is engine._rank: the top and the bottom of the rows scored this
// year, the bottom never repeating the top.
func rank(rows []ranked) (best, worst []ranked) {
	scored := []ranked{}
	for _, r := range rows {
		if r.current != nil {
			scored = append(scored, r)
		}
	}
	sort.SliceStable(scored, func(i, j int) bool {
		a, b := scored[i], scored[j]
		if *a.current != *b.current {
			return *a.current > *b.current
		}
		if a.changeOr0() != b.changeOr0() {
			return a.changeOr0() > b.changeOr0()
		}
		return strings.ToLower(a.name) < strings.ToLower(b.name)
	})
	n := rules.Engine.Scope.Ranked
	for i := 0; i < len(scored) && i < n; i++ {
		r := scored[i]
		r.rank = i + 1
		best = append(best, r)
	}
	tail := []ranked{}
	if len(scored) > n {
		tail = scored[n:]
		if len(tail) > n {
			tail = tail[len(tail)-n:]
		}
	}
	for i := len(tail) - 1; i >= 0; i-- {
		r := tail[i]
		r.rank = len(scored) - (len(tail) - 1 - i)
		worst = append(worst, r)
	}
	return best, worst
}

// movers is engine._movers: the rows that improved most and those that
// declined most.
func movers(rows []ranked) (improving, declining []ranked) {
	for _, r := range rows {
		switch r.verdict.status {
		case "improved":
			improving = append(improving, r)
		case "declined":
			declining = append(declining, r)
		}
	}
	byName := func(a, b ranked) bool { return strings.ToLower(a.name) < strings.ToLower(b.name) }
	sort.SliceStable(improving, func(i, j int) bool {
		a, b := improving[i], improving[j]
		if *a.verdict.delta != *b.verdict.delta {
			return *a.verdict.delta > *b.verdict.delta
		}
		return byName(a, b)
	})
	sort.SliceStable(declining, func(i, j int) bool {
		a, b := declining[i], declining[j]
		if *a.verdict.delta != *b.verdict.delta {
			return *a.verdict.delta < *b.verdict.delta
		}
		return byName(a, b)
	})
	cut := func(list []ranked) []ranked {
		if len(list) > rules.Engine.Scope.Ranked {
			list = list[:rules.Engine.Scope.Ranked]
		}
		for i := range list {
			list[i].rank = i + 1
		}
		return list
	}
	return cut(improving), cut(declining)
}

// schoolRows are the scope's schools as the rankings read them.
func (pr *scopeProfile) schoolRows() []ranked {
	out := make([]ranked, 0, len(pr.schools))
	for _, x := range pr.schools {
		score := pr.scores[x.id]
		r := ranked{id: x.id, code: x.code, name: x.name, current: score.current, previous: score.previous, verdict: pr.verdicts[x.id]}
		if w := pr.schoolWork[x.id]; w != nil {
			r.visits, r.visitsDone, r.trainings, r.trainingsDone = w.visits, w.visitsDone, w.trainings, w.trainingsDone
		}
		out = append(out, r)
	}
	return out
}

// clusterRows are engine.build's clusters: each live cluster's schools in
// the scope, their mean scores and the change, by name.
func (pr *scopeProfile) clusterRows(book ruleBook) []ranked {
	members := map[string][]scopeSchool{}
	for _, x := range pr.schools {
		if pr.clusters[x.cluster] != "" {
			members[x.cluster] = append(members[x.cluster], x)
		}
	}
	out := []ranked{}
	for id, name := range pr.clusters {
		current, previous := []*float64{}, []*float64{}
		r := ranked{id: id, name: name}
		for _, x := range members[id] {
			score := pr.scores[x.id]
			current, previous = append(current, score.current), append(previous, score.previous)
			if w := pr.schoolWork[x.id]; w != nil {
				r.visits += w.visits
				r.visitsDone += w.visitsDone
			}
		}
		r.current, r.previous = pyMean(current), pyMean(previous)
		r.verdict = book.overallChange(r.previous, r.current)
		if w := pr.clusterWork[id]; w != nil {
			r.trainings, r.trainingsDone = w.trainings, w.trainingsDone
		}
		out = append(out, r)
	}
	sort.SliceStable(out, func(i, j int) bool {
		a, b := strings.ToLower(out[i].name), strings.ToLower(out[j].name)
		if a != b {
			return a < b
		}
		return out[i].id < out[j].id
	})
	return out
}

// focusWork is profile_records.focus_work: the year's work in the scope
// naming each intervention as its focus, planned and done.
func (s *Service) focusWork(ctx context.Context, ids, liveClusters []string, fy string, w window) (map[string][2]int, error) {
	args := []any{}
	where := scopeWork(ids, liveClusters, fy, w, &args)
	args = append(args, rules.Engine.CompletedWorkStatuses)
	rows, err := s.db.Query(ctx, fmt.Sprintf(`
SELECT a.focus_intervention, count(a.id), count(a.id) FILTER (WHERE a.status = ANY($%d))
FROM activity a WHERE a.focus_intervention IS NOT NULL AND a.focus_intervention <> '' AND `, len(args))+where+`
GROUP BY 1`, args...)
	if err != nil {
		return nil, fmt.Errorf("schoolprofile: reading the work by intervention: %w", err)
	}
	out := map[string][2]int{}
	for rows.Next() {
		var key string
		var planned, done int
		if err := rows.Scan(&key, &planned, &done); err != nil {
			rows.Close()
			return nil, err
		}
		out[key] = [2]int{planned, done}
	}
	rows.Close()
	return out, rows.Err()
}

// rankingTable is partials/profiles/_ranking.html for schools.
func rankingTable(rows []ranked, title, empty, label, previousLabel string, openSchools bool) *screensv1.PageBlock {
	t := &screensv1.PageTable{Title: title, Subtitle: label}
	if len(rows) == 0 {
		t.EmptyMessage = empty
		return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Table{Table: t}}
	}
	t.Columns = []*screensv1.PageColumn{{Label: "#", Numeric: true}, {Label: "School ID"}, {Label: "School"},
		{Label: previousLabel, Numeric: true}, {Label: label, Numeric: true}, {Label: "Change", Numeric: true}}
	for _, r := range rows {
		name := &screensv1.PageCell{Text: r.name}
		if openSchools {
			name.Href = "/schools/" + r.id
		}
		changeCell := &screensv1.PageCell{Text: "—"}
		if r.verdict.delta != nil {
			changeCell = &screensv1.PageCell{Text: signedTwoPlaces(*r.verdict.delta), Tone: r.verdict.tone()}
		}
		t.Rows = append(t.Rows, &screensv1.PageRow{Cells: []*screensv1.PageCell{
			{Text: strconv.Itoa(r.rank)}, {Text: r.code}, name,
			{Text: score(r.previous)}, {Text: score(r.current), Strong: true}, changeCell,
		}})
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Table{Table: t}}
}

// tables are the Overview's tables after its strips, then its rail.
func (pr *scopeProfile) tables(l lens, book ruleBook, focus map[string][2]int, openSchools bool) []*screensv1.PageBlock {
	records := l.records()
	label, previousLabel := fyLabel(l.fy), fyLabel(previousFY(l.fy))
	tabURL := func(section, show string) string {
		u := l.href() + "tab=" + section + "&fy=" + l.fy
		if show != "" {
			u += "&show=" + show
		}
		return u
	}
	noSSA := 0
	for _, x := range pr.schools {
		if rules.Engine.Requirements[x.kind].TakesSSA && pr.scores[x.id].current == nil {
			noSSA++
		}
	}

	// ── Best and struggling intervention ──────────────────────────────────
	best, struggling := picks(pr.cmp.rows)
	table := &screensv1.PageTable{
		Title: "Best Performing And Struggling Intervention", Subtitle: previousLabel + " to " + label,
		Columns: []*screensv1.PageColumn{{Label: "Standing"}, {Label: "Intervention"}, {Label: "Previous", Numeric: true},
			{Label: "Current", Numeric: true}, {Label: "Change", Numeric: true}, {Label: "Trend"}, {Label: "Chosen By"},
			{Label: "Supporting Activities", Numeric: true}, {Label: "Recommended"}},
		Footnote: rules.Engine.InterventionMethod,
	}
	w := work{focus: focus}
	for _, slot := range []struct {
		pick           *pick
		standing, tone string
		isBest         bool
	}{{best, "Best performing", "success", true}, {struggling, "Struggling", "danger", false}} {
		table.Rows = append(table.Rows, &screensv1.PageRow{Cells: interventionRow(slot.pick, slot.standing, slot.tone, slot.isBest, best != nil, noSSA > 0, w, label, records)})
	}
	blocks := []*screensv1.PageBlock{{Kind: &screensv1.PageBlock_Table{Table: table}}}

	// ── What this profile covers ───────────────────────────────────────────
	schools, clusters := pr.schoolRows(), pr.clusterRows(book)
	levels := rules.Engine.Scope.LevelsOf[pr.scope.kind]
	sections := rules.Engine.Scope.SectionsOf[pr.scope.kind]
	if len(levels) > 0 {
		summary := &screensv1.PageTable{Title: "What This Profile Covers", Subtitle: pr.scope.covers + " · " + label,
			Columns: []*screensv1.PageColumn{{Label: "Level"}, {Label: "Total", Numeric: true}, {Label: "With SSA", Numeric: true},
				{Label: "Improved", Numeric: true}, {Label: "Declined", Numeric: true}, {Label: "Best"}, {Label: "Lowest"},
				{Label: "Visits Completed", Numeric: true}, {Label: "Trainings Completed", Numeric: true}}}
		for _, level := range levels {
			var rows []ranked
			switch level {
			case "schools":
				rows = schools
			case "clusters":
				rows = clusters
			default:
				// A level read by its parts (engine.groups) is not drawn yet.
				return nil
			}
			measured, improved, declined := 0, 0, 0
			var visits, visitsDone, trainings, trainingsDone int
			for _, r := range rows {
				if r.current != nil {
					measured++
				}
				switch r.verdict.status {
				case "improved":
					improved++
				case "declined":
					declined++
				}
				visits, visitsDone, trainings, trainingsDone = visits+r.visits, visitsDone+r.visitsDone, trainings+r.trainings, trainingsDone+r.trainingsDone
			}
			top, bottom := rank(rows)
			bestText, lowestText := "—", "—"
			if len(top) > 0 {
				bestText = top[0].name + " · " + twoPlaces(*top[0].current)
			}
			if measured > 1 {
				lowest := bottom
				if len(lowest) == 0 {
					lowest = top[1:]
				}
				if len(lowest) > 0 {
					last := lowest[len(lowest)-1]
					lowestText = last.name + " · " + twoPlaces(*last.current)
				}
			}
			href := ""
			if contains(sections, level) {
				href = tabURL(level, "")
			}
			toned := func(n int, tone string) *screensv1.PageCell {
				if n == 0 {
					return &screensv1.PageCell{Text: "0"}
				}
				return &screensv1.PageCell{Text: intcomma(n), Tone: tone}
			}
			summary.Rows = append(summary.Rows, &screensv1.PageRow{Cells: []*screensv1.PageCell{
				{Text: rules.Engine.Scope.LevelLabels[level], Href: href},
				{Text: intcomma(len(rows)), Href: href, Strong: true},
				{Text: intcomma(measured)}, toned(improved, "success"), toned(declined, "danger"),
				{Text: bestText}, {Text: lowestText},
				{Text: intcomma(visitsDone) + " / " + intcomma(visits)},
				{Text: intcomma(trainingsDone) + " / " + intcomma(trainings)},
			}})
		}
		blocks = append(blocks, &screensv1.PageBlock{Kind: &screensv1.PageBlock_Table{Table: summary}})
	}

	// ── The rankings ───────────────────────────────────────────────────────
	top, bottom := rank(schools)
	improving, declining := movers(schools)
	blocks = append(blocks,
		rankingTable(top, "Best Performing Schools", "No school has a confirmed SSA in this year.", label, previousLabel, openSchools),
		rankingTable(bottom, "Schools Needing The Most Support", "No further school has a confirmed SSA in this year.", label, previousLabel, openSchools),
		rankingTable(improving, "Improving Schools", "No school's SSA improved since the previous year.", label, previousLabel, openSchools),
		rankingTable(declining, "Declining Schools", "No school's SSA declined since the previous year.", label, previousLabel, openSchools),
		&screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{Badges: []*screensv1.PageBadge{},
			Items: []*screensv1.PagePanelItem{{Kind: &screensv1.PagePanelItem_Text{Text: rules.Engine.Scope.RankingMethod + " " + rules.Engine.Scope.MoversMethod}}}}}},
	)
	return append(blocks, pr.rail(l, schools, clusters, noSSA))
}

// rail is profile_rail.build: the SSA score and each intervention's, and
// what needs attention (engine.build's attention).
func (pr *scopeProfile) rail(l lens, schools, clusters []ranked, noSSA int) *screensv1.PageBlock {
	records := l.records()
	label, previousLabel := fyLabel(l.fy), fyLabel(previousFY(l.fy))
	tabURL := func(section, show string) string {
		u := l.href() + "tab=" + section + "&fy=" + l.fy
		if show != "" {
			u += "&show=" + show
		}
		return u
	}
	count := func(rows []ranked, status string) int {
		n := 0
		for _, r := range rows {
			if r.verdict.status == status {
				n++
			}
		}
		return n
	}
	interventionsDeclined := 0
	for _, r := range pr.cmp.rows {
		if r.verdict.status == "declined" {
			interventionsDeclined++
		}
	}
	noTraining, noVisit, awaiting := 0, 0, 0
	for _, x := range pr.schools {
		need := rules.Engine.Requirements[x.kind]
		at := pr.schoolWork[x.id]
		if need.Trainings > 0 && (at == nil || at.trainings == 0) {
			noTraining++
		}
		if need.Visits > 0 && (at == nil || at.visits == 0) {
			noVisit++
		}
		if pr.handovers.awaitingSchools[x.id] {
			awaiting++
		}
	}
	type line struct {
		count           int
		one, many, when string
		tab, show, what string
	}
	lines := []line{
		{noSSA, "school has no confirmed SSA", "schools have no confirmed SSA", "in " + label, "schools", "no_ssa", ""},
		{pr.unplanned, "school has nothing planned", "schools have nothing planned", "in " + label, "schools", "unplanned", ""},
		{count(schools, "declined"), "school's SSA declined", "schools' SSA declined", "since " + previousLabel, "schools", "declined", ""},
	}
	if pr.scope.kind != "cluster" {
		lines = append(lines, line{count(clusters, "declined"), "cluster's SSA declined", "clusters' SSA declined", "since " + previousLabel, "clusters", "", ""})
	}
	lines = append(lines,
		line{interventionsDeclined, "SSA intervention declined", "SSA interventions declined", "since " + previousLabel, "ssa", "", ""},
		line{noTraining, "school due a training has none in the plan", "schools due a training have none in the plan", "in " + label, "schools", "no_training", ""},
		line{noVisit, "school due a visit has none in the plan", "schools due a visit have none in the plan", "in " + label, "schools", "no_visit", ""},
		line{awaiting, "school is waiting for a partner's date", "schools are waiting for a partner's date", "", "schools", "awaiting_partner", ""},
		line{pr.meetings.overdue, "cluster meeting is past its date and not held", "cluster meetings are past their date and not held", "", "activities", "", "meetings_overdue"},
		line{pr.visits.overdue, "visit is past its date and not done", "visits are past their date and not done", "", "activities", "", "visits_overdue"},
		line{pr.trainings.overdue, "training is past its date and not delivered", "trainings are past their date and not delivered", "", "activities", "", "trainings_overdue"},
		line{pr.projectOverdue, "project activity is past its date and not done", "project activities are past their date and not done", "", "activities", "", "project_overdue"},
	)
	attention := []*screensv1.PageLink{}
	for _, ln := range lines {
		if ln.count == 0 {
			continue
		}
		words := ln.many
		if ln.count == 1 {
			words = ln.one
		}
		href := tabURL(ln.tab, ln.show)
		if ln.what != "" {
			href = records + ln.what
		}
		attention = append(attention, &screensv1.PageLink{Text: strings.TrimSpace(intcomma(ln.count) + " " + words + " " + ln.when), Href: href})
	}
	meters := []*screensv1.PageMeter{}
	for _, r := range pr.cmp.rows {
		v := 0.0
		if r.current != nil {
			v = *r.current
		}
		share := math.RoundToEven(v * 100 / 10)
		meters = append(meters, &screensv1.PageMeter{
			Label: r.label, Value: strconv.FormatFloat(v, 'f', 1, 64), Fraction: pyRound(share/100, 4),
			Href: records + "intervention&key=" + url.QueryEscape(r.key),
		})
	}
	current, previous := 0.0, 0.0
	if pr.cmp.current != nil {
		current = *pr.cmp.current
	}
	if pr.cmp.previous != nil {
		previous = *pr.cmp.previous
	}
	moved := "0.00"
	if pr.overall.delta != nil && *pr.overall.delta != 0 {
		moved = signedTwoPlaces(*pr.overall.delta)
	}
	subtitle := label
	if l.window.label != "" {
		subtitle += " · " + l.window.label
	}
	attentionPart := &screensv1.PageRailPart{Key: "attention", Title: "Needs Attention", Meters: []*screensv1.PageMeter{}, Links: attention}
	if len(attention) == 0 {
		attentionPart.Note = "Nothing needs attention in " + label + "."
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Rail{Rail: &screensv1.PageRail{
		Title: "Profile Insights", Subtitle: subtitle,
		Parts: []*screensv1.PageRailPart{
			{
				Key: "ssa", Title: "SSA Performance", Figure: strconv.FormatFloat(current, 'f', 2, 64), FigureHref: tabURL("ssa", ""),
				FigureNote: "baseline " + strconv.FormatFloat(previous, 'f', 2, 64) + " · " + moved + " since " + previousLabel,
				Meters:     meters, Note: "Each intervention out of 10; a line opens its schools.", Links: []*screensv1.PageLink{},
			},
			attentionPart,
		},
	}}}
}
