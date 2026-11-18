package schoolprofile

import (
	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/tablepager"
)

// The Schools tab of a profile of many schools (profile_intelligence.
// school_rows): every school of the scope, or the ones a figure counted,
// fifty a page.

// showsSchool is whether the school is in the list a figure opens
// (build's _flags).
func (pr *scopeProfile) showsSchool(x scopeSchool, show string) bool {
	score := pr.scores[x.id]
	need := rules.Engine.Requirements[x.kind]
	at := pr.schoolWork[x.id]
	switch show {
	case "no_ssa":
		return need.TakesSSA && score.current == nil
	case "unplanned":
		return !pr.planned[x.id]
	case "improved", "declined":
		return pr.verdicts[x.id].status == show
	case "awaiting_partner":
		return pr.handovers.awaitingSchools[x.id]
	case "no_training":
		return need.Trainings > 0 && (at == nil || at.trainings == 0)
	case "no_visit":
		return need.Visits > 0 && (at == nil || at.visits == 0)
	}
	return true
}

// schoolsBlocks is the Schools tab's table.
func (pr *scopeProfile) schoolsBlocks(l lens, show, subCounty string, d doors) []*screensv1.PageBlock {
	rows := []scopeSchool{}
	districts := map[string]bool{}
	for _, x := range pr.schools {
		if x.district != "" {
			districts[x.district] = true
		}
		if !pr.showsSchool(x, show) || (subCounty != "" && x.subCounty != subCounty) {
			continue
		}
		rows = append(rows, x)
	}
	manyDistricts := len(districts) > 1
	yearLabel, previousLabel := fyLabel(l.fy), fyLabel(previousFY(l.fy))
	t := &screensv1.PageTable{Title: rules.Engine.Scope.ShowLabels[show],
		Subtitle: intcomma(len(rows)) + " school" + plural(len(rows)) + " · " + yearLabel}
	if len(rows) == 0 {
		t.EmptyMessage = "No school is in this list."
		return []*screensv1.PageBlock{{Kind: &screensv1.PageBlock_Table{Table: t}}}
	}
	t.Columns = []*screensv1.PageColumn{{Label: "School ID"}, {Label: "School"}, {Label: "Type"}}
	if manyDistricts {
		t.Columns = append(t.Columns, &screensv1.PageColumn{Label: "District"})
	}
	t.Columns = append(t.Columns, &screensv1.PageColumn{Label: "Cluster"}, &screensv1.PageColumn{Label: "Enrolment", Numeric: true},
		&screensv1.PageColumn{Label: "Visits", Numeric: true}, &screensv1.PageColumn{Label: "Trainings", Numeric: true},
		&screensv1.PageColumn{Label: "Teachers Trained", Numeric: true}, &screensv1.PageColumn{Label: "Leaders Trained", Numeric: true},
		&screensv1.PageColumn{Label: previousLabel, Numeric: true}, &screensv1.PageColumn{Label: yearLabel, Numeric: true},
		&screensv1.PageColumn{Label: "Change", Numeric: true}, &screensv1.PageColumn{Label: "Status"})
	page := tablepager.Paginate(len(rows), tablePageSize, l.query, "schools_page")
	for _, x := range rows[page.Start:page.End] {
		year, verdict := pr.scores[x.id], pr.verdicts[x.id]
		w := pr.schoolWork[x.id]
		if w == nil {
			w = &placeWork{}
		}
		name := &screensv1.PageCell{Text: x.name}
		if d.Profile {
			name.Href = "/schools/" + x.id
		}
		cells := []*screensv1.PageCell{{Text: x.code}, name, {Text: label(rules.SchoolTypes, x.kind)}}
		if manyDistricts {
			district := &screensv1.PageCell{Text: "—"}
			if x.districtName != "" {
				district.Text = x.districtName
				if d.OpenDistrict {
					district.Href = "/districts/" + x.district
				}
			}
			cells = append(cells, district)
		}
		cluster := &screensv1.PageCell{Text: "—"}
		if name := pr.clusters[x.cluster]; name != "" {
			cluster.Text = name
			if d.OpenCluster {
				cluster.Href = "/clusters/" + x.cluster
			}
		}
		enrolment := "—"
		if x.hasEnrolment {
			enrolment = intcomma(x.enrolment)
		}
		changeCell := &screensv1.PageCell{Text: "—"}
		if verdict.delta != nil {
			changeCell = &screensv1.PageCell{Text: signedTwoPlaces(*verdict.delta), Tone: verdict.tone()}
		}
		cells = append(cells, cluster, &screensv1.PageCell{Text: enrolment},
			&screensv1.PageCell{Text: itoa(w.visitsDone) + " / " + itoa(w.visits)},
			&screensv1.PageCell{Text: itoa(w.trainingsDone) + " / " + itoa(w.trainings)},
			&screensv1.PageCell{Text: intcomma(w.teachers)}, &screensv1.PageCell{Text: intcomma(w.leaders)},
			&screensv1.PageCell{Text: score(year.previous)}, &screensv1.PageCell{Text: score(year.current), Strong: true},
			changeCell, &screensv1.PageCell{Text: verdict.label()})
		t.Rows = append(t.Rows, &screensv1.PageRow{Cells: cells})
	}
	if page.Pager != nil {
		t.Pager, t.Footnote = page.Pager, page.Pager.Summary
	}
	return []*screensv1.PageBlock{{Kind: &screensv1.PageBlock_Table{Table: t}}}
}
