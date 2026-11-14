package coreoversight

import "testing"

// A recommendation is one line as the feed reads the template's span: the
// intervention (score, band), " · ", the recommended training's name or "No
// mapped training[: why]", then its reason with no separator (the feed joins
// adjacent inline text); its state is the next item. Read on
// edify_gorn_dev's three recommendations (2026-11-13, backlog
// core-recommendations).
func TestARecommendationIsOneLineAsTheFeedReadsIt(t *testing.T) {
	score := "6.10"
	reason := "Financial Health scored 6.1 (Improving). It has stayed weak in 1 of the last 2 assessments."
	cases := []struct {
		name string
		rec  recommendationRow
		want string
	}{
		{"a mapped training", recommendationRow{Intervention: "financial_health", Score: &score, Band: "Improving", Reason: reason, Item: "Business Planning Support", HasItem: true},
			"Financial Health (6.1, Improving) · Business Planning Support" + reason},
		{"no training, with why", recommendationRow{Intervention: "financial_health", Score: &score, Band: "Improving", Reason: reason, Unmapped: "No course covers it"},
			"Financial Health (6.1, Improving) · No mapped training: No course covers it" + reason},
		{"no training, no why, no reason", recommendationRow{Intervention: "financial_health", Score: &score},
			"Financial Health (6.1) · No mapped training"},
		{"no score", recommendationRow{Intervention: "financial_health", Item: "Business Planning Support", HasItem: true},
			"Financial Health · Business Planning Support"},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			if got := recommendationText(c.rec); got != c.want {
				t.Fatalf("got  %q\nwant %q", got, c.want)
			}
		})
	}
}
