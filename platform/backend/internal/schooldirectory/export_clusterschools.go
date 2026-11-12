package schooldirectory

// What a cluster's schools list (internal/clusterpage) reads beside the
// groups: build_ssa_score_summary's average and its tone.

// SSAAverage is build_ssa_score_summary's average_score (nil with no
// score) and average_tone.
func SSAAverage(scores []SSAScore) (*float64, string) {
	raw := make([]struct {
		intervention string
		score        *float64
	}, len(scores))
	for i, s := range scores {
		raw[i].intervention, raw[i].score = s.Intervention, s.Score
	}
	summary := summarize(raw)
	return summary.average, summary.tone
}
