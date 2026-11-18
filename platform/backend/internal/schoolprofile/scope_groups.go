package schoolprofile

import (
	"context"
	"fmt"
	"sort"
	"strconv"
	"strings"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/tablepager"
)

// A scope read by its parts (profile_intelligence.groups): its schools by
// sub-region, district, sub-county or holder, each part's figures, and the
// parts at the top and the bottom.

// part is one part's row.
type part struct {
	ranked
	schools, assessed, unplanned, clusters, enrolment, teachers, leaders int
}

// partField is the school field a scope is read by (GROUPS).
func partField(x scopeSchool, by string) string {
	switch by {
	case "sub_regions":
		return x.subRegion
	case "districts":
		return x.district
	case "sub_counties":
		return x.subCounty
	}
	return x.owner
}

// partNames is _group_names: each field value's part (its id) and name. A
// holder is written as a staff id or a user id, and both are one person.
func (s *Service) partNames(ctx context.Context, by string, keys []string) (map[string][2]string, error) {
	var sql string
	switch by {
	case "districts":
		sql = `SELECT id, id, name FROM district WHERE id = ANY($1)`
	case "sub_regions":
		sql = `SELECT id, id, name FROM sub_region WHERE id = ANY($1)`
	case "sub_counties":
		sql = `SELECT id, id, name FROM sub_county WHERE id = ANY($1)`
	default:
		sql = `SELECT k.key, sp.user_id, COALESCE(NULLIF(u.name, ''), NULLIF(u.email, ''), 'Unnamed')
FROM unnest($1::varchar[]) k(key) JOIN staff_profile sp ON sp.id = k.key OR sp.user_id = k.key
JOIN "user" u ON u.id = sp.user_id`
	}
	rows, err := s.db.Query(ctx, sql, keys)
	if err != nil {
		return nil, fmt.Errorf("schoolprofile: reading the parts' names: %w", err)
	}
	out := map[string][2]string{}
	for rows.Next() {
		var key, id, name string
		if err := rows.Scan(&key, &id, &name); err != nil {
			rows.Close()
			return nil, err
		}
		out[key] = [2]string{id, name}
	}
	rows.Close()
	return out, rows.Err()
}

// groups is profile_intelligence.groups: the rows by name, and how many
// schools have no such part.
func (s *Service) groups(ctx context.Context, pr *scopeProfile, by string, planned map[string]bool) ([]part, int, error) {
	members := map[string][]scopeSchool{}
	order := []string{}
	unplaced := 0
	for _, x := range pr.schools {
		key := partField(x, by)
		if key == "" {
			unplaced++
			continue
		}
		if _, seen := members[key]; !seen {
			order = append(order, key)
		}
		members[key] = append(members[key], x)
	}
	names, err := s.partNames(ctx, by, order)
	if err != nil {
		return nil, 0, err
	}
	// Two identities of one person are one row.
	merged := map[string][]scopeSchool{}
	label := map[string]string{}
	ids := []string{}
	for _, key := range order {
		named, ok := names[key]
		if !ok {
			named = [2]string{key, "Unnamed"}
		}
		if _, seen := merged[named[0]]; !seen {
			ids = append(ids, named[0])
			label[named[0]] = named[1]
		}
		merged[named[0]] = append(merged[named[0]], members[key]...)
	}
	rows := []part{}
	for _, id := range ids {
		p := part{ranked: ranked{id: id, name: label[id]}}
		current, previous := []*float64{}, []*float64{}
		clusters := map[string]bool{}
		for _, x := range merged[id] {
			score := pr.scores[x.id]
			current, previous = append(current, score.current), append(previous, score.previous)
			p.schools++
			if score.current != nil {
				p.assessed++
			}
			if !planned[x.id] {
				p.unplanned++
			}
			if x.cluster != "" {
				clusters[x.cluster] = true
			}
			p.enrolment += x.enrolment
			if w := pr.schoolWork[x.id]; w != nil {
				p.visits += w.visits
				p.visitsDone += w.visitsDone
				p.trainings += w.trainings
				p.trainingsDone += w.trainingsDone
				p.teachers += w.teachers
				p.leaders += w.leaders
			}
		}
		p.clusters = len(clusters)
		p.current, p.previous = pyMean(current), pyMean(previous)
		p.verdict = pr.book.overallChange(p.previous, p.current)
		rows = append(rows, p)
	}
	sort.SliceStable(rows, func(i, j int) bool {
		a, b := strings.ToLower(rows[i].name), strings.ToLower(rows[j].name)
		if a != b {
			return a < b
		}
		return rows[i].id < rows[j].id
	})
	return rows, unplaced, nil
}

