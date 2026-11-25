package activities

import "testing"

// The reason is recommendation_service.explain's sentences, each said only
// when its component fired, in the existing words.
func TestARecommendationsReasonIsExplainsWords(t *testing.T) {
	need := rankedNeed{Intervention: "leadership", Label: "Leadership", Band: "Weak", Score: 4.0, Confidence: "moderate",
		Components: map[string]component{
			"peer_gap":    {measurable: true, zScore: -1.2, peerMean: 6.25, peerCount: 5},
			"trend":       {measurable: true, direction: "declining"},
			"persistence": {measurable: true, belowCount: 2, considered: 2},
		}}
	want := "Leadership scored 4.0 (Weak). It sits below the cluster average of 6.25 across 5 peer schools. " +
		"It has been declining across assessments. It has stayed weak in 2 of the last 2 assessments. " +
		"1 previous support activity has not moved it. Confidence is moderate — there are few assessments to compare."
	if got := explainNeed(need, 1); got != want {
		t.Errorf("\n got %q\nwant %q", got, want)
	}
	plain := rankedNeed{Intervention: "enrolment", Label: "Enrolment", Band: "Strong", Score: 8.5, Confidence: "high",
		Components: map[string]component{"peer_gap": {measurable: true, zScore: 0.4}}}
	if got := explainNeed(plain, 0); got != "Enrolment scored 8.5 (Strong). No support has been delivered against it yet." {
		t.Errorf("%q", got)
	}
	if got := explainNeed(plain, 3); got != "Enrolment scored 8.5 (Strong). 3 previous support activities have not moved it." {
		t.Errorf("%q", got)
	}
}
