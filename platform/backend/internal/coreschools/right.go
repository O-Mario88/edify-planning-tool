package coreschools

import (
	"context"
	"fmt"
	"strconv"
	"strings"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
)

// attention is one school of get_recommendation_card's Attention Needed.
type attention struct {
	code, name                      string
	visitsMissing, trainingsMissing int
}

func plural(n int, word string) string {
	if n == 1 {
		return word
	}
	return word + "s"
}

// recommendationCard is get_recommendation_card over the filtered schools,
// for the operational year.
func (pg *page) recommendationCard(ctx context.Context) (list []attention, strategy string, next [][2]string, err error) {
	_, codes := ids(pg.all)
	rows, err := pg.db.Query(ctx, `
SELECT p.school_id, p.baseline_average IS NULL,
       (SELECT count(*) FROM core_activity_slot sl WHERE sl.core_plan_id = p.id AND sl.activity_type = 'visit' AND sl.status = ANY($3)),
       (SELECT count(*) FROM core_activity_slot sl WHERE sl.core_plan_id = p.id AND sl.activity_type = 'training' AND sl.status = ANY($3)),
       (SELECT s.name FROM school s WHERE s.school_id = p.school_id ORDER BY s.created_at DESC, s.id DESC LIMIT 1)
FROM core_plan p WHERE p.school_id = ANY($1) AND p.fy = $2 ORDER BY p.school_id, p.id`, codes, pg.operational, rules.RecommendationDone)
	if err != nil {
		return nil, "", nil, fmt.Errorf("coreschools: reading the attention list: %w", err)
	}
	unassessed := 0
	for rows.Next() {
		var a attention
		var noBaseline bool
		var visits, trainings int
		var name *string
		if err := rows.Scan(&a.code, &noBaseline, &visits, &trainings, &name); err != nil {
			rows.Close()
			return nil, "", nil, fmt.Errorf("coreschools: reading an attention row: %w", err)
		}
		if noBaseline {
			unassessed++
		}
		a.visitsMissing, a.trainingsMissing = 4-visits, 4-trainings
		if (a.visitsMissing > 0 || a.trainingsMissing > 0) && name != nil {
			a.name = *name
			list = append(list, a)
		}
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, "", nil, fmt.Errorf("coreschools: reading the attention list: %w", err)
	}
	var visits, trainings, visitSchools, trainingSchools int
	for _, a := range list {
		visits += a.visitsMissing
		trainings += a.trainingsMissing
		if a.visitsMissing != 0 {
			visitSchools++
		}
		if a.trainingsMissing != 0 {
			trainingSchools++
		}
	}
	parts := []string{}
	if unassessed > 0 {
		parts = append(parts, fmt.Sprintf("complete %d pending Core %s first", unassessed, plural(unassessed, "Assessment")))
	}
	switch {
	case visits >= trainings && visits != 0:
		parts = append(parts, fmt.Sprintf("close the %d missing visit %s", visits, plural(visits, "slot")))
		if trainings != 0 {
			parts = append(parts, fmt.Sprintf("then the %d training %s", trainings, plural(trainings, "slot")))
		}
	case trainings != 0:
		parts = append(parts, fmt.Sprintf("close the %d missing training %s", trainings, plural(trainings, "slot")))
	}
	strategy = "All core packages are on track — prepare Champion reviews and follow-up assessments."
	if len(parts) > 0 {
		strategy = "Focus on " + strings.Join(parts, ", ") + "."
	}
	if unassessed > 0 {
		next = append(next, [2]string{fmt.Sprintf("Review assessment results for %d core %s", unassessed, plural(unassessed, "school")),
			"/core-schools?ssa_status=required"})
	}
	if visitSchools > 0 {
		next = append(next, [2]string{fmt.Sprintf("Schedule pending visits for %d core %s", visitSchools, plural(visitSchools, "school")), "/core-schools"})
	}
	if trainingSchools > 0 {
		next = append(next, [2]string{fmt.Sprintf("Schedule pending trainings for %d core %s", trainingSchools, plural(trainingSchools, "school")),
			"/core-schools"})
	}
	return list, strategy, next, nil
}

// right is partials/core_schools/right_panel.html.
func (pg *page) right(ctx context.Context) ([]*screensv1.PageBlock, error) {
	list, strategy, next, err := pg.recommendationCard(ctx)
	if err != nil {
		return nil, err
	}
	text := func(s string) *screensv1.PagePanelItem {
		return &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Text{Text: s}}
	}
	links := func(ls ...*screensv1.PageLink) *screensv1.PagePanelItem {
		return &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Links{Links: &screensv1.PageLinks{Links: ls}}}
	}
	panel := func(title string, items ...*screensv1.PagePanelItem) *screensv1.PageBlock {
		return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{Title: title, Items: items}}}
	}
	attentionItems := []*screensv1.PagePanelItem{text(strconv.Itoa(len(list)))}
	for i, a := range list {
		if i == 5 {
			break
		}
		parts := []string{}
		if a.visitsMissing > 0 {
			parts = append(parts, fmt.Sprintf("%d visits", a.visitsMissing))
		}
		if a.visitsMissing > 0 && a.trainingsMissing > 0 {
			parts = append(parts, "and")
		}
		if a.trainingsMissing > 0 {
			parts = append(parts, fmt.Sprintf("%d trainings", a.trainingsMissing))
		}
		attentionItems = append(attentionItems, text(a.code+" · "+a.name), text(strings.Join(append(parts, "missing"), " ")))
	}
	if len(list) == 0 {
		attentionItems = append(attentionItems, text("All schools have full support planned."))
	}
	nextItems := []*screensv1.PagePanelItem{}
	nextLinks := []*screensv1.PageLink{}
	for i, n := range next {
		if i == 3 {
			break
		}
		nextLinks = append(nextLinks, &screensv1.PageLink{Text: n[0], Href: n[1]})
	}
	if len(nextLinks) == 0 {
		nextItems = append(nextItems, text("Every core package is fully planned — nothing waiting."))
	}
	nextLinks = append(nextLinks, &screensv1.PageLink{Text: "Go to My Plan →", Href: "/my-plan"})
	nextItems = append(nextItems, links(nextLinks...))
	return []*screensv1.PageBlock{
		panel("Core Planning Rules", links(
			&screensv1.PageLink{Text: "Every core school requires 4 Visits + 4 Trainings per FY."},
			&screensv1.PageLink{Text: "Core assessment scores guide the support and intervention plan."},
			&screensv1.PageLink{Text: "All scheduled visits and trainings automatically move to My Plan."},
			&screensv1.PageLink{Text: "View Full Guidelines", Href: "/help"})),
		panel("Attention Needed", attentionItems...),
		panel("Recommended Strategy", text(strategy),
			links(&screensv1.PageLink{Text: "View Strategy Playbook", Href: "/core-schools/strategy-playbook", Drawer: true})),
		panel("Next Action", nextItems...),
		panel("", &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Heading{Heading: "System Note"}},
			text("All core activities are synced to My Plan in real time.")),
	}, nil
}