// partsBlocks is the section of a scope read by its parts: the parts'
// table (fifty a page) and, with more than one part, their rankings.
func (pr *scopeProfile) partsBlocks(l lens, by string, rows []part, unplaced int, openGroup bool) []*screensv1.PageBlock {
	labels := map[string]string{}
	for _, pair := range rules.Engine.Scope.Sections {
		labels[pair[0]] = pair[1]
	}
	name := labels[by]
	if by == "staff" && pr.scope.kind == "program_lead" {
		name = rules.Engine.Scope.TeamLabel
	}
	groupURL := map[string]string{"sub_regions": "/sub-regions/", "districts": "/districts/", "staff": "/staff/"}[by]
	label, previousLabel := fyLabel(l.fy), fyLabel(previousFY(l.fy))
	t := &screensv1.PageTable{Title: name, Subtitle: intcomma(len(rows)) + " · " + label}
	page := tablepager.Paginate(len(rows), tablePageSize, l.query, "parts_page")
	if len(rows) == 0 {
		t.EmptyMessage = "Nothing to list here."
	} else {
		t.Columns = []*screensv1.PageColumn{{Label: name}, {Label: "Schools", Numeric: true}, {Label: "Assessed", Numeric: true},
			{Label: "Nothing Planned", Numeric: true}, {Label: "Clusters", Numeric: true}, {Label: "Enrolment", Numeric: true},
			{Label: "Visits", Numeric: true}, {Label: "Trainings", Numeric: true}, {Label: "Teachers Trained", Numeric: true},
			{Label: "Leaders Trained", Numeric: true}, {Label: previousLabel, Numeric: true}, {Label: label, Numeric: true},
			{Label: "Change", Numeric: true}, {Label: "Status"}}
		for _, p := range rows[page.Start:page.End] {
			nameCell, schoolsCell := &screensv1.PageCell{Text: p.name}, &screensv1.PageCell{Text: intcomma(p.schools)}
			switch {
			case groupURL == "":
				link := l.href() + "tab=schools&fy=" + l.fy + "&sub_county=" + p.id
				nameCell.Href, schoolsCell.Href = link, link
			case openGroup:
				nameCell.Href = groupURL + p.id + "?fy=" + l.fy
			}
			changeCell := &screensv1.PageCell{Text: "—"}
			if p.verdict.delta != nil {
				changeCell = &screensv1.PageCell{Text: signedTwoPlaces(*p.verdict.delta), Tone: p.verdict.tone()}
			}
			t.Rows = append(t.Rows, &screensv1.PageRow{Cells: []*screensv1.PageCell{
				nameCell, schoolsCell, {Text: intcomma(p.assessed)}, {Text: intcomma(p.unplanned)}, {Text: intcomma(p.clusters)},
				{Text: intcomma(p.enrolment)}, {Text: intcomma(p.visitsDone) + " / " + intcomma(p.visits)},
				{Text: intcomma(p.trainingsDone) + " / " + intcomma(p.trainings)}, {Text: intcomma(p.teachers)}, {Text: intcomma(p.leaders)},
				{Text: score(p.previous)}, {Text: score(p.current), Strong: true}, changeCell, {Text: p.verdict.label()},
			}})
		}
	}
	if page.Pager != nil {
		t.Pager, t.Footnote = page.Pager, page.Pager.Summary
	} else if unplaced > 0 {
		isAre, itThem, has, itIs := "are", "them", "they have", "They are"
		if unplaced == 1 {
			isAre, itThem, has, itIs = "is", "it", "it has", "It is"
		}
		why := has + " none recorded"
		if by == "staff" {
			why = "nobody holds " + itThem
		}
		t.Footnote = fmt.Sprintf("%s school%s of this portfolio %s in no row here: %s. %s still counted in every total of the profile.",
			intcomma(unplaced), plural(unplaced), isAre, why, itIs)
	}
	blocks := []*screensv1.PageBlock{{Kind: &screensv1.PageBlock_Table{Table: t}}}
	if len(rows) <= 1 {
		return blocks
	}
	plain := make([]ranked, len(rows))
	for i, p := range rows {
		plain[i] = p.ranked
	}
	lower := strings.ToLower(name)
	if name == rules.Engine.Scope.TeamLabel {
		lower = "team members"
	}
	best, worst := rank(plain)
	improving, declining := movers(plain)
	partRanking := func(list []ranked, title, empty string) *screensv1.PageBlock {
		rt := &screensv1.PageTable{Title: title, Subtitle: label}
		if len(list) == 0 {
			rt.EmptyMessage = empty
			return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Table{Table: rt}}
		}
		rt.Columns = []*screensv1.PageColumn{{Label: "#", Numeric: true}, {Label: name},
			{Label: previousLabel, Numeric: true}, {Label: label, Numeric: true}, {Label: "Change", Numeric: true}}
		for _, r := range list {
			nameCell := &screensv1.PageCell{Text: r.name}
			if openGroup {
				// The existing page's address: the part's own page, or (a
				// sub-county having none) its id alone.
				nameCell.Href = groupURL + r.id + "?fy=" + l.fy
			}
			changeCell := &screensv1.PageCell{Text: "—"}
			if r.verdict.delta != nil {
				changeCell = &screensv1.PageCell{Text: signedTwoPlaces(*r.verdict.delta), Tone: r.verdict.tone()}
			}
			rt.Rows = append(rt.Rows, &screensv1.PageRow{Cells: []*screensv1.PageCell{
				{Text: strconv.Itoa(r.rank)}, nameCell, {Text: score(r.previous)}, {Text: score(r.current), Strong: true}, changeCell,
			}})
		}
		return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Table{Table: rt}}
	}
	return append(blocks,
		partRanking(best, "Best performing "+lower, "Nothing has a confirmed SSA in this year."),
		partRanking(worst, name+" needing the most support", "Nothing further has a confirmed SSA in this year."),
		partRanking(improving, "Improving "+lower, "None improved since the previous year."),
		partRanking(declining, "Declining "+lower, "None declined since the previous year."),
		&screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{Badges: []*screensv1.PageBadge{},
			Items: []*screensv1.PagePanelItem{{Kind: &screensv1.PagePanelItem_Text{Text: rules.Engine.Scope.RankingMethod + " " + rules.Engine.Scope.MoversMethod}}}}}},
	)
}
