package programmerollout

import (
	"context"
	"fmt"
	"net/url"
	"slices"
	"sort"
	"strconv"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
)

// openTone is the open recommendations tile's tone.
func openTone(open int) string {
	if open > 0 {
		return "warning"
	}
	return "info"
}

// courseRating is the course table's Regional Lead rating: "{rating} of 4
// ({observed})", or "Not observed".
func courseRating(f observationFold) string {
	if f.rating == nil {
		return "Not observed"
	}
	return fmt.Sprintf("%s of 4 (%d)", pyFloat(*f.rating), f.observed)
}

// observationsByDeliverer is the Trainings view's "Regional Lead
// observations": the team's own trainings first, then each partner, most
// open recommendations first, by name, the first thirty.
func observationsByDeliverer(obs []observation, n names, sc *scope) *screensv1.PageTable {
	type group struct {
		name string
		rows []observation
	}
	staff := []observation{}
	partners := []*group{}
	byPartner := map[string]*group{}
	for _, o := range obs {
		if o.partnerID == "" {
			staff = append(staff, o)
			continue
		}
		g, ok := byPartner[o.partnerID]
		if !ok {
			g = &group{name: "Training partner"}
			if name, found := n.partners[o.partnerID]; found {
				g.name = name
			}
			byPartner[o.partnerID] = g
			partners = append(partners, g)
		}
		g.rows = append(g.rows, o)
	}
	sort.SliceStable(partners, func(i, j int) bool {
		a, b := foldObservations(partners[i].rows), foldObservations(partners[j].rows)
		if a.open != b.open {
			return a.open > b.open
		}
		return partners[i].name < partners[j].name
	})
	if len(staff) > 0 {
		name := "Your officers"
		if sc.support {
			name = "The officers"
		}
		partners = append([]*group{{name: name, rows: staff}}, partners...)
	}
	t := &screensv1.PageTable{Columns: columns("Delivered by", "Observed", "Rating", "Biblical integration", "Open")}
	// `observations_by_deliverer|slice:":30"`: the first rows, no pager.
	for _, g := range partners[:min(len(partners), rules.Observations.DelivererRows)] {
		f := foldObservations(g.rows)
		t.Rows = append(t.Rows, &screensv1.PageRow{Cells: []*screensv1.PageCell{cell(g.name), cell(strconv.Itoa(f.observed)),
			cell(ofFour(f.rating)), cell(ofFour(f.biblical)), cell(strconv.Itoa(f.open))}})
	}
	if len(partners) == 0 {
		empty(t, "No observation has been shared with you this year.", "The Regional Lead's feedback on a training appears here once it is shared.")
	}
	return t
}

// recommendations is "Strengthen or replace recommendations": unanswered
// first, then the earliest observed, a page at a time. A pager carrying more
// than one other key hands on (ok false).
func (s *Service) recommendations(ctx context.Context, sc *scope, obs []observation, byID map[string]course, n names,
	query url.Values) ([]*screensv1.PageBlock, bool, error) {
	followed, err := s.followUps(ctx, sc, obs)
	if err != nil {
		return nil, true, err
	}
	asked := []observation{}
	for _, o := range obs {
		if slices.Contains(rules.Observations.ChangeRecommendations, o.recommendation) {
			asked = append(asked, o)
		}
	}
	sort.SliceStable(asked, func(i, j int) bool {
		if asked[i].isOpen != asked[j].isOpen {
			return asked[i].isOpen
		}
		return asked[i].heldOn.Before(asked[j].heldOn)
	})
	start, end, pager, ok := paged(query, "recommendation_page", len(asked))
	if !ok {
		return nil, false, nil
	}
	t := &screensv1.PageTable{Columns: columns("Training", "Delivered by", "Observed", "Recommendation", "Rating", "State", "Partner follow-up")}
	for _, o := range asked[start:end] {
		activity := training{}
		if o.activity != nil {
			activity = *o.activity
		}
		label, ok := rules.Observations.RecommendationLabels[o.recommendation]
		if !ok {
			label = o.recommendation
		}
		follow := "None recorded"
		if held, ok := followed[o.id]; ok {
			follow = "Partner engagement " + day(held, " Jan 2006")
		}
		t.Rows = append(t.Rows, &screensv1.PageRow{Cells: []*screensv1.PageCell{cell(observedTraining(o, byID)), cell(deliveredBy(sc, n, activity)),
			cell(day(o.heldOn, " Jan 2006")), cell(label), cell(ofFour(o.average)), cell(feedbackState(o, sc)), cell(follow)}})
	}
	if len(asked) == 0 {
		empty(t, "No training was recommended for strengthening or replacement this year.", "")
	}
	return withPager(t, pager), true, nil
}
